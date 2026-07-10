package tides

import (
	"bytes"
	"context"
	"encoding/json"
	"log/slog"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/headway-transit/headway/services/ingestion/internal/envelope"
	"github.com/headway-transit/headway/services/ingestion/internal/producer"
)

// validCSV is a minimal TIDES passenger_events file containing every
// required column (per the schema commit cited in tides.go) and one row.
const validCSV = "passenger_event_id,service_date,event_timestamp,trip_id_performed,trip_stop_sequence,event_type,vehicle_id,event_count\n" +
	"pe-1,2026-07-08,2026-07-08T12:00:00Z,trip-1,1,Passenger boarded,veh-1,2\n"

// missingColumnCSV lacks the required vehicle_id column.
const missingColumnCSV = "passenger_event_id,service_date,event_timestamp,trip_stop_sequence,event_type\n" +
	"pe-1,2026-07-08,2026-07-08T12:00:00Z,1,Passenger boarded\n"

func newTestScanner(t *testing.T) (*Scanner, *producer.Fake, *FakeStore, string) {
	t.Helper()
	dir := t.TempDir()
	fakeProd := producer.NewFake()
	fakeStore := NewFakeStore()
	s := &Scanner{
		Dir:      dir,
		Store:    fakeStore,
		Producer: fakeProd,
		Log:      slog.New(slog.NewTextHandler(testWriter{t}, nil)),
		Clock:    func() time.Time { return time.Date(2026, 7, 10, 12, 0, 0, 0, time.UTC) },
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

func TestScanOnceEnvelopeCorrectness(t *testing.T) {
	s, fakeProd, fakeStore, dir := newTestScanner(t)
	dropFile(t, dir, "passenger_events_2026-07-08.csv", validCSV)

	if err := s.ScanOnce(context.Background()); err != nil {
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
	wantKey := "raw/tides/" + wantID + ".csv"
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
	if m["source"] != DefaultSource || m["connector"] != ConnectorName || m["content_type"] != ContentType {
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

func TestMissingRequiredColumnStillLandedAndProducedAsMalformed(t *testing.T) {
	s, fakeProd, fakeStore, dir := newTestScanner(t)
	dropFile(t, dir, "passenger_events_bad.csv", missingColumnCSV)

	if err := s.ScanOnce(context.Background()); err != nil {
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
	if s, _ := m["parse_error"].(string); s == "" {
		t.Errorf("parse_error missing on malformed envelope")
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
	if _, err := os.Stat(filepath.Join(dir, ProcessedDir, "passenger_events_bad.csv")); err != nil {
		t.Errorf("malformed file not moved to processed/: %v", err)
	}
}

func TestSourceRespected(t *testing.T) {
	// The simulator drop rule (handoff 0005): TIDES_SOURCE=tides_simulated
	// must flow to the envelope source verbatim.
	s, fakeProd, _, dir := newTestScanner(t)
	s.Source = "tides_simulated"
	dropFile(t, dir, "passenger_events.csv", validCSV)

	if err := s.ScanOnce(context.Background()); err != nil {
		t.Fatalf("ScanOnce: %v", err)
	}
	msgs := fakeProd.Messages()
	if len(msgs) != 1 {
		t.Fatalf("produced %d messages, want 1", len(msgs))
	}
	var m map[string]any
	if err := json.Unmarshal(msgs[0].Value, &m); err != nil {
		t.Fatalf("envelope not JSON: %v", err)
	}
	if m["source"] != "tides_simulated" {
		t.Errorf("source = %v, want tides_simulated", m["source"])
	}
}

func TestProcessedMoveMakesRescanIdempotent(t *testing.T) {
	s, fakeProd, _, dir := newTestScanner(t)
	path := dropFile(t, dir, "passenger_events_a.csv", validCSV)

	if err := s.ScanOnce(context.Background()); err != nil {
		t.Fatalf("first ScanOnce: %v", err)
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Errorf("file still present in drop dir after processing")
	}
	moved := filepath.Join(dir, ProcessedDir, "passenger_events_a.csv")
	got, err := os.ReadFile(moved)
	if err != nil {
		t.Fatalf("processed file missing: %v", err)
	}
	if !bytes.Equal(got, []byte(validCSV)) {
		t.Errorf("processed file bytes were mutated")
	}

	// Re-scan produces nothing: the file is out of the pattern's reach.
	if err := s.ScanOnce(context.Background()); err != nil {
		t.Fatalf("second ScanOnce: %v", err)
	}
	if got := len(fakeProd.Messages()); got != 1 {
		t.Fatalf("re-scan re-produced: %d messages, want 1", got)
	}
}

func TestNonMatchingFilesIgnored(t *testing.T) {
	s, fakeProd, _, dir := newTestScanner(t)
	dropFile(t, dir, "notes.txt", "not a drop file")
	dropFile(t, dir, "vehicle_locations.csv", "also not passenger events")

	if err := s.ScanOnce(context.Background()); err != nil {
		t.Fatalf("ScanOnce: %v", err)
	}
	if got := len(fakeProd.Messages()); got != 0 {
		t.Fatalf("non-matching files produced %d messages, want 0", got)
	}
}

func TestStoreFailureBlocksProduceAndLeavesFile(t *testing.T) {
	s, fakeProd, fakeStore, dir := newTestScanner(t)
	fakeStore.Err = context.DeadlineExceeded
	path := dropFile(t, dir, "passenger_events.csv", validCSV)

	if err := s.ScanOnce(context.Background()); err == nil {
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
