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
//	VENDOR_DROP_DIR                scan this directory every POLL_INTERVAL for vendor-export *.csv files (optional, handoff 0015)
//	VENDOR_SOURCE                  envelope source for vendor drops — REQUIRED with VENDOR_DROP_DIR,
//	                               no default (fail closed). Must be the REGISTERED adapter
//	                               mapping-spec label `<vendor>_<product>` (adapters/), or
//	                               `<vendor>_<product>_simulated` for synthetic data; the
//	                               transform runtime refuses unregistered labels
//	DROP_MAX_FILE_BYTES            cap on a dropped file's size in bytes (optional, default 256 MiB);
//	                               oversize files are moved to <drop dir>/rejected/ and logged
//	SAMSARA_ENABLED                "true" turns on the Samsara fleet-telematics poller (handoff 0028).
//	                               The TOKEN deliberately does NOT act as the on-switch: a missing
//	                               token must be a loud refusal, not a silently skipped connector
//	SAMSARA_API_TOKEN              bearer API token — REQUIRED with SAMSARA_ENABLED, from the secret
//	                               store, NEVER logged and never written into a record. Needs only the
//	                               read-only "Read Vehicle Statistics" scope (Vehicles category)
//	SAMSARA_SOURCE                 envelope source for telematics records — REQUIRED with
//	                               SAMSARA_ENABLED, no default (fail closed). Must be a REGISTERED
//	                               label from contracts/fleet-telematics.v0.schema.json: "samsara"
//	                               for a real account, "samsara_simulated" for anything synthetic
//	SAMSARA_SERVICE_DAY_TZ         the agency's IANA service-day timezone (e.g. America/New_York) —
//	                               REQUIRED with SAMSARA_ENABLED, never guessed. The transform must
//	                               be given the SAME zone (HEADWAY_TELEMATICS_SERVICE_DAY_TZ)
//	SAMSARA_BASE_URL               API root (optional, default https://api.samsara.com; the vendor
//	                               spec also lists https://api.eu.samsara.com and https://api.ca.samsara.com)
//	SAMSARA_VEHICLE_IDS            comma-separated vendor vehicle ids to restrict the poll to (optional)
//	SAMSARA_TAG_IDS                comma-separated vendor tag ids (optional; a tag-scoped token plus
//	                               a tag filter is the least-privilege way to poll only the vanpool)
//	SAMSARA_PARENT_TAG_IDS         comma-separated vendor parent tag ids (optional)
//	SAMSARA_ENGINE_TIME            "false" to skip the engine-runtime request (optional, default true).
//	                               Engine RUNTIME is not duty hours and not revenue hours
//	SAMSARA_LAG_DAYS               how many days back the newest polled service day sits (optional,
//	                               default 1 — a service day is not complete until it ends)
//	SAMSARA_BACKFILL_DAYS          how many consecutive service days each cycle re-polls to catch
//	                               late-arriving samples (optional, default 3; re-polls are idempotent)
//	SAMSARA_POLL_INTERVAL          Go duration between poll cycles (optional, default 6h). Deliberately
//	                               separate from POLL_INTERVAL: a daily-window API is not a 30s feed
//	SAMSARA_MAX_PAGE_BYTES         cap on one API response page in bytes (optional, default 64 MiB)
//	SQLSOURCE_ENABLED              "true" turns on the generic SQL-source connector (handoff 0033):
//	                               keyset-polls an AGENCY-SUPPLIED view on the agency's own database
//	                               server and lands each batch through the vendor-file pipeline.
//	                               The DSN deliberately does NOT act as the on-switch: a missing DSN
//	                               must be a loud refusal, not a silently skipped connector
//	SQLSOURCE_DSN                  read-only connection string — REQUIRED with SQLSOURCE_ENABLED,
//	                               from the secret store, NEVER logged (including in errors), e.g.
//	                               sqlserver://headway_ro:pass@host:1433?database=WAREHOUSE&encrypt=true
//	SQLSOURCE_DRIVER               optional, default "sqlserver" — the only driver v0 supports;
//	                               anything else is refused (Postgres/Oracle are future increments)
//	SQLSOURCE_VIEW                 the view the agency's DBA created for Headway (e.g.
//	                               dbo.vw_headway_apc) — REQUIRED; vendor table names never
//	                               enter Headway configuration conventions
//	SQLSOURCE_COLUMNS              comma-separated ordered column list — REQUIRED; must be EXACTLY
//	                               the registered adapter's declared positional columns in the
//	                               adapter's order (mapping.v0.yaml source_format.csv.columns);
//	                               "*" is refused (ADR-0013 minimization)
//	SQLSOURCE_CURSOR_COLUMN        monotonic INTEGER keyset column, one of SQLSOURCE_COLUMNS —
//	                               REQUIRED (e.g. the view's warehouse key)
//	SQLSOURCE_ADAPTER_LABEL        envelope source — REQUIRED, no default (fail closed). Must be
//	                               the REGISTERED adapter mapping-spec label `<vendor>_<product>`
//	                               (adapters/), or `<vendor>_<product>_simulated` for synthetic data
//	SQLSOURCE_STATE_DIR            writable directory persisting the high-water mark — REQUIRED
//	SQLSOURCE_POLL_INTERVAL        Go duration between poll cycles (optional, default 5m)
//	SQLSOURCE_BATCH_MAX_ROWS       cap on one rendered batch (optional, default 5000)
//	SQLSOURCE_QUERY_TIMEOUT        client-side statement timeout (optional, default 60s)
//	POLL_INTERVAL                  Go duration, default 30s (GTFS-RT polls AND drop-dir rescans;
//	                               also the file-drop partial-copy settle time)
//	AGENCY_ID                      optional envelope agency_id
//	S3_ENDPOINT                    MinIO/S3 endpoint host:port (required with ANY connector that
//	                               lands payloads — GTFS_RT_*_URL, GTFS_STATIC_URL, TIDES_DROP_DIR,
//	                               DR_DROP_DIR, VENDOR_DROP_DIR, SAMSARA_ENABLED, SQLSOURCE_ENABLED.
//	                               GTFS-RT frames land at raw/gtfs_rt/<record_id>.pb BEFORE the
//	                               envelope is produced — handoff 0036)
//	S3_ACCESS_KEY, S3_SECRET_KEY   credentials (from the secret store; never logged)
//	S3_BUCKET                      target bucket, default headway-raw
//	S3_USE_SSL                     "true" to use TLS, default false (on-prem MinIO)
package main

import (
	"context"
	"database/sql"
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
	"github.com/headway-transit/headway/services/ingestion/connectors/samsara"
	"github.com/headway-transit/headway/services/ingestion/connectors/sqlsource"
	"github.com/headway-transit/headway/services/ingestion/connectors/tides"
	"github.com/headway-transit/headway/services/ingestion/connectors/vendorfile"
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
	// One store shared by all GTFS-RT pollers, built only when a feed is
	// configured. S3_* is now REQUIRED with any GTFS_RT_*_URL (handoff
	// 0036): frames land in the object store before producing, like every
	// other connector — the broker is the wire, not the system of record.
	var rtStore *gtfsrt.MinioStore
	for _, feed := range rtFeeds {
		url := os.Getenv(feed.env)
		if url == "" {
			continue
		}
		if rtStore == nil {
			client, bucket, err := minioFromEnv(feed.env)
			if err != nil {
				return err
			}
			rtStore = gtfsrt.NewMinioStore(client, bucket)
		}
		poller := &gtfsrt.Poller{
			URL:      url,
			FeedType: feed.ft,
			Interval: interval,
			AgencyID: agencyID,
			HTTP:     httpClient,
			Store:    rtStore,
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

	if dropDir := os.Getenv("VENDOR_DROP_DIR"); dropDir != "" {
		// Fail closed: the label is the adapter-registry key AND the
		// provenance rule from TIDES_SOURCE/DR_SOURCE above.
		source := strings.TrimSpace(os.Getenv("VENDOR_SOURCE"))
		if source == "" {
			return fmt.Errorf("VENDOR_DROP_DIR is set but VENDOR_SOURCE is not. " +
				"Headway needs to know which REGISTERED adapter this drop " +
				"directory carries and refuses to guess: set VENDOR_SOURCE to " +
				"the mapping-spec label `<vendor>_<product>` (see adapters/), " +
				"or `<vendor>_<product>_simulated` for synthetic data — an " +
				"unlabeled feed could be mapped by the wrong spec or record " +
				"simulated data as real (Shared Constraint 2: full provenance)")
		}
		client, bucket, err := minioFromEnv("VENDOR_DROP_DIR")
		if err != nil {
			return err
		}
		scanner := &vendorfile.Scanner{
			Dir:          dropDir,
			Source:       source,
			AgencyID:     agencyID,
			MaxFileBytes: dropMaxBytes,
			Interval:     interval,
			Store:        vendorfile.NewMinioStore(client, bucket),
			Producer:     kafka,
			Log:          log,
		}
		started++
		wg.Add(1)
		go func() {
			defer wg.Done()
			log.Info("vendor drop-dir scanner started",
				"dir", dropDir, "source", source, "interval", interval.String())
			if err := scanner.Run(ctx); err != nil && ctx.Err() == nil {
				log.Error("vendor drop-dir scanner stopped", "error", err)
			}
		}()
	}

	// Samsara fleet telematics (handoff 0028). SAMSARA_ENABLED is the
	// on-switch rather than the token, precisely so that a missing token is a
	// loud refusal instead of a connector that quietly never runs.
	if strings.EqualFold(os.Getenv("SAMSARA_ENABLED"), "true") {
		poller, err := samsaraFromEnv(agencyID, kafka, log)
		if err != nil {
			return err
		}
		started++
		wg.Add(1)
		go func() {
			defer wg.Done()
			log.Info("samsara telematics poller started",
				"source", poller.Source, "timezone", poller.ServiceDay.String(),
				"interval", poller.Interval.String(),
				"lag_days", poller.LagDays, "backfill_days", poller.BackfillDays,
				"engine_time", poller.IncludeEngineTime)
			if err := poller.Run(ctx); err != nil && ctx.Err() == nil {
				log.Error("samsara telematics poller stopped", "error", err)
			}
		}()
	}

	// Generic SQL-source connector (handoff 0033). SQLSOURCE_ENABLED is the
	// on-switch rather than the DSN, for the same reason as SAMSARA_ENABLED:
	// a missing secret must be a loud refusal, never a connector that
	// quietly never runs.
	if strings.EqualFold(os.Getenv("SQLSOURCE_ENABLED"), "true") {
		poller, db, err := sqlsourceFromEnv(agencyID, kafka, log)
		if err != nil {
			return err
		}
		defer db.Close()
		started++
		wg.Add(1)
		go func() {
			defer wg.Done()
			log.Info("sql-source poller started",
				"view", poller.View, "source", poller.Source,
				"cursor_column", poller.CursorColumn,
				"columns", len(poller.Columns),
				"interval", poller.Interval.String())
			if err := poller.Run(ctx); err != nil && ctx.Err() == nil {
				log.Error("sql-source poller stopped", "error", err)
			}
		}()
	}

	if started == 0 {
		return fmt.Errorf("no connectors configured: set GTFS_RT_*_URL, GTFS_STATIC_URL, TIDES_DROP_DIR, DR_DROP_DIR, VENDOR_DROP_DIR, SAMSARA_ENABLED=true, and/or SQLSOURCE_ENABLED=true")
	}

	log.Info("headway-ingest running", "connectors", started)
	<-ctx.Done()
	log.Info("shutdown signal received, stopping connectors")
	wg.Wait()
	log.Info("headway-ingest stopped cleanly")
	return nil
}

// samsaraFromEnv builds the Samsara telematics poller. Every value Headway
// must never guess (token, source label, service-day timezone) is REQUIRED;
// the poller's own Check() produces the plain-language refusal so the
// wording lives next to the rules it enforces.
func samsaraFromEnv(agencyID string, kafka producer.Producer, log *slog.Logger) (*samsara.Poller, error) {
	client, bucket, err := minioFromEnv("SAMSARA_ENABLED")
	if err != nil {
		return nil, err
	}

	poller := &samsara.Poller{
		BaseURL:      strings.TrimSpace(os.Getenv("SAMSARA_BASE_URL")),
		Token:        os.Getenv("SAMSARA_API_TOKEN"),
		Source:       strings.TrimSpace(os.Getenv("SAMSARA_SOURCE")),
		VehicleIDs:   csvFromEnv("SAMSARA_VEHICLE_IDS"),
		TagIDs:       csvFromEnv("SAMSARA_TAG_IDS"),
		ParentTagIDs: csvFromEnv("SAMSARA_PARENT_TAG_IDS"),
		AgencyID:     agencyID,
		Store:        samsara.NewMinioStore(client, bucket),
		Producer:     kafka,
		Log:          log,
	}

	// The service-day timezone is loaded here (not in Check) so an
	// unresolvable zone name is distinguishable from an absent one.
	if tz := strings.TrimSpace(os.Getenv("SAMSARA_SERVICE_DAY_TZ")); tz != "" {
		loc, err := time.LoadLocation(tz)
		if err != nil {
			return nil, fmt.Errorf(
				"SAMSARA_SERVICE_DAY_TZ=%q is not a resolvable IANA timezone "+
					"(%w). Use a zone name like America/New_York; a service "+
					"date is a local wall date and is never guessed", tz, err)
		}
		poller.ServiceDay = loc
	}

	poller.IncludeEngineTime = true
	if v := strings.TrimSpace(os.Getenv("SAMSARA_ENGINE_TIME")); v != "" {
		if strings.EqualFold(v, "false") {
			poller.IncludeEngineTime = false
		} else if !strings.EqualFold(v, "true") {
			return nil, fmt.Errorf("SAMSARA_ENGINE_TIME must be true or false, got %q", v)
		}
	}

	if poller.LagDays, err = intFromEnv("SAMSARA_LAG_DAYS"); err != nil {
		return nil, err
	}
	if poller.BackfillDays, err = intFromEnv("SAMSARA_BACKFILL_DAYS"); err != nil {
		return nil, err
	}
	if poller.MaxPageBytes, err = bytesFromEnv("SAMSARA_MAX_PAGE_BYTES"); err != nil {
		return nil, err
	}
	poller.Interval = samsara.DefaultInterval
	if v := os.Getenv("SAMSARA_POLL_INTERVAL"); v != "" {
		d, err := time.ParseDuration(v)
		if err != nil {
			return nil, fmt.Errorf("SAMSARA_POLL_INTERVAL: %w", err)
		}
		poller.Interval = d
	}
	if poller.LagDays == 0 {
		poller.LagDays = samsara.DefaultLagDays
	}
	if poller.BackfillDays == 0 {
		poller.BackfillDays = samsara.DefaultBackfillDays
	}

	// Refuse now, at startup, rather than on the first poll.
	if err := poller.Check(); err != nil {
		return nil, err
	}
	return poller, nil
}

// sqlsourceFromEnv builds the generic SQL-source poller (handoff 0033).
// Everything Headway must never guess (DSN, view, column order, cursor,
// adapter label, state dir) is REQUIRED; the poller's Check() produces the
// plain-language refusals so the wording lives next to the rules it
// enforces. The DSN is read here and handed straight to the driver — the
// poller itself never holds it, so it can never be logged.
func sqlsourceFromEnv(agencyID string, kafka producer.Producer, log *slog.Logger) (*sqlsource.Poller, *sql.DB, error) {
	if drv := strings.TrimSpace(os.Getenv("SQLSOURCE_DRIVER")); drv != "" && !strings.EqualFold(drv, sqlsource.DriverSQLServer) {
		return nil, nil, fmt.Errorf(
			"SQLSOURCE_DRIVER=%q is not supported: v0 speaks to SQL Server "+
				"only (driver %q). Postgres/Oracle drivers are planned "+
				"increments on the same config shape — this refusal is the "+
				"honest alternative to pretending", drv, sqlsource.DriverSQLServer)
	}
	client, bucket, err := minioFromEnv("SQLSOURCE_ENABLED")
	if err != nil {
		return nil, nil, err
	}
	db, err := sqlsource.OpenDB(os.Getenv("SQLSOURCE_DSN"))
	if err != nil {
		return nil, nil, err
	}

	poller := &sqlsource.Poller{
		DB:           db,
		View:         strings.TrimSpace(os.Getenv("SQLSOURCE_VIEW")),
		Columns:      csvFromEnv("SQLSOURCE_COLUMNS"),
		CursorColumn: strings.TrimSpace(os.Getenv("SQLSOURCE_CURSOR_COLUMN")),
		Source:       strings.TrimSpace(os.Getenv("SQLSOURCE_ADAPTER_LABEL")),
		StateDir:     strings.TrimSpace(os.Getenv("SQLSOURCE_STATE_DIR")),
		AgencyID:     agencyID,
		Store:        vendorfile.NewMinioStore(client, bucket),
		Producer:     kafka,
		Log:          log,
	}
	if poller.BatchMaxRows, err = intFromEnv("SQLSOURCE_BATCH_MAX_ROWS"); err != nil {
		return nil, nil, err
	}
	poller.Interval = sqlsource.DefaultPollInterval
	if v := os.Getenv("SQLSOURCE_POLL_INTERVAL"); v != "" {
		d, err := time.ParseDuration(v)
		if err != nil {
			return nil, nil, fmt.Errorf("SQLSOURCE_POLL_INTERVAL: %w", err)
		}
		poller.Interval = d
	}
	if v := os.Getenv("SQLSOURCE_QUERY_TIMEOUT"); v != "" {
		d, err := time.ParseDuration(v)
		if err != nil {
			return nil, nil, fmt.Errorf("SQLSOURCE_QUERY_TIMEOUT: %w", err)
		}
		poller.QueryTimeout = d
	}

	// Refuse now, at startup, rather than on the first poll.
	if err := poller.Check(); err != nil {
		return nil, nil, err
	}
	return poller, db, nil
}

// csvFromEnv splits an optional comma-separated env var, trimming blanks.
func csvFromEnv(name string) []string {
	raw := strings.TrimSpace(os.Getenv(name))
	if raw == "" {
		return nil
	}
	var out []string
	for _, part := range strings.Split(raw, ",") {
		if trimmed := strings.TrimSpace(part); trimmed != "" {
			out = append(out, trimmed)
		}
	}
	return out
}

// intFromEnv parses an optional positive-integer env var; 0 means unset.
func intFromEnv(name string) (int, error) {
	v := strings.TrimSpace(os.Getenv(name))
	if v == "" {
		return 0, nil
	}
	n, err := strconv.Atoi(v)
	if err != nil || n <= 0 {
		return 0, fmt.Errorf("%s must be a positive integer, got %q", name, v)
	}
	return n, nil
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
