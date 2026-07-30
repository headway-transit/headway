package sqlsource

// Integration test against a real SQL Server — a DISPOSABLE
// mcr.microsoft.com/mssql/server container, NEVER an agency system (see the
// README verification statement: no agency server has ever been contacted).
//
// Skipped unless SQLSOURCE_IT_DSN is set, e.g.:
//
//	sg docker -c "docker run -d --name headway-0033-mssql \
//	  -e ACCEPT_EULA=Y -e 'MSSQL_SA_PASSWORD=<pw>' \
//	  -p 127.0.0.1:21433:1433 mcr.microsoft.com/mssql/server:2022-latest"
//	SQLSOURCE_IT_DSN='sqlserver://sa:<pw>@127.0.0.1:21433?database=master' \
//	  go test ./connectors/sqlsource/ -run Integration -count=1 -v
//
// The test creates its own throwaway table + views in the container's
// master database and drops them; the DML in setup is the TEST harness
// seeding fixture data — the connector under test still only ever SELECTs.

import (
	"context"
	"database/sql"
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

func integrationDB(t *testing.T) *sql.DB {
	t.Helper()
	dsn := os.Getenv("SQLSOURCE_IT_DSN")
	if dsn == "" {
		t.Skip("SQLSOURCE_IT_DSN not set; integration test needs the disposable mssql container (see file header)")
	}
	db, err := OpenDB(dsn)
	if err != nil {
		t.Fatalf("OpenDB: %v", err)
	}
	t.Cleanup(func() { _ = db.Close() })
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()
	for {
		if err := db.PingContext(ctx); err == nil {
			break
		} else if ctx.Err() != nil {
			t.Fatalf("SQL Server never became ready: %v", err)
		}
		time.Sleep(2 * time.Second)
	}
	return db
}

func mustExec(t *testing.T, db *sql.DB, stmts ...string) {
	t.Helper()
	for _, s := range stmts {
		if _, err := db.ExecContext(context.Background(), s); err != nil {
			t.Fatalf("setup exec %q: %v", s, err)
		}
	}
}

func TestIntegrationKeysetPollAgainstRealSQLServer(t *testing.T) {
	db := integrationDB(t)

	mustExec(t, db,
		`IF OBJECT_ID('dbo.vw_headway_apc_it','V') IS NOT NULL DROP VIEW dbo.vw_headway_apc_it`,
		`IF OBJECT_ID('dbo.vw_headway_apc_it_baddate','V') IS NOT NULL DROP VIEW dbo.vw_headway_apc_it_baddate`,
		`IF OBJECT_ID('dbo.headway_it_apc','U') IS NOT NULL DROP TABLE dbo.headway_it_apc`,
		`CREATE TABLE dbo.headway_it_apc (
			apc_key       bigint IDENTITY(1,1) PRIMARY KEY,
			vehicle       nvarchar(32)  NOT NULL,
			total_count   int           NOT NULL,
			board_count   int           NOT NULL,
			alight_count  int           NOT NULL,
			unmod_alight  int           NULL,
			apc_source    nvarchar(16)  NOT NULL,
			is_tripper    bit           NOT NULL,
			is_detour     bit           NOT NULL,
			trip_name     nvarchar(64)  NOT NULL,
			route_name    nvarchar(64)  NOT NULL,
			route_short   nvarchar(16)  NOT NULL,
			pattern_name  nvarchar(16)  NOT NULL,
			stop_name     nvarchar(64)  NOT NULL,
			stop_code     nvarchar(16)  NOT NULL,
			pattern_rank  int           NOT NULL,
			direction_key int           NOT NULL,
			event_time    datetime2     NOT NULL)`,
		// The agency-shaped view: the DBA aliases warehouse columns onto the
		// adapter's declared positional names and CASTs the datetime to a
		// varchar in the adapter's sample format — the view is the contract.
		`CREATE VIEW dbo.vw_headway_apc_it AS SELECT
			apc_key                                   AS VehicleLocationAPCKey,
			vehicle                                   AS VehicleName,
			total_count                               AS TotalCount,
			board_count                               AS BoardCount,
			alight_count                              AS AlightCount,
			unmod_alight                              AS UnmodifiedAlightCount,
			apc_source                                AS APCSource,
			is_tripper                                AS IsTripper,
			is_detour                                 AS IsDetour,
			trip_name                                 AS TripName,
			route_name                                AS RouteName,
			route_short                               AS RouteShortName,
			pattern_name                              AS PatternName,
			stop_name                                 AS StopName,
			stop_code                                 AS StopCode,
			pattern_rank                              AS PatternPointRank,
			direction_key                             AS DirectionKey,
			CONVERT(varchar(19), event_time, 126)     AS EventDateISO
		FROM dbo.headway_it_apc`,
		// A deliberately WRONG view exposing the raw datetime2 — the
		// connector must refuse to invent a format for it.
		`CREATE VIEW dbo.vw_headway_apc_it_baddate AS SELECT
			apc_key AS VehicleLocationAPCKey, vehicle AS VehicleName,
			total_count AS TotalCount, board_count AS BoardCount,
			alight_count AS AlightCount, unmod_alight AS UnmodifiedAlightCount,
			apc_source AS APCSource, is_tripper AS IsTripper,
			is_detour AS IsDetour, trip_name AS TripName,
			route_name AS RouteName, route_short AS RouteShortName,
			pattern_name AS PatternName, stop_name AS StopName,
			stop_code AS StopCode, pattern_rank AS PatternPointRank,
			direction_key AS DirectionKey, event_time AS EventDateISO
		FROM dbo.headway_it_apc`,
	)
	t.Cleanup(func() {
		mustExec(t, db,
			`DROP VIEW dbo.vw_headway_apc_it`,
			`DROP VIEW dbo.vw_headway_apc_it_baddate`,
			`DROP TABLE dbo.headway_it_apc`)
	})

	insert := `INSERT INTO dbo.headway_it_apc
		(vehicle,total_count,board_count,alight_count,unmod_alight,apc_source,
		 is_tripper,is_detour,trip_name,route_name,route_short,pattern_name,
		 stop_name,stop_code,pattern_rank,direction_key,event_time) VALUES
		(@p1,@p2,@p3,@p4,@p5,'APC',0,0,'7 - A - 08:00','Route 7','7','A',@p6,@p7,@p8,1,@p9)`
	seed := func(vehicle string, rank int) {
		t.Helper()
		if _, err := db.ExecContext(context.Background(), insert,
			vehicle, 10+rank, 2, 1, nil, "Main St & 1st", "1001", rank,
			time.Date(2026, 7, 30, 8, 10+rank, 0, 0, time.UTC)); err != nil {
			t.Fatalf("seed: %v", err)
		}
	}
	for i := 1; i <= 5; i++ {
		seed("BUS-12", i)
	}

	fakeProd := producer.NewFake()
	fakeStore := vendorfile.NewFakeStore()
	p := &Poller{
		DB:           db,
		View:         "dbo.vw_headway_apc_it",
		Columns:      append([]string(nil), tripsparkColumns...),
		CursorColumn: "VehicleLocationAPCKey",
		Source:       "tripspark_streets_simulated", // synthetic fixture data, labeled as such
		StateDir:     t.TempDir(),
		BatchMaxRows: 2,
		Store:        fakeStore,
		Producer:     fakeProd,
		Log:          slog.New(slog.NewTextHandler(testWriter{t}, nil)),
	}

	// Poll 1: 5 rows through a 2-row cap -> 3 batches (2+2+1).
	if err := p.PollOnce(context.Background()); err != nil {
		t.Fatalf("PollOnce: %v", err)
	}
	msgs := fakeProd.Messages()
	if len(msgs) != 3 {
		t.Fatalf("produced %d batches, want 3", len(msgs))
	}
	var m map[string]any
	_ = json.Unmarshal(msgs[0].Value, &m)
	stored, ok := fakeStore.Get(m["payload"].(string))
	if !ok {
		t.Fatal("first batch not landed")
	}
	lines := strings.Split(strings.TrimRight(string(stored), "\n"), "\n")
	if len(lines) != 2 {
		t.Fatalf("first batch has %d rows, want 2:\n%s", len(lines), stored)
	}
	wantRow1 := "1,BUS-12,11,2,1,,APC,0,0,7 - A - 08:00,Route 7,7,A,Main St & 1st,1001,1,1,2026-07-30T08:11:00"
	if lines[0] != wantRow1 {
		t.Errorf("row 1 rendered as\n%q\nwant\n%q", lines[0], wantRow1)
	}
	if envelope.RecordID(stored) != m["record_id"] {
		t.Error("record_id is not the content address of the landed bytes")
	}

	// Poll 2: nothing new -> nothing landed.
	if err := p.PollOnce(context.Background()); err != nil {
		t.Fatalf("PollOnce (idle): %v", err)
	}
	if len(fakeProd.Messages()) != 3 {
		t.Fatal("an idle poll produced something")
	}

	// New rows arrive; only they are read (keyset resume, real WHERE/ORDER).
	seed("BUS-31", 6)
	seed("BUS-31", 7)
	if err := p.PollOnce(context.Background()); err != nil {
		t.Fatalf("PollOnce (new rows): %v", err)
	}
	msgs = fakeProd.Messages()
	if len(msgs) != 4 {
		t.Fatalf("produced %d batches after new rows, want 4", len(msgs))
	}
	_ = json.Unmarshal(msgs[3].Value, &m)
	stored, _ = fakeStore.Get(m["payload"].(string))
	if !strings.HasPrefix(string(stored), "6,BUS-31,") || strings.Contains(string(stored), "\n1,") {
		t.Errorf("resumed batch re-read history or missed rows:\n%s", stored)
	}

	// A restarted process resumes from the persisted mark.
	p2 := &Poller{
		DB: db, View: p.View, Columns: p.Columns, CursorColumn: p.CursorColumn,
		Source: p.Source, StateDir: p.StateDir, BatchMaxRows: 2,
		Store: fakeStore, Producer: fakeProd,
		Log: slog.New(slog.NewTextHandler(testWriter{t}, nil)),
	}
	if err := p2.PollOnce(context.Background()); err != nil {
		t.Fatalf("PollOnce (restarted): %v", err)
	}
	if len(fakeProd.Messages()) != 4 {
		t.Fatal("a restarted poller re-read history")
	}

	// The wrong view (raw datetime2) is refused with the view-side fix named.
	bad := &Poller{
		DB: db, View: "dbo.vw_headway_apc_it_baddate", Columns: p.Columns,
		CursorColumn: p.CursorColumn, Source: p.Source, StateDir: t.TempDir(),
		Store: vendorfile.NewFakeStore(), Producer: producer.NewFake(),
		Log: slog.New(slog.NewTextHandler(testWriter{t}, nil)),
	}
	err := bad.PollOnce(context.Background())
	if err == nil || !strings.Contains(err.Error(), "EventDateISO") || !strings.Contains(err.Error(), "CAST") {
		t.Fatalf("raw datetime2 column not refused with the fix named: %v", err)
	}
}
