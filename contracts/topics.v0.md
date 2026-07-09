# Kafka Topic Registry — v0

Convention: `raw.<source>.<subtype>` for connector-produced raw records (envelope: `raw-record-envelope.v0.schema.json`). All topics use the raw-record envelope as the message value (JSON); the message key is `record_id`. Schemas are registered in Apicurio under the same names (ADR-0006).

| Topic | Producer | Payload content |
| --- | --- | --- |
| `raw.gtfs_static.feed` | `headway-gtfs-static` | Complete GTFS static zip (payload_encoding: `object_ref`) |
| `raw.gtfs_rt.vehicle_positions` | `headway-gtfs-rt` | One GTFS-Realtime FeedMessage protobuf frame (base64) |
| `raw.gtfs_rt.trip_updates` | `headway-gtfs-rt` | One GTFS-Realtime FeedMessage protobuf frame (base64) |
| `raw.gtfs_rt.alerts` | `headway-gtfs-rt` | One GTFS-Realtime FeedMessage protobuf frame (base64) |

GTFS and GTFS-Realtime payload semantics are defined by the specifications at gtfs.org — verify against the current published spec; this registry defines transport only, never field meaning.

Adding a topic requires a contracts change (Platform Architect governance) — connectors must not invent topics.
