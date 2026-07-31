package gtfsrt

// Integration test against a real S3 endpoint — a DISPOSABLE MinIO
// container, never a live install's bucket. Skipped unless
// GTFSRT_IT_S3_ENDPOINT is set, e.g.:
//
//	sg docker -c "docker run -d --name headway-0036-minio \
//	  -e MINIO_ROOT_USER=it -e MINIO_ROOT_PASSWORD=<pw> \
//	  -p 127.0.0.1:29000:9000 minio/minio:RELEASE.2025-04-22T22-12-26Z \
//	  server /data"
//	GTFSRT_IT_S3_ENDPOINT=127.0.0.1:29000 GTFSRT_IT_S3_ACCESS_KEY=it \
//	  GTFSRT_IT_S3_SECRET_KEY=<pw> \
//	  go test ./connectors/gtfsrt/ -run Integration -count=1 -v
//
// The test creates its own throwaway bucket. It proves the two things the
// unit fakes cannot: the MinioStore Put path against the real wire
// protocol, and byte-fidelity of what lands (read back and re-hashed).

import (
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
	"time"

	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"

	"github.com/headway-transit/headway/services/ingestion/internal/envelope"
	"github.com/headway-transit/headway/services/ingestion/internal/producer"
)

func integrationClient(t *testing.T) (*minio.Client, string) {
	t.Helper()
	endpoint := os.Getenv("GTFSRT_IT_S3_ENDPOINT")
	if endpoint == "" {
		t.Skip("GTFSRT_IT_S3_ENDPOINT not set; integration test needs the disposable MinIO container (see file header)")
	}
	client, err := minio.New(endpoint, &minio.Options{
		Creds: credentials.NewStaticV4(
			os.Getenv("GTFSRT_IT_S3_ACCESS_KEY"),
			os.Getenv("GTFSRT_IT_S3_SECRET_KEY"), ""),
		Secure: false,
	})
	if err != nil {
		t.Fatalf("minio client: %v", err)
	}
	bucket := "headway-0036-it"
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	exists, err := client.BucketExists(ctx, bucket)
	if err != nil {
		t.Fatalf("bucket exists check (is the disposable MinIO up?): %v", err)
	}
	if !exists {
		if err := client.MakeBucket(ctx, bucket, minio.MakeBucketOptions{}); err != nil {
			t.Fatalf("make bucket: %v", err)
		}
	}
	return client, bucket
}

func TestIntegrationPollLandsFrameInRealMinioBeforeProduce(t *testing.T) {
	client, bucket := integrationClient(t)
	frame := validFrame(t)

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", ContentType)
		w.Write(frame)
	}))
	defer srv.Close()

	fake := producer.NewFake()
	p := &Poller{
		URL:      srv.URL,
		FeedType: VehiclePositions,
		Interval: time.Second,
		Store:    NewMinioStore(client, bucket),
		Producer: fake,
		Log:      slog.New(slog.NewTextHandler(testWriter{t}, nil)),
	}
	if err := p.PollOnce(context.Background()); err != nil {
		t.Fatalf("PollOnce against real MinIO: %v", err)
	}

	recordID := envelope.RecordID(frame)
	obj, err := client.GetObject(context.Background(), bucket,
		ObjectKey(recordID), minio.GetObjectOptions{})
	if err != nil {
		t.Fatalf("get object: %v", err)
	}
	defer obj.Close()
	stored, err := io.ReadAll(obj)
	if err != nil {
		t.Fatalf("read object: %v", err)
	}
	if string(stored) != string(frame) {
		t.Fatalf("stored bytes differ from raw frame bytes")
	}
	if got := envelope.RecordID(stored); got != recordID {
		t.Fatalf("stored bytes re-hash to %s, want %s", got, recordID)
	}
	if len(fake.Messages()) != 1 {
		t.Fatalf("produced %d messages, want 1", len(fake.Messages()))
	}

	// Idempotent re-put of the same content-addressed key must succeed
	// (a restart re-lands the current frame; same key, same bytes).
	if err := p.Store.Put(context.Background(), ObjectKey(recordID), frame); err != nil {
		t.Fatalf("idempotent re-put: %v", err)
	}
}

func TestIntegrationStoreRefusalBlocksProduce(t *testing.T) {
	client, _ := integrationClient(t)
	frame := validFrame(t)

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", ContentType)
		w.Write(frame)
	}))
	defer srv.Close()

	fake := producer.NewFake()
	p := &Poller{
		URL:      srv.URL,
		FeedType: VehiclePositions,
		Interval: time.Second,
		// A bucket that does not exist: the real store refuses the write.
		Store:    NewMinioStore(client, "headway-0036-it-missing-bucket"),
		Producer: fake,
		Log:      slog.New(slog.NewTextHandler(testWriter{t}, nil)),
		Sleep:    func(time.Duration) {},
	}
	if err := p.PollOnce(context.Background()); err == nil {
		t.Fatal("PollOnce must fail loudly when the real store refuses the write")
	}
	if got := len(fake.Messages()); got != 0 {
		t.Fatalf("store refused but %d message(s) produced — store-before-produce violated", got)
	}
}
