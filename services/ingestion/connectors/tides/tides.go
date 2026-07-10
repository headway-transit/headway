// Package tides is the TIDES passenger_events file-drop connector (handoff
// 0005, slice 2). It scans a drop directory for passenger_events*.csv files,
// lands the EXACT bytes in the object store at a content-addressed key, and
// produces an object_ref raw-record envelope to raw.tides.passenger_events
// keyed by record_id. Processed files are moved to a processed/ subdirectory
// so a re-scan is idempotent (content-addressing already dedupes re-produces
// of the same bytes).
//
// The CSV header sanity check (required TIDES columns present; row-level
// semantics per the TIDES spec are the Data Engineer's concern, not
// ingestion's) is used ONLY to set parse_status. A malformed file is still
// landed and produced as malformed — never dropped (Guardrail 7).
//
// The envelope source is configurable (TIDES_SOURCE): real feeds use the
// default "tides"; simulator drops MUST use "tides_simulated" so simulated
// data stays permanently distinguishable in provenance (handoff 0005 binding
// rule).
//
// TIDES passenger_events schema verified against TIDES-transit/TIDES
// spec/passenger_events.schema.json (commit
// d887d42ce081f3fb6155664a3c486101d62ec52b, fetched 2026-07-10).
// Required columns: passenger_event_id, service_date, event_timestamp,
// trip_stop_sequence, event_type, vehicle_id.
// event_type enumeration (constraints.enum), verbatim:
//
//	"Vehicle arrived at stop", "Vehicle departed stop", "Door opened",
//	"Door closed", "Passenger boarded", "Passenger alighted",
//	"Kneel was engaged", "Kneel was disengaged", "Ramp was deployed",
//	"Ramp was raised", "Ramp deployment failed", "Lift was deployed",
//	"Lift was raised", "Individual bike boarded",
//	"Individual bike alighted", "Bike rack deployed"
package tides

import (
	"bytes"
	"context"
	"encoding/csv"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/headway-transit/headway/services/ingestion/internal/envelope"
	"github.com/headway-transit/headway/services/ingestion/internal/producer"
)

// Connector identity recorded on every envelope (contracts/topics.v0.md).
const (
	ConnectorName    = "headway-tides"
	ConnectorVersion = "0.1.0"
	DefaultSource    = "tides"
	ContentType      = "text/csv"
	Topic            = "raw.tides.passenger_events"

	// FilePattern selects droppable files within the drop directory.
	FilePattern = "passenger_events*.csv"
	// ProcessedDir is the subdirectory processed files are moved into.
	ProcessedDir = "processed"
)

// RequiredColumns are the required fields of the TIDES passenger_events
// schema (constraints.required: true), verified against
// spec/passenger_events.schema.json at the commit cited in the package
// comment. Used ONLY for the header sanity check that sets parse_status.
var RequiredColumns = []string{
	"passenger_event_id",
	"service_date",
	"event_timestamp",
	"trip_stop_sequence",
	"event_type",
	"vehicle_id",
}

// ObjectKey returns the content-addressed object-store key for a
// passenger_events CSV file.
func ObjectKey(recordID string) string {
	return fmt.Sprintf("raw/tides/%s.csv", recordID)
}

// Scanner scans one drop directory for TIDES passenger_events CSV files,
// lands each, produces its envelope, and moves the file to processed/.
type Scanner struct {
	Dir      string
	Source   string // envelope source; empty means DefaultSource ("tides")
	AgencyID string // optional

	Store    ObjectStore
	Producer producer.Producer
	Log      *slog.Logger

	// Clock is injectable for tests; defaults to time.Now.
	Clock func() time.Time
}

func (s *Scanner) clock() time.Time {
	if s.Clock != nil {
		return s.Clock()
	}
	return time.Now()
}

func (s *Scanner) source() string {
	if s.Source != "" {
		return s.Source
	}
	return DefaultSource
}

// ScanOnce processes every passenger_events*.csv currently in Dir, in
// filename order. Each file is landed, produced, then moved to processed/;
// a per-file failure is logged and reported but does not stop the other
// files. Landing precedes producing: a consumer must never see an envelope
// whose object does not exist. A header sanity-check failure sets
// parse_status malformed but the bytes are still landed and produced.
func (s *Scanner) ScanOnce(ctx context.Context) error {
	matches, err := filepath.Glob(filepath.Join(s.Dir, FilePattern))
	if err != nil {
		return fmt.Errorf("tides: scan %s: %w", s.Dir, err)
	}
	sort.Strings(matches)

	var errs []error
	for _, path := range matches {
		if err := s.processFile(ctx, path); err != nil {
			s.Log.Error("tides file failed (left in place for re-scan)",
				"connector", ConnectorName, "path", path, "error", err)
			errs = append(errs, err)
		}
	}
	return errors.Join(errs...)
}

// processFile lands one file, produces its envelope, and moves it to
// processed/. The move happens only after a successful produce, so a failed
// file stays in the drop directory for the next scan (idempotent by
// content-addressed record_id).
func (s *Scanner) processFile(ctx context.Context, path string) error {
	body, err := os.ReadFile(path)
	if err != nil {
		return fmt.Errorf("tides: read %s: %w", path, err)
	}
	fetchedAt := s.clock()

	recordID := envelope.RecordID(body)
	key := ObjectKey(recordID)

	// Sanity check ONLY to classify parse_status; the raw bytes are the
	// record regardless of the outcome.
	parseStatus, parseError := envelope.ParseOK, ""
	if err := checkHeader(body); err != nil {
		parseStatus = envelope.ParseMalformed
		parseError = fmt.Sprintf("tides passenger_events header check failed: %v", err)
	}

	if err := s.Store.Put(ctx, key, body); err != nil {
		return fmt.Errorf("tides: land %s: %w", key, err)
	}

	env, err := envelope.NewObjectRef(body, key, envelope.Params{
		Source:           s.source(),
		Connector:        ConnectorName,
		ConnectorVersion: ConnectorVersion,
		AgencyID:         s.AgencyID,
		FetchedAt:        fetchedAt,
		ContentType:      ContentType,
		ParseStatus:      parseStatus,
		ParseError:       parseError,
	})
	if err != nil {
		return fmt.Errorf("tides: build envelope: %w", err)
	}
	value, err := env.MarshalJSONBytes()
	if err != nil {
		return fmt.Errorf("tides: marshal envelope: %w", err)
	}
	if err := s.Producer.Produce(ctx, Topic, []byte(recordID), value); err != nil {
		return fmt.Errorf("tides: %w", err)
	}

	if err := s.moveToProcessed(path); err != nil {
		return err
	}

	if parseStatus == envelope.ParseMalformed {
		// DQ hook (walking skeleton): landed and surfaced loudly.
		s.Log.Error("malformed passenger_events file landed (never dropped)",
			"connector", ConnectorName, "record_id", recordID,
			"object_key", key, "topic", Topic, "source", s.source(),
			"file", filepath.Base(path), "parse_error", parseError)
	} else {
		s.Log.Info("passenger_events file landed and produced",
			"connector", ConnectorName, "record_id", recordID,
			"object_key", key, "topic", Topic, "source", s.source(),
			"file", filepath.Base(path), "bytes", len(body))
	}
	return nil
}

// moveToProcessed relocates a produced file into Dir/processed/ so the next
// scan does not pick it up again.
func (s *Scanner) moveToProcessed(path string) error {
	dir := filepath.Join(s.Dir, ProcessedDir)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return fmt.Errorf("tides: create %s: %w", dir, err)
	}
	dest := filepath.Join(dir, filepath.Base(path))
	if err := os.Rename(path, dest); err != nil {
		return fmt.Errorf("tides: move %s to processed: %w", path, err)
	}
	return nil
}

// checkHeader parses only the first CSV record and verifies every required
// TIDES passenger_events column is present. It never inspects data rows —
// row semantics belong to the Data Engineer's normalizer.
func checkHeader(body []byte) error {
	r := csv.NewReader(bytes.NewReader(body))
	r.FieldsPerRecord = -1
	header, err := r.Read()
	if err != nil {
		return fmt.Errorf("read header row: %w", err)
	}
	seen := make(map[string]bool, len(header))
	for i, name := range header {
		if i == 0 {
			name = strings.TrimPrefix(name, "\ufeff") // tolerate a UTF-8 BOM
		}
		seen[strings.TrimSpace(name)] = true
	}
	var missing []string
	for _, col := range RequiredColumns {
		if !seen[col] {
			missing = append(missing, col)
		}
	}
	if len(missing) > 0 {
		return fmt.Errorf("missing required TIDES columns: %s", strings.Join(missing, ", "))
	}
	return nil
}
