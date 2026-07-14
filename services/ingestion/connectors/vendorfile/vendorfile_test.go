package vendorfile

import (
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

// vendorCSV is a fragment of the reference adapter's invented RideLog
// format (semicolon dialect) — this connector must land ANY vendor dialect
// byte-for-byte without interpreting it.
const vendorCSV = "Acme Transit Suite - RideLog daily unit export\n" +
	"Units: ALL\n" +
	"RecType;Seq;UnitNo;LocalTime;Dir;Cnt;StopSeq\n" +
	"CNT;00001;1207;03/07/2026 08:15:00;B;2;1\n"

// simulatedSemicolonCSV carries the structural simulator marker inside a
// NON-comma dialect — the marker scan must still find it.
const simulatedSemicolonCSV = "RecType;Seq;UnitNo;LocalTime;Dir;Cnt;StopSeq\n" +
	"CNT;sim:2026-07-13:1207:1;1207;03/07/2026 08:15:00;B;2;1\n"

func newTestScanner(t *testing.T) (*Scanner, *producer.Fake, *FakeStore, string) {
	t.Helper()
	dir := t.TempDir()
	fakeProd := producer.NewFake()
	fakeStore := NewFakeStore()
	s := &Scanner{
		Dir:      dir,
		Source:   "acme_ridelog", // explicit — there is no default (fail closed)
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
// for the partial-copy stability guard, the second ingests stable ones.
func scanTwice(t *testing.T, s *Scanner) error {
	t.Helper()
	if err := s.ScanOnce(context.Background()); err != nil {
		t.Fatalf("first (observation) ScanOnce: %v", err)
	}
	return s.ScanOnce(context.Background())
}

func TestScanOnceEnvelopeCorrectness(t *testing.T) {
	s, fakeProd, fakeStore, dir := newTestScanner(t)
	dropFile(t, dir, "ridelog_2026-03-07.csv", vendorCSV)

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
	wantID := envelope.RecordID([]byte(vendorCSV))
	wantKey := "raw/vendor/" + wantID + ".csv"
	if m["record_id"] != wantID {
		t.Errorf("record_id = %v, want %v (content address of the ORIGINAL vendor bytes)", m["record_id"], wantID)
	}
	if string(msgs[0].Key) != wantID {
		t.Errorf("message key = %q, want record_id", msgs[0].Key)
	}
	if m["payload"] != wantKey {
		t.Errorf("payload = %v, want object key %v", m["payload"], wantKey)
	}
	if m["parse_status"] != envelope.ParseOK {
		t.Errorf("parse_status = %v, want ok (content checks belong to the adapter runtime)", m["parse_status"])
	}
	if m["source"] != "acme_ridelog" || m["connector"] != ConnectorName {
		t.Errorf("identity fields wrong: %v/%v", m["source"], m["connector"])
	}
	stored, ok := fakeStore.Get(wantKey)
	if !ok || string(stored) != vendorCSV {
		t.Errorf("object store does not hold the exact original bytes")
	}
}

func TestGrowingFileNotIngestedUntilStable(t *testing.T) {
	s, fakeProd, _, dir := newTestScanner(t)
	path := dropFile(t, dir, "export.csv", "partial")

	if err := s.ScanOnce(context.Background()); err != nil {
		t.Fatalf("scan 1: %v", err)
	}
	// The file grows between scans (copy still in progress) — and its
	// mtime moves too.
	if err := os.WriteFile(path, []byte(vendorCSV), 0o644); err != nil {
		t.Fatalf("grow file: %v", err)
	}
	future := time.Now().Add(2 * time.Second)
	if err := os.Chtimes(path, future, future); err != nil {
		t.Fatalf("chtimes: %v", err)
	}
	if err := s.ScanOnce(context.Background()); err != nil {
		t.Fatalf("scan 2: %v", err)
	}
	if got := len(fakeProd.Messages()); got != 0 {
		t.Fatalf("unstable file was ingested (%d messages) — partial-copy guard broken", got)
	}
	// Third scan: now unchanged since scan 2 -> ingested with FINAL bytes.
	if err := s.ScanOnce(context.Background()); err != nil {
		t.Fatalf("scan 3: %v", err)
	}
	msgs := fakeProd.Messages()
	if len(msgs) != 1 {
		t.Fatalf("stable file not ingested (got %d messages)", len(msgs))
	}
	var m map[string]any
	_ = json.Unmarshal(msgs[0].Value, &m)
	if m["record_id"] != envelope.RecordID([]byte(vendorCSV)) {
		t.Errorf("ingested record is not the final complete bytes")
	}
}

func TestEmptySourceRefusedAtScan(t *testing.T) {
	s, fakeProd, _, dir := newTestScanner(t)
	s.Source = "   "
	dropFile(t, dir, "export.csv", vendorCSV)
	err := s.ScanOnce(context.Background())
	if err == nil || !strings.Contains(err.Error(), "VENDOR_SOURCE") {
		t.Fatalf("empty source not refused: %v", err)
	}
	if len(fakeProd.Messages()) != 0 {
		t.Fatal("message produced without a source label")
	}
}

func TestSimulatorMarkedContentUnderRealSourceRefused(t *testing.T) {
	s, fakeProd, fakeStore, dir := newTestScanner(t)
	dropFile(t, dir, "export.csv", simulatedSemicolonCSV)

	err := scanTwice(t, s)
	if err == nil || !strings.Contains(err.Error(), "simulator marker") {
		t.Fatalf("sim-marked content under real label not refused: %v", err)
	}
	if len(fakeProd.Messages()) != 0 {
		t.Fatal("refused file was still produced")
	}
	if got, _ := fakeStore.Get(ObjectKey(envelope.RecordID([]byte(simulatedSemicolonCSV)))); got != nil {
		t.Fatal("refused file was still landed")
	}
	if _, err := os.Stat(filepath.Join(dir, RejectedDir, "export.csv")); err != nil {
		t.Fatalf("refused file not preserved in rejected/: %v", err)
	}
}

func TestSimulatorMarkedContentUnderSimulatedSourceIngested(t *testing.T) {
	s, fakeProd, _, dir := newTestScanner(t)
	s.Source = "acme_ridelog_simulated"
	dropFile(t, dir, "export.csv", simulatedSemicolonCSV)
	if err := scanTwice(t, s); err != nil {
		t.Fatalf("scan: %v", err)
	}
	msgs := fakeProd.Messages()
	if len(msgs) != 1 {
		t.Fatalf("simulated drop under _simulated label not ingested (%d msgs)", len(msgs))
	}
	var m map[string]any
	_ = json.Unmarshal(msgs[0].Value, &m)
	if m["source"] != "acme_ridelog_simulated" {
		t.Errorf("source = %v, want acme_ridelog_simulated", m["source"])
	}
}

func TestOversizeFileRejected(t *testing.T) {
	s, fakeProd, _, dir := newTestScanner(t)
	s.MaxFileBytes = 16
	dropFile(t, dir, "big.csv", strings.Repeat("x", 64))
	err := s.ScanOnce(context.Background())
	if err == nil || !strings.Contains(err.Error(), "over the 16-byte limit") {
		t.Fatalf("oversize not refused: %v", err)
	}
	if len(fakeProd.Messages()) != 0 {
		t.Fatal("oversize file was produced")
	}
	if _, err := os.Stat(filepath.Join(dir, RejectedDir, "big.csv")); err != nil {
		t.Fatalf("oversize file not preserved in rejected/: %v", err)
	}
}

func TestProcessedMoveMakesRescanIdempotent(t *testing.T) {
	s, fakeProd, _, dir := newTestScanner(t)
	dropFile(t, dir, "export.csv", vendorCSV)
	if err := scanTwice(t, s); err != nil {
		t.Fatalf("scan: %v", err)
	}
	if err := scanTwice(t, s); err != nil {
		t.Fatalf("rescan: %v", err)
	}
	if got := len(fakeProd.Messages()); got != 1 {
		t.Fatalf("rescan re-produced (%d messages, want 1)", got)
	}
	if _, err := os.Stat(filepath.Join(dir, ProcessedDir, "export.csv")); err != nil {
		t.Fatalf("processed file not moved: %v", err)
	}
}

func TestNonMatchingFilesIgnored(t *testing.T) {
	s, fakeProd, _, dir := newTestScanner(t)
	dropFile(t, dir, "notes.txt", "not a csv")
	dropFile(t, dir, "export.csv.tmp", "still copying")
	if err := scanTwice(t, s); err != nil {
		t.Fatalf("scan: %v", err)
	}
	if len(fakeProd.Messages()) != 0 {
		t.Fatal("non-matching file was ingested")
	}
}

func TestStoreFailureBlocksProduceAndLeavesFile(t *testing.T) {
	s, fakeProd, fakeStore, dir := newTestScanner(t)
	fakeStore.Err = os.ErrPermission
	dropFile(t, dir, "export.csv", vendorCSV)
	if err := scanTwice(t, s); err == nil {
		t.Fatal("store failure not reported")
	}
	if len(fakeProd.Messages()) != 0 {
		t.Fatal("produced an envelope whose object was never landed")
	}
	if _, err := os.Stat(filepath.Join(dir, "export.csv")); err != nil {
		t.Fatalf("failed file must stay in the drop dir for re-scan: %v", err)
	}
}

func TestRunScansPeriodicallyAndStopsOnCancel(t *testing.T) {
	s, fakeProd, _, dir := newTestScanner(t)
	s.Interval = 10 * time.Millisecond
	dropFile(t, dir, "export.csv", vendorCSV)

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- s.Run(ctx) }()

	deadline := time.After(2 * time.Second)
	for len(fakeProd.Messages()) == 0 {
		select {
		case <-deadline:
			cancel()
			t.Fatal("Run never ingested the stable file")
		case <-time.After(5 * time.Millisecond):
		}
	}
	cancel()
	if err := <-done; err != context.Canceled {
		t.Fatalf("Run returned %v, want context.Canceled", err)
	}
}
