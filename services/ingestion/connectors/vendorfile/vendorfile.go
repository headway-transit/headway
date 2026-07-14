// Package vendorfile is the generic vendor-export file-drop connector for the
// adapter framework (handoff 0015). It scans a drop directory for *.csv
// files in ANY vendor's export format, lands the EXACT original bytes in the
// object store at a content-addressed key (content addressing is always on
// the ORIGINAL vendor bytes — the raw record is what the vendor pushed), and
// produces an object_ref raw-record envelope to raw.vendor.files keyed by
// record_id. Interpreting the bytes is NOT this connector's job: the
// transform-side adapter runtime resolves the envelope source label against
// the registered mapping specs (adapters/) and maps the file onto an open
// contract — or REFUSES it fail-closed when the label is unregistered.
//
// The hardening pattern is the dr/tides connectors', deliberately
// (2026-07-13 hardening pass — the binding precedent):
//
//   - Partial-copy guard: a file is ingested only after it has been observed
//     with an identical size AND mtime on two consecutive scans, so a file
//     still being copied can never land truncated. Agencies SHOULD also
//     write-then-rename (rename is atomic on the same filesystem).
//   - Size cap: oversize files are moved to rejected/ and loudly logged —
//     never read into memory, never silently skipped.
//   - Fail-closed source label: VENDOR_SOURCE is REQUIRED and has no
//     default. It must be the registered mapping-spec label
//     `<vendor>_<product>` (or `<vendor>_<product>_simulated` for synthetic
//     data — e.g. acme_ridelog_simulated, the reference adapter). The
//     transform runtime refuses unregistered labels, so a typo here becomes
//     a blocking DQ issue, never silently mapped data.
//   - Simulated-data defense: content carrying the structural simulator
//     marker ("sim:"-prefixed field) under a source label that does not
//     declare simulation is hard-refused (moved to rejected/) before
//     anything is landed or produced — simulated data must never masquerade
//     as real (Shared Constraint 2: full provenance).
//   - parse_status is always "ok" from this connector: it deliberately
//     performs NO header/content check, because only the registered mapping
//     spec knows what the vendor format looks like. Malformed-for-the-spec
//     files still land and are quarantined per-row (or refused whole) by the
//     transform adapter runtime — never dropped (Guardrail 7).
package vendorfile

import (
	"bytes"
	"context"
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
	ConnectorName    = "headway-vendor-file"
	ConnectorVersion = "0.1.0"
	ContentType      = "text/csv"
	Topic            = "raw.vendor.files"

	// FilePattern selects droppable files within the drop directory. v0
	// adapters map CSV exports (contracts/adapter-mapping.v0.md); other
	// source kinds arrive with future mapping-spec versions.
	FilePattern = "*.csv"
	// ProcessedDir is the subdirectory processed files are moved into.
	ProcessedDir = "processed"
	// RejectedDir is the subdirectory refused files are moved into
	// (oversize, or simulator-marked content under a non-simulated source
	// label). Refused files are preserved for human inspection — moved,
	// logged loudly, never deleted and never silently skipped.
	RejectedDir = "rejected"

	// SimulatedSourceSuffix marks a source label as carrying simulated
	// data (e.g. "acme_ridelog_simulated") — the handoff-0005 binding rule.
	SimulatedSourceSuffix = "_simulated"
	// SimMarkerPrefix is the structural row marker every Headway simulator
	// writes into its identifiers.
	SimMarkerPrefix = "sim:"

	// DefaultMaxFileBytes caps how large a dropped file may be before the
	// scanner refuses it (moved to rejected/, logged). Override per Scanner.
	DefaultMaxFileBytes = 256 << 20 // 256 MiB

	// DefaultScanInterval is Run's rescan cadence when none is configured.
	DefaultScanInterval = 30 * time.Second
)

// ObjectKey returns the content-addressed object-store key for a vendor
// export file.
func ObjectKey(recordID string) string {
	return fmt.Sprintf("raw/vendor/%s.csv", recordID)
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

// Scanner scans one drop directory for vendor export files, lands each
// stable file, produces its envelope, and moves the file to processed/.
type Scanner struct {
	Dir      string
	Source   string // envelope source label; REQUIRED, no default (fail closed)
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
// default: the label is the adapter-registry key AND what keeps simulated
// data permanently distinguishable in provenance (Shared Constraint 2).
func (s *Scanner) checkSource() error {
	if strings.TrimSpace(s.Source) != "" {
		return nil
	}
	return errors.New(
		"vendorfile: no source label configured. Set VENDOR_SOURCE to the " +
			"REGISTERED mapping-spec label for this drop directory " +
			"(`<vendor>_<product>`, e.g. from adapters/<vendor>/<product>/" +
			"mapping.v0.yaml; `<vendor>_<product>_simulated` for synthetic " +
			"data). The connector refuses to guess: an unlabeled feed could " +
			"be mapped by the wrong spec or record simulated data as real " +
			"(Shared Constraint 2: full provenance)")
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
			s.Log.Error("vendor drop-dir scan had failures (will rescan)",
				"connector", ConnectorName, "dir", s.Dir, "error", err)
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-ticker.C:
		}
	}
}

// ScanOnce examines every *.csv currently in Dir, in filename order. A file
// is ingested only once it is STABLE — same size and mtime as on the
// previous scan (partial-copy guard). Each stable file is landed, produced,
// then moved to processed/; a per-file failure is logged and reported but
// does not stop the other files. Landing precedes producing: a consumer
// must never see an envelope whose object does not exist.
func (s *Scanner) ScanOnce(ctx context.Context) error {
	if err := s.checkSource(); err != nil {
		return err
	}
	matches, err := filepath.Glob(filepath.Join(s.Dir, FilePattern))
	if err != nil {
		return fmt.Errorf("vendorfile: scan %s: %w", s.Dir, err)
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
			errs = append(errs, fmt.Errorf("vendorfile: stat %s: %w", path, err))
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
			s.Log.Error("vendor file failed (left in place for re-scan)",
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
		return fmt.Errorf("vendorfile: read %s: %w", path, err)
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
					"really is simulator/synthetic output, re-drop it with a "+
					"VENDOR_SOURCE label ending in %s",
				n, SimMarkerPrefix, s.Source, SimulatedSourceSuffix))
		}
	}

	recordID := envelope.RecordID(body)
	key := ObjectKey(recordID)

	if err := s.Store.Put(ctx, key, body); err != nil {
		return fmt.Errorf("vendorfile: land %s: %w", key, err)
	}

	// parse_status is always ok here: only the registered mapping spec
	// knows the vendor format, so ALL content checks are the transform
	// adapter runtime's (per-row quarantine / fail-closed refusal).
	env, err := envelope.NewObjectRef(body, key, envelope.Params{
		Source:           s.Source,
		Connector:        ConnectorName,
		ConnectorVersion: ConnectorVersion,
		AgencyID:         s.AgencyID,
		FetchedAt:        fetchedAt,
		ContentType:      ContentType,
		ParseStatus:      envelope.ParseOK,
	})
	if err != nil {
		return fmt.Errorf("vendorfile: build envelope: %w", err)
	}
	value, err := env.MarshalJSONBytes()
	if err != nil {
		return fmt.Errorf("vendorfile: marshal envelope: %w", err)
	}
	if err := s.Producer.Produce(ctx, Topic, []byte(recordID), value); err != nil {
		return fmt.Errorf("vendorfile: %w", err)
	}

	if err := s.moveTo(path, ProcessedDir); err != nil {
		return err
	}

	s.Log.Info("vendor export file landed and produced",
		"connector", ConnectorName, "record_id", recordID,
		"object_key", key, "topic", Topic, "source", s.Source,
		"file", filepath.Base(path), "bytes", len(body))
	return nil
}

// rejectFile moves a refused file to Dir/rejected/, logs the refusal
// loudly, and returns the refusal as an error so the scan reports it. The
// file is preserved for human inspection — refused, never deleted, never
// silent.
func (s *Scanner) rejectFile(path, reason string) error {
	moveErr := s.moveTo(path, RejectedDir)
	s.Log.Error("REFUSED vendor export file (moved to rejected/, never silently skipped)",
		"connector", ConnectorName, "file", filepath.Base(path),
		"reason", reason, "move_error", moveErr)
	if moveErr != nil {
		return fmt.Errorf("vendorfile: refused %s (%s) but could not move it to %s/: %w",
			path, reason, RejectedDir, moveErr)
	}
	return fmt.Errorf("vendorfile: refused %s: %s (moved to %s/)", path, reason, RejectedDir)
}

// moveTo relocates a file into Dir/<subdir>/ so the next scan does not pick
// it up again.
func (s *Scanner) moveTo(path, subdir string) error {
	dir := filepath.Join(s.Dir, subdir)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return fmt.Errorf("vendorfile: create %s: %w", dir, err)
	}
	dest := filepath.Join(dir, filepath.Base(path))
	if err := os.Rename(path, dest); err != nil {
		return fmt.Errorf("vendorfile: move %s to %s: %w", path, subdir, err)
	}
	return nil
}

// simMarkedRowCount counts lines containing a field that begins with the
// simulator marker "sim:". It deliberately uses a plain byte scan rather
// than a CSV parser: the check must hold for arbitrary vendor dialects and
// malformed files too, and a marker hidden by broken quoting must still
// refuse.
func simMarkedRowCount(body []byte) int {
	count := 0
	for _, line := range bytes.Split(body, []byte("\n")) {
		for _, field := range bytes.FieldsFunc(line, func(r rune) bool {
			return r == ',' || r == ';' || r == '|' || r == '\t'
		}) {
			trimmed := bytes.TrimLeft(field, " \t\"'")
			if bytes.HasPrefix(trimmed, []byte(SimMarkerPrefix)) {
				count++
				break
			}
		}
	}
	return count
}
