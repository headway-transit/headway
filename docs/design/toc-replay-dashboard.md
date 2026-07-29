# Design blueprint: the Transit Operations Center replay dashboard

Status: **design, not built.** Authored 2026-07-29 from a project-lead brief adapting
the temporal-scrubber paradigm of Hugging Face's incident-replay dashboard to a transit
operations center. Nothing here has shipped; the phasing in §6 says what must exist
first. Everything here is subordinate to `.claude/roles/_SHARED_CONSTRAINTS.md`.

---

## 0. The one adaptation that matters: reconstruction is not observation

The source paradigm scrubs through a log of *discrete events* — each one either happened
or didn't. Transit telemetry is different: a vehicle reports its position every ~30
seconds and **we do not know where it was in between.** A scrubber that glides a bus
smoothly between two pings is drawing positions no vehicle ever reported.

This platform already has a shipped rule about exactly that (handoff 0024, live in the
map's user-facing copy):

> A vehicle's dot moves only when a new position is reported — Headway never animates a
> guess.

The replay dashboard does not get an exemption. It gets a **distinction**, and the
distinction is the feature:

| | Live map (`/map`, shipped) | Replay dashboard (this design) |
| --- | --- | --- |
| What it is | Observation | **Reconstruction** |
| Between samples | Nothing. Dots jump. | Interpolated path, drawn as such |
| Labeling | "Live — newest position at HH:MM:SS" | Persistent "Reconstructed replay" state |
| Long gaps | Chip states the quiet duration | **Segment breaks, visibly** — never bridged |
| Feeds calculations | Yes (observed positions only) | **Never** |

Three binding rules follow:

1. **Observed samples render differently from reconstructed motion.** The observation is
   a mark; the motion between observations is a trail. A viewer must be able to tell,
   without reading documentation, which pixels are data and which are inference.
2. **Gaps break the trail.** If the interval between two consecutive samples exceeds the
   gap threshold, the path is *split*, not bridged. This is not a nicety: the MBTA
   dataset's tunnel gaps are precisely where a naive dashboard would draw a confident
   straight line through solid rock, and the calc engine already refuses to compute over
   those same gaps (handoff 0004, 122 real gaps). The dashboard must not claim what the
   calculations refuse to claim.
3. **The replay surface is ops-category** (handoff 0014): never certified, never gating
   certification, badged as operational insight. No figure displayed here is a
   submittable number, and nothing computed from an interpolated position may ever reach
   `computed.metric_values`.

The gap threshold is not invented here — it comes from `app.settings` with its basis
citation, like every other threshold (migration 0014, runner-reads-settings wave).

---

## 1. Spatial visualization: deck.gl over the existing MapLibre + PMTiles stack

**License check (ADR-0001 gate):** deck.gl is MIT, `@deck.gl/react` MIT — OSI-clean,
passes. Bundled, never CDN-loaded: the zero-external-requests posture proven in handoff
0027 extends here unconditionally.

### Composition (bottom to top)

| Layer | Source | Purpose | Notes |
| --- | --- | --- | --- |
| MapLibre basemap | self-hosted PMTiles (shipped, 0027) | streets | user-chosen light/dark (0027 follow-up); never theme-coupled |
| `PathLayer` — routes | `GET /geometry/routes` | network context | **schematic** (stop-to-stop) until shapes.txt ingestion; legend says so |
| `TripsLayer` — vehicle trails | replay chunks | the cinematic motion | see gap-splitting below |
| `ScatterplotLayer` — observations | replay chunks | *actual reported positions* | binary attributes; distinct from trail |
| `ScatterplotLayer` / `ColumnLayer` — stations | `GET /geometry/stops` + ops timeline | "ignition" | see below |
| `ScatterplotLayer` — current vehicles | worker output | the playhead's fleet | one draw call, typed arrays |

**One correction to the brief's vocabulary:** this installation has no *tileserver*.
Handoff 0027 ships a single self-hosted **PMTiles archive** read by same-origin byte-range
requests — no tile service, no per-tile HTTP fan-out, nothing to keep running. That is
strictly better for this design: replay hammers the map with camera movement, and a
byte-range read against one static file has no server-side cost to amplify.

Use `MapboxOverlay` in **interleaved** mode so deck layers sit correctly relative to
basemap labels (streets under vehicles, place labels above the basemap but below the
fleet). Interleaved costs a little; the alternative (overlaid) puts deck's canvas above
every label and looks wrong in a dense downtown.

### Gap-splitting: the implementation detail that enforces rule 2

`TripsLayer` interpolates *within* a path — so the honesty work happens at data
preparation, not at render time. In the worker, a vehicle's observation sequence is cut
into **segments** wherever `t[i+1] - t[i] > gapThresholdSeconds`. Each segment becomes
its own path. `TripsLayer` therefore never bridges a gap: it cannot, because the two
sides are different paths. The break is visible as an absence, and a companion
`TextLayer` or the inspector states its duration on demand.

```
observations:  ●——●——●——●        ●——●——●
                              ↑
                   4 min gap: the trail STOPS and RESUMES.
                   Never a straight line drawn through it.
```

### "Station ignition" — earned, not decorative

In the source dashboard nodes ignite as an attacker reaches them. Here, a station
ignites when **something we actually measured** crosses a threshold **we can cite**:

- **headway bunching** — `headway_adherence_v0`'s coefficient of variation of headway
  (live MBTA: 0.3010), TCQSM-quoted definitions in `OPS_DEFINITIONS.md`;
- **on-time performance collapse** — `otp_v0` (live MBTA: 54.10%);
- **observation drought** — no positions passing a stop for longer than expected, which
  is a data-quality finding, not a service finding, and must be labeled as such.

Two consequences that separate this from a pretty dashboard:

1. **Every ignition is clickable to its receipt.** The station glows; you click; you get
   the figure, the calc name and version, the definition quote with its page cite, and
   the lineage back to raw records. Spectacle that survives "prove it."
2. **Ignition thresholds live in `app.settings`** with basis citations, adjustable per
   agency, and shown in the legend. No magic numbers in a shader.

**Performance:** do not recompute ignition per frame in JS. Precompute, in the worker, a
per-station **ignition timeline** (a `Uint8Array` of state per station per time bucket,
plus intensity as a second array). Per frame the main thread slices the bucket for the
current time and hands deck.gl a **binary attribute update** — no per-object iteration,
no `updateTriggers` thrash, no layer recreation. Intensity drives radius and color via
the standard accessors reading from the binary attribute; a pulse effect, if wanted, is
a cheap sine on the time uniform inside a small custom layer extension — and it must be
disabled under `prefers-reduced-motion` (house rule) and must never be the *only* signal
(color/motion alone never carries meaning; the station list carries words).

---

## 2. State management: the master clock

### The rule that decides the architecture

**The clock must not live in React state.** A 60 Hz `setState` is the classic way to
turn a smooth dashboard into a slideshow. Instead:

- `requestAnimationFrame` advances a **mutable ref** (`currentTimeMs`) inside a
  singleton store;
- **deck.gl** receives the raw time on every frame (its own render loop, outside React
  reconciliation) via layer props updated imperatively or by a `useRef`-driven
  `MapboxOverlay.setProps`;
- **React** subscribes through `useSyncExternalStore` with a **quantized selector** —
  text clocks re-render at ~4 Hz, histograms on bucket boundaries, the live stream on
  new rows. Coarse UI never re-renders at frame rate.

### Zustand or XState? — Zustand, plus a small explicit transport union

Recommendation: **Zustand** for the store, and model transport state as an explicit
discriminated union inside it rather than adopting XState.

- The genuinely stateful part (`idle | playing | paused | scrubbing | buffering`) is
  five states with obvious transitions; a hand-written reducer is ~30 lines and fully
  testable.
- XState earns its weight when transitions are numerous, guarded, and business-critical
  (the certification flow would be a candidate). A media transport is not that.
- Zustand's transient-update API (`subscribe` with `getState` outside React) is exactly
  the escape hatch the clock needs, and it is 1 kB.

The store owns: `transport`, `currentTimeMs`, `playbackRate`, `window {t0, t1}`,
`loadedChunks`, `filters` (mode, route, agency), `persona`. Nothing derived is stored —
derived values are computed in the worker or selected at read time.

### Buffering is a first-class state, and it is honest

Scrubbing to an unloaded hour must not silently show an empty map (which reads as "no
service"). `buffering` renders a plain "loading 14:00–15:00" state, and the map holds its
last honest frame rather than clearing. Empty-because-not-loaded and
empty-because-nothing-ran are different facts and must look different — the same
distinction the DQ and empty-state work has been enforcing everywhere else.

---

## 3. Worker architecture

**Why a worker at all:** aggressive scrubbing means re-answering "where was every
vehicle at time T?" tens of times per second over a few million observations. Binary
search per vehicle is cheap individually and ruinous in aggregate on the main thread
next to React.

**Division of labor:**

| Main thread | Worker |
| --- | --- |
| rAF clock, transport state, camera | column store of observations |
| deck.gl draw calls | per-vehicle segment index |
| React UI at quantized rates | position resolution at time T |
| chunk fetch orchestration | ignition timeline precompute |
| | histogram bucket precompute |

**Data shape (worker-side).** Columnar typed arrays, not objects:

```
vehicleIds:   string[]            // index → id, built once
offsets:      Uint32Array         // per-vehicle slice into the sample arrays
times:        Float64Array        // epoch ms, sorted within each vehicle
lons, lats:   Float32Array
segmentIds:   Uint16Array         // gap-split segment membership (rule 2)
```

**Transfer protocol.** The worker posts back **transferables** — `Float32Array`
positions (interleaved x,y), `Uint8Array` status, `Float32Array` age-in-seconds — which
deck.gl consumes directly as binary attributes with zero per-object JS work. Buffers are
recycled (double-buffered) so scrubbing does not allocate per frame.

**Wire format from the server.** JSON is the wrong shape at this volume. Prefer Arrow
IPC or a compact binary chunk; the honest v0 compromise is gzipped columnar JSON
(arrays-of-arrays, not arrays-of-objects) which the worker converts to typed arrays once.
Sizing reality: a 48-vehicle agency producing a ping every 30 s for a 20-hour service day
is ~115k samples — trivial. A 1,000-vehicle agency is ~2.4M samples/day ≈ 30 MB of
typed arrays — fine in memory, but it must arrive in **time-ordered chunks** (15 or 30
minutes each) loaded around the playhead, not as one download.

---

## 4. Audience views

These are not new inventions: the dashboard already shipped **Board / Executive /
Operations** lens presets (handoff 0024), and they are *stated to be lens configurations
only* — they change grouping and emphasis, never a number. The replay dashboard extends
the same vocabulary rather than competing with it.

**Executive.** Macro network health: modal split (bus / light rail / subway as separate
series), the volume histogram as the hero, ignition density rather than individual
stations, hour-scale scrubbing. Cinematic pacing (higher default playback rate, camera
eased between hotspots). Every headline figure still opens its receipt — the reason an
executive can repeat the number in a board meeting without risk.

**Operations.** Dispatch grit: individual vehicles addressable and searchable, the raw
**GTFS-RT live stream** (see below), bottleneck ignition with the specific stop and
route named, minute-scale scrubbing, delay distribution rather than averages. Filters by
mode, route, garage/block. This is the persona the "Live Action Stream" is for — and it
is not decorative: each streamed line carries the raw record id and is clickable to the
raw payload in object storage, which makes the prettiest possible provenance
demonstration.

**Public.** Simplified and smoothed, *and labeled as such*: the public view is where the
temptation to over-smooth is strongest and where honesty matters most, because the
viewer has no way to check. No ignition (it invites misreading as "danger"), no raw
stream, arrival-oriented language, the schematic-geometry caveat kept visible. The
existing `/public` page and its certified-figures-only rule are the precedent.

Persona selection is presentation, not permission: the server enforces roles; the public
surface serves only what the public endpoint already serves.

---

## 5. Implementation sketches

### 5.1 The master clock (React + Zustand)

```ts
// clockStore.ts — the clock lives OUTSIDE React's render cycle on purpose.
import { create } from "zustand";

export type Transport =
  | { kind: "idle" }
  | { kind: "playing" }
  | { kind: "paused" }
  | { kind: "scrubbing" }
  | { kind: "buffering"; needs: [number, number] };

interface ClockState {
  transport: Transport;
  rate: number;                 // 1 = real time; 60 = a minute per second
  window: { t0: number; t1: number };
  /** Frame-rate value. Read via getTime(); NEVER select this into React. */
  timeRef: { current: number };
  tick: (dtMs: number) => void;
  seek: (t: number) => void;
  play: () => void;
  pause: () => void;
}

export const useClock = create<ClockState>((set, get) => ({
  transport: { kind: "idle" },
  rate: 60,
  window: { t0: 0, t1: 0 },
  timeRef: { current: 0 },

  tick: (dtMs) => {
    const s = get();
    if (s.transport.kind !== "playing") return;
    const next = s.timeRef.current + dtMs * s.rate;
    // End of window: stop plainly. No loop-around — a replay that silently
    // restarts misleads anyone who looked away.
    if (next >= s.window.t1) {
      s.timeRef.current = s.window.t1;
      set({ transport: { kind: "paused" } });
      return;
    }
    s.timeRef.current = next;        // mutation, not setState: no re-render
  },

  seek: (t) => {
    const s = get();
    s.timeRef.current = Math.min(Math.max(t, s.window.t0), s.window.t1);
  },
  play:  () => set({ transport: { kind: "playing" } }),
  pause: () => set({ transport: { kind: "paused" } }),
}));
```

```ts
// useMasterClock.ts — one rAF loop for the whole dashboard.
export function useMasterClock(onFrame: (timeMs: number) => void) {
  const raf = useRef<number>();
  const last = useRef<number>();

  useEffect(() => {
    const loop = (ts: number) => {
      const dt = last.current == null ? 0 : ts - last.current;
      last.current = ts;
      useClock.getState().tick(dt);
      onFrame(useClock.getState().timeRef.current);   // → worker + deck.gl
      raf.current = requestAnimationFrame(loop);
    };
    raf.current = requestAnimationFrame(loop);
    return () => {
      if (raf.current) cancelAnimationFrame(raf.current);
      last.current = undefined;
    };
  }, [onFrame]);
}

/** Coarse UI subscribes HERE, quantized — text clocks at ~4 Hz, not 60. */
export function useQuantizedTime(stepMs = 250): number {
  const [t, setT] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => {
      const now = useClock.getState().timeRef.current;
      setT((prev) => (Math.abs(now - prev) >= stepMs ? now : prev));
    }, stepMs);
    return () => window.clearInterval(id);
  }, [stepMs]);
  return t;
}
```

The scrubber itself is an `<input type="range">` — a real one, because keyboard and
screen-reader support come free and this project does not reimplement native controls
(the React Aria precedent). It writes through `seek()`, sets `transport` to `scrubbing`
on pointer-down and restores the prior state on pointer-up.

### 5.2 The position worker (pseudocode, honest about gaps)

```js
// positionWorker.js
let store = null;              // columnar arrays (see §3)
let gapThresholdSec = 300;     // from app.settings, NOT hardcoded at build time
let out = { pos: null, status: null, age: null };   // recycled buffers

onmessage = ({ data }) => {
  switch (data.type) {
    case "init":      store = buildColumnStore(data.chunks);
                      gapThresholdSec = data.gapThresholdSec; break;
    case "chunk":     mergeChunk(store, data.chunk); break;
    case "resolve":   postMessage(...resolveAt(data.timeMs)); break;
  }
};

function resolveAt(t) {
  const n = store.vehicleCount;
  ensureBuffers(n);
  for (let v = 0; v < n; v++) {
    const [lo, hi] = sliceOf(store.offsets, v);
    const i = upperBound(store.times, lo, hi, t);   // last sample at or before t

    if (i < lo) {                       // vehicle has not reported yet today
      out.status[v] = STATUS_ABSENT; continue;
    }
    const tPrev = store.times[i];

    if (i + 1 >= hi) {                  // nothing after t: last known position
      writePos(v, store.lons[i], store.lats[i]);
      out.age[v] = (t - tPrev) / 1000;
      out.status[v] = out.age[v] > gapThresholdSec ? STATUS_STALE : STATUS_OBSERVED;
      continue;
    }

    const tNext = store.times[i + 1];
    const dt = (tNext - tPrev) / 1000;

    if (dt > gapThresholdSec) {
      // RULE 2. We do not know where it went. Hold the last OBSERVED position,
      // mark it stale, and let the renderer draw a broken trail. Interpolating
      // here is exactly the lie this platform exists not to tell.
      writePos(v, store.lons[i], store.lats[i]);
      out.age[v] = (t - tPrev) / 1000;
      out.status[v] = STATUS_GAP;
      continue;
    }

    const f = (t - tPrev) / (tNext - tPrev);        // 0..1 within a SHORT gap
    writePos(v,
      store.lons[i] + f * (store.lons[i + 1] - store.lons[i]),
      store.lats[i] + f * (store.lats[i + 1] - store.lats[i]));
    out.age[v] = 0;
    // Reconstructed — never reported. The renderer styles it as a trail
    // position, and the inspector says "between observations at HH:MM:SS
    // and HH:MM:SS".
    out.status[v] = STATUS_RECONSTRUCTED;
  }
  return [{ pos: out.pos, status: out.status, age: out.age, t },
          [out.pos.buffer, out.status.buffer, out.age.buffer]];   // transferables
}
```

Note what the status vocabulary buys: `OBSERVED`, `RECONSTRUCTED`, `GAP`, `STALE`,
`ABSENT` are five *visually distinct* states, and the legend can name all five in plain
words. That is the whole honesty argument rendered as an enum.

Straight-line interpolation between short-interval samples is itself an approximation
(vehicles follow streets, not great circles). v1 improvement, once shapes.txt ingestion
lands: snap reconstruction to the route geometry. Until then the legend says the trail
is a straight-line reconstruction — one more sentence, no pretending.

---

## 6. Phasing — what must exist first

1. **Retention decision (blocking, Platform Architect).** Replay needs stored history.
   `canonical.vehicle_positions` has it (15M rows live). The GTFS-RT **trip_updates**
   poller is DISABLED pending a retention policy (~1.1 GB/hr normalized, handoff 0014) —
   so prediction-based features (schedule adherence at the playhead) are out of scope
   until that decision lands. Phase 1 is positions-only, and says so.
2. **A replay endpoint.** `GET /ops/vehicles/replay?from&to&bbox&chunk` serving
   time-ordered chunks, columnar, bounded, ops-category envelope, with the same
   truncation honesty as the existing ops endpoints. This is a small backend wave and
   the natural next handoff.
3. **Ignition timelines.** Per-stop ops metrics over time — a calc/API question, not a
   frontend one, and it must reuse `otp_v0` / `headway_adherence_v0` rather than invent
   parallel math.
4. **Then the frontend wave**: deck.gl integration, clock, worker, three personas,
   lazy-loaded so `/today` never pays for it.

Each phase ships with live verification against real agency data, or it does not ship.

## 7. Open questions

- Playback of *yesterday* vs an arbitrary historical window: retention again.
- Multi-agency views (regional TOC) — the tenancy boundary is one database per agency
  (ADR-0004); a cross-agency replay is a different architecture, not a filter.
- Whether the public persona should exist at all in v1, or wait until the ops-vs-public
  language has been reviewed with an agency communications team.
- Recording/export ("share this replay") — attractive for demos, and a provenance
  question the moment it leaves the building.
