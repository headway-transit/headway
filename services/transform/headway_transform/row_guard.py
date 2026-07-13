"""Per-row CSV parse guards shared by the CSV/GTFS normalizers.

The 2026-07-13 hardening reviews reproduced three parser-level ways one
crafted row could corrupt a whole file's normalization:

1. **Oversized field** — ``csv`` raises ``_csv.Error("field larger than
   field limit (131072)")`` mid-iteration, which aborted the entire batch.
   ``iter_rows`` catches the error per row and keeps iterating (verified on
   CPython 3.12: the reader resumes cleanly at the next record), so ONE bad
   row becomes ONE quarantine finding and every other row still lands.
2. **NUL byte in a cell** — ``csv`` passes ``\\x00`` through silently, and
   PostgreSQL then rejects the INSERT, aborting the batch. ``field_problems``
   rejects the row at field level BEFORE anything reaches the database.
3. **Stray/unterminated quote** — ``csv`` (non-strict) silently absorbs
   every following line into one quoted field, swallowing rows without a
   trace. ``field_problems`` detects the absorption (a field spanning
   physical lines — none of the wire contracts carries multi-line values)
   and quarantines the row with a finding that COUNTS the absorbed span.

Every detection becomes a DQ finding in the caller — a row is quarantined,
never silently dropped (Shared Constraint 7), and one row's defect can no
longer abort its file's batch.
"""

from __future__ import annotations

import csv
from typing import Iterator, Optional

#: Per-field character budget. Matches the stdlib csv default field size
#: limit (131072), kept as an explicit policy number so the quarantine
#: finding can name it.
MAX_FIELD_CHARS = 131072


def iter_rows(
    reader: "csv.DictReader",
) -> Iterator[tuple[int, Optional[dict], Optional[str]]]:
    """Iterate a csv.DictReader with per-row parse-error capture.

    Yields ``(index, row, None)`` for parseable rows and
    ``(index, None, error_text)`` when the csv module raises mid-iteration
    (e.g. a field over the field size limit) — the caller quarantines that
    row and iteration CONTINUES with the next record instead of aborting
    the file.
    """
    index = 0
    while True:
        try:
            row = next(reader)
        except StopIteration:
            return
        except csv.Error as exc:
            yield index, None, str(exc)
        else:
            yield index, row, None
        index += 1


def field_problems(row: dict, max_field_chars: int = MAX_FIELD_CHARS) -> list[str]:
    """Field-level defects that must quarantine the row (see module doc).

    Checks every parsed field for NUL bytes, absorbed-line merges (an
    unterminated quote swallowing following rows), and oversized values.
    Returns plain-language problem strings; empty list means the row is
    structurally sound (contract semantics are the caller's business).
    """
    problems: list[str] = []
    for name, value in row.items():
        # csv.DictReader puts extra unnamed columns under key None as a
        # list; normalize both shapes.
        label = name if name is not None else "<extra unnamed column>"
        values = value if isinstance(value, list) else [value]
        for item in values:
            if item is None:
                continue
            if "\x00" in item:
                problems.append(
                    f"field {label!r} contains a NUL byte (0x00), which "
                    "cannot be stored as text; row quarantined before it "
                    "could abort the database batch"
                )
            if "\n" in item or "\r" in item:
                absorbed = item.count("\n") or item.count("\r")
                problems.append(
                    f"field {label!r} spans {absorbed + 1} physical lines — "
                    "an unterminated/stray quote absorbs following rows "
                    f"into one field; {absorbed} absorbed line(s) are "
                    "quarantined with this row, never silently swallowed"
                )
            if len(item) > max_field_chars:
                problems.append(
                    f"field {label!r} is {len(item)} characters, over the "
                    f"{max_field_chars}-character field limit"
                )
    return problems
