# Bluesky launch content — Headway

## Profile
- Handle suggestion: `@headway-transit.bsky.social` (custom domain later: `@headway.dev`-style once one exists)
- Display name: Headway
- Bio (≤256): Open-source transit data platform where every number can prove itself. Deterministic NTD reporting, full lineage to raw records, the FTA rule quoted inside every figure. AI assists — never computes a reported number. Apache-2.0.
- Avatar: the 🚌 mark / favicon from web/public (export as PNG); banner: the Receipt screenshot (docs/images/receipt.png).

## Announcement thread (post after the repo is public)

**1/**
Meet Headway: an open-source data platform for public transit agencies, built on one idea — every reported number should be able to prove itself.

github.com/headway-transit/headway

**2/**
Click any figure and it opens its receipt: how complete the data is, what was excluded and why, and the federal regulation it implements — quoted, page-cited, inside the number. Then walk it down to the raw vehicle telemetry it came from.

**3/**
It refuses to lie. Gaps in telemetry never get papered over — the platform declines to report figures it can't stand behind, and every exclusion becomes a documented, owned data-quality issue. (An unexplained gap becomes a finding in an FTA triennial review. So: no unexplained gaps.)

**4/**
AI helps — flagging anomalies, triaging data quality — but AI never computes a reported number. That's enforced by types and a CI grounding gate, not a policy PDF. Every AI output cites its sources and requires human review.

**5/**
Everything runs on one commodity Linux box a small agency can afford (Postgres/TimescaleDB, Kafka, all open source), with a guided installer written for IT generalists. Gov-cloud runs the identical signed artifacts. Cloud-only features are rejected by charter.

**6/**
It's alpha, it's honest about that (the UI marks every pre-verification figure), and it's built to resist single-vendor capture — governance charter included. Agencies, vendors, transit data folks: come look. Apache-2.0.

github.com/headway-transit/headway

## Posting notes
- Account creation is manual (email required). For API posting later: create an app password in Bluesky settings; the atproto HTTP API (`com.atproto.repo.createRecord`) posts with handle + app password. Never store the app password in the repo.
