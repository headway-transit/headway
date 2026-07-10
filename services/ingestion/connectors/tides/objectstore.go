package tides

import (
	"bytes"
	"context"
	"fmt"
	"sync"

	"github.com/minio/minio-go/v7"
)

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
}

// NewFakeStore returns an empty in-memory store.
func NewFakeStore() *FakeStore {
	return &FakeStore{objects: map[string][]byte{}}
}

// Put stores a copy of the bytes.
func (f *FakeStore) Put(_ context.Context, key string, data []byte) error {
	f.mu.Lock()
	defer f.mu.Unlock()
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
