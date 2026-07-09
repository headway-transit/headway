package envelope

import (
	"encoding/base64"
	"encoding/json"
	"testing"
	"time"
)

var testParams = Params{
	Source:           "gtfs_rt",
	Connector:        "headway-gtfs-rt",
	ConnectorVersion: "0.1.0",
	FeedURL:          "https://example.test/vp.pb",
	FetchedAt:        time.Date(2026, 7, 8, 12, 0, 0, 0, time.UTC),
	ContentType:      "application/x-protobuf",
	ParseStatus:      ParseOK,
}

func TestRecordIDKnownVector(t *testing.T) {
	// SHA-256("abc") — FIPS 180-4 test vector.
	const want = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
	if got := RecordID([]byte("abc")); got != want {
		t.Fatalf("RecordID(\"abc\") = %s, want %s", got, want)
	}
	// SHA-256 of the empty string, for completeness.
	const wantEmpty = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
	if got := RecordID(nil); got != wantEmpty {
		t.Fatalf("RecordID(nil) = %s, want %s", got, wantEmpty)
	}
}

func TestRecordIDDeterministic(t *testing.T) {
	payload := []byte{0x0a, 0x0b, 0x00, 0xff, 0x10}
	a := RecordID(payload)
	b := RecordID(append([]byte(nil), payload...)) // fresh copy, same bytes
	if a != b {
		t.Fatalf("same bytes produced different record_ids: %s vs %s", a, b)
	}
	if c := RecordID([]byte{0x0a, 0x0b, 0x00, 0xff, 0x11}); c == a {
		t.Fatalf("different bytes produced the same record_id: %s", c)
	}
}

func TestNewRequiredFieldsComplete(t *testing.T) {
	payload := []byte("raw frame bytes")
	e, err := New(payload, testParams)
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	raw, err := e.MarshalJSONBytes()
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	var m map[string]any
	if err := json.Unmarshal(raw, &m); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	for _, k := range []string{
		"envelope_version", "record_id", "source", "connector",
		"connector_version", "fetched_at", "content_type",
		"payload_encoding", "payload", "parse_status",
	} {
		if _, ok := m[k]; !ok {
			t.Errorf("marshaled envelope missing required field %q", k)
		}
	}
	if m["envelope_version"] != float64(0) {
		t.Errorf("envelope_version = %v, want 0", m["envelope_version"])
	}
	if m["payload_encoding"] != EncodingBase64 {
		t.Errorf("payload_encoding = %v, want base64", m["payload_encoding"])
	}
	// Round-trip: base64 payload must decode to the exact original bytes.
	decoded, err := base64.StdEncoding.DecodeString(m["payload"].(string))
	if err != nil {
		t.Fatalf("payload is not valid base64: %v", err)
	}
	if string(decoded) != string(payload) {
		t.Errorf("payload round-trip mutated bytes: got %q want %q", decoded, payload)
	}
	if m["record_id"] != RecordID(payload) {
		t.Errorf("record_id = %v, want hash of payload bytes", m["record_id"])
	}
	if _, err := time.Parse(time.RFC3339, m["fetched_at"].(string)); err != nil {
		t.Errorf("fetched_at not RFC3339: %v", err)
	}
	// parse_error must be omitted when parse_status is ok.
	if _, ok := m["parse_error"]; ok {
		t.Errorf("parse_error present on ok envelope")
	}
}

func TestMalformedPathSetsStatusAndError(t *testing.T) {
	p := testParams
	p.ParseStatus = ParseMalformed
	p.ParseError = "proto: cannot parse invalid wire-format data"
	e, err := New([]byte("garbage that is not a protobuf"), p)
	if err != nil {
		t.Fatalf("New must still build an envelope for malformed input (never drop): %v", err)
	}
	if e.ParseStatus != ParseMalformed {
		t.Errorf("parse_status = %q, want malformed", e.ParseStatus)
	}
	if e.ParseError == "" {
		t.Errorf("parse_error empty on malformed envelope")
	}
}

func TestMalformedWithoutParseErrorRejected(t *testing.T) {
	p := testParams
	p.ParseStatus = ParseMalformed
	p.ParseError = ""
	if _, err := New([]byte("x"), p); err == nil {
		t.Fatal("expected validation error: malformed without parse_error")
	}
}

func TestMissingRequiredFieldRejected(t *testing.T) {
	p := testParams
	p.Source = ""
	if _, err := New([]byte("x"), p); err == nil {
		t.Fatal("expected validation error for empty source")
	}
}

func TestNewObjectRef(t *testing.T) {
	payload := []byte("PK\x03\x04 pretend zip bytes")
	id := RecordID(payload)
	key := "raw/gtfs_static/" + id + ".zip"
	p := testParams
	p.Source = "gtfs_static"
	p.ContentType = "application/zip"
	e, err := NewObjectRef(payload, key, p)
	if err != nil {
		t.Fatalf("NewObjectRef: %v", err)
	}
	if e.PayloadEncoding != EncodingObjectRef {
		t.Errorf("payload_encoding = %q, want object_ref", e.PayloadEncoding)
	}
	if e.Payload != key {
		t.Errorf("payload = %q, want object key %q", e.Payload, key)
	}
	if e.RecordID != id {
		t.Errorf("record_id = %q, want hash of object bytes %q", e.RecordID, id)
	}
}
