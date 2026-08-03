"""The reported-dataset registry: what this agency reports, and whether it arrived.

From the partner agency's ITS manager (2026-08-03), whose NTD certification
framework opened with an ownership matrix — dataset, owner, system of record,
frequency, NTD form — and the right instinct behind it: treat certification
like a financial audit rather than a data upload.

WHY THIS ENDPOINT DOES TWO THINGS AT ONCE. A registry that only listed what
somebody typed would be a spreadsheet with extra steps. What makes it worth
building is that Headway already knows what actually ARRIVED: ``raw.records``
carries every landed record with its source label, and ``GET /sources/status``
already derives freshness from those same rows. So every dataset is served
with its DECLARED cadence beside its OBSERVED last arrival, and the gap
between them is a finding nobody has to remember to look for.

THREE STATES, NEVER COLLAPSED:

- **overdue** — a cadence was declared, a source is linked, and nothing has
  arrived within it. Actionable, and the only state that means something is
  wrong.
- **not_received** — the agency reports this dataset and Headway holds no
  source for it at all. NOT an error: the ITS manager's own matrix had an
  "eventually" section (fleet inventory, operating expenses, employee counts)
  that no system feeds today. Saying so plainly is the point.
- **no_cadence** — a source is linked but no expected interval was declared,
  so "late" has no meaning. We do not infer one from arrivals: inferring
  cadence from observed data makes a broken feed look correct by redefining
  normal around its own failure.

Anything else is **current**.

NOTHING HERE IS SEEDED. Every row is an agency fact — their departments, their
vendors, their forms. An ownership matrix that is subtly wrong is worse than
an absent one, because it sends someone to the wrong department mid-filing.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..audit import write_event
from ..auth import Identity
from ..authz import require_authenticated, require_certifying_official
from ..db import get_db

router = APIRouter(tags=["datasets"])

UTC = dt.timezone.utc

_COLUMNS = (
    "dataset_key, display_name, owner, system_of_record, "
    "expected_interval, ntd_forms, headway_sources, notes, "
    "updated_by, updated_at"
)

_SELECT_DATASETS = f"SELECT {_COLUMNS} FROM app.reported_datasets"

#: Newest landed record per source label — the OBSERVED half. Deliberately the
#: same table GET /sources/status reads, so the registry and the sources
#: screen can never disagree about when something last arrived.
_SELECT_LAST_SEEN = (
    "SELECT source, max(landed_at) FROM raw.records "
    "WHERE source = ANY(%s) GROUP BY source"
)

_UPSERT = (
    "INSERT INTO app.reported_datasets (dataset_key, display_name, owner, "
    "system_of_record, expected_interval, ntd_forms, headway_sources, notes, "
    "updated_by, updated_at) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now()) "
    "ON CONFLICT (dataset_key) DO UPDATE SET "
    "display_name = EXCLUDED.display_name, owner = EXCLUDED.owner, "
    "system_of_record = EXCLUDED.system_of_record, "
    "expected_interval = EXCLUDED.expected_interval, "
    "ntd_forms = EXCLUDED.ntd_forms, "
    "headway_sources = EXCLUDED.headway_sources, notes = EXCLUDED.notes, "
    "updated_by = EXCLUDED.updated_by, updated_at = now() "
    "RETURNING updated_at"
)

_DELETE = (
    "DELETE FROM app.reported_datasets WHERE dataset_key = %s "
    "RETURNING display_name"
)

REGISTRY_NOTE = (
    "This list is your agency's own record of what you report, who owns it, "
    "and which system it comes from. Headway never fills it in for you: an "
    "ownership matrix that is subtly wrong is worse than an empty one, "
    "because it sends someone to the wrong department in the middle of a "
    "filing. Where a dataset names a source Headway receives, the 'last "
    "received' column is measured from the records themselves — not from "
    "anything typed here."
)


class ReportedDataset(BaseModel):
    dataset_key: str
    display_name: str
    owner: str
    system_of_record: str
    #: Whole seconds, or null when no cadence is declared. Seconds rather than
    #: a phrase so a caller can compare it without parsing English.
    expected_interval_seconds: Optional[int] = None
    ntd_forms: list[str] = []
    headway_sources: list[str] = []
    notes: Optional[str] = None
    updated_by: str
    updated_at: dt.datetime

    #: OBSERVED, from raw.records — never from this table.
    last_received_at: Optional[dt.datetime] = None
    #: 'current' | 'overdue' | 'not_received' | 'no_cadence'. Distinct states
    #: on purpose; see the module docstring.
    arrival_state: str
    #: Plain language for the state, so every screen says the same thing.
    arrival_note: str


class DatasetPage(BaseModel):
    datasets: list[ReportedDataset]
    registry_note: str = REGISTRY_NOTE


class UpsertDatasetRequest(BaseModel):
    display_name: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    system_of_record: str = Field(min_length=1)
    expected_interval_seconds: Optional[int] = Field(default=None, gt=0)
    ntd_forms: list[str] = []
    headway_sources: list[str] = []
    notes: Optional[str] = None


def _arrival(
    expected_seconds: Optional[int],
    sources: list[str],
    last_seen: Optional[dt.datetime],
    now: dt.datetime,
) -> tuple[str, str]:
    """The three not-wrong states, and the one that is."""
    if not sources:
        return (
            "not_received",
            "Headway does not receive this dataset yet. That is recorded on "
            "purpose — it is a gap in coverage, not a fault.",
        )
    if last_seen is None:
        return (
            "not_received",
            "This dataset names a source, but no records have ever arrived "
            "under it. Check the source name against Data sources.",
        )
    if expected_seconds is None:
        return (
            "no_cadence",
            "Records are arriving. No expected frequency is declared, so "
            "Headway cannot say whether they are late — set one to be told.",
        )
    age = (now - last_seen).total_seconds()
    if age > expected_seconds:
        return (
            "overdue",
            f"Expected every {_humanize(expected_seconds)}, but the newest "
            f"record arrived {_humanize(int(age))} ago.",
        )
    return (
        "current",
        f"Arriving as expected — newest record {_humanize(int(age))} ago, "
        f"within the declared {_humanize(expected_seconds)}.",
    )


def _humanize(seconds: int) -> str:
    """A duration in the words an operator uses. Never a bare number."""
    if seconds < 90:
        return f"{max(seconds, 0)} seconds"
    minutes = seconds // 60
    if minutes < 90:
        return f"{minutes} minutes"
    hours = minutes // 60
    if hours < 48:
        return f"{hours} hours"
    return f"{hours // 24} days"


@router.get("/datasets", response_model=DatasetPage)
def list_datasets(
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> DatasetPage:
    """The agency's reported-dataset registry, with observed arrival.

    Readable by any signed-in role: knowing what the agency reports and who
    owns it is orientation, not privilege.
    """
    rows = db.execute(_SELECT_DATASETS + " ORDER BY display_name").fetchall()
    wanted = sorted({s for r in rows for s in (r[6] or [])})
    last_seen: dict[str, dt.datetime] = {}
    if wanted:
        for source, seen in db.execute(_SELECT_LAST_SEEN, (wanted,)).fetchall():
            last_seen[source] = seen

    now = dt.datetime.now(UTC)
    out: list[ReportedDataset] = []
    for r in rows:
        sources = list(r[6] or [])
        # The FRESHEST of a dataset's sources: one arriving feed means the
        # dataset is arriving, and reporting the stalest would call a healthy
        # dataset overdue because a second, optional feed is quiet.
        seen = max((last_seen[s] for s in sources if s in last_seen), default=None)
        interval = r[4]
        expected = int(interval.total_seconds()) if interval is not None else None
        state, note = _arrival(expected, sources, seen, now)
        out.append(
            ReportedDataset(
                dataset_key=r[0],
                display_name=r[1],
                owner=r[2],
                system_of_record=r[3],
                expected_interval_seconds=expected,
                ntd_forms=list(r[5] or []),
                headway_sources=sources,
                notes=r[7],
                updated_by=r[8],
                updated_at=r[9],
                last_received_at=seen,
                arrival_state=state,
                arrival_note=note,
            )
        )
    return DatasetPage(datasets=out)


@router.put("/datasets/{dataset_key}", response_model=ReportedDataset)
def upsert_dataset(
    dataset_key: str,
    body: UpsertDatasetRequest,
    identity: Identity = Depends(require_certifying_official),
    db=Depends(get_db),
) -> ReportedDataset:
    """Record or update one dataset. Certifying official only, and audited.

    Same authority as the policy settings: this registry says who is
    accountable for a federal figure's inputs, and that is not a note anyone
    should be able to change unattributed.
    """
    key = dataset_key.strip()
    if not key:
        raise HTTPException(
            status_code=422,
            detail="A dataset needs a short key, like 'ridership'.",
        )
    interval = (
        dt.timedelta(seconds=body.expected_interval_seconds)
        if body.expected_interval_seconds is not None
        else None
    )
    with db.transaction():
        db.execute(
            _UPSERT,
            (
                key,
                body.display_name,
                body.owner,
                body.system_of_record,
                interval,
                body.ntd_forms,
                body.headway_sources,
                body.notes,
                identity.username,
            ),
        ).fetchone()
        write_event(
            db,
            actor=identity.username,
            action="reported_dataset_recorded",
            subject_kind="app.reported_datasets",
            subject_id=key,
            detail={
                "display_name": body.display_name,
                "owner": body.owner,
                "system_of_record": body.system_of_record,
                "expected_interval_seconds": body.expected_interval_seconds,
                "ntd_forms": body.ntd_forms,
                "headway_sources": body.headway_sources,
            },
        )
    page = list_datasets(identity=identity, db=db)
    for entry in page.datasets:
        if entry.dataset_key == key:
            return entry
    raise HTTPException(  # pragma: no cover — the row was just written
        status_code=500,
        detail="The dataset was saved but could not be read back.",
    )


@router.delete("/datasets/{dataset_key}")
def delete_dataset(
    dataset_key: str,
    identity: Identity = Depends(require_certifying_official),
    db=Depends(get_db),
) -> dict:
    """Remove a dataset from the registry. Audited like every other change."""
    with db.transaction():
        row = db.execute(_DELETE, (dataset_key,)).fetchone()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"'{dataset_key}' is not in the dataset registry, so "
                    f"there is nothing to remove."
                ),
            )
        write_event(
            db,
            actor=identity.username,
            action="reported_dataset_removed",
            subject_kind="app.reported_datasets",
            subject_id=dataset_key,
            detail={"display_name": row[0]},
        )
    return {"dataset_key": dataset_key, "removed": True}
