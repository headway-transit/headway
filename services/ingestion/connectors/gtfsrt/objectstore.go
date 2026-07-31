package gtfsrt

// Durable landing for GTFS-Realtime frames (handoff 0036). Until this wave
// the connector base64-encoded each frame into the ingest envelope and the
// broker was the ONLY place the bytes existed — broker retention (a
// deployment knob) was silently acting as the records policy for every
// realtime lineage leaf. Now the exact received bytes are written to the
// object store BEFORE the envelope is produced, exactly like every other
// connector (the tides/samsara/vendorfile objectstore pattern): the object
// store is the system of record, the broker is the wire (ADR-0006 posture,
// ADR-0012 retention).

import (
	"bytes"
	"context"
	"fmt"
	"sync"

	"github.com/minio/minio-go/v7"
)

// ObjectKey returns the content-addressed object-store key for one
// GTFS-Realtime frame. DELIBERATELY derivable from columns raw.records
// already holds (source + record_id, nothing else): legacy rows landed
// before durable storage have payload_ref NULL, and the API's payload
// reader and the backfill tool must both be able to compute this key from
// the immutable row alone. The feed type (vehicle_positions / trip_updates
// / alerts) is NOT in the key because raw.records does not record it —
// content addressing makes collisions impossible and identical bytes are
// the same record regardless of which feed carried them.
func ObjectKey(recordID string) string {
	return fmt.Sprintf("raw/gtfs_rt/%s.pb", recordID)
}

// ObjectStore lands immutable raw bytes at a key. Implementations must
// never rewrite an existing object's bytes: keys are content-addressed
// (derived from record_id), so a re-put of the same key carries the same
// bytes by construction (idempotent re-ingest).
type ObjectStore interface {
	Put(ctx context.Context, key string, data []byte) error
}

// MinioStore is an ObjectStore backed by an S3-compatible endpoint
// (MinIO on-prem, S3 API in gov-cloud) via minio-go (Apache-2.0).
type MinioStore struct {
	client *minio.Client
	bucket string
}

// NewMinioStore wraps an existing minio client and target bucket.
func NewMinioStore(client *minio.Client, bucket string) *MinioStore {
	return &MinioStore{client: client, bucket: bucket}
}

// Put uploads the bytes at key.
func (s *MinioStore) Put(ctx context.Context, key string, data []byte) error {
	_, err := s.client.PutObject(ctx, s.bucket, key,
		bytes.NewReader(data), int64(len(data)),
		minio.PutObjectOptions{ContentType: ContentType})
	if err != nil {
		return fmt.Errorf("object store put %s/%s: %w", s.bucket, key, err)
	}
	return nil
}

// FakeStore is an in-memory ObjectStore for tests.
type FakeStore struct {
	mu      sync.Mutex
	objects map[string][]byte

	// Err, when non-nil, is returned by Put (simulates store failure).
	Err error
	// FailPuts > 0 makes the next N Puts fail with Err (retry testing).
	FailPuts int
	// Puts counts every Put attempt, including refused ones.
	Puts int
}

// NewFakeStore returns an empty in-memory store.
func NewFakeStore() *FakeStore {
	return &FakeStore{objects: map[string][]byte{}}
}

// Put stores a copy of the bytes.
func (f *FakeStore) Put(_ context.Context, key string, data []byte) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.Puts++
	if f.FailPuts > 0 {
		f.FailPuts--
		if f.Err != nil {
			return f.Err
		}
		return fmt.Errorf("fake store: transient failure")
	}
	if f.Err != nil {
		return f.Err
	}
	f.objects[key] = append([]byte(nil), data...)
	return nil
}

// Get returns the stored bytes and whether the key exists.
func (f *FakeStore) Get(key string) ([]byte, bool) {
	f.mu.Lock()
	defer f.mu.Unlock()
	b, ok := f.objects[key]
	return b, ok
}
