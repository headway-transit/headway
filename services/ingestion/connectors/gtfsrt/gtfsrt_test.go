package gtfsrt

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	gtfs "github.com/MobilityData/gtfs-realtime-bindings/golang/gtfs"
	"google.golang.org/protobuf/proto"

	"github.com/headway-transit/headway/services/ingestion/internal/envelope"
	"github.com/headway-transit/headway/services/ingestion/internal/producer"
)

// validFrame builds a real GTFS-RT FeedMessage frame with one vehicle
// position, marshaled with the pinned MobilityData bindings.
func validFrame(t *testing.T) []byte {
	t.Helper()
	feed := &gtfs.FeedMessage{
		Header: &gtfs.FeedHeader{
			GtfsRealtimeVersion: proto.String("2.0"),
			Timestamp:           proto.Uint64(1751976000),
		},
		Entity: []*gtfs.FeedEntity{{
			Id: proto.String("veh-1"),
			Vehicle: &gtfs.VehiclePosition{
				Vehicle:  &gtfs.VehicleDescriptor{Id: proto.String("bus-42")},
				Position: &gtfs.Position{Latitude: proto.Float32(47.6), Longitude: proto.Float32(-122.3)},
			},
		}},
	}
	b, err := proto.Marshal(feed)
	if err != nil {
		t.Fatalf("marshal fixture: %v", err)
	}
	return b
}

func newTestPoller(t *testing.T, serverBody func() []byte, ft FeedType) (*Poller, *producer.Fake, *httptest.Server) {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", ContentType)
		w.Write(serverBody())
	}))
	t.Cleanup(srv.Close)
	fake := producer.NewFake()
	p := &Poller{
		URL:      srv.URL,
		FeedType: ft,
		Interval: time.Second,
		Producer: fake,
		Log:      slog.New(slog.NewTextHandler(testWriter{t}, nil)),
		Clock:    func() time.Time { return time.Date(2026, 7, 8, 12, 0, 0, 0, time.UTC) },
	}
	return p, fake, srv
}

type testWriter struct{ t *testing.T }

func (w testWriter) Write(p []byte) (int, error) { w.t.Log(string(p)); return len(p), nil }

func TestHappyPathProducesSchemaCompleteEnvelope(t *testing.T) {
	frame := validFrame(t)
	p, fake, srv := newTestPoller(t, func() []byte { return frame }, VehiclePositions)

	if err := p.PollOnce(context.Background()); err != nil {
		t.Fatalf("PollOnce: %v", err)
	}
	msgs := fake.Messages()
	if len(msgs) != 1 {
		t.Fatalf("produced %d messages, want 1", len(msgs))
	}
	msg := msgs[0]
	if msg.Topic != "raw.gtfs_rt.vehicle_positions" {
		t.Errorf("topic = %q, want raw.gtfs_rt.vehicle_positions", msg.Topic)
	}

	var m map[string]any
	if err := json.Unmarshal(msg.Value, &m); err != nil {
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
	if m["parse_status"] != envelope.ParseOK {
		t.Errorf("parse_status = %v, want ok", m["parse_status"])
	}
	if m["source"] != Source || m["connector"] != ConnectorName {
		t.Errorf("source/connector = %v/%v", m["source"], m["connector"])
	}
	if m["feed_url"] != srv.URL {
		t.Errorf("feed_url = %v, want %v", m["feed_url"], srv.URL)
	}

	// Kafka key is the record_id, and record_id hashes the exact raw bytes.
	wantID := envelope.RecordID(frame)
	if string(msg.Key) != wantID {
		t.Errorf("message key = %q, want record_id %q", msg.Key, wantID)
	}
	if m["record_id"] != wantID {
		t.Errorf("record_id = %v, want %v", m["record_id"], wantID)
	}
	// The enveloped payload must be the RAW bytes, byte-identical — never
	// a reserialized form.
	decoded, err := base64.StdEncoding.DecodeString(m["payload"].(string))
	if err != nil {
		t.Fatalf("payload base64: %v", err)
	}
	if string(decoded) != string(frame) {
		t.Errorf("payload bytes differ from raw frame bytes")
	}
}

func TestGarbagePayloadStillProducedAsMalformed(t *testing.T) {
	garbage := []byte("this is definitely not a protobuf FeedMessage frame")
	p, fake, _ := newTestPoller(t, func() []byte { return garbage }, TripUpdates)

	if err := p.PollOnce(context.Background()); err != nil {
		t.Fatalf("PollOnce must not error on malformed payload (never drop): %v", err)
	}
	msgs := fake.Messages()
	if len(msgs) != 1 {
		t.Fatalf("malformed frame was dropped: produced %d messages, want 1", len(msgs))
	}
	if msgs[0].Topic != "raw.gtfs_rt.trip_updates" {
		t.Errorf("topic = %q, want raw.gtfs_rt.trip_updates", msgs[0].Topic)
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
	// Raw garbage bytes still landed byte-identically.
	decoded, _ := base64.StdEncoding.DecodeString(m["payload"].(string))
	if string(decoded) != string(garbage) {
		t.Errorf("malformed payload bytes were mutated")
	}
}

func TestDuplicateConsecutiveFrameSkipped(t *testing.T) {
	frame := validFrame(t)
	current := frame
	p, fake, _ := newTestPoller(t, func() []byte { return current }, Alerts)

	ctx := context.Background()
	if err := p.PollOnce(ctx); err != nil {
		t.Fatalf("poll 1: %v", err)
	}
	if err := p.PollOnce(ctx); err != nil {
		t.Fatalf("poll 2 (duplicate): %v", err)
	}
	if got := len(fake.Messages()); got != 1 {
		t.Fatalf("duplicate frame was produced: %d messages, want 1", got)
	}

	// A changed frame must produce again.
	changed := &gtfs.FeedMessage{Header: &gtfs.FeedHeader{
		GtfsRealtimeVersion: proto.String("2.0"),
		Timestamp:           proto.Uint64(1751976060),
	}}
	var err error
	current, err = proto.Marshal(changed)
	if err != nil {
		t.Fatalf("marshal changed fixture: %v", err)
	}
	if err := p.PollOnce(ctx); err != nil {
		t.Fatalf("poll 3 (changed): %v", err)
	}
	msgs := fake.Messages()
	if len(msgs) != 2 {
		t.Fatalf("changed frame not produced: %d messages, want 2", len(msgs))
	}
	if msgs[0].Topic != "raw.gtfs_rt.alerts" {
		t.Errorf("topic = %q, want raw.gtfs_rt.alerts", msgs[0].Topic)
	}
	if string(msgs[0].Key) == string(msgs[1].Key) {
		t.Errorf("different frames produced identical record_ids")
	}
}

func TestUnknownFeedTypeRejected(t *testing.T) {
	if _, err := FeedType("bogus").Topic(); err == nil {
		t.Fatal("expected error for unknown feed type")
	}
}
