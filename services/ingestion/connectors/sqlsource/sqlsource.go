// Package sqlsource is the generic SQL-source connector (handoff 0033). It
// polls a VIEW OR QUERY THE AGENCY SUPPLIES IN CONFIGURATION on the agency's
// own database server — SQL Server first, via github.com/microsoft/go-mssqldb
// (BSD-3-Clause, verified against the ADR-0001 license gate) — renders each
// polled batch to the registered adapter's declared positional-CSV shape, and
// lands it EXACTLY like a dropped vendor file: content-addressed into the
// object store at the vendorfile connector's key layout, then produced as an
// object_ref raw-record envelope to raw.vendor.files. The existing transform
// adapter runtime and trip resolution take over untouched. One pipeline, two
// intakes (the ROADMAP framing, corrected 2026-07-29).
//
// WHAT NEVER ENTERS THIS REPOSITORY: vendor table and column names. The
// agency's DBA creates a view (e.g. dbo.vw_headway_apc) over the vendor
// warehouse and grants a read-only login (e.g. headway_ro) SELECT on it; the
// view's column list — declared in configuration — is the contract. A vendor
// upgrade that changes internals is absorbed by the agency editing its view,
// never by editing Headway.
//
// THE COLUMN-ORDER CONTRACT (binding, recorded per handoff 0033 §4).
// SQLSOURCE_COLUMNS must list EXACTLY the registered adapter's declared
// positional columns (`source_format.csv.columns` in
// adapters/<vendor>/<product>/mapping.v0.yaml), in the same order. The
// connector SELECTs exactly that list — never SELECT * (ADR-0013
// minimization: only the columns the adapter declares are ever read or
// landed) — and renders headerless positional CSV in that order. Two
// enforcement points uphold the wrong_width precedent:
//
//   - here: the result set's column names/order/count must equal the
//     configured list or the batch is REFUSED whole, nothing landed, the
//     high-water mark not advanced;
//   - downstream: the adapter runtime quarantines any row whose field count
//     differs from the spec's declared width (services/transform, the
//     wrong_width fixture) — so even a misconfigured column list can never
//     be mapped by guesswork.
//
// INCREMENTAL KEYSET POLLING. Each poll reads
// `WHERE <cursor> > @high_water ORDER BY <cursor> ASC` up to the batch cap,
// batch after batch until a short batch, so catch-up after downtime is one
// poll cycle. The cursor column is agency-declared, monotonic, and in v0
// must be an INTEGER key (e.g. an identity/bigint warehouse key); other
// cursor types are refused with instructions, never coerced. The high-water
// mark persists as a small JSON state file under SQLSOURCE_STATE_DIR
// (chosen over app.settings so the connector keeps zero database
// dependencies of its own; revisit per the handoff's open question), written
// atomically (temp + rename) and only AFTER a successful land + produce —
// at-least-once by construction. Losing or deliberately deleting the state
// file merely re-reads history: an identical batch renders identical bytes,
// lands under the identical content-addressed record_id, and the adapter
// runtime's mapped records carry deterministic natural keys, so redelivery
// writes nothing new (proved in tests here; engine determinism per
// contracts/adapter-mapping.v0.md).
//
// HONEST SCOPE (handoff 0033 §6): read-only SELECTs only — the connector
// cannot emit DML by construction (one generated SELECT, bracket-quoted
// identifiers validated against a strict pattern) and the agency-side
// enforcement is the read-only login; every query runs under a client-side
// statement timeout; no schema discovery; SQL Server only (the config shape
// is driver-neutral, the SQL dialect is internal). The DSN is a secret: the
// connector never holds it (it takes an already-open *sql.DB), and OpenDB
// withholds the DSN value from its own error.
//
// House rules held, in the shape of the existing connectors: fail-closed
// startup with plain-language refusals; store-before-produce; content-
// addressed record ids; the *_simulated source-label rule enforced
// structurally (a "sim:"-marked cell under a non-simulated label refuses the
// batch); secrets never logged, including in errors.
package sqlsource

import (
	"context"
	"database/sql"
	"encoding/csv"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"

	// SQL Server driver (BSD-3-Clause; license verified in the module cache
	// and against scripts/license_gate.py — see the connector README).
	_ "github.com/microsoft/go-mssqldb"

	"github.com/headway-transit/headway/services/ingestion/connectors/vendorfile"
	"github.com/headway-transit/headway/services/ingestion/internal/envelope"
	"github.com/headway-transit/headway/services/ingestion/internal/producer"
)

// Connector identity recorded on every envelope. Topic, content type and
// object-key layout are DELIBERATELY the vendorfile connector's: a polled
// batch is indistinguishable from a dropped file downstream (one pipeline,
// two intakes).
const (
	ConnectorName    = "headway-sqlsource"
	ConnectorVersion = "0.1.0"
	// DriverSQLServer is the only supported driver in v0. The config shape
	// (view + columns + cursor) is driver-neutral so Postgres/Oracle can be
	// added later without breaking existing configuration.
	DriverSQLServer = "sqlserver"
)

// Operational defaults — Headway choices, overridable from the environment.
const (
	// DefaultPollInterval: "more frequent than nightly" is the whole point;
	// five minutes keeps warehouse load trivial (one indexed keyset SELECT).
	DefaultPollInterval = 5 * time.Minute
	// DefaultBatchMaxRows caps one rendered batch (one raw record).
	DefaultBatchMaxRows = 5000
	// DefaultQueryTimeout is the client-side statement timeout; go-mssqldb
	// cancels the running statement when the context deadline passes.
	DefaultQueryTimeout = 60 * time.Second
	// DefaultMaxBatchesPerPoll bounds one poll cycle so a source that grows
	// faster than it can be read stops loudly instead of looping forever.
	DefaultMaxBatchesPerPoll = 1000
	// stateVersion versions the high-water state file format.
	stateVersion = 1
)

// identPattern is the ONLY shape accepted for the view name's parts and for
// column names. It is what makes bracket-quoted identifier interpolation
// safe and is also the SELECT *-refusal: "*" cannot match.
var identPattern = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]*$`)

// labelPattern is the registered-adapter-label shape (`<vendor>_<product>`,
// adapters/README.md) — also what makes the label safe in a state filename.
var labelPattern = regexp.MustCompile(`^[a-z][a-z0-9_]*$`)

// OpenDB opens the SQL Server pool for a DSN. The DSN carries credentials,
// so on failure the error deliberately WITHHOLDS both the DSN value and the
// driver's parse detail (either may echo fragments of the secret).
func OpenDB(dsn string) (*sql.DB, error) {
	if strings.TrimSpace(dsn) == "" {
		return nil, errors.New(
			"SQLSOURCE_DSN is not set. Headway refuses to start the SQL-source " +
				"connector without a connection string rather than guess one. " +
				"Ask your DBA for a READ-ONLY login (e.g. headway_ro) that can " +
				"SELECT from the agreed view and nothing else, and set " +
				"SQLSOURCE_DSN=sqlserver://user:password@host:1433?database=... " +
				"from the secret store. The value is never logged")
	}
	db, err := sql.Open(DriverSQLServer, dsn)
	if err != nil {
		// The driver's own message can echo pieces of the connection string.
		return nil, errors.New(
			"SQLSOURCE_DSN could not be parsed as a SQL Server connection " +
				"string. The value and the parser's detail are withheld from " +
				"this message because they may contain credentials. Expected " +
				"shape: sqlserver://user:password@host:1433?database=WAREHOUSE" +
				"&encrypt=true (URL-encode reserved characters in the password)")
	}
	return db, nil
}

// Poller polls one agency-supplied view and lands rendered batches through
// the vendorfile pipeline. It never sees the DSN: it is handed an open pool.
type Poller struct {
	// DB is the open connection pool (from OpenDB). REQUIRED.
	DB *sql.DB
	// View is the agency-supplied view (or table) name, e.g.
	// "dbo.vw_headway_apc". One to three dot-separated identifiers. REQUIRED.
	View string
	// Columns is the ordered column list — EXACTLY the registered adapter's
	// declared positional columns, in the same order (the column-order
	// contract). REQUIRED. "*" is refused: minimization (ADR-0013) means
	// only the columns the adapter declares are ever selected.
	Columns []string
	// CursorColumn is the agency-declared monotonic INTEGER keyset column
	// (e.g. VehicleLocationAPCKey). Must be one of Columns, so every landed
	// batch carries its own cursor evidence. REQUIRED.
	CursorColumn string
	// Source is the envelope source label — the REGISTERED adapter
	// mapping-spec label (`<vendor>_<product>`, or `..._simulated` for
	// synthetic data). REQUIRED, no default; the transform runtime refuses
	// unregistered labels fail-closed (handoff 0015).
	Source string
	// StateDir is where the high-water mark persists. REQUIRED.
	StateDir string

	BatchMaxRows      int
	QueryTimeout      time.Duration
	MaxBatchesPerPoll int
	Interval          time.Duration
	AgencyID          string

	Store    vendorfile.ObjectStore
	Producer producer.Producer
	Log      *slog.Logger

	// Clock is injectable for tests; defaults to time.Now.
	Clock func() time.Time

	// In-memory high-water mark, loaded from the state file on first poll.
	hw       int64
	hwSet    bool
	hwLoaded bool
}

func (p *Poller) clock() time.Time {
	if p.Clock != nil {
		return p.Clock()
	}
	return time.Now()
}

func (p *Poller) batchMaxRows() int {
	if p.BatchMaxRows > 0 {
		return p.BatchMaxRows
	}
	return DefaultBatchMaxRows
}

func (p *Poller) queryTimeout() time.Duration {
	if p.QueryTimeout > 0 {
		return p.QueryTimeout
	}
	return DefaultQueryTimeout
}

func (p *Poller) maxBatchesPerPoll() int {
	if p.MaxBatchesPerPoll > 0 {
		return p.MaxBatchesPerPoll
	}
	return DefaultMaxBatchesPerPoll
}

func (p *Poller) sourceIsSimulated() bool {
	return strings.HasSuffix(p.Source, vendorfile.SimulatedSourceSuffix)
}

// Check validates configuration and refuses to run without the things
// Headway must never guess. Messages are written for the person configuring
// the connector, not for a stack trace.
func (p *Poller) Check() error {
	var problems []string

	if p.DB == nil {
		problems = append(problems, "no database connection configured (SQLSOURCE_DSN)")
	}

	view := strings.TrimSpace(p.View)
	if view == "" {
		problems = append(problems,
			"SQLSOURCE_VIEW is not set. Headway reads a view YOUR DBA creates "+
				"and names (e.g. dbo.vw_headway_apc) — vendor table names never "+
				"enter Headway's configuration conventions. Set SQLSOURCE_VIEW "+
				"to that view's name")
	} else if !viewNameValid(view) {
		problems = append(problems, fmt.Sprintf(
			"SQLSOURCE_VIEW=%q is not a plain view name. Headway accepts one "+
				"to three dot-separated identifiers (letters, digits, "+
				"underscore; e.g. dbo.vw_headway_apc) and nothing else — free-"+
				"form SQL here could smuggle in writes or columns the adapter "+
				"never declared. Put any query logic INSIDE the view", view))
	}

	if len(p.Columns) == 0 {
		problems = append(problems,
			"SQLSOURCE_COLUMNS is not set. Headway selects ONLY the columns "+
				"the registered adapter declares (data minimization, ADR-0013) "+
				"and refuses to guess them: set SQLSOURCE_COLUMNS to the "+
				"adapter's positional column list, comma-separated, in the "+
				"adapter's declared order (source_format.csv.columns in "+
				"adapters/<vendor>/<product>/mapping.v0.yaml)")
	} else {
		seen := map[string]bool{}
		for _, c := range p.Columns {
			if c == "*" || strings.Contains(c, "*") {
				problems = append(problems,
					"SQLSOURCE_COLUMNS contains \"*\". SELECT * is refused: "+
						"Headway lands only the columns the registered adapter "+
						"declares, so an unrequested column — which could carry "+
						"personal data — is never read, let alone stored "+
						"(ADR-0013: minimization precedes immutability)")
				continue
			}
			if !identPattern.MatchString(c) {
				problems = append(problems, fmt.Sprintf(
					"SQLSOURCE_COLUMNS entry %q is not a plain column name "+
						"(letters, digits, underscore). Rename or alias the "+
						"column inside the view", c))
			}
			if seen[c] {
				problems = append(problems, fmt.Sprintf(
					"SQLSOURCE_COLUMNS lists %q twice; the adapter's positional "+
						"columns are unique by contract", c))
			}
			seen[c] = true
		}
		if cc := strings.TrimSpace(p.CursorColumn); cc != "" && !seen[cc] {
			problems = append(problems, fmt.Sprintf(
				"SQLSOURCE_CURSOR_COLUMN=%q is not in SQLSOURCE_COLUMNS. The "+
					"cursor must be one of the adapter's declared columns so "+
					"every landed batch carries its own cursor evidence", cc))
		}
	}

	if strings.TrimSpace(p.CursorColumn) == "" {
		problems = append(problems,
			"SQLSOURCE_CURSOR_COLUMN is not set. Headway polls incrementally "+
				"by keyset (WHERE cursor > last-seen ORDER BY cursor) and "+
				"refuses to guess which column that is: set it to the view's "+
				"monotonic integer key (e.g. VehicleLocationAPCKey), declared "+
				"by your DBA, unique and never reused")
	}

	if strings.TrimSpace(p.Source) == "" {
		problems = append(problems,
			"SQLSOURCE_ADAPTER_LABEL is not set. Headway needs to know which "+
				"REGISTERED adapter maps these rows and refuses to guess: set "+
				"it to the mapping-spec label `<vendor>_<product>` (see "+
				"adapters/), or `<vendor>_<product>_simulated` for synthetic "+
				"data — an unlabeled feed could be mapped by the wrong spec or "+
				"record simulated data as real (Shared Constraint 2: full "+
				"provenance). The transform runtime refuses unregistered "+
				"labels with a blocking DQ issue (handoff 0015)")
	} else if !labelPattern.MatchString(p.Source) {
		problems = append(problems, fmt.Sprintf(
			"SQLSOURCE_ADAPTER_LABEL=%q is not a plain lowercase label. "+
				"Registered adapter labels look like tripspark_streets "+
				"(adapters/README.md)", p.Source))
	}

	if strings.TrimSpace(p.StateDir) == "" {
		problems = append(problems,
			"SQLSOURCE_STATE_DIR is not set. The high-water mark must persist "+
				"across restarts so history is never re-read by accident; give "+
				"the connector a writable directory (the Compose file mounts "+
				"deploy/compose/sqlsource-state)")
	}

	if p.Store == nil {
		problems = append(problems, "no object store configured (S3_ENDPOINT and credentials are required): batches must be landed before they are produced")
	}
	if p.Producer == nil {
		problems = append(problems, "no Kafka producer configured")
	}
	if p.Log == nil {
		problems = append(problems, "no logger configured")
	}

	if len(problems) > 0 {
		return fmt.Errorf("sqlsource: refusing to start:\n  - %s",
			strings.Join(problems, "\n  - "))
	}
	return nil
}

// viewNameValid accepts one to three dot-separated plain identifiers.
func viewNameValid(view string) bool {
	parts := strings.Split(view, ".")
	if len(parts) < 1 || len(parts) > 3 {
		return false
	}
	for _, part := range parts {
		if !identPattern.MatchString(part) {
			return false
		}
	}
	return true
}

// quoteIdent bracket-quotes a validated identifier for T-SQL.
func quoteIdent(ident string) string {
	return "[" + ident + "]"
}

// buildQuery renders the one SELECT this connector is capable of issuing.
// Identifiers were validated by Check; values travel as parameters. The
// T-SQL dialect (TOP, brackets, @p1) is internal to this function — a future
// Postgres/Oracle driver adds its own dialect here, not new config.
func (p *Poller) buildQuery() string {
	quoted := make([]string, len(p.Columns))
	for i, c := range p.Columns {
		quoted[i] = quoteIdent(c)
	}
	viewParts := strings.Split(strings.TrimSpace(p.View), ".")
	for i, part := range viewParts {
		viewParts[i] = quoteIdent(part)
	}
	q := fmt.Sprintf("SELECT TOP (%d) %s FROM %s",
		p.batchMaxRows(), strings.Join(quoted, ", "), strings.Join(viewParts, "."))
	if p.hwSet {
		q += fmt.Sprintf(" WHERE %s > @p1", quoteIdent(p.CursorColumn))
	}
	q += fmt.Sprintf(" ORDER BY %s ASC", quoteIdent(p.CursorColumn))
	return q
}

// batch is one polled, rendered batch.
type batch struct {
	csv        []byte
	rows       int
	cursorFrom int64
	cursorTo   int64
}

// fetchBatch runs one keyset query and renders the result to the adapter's
// positional CSV. It returns nil when the source has no rows past the
// high-water mark.
func (p *Poller) fetchBatch(ctx context.Context) (*batch, error) {
	qctx, cancel := context.WithTimeout(ctx, p.queryTimeout())
	defer cancel()

	query := p.buildQuery()
	var rows *sql.Rows
	var err error
	if p.hwSet {
		rows, err = p.DB.QueryContext(qctx, query, sql.Named("p1", p.hw))
	} else {
		rows, err = p.DB.QueryContext(qctx, query)
	}
	if err != nil {
		return nil, fmt.Errorf("sqlsource: query %s: %w", p.View, err)
	}
	defer rows.Close()

	// The column-order contract, enforced before anything is read: the
	// result set must present EXACTLY the configured columns, in order.
	got, err := rows.Columns()
	if err != nil {
		return nil, fmt.Errorf("sqlsource: read result columns: %w", err)
	}
	if err := columnsMatch(p.Columns, got); err != nil {
		return nil, fmt.Errorf(
			"sqlsource: the view's result does not match SQLSOURCE_COLUMNS "+
				"(%w). The configured list must be EXACTLY the registered "+
				"adapter's declared positional columns, in the adapter's "+
				"order — a mismatched batch would be quarantined row by row "+
				"downstream (the wrong_width rule), so it is refused here "+
				"whole: nothing landed, high-water mark not advanced", err)
	}

	cursorIdx := -1
	for i, c := range p.Columns {
		if c == p.CursorColumn {
			cursorIdx = i
		}
	}

	var buf strings.Builder
	w := csv.NewWriter(&buf)
	count := 0
	var first, last int64
	prev := int64(0)
	prevSet := false
	values := make([]any, len(p.Columns))
	ptrs := make([]any, len(p.Columns))
	for i := range values {
		ptrs[i] = &values[i]
	}
	record := make([]string, len(p.Columns))
	tieAtBoundary := false

	for rows.Next() {
		if err := rows.Scan(ptrs...); err != nil {
			return nil, fmt.Errorf("sqlsource: scan row: %w", err)
		}
		cursor, err := cursorValue(values[cursorIdx])
		if err != nil {
			return nil, fmt.Errorf(
				"sqlsource: cursor column %s: %w. The keyset cursor must be a "+
					"non-NULL monotonic integer key in every row; fix the view "+
					"(e.g. cast or filter) — Headway will not guess an order",
				p.CursorColumn, err)
		}
		if prevSet && cursor == prev {
			tieAtBoundary = true // only matters if this batch fills the cap
		} else {
			tieAtBoundary = false
		}
		prev, prevSet = cursor, true

		for i, v := range values {
			cell, err := renderCell(v)
			if err != nil {
				return nil, fmt.Errorf(
					"sqlsource: column %s: %w. The view is the contract: CAST "+
						"the column to a varchar in exactly the format the "+
						"adapter's sample demonstrated — Headway renders bytes, "+
						"it does not invent a format (that would be silent "+
						"normalization at the ingest boundary)",
					p.Columns[i], err)
			}
			record[i] = cell
		}

		// Provenance enforcement, same rule as the file intake: simulator-
		// marked content under a non-simulated label never lands.
		if !p.sourceIsSimulated() {
			for i, cell := range record {
				if strings.HasPrefix(strings.TrimLeft(cell, " \t\"'"), vendorfile.SimMarkerPrefix) {
					return nil, fmt.Errorf(
						"sqlsource: column %s carries the simulator marker %q "+
							"but SQLSOURCE_ADAPTER_LABEL=%q does not declare "+
							"simulated data; simulated data must never be "+
							"ingested as real (Shared Constraint 2: full "+
							"provenance). If this source really is synthetic, "+
							"use a label ending in %s. Batch refused, nothing "+
							"landed",
						p.Columns[i], vendorfile.SimMarkerPrefix, p.Source,
						vendorfile.SimulatedSourceSuffix)
				}
			}
		}

		if err := w.Write(record); err != nil {
			return nil, fmt.Errorf("sqlsource: render csv: %w", err)
		}
		if count == 0 {
			first = cursor
		}
		last = cursor
		count++
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("sqlsource: read rows: %w", err)
	}
	if count == 0 {
		return nil, nil
	}
	if count >= p.batchMaxRows() && tieAtBoundary {
		return nil, fmt.Errorf(
			"sqlsource: the batch filled its %d-row cap and the last two rows "+
				"share cursor value %d. Advancing past a tied boundary could "+
				"skip rows silently, so the batch is refused: the cursor "+
				"column must be UNIQUE (a key), or raise SQLSOURCE_BATCH_MAX_ROWS "+
				"above the largest tie group", p.batchMaxRows(), last)
	}
	w.Flush()
	if err := w.Error(); err != nil {
		return nil, fmt.Errorf("sqlsource: render csv: %w", err)
	}
	return &batch{csv: []byte(buf.String()), rows: count, cursorFrom: first, cursorTo: last}, nil
}

// columnsMatch compares configured and returned column lists exactly.
func columnsMatch(want, got []string) error {
	if len(want) != len(got) {
		return fmt.Errorf("configured %d columns, the view returned %d", len(want), len(got))
	}
	for i := range want {
		if want[i] != got[i] {
			return fmt.Errorf("position %d: configured %q, the view returned %q",
				i+1, want[i], got[i])
		}
	}
	return nil
}

// cursorValue extracts the v0-supported integer cursor.
func cursorValue(v any) (int64, error) {
	switch c := v.(type) {
	case int64:
		return c, nil
	case nil:
		return 0, errors.New("value is NULL")
	default:
		return 0, fmt.Errorf("value has type %T; v0 supports integer cursors only", v)
	}
}

// renderCell converts one scanned value to its CSV cell, deterministically
// and without interpretation. Types whose textual form would be a Headway
// FORMATTING CHOICE (datetimes, floats/decimals, binary) are refused — the
// agency casts them to varchar inside the view, where the format is the
// agency's declaration, not Headway's guess.
func renderCell(v any) (string, error) {
	switch c := v.(type) {
	case nil:
		return "", nil
	case string:
		return c, nil
	case []byte:
		return string(c), nil
	case int64:
		return strconv.FormatInt(c, 10), nil
	case bool:
		if c {
			return "1", nil
		}
		return "0", nil
	default:
		return "", fmt.Errorf("scanned as %T, which Headway refuses to format", v)
	}
}

// PollOnce drains everything past the high-water mark, one capped batch per
// raw record, and persists the mark after each landed+produced batch.
func (p *Poller) PollOnce(ctx context.Context) error {
	if err := p.Check(); err != nil {
		return err
	}
	if !p.hwLoaded {
		if err := p.loadState(); err != nil {
			return err
		}
		p.hwLoaded = true
	}

	for i := 0; ; i++ {
		if i >= p.maxBatchesPerPoll() {
			return fmt.Errorf(
				"sqlsource: one poll cycle exceeded %d batches; stopping "+
					"loudly rather than reading forever (progress is kept — "+
					"the high-water mark advanced with every landed batch)",
				p.maxBatchesPerPoll())
		}
		b, err := p.fetchBatch(ctx)
		if err != nil {
			return err
		}
		if b == nil {
			return nil
		}
		if err := p.landAndProduce(ctx, b); err != nil {
			return err
		}
		// Advance and persist ONLY after land + produce: a crash in between
		// re-reads the batch (at-least-once), and the identical bytes land
		// under the identical record_id — never a gap, never a double count.
		p.hw, p.hwSet = b.cursorTo, true
		if err := p.saveState(); err != nil {
			return err
		}
		if b.rows < p.batchMaxRows() {
			return nil
		}
	}
}

// landAndProduce stores one rendered batch content-addressed at the
// vendorfile key layout and produces its envelope to raw.vendor.files.
// Landing precedes producing.
func (p *Poller) landAndProduce(ctx context.Context, b *batch) error {
	recordID := envelope.RecordID(b.csv)
	key := vendorfile.ObjectKey(recordID)
	if err := p.Store.Put(ctx, key, b.csv); err != nil {
		return fmt.Errorf("sqlsource: land %s: %w", key, err)
	}
	// parse_status is always ok, the vendorfile rule: only the registered
	// mapping spec knows what the rendered shape means; per-row quarantine
	// and the fail-closed unregistered-label refusal are the transform
	// adapter runtime's.
	env, err := envelope.NewObjectRef(b.csv, key, envelope.Params{
		Source:           p.Source,
		Connector:        ConnectorName,
		ConnectorVersion: ConnectorVersion,
		AgencyID:         p.AgencyID,
		FetchedAt:        p.clock(),
		ContentType:      vendorfile.ContentType,
		ParseStatus:      envelope.ParseOK,
	})
	if err != nil {
		return fmt.Errorf("sqlsource: build envelope: %w", err)
	}
	value, err := env.MarshalJSONBytes()
	if err != nil {
		return fmt.Errorf("sqlsource: marshal envelope: %w", err)
	}
	if err := p.Producer.Produce(ctx, vendorfile.Topic, []byte(recordID), value); err != nil {
		return fmt.Errorf("sqlsource: %w", err)
	}
	p.Log.Info("sql-source batch rendered, landed and produced",
		"connector", ConnectorName, "record_id", recordID, "object_key", key,
		"topic", vendorfile.Topic, "source", p.Source, "view", p.View,
		"rows", b.rows, "cursor_from", b.cursorFrom, "cursor_to", b.cursorTo,
		"bytes", len(b.csv))
	return nil
}

// Run polls immediately, then on every Interval tick until ctx is done.
// Poll errors are logged loudly and retried next cycle; a configuration
// refusal returns immediately.
func (p *Poller) Run(ctx context.Context) error {
	if err := p.Check(); err != nil {
		return err
	}
	interval := p.Interval
	if interval <= 0 {
		interval = DefaultPollInterval
	}
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		if err := p.PollOnce(ctx); err != nil {
			if ctx.Err() != nil {
				return ctx.Err()
			}
			p.Log.Error("sql-source poll cycle failed (will retry next cycle)",
				"connector", ConnectorName, "view", p.View, "error", err)
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-ticker.C:
		}
	}
}

// --- high-water mark persistence -----------------------------------------

// hwState is the on-disk high-water record. View and cursor column are
// stored so a mark recorded under a different contract is never silently
// reused.
type hwState struct {
	StateVersion int    `json:"state_version"`
	View         string `json:"view"`
	CursorColumn string `json:"cursor_column"`
	HighWater    string `json:"high_water"`
	UpdatedAt    string `json:"updated_at"`
}

// StatePath returns the state-file path for a source label.
func StatePath(stateDir, source string) string {
	return filepath.Join(stateDir, "sqlsource-"+source+".json")
}

func (p *Poller) loadState() error {
	path := StatePath(p.StateDir, p.Source)
	raw, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		// First run: read from the beginning of the view.
		p.hwSet = false
		return nil
	}
	if err != nil {
		return fmt.Errorf("sqlsource: read high-water state %s: %w", path, err)
	}
	var s hwState
	if err := json.Unmarshal(raw, &s); err != nil {
		return fmt.Errorf(
			"sqlsource: the high-water state file %s is not readable (%w). "+
				"Headway refuses to guess a cursor position. Fix or delete the "+
				"file DELIBERATELY; deleting it re-reads the view from the "+
				"beginning, which is safe — identical batches land identical "+
				"record ids and mapped rows carry deterministic natural keys, "+
				"so nothing is double-counted", path, err)
	}
	if s.View != p.View || s.CursorColumn != p.CursorColumn {
		return fmt.Errorf(
			"sqlsource: the high-water state file %s was recorded for "+
				"view=%q cursor=%q, but the connector is configured for "+
				"view=%q cursor=%q. A mark from a different contract is "+
				"meaningless, so Headway refuses to reuse it: delete the file "+
				"DELIBERATELY to re-read from the beginning (safe — replayed "+
				"batches are idempotent by content address and natural keys)",
			path, s.View, s.CursorColumn, p.View, p.CursorColumn)
	}
	hw, err := strconv.ParseInt(s.HighWater, 10, 64)
	if err != nil {
		return fmt.Errorf(
			"sqlsource: the high-water value %q in %s is not an integer (%w); "+
				"fix or delete the file deliberately (re-reading is safe)",
			s.HighWater, path, err)
	}
	p.hw, p.hwSet = hw, true
	return nil
}

// saveState writes the mark atomically (temp file + rename) so a crash can
// never leave a torn state file.
func (p *Poller) saveState() error {
	if err := os.MkdirAll(p.StateDir, 0o755); err != nil {
		return fmt.Errorf("sqlsource: create state dir: %w", err)
	}
	s := hwState{
		StateVersion: stateVersion,
		View:         p.View,
		CursorColumn: p.CursorColumn,
		HighWater:    strconv.FormatInt(p.hw, 10),
		UpdatedAt:    p.clock().UTC().Format(time.RFC3339),
	}
	raw, err := json.Marshal(s)
	if err != nil {
		return fmt.Errorf("sqlsource: marshal high-water state: %w", err)
	}
	path := StatePath(p.StateDir, p.Source)
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, raw, 0o644); err != nil {
		return fmt.Errorf("sqlsource: write high-water state: %w", err)
	}
	if err := os.Rename(tmp, path); err != nil {
		return fmt.Errorf("sqlsource: persist high-water state: %w", err)
	}
	return nil
}
