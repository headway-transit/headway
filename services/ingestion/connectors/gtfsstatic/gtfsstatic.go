// Package gtfsstatic is the GTFS static feed connector (ADR-0009 walking
// skeleton). It fetches the complete GTFS zip from a URL, lands the EXACT
// bytes in the object store at a content-addressed key, and produces an
// object_ref raw-record envelope to raw.gtfs_static.feed keyed by record_id.
//
// The zip sanity check (archive/zip open; GTFS file-set semantics per
// gtfs.org are the Data Engineer's concern, not ingestion's) is used ONLY
// to set parse_status. A broken zip is still landed and produced as
// malformed — never dropped (Guardrail 7).
package gtfsstatic

import (
	"archive/zip"
	"bytes"
	"context"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"time"

	"github.com/headway-transit/headway/services/ingestion/internal/envelope"
	"github.com/headway-transit/headway/services/ingestion/internal/producer"
)

// Connector identity recorded on every envelope (contracts/topics.v0.md).
const (
	ConnectorName    = "headway-gtfs-static"
	ConnectorVersion = "0.1.1"
	Source           = "gtfs_static"
	ContentType      = "application/zip"
	Topic            = "raw.gtfs_static.feed"

	// DefaultMaxFetchBytes caps how much of the HTTP response body is
	// buffered (2026-07-13 hardening pass — an unbounded read is a DoS
	// vector). Generous: national-scale GTFS zips are tens of MiB.
	DefaultMaxFetchBytes = 256 << 20 // 256 MiB
)

// ObjectKey returns the content-addressed object-store key for a feed zip.
func ObjectKey(recordID string) string {
	return fmt.Sprintf("raw/gtfs_static/%s.zip", recordID)
}

// Fetcher fetches one GTFS static zip, lands it, and produces its envelope.
type Fetcher struct {
	URL      string
	AgencyID string // optional

	// MaxBytes caps the response body size; <= 0 means
	// DefaultMaxFetchBytes. An oversize response is a loud refusal
	// (error + log), never a truncated record.
	MaxBytes int64

	HTTP     *http.Client
	Store    ObjectStore
	Producer producer.Producer
	Log      *slog.Logger

	// Clock is injectable for tests; defaults to time.Now.
	Clock func() time.Time
}

func (f *Fetcher) clock() time.Time {
	if f.Clock != nil {
		return f.Clock()
	}
	return time.Now()
}

func (f *Fetcher) httpClient() *http.Client {
	if f.HTTP != nil {
		return f.HTTP
	}
	return http.DefaultClient
}

// FetchOnce downloads the feed, writes the raw bytes to the object store at
// raw/gtfs_static/<record_id>.zip, then produces the object_ref envelope.
// Landing precedes producing: a consumer must never see an envelope whose
// object does not exist. A zip open failure sets parse_status malformed but
// the bytes are still landed and produced.
func (f *Fetcher) FetchOnce(ctx context.Context) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, f.URL, nil)
	if err != nil {
		return fmt.Errorf("gtfsstatic: build request: %w", err)
	}
	resp, err := f.httpClient().Do(req)
	if err != nil {
		return fmt.Errorf("gtfsstatic: fetch %s: %w", f.URL, err)
	}
	defer resp.Body.Close()
	fetchedAt := f.clock()

	// Cap the buffered body (hardening pass 2026-07-13): read at most
	// limit+1 bytes so an over-limit response is detected and refused
	// loudly instead of buffering without bound (DoS) or silently
	// truncating (a partial feed must never become a record).
	limit := f.MaxBytes
	if limit <= 0 {
		limit = DefaultMaxFetchBytes
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, limit+1))
	if err != nil {
		return fmt.Errorf("gtfsstatic: read body: %w", err)
	}
	if int64(len(body)) > limit {
		return fmt.Errorf(
			"gtfsstatic: fetch %s: response exceeds the %d-byte limit "+
				"(GTFS_STATIC_MAX_BYTES); refusing to buffer an unbounded "+
				"body — raise the limit explicitly if this feed is really "+
				"that large", f.URL, limit)
	}
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("gtfsstatic: fetch %s: HTTP %d", f.URL, resp.StatusCode)
	}
	if len(body) == 0 {
		return fmt.Errorf("gtfsstatic: fetch %s: empty response body", f.URL)
	}

	recordID := envelope.RecordID(body)
	key := ObjectKey(recordID)

	// Sanity check ONLY to classify parse_status; the raw bytes are the
	// record regardless of the outcome.
	parseStatus, parseError := envelope.ParseOK, ""
	if _, err := zip.NewReader(bytes.NewReader(body), int64(len(body))); err != nil {
		parseStatus = envelope.ParseMalformed
		parseError = fmt.Sprintf("gtfs static zip open failed: %v", err)
	}

	if err := f.Store.Put(ctx, key, body); err != nil {
		return fmt.Errorf("gtfsstatic: land %s: %w", key, err)
	}

	env, err := envelope.NewObjectRef(body, key, envelope.Params{
		Source:           Source,
		Connector:        ConnectorName,
		ConnectorVersion: ConnectorVersion,
		AgencyID:         f.AgencyID,
		FeedURL:          f.URL,
		FetchedAt:        fetchedAt,
		ContentType:      ContentType,
		ParseStatus:      parseStatus,
		ParseError:       parseError,
	})
	if err != nil {
		return fmt.Errorf("gtfsstatic: build envelope: %w", err)
	}
	value, err := env.MarshalJSONBytes()
	if err != nil {
		return fmt.Errorf("gtfsstatic: marshal envelope: %w", err)
	}
	if err := f.Producer.Produce(ctx, Topic, []byte(recordID), value); err != nil {
		return fmt.Errorf("gtfsstatic: %w", err)
	}

	if parseStatus == envelope.ParseMalformed {
		// DQ hook (walking skeleton): landed and surfaced loudly.
		f.Log.Error("malformed feed landed (never dropped)",
			"connector", ConnectorName, "record_id", recordID,
			"object_key", key, "topic", Topic, "parse_error", parseError)
	} else {
		f.Log.Info("feed landed and produced",
			"connector", ConnectorName, "record_id", recordID,
			"object_key", key, "topic", Topic, "bytes", len(body))
	}
	return nil
}
