package samsara

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/headway-transit/headway/services/ingestion/internal/envelope"
	"github.com/headway-transit/headway/services/ingestion/internal/producer"
)

// testToken is a stand-in for an agency API token. Several tests assert it
// never appears in a log line, an error message, an envelope or a record.
const testToken = "samsara_test_token_NEVER_LOG_ME_0123456789"

const testTZName = "America/New_York"

// logCapture collects every log line so tests can prove the token is absent.
type logCapture struct {
	mu  sync.Mutex
	buf bytes.Buffer
	t   *testing.T
}

func (c *logCapture) Write(p []byte) (int, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.t.Log(strings.TrimRight(string(p), "\n"))
	return c.buf.Write(p)
}

func (c *logCapture) String() string {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.buf.String()
}

func testLocation(t *testing.T) *time.Location {
	t.Helper()
	loc, err := time.LoadLocation(testTZName)
	if err != nil {
		t.Skipf("system tzdata unavailable (%v)", err)
	}
	return loc
}

// newPoller wires a Poller against an httptest server with fakes for the
// object store, producer, clock and sleep.
func newPoller(t *testing.T, handler http.HandlerFunc) (
	*Poller, *producer.Fake, *FakeStore, *httptest.Server, *logCapture, *[]time.Duration,
) {
	t.Helper()
	srv := httptest.NewServer(handler)
	t.Cleanup(srv.Close)

	fake := producer.NewFake()
	store := NewFakeStore()
	capture := &logCapture{t: t}
	var slept []time.Duration

	p := &Poller{
		BaseURL:    srv.URL,
		Token:      testToken,
		Source:     "samsara",
		ServiceDay: testLocation(t),
		Store:      store,
		Producer:   fake,
		Log:        slog.New(slog.NewJSONHandler(capture, nil)),
		Clock:      func() time.Time { return time.Date(2026, 7, 20, 9, 0, 0, 0, time.UTC) },
		Sleep: func(_ context.Context, d time.Duration) error {
			slept = append(slept, d)
			return nil
		},
		BackoffBase: 10 * time.Millisecond,
	}
	return p, fake, store, srv, capture, &slept
}

func onePage(hasNext bool, cursor string) string {
	return fmt.Sprintf(`{"data":[{"id":"281474977075805","name":"Van 7",`+
		`"obdOdometerMeters":[{"time":"2026-07-19T12:00:00Z","value":14010293}],`+
		`"gpsDistanceMeters":[{"time":"2026-07-19T12:00:05Z","value":81029.591434899}]}],`+
		`"pagination":{"endCursor":%q,"hasNextPage":%t}}`, cursor, hasNext)
}

func day(t *testing.T, y int, m time.Month, d int) time.Time {
	t.Helper()
	return time.Date(y, m, d, 12, 0, 0, 0, testLocation(t))
}

// --- contract / spec conformance -------------------------------------------

// The Go source-label list must never drift from the checked-in contract.
func TestRegisteredSourcesMatchContractEnum(t *testing.T) {
	path := filepath.Join("..", "..", "..", "..", "contracts",
		"fleet-telematics.v0.schema.json")
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read contract: %v", err)
	}
	var schema struct {
		Properties struct {
			SourceSystem struct {
				Enum []string `json:"enum"`
			} `json:"source_system"`
		} `json:"properties"`
	}
	if err := json.Unmarshal(raw, &schema); err != nil {
		t.Fatalf("parse contract: %v", err)
	}
	got := strings.Join(RegisteredSources, ",")
	want := strings.Join(schema.Properties.SourceSystem.Enum, ",")
	if got != want {
		t.Fatalf("RegisteredSources = %q, contract source_system enum = %q "+
			"(the connector must never carry a label the contract does not "+
			"register)", got, want)
	}
}

// The vendor's OpenAPI document caps `types` at three per request; the
// distance set sits exactly at that cap, which is why engine time is a
// separate request.
func TestStatTypeSetsRespectVendorThreeTypeLimit(t *testing.T) {
	if len(DistanceStatTypes) != MaxStatTypesPerRequest {
		t.Errorf("DistanceStatTypes has %d types, expected exactly the "+
			"documented maximum %d", len(DistanceStatTypes), MaxStatTypesPerRequest)
	}
	for _, set := range [][]string{DistanceStatTypes, EngineTimeStatTypes} {
		if len(set) > MaxStatTypesPerRequest {
			t.Errorf("stat set %v exceeds the vendor's documented limit of %d",
				set, MaxStatTypesPerRequest)
		}
	}
}

func TestEngineTimeIsASeparateRequest(t *testing.T) {
	p, _, _, _, _, _ := newPoller(t, func(w http.ResponseWriter, r *http.Request) {})
	if got := len(p.statTypeSets()); got != 1 {
		t.Fatalf("engine time off: %d request sets, want 1", got)
	}
	p.IncludeEngineTime = true
	sets := p.statTypeSets()
	if len(sets) != 2 {
		t.Fatalf("engine time on: %d request sets, want 2", len(sets))
	}
	if strings.Join(sets[0], ",") == strings.Join(sets[1], ",") {
		t.Error("distance and engine-time sets must differ")
	}
}

// --- fail-closed configuration ---------------------------------------------

func TestRefusesWithoutToken(t *testing.T) {
	p := &Poller{Source: "samsara", ServiceDay: time.UTC,
		Store: NewFakeStore(), Producer: producer.NewFake(),
		Log: slog.New(slog.NewJSONHandler(&logCapture{t: t}, nil))}
	err := p.Check()
	if err == nil {
		t.Fatal("Check() succeeded without a token; must fail closed")
	}
	msg := err.Error()
	for _, want := range []string{"SAMSARA_API_TOKEN", "Read Vehicle Statistics"} {
		if !strings.Contains(msg, want) {
			t.Errorf("refusal message missing %q; got: %s", want, msg)
		}
	}
}

func TestRefusesWithoutSourceLabel(t *testing.T) {
	p := &Poller{Token: testToken, ServiceDay: time.UTC,
		Store: NewFakeStore(), Producer: producer.NewFake(),
		Log: slog.New(slog.NewJSONHandler(&logCapture{t: t}, nil))}
	err := p.Check()
	if err == nil || !strings.Contains(err.Error(), "samsara_simulated") {
		t.Fatalf("expected a fail-closed source-label refusal naming the "+
			"simulated label; got %v", err)
	}
}

func TestRefusesUnregisteredSourceLabel(t *testing.T) {
	p := &Poller{Token: testToken, Source: "samsara_prod", ServiceDay: time.UTC,
		Store: NewFakeStore(), Producer: producer.NewFake(),
		Log: slog.New(slog.NewJSONHandler(&logCapture{t: t}, nil))}
	err := p.Check()
	if err == nil || !strings.Contains(err.Error(), "REGISTERED") {
		t.Fatalf("unregistered label must be refused; got %v", err)
	}
	if SourceRegistered("samsara_prod") {
		t.Error("SourceRegistered accepted an unregistered label")
	}
	for _, ok := range RegisteredSources {
		if !SourceRegistered(ok) {
			t.Errorf("SourceRegistered rejected registered label %q", ok)
		}
	}
}

func TestRefusesWithoutDeclaredServiceDayTimezone(t *testing.T) {
	p := &Poller{Token: testToken, Source: "samsara",
		Store: NewFakeStore(), Producer: producer.NewFake(),
		Log: slog.New(slog.NewJSONHandler(&logCapture{t: t}, nil))}
	err := p.Check()
	if err == nil || !strings.Contains(err.Error(), "SAMSARA_SERVICE_DAY_TZ") {
		t.Fatalf("a missing declared timezone must be refused; got %v", err)
	}
}

func TestRefusalMessagesNeverContainTheToken(t *testing.T) {
	p := &Poller{Token: testToken,
		Log: slog.New(slog.NewJSONHandler(&logCapture{t: t}, nil))}
	err := p.Check()
	if err == nil {
		t.Fatal("expected refusal")
	}
	if strings.Contains(err.Error(), testToken) {
		t.Fatal("refusal message leaked the API token")
	}
}

// --- happy path -------------------------------------------------------------

func TestHappyPathLandsExactBytesThenProducesEnvelope(t *testing.T) {
	body := onePage(false, "")
	var gotAuth, gotQuery string
	p, fake, store, srv, capture, _ := newPoller(t,
		func(w http.ResponseWriter, r *http.Request) {
			gotAuth = r.Header.Get("Authorization")
			gotQuery = r.URL.RawQuery
			w.Header().Set("Content-Type", ContentType)
			fmt.Fprint(w, body)
		})

	n, err := p.PollWindow(context.Background(), day(t, 2026, time.July, 19))
	if err != nil {
		t.Fatalf("PollWindow: %v", err)
	}
	if n != 1 {
		t.Fatalf("produced %d records, want 1", n)
	}

	// Documented bearer authentication: header, never a query parameter.
	if gotAuth != "Bearer "+testToken {
		t.Errorf("Authorization header = %q", gotAuth)
	}
	if strings.Contains(gotQuery, testToken) {
		t.Error("token leaked into the query string")
	}
	for _, want := range []string{"startTime=", "endTime=", "types="} {
		if !strings.Contains(gotQuery, want) {
			t.Errorf("query %q missing required parameter %q", gotQuery, want)
		}
	}
	// Exactly the three documented distance types, comma-separated.
	if !strings.Contains(gotQuery,
		"types="+strings.Join(DistanceStatTypes, "%2C")) {
		t.Errorf("types parameter not the documented distance set: %q", gotQuery)
	}
	// Local service-day boundaries, RFC 3339 with an offset (URL-encoded).
	if !strings.Contains(gotQuery, "2026-07-19T00%3A00%3A00-04%3A00") ||
		!strings.Contains(gotQuery, "2026-07-20T00%3A00%3A00-04%3A00") {
		t.Errorf("window is not the declared local service day: %q", gotQuery)
	}

	msgs := fake.Messages()
	if len(msgs) != 1 {
		t.Fatalf("produced %d messages, want 1", len(msgs))
	}
	if msgs[0].Topic != Topic {
		t.Errorf("topic = %q, want %q", msgs[0].Topic, Topic)
	}

	// The record is the MINIMIZED response (data minimization at the
	// connector boundary), and record_id hashes exactly what was landed.
	wantBytes, dropped, ok := minimizePage([]byte(body), DistanceStatTypes)
	if !ok {
		t.Fatal("fixture page could not be minimized")
	}
	if len(dropped) != 0 {
		t.Errorf("fixture dropped %v; this test's page should already be minimal", dropped)
	}
	wantID := envelope.RecordID(wantBytes)
	if string(msgs[0].Key) != wantID {
		t.Errorf("message key = %q, want record_id %q", msgs[0].Key, wantID)
	}

	var env map[string]any
	if err := json.Unmarshal(msgs[0].Value, &env); err != nil {
		t.Fatalf("envelope not JSON: %v", err)
	}
	for _, k := range []string{
		"envelope_version", "record_id", "source", "connector",
		"connector_version", "fetched_at", "content_type",
		"payload_encoding", "payload", "parse_status",
	} {
		if _, ok := env[k]; !ok {
			t.Errorf("envelope missing required field %q", k)
		}
	}
	if env["parse_status"] != envelope.ParseOK {
		t.Errorf("parse_status = %v, want ok", env["parse_status"])
	}
	if env["payload_encoding"] != envelope.EncodingObjectRef {
		t.Errorf("payload_encoding = %v, want object_ref", env["payload_encoding"])
	}
	if env["source"] != "samsara" || env["connector"] != ConnectorName {
		t.Errorf("source/connector = %v/%v", env["source"], env["connector"])
	}
	if env["record_id"] != wantID {
		t.Errorf("record_id = %v, want %v", env["record_id"], wantID)
	}
	if env["payload"] != ObjectKey(wantID) {
		t.Errorf("payload = %v, want object key %v", env["payload"], ObjectKey(wantID))
	}
	feedURL, _ := env["feed_url"].(string)
	if !strings.HasPrefix(feedURL, srv.URL+StatsHistoryPath) {
		t.Errorf("feed_url = %q, want the request URL", feedURL)
	}
	if strings.Contains(feedURL, testToken) {
		t.Fatal("feed_url leaked the API token")
	}

	// The landed object is exactly what was hashed, with every measured
	// value preserved verbatim.
	landed, ok := store.Get(ObjectKey(wantID))
	if !ok {
		t.Fatalf("no object landed at %s", ObjectKey(wantID))
	}
	if envelope.RecordID(landed) != wantID {
		t.Error("record_id does not hash the bytes that were landed")
	}
	if !bytes.Contains(landed, []byte("14010293")) ||
		!bytes.Contains(landed, []byte("81029.591434899")) {
		t.Error("landed object lost a measured value (numbers must survive verbatim)")
	}

	// The token appears nowhere in the logs or the produced bytes.
	if strings.Contains(capture.String(), testToken) {
		t.Fatal("API token leaked into the logs")
	}
	if bytes.Contains(msgs[0].Value, []byte(testToken)) {
		t.Fatal("API token leaked into the produced envelope")
	}
}

func TestStoreBeforeProduce(t *testing.T) {
	p, fake, store, _, _, _ := newPoller(t,
		func(w http.ResponseWriter, r *http.Request) {
			fmt.Fprint(w, onePage(false, ""))
		})
	store.Err = fmt.Errorf("object store down")

	if _, err := p.PollWindow(context.Background(), day(t, 2026, time.July, 19)); err == nil {
		t.Fatal("expected a landing failure")
	}
	if got := len(fake.Messages()); got != 0 {
		t.Fatalf("produced %d messages after a landing failure; a consumer "+
			"must never see an envelope whose object does not exist", got)
	}
}

// --- pagination -------------------------------------------------------------

func TestPaginationFollowsEndCursor(t *testing.T) {
	var cursors []string
	p, fake, store, _, _, _ := newPoller(t,
		func(w http.ResponseWriter, r *http.Request) {
			after := r.URL.Query().Get("after")
			cursors = append(cursors, after)
			switch after {
			case "":
				fmt.Fprint(w, onePage(true, "MjkY"))
			case "MjkY":
				fmt.Fprint(w, onePage(false, ""))
			default:
				t.Errorf("unexpected cursor %q", after)
			}
		})

	n, err := p.PollWindow(context.Background(), day(t, 2026, time.July, 19))
	if err != nil {
		t.Fatalf("PollWindow: %v", err)
	}
	if n != 2 || len(fake.Messages()) != 2 || store.Len() != 2 {
		t.Fatalf("produced=%d messages=%d objects=%d, want 2/2/2",
			n, len(fake.Messages()), store.Len())
	}
	if len(cursors) != 2 || cursors[0] != "" || cursors[1] != "MjkY" {
		t.Fatalf("cursor sequence = %v, want [\"\", \"MjkY\"]", cursors)
	}
}

func TestPaginationStopsLoudlyOnAStuckCursor(t *testing.T) {
	p, fake, _, _, _, _ := newPoller(t,
		func(w http.ResponseWriter, r *http.Request) {
			// hasNextPage true but no cursor to advance on.
			fmt.Fprint(w, onePage(true, ""))
		})
	_, err := p.PollWindow(context.Background(), day(t, 2026, time.July, 19))
	if err == nil || !strings.Contains(err.Error(), "no new endCursor") {
		t.Fatalf("a stuck cursor must fail loudly; got %v", err)
	}
	if len(fake.Messages()) != 1 {
		t.Errorf("the page itself must still be landed and produced; got %d",
			len(fake.Messages()))
	}
}

// --- rate limits and server errors -----------------------------------------

func TestRateLimitHonoursRetryAfterThenSucceeds(t *testing.T) {
	calls := 0
	p, fake, _, _, capture, slept := newPoller(t,
		func(w http.ResponseWriter, r *http.Request) {
			calls++
			if calls == 1 {
				// The vendor documents Retry-After in seconds, shown as a
				// fractional value.
				w.Header().Set("Retry-After", "0.40235")
				w.WriteHeader(http.StatusTooManyRequests)
				return
			}
			fmt.Fprint(w, onePage(false, ""))
		})

	if _, err := p.PollWindow(context.Background(), day(t, 2026, time.July, 19)); err != nil {
		t.Fatalf("PollWindow: %v", err)
	}
	if calls != 2 {
		t.Fatalf("server called %d times, want 2 (one 429 + one retry)", calls)
	}
	if len(*slept) != 1 {
		t.Fatalf("slept %d times, want 1", len(*slept))
	}
	want := time.Duration(0.40235 * float64(time.Second))
	if (*slept)[0] != want {
		t.Errorf("backoff = %v, want the Retry-After value %v", (*slept)[0], want)
	}
	if len(fake.Messages()) != 1 {
		t.Errorf("produced %d messages, want 1", len(fake.Messages()))
	}
	if strings.Contains(capture.String(), testToken) {
		t.Fatal("token leaked into a rate-limit log line")
	}
}

func TestRateLimitWithoutHeaderFallsBackToBackoff(t *testing.T) {
	calls := 0
	p, _, _, _, _, slept := newPoller(t,
		func(w http.ResponseWriter, r *http.Request) {
			calls++
			if calls == 1 {
				w.WriteHeader(http.StatusTooManyRequests)
				return
			}
			fmt.Fprint(w, onePage(false, ""))
		})
	if _, err := p.PollWindow(context.Background(), day(t, 2026, time.July, 19)); err != nil {
		t.Fatalf("PollWindow: %v", err)
	}
	if len(*slept) != 1 || (*slept)[0] != p.backoffBase() {
		t.Fatalf("slept %v, want one backoffBase wait", *slept)
	}
}

func TestServerErrorBacksOffExponentiallyThenGivesUpLoudly(t *testing.T) {
	calls := 0
	p, fake, _, _, _, slept := newPoller(t,
		func(w http.ResponseWriter, r *http.Request) {
			calls++
			w.WriteHeader(http.StatusBadGateway)
		})
	p.MaxAttempts = 3

	_, err := p.PollWindow(context.Background(), day(t, 2026, time.July, 19))
	if err == nil || !strings.Contains(err.Error(), "502") {
		t.Fatalf("expected a loud 5xx failure, got %v", err)
	}
	if calls != 3 {
		t.Fatalf("server called %d times, want MaxAttempts=3", calls)
	}
	if len(*slept) != 2 {
		t.Fatalf("slept %d times, want 2", len(*slept))
	}
	if (*slept)[1] != 2*(*slept)[0] {
		t.Errorf("backoff not exponential: %v", *slept)
	}
	if len(fake.Messages()) != 0 {
		t.Error("nothing may be produced when no bytes were received")
	}
}

func TestUnauthorizedIsNotRetriedAndNamesTheScope(t *testing.T) {
	calls := 0
	p, _, _, _, _, _ := newPoller(t,
		func(w http.ResponseWriter, r *http.Request) {
			calls++
			w.WriteHeader(http.StatusUnauthorized)
		})
	_, err := p.PollWindow(context.Background(), day(t, 2026, time.July, 19))
	if err == nil {
		t.Fatal("expected a 401 failure")
	}
	if calls != 1 {
		t.Errorf("a 401 must not be retried; server called %d times", calls)
	}
	if !strings.Contains(err.Error(), "Read Vehicle Statistics") {
		t.Errorf("401 message should name the required scope: %v", err)
	}
	if strings.Contains(err.Error(), testToken) {
		t.Fatal("401 message leaked the token")
	}
}

// --- malformed / partial responses ------------------------------------------

func TestMalformedPageIsLandedNotDropped(t *testing.T) {
	garbage := `{"data": not json`
	p, fake, store, _, _, _ := newPoller(t,
		func(w http.ResponseWriter, r *http.Request) {
			fmt.Fprint(w, garbage)
		})

	_, err := p.PollWindow(context.Background(), day(t, 2026, time.July, 19))
	if err == nil || !strings.Contains(err.Error(), "malformed") {
		t.Fatalf("a malformed page must fail loudly; got %v", err)
	}

	msgs := fake.Messages()
	if len(msgs) != 1 {
		t.Fatalf("malformed page produced %d messages, want 1 (never dropped)",
			len(msgs))
	}
	var env map[string]any
	if err := json.Unmarshal(msgs[0].Value, &env); err != nil {
		t.Fatalf("envelope not JSON: %v", err)
	}
	if env["parse_status"] != envelope.ParseMalformed {
		t.Errorf("parse_status = %v, want malformed", env["parse_status"])
	}
	if env["parse_error"] == nil || env["parse_error"] == "" {
		t.Error("parse_error is required when parse_status is malformed")
	}
	if landed, ok := store.Get(ObjectKey(envelope.RecordID([]byte(garbage)))); !ok {
		t.Error("malformed page was not landed")
	} else if string(landed) != garbage {
		t.Error("landed bytes were mutated")
	}
}

func TestResponseMissingRequiredPaginationIsMalformed(t *testing.T) {
	// Valid JSON, but not the documented VehicleStatsListResponse: the
	// vendor's spec marks data and pagination (with endCursor and
	// hasNextPage) as required.
	p, fake, _, _, _, _ := newPoller(t,
		func(w http.ResponseWriter, r *http.Request) {
			fmt.Fprint(w, `{"data":[]}`)
		})
	_, err := p.PollWindow(context.Background(), day(t, 2026, time.July, 19))
	if err == nil || !strings.Contains(err.Error(), "malformed") {
		t.Fatalf("missing pagination must be malformed; got %v", err)
	}
	msgs := fake.Messages()
	if len(msgs) != 1 {
		t.Fatalf("produced %d messages, want 1", len(msgs))
	}
	var env map[string]any
	_ = json.Unmarshal(msgs[0].Value, &env)
	if env["parse_status"] != envelope.ParseMalformed {
		t.Errorf("parse_status = %v, want malformed", env["parse_status"])
	}
}

func TestEmptyBodyProducesNothing(t *testing.T) {
	p, fake, store, _, _, _ := newPoller(t,
		func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(http.StatusOK)
		})
	_, err := p.PollWindow(context.Background(), day(t, 2026, time.July, 19))
	if err == nil || !strings.Contains(err.Error(), "empty body") {
		t.Fatalf("an empty 200 must fail loudly; got %v", err)
	}
	if len(fake.Messages()) != 0 || store.Len() != 0 {
		t.Error("nothing may be landed or produced when no bytes arrived")
	}
}

func TestOversizePageIsRefusedNotTruncated(t *testing.T) {
	big := strings.Repeat("x", 4096)
	p, fake, store, _, _, _ := newPoller(t,
		func(w http.ResponseWriter, r *http.Request) {
			fmt.Fprint(w, big)
		})
	p.MaxPageBytes = 512

	_, err := p.PollWindow(context.Background(), day(t, 2026, time.July, 19))
	if err == nil || !strings.Contains(err.Error(), "page limit") {
		t.Fatalf("an oversize page must be refused loudly; got %v", err)
	}
	if len(fake.Messages()) != 0 || store.Len() != 0 {
		t.Error("an oversize page must never land truncated")
	}
}

// --- idempotence ------------------------------------------------------------

func TestIdenticalRepollProducesNothingNew(t *testing.T) {
	p, fake, store, _, _, _ := newPoller(t,
		func(w http.ResponseWriter, r *http.Request) {
			fmt.Fprint(w, onePage(false, ""))
		})
	ctx := context.Background()
	d := day(t, 2026, time.July, 19)

	if _, err := p.PollWindow(ctx, d); err != nil {
		t.Fatalf("first poll: %v", err)
	}
	if _, err := p.PollWindow(ctx, d); err != nil {
		t.Fatalf("second poll: %v", err)
	}
	if got := len(fake.Messages()); got != 1 {
		t.Fatalf("re-polling identical bytes produced %d messages, want 1", got)
	}
	if store.Len() != 1 {
		t.Fatalf("re-polling landed %d objects, want 1 (content-addressed)",
			store.Len())
	}
}

func TestChangedBytesProduceANewRecord(t *testing.T) {
	call := 0
	p, fake, store, _, _, _ := newPoller(t,
		func(w http.ResponseWriter, r *http.Request) {
			call++
			if call == 1 {
				fmt.Fprint(w, onePage(false, ""))
				return
			}
			// A later sample arrived; the bytes differ, so the record differs.
			fmt.Fprint(w, strings.Replace(onePage(false, ""),
				"14010293", "14019999", 1))
		})
	ctx := context.Background()
	d := day(t, 2026, time.July, 19)

	if _, err := p.PollWindow(ctx, d); err != nil {
		t.Fatalf("first poll: %v", err)
	}
	if _, err := p.PollWindow(ctx, d); err != nil {
		t.Fatalf("second poll: %v", err)
	}
	if got := len(fake.Messages()); got != 2 {
		t.Fatalf("changed bytes produced %d messages, want 2", got)
	}
	if store.Len() != 2 {
		t.Fatalf("changed bytes landed %d objects, want 2", store.Len())
	}
}

// --- service-day windows ----------------------------------------------------

func TestServiceDayWindowUsesDeclaredZoneAndIsNotAssumed24Hours(t *testing.T) {
	p, _, _, _, _, _ := newPoller(t, func(w http.ResponseWriter, r *http.Request) {})

	// 2026-03-08 is the US spring-forward date: a 23-hour local day.
	start, end := p.ServiceDayWindow(day(t, 2026, time.March, 8))
	if got := end.Sub(start); got != 23*time.Hour {
		t.Errorf("spring-forward service day = %v, want 23h (the day length "+
			"is whatever the declared zone says, never assumed)", got)
	}
	if start.Format(time.RFC3339) != "2026-03-08T00:00:00-05:00" {
		t.Errorf("window start = %s", start.Format(time.RFC3339))
	}

	// 2026-11-01 is the fall-back date: a 25-hour local day.
	start, end = p.ServiceDayWindow(day(t, 2026, time.November, 1))
	if got := end.Sub(start); got != 25*time.Hour {
		t.Errorf("fall-back service day = %v, want 25h", got)
	}
}

func TestPollOnceCoversTheBackfillSpanEndingAtTheLag(t *testing.T) {
	var windows []string
	p, _, _, _, _, _ := newPoller(t,
		func(w http.ResponseWriter, r *http.Request) {
			windows = append(windows, r.URL.Query().Get("startTime"))
			fmt.Fprint(w, onePage(false, ""))
		})
	// Clock: 2026-07-20T09:00Z == 2026-07-20 05:00 local.
	p.LagDays = 1
	p.BackfillDays = 3

	if err := p.PollOnce(context.Background()); err != nil {
		t.Fatalf("PollOnce: %v", err)
	}
	want := []string{
		"2026-07-17T00:00:00-04:00",
		"2026-07-18T00:00:00-04:00",
		"2026-07-19T00:00:00-04:00",
	}
	if len(windows) != len(want) {
		t.Fatalf("polled %d windows (%v), want %d", len(windows), windows, len(want))
	}
	for i := range want {
		if windows[i] != want[i] {
			t.Errorf("window %d = %s, want %s", i, windows[i], want[i])
		}
	}
}

func TestEngineTimeRequestIsIssuedSeparately(t *testing.T) {
	var typeParams []string
	p, fake, _, _, _, _ := newPoller(t,
		func(w http.ResponseWriter, r *http.Request) {
			types := r.URL.Query().Get("types")
			typeParams = append(typeParams, types)
			// Distinct bodies: distance and engine-time pages are different
			// records, so both must be landed and produced.
			fmt.Fprintf(w, `{"data":[{"id":"1","name":"Van 7","%s":[]}],`+
				`"pagination":{"endCursor":"","hasNextPage":false}}`,
				strings.Split(types, ",")[0])
		})
	p.IncludeEngineTime = true

	if _, err := p.PollWindow(context.Background(), day(t, 2026, time.July, 19)); err != nil {
		t.Fatalf("PollWindow: %v", err)
	}
	if len(typeParams) != 2 {
		t.Fatalf("issued %d requests (%v), want 2", len(typeParams), typeParams)
	}
	if typeParams[0] != strings.Join(DistanceStatTypes, ",") {
		t.Errorf("first request types = %q", typeParams[0])
	}
	if typeParams[1] != strings.Join(EngineTimeStatTypes, ",") {
		t.Errorf("second request types = %q", typeParams[1])
	}
	if len(fake.Messages()) != 2 {
		t.Errorf("produced %d messages, want 2", len(fake.Messages()))
	}
}

func TestRetryAfterParsing(t *testing.T) {
	fallback := 3 * time.Second
	cases := []struct {
		header string
		want   time.Duration
	}{
		{"0.40235", time.Duration(0.40235 * float64(time.Second))},
		{"2", 2 * time.Second},
		{"", fallback},
		{"soon", fallback},
		{"-1", fallback},
	}
	for _, c := range cases {
		if got := parseRetryAfter(c.header, fallback); got != c.want {
			t.Errorf("parseRetryAfter(%q) = %v, want %v", c.header, got, c.want)
		}
	}
}

// --- data minimization (handoff 0028 governance addition) -------------------

// A response carrying driver-identified and unrequested fields must have
// them removed BEFORE anything is hashed, landed or produced.
func TestDriverIdentifiedFieldsAreDroppedBeforeAnythingIsStored(t *testing.T) {
	// SYNTHETIC page deliberately padded with fields Headway never requests:
	// an employee-linking externalIds (the vendor's own example for it is a
	// payrollId), ID-card scans, a driver object, and per-sample GPS
	// decorations.
	body := `{"data":[{"id":"veh-1","name":"Van 7",` +
		`"externalIds":{"payrollId":"ABFS18600","maintenanceId":"250020"},` +
		`"nfcCardScans":[{"time":"2026-07-19T12:00:00Z","value":{"badgeId":"EMP-4471"}}],` +
		`"driver":{"id":"drv-99","name":"A. Operator"},` +
		`"obdOdometerMeters":[{"time":"2026-07-19T12:00:00Z","value":14010293,` +
		`"decorations":{"gps":{"latitude":42.36,"longitude":-71.06}}}]}],` +
		`"pagination":{"endCursor":"","hasNextPage":false},"extraTopLevel":1}`

	p, fake, store, _, capture, _ := newPoller(t,
		func(w http.ResponseWriter, r *http.Request) { fmt.Fprint(w, body) })

	if _, err := p.PollWindow(context.Background(), day(t, 2026, time.July, 19)); err != nil {
		t.Fatalf("PollWindow: %v", err)
	}

	msgs := fake.Messages()
	if len(msgs) != 1 {
		t.Fatalf("produced %d messages, want 1", len(msgs))
	}
	var env map[string]any
	if err := json.Unmarshal(msgs[0].Value, &env); err != nil {
		t.Fatalf("envelope not JSON: %v", err)
	}
	landed, ok := store.Get(env["payload"].(string))
	if !ok {
		t.Fatalf("nothing landed at %v", env["payload"])
	}

	// NOTHING driver-identified reached the object store.
	for _, forbidden := range []string{
		"payrollId", "ABFS18600", "maintenanceId", "250020",
		"nfcCardScans", "badgeId", "EMP-4471",
		"driver", "drv-99", "A. Operator",
		"decorations", "latitude", "42.36", "extraTopLevel",
	} {
		if bytes.Contains(landed, []byte(forbidden)) {
			t.Errorf("landed raw record still contains %q — driver-identified "+
				"and unrequested data must be dropped BEFORE the first write",
				forbidden)
		}
	}
	// The measurement itself survived, verbatim.
	if !bytes.Contains(landed, []byte("14010293")) ||
		!bytes.Contains(landed, []byte("veh-1")) ||
		!bytes.Contains(landed, []byte("Van 7")) {
		t.Errorf("minimization removed data Headway does need: %s", landed)
	}
	// record_id hashes what was landed, so lineage still resolves.
	if env["record_id"] != envelope.RecordID(landed) {
		t.Error("record_id does not hash the landed bytes")
	}

	// Dropped key NAMES are logged; dropped VALUES never are.
	logs := capture.String()
	if !strings.Contains(logs, "data minimization") {
		t.Error("the drop was not logged")
	}
	for _, name := range []string{"data[].externalIds", "data[].nfcCardScans",
		"data[].driver", "extraTopLevel"} {
		if !strings.Contains(logs, name) {
			t.Errorf("log does not name the dropped key %q", name)
		}
	}
	for _, value := range []string{"ABFS18600", "EMP-4471", "A. Operator", "42.36"} {
		if strings.Contains(logs, value) {
			t.Errorf("log leaked a dropped VALUE %q", value)
		}
	}
}

func TestMinimizationKeepsOnlyTheAllowList(t *testing.T) {
	body := []byte(`{"data":[{"id":"v","name":"n","externalIds":{"a":"b"},` +
		`"obdOdometerMeters":[{"time":"t","value":1,"decorations":{}}],` +
		`"fuelPercents":[{"time":"t","value":50}]}],` +
		`"pagination":{"endCursor":"","hasNextPage":false}}`)
	out, dropped, ok := minimizePage(body, DistanceStatTypes)
	if !ok {
		t.Fatal("minimizePage refused a well-formed page")
	}
	want := []string{
		"data[].externalIds",
		"data[].fuelPercents",
		"data[].obdOdometerMeters[].decorations",
	}
	if strings.Join(dropped, "|") != strings.Join(want, "|") {
		t.Errorf("dropped = %v, want %v", dropped, want)
	}
	var doc map[string]any
	if err := json.Unmarshal(out, &doc); err != nil {
		t.Fatalf("minimized output is not JSON: %v", err)
	}
	if _, present := doc["pagination"]; !present {
		t.Error("pagination must survive: the connector needs the cursor")
	}
	vehicle := doc["data"].([]any)[0].(map[string]any)
	gotKeys := make([]string, 0, len(vehicle))
	for k := range vehicle {
		gotKeys = append(gotKeys, k)
	}
	sort.Strings(gotKeys)
	if strings.Join(gotKeys, ",") != "id,name,obdOdometerMeters" {
		t.Errorf("vehicle keys = %v, want id,name,obdOdometerMeters", gotKeys)
	}
}

// Minimization must not change a number's value or its literal form, or
// re-polls would stop being idempotent and measurements would drift.
func TestMinimizationPreservesNumericLiteralsAndIsDeterministic(t *testing.T) {
	body := []byte(`{"data":[{"id":"v","gpsDistanceMeters":` +
		`[{"time":"t","value":81029.591434899},{"time":"u","value":14010293}]}],` +
		`"pagination":{"endCursor":"","hasNextPage":false}}`)
	first, _, ok := minimizePage(body, DistanceStatTypes)
	if !ok {
		t.Fatal("minimizePage refused a well-formed page")
	}
	second, _, _ := minimizePage(body, DistanceStatTypes)
	if !bytes.Equal(first, second) {
		t.Fatal("minimization is not deterministic; re-polls would not be idempotent")
	}
	for _, literal := range []string{"81029.591434899", "14010293"} {
		if !bytes.Contains(first, []byte(literal)) {
			t.Errorf("numeric literal %q did not survive verbatim: %s", literal, first)
		}
	}
}

// A page that cannot be minimized is still landed (evidence is never
// destroyed) — as malformed, and only because the scope Headway asks for
// cannot return driver records in the first place.
func TestUnminimizablePageIsLandedAsMalformed(t *testing.T) {
	if _, _, ok := minimizePage([]byte(`{"data":"not-a-list"}`), DistanceStatTypes); ok {
		t.Error("minimizePage accepted a page whose data is not a list")
	}
	p, fake, _, _, _, _ := newPoller(t,
		func(w http.ResponseWriter, r *http.Request) {
			fmt.Fprint(w, `{"data":"not-a-list","pagination":{"endCursor":"","hasNextPage":false}}`)
		})
	_, err := p.PollWindow(context.Background(), day(t, 2026, time.July, 19))
	if err == nil || !strings.Contains(err.Error(), "malformed") {
		t.Fatalf("expected a loud malformed failure, got %v", err)
	}
	if len(fake.Messages()) != 1 {
		t.Fatalf("the page must still be landed, never dropped; got %d messages",
			len(fake.Messages()))
	}
}

// Headway must never request a stat type that returns driver-identified
// data. This pins the request surface so a future edit cannot widen it
// without a deliberate change to this test.
func TestRequestSurfaceCarriesNoDriverIdentifiedTypes(t *testing.T) {
	forbidden := map[string]string{
		"nfcCardScans": "ID-card scans identify the operator",
		"gps":          "GPS positions are not needed for daily distance",
		"faultCodes":   "not needed for distance or engine time",
	}
	for _, set := range [][]string{DistanceStatTypes, EngineTimeStatTypes} {
		for _, statType := range set {
			if why, bad := forbidden[statType]; bad {
				t.Errorf("requested stat type %q must not be requested: %s",
					statType, why)
			}
		}
	}
	// Decorations are never requested at all.
	p, _, _, _, _, _ := newPoller(t, func(w http.ResponseWriter, r *http.Request) {})
	if strings.Contains(p.buildURL(time.Now(), time.Now(), DistanceStatTypes, ""),
		"decorations") {
		t.Error("the request URL must never ask for decorations")
	}
}
