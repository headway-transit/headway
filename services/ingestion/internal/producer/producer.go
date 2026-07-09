// Package producer defines the minimal Kafka production boundary for
// ingestion connectors (ADR-0002, ADR-0006). Connectors depend on the
// Producer interface only; the Kafka implementation lives in kafka.go and
// an in-memory fake for tests lives in fake.go.
package producer

import "context"

// Producer produces one message to a topic. Implementations must be safe
// for concurrent use. Ingestion keys every message by record_id.
type Producer interface {
	Produce(ctx context.Context, topic string, key, value []byte) error
}
