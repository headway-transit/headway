# Testing a first install on a clean machine

This is the checklist for putting Headway on a computer that has never had it,
the way a stranger who downloaded the project would — and for recording what
that machine tells you. It exists because **nothing automated runs the
installer**. CI builds every service and runs 784 tests against them, and none
of that touches `install/install.sh`, which is the one path every first-time
operator takes.

The first time it was run this way (2026-08-02, clean Ubuntu 26.04) it found
four defects in an hour, one of them severe enough that the default install
produced no working Headway at all. Assume the next run finds more.

## What the machine needs

- A **clean** Linux install. The value is in it *not* having your development
  environment — no Docker, no Go, no Node, no checkout. If you reuse a machine,
  you are testing your own history, not the product.
- 4 GB RAM minimum, 8+ comfortable (the stack runs TimescaleDB, Kafka, MinIO,
  Prometheus, Grafana and Apicurio alongside the four Headway services).
- 20 GB free disk. A build cycle strands layers; expect real growth.
- Network access for the image pulls (~2 GB on first start).

**Never put real agency data on a UAT machine.** Use a public feed from an
agency you have no relationship with. `docs/connecting-your-data.md` covers the
feed settings; the 2026-08-02 run used Link Transit (Wenatchee), which needs no
key and publishes all three realtime feeds.

## The sequence

### 1. Docker, before anything else

The installer does **not** install Docker, deliberately: it needs root and this
installer never uses root on your behalf. Since 2026-08-02 it detects your
distribution and prints the exact one-line command; run that, then log out and
back in so the `docker` group applies.

> If you are driving this over SSH, the group change does not reach an existing
> connection. Reconnect, or `id -nG` will still show no `docker` and every
> command will fail with "permission denied … /var/run/docker.sock".

### 2. `./install/install.sh --check`

Changes nothing. Every line should be OK. Expect a NOTE about `buildx` if you
installed Docker from a distribution package — harmless, the build falls back.

Run this **again after the install** too. It should say *ready*, not report its
own containers as port conflicts. That was a defect; it is a regression test
now.

### 3. `./install/install.sh`

Or `--yes` with `HEADWAY_AGENCY_ID`, `HEADWAY_ADMIN_USERNAME`,
`HEADWAY_ADMIN_PASSWORD` set (see `install/README.md`).

**Generate the admin password on the target machine**, not on your laptop and
not in a chat window:

```sh
umask 077; openssl rand -base64 24 > ~/headway-admin-password.txt
```

When it finishes, **verify it actually installed something**:

```sh
docker ps --format '{{.Names}}\t{{.Status}}'
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/openapi.json   # 200
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/               # 200
```

You must see `api`, `web`, `transform` and `ingestion`, not just the
infrastructure containers. Until 2026-08-02 the default access mode started
infrastructure only and still reported "All services are healthy" — the health
gate and the missing services agreed with each other. Do not trust the summary;
ask the ports.

### 4. Feeds

Set `GTFS_STATIC_URL` and `GTFS_RT_VEHICLE_POSITIONS_URL` in
`deploy/compose/.env` and restart. **Vehicle positions are not optional**: the
calculation library reads `canonical.vehicle_positions`, so a static-only feed
gives you routes and stops and zero VRM/VRH — a system that looks populated and
reports nothing.

Let it poll for at least 30 minutes before computing anything. A figure over
four minutes of movement is arithmetic, not evidence.

Then dispatch a run and read what comes back:

```sh
curl -X POST .../calc/runs -d '{"period_start":"YYYY-MM-DD","period_end":"YYYY-MM-DD"}'
```

### 5. Network access

`./install/install.sh --reconfigure-access` moves between "just this computer"
and "other computers in the office". The `lan` mode starts Caddy, which
publishes 80 and 443 on every interface — the one deliberate non-localhost
binding in the stack. Browsers warn once, because Caddy issues from its own
local CA; `docs/network-access.md` has the steps to install that root.

If you put your own proxy in front instead, set `HEADWAY_TRUSTED_PROXIES`. Skip
it and every request arrives as the proxy: one shared rate-limit allowance for
the whole office, one shared failed-sign-in audit bucket, and an audit trail
that records the proxy instead of the person.

## What to look at that a test suite cannot

These are the questions worth a real machine. Everything else is cheaper to
test in CI.

1. **Does a successful install produce a working application?** Ask the ports,
   never the summary.
2. **Do two different clients get separate rate-limit allowances through the
   proxy?** Exhaust the public allowance from one address, then call from
   another. Separate buckets is the correct answer; a second 429 means
   `HEADWAY_TRUSTED_PROXIES` is unset or wrong.
3. **Does revoking access revoke access?** Deactivate an account and reuse its
   token immediately. It must fail on the very next request.
4. **Does the pipeline refuse when it should?** With no passenger counts,
   `pmt_v0` must raise a *blocking* finding and write no figure — and
   certification must then refuse. A run that certifies cleanly over a known
   gap is the most serious possible failure.
5. **What do the numbers look like?** This is the check only a human with
   domain knowledge can make. A plausible VRM for a small agency is the whole
   point; "the pipeline ran" is a much weaker result.

## Things that cannot be automated, on purpose

- **`--download-basemap` refuses `--yes`.** It reaches the internet, so it
  always asks a person. Correct for the command; it does mean an IT department
  cannot script a fleet install *with* a basemap. Open question, not a defect.
- **The installer never runs `sudo`.** It prints commands for you to run.
  Pinned by `install/test_installer_static.py`.

## Recording what you find

Findings go in a PR against the thing that was wrong, with the evidence inline
— the command, its output, and what an operator would have concluded. Chat
scrolls; a commit message does not. Where a finding is a first-run defect, add
a static check to `install/test_installer_static.py` and confirm it **fails
against the old code** before you keep it. A test that never went red proves
nothing.
