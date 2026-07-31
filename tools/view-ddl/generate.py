#!/usr/bin/env python3
"""Generate the SQL Server "view is the contract" pack for one adapter.

Handoff 0037, design point 6. The audience for the OUTPUT is an agency
with no DBA and a process expert who has never typed SQL: everything this
tool emits is meant to be run through SSMS click-paths (the generated
SSMS-CLICK-PATH.md walks every click), and every generated statement
follows the rules learned live with the first partner agency:

  - the view lists every column EXPLICITLY, in the adapter's declared
    order — never SELECT * (ADR-0013 minimization; a column Headway was
    not told about is never read);
  - date/time columns are CONVERTed to text in the view, in exactly the
    format the adapter declares — Headway refuses to invent a date format
    (handoff 0033, design point 6), so the CONVERT is baked in here;
  - the headway_ro login gets SELECT on the one view and nothing else.

The tool itself runs on the Headway side with zero extra install steps
(python3 + PyYAML, both already required by the transform service and the
adapter harness). Its OUTPUT is what travels to the agency.

Usage:
    python3 tools/view-ddl/generate.py adapters/tripspark/streets/mapping.v0.yaml \
        --out /tmp/pack [--view-name dbo.vw_headway_apc] [--login headway_ro] \
        [--cursor-column VehicleLocationAPCKey]

Emits into --out (numbered in the order they are run):
    01-create-view.sql        CREATE VIEW template (FILL_IN markers for the
                              agency's own table/column names)
    02-create-login-and-grant.sql
                              headway_ro login + user + the single grant
    03-verify-view.sql        explicit-column TOP-5 + row count check
    SSMS-CLICK-PATH.md        the numbered zero-SQL walk-through
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - environment guard, said plainly
    sys.exit(
        "PROBLEM: the PyYAML library is not installed, and this tool reads "
        "the adapter mapping spec with it.\nTo fix: python3 -m pip install "
        "pyyaml   (it is already a dependency of services/transform)"
    )

# strftime format (as adapter specs declare it) -> (varchar length,
# SQL Server CONVERT style). Only formats that round-trip EXACTLY are
# listed; an unknown format is a loud refusal below, never a guess —
# a wrong date format would corrupt every row silently (Guardrail 7).
DATETIME_CONVERT = {
    "%Y-%m-%dT%H:%M:%S": (19, 126),  # ISO-8601 with 'T' (style 126)
    "%Y-%m-%d %H:%M:%S": (19, 120),  # ODBC canonical (style 120)
    "%Y-%m-%d": (10, 23),            # ISO date only (style 23)
}

FILL_PREFIX = "FILL_IN_"


def display_path(path: Path) -> str:
    """The spec path as recorded in generated headers: repo-relative when
    the spec lives in a checkout, so the generated pack is byte-identical
    no matter where the tool was invoked from (golden-file stability)."""
    resolved = path.resolve()
    for parent in resolved.parents:
        if (parent / ".git").exists():
            return resolved.relative_to(parent).as_posix()
    return path.as_posix()


def bracket(identifier: str) -> str:
    """Quote a SQL Server identifier; refuse anything that cannot be."""
    if "]" in identifier or not identifier:
        sys.exit(f"PROBLEM: cannot use {identifier!r} as a SQL identifier.")
    return f"[{identifier}]"


def parse_view_name(view_name: str) -> tuple[str, str]:
    parts = view_name.split(".")
    if len(parts) == 1:
        return "dbo", parts[0]
    if len(parts) == 2:
        return parts[0], parts[1]
    sys.exit(
        f"PROBLEM: --view-name must be 'view' or 'schema.view', got {view_name!r}."
    )


def load_spec(path: Path) -> dict:
    try:
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        sys.exit(f"PROBLEM: cannot read the adapter spec: {exc}")
    except yaml.YAMLError as exc:
        sys.exit(f"PROBLEM: the adapter spec is not valid YAML: {exc}")
    if not isinstance(spec, dict):
        sys.exit("PROBLEM: the adapter spec did not parse to a mapping.")
    return spec


def spec_columns(spec: dict, path: Path) -> list[str]:
    try:
        columns = spec["source_format"]["csv"]["columns"]
    except (KeyError, TypeError):
        sys.exit(
            f"PROBLEM: {path} declares no source_format.csv.columns list — "
            "this tool generates views for positional-CSV adapter contracts."
        )
    if not isinstance(columns, list) or not columns:
        sys.exit(f"PROBLEM: {path}: source_format.csv.columns is empty.")
    if len(set(columns)) != len(columns):
        sys.exit(f"PROBLEM: {path}: duplicate column names in the contract.")
    return [str(c) for c in columns]


def datetime_columns(spec: dict) -> dict[str, str]:
    """Source columns the adapter coerces to datetime -> declared format."""
    found: dict[str, str] = {}

    def walk_fields(fields: object) -> None:
        if not isinstance(fields, dict):
            return
        for defn in fields.values():
            if (
                isinstance(defn, dict)
                and defn.get("coerce") == "datetime"
                and isinstance(defn.get("from"), str)
            ):
                fmt = defn.get("format")
                if not isinstance(fmt, str):
                    sys.exit(
                        "PROBLEM: the adapter coerces "
                        f"{defn['from']!r} to datetime without declaring a "
                        "format — the view's CONVERT cannot be generated "
                        "without one, and guessing a date format is refused."
                    )
                found[defn["from"]] = fmt

    walk_fields(spec.get("fields"))
    for emission in spec.get("emit") or []:
        if isinstance(emission, dict):
            walk_fields(emission.get("fields"))
    return found


def select_lines(columns: list[str], dt_cols: dict[str, str]) -> list[str]:
    lines = []
    for i, col in enumerate(columns):
        comma = "," if i < len(columns) - 1 else ""
        target = bracket(col)
        source = bracket(f"{FILL_PREFIX}{col}")
        if col in dt_cols:
            fmt = dt_cols[col]
            if fmt not in DATETIME_CONVERT:
                sys.exit(
                    f"PROBLEM: the adapter declares datetime format {fmt!r} "
                    f"for column {col!r}, and this tool has no exact SQL "
                    "Server CONVERT for it. Add the mapping to "
                    "DATETIME_CONVERT in tools/view-ddl/generate.py — "
                    "guessing a date style is refused."
                )
            length, style = DATETIME_CONVERT[fmt]
            expr = f"CONVERT(varchar({length}), src.{source}, {style})"
            note = f"  -- date as text, exactly '{fmt}'"
        else:
            expr = f"src.{source}"
            note = ""
        lines.append(f"    {expr} AS {target}{comma}{note}")
    return lines


def create_view_sql(
    spec_label: str, spec_path: str, columns: list[str],
    dt_cols: dict[str, str], schema: str, view: str,
) -> str:
    body = "\n".join(select_lines(columns, dt_cols))
    return f"""\
-- =========================================================================
-- 01-create-view.sql — the Headway view: the view is the contract.
-- Generated by tools/view-ddl from {spec_path}
-- (adapter source label: {spec_label}). Do not hand-edit the column list
-- or its order — Headway reads these exact {len(columns)} columns, in this
-- exact order, and refuses anything else (explicit columns only, never
-- the select-everything shorthand).
--
-- BEFORE RUNNING: replace every name that starts with {FILL_PREFIX}
-- with the real name from YOUR vendor database (your vendor's data
-- dictionary has them, or ask your Headway contact). The words after
-- "AS" must NOT be changed — they are the contract.
--
-- Dates and times: Headway refuses to guess date formats, so date/time
-- columns are converted to text HERE, in the view, in the exact format
-- the adapter declares. If any of your other columns is a decimal or
-- float, wrap it in CONVERT(varchar(32), ...) the same way — Headway
-- reports an error naming the column if a raw one slips through.
-- =========================================================================
USE {bracket(FILL_PREFIX + "YOUR_DATABASE_NAME")};
GO

CREATE VIEW {bracket(schema)}.{bracket(view)}
AS
SELECT
{body}
FROM {bracket(FILL_PREFIX + "YourSchema")}.{bracket(FILL_PREFIX + "YourApcTable")} AS src;
GO
"""


def create_login_sql(schema: str, view: str, login: str) -> str:
    return f"""\
-- =========================================================================
-- 02-create-login-and-grant.sql — the read-only account Headway signs
-- in with. Generated by tools/view-ddl.
--
-- BEFORE RUNNING:
--   1. Replace {FILL_PREFIX}YOUR_DATABASE_NAME with your database's name
--      (the same one you used in 01-create-view.sql).
--   2. Replace PASTE_A_NEW_STRONG_PASSWORD_HERE with a NEW strong
--      password. Write it down somewhere safe — it goes into Headway's
--      configuration later, and it is never sent by email.
--
-- What this deliberately does NOT do: no table access, no write access,
-- no admin role. The {login} account can read the one Headway view and
-- nothing else — that is the whole point.
-- =========================================================================
USE [master];
GO

IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'{login}')
    CREATE LOGIN {bracket(login)}
    WITH PASSWORD = N'PASTE_A_NEW_STRONG_PASSWORD_HERE',
         CHECK_POLICY = ON;
GO

USE {bracket(FILL_PREFIX + "YOUR_DATABASE_NAME")};
GO

IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'{login}')
    CREATE USER {bracket(login)} FOR LOGIN {bracket(login)};
GO

GRANT SELECT ON {bracket(schema)}.{bracket(view)} TO {bracket(login)};
GO
"""


def verify_sql(columns: list[str], schema: str, view: str, cursor: str) -> str:
    collist = ",\n    ".join(bracket(c) for c in columns)
    return f"""\
-- =========================================================================
-- 03-verify-view.sql — a read-only check that the view works.
-- Generated by tools/view-ddl. Safe to run any time; it changes nothing.
-- Every column is listed explicitly (never the select-everything
-- shorthand).
-- =========================================================================
USE {bracket(FILL_PREFIX + "YOUR_DATABASE_NAME")};
GO

SELECT TOP (5)
    {collist}
FROM {bracket(schema)}.{bracket(view)}
ORDER BY {bracket(cursor)} DESC;
GO

SELECT COUNT_BIG(*) AS total_rows_in_view
FROM {bracket(schema)}.{bracket(view)};
GO
"""


def click_path_md(
    spec_label: str, columns: list[str], schema: str, view: str,
    login: str, cursor: str,
) -> str:
    return f"""\
# Setting up the Headway view in SSMS — a click-by-click guide

*Generated by `tools/view-ddl` for the `{spec_label}` adapter
({len(columns)} columns, view `{schema}.{view}`, read-only login
`{login}`). Written for someone who has never run SQL — every click is
listed, and nothing here changes your vendor's data. The view is a saved,
named query: your data stays where it is.*

**Time needed: about 20 minutes.** You will run three small files, in
order, and send two confirmations back.

## What you need before starting

1. **SQL Server Management Studio (SSMS)** on a computer that can reach
   your vendor's database server. If you don't have it, your IT contact
   can install it from Microsoft — it is free.
2. **A sign-in that can create views and logins** on that database
   (usually the admin sign-in your vendor set up — your IT contact or
   vendor support knows it).
3. **The three `.sql` files** that came with this guide, and the list of
   your vendor's real column names (your vendor's data dictionary, or ask
   your Headway contact — they will map them with you).

## Step 1 — open SSMS and connect

1. Start **SQL Server Management Studio** (Start menu → type "SSMS").
2. A **Connect to Server** window appears.
   - **Server name:** your database server's name (from your IT contact —
     it often looks like `SERVERNAME\\INSTANCE`).
   - **Authentication:** whatever your admin sign-in uses (ask if unsure).
3. Click **Connect**. The left panel (Object Explorer) fills in.

## Step 2 — run file 01 (create the view)

1. In SSMS click **File → Open → File…** and open
   `01-create-view.sql`.
2. **Fill in the marked names.** Every name that starts with `FILL_IN_`
   must be replaced with the real name from your vendor database — the
   database name, the table name, and one source column per line. Use
   **Edit → Find and Replace** for each. Two rules:
   - Do **not** change anything after the word `AS` on each column line —
     those names are the contract Headway reads.
   - Do **not** run the file while any `FILL_IN_` is still in it (you
     would get a red error naming it — harmless, but nothing happens).
3. Press **F5** (or click **Execute**).
4. **What you should see:** the message pane at the bottom says
   `Commands completed successfully.`
5. **If you see red error text instead:** nothing was broken — copy the
   whole message (right-click → Select All → Copy) and send it to your
   Headway contact. Do not retype it; the exact words matter.

## Step 3 — run file 02 (create Headway's read-only sign-in)

1. **File → Open → File…** → `02-create-login-and-grant.sql`.
2. Replace `FILL_IN_YOUR_DATABASE_NAME` (same database name as before).
3. Replace `PASTE_A_NEW_STRONG_PASSWORD_HERE` with a **new** strong
   password. Write it down somewhere safe — Headway's configuration
   needs it later. **Never email a password**; hand it over by phone or
   your password manager.
4. Press **F5**. Expect `Commands completed successfully.`

This sign-in can read the one Headway view and nothing else — it cannot
change data, and it cannot see your other tables.

## Step 4 — run file 03 (prove it works) and send the results back

1. **File → Open → File…** → `03-verify-view.sql`, replace
   `FILL_IN_YOUR_DATABASE_NAME`, press **F5**.
2. **What you should see:** a small grid with up to 5 rows of data, and
   below it a single number (`total_rows_in_view`).
3. Send the result back: right-click anywhere in the results grid →
   **Save Results As…** → save as a `.csv` file → send that file to your
   Headway contact together with the two `Commands completed
   successfully.` confirmations, the database name, and the server name.
   (Never send a password this way.)

> **Warning — do not open the CSV in Excel before sending it.** Opening
> a CSV in Excel and saving it silently rewrites dates into Excel's own
> format and strips leading zeros (a stop code `0042` becomes `42`) —
> the file looks fine on screen and is quietly different on disk. Send
> the file exactly as SSMS saved it; if you want to peek, use Notepad,
> or look at a copy.

## What happens next

Your Headway contact wires the Headway side to read the view (the
`SQLSOURCE_*` lines in `deploy/compose/.env`, using the `{login}`
password you set and `{cursor}` as the cursor column) and confirms data
is flowing end to end. From then on, when your vendor upgrades and
renames its internals, only the view needs editing — repeat Step 2 with
the new names; nothing on the Headway side changes. The view is the contract.
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate the SQL Server view-is-the-contract pack "
        "(view DDL + read-only login + SSMS click-path) from an adapter "
        "mapping spec."
    )
    parser.add_argument("spec", type=Path, help="adapter mapping.v0.yaml")
    parser.add_argument("--out", type=Path, required=True,
                        help="directory to write the pack into")
    parser.add_argument("--view-name", default="dbo.vw_headway_apc",
                        help="view name (default: dbo.vw_headway_apc)")
    parser.add_argument("--login", default="headway_ro",
                        help="read-only login name (default: headway_ro)")
    parser.add_argument("--cursor-column", default=None,
                        help="the ever-growing key column (default: the "
                        "adapter's first declared column)")
    args = parser.parse_args()

    spec = load_spec(args.spec)
    columns = spec_columns(spec, args.spec)
    dt_cols = datetime_columns(spec)
    label = str(spec.get("source_label") or
                f"{spec.get('vendor', '?')}_{spec.get('product', '?')}")
    schema, view = parse_view_name(args.view_name)
    cursor = args.cursor_column or columns[0]
    if cursor not in columns:
        sys.exit(
            f"PROBLEM: --cursor-column {cursor!r} is not one of the "
            f"adapter's declared columns: {', '.join(columns)}"
        )

    args.out.mkdir(parents=True, exist_ok=True)
    spec_path = display_path(args.spec)
    files = {
        "01-create-view.sql": create_view_sql(
            label, spec_path, columns, dt_cols, schema, view),
        "02-create-login-and-grant.sql": create_login_sql(
            schema, view, args.login),
        "03-verify-view.sql": verify_sql(columns, schema, view, cursor),
        "SSMS-CLICK-PATH.md": click_path_md(
            label, columns, schema, view, args.login, cursor),
    }
    for name, content in files.items():
        (args.out / name).write_text(content, encoding="utf-8")
        print(f"wrote {args.out / name}")
    print(
        f"\nPack generated for adapter '{label}': {len(columns)} explicit "
        f"columns, {len(dt_cols)} date/time CONVERT(s), login "
        f"'{args.login}' with SELECT on {schema}.{view} only.\n"
        "Hand the whole folder to the agency; SSMS-CLICK-PATH.md is the "
        "document they follow."
    )


if __name__ == "__main__":
    main()
