package sqlsource

// An in-memory database/sql driver for the unit tests: it serves scripted
// result sets through the REAL database/sql scan path (the same one the
// go-mssqldb driver feeds), records every query text and its parameters,
// and can fail on demand. No network, no SQL parsing — the connector's own
// query construction is asserted against the recorded text.

import (
	"context"
	"database/sql"
	"database/sql/driver"
	"errors"
	"io"
	"sync"
)

type fakeResult struct {
	cols []string
	rows [][]driver.Value
	err  error // returned instead of the result when non-nil
}

type recordedQuery struct {
	query string
	args  []driver.NamedValue
}

type fakeDB struct {
	mu      sync.Mutex
	results []fakeResult
	queries []recordedQuery
}

func (f *fakeDB) pop(query string, args []driver.NamedValue) (fakeResult, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.queries = append(f.queries, recordedQuery{query: query, args: args})
	if len(f.results) == 0 {
		return fakeResult{}, errors.New("fakedb: query issued but no result scripted")
	}
	r := f.results[0]
	f.results = f.results[1:]
	if r.err != nil {
		return fakeResult{}, r.err
	}
	return r, nil
}

func (f *fakeDB) recorded() []recordedQuery {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]recordedQuery(nil), f.queries...)
}

// driver plumbing

type fakeConnector struct{ db *fakeDB }

func (c fakeConnector) Connect(context.Context) (driver.Conn, error) { return fakeConn{c.db}, nil }
func (c fakeConnector) Driver() driver.Driver                        { return fakeDriver{} }

type fakeDriver struct{}

func (fakeDriver) Open(string) (driver.Conn, error) { return nil, errors.New("use OpenDB") }

type fakeConn struct{ db *fakeDB }

func (c fakeConn) Prepare(string) (driver.Stmt, error) { return nil, errors.New("not implemented") }
func (c fakeConn) Close() error                        { return nil }
func (c fakeConn) Begin() (driver.Tx, error)           { return nil, errors.New("read-only") }

func (c fakeConn) QueryContext(_ context.Context, query string, args []driver.NamedValue) (driver.Rows, error) {
	r, err := c.db.pop(query, args)
	if err != nil {
		return nil, err
	}
	return &fakeRows{cols: r.cols, rows: r.rows}, nil
}

type fakeRows struct {
	cols []string
	rows [][]driver.Value
	pos  int
}

func (r *fakeRows) Columns() []string { return r.cols }
func (r *fakeRows) Close() error      { return nil }

func (r *fakeRows) Next(dest []driver.Value) error {
	if r.pos >= len(r.rows) {
		return io.EOF
	}
	copy(dest, r.rows[r.pos])
	r.pos++
	return nil
}

// openFake returns a *sql.DB backed by the scripted results.
func openFake(results ...fakeResult) (*sql.DB, *fakeDB) {
	db := &fakeDB{results: results}
	return sql.OpenDB(fakeConnector{db}), db
}
