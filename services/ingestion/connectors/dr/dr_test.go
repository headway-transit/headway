package dr

import (
	"bytes"
	"context"
	"encoding/json"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/headway-transit/headway/services/ingestion/internal/envelope"
	"github.com/headway-transit/headway/services/ingestion/internal/producer"
)

// validCSV is a minimal demand_response_trips file containing every required
// column of contracts/demand-response-trip.v0.schema.json and one row.
const validCSV = "dr_trip_id,service_date,vehicle_id,mode,tos,pickup_timestamp,dropoff_timestamp,riders,attendants_companions,ada_related,sponsored,sponsor,no_show,interruption_after,onboard_miles\n" +
	"drt-1,2026-07-14,van-1,DR,DO,2026-07-14T13:00:00Z,2026-07-14T13:20:00Z,1,0,true,false,,false,none,4.2\n"

// simulatedCSV carries the structural simulator marker (tools/dr-simulator
// writes dr_trip_id "sim:<date>:<vehicle>:<n>" on every row).
const simulatedCSV = "dr_trip_id,service_date,vehicle_id,mode,tos,pickup_timestamp,dropoff_timestamp,riders,attendants_companions,ada_related,sponsored,sponsor,no_show,interruption_after,onboard_miles\n" +
	"sim:2026-07-14:dr-van-01:1,2026-07-14,dr-van-01,DR,DO,2026-07-14T13:00:00Z,2026-07-14T13:20:00Z,1,0,true,false,,false,none,4.2\n"

// missingColumnCSV lacks the required tos and no_show columns.
const missingColumnCSV = "dr_trip_id,service_date,vehicle_id,mode,pickup_timestamp,dropoff_timestamp,riders,attendants_companions,ada_related,sponsored\n" +
	"drt-1,2026-07-14,van-1,DR,2026-07-14T13:00:00Z,2026-07-14T13:20:00Z,1,0,true,false\n"

func newTestScanner(t *testing.T) (*Scanner, *producer.Fake, *FakeStore, string) {
	t.Helper()
	dir := t.TempDir()
	fakeProd := producer.NewFake()
	fakeStore := NewFakeStore()
	s := &Scanner{
		Dir:      dir,
		Source:   "dr", // explicit — there is no default (fail closed)
		Store:    fakeStore,
		Producer: fakeProd,
		Log:      slog.New(slog.NewTextHandler(testWriter{t}, nil)),
		Clock:    func() time.Time { return time.Date(2026, 7, 13, 12, 0, 0, 0, time.UTC) },
	}
	return s, fakeProd, fakeStore, dir
}

type testWriter struct{ t *testing.T }

func (w testWriter) Write(p []byte) (int, error) { w.t.Log(string(p)); return len(p), nil }

func dropFile(t *testing.T, dir, name, content string) string {
	t.Helper()
	path := filepath.Join(dir, name)
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatalf("write drop file: %v", err)
	}
	return path
}

// scanTwice runs two consecutive scans: the first observes candidate files
// for the partial-copy stability guard, the second ingests stable ones. It
// returns the second scan's error (the first must not fail).
func scanTwice(t *testing.T, s *Scanner) error {
	t.Helper()
	if err := s.ScanOnce(context.Background()); err != nil {
		t.Fatalf("first (observation) ScanOnce: %v", err)
	}
	return s.ScanOnce(context.Background())
}

func TestScanOnceEnvelopeCorrectness(t *testing.T) {
	s, fakeProd, fakeStore, dir := newTestScanner(t)
	dropFile(t, dir, "demand_response_trips_2026-07-14.csv", validCSV)

	if err := scanTwice(t, s); err != nil {
		t.Fatalf("ScanOnce: %v", err)
	}
	msgs := fakeProd.Messages()
	if len(msgs) != 1 {
		t.Fatalf("produced %d messages, want 1", len(msgs))
	}
	if msgs[0].Topic != Topic {
		t.Errorf("topic = %q, want %q", msgs[0].Topic, Topic)
	}

	var m map[string]any
	if err := json.Unmarshal(msgs[0].Value, &m); err != nil {
		t.Fatalf("envelope not JSON: %v", err)
	}
	for _, k := range []string{
		"envelope_version", "record_id", "source", "connector",
		"connector_version", "fetched_at", "content_type",
		"payload_encoding", "payload", "parse_status",
	} {
		if _, ok := m[k]; !ok {
			t.Errorf("envelope missing required field %q", k)
		}
	}
	wantID := envelope.RecordID([]byte(validCSV))
	wantKey := "raw/dr/" + wantID + ".csv"
	if m["record_id"] != wantID {
		t.Errorf("record_id = %v, want %v", m["record_id"], wantID)
	}
	if string(msgs[0].Key) != wantID {
		t.Errorf("message key = %q, want record_id", msgs[0].Key)
	}
	if m["payload_encoding"] != envelope.EncodingObjectRef {
		t.Errorf("payload_encoding = %v, want object_ref", m["payload_encoding"])
	}
	if m["payload"] != wantKey {
		t.Errorf("payload = %v, want object key %v", m["payload"], wantKey)
	}
	if m["parse_status"] != envelope.ParseOK {
		t.Errorf("parse_status = %v, want ok", m["parse_status"])
	}
	if m["source"] != "dr" || m["connector"] != ConnectorName || m["content_type"] != ContentType {
		t.Errorf("identity fields wrong: %v/%v/%v", m["source"], m["connector"], m["content_type"])
	}

	// Object key matches record_id and the landed bytes are byte-identical.
	stored, ok := fakeStore.Get(wantKey)
	if !ok {
		t.Fatalf("object not landed at %s", wantKey)
	}
	if !bytes.Equal(stored, []byte(validCSV)) {
		t.Errorf("landed object bytes differ from dropped file bytes")
	}
	if envelope.RecordID(stored) != wantID {
		t.Errorf("landed object does not hash to record_id")
	}
}

func TestGrowingFileNotIngestedUntilStable(t *testing.T) {
	// The reviewers' partial-copy scenario: a file still being copied into
	// the drop directory must never be ingested mid-copy. The scanner may
	// ingest only after the file is unchanged across two consecutive scans.
	s, fakeProd, fakeStore, dir := newTestScanner(t)
	path := filepath.Join(dir, "demand_response_trips_growing.csv")

	half := len(validCSV) / 2
	if err := os.WriteFile(path, []byte(validCSV[:half]), 0o644); err != nil {
		t.Fatalf("write partial file: %v", err)
	}

	// Scan 1: first observation — never ingested on first sight.
	if err := s.ScanOnce(context.Background()); err != nil {
		t.Fatalf("scan 1: %v", err)
	}
	if got := len(fakeProd.Messages()); got != 0 {
		t.Fatalf("partial file ingested on first sight: %d messages", got)
	}

	// The copy continues: the file grows between scans.
	if err := os.WriteFile(path, []byte(validCSV), 0o644); err != nil {
		t.Fatalf("grow file: %v", err)
	}

	// Scan 2: size changed since scan 1 — still not stable, no ingest.
	if err := s.ScanOnce(context.Background()); err != nil {
		t.Fatalf("scan 2: %v", err)
	}
	if got := len(fakeProd.Messages()); got != 0 {
		t.Fatalf("growing file ingested mid-copy: %d messages (silent truncation!)", got)
	}

	// Scan 3: unchanged for a full scan interval — ingest exactly once,
	// with the COMPLETE bytes.
	if err := s.ScanOnce(context.Background()); err != nil {
		t.Fatalf("scan 3: %v", err)
	}
	msgs := fakeProd.Messages()
	if len(msgs) != 1 {
		t.Fatalf("stable file: %d messages, want exactly 1", len(msgs))
	}
	wantID := envelope.RecordID([]byte(validCSV))
	stored, ok := fakeStore.Get(ObjectKey(wantID))
	if !ok {
		t.Fatalf("complete file not landed")
	}
	if !bytes.Equal(stored, []byte(validCSV)) {
		t.Errorf("landed bytes are not the complete file")
	}

	// Scan 4: nothing left to ingest.
	if err := s.ScanOnce(context.Background()); err != nil {
		t.Fatalf("scan 4: %v", err)
	}
	if got := len(fakeProd.Messages()); got != 1 {
		t.Fatalf("file re-ingested after processing: %d messages", got)
	}
}

func TestEmptySourceRefusedAtScan(t *testing.T) {
	// Fail closed: no source label, no scan. The old default ("dr") let
	// simulated drops masquerade as real data.
	s, fakeProd, _, dir := newTestScanner(t)
	s.Source = ""
	dropFile(t, dir, "demand_response_trips.csv", validCSV)

	err := s.ScanOnce(context.Background())
	if err == nil {
		t.Fatal("ScanOnce with no source label must refuse")
	}
	if !strings.Contains(err.Error(), "DR_SOURCE") {
		t.Errorf("refusal must name DR_SOURCE for the operator, got: %v", err)
	}
	if got := len(fakeProd.Messages()); got != 0 {
		t.Fatalf("messages produced despite missing source label: %d", got)
	}
	if err := s.Run(context.Background()); err == nil {
		t.Fatal("Run with no source label must refuse immediately")
	}
}

func TestSimulatorMarkedContentUnderRealSourceRefused(t *testing.T) {
	// Provenance enforcement (Shared Constraint 2): simulator-marked rows
	// ("sim:" ids) under a non-simulated source label are hard-refused —
	// moved to rejected/, never landed, never produced.
	s, fakeProd, fakeStore, dir := newTestScanner(t)
	s.Source = "dr" // a REAL source label
	dropFile(t, dir, "demand_response_trips_sim.csv", simulatedCSV)

	err := scanTwice(t, s)
	if err == nil {
		t.Fatal("simulator-marked file under a real source label must refuse")
	}
	if !strings.Contains(err.Error(), "sim:") || !strings.Contains(err.Error(), "dr_simulated") {
		t.Errorf("refusal must explain the marker and the fix, got: %v", err)
	}
	if got := len(fakeProd.Messages()); got != 0 {
		t.Fatalf("simulated data produced under real source label: %d messages", got)
	}
	if _, ok := fakeStore.Get(ObjectKey(envelope.RecordID([]byte(simulatedCSV)))); ok {
		t.Fatal("simulated data landed under real source label")
	}
	// Preserved for inspection in rejected/, out of the scanner's reach.
	rejected := filepath.Join(dir, RejectedDir, "demand_response_trips_sim.csv")
	got, readErr := os.ReadFile(rejected)
	if readErr != nil {
		t.Fatalf("refused file not preserved in rejected/: %v", readErr)
	}
	if !bytes.Equal(got, []byte(simulatedCSV)) {
		t.Errorf("rejected file bytes were mutated")
	}
}

func TestSimulatorMarkedContentUnderSimulatedSourceIngested(t *testing.T) {
	// The counterpart: the same simulator output under dr_simulated is
	// legitimate and ingests normally, source carried verbatim.
	s, fakeProd, _, dir := newTestScanner(t)
	s.Source = "dr_simulated"
	dropFile(t, dir, "demand_response_trips_sim.csv", simulatedCSV)

	if err := scanTwice(t, s); err != nil {
		t.Fatalf("simulated drop under dr_simulated must ingest: %v", err)
	}
	msgs := fakeProd.Messages()
	if len(msgs) != 1 {
		t.Fatalf("produced %d messages, want 1", len(msgs))
	}
	var m map[string]any
	if err := json.Unmarshal(msgs[0].Value, &m); err != nil {
		t.Fatalf("envelope not JSON: %v", err)
	}
	if m["source"] != "dr_simulated" {
		t.Errorf("source = %v, want dr_simulated", m["source"])
	}
}

func TestOversizeFileRejected(t *testing.T) {
	s, fakeProd, _, dir := newTestScanner(t)
	s.MaxFileBytes = 64 // tiny cap for test speed
	dropFile(t, dir, "demand_response_trips_big.csv", validCSV) // > 64 bytes

	err := s.ScanOnce(context.Background())
	if err == nil {
		t.Fatal("oversize file must be refused, not ingested")
	}
	if !strings.Contains(err.Error(), "64-byte limit") {
		t.Errorf("refusal must name the limit, got: %v", err)
	}
	if got := len(fakeProd.Messages()); got != 0 {
		t.Fatalf("oversize file produced %d messages", got)
	}
	rejected := filepath.Join(dir, RejectedDir, "demand_response_trips_big.csv")
	if _, statErr := os.Stat(rejected); statErr != nil {
		t.Fatalf("oversize file not preserved in rejected/: %v", statErr)
	}
	// Rejected file is out of reach: the next scan is clean.
	if err := s.ScanOnce(context.Background()); err != nil {
		t.Fatalf("scan after rejection must be clean: %v", err)
	}
}

func TestMissingRequiredColumnStillLandedAndProducedAsMalformed(t *testing.T) {
	s, fakeProd, fakeStore, dir := newTestScanner(t)
	dropFile(t, dir, "demand_response_trips_bad.csv", missingColumnCSV)

	if err := scanTwice(t, s); err != nil {
		t.Fatalf("ScanOnce must not error on a malformed header (never drop): %v", err)
	}
	msgs := fakeProd.Messages()
	if len(msgs) != 1 {
		t.Fatalf("malformed file was dropped: %d messages, want 1", len(msgs))
	}
	var m map[string]any
	if err := json.Unmarshal(msgs[0].Value, &m); err != nil {
		t.Fatalf("envelope not JSON: %v", err)
	}
	if m["parse_status"] != envelope.ParseMalformed {
		t.Errorf("parse_status = %v, want malformed", m["parse_status"])
	}
	perr, _ := m["parse_error"].(string)
	if perr == "" {
		t.Errorf("parse_error missing on malformed envelope")
	}
	// The check must name the missing contract columns.
	for _, col := range []string{"tos", "no_show"} {
		if !bytes.Contains([]byte(perr), []byte(col)) {
			t.Errorf("parse_error %q does not name missing column %q", perr, col)
		}
	}
	// Still landed, byte-identical, at the content-addressed key.
	wantKey := ObjectKey(envelope.RecordID([]byte(missingColumnCSV)))
	stored, ok := fakeStore.Get(wantKey)
	if !ok {
		t.Fatalf("malformed file was not landed at %s", wantKey)
	}
	if !bytes.Equal(stored, []byte(missingColumnCSV)) {
		t.Errorf("malformed file bytes were mutated")
	}
	// Malformed files are still processed: moved out of the drop dir.
	if _, err := os.Stat(filepath.Join(dir, ProcessedDir, "demand_response_trips_bad.csv")); err != nil {
		t.Errorf("malformed file not moved to processed/: %v", err)
	}
}

func TestProcessedMoveMakesRescanIdempotent(t *testing.T) {
	s, fakeProd, _, dir := newTestScanner(t)
	path := dropFile(t, dir, "demand_response_trips_a.csv", validCSV)

	if err := scanTwice(t, s); err != nil {
		t.Fatalf("ScanOnce: %v", err)
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Errorf("file still present in drop dir after processing")
	}
	moved := filepath.Join(dir, ProcessedDir, "demand_response_trips_a.csv")
	got, err := os.ReadFile(moved)
	if err != nil {
		t.Fatalf("processed file missing: %v", err)
	}
	if !bytes.Equal(got, []byte(validCSV)) {
		t.Errorf("processed file bytes were mutated")
	}

	// Re-scan produces nothing: the file is out of the pattern's reach.
	if err := s.ScanOnce(context.Background()); err != nil {
		t.Fatalf("re-scan ScanOnce: %v", err)
	}
	if got := len(fakeProd.Messages()); got != 1 {
		t.Fatalf("re-scan re-produced: %d messages, want 1", got)
	}
}

func TestNonMatchingFilesIgnored(t *testing.T) {
	s, fakeProd, _, dir := newTestScanner(t)
	dropFile(t, dir, "notes.txt", "not a drop file")
	dropFile(t, dir, "passenger_events.csv", "a TIDES file, not a DR file")

	if err := scanTwice(t, s); err != nil {
		t.Fatalf("ScanOnce: %v", err)
	}
	if got := len(fakeProd.Messages()); got != 0 {
		t.Fatalf("non-matching files produced %d messages, want 0", got)
	}
}

func TestStoreFailureBlocksProduceAndLeavesFile(t *testing.T) {
	s, fakeProd, fakeStore, dir := newTestScanner(t)
	fakeStore.Err = context.DeadlineExceeded
	path := dropFile(t, dir, "demand_response_trips.csv", validCSV)

	if err := scanTwice(t, s); err == nil {
		t.Fatal("expected error when object store put fails")
	}
	// No envelope may reference an object that was never landed.
	if got := len(fakeProd.Messages()); got != 0 {
		t.Fatalf("envelope produced despite failed landing: %d messages", got)
	}
	// The file stays in the drop dir for the next scan.
	if _, err := os.Stat(path); err != nil {
		t.Errorf("failed file was moved out of the drop dir: %v", err)
	}
}

func TestRunScansPeriodicallyAndStopsOnCancel(t *testing.T) {
	s, fakeProd, _, dir := newTestScanner(t)
	s.Interval = 5 * time.Millisecond
	dropFile(t, dir, "demand_response_trips_run.csv", validCSV)

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- s.Run(ctx) }()

	// The stability guard needs two scans; give Run a few intervals.
	deadline := time.After(2 * time.Second)
	for len(fakeProd.Messages()) == 0 {
		select {
		case <-deadline:
			t.Fatal("Run never ingested the stable file")
		case <-time.After(5 * time.Millisecond):
		}
	}
	cancel()
	select {
	case err := <-done:
		if err != context.Canceled {
			t.Errorf("Run returned %v, want context.Canceled", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Run did not stop on cancel")
	}
	if got := len(fakeProd.Messages()); got != 1 {
		t.Fatalf("Run produced %d messages, want exactly 1", got)
	}
}
