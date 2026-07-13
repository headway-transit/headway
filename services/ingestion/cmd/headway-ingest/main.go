// Command headway-ingest runs the walking-skeleton ingestion connectors
// (ADR-0009): GTFS-RT pollers for vehicle positions / trip updates / alerts
// and a one-shot GTFS static fetch. Configuration is environment-only.
//
// Env:
//
//	KAFKA_BROKERS                  comma-separated broker list (required)
//	GTFS_RT_VEHICLE_POSITIONS_URL  poll this vehicle-positions feed (optional)
//	GTFS_RT_TRIP_UPDATES_URL       poll this trip-updates feed (optional)
//	GTFS_RT_ALERTS_URL             poll this alerts feed (optional)
//	GTFS_STATIC_URL                fetch this GTFS static zip once (optional)
//	GTFS_STATIC_MAX_BYTES          cap on the fetched zip size in bytes (optional, default 256 MiB)
//	TIDES_DROP_DIR                 scan this directory every POLL_INTERVAL for TIDES passenger_events*.csv (optional)
//	TIDES_SOURCE                   envelope source for TIDES drops — REQUIRED with TIDES_DROP_DIR,
//	                               no default (fail closed); simulator drops MUST set
//	                               "tides_simulated" (handoff 0005, Shared Constraint 2)
//	DR_DROP_DIR                    scan this directory every POLL_INTERVAL for demand_response_trips*.csv (optional, handoff 0013)
//	DR_SOURCE                      envelope source for DR drops — REQUIRED with DR_DROP_DIR,
//	                               no default (fail closed); simulator drops MUST set
//	                               "dr_simulated" (handoff 0013, Shared Constraint 2)
//	DROP_MAX_FILE_BYTES            cap on a dropped file's size in bytes (optional, default 256 MiB);
//	                               oversize files are moved to <drop dir>/rejected/ and logged
//	POLL_INTERVAL                  Go duration, default 30s (GTFS-RT polls AND drop-dir rescans;
//	                               also the file-drop partial-copy settle time)
//	AGENCY_ID                      optional envelope agency_id
//	S3_ENDPOINT                    MinIO/S3 endpoint host:port (required with GTFS_STATIC_URL, TIDES_DROP_DIR or DR_DROP_DIR)
//	S3_ACCESS_KEY, S3_SECRET_KEY   credentials (from the secret store; never logged)
//	S3_BUCKET                      target bucket, default headway-raw
//	S3_USE_SSL                     "true" to use TLS, default false (on-prem MinIO)
package main

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"

	"github.com/headway-transit/headway/services/ingestion/connectors/dr"
	"github.com/headway-transit/headway/services/ingestion/connectors/gtfsrt"
	"github.com/headway-transit/headway/services/ingestion/connectors/gtfsstatic"
	"github.com/headway-transit/headway/services/ingestion/connectors/tides"
	"github.com/headway-transit/headway/services/ingestion/internal/producer"
)

func main() {
	log := slog.New(slog.NewJSONHandler(os.Stderr, nil))
	slog.SetDefault(log)
	if err := run(log); err != nil {
		log.Error("fatal", "error", err)
		os.Exit(1)
	}
}

func run(log *slog.Logger) error {
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	brokersEnv := os.Getenv("KAFKA_BROKERS")
	if brokersEnv == "" {
		return fmt.Errorf("KAFKA_BROKERS is required")
	}
	brokers := strings.Split(brokersEnv, ",")

	interval := 30 * time.Second
	if v := os.Getenv("POLL_INTERVAL"); v != "" {
		d, err := time.ParseDuration(v)
		if err != nil {
			return fmt.Errorf("POLL_INTERVAL: %w", err)
		}
		interval = d
	}
	agencyID := os.Getenv("AGENCY_ID")

	kafka, err := producer.NewKafka(brokers)
	if err != nil {
		return err
	}
	defer kafka.Close()

	httpClient := &http.Client{Timeout: 30 * time.Second}

	rtFeeds := []struct {
		env string
		ft  gtfsrt.FeedType
	}{
		{"GTFS_RT_VEHICLE_POSITIONS_URL", gtfsrt.VehiclePositions},
		{"GTFS_RT_TRIP_UPDATES_URL", gtfsrt.TripUpdates},
		{"GTFS_RT_ALERTS_URL", gtfsrt.Alerts},
	}

	var wg sync.WaitGroup
	started := 0
	for _, feed := range rtFeeds {
		url := os.Getenv(feed.env)
		if url == "" {
			continue
		}
		poller := &gtfsrt.Poller{
			URL:      url,
			FeedType: feed.ft,
			Interval: interval,
			AgencyID: agencyID,
			HTTP:     httpClient,
			Producer: kafka,
			Log:      log,
		}
		started++
		wg.Add(1)
		go func() {
			defer wg.Done()
			log.Info("gtfs-rt poller started",
				"feed_type", string(poller.FeedType), "url", poller.URL, "interval", interval.String())
			if err := poller.Run(ctx); err != nil && ctx.Err() == nil {
				log.Error("gtfs-rt poller stopped", "feed_type", string(poller.FeedType), "error", err)
			}
		}()
	}

	if staticURL := os.Getenv("GTFS_STATIC_URL"); staticURL != "" {
		client, bucket, err := minioFromEnv("GTFS_STATIC_URL")
		if err != nil {
			return err
		}
		staticMaxBytes, err := bytesFromEnv("GTFS_STATIC_MAX_BYTES")
		if err != nil {
			return err
		}
		store := gtfsstatic.NewMinioStore(client, bucket)
		fetcher := &gtfsstatic.Fetcher{
			URL:      staticURL,
			AgencyID: agencyID,
			MaxBytes: staticMaxBytes,
			HTTP:     &http.Client{Timeout: 5 * time.Minute},
			Store:    store,
			Producer: kafka,
			Log:      log,
		}
		started++
		wg.Add(1)
		go func() {
			defer wg.Done()
			log.Info("gtfs static fetch started", "url", staticURL)
			if err := fetcher.FetchOnce(ctx); err != nil && ctx.Err() == nil {
				log.Error("gtfs static fetch failed", "error", err)
			}
		}()
	}

	dropMaxBytes, err := bytesFromEnv("DROP_MAX_FILE_BYTES")
	if err != nil {
		return err
	}

	if dropDir := os.Getenv("TIDES_DROP_DIR"); dropDir != "" {
		// Fail closed: the source label is what makes simulated data
		// permanently distinguishable in provenance (Shared Constraint 2),
		// so it is never guessed or defaulted.
		source := strings.TrimSpace(os.Getenv("TIDES_SOURCE"))
		if source == "" {
			return fmt.Errorf("TIDES_DROP_DIR is set but TIDES_SOURCE is not. " +
				"Headway needs to know what this drop directory carries and " +
				"refuses to guess: set TIDES_SOURCE=tides (or your vendor's " +
				"label) for a real agency feed, or TIDES_SOURCE=tides_simulated " +
				"for simulator output — simulated data must never be recorded " +
				"as real (Shared Constraint 2: full provenance)")
		}
		client, bucket, err := minioFromEnv("TIDES_DROP_DIR")
		if err != nil {
			return err
		}
		scanner := &tides.Scanner{
			Dir:          dropDir,
			Source:       source,
			AgencyID:     agencyID,
			MaxFileBytes: dropMaxBytes,
			Interval:     interval,
			Store:        tides.NewMinioStore(client, bucket),
			Producer:     kafka,
			Log:          log,
		}
		started++
		wg.Add(1)
		go func() {
			defer wg.Done()
			log.Info("tides drop-dir scanner started",
				"dir", dropDir, "source", source, "interval", interval.String())
			if err := scanner.Run(ctx); err != nil && ctx.Err() == nil {
				log.Error("tides drop-dir scanner stopped", "error", err)
			}
		}()
	}

	if dropDir := os.Getenv("DR_DROP_DIR"); dropDir != "" {
		// Fail closed: same provenance rule as TIDES_SOURCE above.
		source := strings.TrimSpace(os.Getenv("DR_SOURCE"))
		if source == "" {
			return fmt.Errorf("DR_DROP_DIR is set but DR_SOURCE is not. " +
				"Headway needs to know what this drop directory carries and " +
				"refuses to guess: set DR_SOURCE=dr (or your vendor's label) " +
				"for a real dispatch feed, or DR_SOURCE=dr_simulated for " +
				"simulator output — simulated data must never be recorded " +
				"as real (Shared Constraint 2: full provenance)")
		}
		client, bucket, err := minioFromEnv("DR_DROP_DIR")
		if err != nil {
			return err
		}
		scanner := &dr.Scanner{
			Dir:          dropDir,
			Source:       source,
			AgencyID:     agencyID,
			MaxFileBytes: dropMaxBytes,
			Interval:     interval,
			Store:        dr.NewMinioStore(client, bucket),
			Producer:     kafka,
			Log:          log,
		}
		started++
		wg.Add(1)
		go func() {
			defer wg.Done()
			log.Info("dr drop-dir scanner started",
				"dir", dropDir, "source", source, "interval", interval.String())
			if err := scanner.Run(ctx); err != nil && ctx.Err() == nil {
				log.Error("dr drop-dir scanner stopped", "error", err)
			}
		}()
	}

	if started == 0 {
		return fmt.Errorf("no connectors configured: set GTFS_RT_*_URL, GTFS_STATIC_URL, TIDES_DROP_DIR, and/or DR_DROP_DIR")
	}

	log.Info("headway-ingest running", "connectors", started)
	<-ctx.Done()
	log.Info("shutdown signal received, stopping connectors")
	wg.Wait()
	log.Info("headway-ingest stopped cleanly")
	return nil
}

// bytesFromEnv parses an optional byte-count env var (plain integer bytes).
// Returns 0 (meaning "use the connector's default cap") when unset.
func bytesFromEnv(name string) (int64, error) {
	v := os.Getenv(name)
	if v == "" {
		return 0, nil
	}
	n, err := strconv.ParseInt(v, 10, 64)
	if err != nil || n <= 0 {
		return 0, fmt.Errorf("%s must be a positive integer byte count, got %q", name, v)
	}
	return n, nil
}

// minioFromEnv builds the shared S3/MinIO client and target bucket from the
// environment; requiredBy names the connector env var that made it needed.
func minioFromEnv(requiredBy string) (*minio.Client, string, error) {
	endpoint := os.Getenv("S3_ENDPOINT")
	if endpoint == "" {
		return nil, "", fmt.Errorf("S3_ENDPOINT is required when %s is set", requiredBy)
	}
	accessKey := os.Getenv("S3_ACCESS_KEY")
	secretKey := os.Getenv("S3_SECRET_KEY")
	if accessKey == "" || secretKey == "" {
		return nil, "", fmt.Errorf("S3_ACCESS_KEY and S3_SECRET_KEY are required when %s is set", requiredBy)
	}
	bucket := os.Getenv("S3_BUCKET")
	if bucket == "" {
		bucket = "headway-raw"
	}
	useSSL := strings.EqualFold(os.Getenv("S3_USE_SSL"), "true")

	client, err := minio.New(endpoint, &minio.Options{
		Creds:  credentials.NewStaticV4(accessKey, secretKey, ""),
		Secure: useSSL,
	})
	if err != nil {
		return nil, "", fmt.Errorf("minio client: %w", err)
	}
	return client, bucket, nil
}
