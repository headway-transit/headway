package sqlsource

import (
	"context"
	"database/sql/driver"
	"encoding/json"
	"log/slog"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/headway-transit/headway/services/ingestion/connectors/vendorfile"
	"github.com/headway-transit/headway/services/ingestion/internal/envelope"
	"github.com/headway-transit/headway/services/ingestion/internal/producer"
)

// tripsparkColumns is the first real adapter's declared positional shape
// (adapters/tripspark/streets/mapping.v0.yaml, 18 headerless columns) — the
// exact column-order contract a rendered batch must reproduce.
var tripsparkColumns = []string{
	"VehicleLocationAPCKey", "VehicleName", "TotalCount", "BoardCount",
	"AlightCount", "UnmodifiedAlightCount", "APCSource", "IsTripper",
	"IsDetour", "TripName", "RouteName", "RouteShortName", "PatternName",
	"StopName", "StopCode", "PatternPointRank", "DirectionKey", "EventDateISO",
}

// Two synthetic warehouse rows (all values invented). Row 2 exercises the
// deterministic renderings: bool -> 1/0, NULL -> empty, []byte -> verbatim.
var apcRow1 = []driver.Value{
	int64(101), "BUS-12", int64(14), int64(2), int64(0), int64(0), "APC",
	false, false, "7 - A - 08:00", "Route 7", "7", "A", "Main St & 1st",
	"1001", int64(4), int64(1), "2026-07-30T08:15:00",
}
var apcRow2 = []driver.Value{
	int64(102), "BUS-12", int64(15), int64(1), int64(1), nil, "APC",
	true, false, "7 - A - 08:00", "Route 7", "7", "A", []byte("2nd Ave & Oak"),
	"1002", int64(5), int64(1), "2026-07-30T08:17:00",
}

// wantCSV is the exact positional, headerless rendering of the two rows —
// the shape the registered adapter's mapping spec declares.
const wantCSV = "101,BUS-12,14,2,0,0,APC,0,0,7 - A - 08:00,Route 7,7,A,Main St & 1st,1001,4,1,2026-07-30T08:15:00\n" +
	"102,BUS-12,15,1,1,,APC,1,0,7 - A - 08:00,Route 7,7,A,2nd Ave & Oak,1002,5,1,2026-07-30T08:17:00\n"

type testWriter struct{ t *testing.T }

func (w testWriter) Write(p []byte) (int, error) { w.t.Log(string(p)); return len(p), nil }

func newTestPoller(t *testing.T, results ...fakeResult) (*Poller, *fakeDB, *producer.Fake, *vendorfile.FakeStore) {
	t.Helper()
	db, fdb := openFake(results...)
	t.Cleanup(func() { _ = db.Close() })
	fakeProd := producer.NewFake()
	fakeStore := vendorfile.NewFakeStore()
	p := &Poller{
		DB:           db,
		View:         "dbo.vw_headway_apc",
		Columns:      append([]string(nil), tripsparkColumns...),
		CursorColumn: "VehicleLocationAPCKey",
		Source:       "tripspark_streets",
		StateDir:     t.TempDir(),
		// Every existing test predates SQLSOURCE_START_AFTER and relied on
		// the old "read from the beginning" default. "0" preserves exactly
		// that behaviour, so these tests keep testing what they were written
		// to test — while the DEFAULT is now a refusal rather than a
		// full-history read. The refusal has its own tests below.
		StartAfter:   "0",
		Store:        fakeStore,
		Producer:     fakeProd,
		Log:          slog.New(slog.NewTextHandler(testWriter{t}, nil)),
		Clock:        func() time.Time { return time.Date(2026, 7, 30, 12, 0, 0, 0, time.UTC) },
	}
	return p, fdb, fakeProd, fakeStore
}

// mkRow builds a full-width synthetic row whose cursor is key.
func mkRow(key int64) []driver.Value {
	row := append([]driver.Value(nil), apcRow1...)
	row[0] = key
	return row
}

func TestPollOnceRendersLandsAndProduces(t *testing.T) {
	p, fdb, fakeProd, fakeStore := newTestPoller(t,
		fakeResult{cols: tripsparkColumns, rows: [][]driver.Value{apcRow1, apcRow2}})

	if err := p.PollOnce(context.Background()); err != nil {
		t.Fatalf("PollOnce: %v", err)
	}

	// First-ever poll. There IS a WHERE clause now, and that is the change:
	// the first read is bounded by the operator's declared SQLSOURCE_START_AFTER
	// (here "0", preserving this test's original full-view intent) rather than
	// being unbounded. An unbounded first read is what filled 123 GB of
	// database against a real 84-million-row warehouse view.
	queries := fdb.recorded()
	if len(queries) != 1 {
		t.Fatalf("recorded %d queries, want 1", len(queries))
	}
	wantQuery := "SELECT TOP (5000) [VehicleLocationAPCKey], [VehicleName], " +
		"[TotalCount], [BoardCount], [AlightCount], [UnmodifiedAlightCount], " +
		"[APCSource], [IsTripper], [IsDetour], [TripName], [RouteName], " +
		"[RouteShortName], [PatternName], [StopName], [StopCode], " +
		"[PatternPointRank], [DirectionKey], [EventDateISO] " +
		"FROM [dbo].[vw_headway_apc] WHERE [VehicleLocationAPCKey] > @p1 " +
		"ORDER BY [VehicleLocationAPCKey] ASC"
	if queries[0].query != wantQuery {
		t.Errorf("query =\n%q\nwant\n%q", queries[0].query, wantQuery)
	}

	msgs := fakeProd.Messages()
	if len(msgs) != 1 {
		t.Fatalf("produced %d messages, want 1", len(msgs))
	}
	if msgs[0].Topic != vendorfile.Topic {
		t.Errorf("topic = %q, want %q (one pipeline, two intakes)", msgs[0].Topic, vendorfile.Topic)
	}
	wantID := envelope.RecordID([]byte(wantCSV))
	wantKey := vendorfile.ObjectKey(wantID)
	var m map[string]any
	if err := json.Unmarshal(msgs[0].Value, &m); err != nil {
		t.Fatalf("envelope not JSON: %v", err)
	}
	if m["record_id"] != wantID || string(msgs[0].Key) != wantID {
		t.Errorf("record_id = %v / key %q, want %v", m["record_id"], msgs[0].Key, wantID)
	}
	if m["payload"] != wantKey || m["payload_encoding"] != envelope.EncodingObjectRef {
		t.Errorf("payload = %v (%v), want object key %v", m["payload"], m["payload_encoding"], wantKey)
	}
	if m["source"] != "tripspark_streets" || m["connector"] != ConnectorName {
		t.Errorf("identity fields wrong: %v / %v", m["source"], m["connector"])
	}
	if m["parse_status"] != envelope.ParseOK {
		t.Errorf("parse_status = %v, want ok (content checks belong to the adapter runtime)", m["parse_status"])
	}
	stored, ok := fakeStore.Get(wantKey)
	if !ok || string(stored) != wantCSV {
		t.Errorf("landed bytes are not the exact positional rendering:\n%q\nwant\n%q", stored, wantCSV)
	}

	// High-water mark persisted with contract identity.
	raw, err := os.ReadFile(StatePath(p.StateDir, p.Source))
	if err != nil {
		t.Fatalf("state file: %v", err)
	}
	var s hwState
	if err := json.Unmarshal(raw, &s); err != nil {
		t.Fatalf("state not JSON: %v", err)
	}
	if s.HighWater != "102" || s.View != "dbo.vw_headway_apc" || s.CursorColumn != "VehicleLocationAPCKey" {
		t.Errorf("state = %+v, want high_water 102 with the configured contract", s)
	}
}

func TestRestartResumesFromPersistedHighWater(t *testing.T) {
	p1, _, _, _ := newTestPoller(t,
		fakeResult{cols: tripsparkColumns, rows: [][]driver.Value{apcRow1, apcRow2}})
	if err := p1.PollOnce(context.Background()); err != nil {
		t.Fatalf("first PollOnce: %v", err)
	}

	// A NEW poller (fresh process) over the same state dir must resume,
	// never re-read history.
	p2, fdb2, fakeProd2, _ := newTestPoller(t, fakeResult{cols: tripsparkColumns})
	p2.StateDir = p1.StateDir
	if err := p2.PollOnce(context.Background()); err != nil {
		t.Fatalf("resumed PollOnce: %v", err)
	}
	queries := fdb2.recorded()
	if len(queries) != 1 {
		t.Fatalf("recorded %d queries, want 1", len(queries))
	}
	if !strings.Contains(queries[0].query, "WHERE [VehicleLocationAPCKey] > @p1") {
		t.Errorf("resumed query lacks the keyset predicate: %q", queries[0].query)
	}
	if len(queries[0].args) != 1 || queries[0].args[0].Name != "p1" || queries[0].args[0].Value != int64(102) {
		t.Errorf("keyset parameter = %+v, want p1=102", queries[0].args)
	}
	if len(fakeProd2.Messages()) != 0 {
		t.Error("an empty batch must land nothing (an empty file is not evidence)")
	}
}

func TestDeletedStateReplayIsIdempotentByContentAddress(t *testing.T) {
	p1, _, prod1, _ := newTestPoller(t,
		fakeResult{cols: tripsparkColumns, rows: [][]driver.Value{apcRow1, apcRow2}})
	if err := p1.PollOnce(context.Background()); err != nil {
		t.Fatalf("first PollOnce: %v", err)
	}
	if err := os.Remove(StatePath(p1.StateDir, p1.Source)); err != nil {
		t.Fatalf("delete state: %v", err)
	}

	p2, _, prod2, _ := newTestPoller(t,
		fakeResult{cols: tripsparkColumns, rows: [][]driver.Value{apcRow1, apcRow2}})
	p2.StateDir = p1.StateDir
	if err := p2.PollOnce(context.Background()); err != nil {
		t.Fatalf("replayed PollOnce: %v", err)
	}
	id1 := string(prod1.Messages()[0].Key)
	id2 := string(prod2.Messages()[0].Key)
	if id1 != id2 {
		t.Errorf("replayed batch landed a DIFFERENT record_id (%s vs %s) — accidental replay must be harmless", id1, id2)
	}
}

func TestBatchCapPaginatesUntilShortBatch(t *testing.T) {
	p, fdb, fakeProd, _ := newTestPoller(t,
		fakeResult{cols: tripsparkColumns, rows: [][]driver.Value{mkRow(1), mkRow(2)}},
		fakeResult{cols: tripsparkColumns, rows: [][]driver.Value{mkRow(3), mkRow(4)}},
		fakeResult{cols: tripsparkColumns, rows: [][]driver.Value{mkRow(5)}},
	)
	p.BatchMaxRows = 2
	if err := p.PollOnce(context.Background()); err != nil {
		t.Fatalf("PollOnce: %v", err)
	}
	queries := fdb.recorded()
	if len(queries) != 3 {
		t.Fatalf("recorded %d queries, want 3 (2+2+1 rows, stop on short batch)", len(queries))
	}
	if len(queries[1].args) != 1 || queries[1].args[0].Value != int64(2) {
		t.Errorf("batch 2 keyset parameter = %+v, want 2", queries[1].args)
	}
	if len(queries[2].args) != 1 || queries[2].args[0].Value != int64(4) {
		t.Errorf("batch 3 keyset parameter = %+v, want 4", queries[2].args)
	}
	if got := len(fakeProd.Messages()); got != 3 {
		t.Errorf("produced %d batches, want 3", got)
	}
	var s hwState
	raw, _ := os.ReadFile(StatePath(p.StateDir, p.Source))
	_ = json.Unmarshal(raw, &s)
	if s.HighWater != "5" {
		t.Errorf("final high_water = %s, want 5", s.HighWater)
	}
}

func TestColumnMismatchRefusedWholeNothingLanded(t *testing.T) {
	wrong := append([]string(nil), tripsparkColumns...)
	wrong[3], wrong[4] = wrong[4], wrong[3] // BoardCount/AlightCount swapped
	p, _, fakeProd, _ := newTestPoller(t,
		fakeResult{cols: wrong, rows: [][]driver.Value{apcRow1}})
	err := p.PollOnce(context.Background())
	if err == nil || !strings.Contains(err.Error(), "SQLSOURCE_COLUMNS") ||
		!strings.Contains(err.Error(), "wrong_width") {
		t.Fatalf("column-order mismatch not refused with the contract named: %v", err)
	}
	if len(fakeProd.Messages()) != 0 {
		t.Error("mismatched batch was produced")
	}
	if _, err := os.Stat(StatePath(p.StateDir, p.Source)); err == nil {
		t.Error("high-water mark advanced past a refused batch")
	}
}

func TestNullCursorRefused(t *testing.T) {
	row := mkRow(1)
	row[0] = nil
	p, _, fakeProd, _ := newTestPoller(t,
		fakeResult{cols: tripsparkColumns, rows: [][]driver.Value{row}})
	err := p.PollOnce(context.Background())
	if err == nil || !strings.Contains(err.Error(), "NULL") {
		t.Fatalf("NULL cursor not refused loudly: %v", err)
	}
	if len(fakeProd.Messages()) != 0 {
		t.Error("batch with an unorderable row was produced")
	}
}

func TestNonIntegerCursorRefused(t *testing.T) {
	row := mkRow(1)
	row[0] = "2026-07-30T08:15:00"
	p, _, _, _ := newTestPoller(t,
		fakeResult{cols: tripsparkColumns, rows: [][]driver.Value{row}})
	err := p.PollOnce(context.Background())
	if err == nil || !strings.Contains(err.Error(), "integer cursors only") {
		t.Fatalf("non-integer cursor not refused with the v0 scope named: %v", err)
	}
}

func TestUnformattableTypeRefusedNamingColumnAndFix(t *testing.T) {
	row := mkRow(1)
	row[17] = time.Date(2026, 7, 30, 8, 15, 0, 0, time.UTC) // a datetime, not a varchar
	p, _, fakeProd, _ := newTestPoller(t,
		fakeResult{cols: tripsparkColumns, rows: [][]driver.Value{row}})
	err := p.PollOnce(context.Background())
	if err == nil || !strings.Contains(err.Error(), "EventDateISO") ||
		!strings.Contains(err.Error(), "CAST") {
		t.Fatalf("unformattable column not refused with the view-side fix named: %v", err)
	}
	if len(fakeProd.Messages()) != 0 {
		t.Error("batch with a Headway-formatted cell was produced")
	}
}

func TestBoundaryTieOnFullBatchRefused(t *testing.T) {
	r1, r2 := mkRow(5), mkRow(5) // duplicate cursor at the cap boundary
	p, _, fakeProd, _ := newTestPoller(t,
		fakeResult{cols: tripsparkColumns, rows: [][]driver.Value{r1, r2}})
	p.BatchMaxRows = 2
	err := p.PollOnce(context.Background())
	if err == nil || !strings.Contains(err.Error(), "tied boundary") &&
		!strings.Contains(err.Error(), "share cursor value") {
		t.Fatalf("tied boundary on a full batch not refused: %v", err)
	}
	if len(fakeProd.Messages()) != 0 {
		t.Error("batch that could skip rows was produced")
	}
}

func TestMidBatchTieAllowedWhenBatchIsShort(t *testing.T) {
	r1, r2, r3 := mkRow(4), mkRow(5), mkRow(5)
	p, _, fakeProd, _ := newTestPoller(t,
		fakeResult{cols: tripsparkColumns, rows: [][]driver.Value{r1, r2, r3}})
	p.BatchMaxRows = 10 // short batch: every tied row is inside this batch
	if err := p.PollOnce(context.Background()); err != nil {
		t.Fatalf("short batch with an internal tie must ingest (no skip risk): %v", err)
	}
	if len(fakeProd.Messages()) != 1 {
		t.Errorf("produced %d, want 1", len(fakeProd.Messages()))
	}
}

func TestSimMarkedContentUnderRealLabelRefused(t *testing.T) {
	row := mkRow(1)
	row[1] = "sim:2026-07-30:1207:1"
	p, _, fakeProd, fakeStore := newTestPoller(t,
		fakeResult{cols: tripsparkColumns, rows: [][]driver.Value{row}})
	err := p.PollOnce(context.Background())
	if err == nil || !strings.Contains(err.Error(), "simulator marker") {
		t.Fatalf("sim-marked row under real label not refused: %v", err)
	}
	if len(fakeProd.Messages()) != 0 {
		t.Error("simulated content was produced under a real label")
	}
	if len(fakeStore.Keys()) != 0 {
		t.Error("simulated content was landed under a real label")
	}
}

func TestSimMarkedContentUnderSimulatedLabelIngested(t *testing.T) {
	row := mkRow(1)
	row[1] = "sim:2026-07-30:1207:1"
	p, _, fakeProd, _ := newTestPoller(t,
		fakeResult{cols: tripsparkColumns, rows: [][]driver.Value{row}})
	p.Source = "tripspark_streets_simulated"
	if err := p.PollOnce(context.Background()); err != nil {
		t.Fatalf("PollOnce under _simulated label: %v", err)
	}
	msgs := fakeProd.Messages()
	if len(msgs) != 1 {
		t.Fatalf("produced %d, want 1", len(msgs))
	}
	var m map[string]any
	_ = json.Unmarshal(msgs[0].Value, &m)
	if m["source"] != "tripspark_streets_simulated" {
		t.Errorf("source = %v, want the simulated label carried verbatim", m["source"])
	}
}

func TestProduceFailureDoesNotAdvanceHighWater(t *testing.T) {
	p, _, fakeProd, _ := newTestPoller(t,
		fakeResult{cols: tripsparkColumns, rows: [][]driver.Value{apcRow1}},
		fakeResult{cols: tripsparkColumns, rows: [][]driver.Value{apcRow1}})
	fakeProd.Err = os.ErrDeadlineExceeded
	if err := p.PollOnce(context.Background()); err == nil {
		t.Fatal("produce failure not reported")
	}
	if _, err := os.Stat(StatePath(p.StateDir, p.Source)); err == nil {
		t.Fatal("high-water mark advanced past an unproduced batch (rows would be lost)")
	}
	// Broker back: the SAME batch is re-read and produced (at-least-once).
	fakeProd.Err = nil
	if err := p.PollOnce(context.Background()); err != nil {
		t.Fatalf("retry PollOnce: %v", err)
	}
	if len(fakeProd.Messages()) != 1 {
		t.Fatalf("retry did not re-produce the batch")
	}
}

func TestStoreFailureBlocksProduce(t *testing.T) {
	p, _, fakeProd, fakeStore := newTestPoller(t,
		fakeResult{cols: tripsparkColumns, rows: [][]driver.Value{apcRow1}})
	fakeStore.Err = os.ErrPermission
	if err := p.PollOnce(context.Background()); err == nil {
		t.Fatal("store failure not reported")
	}
	if len(fakeProd.Messages()) != 0 {
		t.Fatal("produced an envelope whose object was never landed")
	}
}

func TestStateContractMismatchRefused(t *testing.T) {
	p1, _, _, _ := newTestPoller(t,
		fakeResult{cols: tripsparkColumns, rows: [][]driver.Value{apcRow1}})
	if err := p1.PollOnce(context.Background()); err != nil {
		t.Fatalf("PollOnce: %v", err)
	}
	p2, _, _, _ := newTestPoller(t)
	p2.StateDir = p1.StateDir
	p2.CursorColumn = "PatternPointRank" // different contract, same file
	p2.Columns = append([]string(nil), tripsparkColumns...)
	err := p2.PollOnce(context.Background())
	if err == nil || !strings.Contains(err.Error(), "DELIBERATELY") {
		t.Fatalf("state recorded under a different contract not refused: %v", err)
	}
}

func TestCheckRefusalsNameTheEnvVar(t *testing.T) {
	cases := []struct {
		name   string
		mutate func(*Poller)
		want   string
	}{
		{"no db", func(p *Poller) { p.DB = nil }, "SQLSOURCE_DSN"},
		{"no view", func(p *Poller) { p.View = "" }, "SQLSOURCE_VIEW"},
		{"injection in view", func(p *Poller) { p.View = "dbo.vw; DROP TABLE x" }, "SQLSOURCE_VIEW"},
		{"no columns", func(p *Poller) { p.Columns = nil }, "SQLSOURCE_COLUMNS"},
		{"select star", func(p *Poller) { p.Columns = []string{"*"} }, "ADR-0013"},
		{"injection in column", func(p *Poller) { p.Columns[2] = "x; DROP TABLE y" }, "not a plain column name"},
		{"duplicate column", func(p *Poller) { p.Columns[1] = p.Columns[0] }, "twice"},
		{"no cursor", func(p *Poller) { p.CursorColumn = "" }, "SQLSOURCE_CURSOR_COLUMN"},
		{"cursor not declared", func(p *Poller) { p.CursorColumn = "SomethingElse" }, "not in SQLSOURCE_COLUMNS"},
		{"no label", func(p *Poller) { p.Source = "" }, "SQLSOURCE_ADAPTER_LABEL"},
		{"bad label", func(p *Poller) { p.Source = "TripSpark Streets" }, "lowercase"},
		{"no state dir", func(p *Poller) { p.StateDir = "" }, "SQLSOURCE_STATE_DIR"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			p, _, _, _ := newTestPoller(t)
			tc.mutate(p)
			err := p.Check()
			if err == nil || !strings.Contains(err.Error(), tc.want) {
				t.Fatalf("Check() = %v, want a refusal containing %q", err, tc.want)
			}
		})
	}
}

func TestOpenDBNeverEchoesTheSecret(t *testing.T) {
	if _, err := OpenDB(""); err == nil || !strings.Contains(err.Error(), "SQLSOURCE_DSN") {
		t.Fatalf("empty DSN not refused: %v", err)
	}
	// A malformed DSN carrying a password: whatever the driver does, the
	// secret must never appear in the returned error.
	_, err := OpenDB("sqlserver://headway_ro:hunter2SECRET@bad host:notaport?database=x")
	if err != nil && strings.Contains(err.Error(), "hunter2SECRET") {
		t.Fatalf("DSN parse error echoed the credential: %v", err)
	}
}

func TestRunPollsPeriodicallyAndStopsOnCancel(t *testing.T) {
	p, _, fakeProd, _ := newTestPoller(t,
		fakeResult{cols: tripsparkColumns, rows: [][]driver.Value{apcRow1}},
		fakeResult{cols: tripsparkColumns},
		fakeResult{cols: tripsparkColumns},
	)
	p.Interval = 10 * time.Millisecond
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- p.Run(ctx) }()

	deadline := time.After(2 * time.Second)
	for len(fakeProd.Messages()) == 0 {
		select {
		case <-deadline:
			cancel()
			t.Fatal("Run never produced the scripted batch")
		case <-time.After(5 * time.Millisecond):
		}
	}
	cancel()
	if err := <-done; err != context.Canceled {
		t.Fatalf("Run returned %v, want context.Canceled", err)
	}
}

// --- SQLSOURCE_START_AFTER: the bound that was missing -----------------------
//
// The first agency to connect a real warehouse pointed this connector at an
// APC view of roughly 84 million rows. With no high-water mark it read from
// the beginning of the view, wrote 123 GB into the database, and the operator
// — who had just been handed a working connection — found out from a
// low-disk-space notification with 1.1 GB left. Nothing warned him, because
// nothing knew it was unusual.
//
// A starting point is now a declared decision. These tests are the reason to
// believe it stays one.

func TestFirstRunRefusesWithoutADeclaredStartingPoint(t *testing.T) {
	p, _, _, _ := newTestPoller(t)
	p.StartAfter = ""

	err := p.PollOnce(context.Background())
	if err == nil {
		t.Fatal("expected a refusal with no SQLSOURCE_START_AFTER, got none")
	}
	msg := err.Error()
	// The refusal has to teach, not just refuse: an operator reading it must
	// learn what to set and why it has no default.
	for _, want := range []string{
		"SQLSOURCE_START_AFTER",
		"whole view from the beginning",
		"years of history",
		"0 if you genuinely want the entire history",
	} {
		if !strings.Contains(msg, want) {
			t.Errorf("refusal does not mention %q:\n%s", want, msg)
		}
	}
}

func TestFirstRunStartsAfterTheDeclaredCursor(t *testing.T) {
	// THE POINT: a recent cursor value means recent data only. The query is
	// bounded by what the operator asked for, not by the size of their table.
	p, fdb, _, _ := newTestPoller(t, fakeResult{cols: tripsparkColumns})
	p.StartAfter = "84000000"

	if err := p.PollOnce(context.Background()); err != nil {
		t.Fatalf("PollOnce: %v", err)
	}
	queries := fdb.recorded()
	if len(queries) != 1 {
		t.Fatalf("recorded %d queries, want 1", len(queries))
	}
	if !strings.Contains(queries[0].query, "WHERE [VehicleLocationAPCKey] > @p1") {
		t.Errorf("first query is not bounded:\n%s", queries[0].query)
	}
	if len(queries[0].args) != 1 {
		t.Fatalf("expected one bound argument, got %d", len(queries[0].args))
	}
	if got, ok := queries[0].args[0].Value.(int64); !ok || got != 84000000 {
		t.Errorf("first read started after %v, want 84000000", queries[0].args[0].Value)
	}
}

func TestStartAfterMustBeAWholeNumber(t *testing.T) {
	// The cursor column is an integer key. A date or a name here would be a
	// silent full-table read if it were coerced, so it is refused instead.
	p, _, _, _ := newTestPoller(t)
	p.StartAfter = "2026-08-01"

	err := p.PollOnce(context.Background())
	if err == nil {
		t.Fatal("expected a refusal for a non-integer starting point")
	}
	if !strings.Contains(err.Error(), "not a whole number") {
		t.Errorf("refusal does not explain the problem:\n%s", err)
	}
}

func TestSavedPositionOutranksTheDeclaredStartingPoint(t *testing.T) {
	// Once the connector has run, the mark on disk is the truth. If
	// StartAfter kept winning, every restart would re-read from it and
	// duplicate work forever — and an operator who set it low would silently
	// replay history on every deploy.
	p, fdb, _, _ := newTestPoller(t, fakeResult{cols: tripsparkColumns}, fakeResult{cols: tripsparkColumns})
	p.StartAfter = "100"

	if err := p.PollOnce(context.Background()); err != nil {
		t.Fatalf("first PollOnce: %v", err)
	}
	// Advance the mark as a real batch would, then reload from disk.
	p.hw, p.hwSet, p.hwLoaded = 500, true, true
	if err := p.saveState(); err != nil {
		t.Fatalf("saveState: %v", err)
	}
	p.hwLoaded, p.hwSet, p.hw = false, false, 0

	if err := p.PollOnce(context.Background()); err != nil {
		t.Fatalf("second PollOnce: %v", err)
	}
	queries := fdb.recorded()
	last := queries[len(queries)-1]
	if got, ok := last.args[0].Value.(int64); !ok || got != 500 {
		t.Errorf("resumed after %v, want the saved 500 — not StartAfter", last.args[0].Value)
	}
}
