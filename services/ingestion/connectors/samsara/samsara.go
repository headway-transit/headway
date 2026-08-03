// Package samsara is the Samsara fleet-telematics poller connector (handoff
// 0028). It pulls vehicle stat history one DECLARED SERVICE DAY at a time,
// reduces each API response page to the data-minimization allow-list, lands
// those exact bytes content-addressed in the object store, and produces an
// object_ref raw-record envelope to raw.telematics.vehicle_stats keyed by
// record_id. See "DATA MINIMIZATION AT THE CONNECTOR BOUNDARY" below for why
// the raw record is the minimized response rather than the wire response.
//
// WHAT THIS CONNECTOR IS NOT. It does not compute anything. Telematics
// distance is NOT revenue miles and engine time is NOT revenue hours (an
// odometer delta includes deadhead, personal use and maintenance travel);
// see the honesty wall in contracts/fleet-telematics.v0.md. This connector
// captures measured vehicle movement and hands it on. Interpreting the bytes
// is the transform's job; turning any of it into a reportable figure is a
// separate, compliance-gated wave that has not happened.
//
// EVERY API DETAIL BELOW IS DERIVED FROM THE VENDOR'S PUBLISHED OPENAPI
// DOCUMENT, NOT FROM MEMORY:
//
//	https://developers.samsara.com/openapi/samsara-api.json
//	info.version 2025-10-23 (OpenAPI 3.0.1), retrieved 2026-07-29,
//	sha256 2ed9a10c736189354662585f50ea6a756b73d5fecb6663b2ee122fdca994730e
//
// Anything the spec does not pin is left unimplemented and recorded in
// README.md — a fabricated endpoint shape would be worse than nothing. No
// live Samsara account has ever been contacted (see README.md,
// "Verification status").
//
// House rules held, in the shape of the existing connectors:
//
//   - Fail closed. No API token, no source label, no declared service-day
//     timezone => the connector REFUSES to start with a plain-language
//     message (the drop-dir precedent), never a guessed default.
//   - Secrets never logged. The bearer token is only ever written into an
//     Authorization header; it appears in no log line, no error message, no
//     envelope field and no raw record. Request URLs are logged, and the
//     token is a header, never a query parameter.
//   - Store before produce. A page's bytes are landed in the object store
//     before its envelope is produced, so a consumer can never see an
//     envelope whose object does not exist.
//   - Content-addressed raw records. record_id is the SHA-256 of the exact
//     bytes landed (the minimized response), so identical re-polls are
//     idempotent by construction.
//   - Fail loudly. A page that does not parse as the documented response
//     shape is STILL landed and produced with parse_status "malformed" and
//     a parse_error; the window then stops rather than paginating on a
//     cursor Headway could not read.
//   - Registered source labels only. `samsara` for a real account,
//     `samsara_simulated` for anything synthetic (handoff 0005/0015 rules);
//     the label enum lives in contracts/fleet-telematics.v0.schema.json and
//     an unregistered label is refused here AND in the transform.
//
// DATA MINIMIZATION AT THE CONNECTOR BOUNDARY (handoff 0028 governance
// addition, 2026-07-29). Fleet telematics is EMPLOYEE-MONITORING data. The
// first partner agency has no records officer and is only now standing up a
// data-classification program, so this connector collects the minimum that
// serves the stated purpose — vehicle-level distance and time — and nothing
// else, by construction rather than by convention:
//
//   - Headway requests ONLY the five vehicle-statistics series in
//     DistanceStatTypes and EngineTimeStatTypes. It never requests GPS
//     positions, `decorations`, ID-card scans (`nfcCardScans`), driver
//     records, hours-of-service, safety scores, harsh-event records or
//     dashcam references, and the token scope it asks for cannot return
//     them.
//   - An ALLOW-LIST is enforced on every response BEFORE anything is
//     hashed, landed or produced: per vehicle only `id`, `name` and the
//     stat series that were requested survive, and within each sample only
//     `time` and `value`. Anything else the vendor sends — including
//     `externalIds` (whose own spec example is a `payrollId`) and any
//     driver-identified field added in a future API version — is DROPPED
//     BEFORE THE FIRST WRITE. It is never landed "just in case".
//
// This is a DELIBERATE, governance-mandated exception to "the raw record is
// the exact bytes as received": the raw record is the exact bytes of the
// MINIMIZED response. Minimization is deterministic (allow-list filtering,
// numbers preserved as their original literals, canonical key order), so
// identical responses still produce identical record_ids and re-polls stay
// idempotent. Dropped key NAMES are logged; dropped VALUES never are. See
// README.md, "Data minimization".
package samsara

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/url"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/headway-transit/headway/services/ingestion/internal/envelope"
	"github.com/headway-transit/headway/services/ingestion/internal/producer"
)

// Connector identity recorded on every envelope (contracts/topics.v0.md).
const (
	ConnectorName    = "headway-samsara"
	ConnectorVersion = "0.1.0"
	ContentType      = "application/json"
	Topic            = "raw.telematics.vehicle_stats"
)

// Vendor API surface, read from the published OpenAPI document (see the
// package comment for version and hash). DefaultBaseURL is the spec's first
// `servers` entry; the spec also lists https://api.eu.samsara.com and
// https://api.ca.samsara.com, which an EU/CA-hosted agency configures.
const (
	DefaultBaseURL   = "https://api.samsara.com"
	StatsHistoryPath = "/fleet/vehicles/stats/history"
)

// RegisteredSources are the telematics source labels this connector may
// carry. They MUST stay identical to the `source_system` enum in
// contracts/fleet-telematics.v0.schema.json — a test asserts that against
// the checked-in contract file, so the two cannot drift silently.
var RegisteredSources = []string{"samsara", "samsara_simulated"}

// MaxStatTypesPerRequest is the vendor's documented cap, quoted from the
// `types` parameter description in the OpenAPI document: "You may list ***up
// to 3*** types using comma-separated format." It is why distance and
// engine-time types cannot share one request.
const MaxStatTypesPerRequest = 3

// DistanceStatTypes are the three distance series named in handoff 0028 —
// exactly at the vendor's documented three-type limit. Each maps to a
// DISTINCT measurement basis downstream and is never substituted for
// another (contracts/fleet-telematics.v0.md).
var DistanceStatTypes = []string{
	"obdOdometerMeters", // spec: meters travelled per on-board diagnostics
	"gpsOdometerMeters", // spec: GPS-maintained odometer, human-seeded
	"gpsDistanceMeters", // spec: metres since the GATEWAY was installed
}

// EngineTimeStatTypes are the two engine-runtime series the spec pins.
// These are engine RUNTIME, not duty hours and not revenue hours.
// syntheticEngineSeconds is explicitly an estimate in the vendor's own
// words and lands under a separate, estimate-labelled basis.
var EngineTimeStatTypes = []string{
	"obdEngineSeconds",
	"syntheticEngineSeconds",
}

// VehicleIdentityKeysKept are the ONLY non-stat keys of a vehicle entry that
// survive the connector's minimization allow-list. `externalIds` is
// deliberately absent: Headway does not use it, and the vendor's own spec
// example for it is a `payrollId` — an employee-linking identifier that must
// never be landed (handoff 0028 governance addition).
var VehicleIdentityKeysKept = []string{"id", "name"}

// StatSampleKeysKept are the ONLY keys of an individual stat sample that
// survive. `decorations` is dropped: Headway never requests decorations, and
// they can carry GPS positions and other unrequested telemetry.
var StatSampleKeysKept = []string{"time", "value"}

// TopLevelKeysKept are the ONLY top-level response keys that survive.
var TopLevelKeysKept = []string{"data", "pagination"}

// Operational defaults. These are HEADWAY choices, not vendor limits — the
// published spec pins no maximum query window and no polling cadence, so
// none is invented here (see README.md, "Left unimplemented").
const (
	// DefaultLagDays: the most recent service day polled is today minus
	// this many days in the declared zone. A service day is not complete
	// until it ends, and gateways upload late; 1 = "yesterday".
	DefaultLagDays = 1
	// DefaultBackfillDays: how many consecutive service days each cycle
	// re-polls, so late-arriving samples are picked up. Re-polls are
	// idempotent by content address, so this costs requests, never rows.
	DefaultBackfillDays = 3
	// DefaultMaxAttempts caps retries per page (429 + 5xx together).
	DefaultMaxAttempts = 5
	// DefaultMaxRetryWait caps how long one Retry-After / backoff sleep may
	// be, so a hostile or mistaken header cannot stall the connector.
	DefaultMaxRetryWait = 60 * time.Second
	// DefaultBackoffBase is the first 5xx backoff step; it doubles per
	// attempt (the vendor's response-codes guide asks for exponential
	// backoff on 5xx).
	DefaultBackoffBase = time.Second
	// DefaultMaxPageBytes caps one response page read into memory. Oversize
	// is a loud refusal, never a truncated record.
	DefaultMaxPageBytes = 64 << 20 // 64 MiB
	// DefaultMaxPagesPerWindow bounds one window's pagination so a
	// misbehaving cursor cannot loop forever; hitting it is an error, not a
	// silent stop.
	DefaultMaxPagesPerWindow = 2000
	// DefaultInterval is Run's cycle cadence when none is configured.
	DefaultInterval = 6 * time.Hour
	// maxSeenRecords bounds the in-process duplicate-page memory.
	maxSeenRecords = 10000
)

// ObjectKey returns the content-addressed object-store key for one API
// response page.
func ObjectKey(recordID string) string {
	return fmt.Sprintf("raw/telematics/%s.json", recordID)
}

// statsPage is the DOCUMENTED response shape (VehicleStatsListResponse in
// the OpenAPI document): `data` and `pagination` are both required, and
// pagination carries the required `endCursor` and `hasNextPage`. It is used
// ONLY to classify parse_status and to follow the cursor — the raw bytes
// are what is landed and produced, never this reparsed form.
type statsPage struct {
	Data       []json.RawMessage `json:"data"`
	Pagination *struct {
		EndCursor   *string `json:"endCursor"`
		HasNextPage *bool   `json:"hasNextPage"`
	} `json:"pagination"`
}

// minimizePage applies the data-minimization allow-list to one response page
// BEFORE anything is hashed, landed or produced (handoff 0028 governance
// addition: fleet telematics is employee-monitoring data; collect the
// minimum that serves vehicle-level distance and time, and never land
// driver-identified data "just in case").
//
// Kept: top level `data` and `pagination`; per vehicle `id`, `name` and the
// stat series in `types`; per sample `time` and `value`. EVERYTHING else is
// dropped — including `externalIds`, `nfcCardScans`, `decorations`, and any
// driver-identified field a future API version adds, because the allow-list
// is positive, not a blocklist to keep up to date.
//
// Returns the minimized bytes, the sorted NAMES of the dropped keys (values
// are never returned or logged), and ok=false when the page's structure does
// not permit minimization (the caller then treats the page as malformed).
//
// Determinism: numbers are preserved as their original literals
// (json.Number) and Go marshals map keys in sorted order, so the same
// response always yields byte-identical minimized output — re-polls stay
// idempotent by content address.
func minimizePage(body []byte, types []string) ([]byte, []string, bool) {
	decoder := json.NewDecoder(bytes.NewReader(body))
	decoder.UseNumber()
	var document map[string]any
	if err := decoder.Decode(&document); err != nil {
		return nil, nil, false
	}
	rawData, ok := document["data"].([]any)
	if !ok {
		return nil, nil, false
	}

	allowedVehicleKeys := make(map[string]bool, len(types)+len(VehicleIdentityKeysKept))
	for _, k := range VehicleIdentityKeysKept {
		allowedVehicleKeys[k] = true
	}
	for _, k := range types {
		allowedVehicleKeys[k] = true
	}
	allowedSampleKeys := make(map[string]bool, len(StatSampleKeysKept))
	for _, k := range StatSampleKeysKept {
		allowedSampleKeys[k] = true
	}
	allowedTopKeys := make(map[string]bool, len(TopLevelKeysKept))
	for _, k := range TopLevelKeysKept {
		allowedTopKeys[k] = true
	}

	dropped := map[string]bool{}

	minimized := make(map[string]any, len(TopLevelKeysKept))
	for key, value := range document {
		if !allowedTopKeys[key] {
			dropped[key] = true
			continue
		}
		minimized[key] = value
	}

	vehicles := make([]any, 0, len(rawData))
	for _, entry := range rawData {
		vehicle, ok := entry.(map[string]any)
		if !ok {
			// Not an object: keep it verbatim so the transform can report it
			// loudly. It carries no vendor-defined driver fields to strip.
			vehicles = append(vehicles, entry)
			continue
		}
		kept := make(map[string]any, len(allowedVehicleKeys))
		for key, value := range vehicle {
			if !allowedVehicleKeys[key] {
				dropped["data[]."+key] = true
				continue
			}
			series, isSeries := value.([]any)
			if !isSeries {
				kept[key] = value
				continue
			}
			samples := make([]any, 0, len(series))
			for _, raw := range series {
				sample, ok := raw.(map[string]any)
				if !ok {
					samples = append(samples, raw)
					continue
				}
				keptSample := make(map[string]any, len(StatSampleKeysKept))
				for sampleKey, sampleValue := range sample {
					if !allowedSampleKeys[sampleKey] {
						dropped["data[]."+key+"[]."+sampleKey] = true
						continue
					}
					keptSample[sampleKey] = sampleValue
				}
				samples = append(samples, keptSample)
			}
			kept[key] = samples
		}
		vehicles = append(vehicles, kept)
	}
	minimized["data"] = vehicles

	out, err := json.Marshal(minimized)
	if err != nil {
		return nil, nil, false
	}
	names := make([]string, 0, len(dropped))
	for name := range dropped {
		names = append(names, name)
	}
	sort.Strings(names)
	return out, names, true
}

// Poller pulls Samsara vehicle stat history and produces raw-record
// envelopes. Zero interpretation of the payload happens here.
type Poller struct {
	// BaseURL is the vendor API root; empty means DefaultBaseURL.
	BaseURL string
	// Token is the bearer API token. REQUIRED. It is written only into the
	// Authorization header and never appears in a log, error or record.
	Token string
	// Source is the envelope source label. REQUIRED, no default, must be
	// one of RegisteredSources (fail closed).
	Source string
	// ServiceDay is the agency's DECLARED service-day timezone. REQUIRED,
	// no default — a service date derived from a guessed zone would be a
	// fabricated fact.
	ServiceDay *time.Location

	// Optional vendor-side filters, passed through verbatim.
	VehicleIDs   []string
	TagIDs       []string
	ParentTagIDs []string

	// IncludeEngineTime adds the second request per window for the
	// engine-runtime series. Engine runtime is NOT duty hours.
	IncludeEngineTime bool

	LagDays           int
	BackfillDays      int
	MaxAttempts       int
	MaxRetryWait      time.Duration
	BackoffBase       time.Duration
	MaxPageBytes      int64
	MaxPagesPerWindow int
	Interval          time.Duration
	AgencyID          string

	HTTP     *http.Client
	Store    ObjectStore
	Producer producer.Producer
	Log      *slog.Logger

	// Clock and Sleep are injectable for tests; they default to time.Now
	// and a context-aware sleep.
	Clock func() time.Time
	Sleep func(ctx context.Context, d time.Duration) error

	// seen holds record_ids already produced by THIS process, so a
	// re-polled window that returns byte-identical pages does not
	// re-produce them. Restarting re-produces once, which is harmless:
	// content-addressed ids make re-ingest idempotent downstream.
	seen map[string]bool
}

func (p *Poller) clock() time.Time {
	if p.Clock != nil {
		return p.Clock()
	}
	return time.Now()
}

func (p *Poller) sleep(ctx context.Context, d time.Duration) error {
	if p.Sleep != nil {
		return p.Sleep(ctx, d)
	}
	if d <= 0 {
		return ctx.Err()
	}
	timer := time.NewTimer(d)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}

func (p *Poller) httpClient() *http.Client {
	if p.HTTP != nil {
		return p.HTTP
	}
	return http.DefaultClient
}

func (p *Poller) baseURL() string {
	if strings.TrimSpace(p.BaseURL) != "" {
		return strings.TrimRight(p.BaseURL, "/")
	}
	return DefaultBaseURL
}

func (p *Poller) lagDays() int {
	if p.LagDays > 0 {
		return p.LagDays
	}
	return DefaultLagDays
}

func (p *Poller) backfillDays() int {
	if p.BackfillDays > 0 {
		return p.BackfillDays
	}
	return DefaultBackfillDays
}

func (p *Poller) maxAttempts() int {
	if p.MaxAttempts > 0 {
		return p.MaxAttempts
	}
	return DefaultMaxAttempts
}

func (p *Poller) maxRetryWait() time.Duration {
	if p.MaxRetryWait > 0 {
		return p.MaxRetryWait
	}
	return DefaultMaxRetryWait
}

func (p *Poller) backoffBase() time.Duration {
	if p.BackoffBase > 0 {
		return p.BackoffBase
	}
	return DefaultBackoffBase
}

func (p *Poller) maxPageBytes() int64 {
	if p.MaxPageBytes > 0 {
		return p.MaxPageBytes
	}
	return DefaultMaxPageBytes
}

func (p *Poller) maxPagesPerWindow() int {
	if p.MaxPagesPerWindow > 0 {
		return p.MaxPagesPerWindow
	}
	return DefaultMaxPagesPerWindow
}

// SourceRegistered reports whether label is one of the registered telematics
// source labels (contracts/fleet-telematics.v0.schema.json).
func SourceRegistered(label string) bool {
	for _, s := range RegisteredSources {
		if s == label {
			return true
		}
	}
	return false
}

// Check validates configuration and refuses to run without the things
// Headway must never guess. Every message is written for the person setting
// the connector up, not for a stack trace.
func (p *Poller) Check() error {
	var problems []string

	if strings.TrimSpace(p.Token) == "" {
		problems = append(problems,
			"SAMSARA_API_TOKEN is not set. Headway refuses to start the "+
				"Samsara connector without an API token rather than poll "+
				"anonymously and record nothing. Create a READ-ONLY token in "+
				"the Samsara dashboard (Settings -> API Tokens) with the "+
				"'Read Vehicle Statistics' scope under the Vehicles category "+
				"— that is the only scope Headway needs — and put it in the "+
				"secret store. The token is never logged and never stored in "+
				"a record")
	}
	if strings.TrimSpace(p.Source) == "" {
		problems = append(problems,
			"SAMSARA_SOURCE is not set. Headway needs to know whether this "+
				"feed carries a REAL agency account or synthetic data and "+
				"refuses to guess: set SAMSARA_SOURCE=samsara for a real "+
				"account, or SAMSARA_SOURCE=samsara_simulated for anything "+
				"synthetic — simulated data must never be recorded as real "+
				"(Shared Constraint 2: full provenance)")
	} else if !SourceRegistered(p.Source) {
		problems = append(problems, fmt.Sprintf(
			"SAMSARA_SOURCE=%q is not a REGISTERED telematics source label. "+
				"Registered labels are %s (contracts/"+
				"fleet-telematics.v0.schema.json, source_system). The "+
				"transform runtime refuses unregistered labels fail-closed, "+
				"so this would land raw records that never become canonical "+
				"rows. Registering a new label is a contracts change",
			p.Source, strings.Join(RegisteredSources, ", ")))
	}
	if p.ServiceDay == nil {
		problems = append(problems,
			"SAMSARA_SERVICE_DAY_TZ is not set. A service DATE is a local "+
				"wall date, so it cannot be derived without the agency's "+
				"timezone, and Headway never guesses one: set "+
				"SAMSARA_SERVICE_DAY_TZ to an IANA zone name (e.g. "+
				"America/New_York). The transform must be given the SAME "+
				"zone (HEADWAY_TELEMATICS_SERVICE_DAY_TZ)")
	}
	if p.Store == nil {
		problems = append(problems, "no object store configured (S3_ENDPOINT and credentials are required): raw telematics pages must be landed before they are produced")
	}
	if p.Producer == nil {
		problems = append(problems, "no Kafka producer configured")
	}
	if p.Log == nil {
		problems = append(problems, "no logger configured")
	}
	if len(problems) > 0 {
		return fmt.Errorf("samsara: refusing to start:\n  - %s",
			strings.Join(problems, "\n  - "))
	}
	return nil
}

// statTypeSets returns the request groups for one window. Distance always;
// engine time only when enabled. They are separate requests because the
// vendor's published `types` parameter allows at most
// MaxStatTypesPerRequest types per call.
func (p *Poller) statTypeSets() [][]string {
	sets := [][]string{DistanceStatTypes}
	if p.IncludeEngineTime {
		sets = append(sets, EngineTimeStatTypes)
	}
	return sets
}

// ServiceDayWindow returns the [start, end) instants of the service day that
// `day` falls on, in the declared zone. Day length is whatever the zone says
// (23 or 25 hours across a DST transition) — never assumed to be 24 hours.
func (p *Poller) ServiceDayWindow(day time.Time) (time.Time, time.Time) {
	local := day.In(p.ServiceDay)
	start := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, p.ServiceDay)
	end := start.AddDate(0, 0, 1)
	return start, end
}

// PollWindow fetches every page of every stat-type set for one service day
// and produces one raw record per page. It returns the number of records
// produced and the joined errors of any set that failed; a failure in one
// set never suppresses the others.
func (p *Poller) PollWindow(ctx context.Context, day time.Time) (int, error) {
	if err := p.Check(); err != nil {
		return 0, err
	}
	start, end := p.ServiceDayWindow(day)
	produced := 0
	var errs []error
	for _, types := range p.statTypeSets() {
		if len(types) > MaxStatTypesPerRequest {
			// Structural guard against a future edit exceeding the vendor's
			// documented three-type limit.
			errs = append(errs, fmt.Errorf(
				"samsara: stat type set %v has %d types, over the vendor's "+
					"documented limit of %d per request",
				types, len(types), MaxStatTypesPerRequest))
			continue
		}
		n, err := p.pollSet(ctx, start, end, types)
		produced += n
		if err != nil {
			errs = append(errs, err)
		}
	}
	return produced, errors.Join(errs...)
}

// pollSet paginates one (window, stat-type set) and lands+produces each page.
func (p *Poller) pollSet(ctx context.Context, start, end time.Time, types []string) (int, error) {
	cursor := ""
	produced := 0
	for page := 1; ; page++ {
		if page > p.maxPagesPerWindow() {
			return produced, fmt.Errorf(
				"samsara: window %s..%s types=%s exceeded %d pages; stopping "+
					"loudly rather than paginating forever",
				start.Format(time.RFC3339), end.Format(time.RFC3339),
				strings.Join(types, ","), p.maxPagesPerWindow())
		}
		requestURL := p.buildURL(start, end, types, cursor)
		body, err := p.fetch(ctx, requestURL)
		if err != nil {
			return produced, err
		}

		// Parse ONLY to classify parse_status and read the cursor. The
		// bytes are the record.
		parseStatus, parseError := envelope.ParseOK, ""
		var parsed statsPage
		if err := json.Unmarshal(body, &parsed); err != nil {
			parseStatus, parseError = envelope.ParseMalformed,
				fmt.Sprintf("response is not JSON matching the documented "+
					"VehicleStatsListResponse shape: %v", err)
		} else if parsed.Data == nil || parsed.Pagination == nil ||
			parsed.Pagination.EndCursor == nil || parsed.Pagination.HasNextPage == nil {
			parseStatus, parseError = envelope.ParseMalformed,
				"response is missing required fields of the documented "+
					"VehicleStatsListResponse shape (data, pagination.endCursor, "+
					"pagination.hasNextPage are all required by the vendor's "+
					"OpenAPI document)"
		}

		// DATA MINIMIZATION, before the first write. A well-formed page is
		// reduced to the allow-list; the MINIMIZED bytes are what is hashed,
		// landed and produced, so an unrequested driver-identified field can
		// never reach the raw store. A page whose structure does not permit
		// minimization is landed as received with parse_status "malformed" —
		// evidence of a failure is never destroyed, and it cannot carry
		// vendor-defined driver records anyway, because the token scope
		// Headway asks for ("Read Vehicle Statistics") does not grant them.
		record := body
		if parseStatus == envelope.ParseOK {
			minimized, dropped, ok := minimizePage(body, types)
			if !ok {
				parseStatus, parseError = envelope.ParseMalformed,
					"response could not be reduced to the data-minimization "+
						"allow-list (its structure did not match the documented "+
						"VehicleStatsListResponse shape)"
			} else {
				record = minimized
				if len(dropped) > 0 {
					// Key NAMES only — never values.
					p.Log.Warn("dropped unrequested response fields at the connector boundary before landing (data minimization; fleet telematics is employee-monitoring data)",
						"connector", ConnectorName, "url", requestURL,
						"dropped_keys", strings.Join(dropped, ","))
				}
			}
		}

		recordID, err := p.landAndProduce(ctx, record, requestURL, parseStatus, parseError)
		if err != nil {
			return produced, err
		}
		if recordID != "" {
			produced++
		}

		if parseStatus == envelope.ParseMalformed {
			// The page is landed and produced (never dropped), but the
			// cursor could not be read — continuing would be guessing.
			return produced, fmt.Errorf(
				"samsara: window %s..%s types=%s page %d did not match the "+
					"documented response shape; the page was LANDED and "+
					"produced with parse_status=malformed (nothing dropped) "+
					"and pagination stopped here: %s",
				start.Format(time.RFC3339), end.Format(time.RFC3339),
				strings.Join(types, ","), page, parseError)
		}
		if !*parsed.Pagination.HasNextPage {
			return produced, nil
		}
		next := *parsed.Pagination.EndCursor
		if next == "" || next == cursor {
			return produced, fmt.Errorf(
				"samsara: window %s..%s types=%s page %d reports "+
					"hasNextPage=true but gave no new endCursor; stopping "+
					"loudly rather than looping",
				start.Format(time.RFC3339), end.Format(time.RFC3339),
				strings.Join(types, ","), page)
		}
		cursor = next
	}
}

// buildURL renders one request URL. The bearer token is NOT here — the
// vendor's documented authentication is an Authorization header, so the URL
// is safe to log and safe to record as the envelope's feed_url.
func (p *Poller) buildURL(start, end time.Time, types []string, cursor string) string {
	q := url.Values{}
	// RFC 3339 with an offset, per the spec's startTime/endTime description.
	q.Set("startTime", start.Format(time.RFC3339))
	q.Set("endTime", end.Format(time.RFC3339))
	q.Set("types", strings.Join(types, ","))
	if len(p.VehicleIDs) > 0 {
		q.Set("vehicleIds", strings.Join(p.VehicleIDs, ","))
	}
	if len(p.TagIDs) > 0 {
		q.Set("tagIds", strings.Join(p.TagIDs, ","))
	}
	if len(p.ParentTagIDs) > 0 {
		q.Set("parentTagIds", strings.Join(p.ParentTagIDs, ","))
	}
	if cursor != "" {
		q.Set("after", cursor)
	}
	return p.baseURL() + StatsHistoryPath + "?" + q.Encode()
}

// fetch performs one GET with the documented retry behaviour: 429 honours
// the Retry-After header (the vendor documents fractional seconds, e.g.
// "0.40235"); 5xx uses exponential backoff (the vendor's response-codes
// guide asks for exactly that); other 4xx are NOT retried because retrying a
// client error just burns rate limit.
//
// No error returned from here ever contains the token.
func (p *Poller) fetch(ctx context.Context, requestURL string) ([]byte, error) {
	var lastErr error
	for attempt := 1; attempt <= p.maxAttempts(); attempt++ {
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, requestURL, nil)
		if err != nil {
			return nil, fmt.Errorf("samsara: build request: %w", err)
		}
		// Bearer authentication per the spec's global security scheme
		// (AccessTokenHeader: type http, scheme bearer). Header only.
		req.Header.Set("Authorization", "Bearer "+p.Token)
		req.Header.Set("Accept", ContentType)

		resp, err := p.httpClient().Do(req)
		if err != nil {
			// net/http errors embed the URL, never headers, so the token
			// cannot leak here.
			lastErr = fmt.Errorf("samsara: GET %s: %w", requestURL, err)
			if wait, ok := p.backoffFor(attempt); ok {
				p.Log.Warn("samsara request failed; backing off",
					"connector", ConnectorName, "url", requestURL,
					"attempt", attempt, "wait", wait.String(), "error", err)
				if serr := p.sleep(ctx, wait); serr != nil {
					return nil, serr
				}
				continue
			}
			return nil, lastErr
		}

		body, readErr := readCapped(resp.Body, p.maxPageBytes())
		status := resp.StatusCode
		retryAfter := resp.Header.Get("Retry-After")
		resp.Body.Close()
		if readErr != nil {
			return nil, fmt.Errorf("samsara: GET %s: %w", requestURL, readErr)
		}

		switch {
		case status == http.StatusOK:
			if len(body) == 0 {
				return nil, fmt.Errorf(
					"samsara: GET %s: HTTP 200 with an empty body; there are "+
						"no bytes to land, so nothing is recorded rather "+
						"than fabricating an empty record", requestURL)
			}
			return body, nil

		case status == http.StatusTooManyRequests:
			wait := parseRetryAfter(retryAfter, p.backoffBase())
			if wait > p.maxRetryWait() {
				wait = p.maxRetryWait()
			}
			lastErr = fmt.Errorf(
				"samsara: GET %s: HTTP 429 (rate limited) after %d attempt(s)",
				requestURL, attempt)
			if attempt == p.maxAttempts() {
				return nil, lastErr
			}
			p.Log.Warn("samsara rate limited; honouring Retry-After",
				"connector", ConnectorName, "url", requestURL,
				"attempt", attempt, "retry_after_header", retryAfter,
				"wait", wait.String())
			if serr := p.sleep(ctx, wait); serr != nil {
				return nil, serr
			}

		case status >= 500:
			lastErr = fmt.Errorf(
				"samsara: GET %s: HTTP %d (server error) after %d attempt(s)",
				requestURL, status, attempt)
			if attempt == p.maxAttempts() {
				return nil, lastErr
			}
			wait, _ := p.backoffFor(attempt)
			p.Log.Warn("samsara server error; exponential backoff",
				"connector", ConnectorName, "url", requestURL,
				"attempt", attempt, "status", status, "wait", wait.String())
			if serr := p.sleep(ctx, wait); serr != nil {
				return nil, serr
			}

		case status == http.StatusUnauthorized || status == http.StatusForbidden:
			// Deliberately says nothing about the token's value.
			return nil, fmt.Errorf(
				"samsara: GET %s: HTTP %d — the API token was rejected. "+
					"Check that the token is current and that it carries the "+
					"'Read Vehicle Statistics' scope (Vehicles category); if "+
					"the token is tag-scoped, check the vanpool vehicles "+
					"carry that tag. The token value is never logged",
				requestURL, status)

		default:
			return nil, fmt.Errorf(
				"samsara: GET %s: HTTP %d (client error; not retried)",
				requestURL, status)
		}
	}
	if lastErr == nil {
		lastErr = fmt.Errorf("samsara: GET %s: exhausted attempts", requestURL)
	}
	return nil, lastErr
}

// backoffFor returns the exponential backoff for an attempt, and whether a
// retry remains.
func (p *Poller) backoffFor(attempt int) (time.Duration, bool) {
	if attempt >= p.maxAttempts() {
		return 0, false
	}
	wait := p.backoffBase() << (attempt - 1)
	if wait > p.maxRetryWait() {
		wait = p.maxRetryWait()
	}
	return wait, true
}

// parseRetryAfter reads the vendor's documented Retry-After header, which
// the rate-limit guide documents in SECONDS and shows as a fractional value
// ("0.40235"). An unreadable or absent header falls back to the caller's
// default rather than guessing zero.
func parseRetryAfter(header string, fallback time.Duration) time.Duration {
	header = strings.TrimSpace(header)
	if header == "" {
		return fallback
	}
	seconds, err := strconv.ParseFloat(header, 64)
	if err != nil || seconds < 0 {
		return fallback
	}
	return time.Duration(seconds * float64(time.Second))
}

// readCapped reads at most max bytes and refuses loudly beyond it, so a
// hostile or mistaken response can never be buffered without bound and can
// never land truncated.
func readCapped(r io.Reader, max int64) ([]byte, error) {
	body, err := io.ReadAll(io.LimitReader(r, max+1))
	if err != nil {
		return nil, fmt.Errorf("read response body: %w", err)
	}
	if int64(len(body)) > max {
		return nil, fmt.Errorf(
			"response exceeds the %d-byte page limit "+
				"(SAMSARA_MAX_PAGE_BYTES); refused rather than landing a "+
				"truncated record", max)
	}
	return body, nil
}

// landAndProduce stores the exact page bytes at their content-addressed key
// and then produces the envelope. Landing precedes producing. Returns "" when
// the page was already produced by this process (identical bytes).
func (p *Poller) landAndProduce(
	ctx context.Context, body []byte, requestURL, parseStatus, parseError string,
) (string, error) {
	recordID := envelope.RecordID(body)
	if p.seen == nil {
		p.seen = make(map[string]bool)
	}
	if p.seen[recordID] {
		p.Log.Info("duplicate telematics page skipped (identical bytes)",
			"connector", ConnectorName, "record_id", recordID,
			"topic", Topic, "url", requestURL)
		return "", nil
	}

	key := ObjectKey(recordID)
	if err := p.Store.Put(ctx, key, body); err != nil {
		return "", fmt.Errorf("samsara: land %s: %w", key, err)
	}

	env, err := envelope.NewObjectRef(body, key, envelope.Params{
		Source:           p.Source,
		Connector:        ConnectorName,
		ConnectorVersion: ConnectorVersion,
		AgencyID:         p.AgencyID,
		FeedURL:          requestURL,
		FetchedAt:        p.clock(),
		ContentType:      ContentType,
		ParseStatus:      parseStatus,
		ParseError:       parseError,
	})
	if err != nil {
		return "", fmt.Errorf("samsara: build envelope: %w", err)
	}
	value, err := env.MarshalJSONBytes()
	if err != nil {
		return "", fmt.Errorf("samsara: marshal envelope: %w", err)
	}
	if err := p.Producer.Produce(ctx, Topic, []byte(recordID), value); err != nil {
		return "", fmt.Errorf("samsara: %w", err)
	}

	if len(p.seen) >= maxSeenRecords {
		p.Log.Info("clearing in-process duplicate-page memory (bounded); "+
			"re-produced pages remain idempotent by content address",
			"connector", ConnectorName, "entries", len(p.seen))
		p.seen = make(map[string]bool)
	}
	p.seen[recordID] = true

	if parseStatus == envelope.ParseMalformed {
		// DQ hook: landed and produced, never dropped (Guardrail 7).
		p.Log.Error("telematics page did not match the documented response shape (landed anyway, never dropped)",
			"connector", ConnectorName, "record_id", recordID,
			"object_key", key, "topic", Topic, "url", requestURL,
			"parse_error", parseError)
	} else {
		p.Log.Info("telematics page landed and produced",
			"connector", ConnectorName, "record_id", recordID,
			"object_key", key, "topic", Topic, "source", p.Source,
			"url", requestURL, "bytes", len(body))
	}
	return recordID, nil
}

// PollOnce polls the current backfill span: BackfillDays consecutive service
// days ending LagDays before today in the declared zone.
func (p *Poller) PollOnce(ctx context.Context) error {
	if err := p.Check(); err != nil {
		return err
	}
	now := p.clock().In(p.ServiceDay)
	last := now.AddDate(0, 0, -p.lagDays())
	var errs []error
	total := 0
	for i := p.backfillDays() - 1; i >= 0; i-- {
		day := last.AddDate(0, 0, -i)
		n, err := p.PollWindow(ctx, day)
		total += n
		if err != nil {
			errs = append(errs, err)
		}
	}
	p.Log.Info("samsara poll cycle complete",
		"connector", ConnectorName, "records_produced", total,
		"service_days", p.backfillDays(), "lag_days", p.lagDays(),
		"timezone", p.ServiceDay.String())
	return errors.Join(errs...)
}

// Run polls immediately, then on every Interval tick until ctx is done.
// Poll errors are logged loudly and do not stop the loop; a configuration
// refusal returns immediately.
func (p *Poller) Run(ctx context.Context) error {
	if err := p.Check(); err != nil {
		return err
	}
	interval := p.Interval
	if interval <= 0 {
		interval = DefaultInterval
	}
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		if err := p.PollOnce(ctx); err != nil {
			if ctx.Err() != nil {
				return ctx.Err()
			}
			p.Log.Error("samsara poll cycle had failures (will retry next cycle)",
				"connector", ConnectorName, "error", err)
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-ticker.C:
		}
	}
}
