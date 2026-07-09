// Package gtfsrt is the GTFS-Realtime poller connector (ADR-0009 walking
// skeleton). It fetches a FeedMessage protobuf frame over HTTP on an
// interval, wraps the EXACT bytes received in a raw-record envelope, and
// produces to the matching raw.gtfs_rt.* topic keyed by record_id.
//
// The protobuf parse (github.com/MobilityData/gtfs-realtime-bindings,
// Apache-2.0; gtfs-realtime.proto per gtfs.org) is used ONLY to set
// parse_status ok/malformed. The raw bytes are what is enveloped and
// produced — never the reparsed form. Malformed frames are NEVER dropped:
// they are produced with parse_status "malformed" (fail loudly, Guardrail 7).
package gtfsrt

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"time"

	gtfs "github.com/MobilityData/gtfs-realtime-bindings/golang/gtfs"
	"google.golang.org/protobuf/proto"

	"github.com/headway-transit/headway/services/ingestion/internal/envelope"
	"github.com/headway-transit/headway/services/ingestion/internal/producer"
)

// Connector identity recorded on every envelope (contracts/topics.v0.md).
const (
	ConnectorName    = "headway-gtfs-rt"
	ConnectorVersion = "0.1.0"
	Source           = "gtfs_rt"
	ContentType      = "application/x-protobuf"
)

// FeedType selects which GTFS-RT feed a poller ingests.
type FeedType string

const (
	VehiclePositions FeedType = "vehicle_positions"
	TripUpdates      FeedType = "trip_updates"
	Alerts           FeedType = "alerts"
)

// Topic returns the raw.gtfs_rt.* topic for the feed type per
// contracts/topics.v0.md. Connectors must not invent topics.
func (ft FeedType) Topic() (string, error) {
	switch ft {
	case VehiclePositions, TripUpdates, Alerts:
		return "raw.gtfs_rt." + string(ft), nil
	default:
		return "", fmt.Errorf("gtfsrt: unknown feed type %q", ft)
	}
}

// Poller polls one GTFS-RT feed URL and produces raw-record envelopes.
type Poller struct {
	URL      string
	FeedType FeedType
	Interval time.Duration
	AgencyID string // optional

	HTTP     *http.Client
	Producer producer.Producer
	Log      *slog.Logger

	// Clock is injectable for tests; defaults to time.Now.
	Clock func() time.Time

	// lastRecordID is the content hash of the last frame produced, used to
	// skip identical consecutive frames (same bytes -> same record_id).
	// Dedupe is in-memory only; a restart re-produces the current frame,
	// which is safe because record_id makes re-ingest idempotent downstream.
	lastRecordID string
}

func (p *Poller) clock() time.Time {
	if p.Clock != nil {
		return p.Clock()
	}
	return time.Now()
}

func (p *Poller) httpClient() *http.Client {
	if p.HTTP != nil {
		return p.HTTP
	}
	return http.DefaultClient
}

// PollOnce fetches the feed once and produces an envelope unless the frame
// is byte-identical to the previous one. A fetch/transport error is
// returned (there are no bytes to land); a parse failure is NOT an error —
// the frame is enveloped as malformed and produced.
func (p *Poller) PollOnce(ctx context.Context) error {
	topic, err := p.FeedType.Topic()
	if err != nil {
		return err
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, p.URL, nil)
	if err != nil {
		return fmt.Errorf("gtfsrt %s: build request: %w", p.FeedType, err)
	}
	resp, err := p.httpClient().Do(req)
	if err != nil {
		return fmt.Errorf("gtfsrt %s: fetch %s: %w", p.FeedType, p.URL, err)
	}
	defer resp.Body.Close()
	fetchedAt := p.clock()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return fmt.Errorf("gtfsrt %s: read body: %w", p.FeedType, err)
	}
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("gtfsrt %s: fetch %s: HTTP %d", p.FeedType, p.URL, resp.StatusCode)
	}
	if len(body) == 0 {
		// No payload bytes were received, so there is nothing to land;
		// surface loudly rather than fabricating a record.
		return fmt.Errorf("gtfsrt %s: fetch %s: empty response body", p.FeedType, p.URL)
	}

	recordID := envelope.RecordID(body)
	if recordID == p.lastRecordID {
		p.Log.Info("duplicate frame skipped",
			"connector", ConnectorName, "feed_type", string(p.FeedType),
			"record_id", recordID, "topic", topic)
		return nil
	}

	// Parse strictly against the pinned gtfs-realtime bindings purely to
	// classify parse_status. The reparsed message is discarded; the raw
	// bytes are the record.
	parseStatus, parseError := envelope.ParseOK, ""
	var feed gtfs.FeedMessage
	if err := proto.Unmarshal(body, &feed); err != nil {
		parseStatus = envelope.ParseMalformed
		parseError = fmt.Sprintf("gtfs-realtime FeedMessage parse failed: %v", err)
	}

	env, err := envelope.New(body, envelope.Params{
		Source:           Source,
		Connector:        ConnectorName,
		ConnectorVersion: ConnectorVersion,
		AgencyID:         p.AgencyID,
		FeedURL:          p.URL,
		FetchedAt:        fetchedAt,
		ContentType:      ContentType,
		ParseStatus:      parseStatus,
		ParseError:       parseError,
	})
	if err != nil {
		return fmt.Errorf("gtfsrt %s: build envelope: %w", p.FeedType, err)
	}
	value, err := env.MarshalJSONBytes()
	if err != nil {
		return fmt.Errorf("gtfsrt %s: marshal envelope: %w", p.FeedType, err)
	}
	if err := p.Producer.Produce(ctx, topic, []byte(recordID), value); err != nil {
		return fmt.Errorf("gtfsrt %s: %w", p.FeedType, err)
	}
	p.lastRecordID = recordID

	if parseStatus == envelope.ParseMalformed {
		// DQ hook (walking skeleton): the malformed record is landed and
		// surfaced loudly; the Data Engineer's rule engine consumes these.
		p.Log.Error("malformed frame landed (never dropped)",
			"connector", ConnectorName, "feed_type", string(p.FeedType),
			"record_id", recordID, "topic", topic, "parse_error", parseError)
	} else {
		p.Log.Info("frame produced",
			"connector", ConnectorName, "feed_type", string(p.FeedType),
			"record_id", recordID, "topic", topic, "bytes", len(body))
	}
	return nil
}

// Run polls immediately, then on every Interval tick until ctx is done.
// Poll errors are logged loudly and do not stop the loop.
func (p *Poller) Run(ctx context.Context) error {
	if p.Interval <= 0 {
		return fmt.Errorf("gtfsrt %s: poll interval must be positive", p.FeedType)
	}
	ticker := time.NewTicker(p.Interval)
	defer ticker.Stop()
	for {
		if err := p.PollOnce(ctx); err != nil {
			if ctx.Err() != nil {
				return ctx.Err()
			}
			p.Log.Error("poll failed",
				"connector", ConnectorName, "feed_type", string(p.FeedType), "error", err)
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-ticker.C:
		}
	}
}
