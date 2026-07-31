// Package envelope builds Headway raw-record envelopes per
// contracts/raw-record-envelope.v0.schema.json (ADR-0006, ADR-0007).
//
// The envelope wraps the EXACT payload bytes as received from the source.
// record_id is the lowercase hex SHA-256 of those bytes (content-addressed
// identity). Payload bytes are never mutated, re-encoded, or normalized here;
// base64 is a transport encoding of the same bytes, and object_ref points at
// an object whose bytes hash to record_id.
package envelope

import (
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"time"
)

// Version is the envelope contract version this package implements.
const Version = 0

// Payload encodings per the schema enum.
const (
	EncodingBase64    = "base64"
	EncodingObjectRef = "object_ref"
)

// Parse statuses per the schema enum.
const (
	ParseOK        = "ok"
	ParseMalformed = "malformed"
)

// Envelope is the wire form of the raw-record envelope v0.
// Field names and optionality match the JSON schema exactly.
type Envelope struct {
	EnvelopeVersion  int    `json:"envelope_version"`
	RecordID         string `json:"record_id"`
	Source           string `json:"source"`
	Connector        string `json:"connector"`
	ConnectorVersion string `json:"connector_version"`
	AgencyID         string `json:"agency_id,omitempty"`
	FeedURL          string `json:"feed_url,omitempty"`
	FetchedAt        string `json:"fetched_at"`
	ContentType      string `json:"content_type"`
	PayloadEncoding  string `json:"payload_encoding"`
	Payload          string `json:"payload"`
	// PayloadRef is the object-store key where the payload bytes are ALSO
	// durably stored (handoff 0036, additive same-version extension). It is
	// what lets a base64 envelope — whose inline payload downstream
	// normalizers keep reading straight off the wire — still register in
	// raw.records as durably held (payload_encoding=object_ref +
	// payload_ref). For object_ref envelopes it is redundant with Payload
	// and left empty.
	PayloadRef  string `json:"payload_ref,omitempty"`
	ParseStatus string `json:"parse_status"`
	ParseError  string `json:"parse_error,omitempty"`
}

// Params carries everything needed to build an envelope around raw bytes.
type Params struct {
	Source           string
	Connector        string
	ConnectorVersion string
	AgencyID         string // optional
	FeedURL          string // optional
	FetchedAt        time.Time
	ContentType      string
	ParseStatus      string
	ParseError       string // required in practice when ParseStatus is malformed
}

// RecordID returns the lowercase hex SHA-256 of the exact payload bytes.
func RecordID(payload []byte) string {
	sum := sha256.Sum256(payload)
	return hex.EncodeToString(sum[:])
}

// New builds a base64-encoded envelope around the exact raw payload bytes.
func New(payload []byte, p Params) (Envelope, error) {
	e := Envelope{
		EnvelopeVersion:  Version,
		RecordID:         RecordID(payload),
		Source:           p.Source,
		Connector:        p.Connector,
		ConnectorVersion: p.ConnectorVersion,
		AgencyID:         p.AgencyID,
		FeedURL:          p.FeedURL,
		FetchedAt:        p.FetchedAt.UTC().Format(time.RFC3339),
		ContentType:      p.ContentType,
		PayloadEncoding:  EncodingBase64,
		Payload:          base64.StdEncoding.EncodeToString(payload),
		ParseStatus:      p.ParseStatus,
		ParseError:       p.ParseError,
	}
	if err := e.Validate(); err != nil {
		return Envelope{}, err
	}
	return e, nil
}

// NewStored builds a base64-encoded envelope whose exact payload bytes have
// ALSO been landed in the object store at objectKey (store-before-produce,
// handoff 0036). The inline base64 copy stays on the wire so consumers keep
// normalizing without an object-store dependency; payload_ref is the durable
// address the raw-record index registers. The caller must have completed the
// store write before producing this envelope — an envelope pointing at an
// object that does not exist is a lie.
func NewStored(payload []byte, objectKey string, p Params) (Envelope, error) {
	e, err := New(payload, p)
	if err != nil {
		return Envelope{}, err
	}
	if objectKey == "" {
		return Envelope{}, fmt.Errorf("envelope: NewStored requires a non-empty object key")
	}
	e.PayloadRef = objectKey
	return e, nil
}

// NewObjectRef builds an object_ref envelope. payload is the raw bytes that
// were (or will be) landed at objectKey in the object store; record_id is
// still the hash of those bytes, so the object contents remain provable.
func NewObjectRef(payload []byte, objectKey string, p Params) (Envelope, error) {
	e := Envelope{
		EnvelopeVersion:  Version,
		RecordID:         RecordID(payload),
		Source:           p.Source,
		Connector:        p.Connector,
		ConnectorVersion: p.ConnectorVersion,
		AgencyID:         p.AgencyID,
		FeedURL:          p.FeedURL,
		FetchedAt:        p.FetchedAt.UTC().Format(time.RFC3339),
		ContentType:      p.ContentType,
		PayloadEncoding:  EncodingObjectRef,
		Payload:          objectKey,
		ParseStatus:      p.ParseStatus,
		ParseError:       p.ParseError,
	}
	if err := e.Validate(); err != nil {
		return Envelope{}, err
	}
	return e, nil
}

// Validate checks the required-field and enum constraints of the v0 schema.
// It exists so a connector fails loudly at build time rather than producing
// a non-conformant message.
func (e Envelope) Validate() error {
	if e.EnvelopeVersion != Version {
		return fmt.Errorf("envelope: envelope_version must be %d, got %d", Version, e.EnvelopeVersion)
	}
	if len(e.RecordID) != 64 {
		return fmt.Errorf("envelope: record_id must be 64 lowercase hex chars, got %q", e.RecordID)
	}
	for _, c := range e.RecordID {
		if (c < '0' || c > '9') && (c < 'a' || c > 'f') {
			return fmt.Errorf("envelope: record_id must be lowercase hex, got %q", e.RecordID)
		}
	}
	required := map[string]string{
		"source":            e.Source,
		"connector":         e.Connector,
		"connector_version": e.ConnectorVersion,
		"fetched_at":        e.FetchedAt,
		"content_type":      e.ContentType,
		"payload_encoding":  e.PayloadEncoding,
		"payload":           e.Payload,
		"parse_status":      e.ParseStatus,
	}
	for name, v := range required {
		if v == "" {
			return fmt.Errorf("envelope: required field %s is empty", name)
		}
	}
	if e.PayloadEncoding != EncodingBase64 && e.PayloadEncoding != EncodingObjectRef {
		return fmt.Errorf("envelope: payload_encoding must be base64 or object_ref, got %q", e.PayloadEncoding)
	}
	if e.ParseStatus != ParseOK && e.ParseStatus != ParseMalformed {
		return fmt.Errorf("envelope: parse_status must be ok or malformed, got %q", e.ParseStatus)
	}
	if e.ParseStatus == ParseMalformed && e.ParseError == "" {
		return fmt.Errorf("envelope: parse_error is required when parse_status is malformed")
	}
	if e.PayloadEncoding == EncodingObjectRef && e.PayloadRef != "" && e.PayloadRef != e.Payload {
		return fmt.Errorf(
			"envelope: object_ref envelope carries payload (key %q) and payload_ref (%q) that disagree",
			e.Payload, e.PayloadRef)
	}
	if _, err := time.Parse(time.RFC3339, e.FetchedAt); err != nil {
		return fmt.Errorf("envelope: fetched_at is not RFC3339: %w", err)
	}
	return nil
}

// MarshalJSONBytes renders the envelope as the Kafka message value.
func (e Envelope) MarshalJSONBytes() ([]byte, error) {
	return json.Marshal(e)
}
