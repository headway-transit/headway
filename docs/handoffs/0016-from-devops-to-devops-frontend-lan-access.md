# Handoff: devops → devops, docs — Plain-language network access ("Where will people use Headway from?")

## Context
The stack binds 127.0.0.1 by design; the documented LAN answer is "SSH tunnel," which assumes skills small agencies don't have (project direction, 2026-07-14: installation must work for people not versed in containers). The installer's charter is IT-generalist plain language — network access must become an installer question with a safe, working answer for each skill level.

## Design (binding)
1. **Installer question** (install.sh, same plain-language style, logged, re-runnable via `--reconfigure-access`): "Where will people use Headway from?" → (a) just this computer [default; today's behavior]; (b) other computers in our office [new]; (c) our IT staff will set up access [today's behavior + docs pointer].
2. **Option (b) mechanics:** compose profile `lan` adds a Caddy reverse proxy (Apache-2.0 — run the license gate) terminating HTTPS with Caddy's automatic local CA (`local_certs`); web+API reachable ONLY through it (upstream ports stay 127.0.0.1); the installer detects the machine's primary LAN address (ask-to-confirm, never assume), sets HEADWAY_CORS_ORIGINS and any session/origin config to match (the wave-14 CORS lesson — the installer owns this wiring), prints: the https:// URL to share, the one ufw/firewalld command if a firewall is active (print, never run — installer's existing sudo posture), a plain-language explanation of the first-visit browser certificate warning and what accepting it means on an internal network, and how to install the local CA cert (per-OS, links into docs/network-access.md). Idempotent re-runs; `--reconfigure-access` can also go BACK to localhost-only.
3. **docs/network-access.md:** the three options with their honest trade-offs in plain language; the tunnel path for real people (Mac/Linux one-liner; Windows PuTTY click-by-click with field names since screenshots aren't possible — write it so a person who has never opened PuTTY succeeds); the local-CA install steps per OS; an explicit "do NOT expose Headway directly to the internet" section (what a reverse proxy/VPN is for, one paragraph, no jargon).
4. **Honest scope:** no Let's Encrypt/public-DNS automation in v0 (agencies with real DNS + certs have IT staff — option c); no changes to Grafana/MinIO/etc. bindings (admin surfaces stay localhost; document that deliberately).
5. **Verification:** compose profile boots on the dev box; HTTPS via Caddy works against the LAN interface address (curl -k from the box's own LAN IP, headers/CORS verified); web login + a metrics fetch through the proxy (the wave-14 class of bug is the target); installer question paths exercised with --check and a real run on the dev box where safe (do NOT break the running demo stack — use a disposable compose project name for the proxied boot test); license gate green with Caddy added. The full fresh-box run remains the standing installer pending (VM incoming — note it, don't fake it).

## Outputs
Installer question + reconfigure path, compose `lan` profile w/ Caddy, CORS/origin auto-wiring, docs/network-access.md, sizing.md + install/README cross-links updated, evidence here.

## Open Questions
- Let's Encrypt path for agencies with a DNS name (v1, likely trivial with Caddy).
- Whether Grafana should ever join the proxy (admin-only; deliberate v0 exclusion).

## Outputs — evidence

Built 2026-07-13 (DevOps role). Working tree only — no commits, per instruction.
Scope touched: `install/install.sh`, `install/README.md`, `deploy/compose/`
(`compose.yaml`, `.env.example`, `caddy/Caddyfile` [new], `README.md`),
`docs/network-access.md` [new], `docs/sizing.md`. `services/`, `web/`, `db/`
untouched (`git status` confirms). The live demo (compose project `headway`,
dev API :8000, vite :5173) was never disrupted — re-verified after teardown, below.

### What shipped, against the five design points

1. **Installer question + `--reconfigure-access`.** `install.sh` asks "Where
   will people use Headway from?" (a/b/c, default a) in the guided flow;
   `--yes` reads `HEADWAY_ACCESS_MODE` (+ `HEADWAY_LAN_ADDRESS`, required for
   lan — never guessed in unattended mode); `--reconfigure-access` re-asks on
   an existing install, works in BOTH directions, and is idempotent (verified
   below). `--check` now also reports the current access mode.
2. **Compose profile `lan`.** `caddy:2.10.2` (pinned; Apache-2.0), `local_certs`
   auto-CA persisted in the `caddy-data` volume, ONE https origin proxying
   `/api/*` → `api:8000` (prefix stripped) and `/` → `web:8080`. Host port
   bindings of web/api stay `127.0.0.1`; Caddy's 80/443 is the single
   deliberate non-localhost binding. Admin surfaces (Grafana, MinIO,
   Prometheus, Apicurio, Kafka, Postgres) deliberately NOT proxied — stated in
   the Caddyfile, compose comments, and docs.
3. **LAN detection + confirm.** `ip -4 route get 1.1.1.1` (fallback
   `hostname -I`), always shown and confirmed by the human; ports 80/443
   checked at answer time (with an exemption when our own caddy already holds
   them, so re-picking (b) stays idempotent).
4. **CORS/origin auto-wiring.** The installer moves four values as one unit:
   `HEADWAY_ACCESS_MODE`, `HEADWAY_LAN_ADDRESS`,
   `HEADWAY_CORS_ORIGINS=https://<addr>,http://localhost:8080`,
   `VITE_API_BASE_URL=https://<addr>/api` (+ `COMPOSE_PROFILES=app,lan`), and
   rebuilds web when the baked URL changes. Design note: the single-origin
   `/api` layout makes browser→API calls same-origin by construction — the
   wave-14 class is structurally impossible through the doorway — and
   `HEADWAY_CORS_ORIGINS` is still wired in lockstep (the API emits the
   headers; verified live below). `compose.yaml` now passes
   `HEADWAY_CORS_ORIGINS` into the api service (it previously had no way in).
5. **Plain-language outputs.** Lan summary prints: the https:// URL to share,
   the ufw/firewalld command (printed, never run — detected via
   `systemctl is-active`), the certificate-warning explanation, and the CA
   pointer into `docs/network-access.md`. That doc carries the three options
   with honest trade-offs, the Mac/Linux tunnel one-liner (both 8080 and
   8000 — the bundle calls localhost:8000), PuTTY click-by-click by field
   name, per-OS CA install (Windows/macOS/Linux + Firefox/Chrome-on-Linux
   stores), the for-IT section, and the no-internet-exposure section in
   plain words.

### Live verification (dev box, 2026-07-13)

**Disposable boot of the real `lan` profile.** Project `-p headway-lan-test`,
this repo's `compose.yaml` + a throwaway override (external network join +
port-mapping strip + `:lan-test` image re-tags so the demo's tags were never
touched; override deleted after). `caddy` 2.10.2 pulled by digest
`sha256:c3d7ee5d…`; web built with `VITE_API_BASE_URL=https://192.168.7.246/api`.
All three containers reached `healthy`.

**TLS + proxying against the box's LAN interface IP (192.168.7.246):**

```
issuer=CN = Caddy Local Authority - ECC Intermediate
X509v3 Subject Alternative Name: critical  IP Address:192.168.7.246
GET http://192.168.7.246/  -> HTTP/1.1 308 Permanent Redirect  Location: https://192.168.7.246/
GET https://192.168.7.246/ -> the web app's HTML; its served JS bundle
                              contains https://192.168.7.246/api (grep: 1 hit)
```

**CORS + a real login + metrics fetch THROUGH the proxy** (scripted with
Origin headers exactly as a browser at the web origin sends them; demo user
`dsteward` from HANDOFF.md, live demo database):

```
OPTIONS /api/auth/login  (preflight) -> 200
  access-control-allow-origin: https://192.168.7.246
  access-control-allow-methods: GET, POST, PUT, DELETE
  via: 1.1 Caddy
LOGIN   status: 200 | ACAO: https://192.168.7.246 | via: 1.1 Caddy | role: data_steward
METRICS status: 200 | ACAO: https://192.168.7.246 | via: 1.1 Caddy | rows: 429
    {'metric': 'headway_adherence', 'value': '0.3346', 'period_start': '2026-07-01', 'calc_version': '0.1.0'}
```

**Negative checks:** ports 3000/9090/9001/8081/5432/8000/8080 all
refused from 192.168.7.246 (admin surfaces + upstreams unreachable except
through Caddy); `Origin: https://evil.example` receives NO
`access-control-allow-origin`; `GET /grafana` through the proxy returns the
web SPA (`text/html`), never Grafana. The documented CA-extraction command
(`docker compose … cp caddy:/data/caddy/pki/authorities/local/root.crt …`)
produced `CN = Caddy Local Authority - 2026 ECC Root` (valid to 2036).

**Three live bugs found and fixed by this test** (the reason live
verification is the norm):

1. `compose.yaml` api build context still `../../services/api` — broken since
   headway-api gained the in-repo headway-calc path dependency (the wave-16
   CI fix never reached compose). Now repo-root context like `transform`.
2. `web` (pre-existing) and `caddy` healthchecks probed `localhost`, which
   busybox wget resolves to `::1`; nginx/Caddy-admin listen IPv4-only — the
   containers served fine but sat `unhealthy`. Now `127.0.0.1`.
3. Browsers/curl send NO TLS server name for bare-IP addresses; without SNI
   Caddy dropped the handshake (`tlsv1 alert internal error`). Fixed with
   global `default_sni {$HEADWAY_LAN_ADDRESS}` — retested: no-SNI handshake
   serves the IP-SAN cert.

**Installer paths exercised.**
- Real box: `--check` run live (correctly diagnosed the 8 occupied ports of
  the running demo, reported the existing install and its access mode,
  changed nothing). Exit codes verified: bad `HEADWAY_ACCESS_MODE` → 1,
  `--yes` lan without address → 1, `--check --reconfigure-access` combo
  refused → 1.
- Conversation + rewiring: exercised against a sandbox copy of the repo
  structure (project name changed to `headway-scratch` AND the apply step
  declined, double-guaranteeing the live demo could not be touched):
  a→b wrote the four values + `COMPOSE_PROFILES=app,lan`; immediate re-run
  b→b left `.env` byte-identical (idempotent); b→a blanked
  address/origins, restored `VITE_API_BASE_URL=http://localhost:8000`, and
  removed `lan` (keeping `app`); c recorded `it` mode. Verbatim transcript
  in the session record.
- The installer now also generates `HEADWAY_SESSION_SECRET` into `.env`
  (hex, never logged) — required because option (b) starts the app profile,
  and the API refuses to boot on an empty secret.

**License gate:** `LICENSE GATE: PASS — 210 dependencies conform to ADR-0001
Amendment 1` (go 27, python 45, node 138). Caddy needs no gate row: the gate
scans the go/python/node dependency trees, and Caddy enters as a pinned
upstream container image (Apache-2.0), the same class as Kafka/MinIO/Grafana —
recorded as such in `compose.yaml`. Two environment-only artifacts were
worked around for the honest run, exactly as the gate's own docstring
prescribes: the go-licenses GOROOT quirk (fetched-toolchain PATH export) and
the gitignored design-sync self-symlink `web/node_modules/web` (parked and
restored; absent on any fresh clone/CI).

**Teardown + demo intact:** `down -v` removed the three containers and both
caddy volumes; throwaway override and `:lan-test` images deleted; nothing
listens on 80/443 afterward. Re-verified: all 8 demo containers up (6
healthy, ingestion/transform running), dev API :8000 `openapi.json` → 200 and
a real login → 200, vite :5173 → 200, Grafana :3000 health → 200. The demo's
`.env` was never modified (mtime predates this session; all test env values
travelled via the shell environment).

### Honest pendings

- **Fresh-box guided install remains the standing pending** (unchanged; VM
  incoming). The new lan path adds to that same pending: question → install →
  `COMPOSE_PROFILES=app,lan` boot → summary, end to end on a clean machine.
- `--reconfigure-access`'s **apply step against a live stack** (web rebuild +
  `up -d` + caddy stop/rm on the way back) was NOT executed on this box — the
  only Headway stack here is the demo, which this task was bound not to
  disrupt. The exact same compose operations (build web with the new URL, up,
  down) were exercised piecewise by the disposable test; the wired command
  sequence itself runs on the fresh-box test.
- Browser-real click-through from a SECOND machine on the LAN (curl + scripted
  fetch stand in for it here; a human from another office computer is the
  real thing).
- Windows/macOS CA-install steps in `docs/network-access.md` are written from
  vendor-documented UI flows, not walked on live Windows/macOS machines in
  this session.
