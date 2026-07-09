package producer

import (
	"context"
	"fmt"

	"github.com/twmb/franz-go/pkg/kgo"
)

// Kafka is a Producer backed by franz-go (BSD-3-Clause). Production is
// synchronous: PollOnce-style connectors need the produce acknowledged
// before advancing their dedupe cursor (at-least-once, never silent loss).
type Kafka struct {
	client *kgo.Client
}

// NewKafka dials the given brokers. The client uses franz-go defaults
// (acks=all, idempotent producer) — deliberate for a walking skeleton;
// backpressure tuning is a next increment.
func NewKafka(brokers []string) (*Kafka, error) {
	client, err := kgo.NewClient(kgo.SeedBrokers(brokers...))
	if err != nil {
		return nil, fmt.Errorf("kafka producer: %w", err)
	}
	return &Kafka{client: client}, nil
}

// Produce sends one record and waits for the broker acknowledgement.
func (k *Kafka) Produce(ctx context.Context, topic string, key, value []byte) error {
	rec := &kgo.Record{Topic: topic, Key: key, Value: value}
	if err := k.client.ProduceSync(ctx, rec).FirstErr(); err != nil {
		return fmt.Errorf("produce to %s: %w", topic, err)
	}
	return nil
}

// Close flushes and releases the underlying client.
func (k *Kafka) Close() {
	k.client.Close()
}
