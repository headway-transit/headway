// Command headway-gtfsrt-backfill rescues GTFS-Realtime raw payloads from
// the broker's retained window into the object store (handoff 0036, design
// point 4) — one shot, idempotent, resumable by re-running.
//
// WHY: until handoff 0036 the GTFS-Realtime connector base64-encoded each
// frame into the ingest envelope and produced it; the broker was the ONLY
// place those bytes existed, and broker retention (a deployment knob) was
// silently acting as the records policy for every realtime lineage leaf.
// The connector now lands frames durably before producing; this tool
// rescues what the broker still holds from BEFORE that change, before it
// ages out.
//
// WHAT IT DOES: scans every raw.gtfs_rt.* topic from the earliest retained
// offset to the end offset captured at startup. For each base64 envelope it
// RE-HASHES the payload bytes (the message key is never trusted as proof of
// identity — 0035's rule) and, when the hash matches a raw.records row with
// payload_ref NULL, writes the bytes to the deterministic content-addressed
// key raw/gtfs_rt/<record_id>.pb (gtfsrt.ObjectKey). Content addressing
// makes re-runs harmless: an object already present is verified present and
// skipped, never rewritten.
//
// WHAT IT NEVER DOES: touch raw.records. The index is immutable by trigger
// (migration 0002) and legacy rows keep payload_encoding='base64' forever;
// the API's payload reader resolves them by checking the object store at
// the same deterministic key first (handoff 0036, design point 5).
//
// Env (read-only against the database; write-only against the raw bucket):
//
//	KAFKA_BROKERS                comma-separated broker list (required)
//	HEADWAY_DATABASE_URL         libpq conninfo or URL for the Headway DB
//	                             (required; read-only queries only; carries
//	                             credentials — NEVER logged)
//	S3_ENDPOINT                  MinIO/S3 endpoint host:port (required)
//	S3_ACCESS_KEY, S3_SECRET_KEY credentials (from the secret store; never logged)
//	S3_BUCKET                    target bucket, default headway-raw
//	S3_USE_SSL                   "true" to use TLS, default false (on-prem MinIO)
//	BACKFILL_DRY_RUN             "true": scan, hash and match but write nothing
//
// Exit status is non-zero if any frame that SHOULD have been written could
// not be (fail loudly; a partial rescue is reported, never silently
// declared done). Counts are printed per topic and in total:
// matched/written/already-present/row-has-ref/unmatched/key-mismatch.
package main

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"
	"github.com/twmb/franz-go/pkg/kadm"
	"github.com/twmb/franz-go/pkg/kgo"

	"github.com/headway-transit/headway/services/ingestion/connectors/gtfsrt"
)

// Topics carrying GTFS-Realtime envelopes (contracts/topics.v0.md).
var topics = []string{
	"raw.gtfs_rt.vehicle_positions",
	"raw.gtfs_rt.trip_updates",
	"raw.gtfs_rt.alerts",
}

// Idle-poll safety valve: completion is defined as progress reaching every
// partition's recorded end offset, which assumes a gapless log. If a partition
// ends in a gap (compaction, aborted transactions, or a retention race that
// deletes frames before we read them), the consumer silently skips those
// offsets and progress never reaches the end — without this bound the tool
// would block in PollFetches forever. After maxIdlePolls consecutive polls of
// idlePollTimeout that deliver nothing, we stop and report the shortfall
// honestly rather than hang: records that do not exist cannot be rescued.
const (
	idlePollTimeout = 10 * time.Second
	maxIdlePolls    = 3
)

// envelopeLite is the slice of the raw-record envelope v0 this tool needs.
type envelopeLite struct {
	RecordID        string `json:"record_id"`
	PayloadEncoding string `json:"payload_encoding"`
	Payload         string `json:"payload"`
}

// counts per topic; every frame scanned lands in exactly one outcome bucket
// (plus matched, which written/already-present subdivide).
type counts struct {
	Scanned       int // envelopes read from the topic
	Matched       int // hash matches a raw.records row with payload_ref NULL
	Written       int // matched and newly written to the object store
	AlreadyThere  int // matched and the object already existed (idempotent re-run)
	RowHasRef     int // hash matches a row that already records a payload_ref
	Unmatched     int // hash matches no raw.records row at all
	KeyMismatch   int // message key differs from the re-computed hash (loud)
	NotBase64     int // object_ref envelopes (already durably stored)
	Unparseable   int // message value not a valid envelope JSON (loud)
	WriteFailures int // matched but the store refused the write (fatal at exit)
	Bytes         int64
	MinBytes      int64
	MaxBytes      int64
}

func (c *counts) observe(n int64) {
	c.Bytes += n
	if c.MinBytes == 0 || n < c.MinBytes {
		c.MinBytes = n
	}
	if n > c.MaxBytes {
		c.MaxBytes = n
	}
}

func main() {
	log := slog.New(slog.NewTextHandler(os.Stderr, nil))
	if err := run(log); err != nil {
		log.Error("fatal", "error", err)
		os.Exit(1)
	}
}

func run(log *slog.Logger) error {
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	brokersEnv := os.Getenv("KAFKA_BROKERS")
	if brokersEnv == "" {
		return fmt.Errorf("KAFKA_BROKERS is required")
	}
	dbURL := os.Getenv("HEADWAY_DATABASE_URL")
	if dbURL == "" {
		return fmt.Errorf("HEADWAY_DATABASE_URL is required (read-only; it is never logged)")
	}
	dryRun := strings.EqualFold(os.Getenv("BACKFILL_DRY_RUN"), "true")

	store, bucket, err := storeFromEnv()
	if err != nil {
		return err
	}

	// The record ids this rescue is FOR: gtfs_rt rows whose bytes have no
	// durable address. Read once up front — raw.records rows are immutable,
	// and rows landed after the durable-landing connector deploys carry
	// payload_ref and are excluded by the query itself.
	needRescue, haveRef, err := loadIndex(ctx, dbURL)
	if err != nil {
		return err
	}
	log.Info("raw.records index loaded",
		"rows_needing_rescue", len(needRescue), "rows_with_payload_ref", len(haveRef))

	client, err := kgo.NewClient(
		kgo.SeedBrokers(strings.Split(brokersEnv, ",")...),
		kgo.ConsumeTopics(topics...),
		kgo.ConsumeResetOffset(kgo.NewOffset().AtStart()),
	)
	if err != nil {
		return fmt.Errorf("kafka client: %w", err)
	}
	defer client.Close()

	// Capture start/end offsets now: the scan is one bounded pass over what
	// the broker holds at start, not a tail — the live connector handles
	// new frames from here on.
	adm := kadm.NewClient(client)
	startOffsets, err := adm.ListStartOffsets(ctx, topics...)
	if err != nil {
		return fmt.Errorf("list start offsets: %w", err)
	}
	endOffsets, err := adm.ListEndOffsets(ctx, topics...)
	if err != nil {
		return fmt.Errorf("list end offsets: %w", err)
	}
	ends := map[string]map[int32]int64{}
	endOffsets.Each(func(o kadm.ListedOffset) {
		if ends[o.Topic] == nil {
			ends[o.Topic] = map[int32]int64{}
		}
		ends[o.Topic][o.Partition] = o.Offset
	})
	startOffsets.Each(func(o kadm.ListedOffset) {
		log.Info("topic bounds", "topic", o.Topic, "partition", o.Partition,
			"earliest_retained_offset", o.Offset, "end_offset", ends[o.Topic][o.Partition])
	})

	perTopic := map[string]*counts{}
	for _, t := range topics {
		perTopic[t] = &counts{}
	}
	written := map[string]bool{} // object keys confirmed present this run

	// Track progress against end offsets per partition. A partition whose
	// earliest retained offset already equals its end is empty and done.
	progress := map[string]map[int32]int64{}
	startOffsets.Each(func(o kadm.ListedOffset) {
		if progress[o.Topic] == nil {
			progress[o.Topic] = map[int32]int64{}
		}
		progress[o.Topic][o.Partition] = o.Offset
	})
	finished := func() bool {
		for t, parts := range ends {
			for p, end := range parts {
				if progress[t] == nil || progress[t][p] < end {
					return false
				}
			}
		}
		return true
	}

	start := time.Now()
	idle := 0
	for !finished() {
		// Bound each poll (see idlePollTimeout) so a partition that never
		// delivers its recorded end offset cannot wedge the tool forever.
		pollCtx, cancel := context.WithTimeout(ctx, idlePollTimeout)
		fetches := client.PollFetches(pollCtx)
		cancel()
		if err := ctx.Err(); err != nil {
			return err
		}
		if errs := fetches.Errors(); len(errs) > 0 {
			realErr := false
			for _, fe := range errs {
				if errors.Is(fe.Err, context.DeadlineExceeded) {
					continue // our own idle-poll timeout, not a broker failure
				}
				realErr = true
				log.Error("fetch error", "topic", fe.Topic, "partition", fe.Partition, "error", fe.Err)
			}
			if realErr {
				return fmt.Errorf("broker fetch failed; re-run to resume (idempotent)")
			}
		}
		if fetches.NumRecords() == 0 {
			idle++
			if idle >= maxIdlePolls {
				for t, parts := range ends {
					for p, end := range parts {
						cur := int64(0)
						if progress[t] != nil {
							cur = progress[t][p]
						}
						if cur < end {
							log.Warn("stopped on idle before the recorded end offset; those offsets were never delivered (log gap: compaction, aborted transaction, or retention race) — records that do not exist cannot be rescued; re-run to resume if the broker recovers",
								"topic", t, "partition", p, "progress", cur, "end_offset", end)
						}
					}
				}
				break
			}
			continue
		}
		idle = 0
		fetches.EachRecord(func(r *kgo.Record) {
			c := perTopic[r.Topic]
			if c == nil {
				return
			}
			if progress[r.Topic] == nil {
				progress[r.Topic] = map[int32]int64{}
			}
			if r.Offset+1 > progress[r.Topic][r.Partition] {
				progress[r.Topic][r.Partition] = r.Offset + 1
			}
			c.Scanned++
			var env envelopeLite
			if err := json.Unmarshal(r.Value, &env); err != nil {
				c.Unparseable++
				log.Error("message is not an envelope; skipped (recorded, not hidden)",
					"topic", r.Topic, "offset", r.Offset, "error", err)
				return
			}
			if env.PayloadEncoding != "base64" {
				c.NotBase64++
				return
			}
			payload, err := base64.StdEncoding.DecodeString(env.Payload)
			if err != nil {
				c.Unparseable++
				log.Error("envelope payload is not valid base64; skipped",
					"topic", r.Topic, "offset", r.Offset, "error", err)
				return
			}
			// Re-hash before writing — the message key and the envelope's
			// own record_id are labels, not proof (0035's rule).
			sum := sha256.Sum256(payload)
			id := hex.EncodeToString(sum[:])
			if string(r.Key) != id {
				c.KeyMismatch++
				log.Error("message key does not match re-computed hash; frame NOT written under either id",
					"topic", r.Topic, "offset", r.Offset, "key", string(r.Key), "hash", id)
				return
			}
			c.observe(int64(len(payload)))
			if haveRefContains(haveRef, id) {
				c.RowHasRef++
				return
			}
			if !needRescue[id] {
				c.Unmatched++
				return
			}
			c.Matched++
			key := gtfsrt.ObjectKey(id)
			if written[key] {
				c.AlreadyThere++
				return
			}
			present, err := objectPresent(ctx, store, bucket, key)
			if err != nil {
				c.WriteFailures++
				log.Error("object store stat failed", "key", key, "error", err)
				return
			}
			if present {
				c.AlreadyThere++
				written[key] = true
				return
			}
			if dryRun {
				c.Written++ // "would write"
				written[key] = true
				return
			}
			if _, err := store.PutObject(ctx, bucket, key,
				strings.NewReader(string(payload)), int64(len(payload)),
				minio.PutObjectOptions{ContentType: "application/x-protobuf"}); err != nil {
				c.WriteFailures++
				log.Error("object store write failed (frame NOT rescued; re-run after fixing the store)",
					"key", key, "error", err)
				return
			}
			c.Written++
			written[key] = true
		})
	}

	// Report. Every number below was counted, not assumed.
	total := counts{}
	failures := 0
	for _, t := range topics {
		c := perTopic[t]
		fmt.Printf("%s: scanned=%d matched=%d written=%d already_present=%d row_has_ref=%d unmatched=%d key_mismatch=%d not_base64=%d unparseable=%d write_failures=%d bytes=%d min_frame=%d max_frame=%d\n",
			t, c.Scanned, c.Matched, c.Written, c.AlreadyThere, c.RowHasRef,
			c.Unmatched, c.KeyMismatch, c.NotBase64, c.Unparseable,
			c.WriteFailures, c.Bytes, c.MinBytes, c.MaxBytes)
		total.Scanned += c.Scanned
		total.Matched += c.Matched
		total.Written += c.Written
		total.AlreadyThere += c.AlreadyThere
		total.RowHasRef += c.RowHasRef
		total.Unmatched += c.Unmatched
		total.KeyMismatch += c.KeyMismatch
		total.NotBase64 += c.NotBase64
		total.Unparseable += c.Unparseable
		total.WriteFailures += c.WriteFailures
		total.Bytes += c.Bytes
		failures += c.WriteFailures
	}
	mode := "LIVE"
	if dryRun {
		mode = "DRY-RUN (nothing written)"
	}
	fmt.Printf("TOTAL [%s, %s]: scanned=%d matched=%d written=%d already_present=%d row_has_ref=%d unmatched=%d key_mismatch=%d not_base64=%d unparseable=%d write_failures=%d bytes=%d\n",
		mode, time.Since(start).Round(time.Millisecond),
		total.Scanned, total.Matched, total.Written, total.AlreadyThere,
		total.RowHasRef, total.Unmatched, total.KeyMismatch, total.NotBase64,
		total.Unparseable, total.WriteFailures, total.Bytes)
	fmt.Printf("rows_still_unrescued=%d (raw.records gtfs_rt rows with payload_ref NULL whose bytes were not in the retained broker window)\n",
		len(needRescue)-countRescued(needRescue, written))

	if failures > 0 {
		return fmt.Errorf("%d frame(s) could not be written to the object store; the rescue is INCOMPLETE — fix the store and re-run (idempotent)", failures)
	}
	return nil
}

func countRescued(needRescue map[string]bool, written map[string]bool) int {
	n := 0
	for id := range needRescue {
		if written[gtfsrt.ObjectKey(id)] {
			n++
		}
	}
	return n
}

func haveRefContains(haveRef map[string]bool, id string) bool { return haveRef[id] }

// loadIndex reads (read-only) the gtfs_rt slice of raw.records: the set of
// record_ids with no payload_ref (rescue targets) and the count that
// already carry one.
func loadIndex(ctx context.Context, dbURL string) (map[string]bool, map[string]bool, error) {
	conn, err := pgx.Connect(ctx, dbURL)
	if err != nil {
		// Deliberately does not wrap the URL: it carries credentials.
		return nil, nil, fmt.Errorf("database connection failed: %w", sanitize(err, dbURL))
	}
	defer conn.Close(ctx)

	needRescue := map[string]bool{}
	haveRef := map[string]bool{}
	rows, err := conn.Query(ctx,
		"SELECT record_id, payload_ref IS NULL FROM raw.records WHERE source = 'gtfs_rt'")
	if err != nil {
		return nil, nil, fmt.Errorf("query raw.records: %w", sanitize(err, dbURL))
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		var refNull bool
		if err := rows.Scan(&id, &refNull); err != nil {
			return nil, nil, err
		}
		if refNull {
			needRescue[id] = true
		} else {
			haveRef[id] = true
		}
	}
	return needRescue, haveRef, rows.Err()
}

// sanitize guards against a driver error echoing the DSN.
func sanitize(err error, dbURL string) error {
	msg := strings.ReplaceAll(err.Error(), dbURL, "<database url redacted>")
	return fmt.Errorf("%s", msg)
}

func storeFromEnv() (*minio.Client, string, error) {
	endpoint := os.Getenv("S3_ENDPOINT")
	if endpoint == "" {
		return nil, "", fmt.Errorf("S3_ENDPOINT is required")
	}
	accessKey := os.Getenv("S3_ACCESS_KEY")
	secretKey := os.Getenv("S3_SECRET_KEY")
	if accessKey == "" || secretKey == "" {
		return nil, "", fmt.Errorf("S3_ACCESS_KEY and S3_SECRET_KEY are required")
	}
	bucket := os.Getenv("S3_BUCKET")
	if bucket == "" {
		bucket = "headway-raw"
	}
	client, err := minio.New(endpoint, &minio.Options{
		Creds:  credentials.NewStaticV4(accessKey, secretKey, ""),
		Secure: strings.EqualFold(os.Getenv("S3_USE_SSL"), "true"),
	})
	if err != nil {
		return nil, "", fmt.Errorf("minio client: %w", err)
	}
	return client, bucket, nil
}

func objectPresent(ctx context.Context, store *minio.Client, bucket, key string) (bool, error) {
	_, err := store.StatObject(ctx, bucket, key, minio.StatObjectOptions{})
	if err == nil {
		return true, nil
	}
	resp := minio.ToErrorResponse(err)
	if resp.Code == "NoSuchKey" || resp.StatusCode == 404 {
		return false, nil
	}
	return false, err
}
