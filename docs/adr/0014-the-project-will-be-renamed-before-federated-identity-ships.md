# ADR-0014: The Project Will Be Renamed Before Federated Identity Ships

- Status: Accepted — **the name is RouteSight** (chosen 2026-08-02)
- Date: 2026-08-02
- Deciders: Founding Architect (Headway)

## Context and Problem Statement

"Headway" is the correct transit word for the interval between vehicles, which is
why it was chosen. It is also, for the same reason, a crowded one.

The collision that forced the decision is specific and material:
**`headwaymaps/headway`** — "Self-hostable maps stack, powered by OpenStreetMap",
~2,955 stars, actively maintained. It is not a distant homonym in an unrelated
industry. It is an open-source, self-hostable, OpenStreetMap-based project, and
this project ships a self-hosted OpenStreetMap basemap (handoff 0027, MapLibre +
PMTiles). The two will be searched for by the same people, in the same terms, on
the same day.

The confusion is no longer hypothetical. A GitHub identity check during the
identity wave surfaced an unrelated account against `headway-stewards`, and the
question "have we run into a collision?" had to be asked and answered. That is
the cost of a descriptive name arriving before anyone was looking.

Two further facts set the deadline rather than merely the direction:

- **Descriptive marks are the weakest and most contested class of trademark.**
  "Headway" describes a property of the thing being measured. Distinctive marks
  in this market — Vanta, Drata, Stripe, Figma — are arbitrary precisely because
  arbitrary marks are ownable and descriptive ones are not.
- **Federated identity is where a name stops being cheap to change.** Once an
  agency has configured an OIDC client, a redirect URI, a group-claim mapping and
  a support contract against a name, changing it means editing a directory the
  agency's IT department controls and this project does not.

## Decision Drivers

- The cost of a rename rises monotonically and steps sharply at each external
  integration; it is near its lifetime minimum today.
- A name is a career-length commitment for the founder, not a sprint deliverable.
  Forcing it to unblock a weekend is how projects end up with a name they explain
  rather than one they say.
- Nothing currently shipped is blocked by the name. Two waves were sitting
  unmerged while the naming discussion ran, which is the wrong ratio.
- Namespace availability is a weak signal and was initially over-weighted here
  (see Follow-ups). Trademark class and active commercial use are the real gates.

## Considered Options

- **Rename before federated identity reaches a customer directory; choose the
  name deliberately, not on a deadline** (chosen)
- Rename immediately, picking from the first shortlist — rejected: the shortlist
  was screened on a flawed availability method, and picking under time pressure
  is how the current problem was created.
- Keep "Headway" and differentiate by qualified org name — rejected: it concedes
  every search result and every trademark argument to an incumbent, permanently,
  in exchange for avoiding one week of mechanical work.
- Defer indefinitely — rejected: the cost only rises, and the first agency to
  integrate its IdP sets it.

## Decision Outcome

**The project will be renamed to RouteSight.**

Why RouteSight, in the words of the tests this project already applies:

- **It names the benefit, not the labor.** "Runcut" was rejected for describing
  what the software does internally. "Sight" is what the user gets: the ability
  to see what a reported number is made of. This product does not plan routes —
  it lets you look through one.
- **"Sight" carries oversight.** The primary artifacts here are receipts,
  lineage walks, an audit trail and a certification ceremony. A name meaning
  *to see clearly* is the argument, not decoration on it.
- **"Route" is transit-correct and cannot be misread** — unlike "Course",
  which reads as education, and unlike "Strides", which reads as walking.
- **It survives a phone call.** No silent letter, no "is that with a Z", no
  "Valley or Volly" — the failure modes that disqualified Stridez and dogged
  ValiRoute.
- **It is not sitting on top of anyone.** GitHub, PyPI and npm are all free;
  `routesight.com` is held by a domain reseller rather than a company; `.io`
  and `.co` are unregistered.

Its honest weakness, recorded rather than glossed: **`-Sight` is a common
analytics suffix** (Insight, FleetSight, DataSight), so it leans descriptive
and is moderately crowded. Less crowded than "Headway", and not competing with
an established project in the same search results.

Binding conditions:

1. **Deadline: before federated identity is configured against any external
   directory outside this repository's own test environment.** Handoff 0046
   ships the relying party; the deadline is the first *customer* IdP, not the
   first commit.
2. **`ValiRoute` is the recorded runner-up.** More distinctive as a coinage,
   but it sits in the most crowded prefix pool in compliance (Verisign,
   Veritas, Validere, Valimail) and is harder to say and spell. Kept here so
   that if RouteSight fails clearance, the next step does not start over.
3. **RouteSight is not yet cleared for public use.** What was run is a
   registry, domain and web-presence screen. **Screening is not clearance.**
   A trademark search of the relevant classes must precede any public use of
   the name — the announcement, the repository rename, the package names.
   Until then this ADR records a decision, not a right.
4. **Disqualification is recorded with its reason**, so no candidate is
   relitigated (see below).
5. **The rename must not require a customer to edit their identity provider.**
   The identity wave already honors this: no group name is hardcoded, defaulted
   or seeded, and the group claim name is configured rather than assumed
   (handoff 0046). Every subsequent wave inherits the constraint.

### Disqualified, with reasons

| Candidate | Why it is out |
| --- | --- |
| Headway | Collides with an active, popular, self-hostable OSM project in the same search space; descriptive, therefore weak as a mark |
| Waybill | Archaic — reads as 19th-century freight, not software |
| Runcut | Correct to a scheduler, harsh to everyone else; names the labor, not the benefit |
| Kinetik | Active NEMT company in adjacent transit |
| TrueLane | Held by a large insurer in vehicle telematics |
| Attesta, Certra | Active GRC / audit platforms |
| Pulse, Kadence | Heavily used; Kadence is an existing brand |
| VeriCourse, ValiCourse | "Course" reads as education, not transit; `Veri-`/`Vali-` is the most crowded prefix in compliance |
| Strides | Large listed company; "strides" implies walking |
| Stridez | Permanent spelling ambiguity; reads dated |
| NextStop | Common phrase, weak as a mark |
| LucidRoute | "Lucid" is taken twice, and both land badly here: Lucid Motors is a *vehicle* company, which makes the association closer rather than safer, and Lucid Software (Lucidchart) is already in the buyer's SaaS stack. Semantically ideal for a provenance product, which is exactly the trap "Headway" fell into |

### Consequences

- Good — the decision is made and dated, so it stops being reopened, while the
  choice stays open long enough to be made well.
- Good — engineering is unblocked immediately; the name does not gate any wave.
- Bad / cost — every day the old name stays, more artifacts carry it: the
  repository, the Bluesky handle `@headway-transit.bsky.social`, `docs/announce/`,
  README badges, the Docker image names, `services/*` package names, the Python
  client on PyPI. The rename checklist grows and is not free.
- Bad / cost — the name appears in published announcement threads that cannot be
  silently rewritten. A rename will need a public, plainly-worded post rather
  than a quiet edit.

### Follow-ups

- **Correct the record on the earlier availability screen.** `GET
  /orgs/{name}` returns 404 for GitHub *user* accounts, and GitHub shares one
  namespace between users and orgs — so the first sweep reported names as free
  that were taken. Every candidate screened that way must be rechecked with
  `/users/{name}`, and bare-handle availability must be treated as a weak signal:
  a qualified org name (`headway-transit`, not `headway`) has always been the
  actual pattern, and compound org names are plentiful.
- **Run the trademark search for RouteSight in the relevant classes before any
  public use.** This is the gate on everything below it.
- Write the mechanical rename checklist — repository and org, Docker image
  names, `services/*` and `headway_api`/`headway_calc` package names, the
  Python client on PyPI, the Bluesky handle, README badges, `docs/announce/`,
  and the installer's user-facing strings — so the work is a list rather than a
  discovery exercise.
- **Register the domains before the name is used anywhere public.**
  `routesight.com` is held by a reseller; `.io` and `.co` are unregistered as
  of 2026-08-02 and will not stay that way once the name is spoken in public.
- Plan the announcement. The old name is in published Bluesky threads that
  cannot be silently rewritten; the rename gets a plainly-worded post saying
  what changed and why, not a quiet edit.
