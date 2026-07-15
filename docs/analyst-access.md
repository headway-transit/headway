# Analyst access — notebooks, BI tools, and read-only SQL

Headway meets your planning and data teams where they already work: Python
notebooks, BI tools, spreadsheets, SQL. This page is for the person setting
that access up (an administrator) and the person using it (an analyst).
Nothing here requires programming beyond copying commands.

First, the promise that makes this safe to hand out:

> Explore and compute freely: nothing computed outside Headway's calculation
> library (services/calc) can ever become a reported figure. Only the
> calculation library writes computed.metric_values, and the walls are
> structural database CHECKs, not policy.

An analyst with the access on this page can read, join, model, and chart
anything they are given — and none of it can flow back into what the agency
reports. Reported figures originate in exactly one place (the deterministic,
versioned calculation library), every figure carries its provenance, and the
database itself refuses the forbidden states (for example, a certified
operations metric is impossible to even represent). Analyst access is
read-only twice over: the API surfaces are reads, and the SQL role below
cannot write a single row.

There are two doors. Most analysts want the first.

## Door 1 — the API, with the Python client

The `headway-client` Python library ([clients/python/](../clients/python/))
wraps the same API the Headway web app uses. Analysts get typed results,
exact decimal figures (never floating point), DataFrame helpers whose
provenance columns are always present, and `walk_lineage()` — the full trail
from any figure down to the raw records that produced it. Worked, executed
examples live in [notebooks/](../notebooks/).

**Administrator: issue the analyst a machine API key.** Sign in as a
certifying official and create a key with the `read:metrics` permission —
in the web app under machine keys, or from a terminal on the Headway
computer:

```sh
# 1) Sign in (you will be asked nothing else; the token lasts 30 minutes)
TOKEN=$(curl -s http://127.0.0.1:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username": "YOUR_ADMIN_USERNAME", "password": "YOUR_ADMIN_PASSWORD"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

# 2) Issue the key — name it after the person or team that will hold it
curl -s http://127.0.0.1:8000/machine/keys \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name": "Planning team — Maria", "scopes": ["read:metrics"]}'
```

The answer contains the key (it starts with `hwk_`) **exactly once** —
Headway keeps only a hash and can never show it again. Hand it to the
analyst the way you would hand over a password. If it is ever lost or the
person leaves, revoke it (`DELETE /machine/keys/{key_id}` or the web app)
and issue a new one; every use of every key is audit-logged.

**Analyst: use it.**

```sh
pip install './clients/python[pandas]'   # from a checkout of this repository
```

```python
from headway_client import HeadwayClient, frames

hw = HeadwayClient("http://127.0.0.1:8000", token="hwk_…")
df = frames.metric_values_frame(hw.metric_values())
trail = hw.walk_lineage(df.metric_value_id[0])   # figure → raw records
```

No key at all still reaches one endpoint: the public open-data feed of
certified figures, `GET /public/metrics/certified` —
`HeadwayClient(...).public_certified()`.

Two API surfaces (metric comparison and the data-quality issue list)
currently accept only a signed-in Headway account, not a machine key. The
client says so honestly in those methods; `headway_client.login()` gets a
session token from an account an administrator creates in the usual way.

## Door 2 — read-only SQL (`headway_readonly`)

For DBeaver, `psql`, R, or `pandas.read_sql`, Headway ships a read-only
database role (migration `db/migrations/0028_readonly_analyst_role.sql`).
It is deliberately least-privilege:

| The role can read | The role can never touch |
| --- | --- |
| `canonical.*` — the normalized transit data (one exception below) | `auth.*` — accounts, key hashes, webhook secrets |
| `canonical.dr_trips` operational columns (times, distances, counts, flags) | `dr_trips` pickup/dropoff **coordinates** — precise paratransit locations are effectively rider home addresses; location-level analysis goes through the application's authorized roles |
| `computed.*` — every computed figure, with provenance | `audit.*`, `cert.*` — audit trail and certification records |
| `lineage.*` — the graph that explains every figure | `app.*` — operator settings |
| `dq.*` — the data-quality workflow | `safety.*`, `sampling.*` — free-text that can name people |
| `raw.records` metadata columns (id, source, connector, timestamps, parse status) | raw payload pointers and parser output; and it can **write nothing, anywhere** |

`headway_readonly` itself cannot log in — it is a bundle of permissions. The
administrator creates one login user **per person**, so access is
individually revocable and attributable:

**Administrator: create an analyst's database login.** On the Headway
computer, from the Headway folder (you will be asked to invent a strong
password for the analyst — use a password manager):

```sh
docker compose --project-directory deploy/compose exec timescaledb \
  psql -U headway -d headway -c \
  "CREATE USER maria WITH LOGIN PASSWORD 'PASTE_A_STRONG_PASSWORD_HERE' IN ROLE headway_readonly;"
```

To remove that access later, the same way:

```sh
docker compose --project-directory deploy/compose exec timescaledb \
  psql -U headway -d headway -c "DROP USER maria;"
```

(If your `deploy/compose/.env` uses a different `POSTGRES_USER`/`POSTGRES_DB`
than the default `headway`, use those names after `-U` and `-d`.)

**Analyst: connect.** The database answers only on the Headway computer
itself, at `127.0.0.1:5432`, database `headway`.

- **psql:** `psql "postgresql://maria@127.0.0.1:5432/headway"` (it prompts
  for the password).
- **DBeaver:** New connection → PostgreSQL → host `127.0.0.1`, port `5432`,
  database `headway`, your username and password. Read-only is enforced by
  the server, but ticking DBeaver's "read-only connection" box too is good
  manners.
- **pandas:**

  ```python
  import pandas as pd
  from sqlalchemy import create_engine

  engine = create_engine("postgresql+psycopg://maria:…@127.0.0.1:5432/headway")
  figures = pd.read_sql(
      """
      SELECT metric, period_start, period_end, scope, value::text AS value,
             calc_name, calc_version, category, certification_status,
             metric_value_id
      FROM computed.metric_values
      ORDER BY period_start, metric
      """,
      engine,
  )
  ```

  Note the `value::text` — figures are exact `NUMERIC`s; casting to text (or
  reading with a Decimal-aware driver) keeps them exact, while letting a
  tool coerce them to floating point is how reported numbers grow rounding
  errors. The API client does this correctly for you, which is one more
  reason Door 1 is the default recommendation.

**Not at the Headway computer?** Use an SSH tunnel, exactly like the one in
[network-access.md](network-access.md) (same steps, one more port): forward
source port `5432` to destination `localhost:5432`, then connect your tool
to `127.0.0.1:5432` as above. One person, one encrypted connection, nothing
opened for anyone else.

## Never expose the database to the internet

The same posture as [network-access.md](network-access.md), and it is not
negotiable: PostgreSQL's port `5432` stays loopback-only, is deliberately
absent from the office-access (`lan`) doorway, and must never be
port-forwarded on a router. It holds your agency's entire operating record.
If several analysts need SQL access from their desks, that is the
hand-this-page-to-IT path: a VPN, or IT-managed access on infrastructure
they watch — never a hole to the world. The API door (with its per-key
audit trail and rate limits) is the right default for anything beyond your
own building.

## Where to go next

- Worked examples with real output: [notebooks/](../notebooks/)
- The client library itself: [clients/python/README.md](../clients/python/README.md)
- Getting your data *into* Headway: [connecting-your-data.md](connecting-your-data.md)
- Sizing a box that also serves analysts: [sizing.md](sizing.md)
