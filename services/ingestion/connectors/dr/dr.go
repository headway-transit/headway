// Package dr is the demand-response trip file-drop connector (handoff 0013,
// Demand Response module v0). It scans a drop directory for
// demand_response_trips*.csv files, lands the EXACT bytes in the object
// store at a content-addressed key, and produces an object_ref raw-record
// envelope to raw.dr.trips keyed by record_id. Processed files are moved to
// a processed/ subdirectory so a re-scan is idempotent (content-addressing
// already dedupes re-produces of the same bytes). The pattern is the TIDES
// connector's, deliberately (connectors/tides/tides.go — the binding
// precedent per handoff 0013).
//
// Partial-copy guard (2026-07-13 hardening pass): a file is ingested only
// after it has been observed with an identical size AND mtime on two
// consecutive scans — i.e. it sat unchanged for a full scan interval. A file
// still being copied into the drop directory grows between scans and is
// skipped (logged, never ingested) until it settles, so a partially-copied
// export can never be landed as a complete record (silent truncation).
// Agencies SHOULD additionally write-then-rename: write the export under a
// non-matching name (e.g. .tmp) and rename() it to its final
// demand_response_trips*.csv name only when complete — rename is atomic on
// the same filesystem, so the scanner only ever sees complete files.
//
// The CSV header sanity check (required demand_response_trip v0 columns
// present; row-level semantics per the contract are the transform
// normalizer's concern, not ingestion's) is used ONLY to set parse_status.
// A malformed file is still landed and produced as malformed — never
// dropped (Guardrail 7).
//
// The envelope source is REQUIRED and has no default (2026-07-13 hardening
// pass — fail closed): real dispatch feeds set DR_SOURCE=dr (or a vendor
// label); simulator drops MUST set DR_SOURCE=dr_simulated so simulated data
// stays permanently distinguishable in provenance (Shared Constraint 2,
// full provenance; the handoff-0005 binding rule, applied to DR by handoff
// 0013). As a second, structural line of defense the scanner REFUSES any
// file whose rows carry the simulator marker ("sim:"-prefixed field, which
// tools/dr-simulator always writes) when the configured source label is not
// a *_simulated label: the file is moved to rejected/ and loudly logged,
// never landed — simulated data must never be able to masquerade as real.
//
// Row format: contracts/demand-response-trip.v0.schema.json (+ the field
// semantics in contracts/demand-response-trip.v0.md). Required columns per
// that schema's "required" list: dr_trip_id, service_date, vehicle_id,
// mode, tos, pickup_timestamp, dropoff_timestamp, riders,
// attendants_companions, ada_related, sponsored, no_show.
package dr

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
	ConnectorName    = "headway-dr"
	ConnectorVersion = "0.2.0"
	ContentType      = "text/csv"
	Topic            = "raw.dr.trips"

	// FilePattern selects droppable files within the drop directory.
	FilePattern = "demand_response_trips*.csv"
	// ProcessedDir is the subdirectory processed files are moved into.
	ProcessedDir = "processed"
	// RejectedDir is the subdirectory refused files are moved into
	// (oversize, or simulator-marked content under a non-simulated source
	// label). Refused files are preserved for human inspection — moved,
	// logged loudly, never deleted and never silently skipped.
	RejectedDir = "rejected"

	// SimulatedSourceSuffix marks a source label as carrying simulated
	// data (e.g. "dr_simulated") — the handoff-0005 binding rule.
	SimulatedSourceSuffix = "_simulated"
	// SimMarkerPrefix is the structural row marker every Headway simulator
	// writes into its identifiers (tools/dr-simulator: dr_trip_id
	// "sim:<date>:<vehicle>:<n>").
	SimMarkerPrefix = "sim:"

	// DefaultMaxFileBytes caps how large a dropped file may be before the
	// scanner refuses it (moved to rejected/, logged). Generous: real
	// booking-level exports are a few MiB per day. Override per Scanner.
	DefaultMaxFileBytes = 256 << 20 // 256 MiB

	// DefaultScanInterval is Run's rescan cadence when none is configured.
	DefaultScanInterval = 30 * time.Second
)

// RequiredColumns are the required fields of the demand_response_trip v0
// contract (contracts/demand-response-trip.v0.schema.json "required" list).
// Used ONLY for the header sanity check that sets parse_status.
var RequiredColumns = []string{
	"dr_trip_id",
	"service_date",
	"vehicle_id",
	"mode",
	"tos",
	"pickup_timestamp",
	"dropoff_timestamp",
	"riders",
	"attendants_companions",
	"ada_related",
	"sponsored",
	"no_show",
}

// ObjectKey returns the content-addressed object-store key for a
// demand_response_trips CSV file.
func ObjectKey(recordID string) string {
	return fmt.Sprintf("raw/dr/%s.csv", recordID)
}

// fileState is one scan's observation of a candidate file, used by the
// partial-copy stability guard.
type fileState struct {
	size  int64
	mtime time.Time
}

func (a fileState) equal(b fileState) bool {
	return a.size == b.size && a.mtime.Equal(b.mtime)
}

// Scanner scans one drop directory for demand_response_trips CSV files,
// lands each stable file, produces its envelope, and moves the file to
// processed/.
type Scanner struct {
	Dir      string
	Source   string // envelope source; REQUIRED, no default (fail closed)
	AgencyID string // optional

	// MaxFileBytes caps the size of a dropped file; <= 0 means
	// DefaultMaxFileBytes. Oversize files are moved to rejected/ and
	// logged — never read into memory, never silently skipped.
	MaxFileBytes int64
	// Interval is Run's rescan cadence; <= 0 means DefaultScanInterval.
	// It is also the settle time of the partial-copy guard: a file must
	// be unchanged for one full interval before it is ingested.
	Interval time.Duration

	Store    ObjectStore
	Producer producer.Producer
	Log      *slog.Logger

	// Clock is injectable for tests; defaults to time.Now.
	Clock func() time.Time

	// pending tracks candidate files' (size, mtime) from the previous
	// scan for the stability guard.
	pending map[string]fileState
}

func (s *Scanner) clock() time.Time {
	if s.Clock != nil {
		return s.Clock()
	}
	return time.Now()
}

func (s *Scanner) maxFileBytes() int64 {
	if s.MaxFileBytes > 0 {
		return s.MaxFileBytes
	}
	return DefaultMaxFileBytes
}

// checkSource refuses to run without an explicit source label. There is no
// default: a connector that guessed "dr" here could ingest simulated drops
// as real agency data (Shared Constraint 2, full provenance).
func (s *Scanner) checkSource() error {
	if strings.TrimSpace(s.Source) != "" {
		return nil
	}
	return errors.New(
		"dr: no source label configured. Set DR_SOURCE to say what this " +
			"drop directory carries: DR_SOURCE=dr (or your vendor's label) " +
			"for a real dispatch feed, or DR_SOURCE=dr_simulated for " +
			"simulator output. The connector refuses to guess, because " +
			"simulated data must never enter provenance under a real " +
			"source label (Shared Constraint 2: full provenance)")
}

// sourceIsSimulated reports whether the configured source label declares
// simulated data (the *_simulated convention, handoff 0005).
func (s *Scanner) sourceIsSimulated() bool {
	return strings.HasSuffix(s.Source, SimulatedSourceSuffix)
}

// Run scans Dir every Interval until ctx is cancelled. Per-file failures
// are logged by ScanOnce and retried on later scans (failed files stay in
// the drop directory); a missing source label is a configuration refusal
// and returns immediately.
func (s *Scanner) Run(ctx context.Context) error {
	if err := s.checkSource(); err != nil {
		return err
	}
	interval := s.Interval
	if interval <= 0 {
		interval = DefaultScanInterval
	}
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		if err := s.ScanOnce(ctx); err != nil && ctx.Err() == nil {
			s.Log.Error("dr drop-dir scan had failures (will rescan)",
				"connector", ConnectorName, "dir", s.Dir, "error", err)
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-ticker.C:
		}
	}
}

// ScanOnce examines every demand_response_trips*.csv currently in Dir, in
// filename order. A file is ingested only once it is STABLE — same size and
// mtime as on the previous scan (partial-copy guard; see the package
// comment). Each stable file is landed, produced, then moved to processed/;
// a per-file failure is logged and reported but does not stop the other
// files. Landing precedes producing: a consumer must never see an envelope
// whose object does not exist. A header sanity-check failure sets
// parse_status malformed but the bytes are still landed and produced.
func (s *Scanner) ScanOnce(ctx context.Context) error {
	if err := s.checkSource(); err != nil {
		return err
	}
	matches, err := filepath.Glob(filepath.Join(s.Dir, FilePattern))
	if err != nil {
		return fmt.Errorf("dr: scan %s: %w", s.Dir, err)
	}
	sort.Strings(matches)
	if s.pending == nil {
		s.pending = make(map[string]fileState)
	}

	var errs []error
	seen := make(map[string]bool, len(matches))
	for _, path := range matches {
		seen[path] = true
		info, err := os.Stat(path)
		if err != nil {
			errs = append(errs, fmt.Errorf("dr: stat %s: %w", path, err))
			continue
		}

		// Size cap: refuse before reading anything into memory. An
		// oversize file only grows, so there is no point waiting for
		// stability.
		if info.Size() > s.maxFileBytes() {
			delete(s.pending, path)
			err := s.rejectFile(path, fmt.Sprintf(
				"file is %d bytes, over the %d-byte limit (DROP_MAX_FILE_BYTES)",
				info.Size(), s.maxFileBytes()))
			errs = append(errs, err)
			continue
		}

		// Partial-copy stability guard: ingest only after the file has
		// been seen unchanged (size AND mtime) across two consecutive
		// scans — one full scan interval of quiet.
		cur := fileState{size: info.Size(), mtime: info.ModTime()}
		prev, known := s.pending[path]
		if !known || !prev.equal(cur) {
			s.pending[path] = cur
			s.Log.Info("file not yet stable; waiting one scan interval before ingest (partial-copy guard)",
				"connector", ConnectorName, "file", filepath.Base(path),
				"bytes", cur.size, "seen_before", known)
			continue
		}

		if err := s.processFile(ctx, path); err != nil {
			s.Log.Error("dr trips file failed (left in place for re-scan)",
				"connector", ConnectorName, "path", path, "error", err)
			errs = append(errs, err)
		} else {
			delete(s.pending, path)
		}
	}
	// Forget files that vanished between scans.
	for path := range s.pending {
		if !seen[path] {
			delete(s.pending, path)
		}
	}
	return errors.Join(errs...)
}

// processFile lands one stable file, produces its envelope, and moves it to
// processed/. The move happens only after a successful produce, so a failed
// file stays in the drop directory for the next scan (idempotent by
// content-addressed record_id).
func (s *Scanner) processFile(ctx context.Context, path string) error {
	body, err := os.ReadFile(path)
	if err != nil {
		return fmt.Errorf("dr: read %s: %w", path, err)
	}
	if int64(len(body)) > s.maxFileBytes() {
		// Grew past the cap between stat and read.
		return s.rejectFile(path, fmt.Sprintf(
			"file is %d bytes, over the %d-byte limit (DROP_MAX_FILE_BYTES)",
			len(body), s.maxFileBytes()))
	}
	fetchedAt := s.clock()

	// Provenance enforcement (Shared Constraint 2 — full provenance:
	// "simulated data is permanently distinguishable in provenance"): the
	// Headway simulators structurally mark every row with a "sim:" id
	// prefix. Simulator-marked content arriving under a source label that
	// does not declare simulation is a provenance violation — hard-refuse
	// the file, loudly, before anything is landed or produced.
	if !s.sourceIsSimulated() {
		if n := simMarkedRowCount(body); n > 0 {
			return s.rejectFile(path, fmt.Sprintf(
				"%d row(s) carry the simulator marker %q but the configured "+
					"source label %q does not declare simulated data; "+
					"simulated data must never be ingested as real "+
					"(Shared Constraint 2: full provenance). If this file "+
					"really is simulator output, re-drop it with "+
					"DR_SOURCE=dr_simulated", n, SimMarkerPrefix, s.Source))
		}
	}

	recordID := envelope.RecordID(body)
	key := ObjectKey(recordID)

	// Sanity check ONLY to classify parse_status; the raw bytes are the
	// record regardless of the outcome.
	parseStatus, parseError := envelope.ParseOK, ""
	if err := checkHeader(body); err != nil {
		parseStatus = envelope.ParseMalformed
		parseError = fmt.Sprintf("demand_response_trip header check failed: %v", err)
	}

	if err := s.Store.Put(ctx, key, body); err != nil {
		return fmt.Errorf("dr: land %s: %w", key, err)
	}

	env, err := envelope.NewObjectRef(body, key, envelope.Params{
		Source:           s.Source,
		Connector:        ConnectorName,
		ConnectorVersion: ConnectorVersion,
		AgencyID:         s.AgencyID,
		FetchedAt:        fetchedAt,
		ContentType:      ContentType,
		ParseStatus:      parseStatus,
		ParseError:       parseError,
	})
	if err != nil {
		return fmt.Errorf("dr: build envelope: %w", err)
	}
	value, err := env.MarshalJSONBytes()
	if err != nil {
		return fmt.Errorf("dr: marshal envelope: %w", err)
	}
	if err := s.Producer.Produce(ctx, Topic, []byte(recordID), value); err != nil {
		return fmt.Errorf("dr: %w", err)
	}

	if err := s.moveTo(path, ProcessedDir); err != nil {
		return err
	}

	if parseStatus == envelope.ParseMalformed {
		// DQ hook: landed and surfaced loudly, never dropped.
		s.Log.Error("malformed demand_response_trips file landed (never dropped)",
			"connector", ConnectorName, "record_id", recordID,
			"object_key", key, "topic", Topic, "source", s.Source,
			"file", filepath.Base(path), "parse_error", parseError)
	} else {
		s.Log.Info("demand_response_trips file landed and produced",
			"connector", ConnectorName, "record_id", recordID,
			"object_key", key, "topic", Topic, "source", s.Source,
			"file", filepath.Base(path), "bytes", len(body))
	}
	return nil
}

// rejectFile moves a refused file to Dir/rejected/, logs the refusal
// loudly, and returns the refusal as an error so the scan reports it. The
// file is preserved for human inspection — refused, never deleted, never
// silent.
func (s *Scanner) rejectFile(path, reason string) error {
	moveErr := s.moveTo(path, RejectedDir)
	s.Log.Error("REFUSED demand_response_trips file (moved to rejected/, never silently skipped)",
		"connector", ConnectorName, "file", filepath.Base(path),
		"reason", reason, "move_error", moveErr)
	if moveErr != nil {
		return fmt.Errorf("dr: refused %s (%s) but could not move it to %s/: %w",
			path, reason, RejectedDir, moveErr)
	}
	return fmt.Errorf("dr: refused %s: %s (moved to %s/)", path, reason, RejectedDir)
}

// moveTo relocates a file into Dir/<subdir>/ so the next scan does not pick
// it up again.
func (s *Scanner) moveTo(path, subdir string) error {
	dir := filepath.Join(s.Dir, subdir)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return fmt.Errorf("dr: create %s: %w", dir, err)
	}
	dest := filepath.Join(dir, filepath.Base(path))
	if err := os.Rename(path, dest); err != nil {
		return fmt.Errorf("dr: move %s to %s: %w", path, subdir, err)
	}
	return nil
}

// simMarkedRowCount counts lines containing a field that begins with the
// simulator marker "sim:". It deliberately uses a plain byte scan rather
// than a CSV parser: the check must hold for malformed files too (those are
// otherwise still landed as parse_status=malformed), and a marker hidden by
// broken quoting must still refuse.
func simMarkedRowCount(body []byte) int {
	count := 0
	for _, line := range bytes.Split(body, []byte("\n")) {
		for _, field := range bytes.Split(line, []byte(",")) {
			trimmed := bytes.TrimLeft(field, " \t\"")
			if bytes.HasPrefix(trimmed, []byte(SimMarkerPrefix)) {
				count++
				break
			}
		}
	}
	return count
}

// checkHeader parses only the first CSV record and verifies every required
// demand_response_trip v0 column is present. It never inspects data rows —
// row semantics belong to the transform normalizer.
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
		return fmt.Errorf("missing required demand_response_trip columns: %s",
			strings.Join(missing, ", "))
	}
	return nil
}
