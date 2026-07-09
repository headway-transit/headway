package producer

import (
	"context"
	"sync"
)

// Message is one record captured by the Fake.
type Message struct {
	Topic string
	Key   []byte
	Value []byte
}

// Fake is an in-memory Producer for tests. It records every produced
// message in order and can be told to fail.
type Fake struct {
	mu       sync.Mutex
	messages []Message

	// Err, when non-nil, is returned by Produce (simulates broker failure).
	Err error
}

// NewFake returns an empty in-memory producer.
func NewFake() *Fake { return &Fake{} }

// Produce records the message.
func (f *Fake) Produce(_ context.Context, topic string, key, value []byte) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.Err != nil {
		return f.Err
	}
	f.messages = append(f.messages, Message{
		Topic: topic,
		Key:   append([]byte(nil), key...),
		Value: append([]byte(nil), value...),
	})
	return nil
}

// Messages returns a copy of everything produced so far.
func (f *Fake) Messages() []Message {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]Message(nil), f.messages...)
}
