package gtfsstatic

import (
	"archive/zip"
	"bytes"
	"context"
	"encoding/json"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/headway-transit/headway/services/ingestion/internal/envelope"
	"github.com/headway-transit/headway/services/ingestion/internal/producer"
)

// validZip builds a minimal real zip archive containing a GTFS-ish file.
func validZip(t *testing.T) []byte {
	t.Helper()
	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)
	w, err := zw.Create("agency.txt")
	if err != nil {
		t.Fatalf("zip create: %v", err)
	}
	w.Write([]byte("agency_id,agency_name,agency_url,agency_timezone\n1,Test,https://example.test,UTC\n"))
	if err := zw.Close(); err != nil {
		t.Fatalf("zip close: %v", err)
	}
	return buf.Bytes()
}

func newTestFetcher(t *testing.T, body []byte) (*Fetcher, *producer.Fake, *FakeStore, *httptest.Server) {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", ContentType)
		w.Write(body)
	}))
	t.Cleanup(srv.Close)
	fakeProd := producer.NewFake()
	fakeStore := NewFakeStore()
	f := &Fetcher{
		URL:      srv.URL,
		Store:    fakeStore,
		Producer: fakeProd,
		Log:      slog.New(slog.NewTextHandler(testWriter{t}, nil)),
		Clock:    func() time.Time { return time.Date(2026, 7, 8, 12, 0, 0, 0, time.UTC) },
	}
	return f, fakeProd, fakeStore, srv
}

type testWriter struct{ t *testing.T }

func (w testWriter) Write(p []byte) (int, error) { w.t.Log(string(p)); return len(p), nil }

func TestFetchOnceEnvelopeCorrectness(t *testing.T) {
	zipBytes := validZip(t)
	f, fakeProd, fakeStore, srv := newTestFetcher(t, zipBytes)

	if err := f.FetchOnce(context.Background()); err != nil {
		t.Fatalf("FetchOnce: %v", err)
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
	wantID := envelope.RecordID(zipBytes)
	wantKey := "raw/gtfs_static/" + wantID + ".zip"
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
	if m["source"] != Source || m["connector"] != ConnectorName || m["content_type"] != ContentType {
		t.Errorf("identity fields wrong: %v/%v/%v", m["source"], m["connector"], m["content_type"])
	}
	if m["feed_url"] != srv.URL {
		t.Errorf("feed_url = %v, want %v", m["feed_url"], srv.URL)
	}

	// Object key matches record_id and the landed bytes are byte-identical.
	stored, ok := fakeStore.Get(wantKey)
	if !ok {
		t.Fatalf("object not landed at %s", wantKey)
	}
	if !bytes.Equal(stored, zipBytes) {
		t.Errorf("landed object bytes differ from raw feed bytes")
	}
	if envelope.RecordID(stored) != wantID {
		t.Errorf("landed object does not hash to record_id")
	}
}

func TestBrokenZipStillLandedAndProducedAsMalformed(t *testing.T) {
	notAZip := []byte("definitely not a zip archive")
	f, fakeProd, fakeStore, _ := newTestFetcher(t, notAZip)

	if err := f.FetchOnce(context.Background()); err != nil {
		t.Fatalf("FetchOnce must not error on a broken zip (never drop): %v", err)
	}
	msgs := fakeProd.Messages()
	if len(msgs) != 1 {
		t.Fatalf("broken zip was dropped: %d messages, want 1", len(msgs))
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
	wantKey := ObjectKey(envelope.RecordID(notAZip))
	stored, ok := fakeStore.Get(wantKey)
	if !ok {
		t.Fatalf("malformed feed was not landed at %s", wantKey)
	}
	if !bytes.Equal(stored, notAZip) {
		t.Errorf("malformed feed bytes were mutated")
	}
}

func TestStoreFailureBlocksProduce(t *testing.T) {
	f, fakeProd, fakeStore, _ := newTestFetcher(t, validZip(t))
	fakeStore.Err = context.DeadlineExceeded

	if err := f.FetchOnce(context.Background()); err == nil {
		t.Fatal("expected error when object store put fails")
	}
	// No envelope may reference an object that was never landed.
	if got := len(fakeProd.Messages()); got != 0 {
		t.Fatalf("envelope produced despite failed landing: %d messages", got)
	}
}
