# Kafka Topic Registry — v0

Convention: `raw.<source>.<subtype>` for connector-produced raw records (envelope: `raw-record-envelope.v0.schema.json`). All topics use the raw-record envelope as the message value (JSON); the message key is `record_id`. Schemas are registered in Apicurio under the same names (ADR-0006).

| Topic | Producer | Payload content |
| --- | --- | --- |
| `raw.gtfs_static.feed` | `headway-gtfs-static` | Complete GTFS static zip (payload_encoding: `object_ref`) |
| `raw.gtfs_rt.vehicle_positions` | `headway-gtfs-rt` | One GTFS-Realtime FeedMessage protobuf frame (base64) |
| `raw.gtfs_rt.trip_updates` | `headway-gtfs-rt` | One GTFS-Realtime FeedMessage protobuf frame (base64) |
| `raw.gtfs_rt.alerts` | `headway-gtfs-rt` | One GTFS-Realtime FeedMessage protobuf frame (base64) |
| `raw.tides.passenger_events` | `headway-tides` | One TIDES `passenger_events` CSV file (payload_encoding: `object_ref`) |
| `raw.dr.trips` | `headway-dr` | One `demand_response_trip` v0 CSV file (payload_encoding: `object_ref`; row format: `demand-response-trip.v0.schema.json` + `demand-response-trip.v0.md`, handoff 0013) |
| `raw.vendor.files` | `headway-vendor-file` | One vendor-export file, ORIGINAL bytes (payload_encoding: `object_ref`). Envelope `source` = the registered adapter mapping-spec label `<vendor>_<product>` (or `<vendor>_<product>_simulated` for synthetic data); interpretation is defined ONLY by the registered spec (`adapters/<vendor>/<product>/mapping.v0.yaml` per `adapter-mapping.v0.schema.json`, handoff 0015). The transform runtime REFUSES unregistered labels fail-closed (raw record retained, blocking DQ issue, zero canonical writes). |

GTFS and GTFS-Realtime payload semantics are defined by the specifications at gtfs.org — verify against the current published spec; this registry defines transport only, never field meaning. TIDES `passenger_events` payload semantics are defined by the TIDES specification (`spec/passenger_events.schema.json` in the TIDES-transit/TIDES repository on GitHub) — verify field names and the `event_type` enumeration against the current spec at implementation time, never from memory. Simulated passenger-event drops carry envelope `source = "tides_simulated"`, never `"tides"` (handoff 0005 binding rule). Demand-response trip payload semantics are defined by `demand-response-trip.v0.schema.json` in this directory (handoff 0013); its regulatory field meanings are pointers to the quotes in `services/calc/REGULATORY_TRACKER.md` ("Verified — Demand Response / on-demand reporting") — verify against the current published NTD Policy Manual, never from memory. Simulated DR drops carry envelope `source = "dr_simulated"`, never `"dr"` (the same binding rule).

Adding a topic requires a contracts change (Platform Architect governance) — connectors must not invent topics.
