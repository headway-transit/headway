"""Static checks on install/install.sh — the front door, and the least tested.

The installer is 3,496 lines and is the ONE path every first-time operator
takes, including every stranger who tries this project because it is open
source. Nothing automated has ever run it, and on 2026-08-02 the first cold
machine install found out what that costs:

``write_access_env`` added the ``app`` compose profile only inside the ``lan``
branch, so the DEFAULT access mode ('local') and the 'it' mode brought up the
database, message queue, object storage and dashboards — and no Headway. No
website, no API, no feed collector. The installer then reported "All services
are healthy" (true of the ones it started), printed "Only web browsers on this
machine can reach it", and exited 0.

WHAT THIS FILE IS, AND IS NOT
-----------------------------
These are static assertions over the script's text. They are cheap, they need
no Docker, and they would have caught the specific defect above. They are NOT
a substitute for running the installer: the real regression test is a smoke
job that installs onto a throwaway machine and then asks the API for a 200.
That job does not exist yet and is the honest follow-up — a static check can
only prove a line is in the right place, never that the thing works.

Same posture as ``db/test_migrations_static.py``: stdlib only, no service
imports, so it runs anywhere pytest does.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

INSTALLER = Path(__file__).resolve().parent / "install.sh"


@pytest.fixture(scope="module")
def source() -> str:
    return INSTALLER.read_text(encoding="utf-8")


def _function_body(source: str, name: str) -> str:
    """The text of one shell function, from ``name() {`` to the closing brace
    in column 1. Every function in this script is written that way."""
    start = source.index(f"{name}() {{")
    end = source.index("\n}\n", start)
    return source[start:end]


def test_the_app_profile_is_added_in_every_access_mode(source):
    """THE REGRESSION. The access mode answers WHO may reach Headway; it must
    never decide WHETHER Headway runs.

    Asserted structurally rather than by string match: the call has to sit
    outside the mode conditional, which is exactly where it was not.
    """
    body = _function_body(source, "write_access_env")
    assert "add_compose_profile app" in body, (
        "write_access_env no longer enables the app profile at all — a "
        "successful install would leave no website, API or collector running."
    )
    # Everything from the mode branch's `if` to its matching `fi` is
    # conditional. The call must not be in there.
    conditional = body[body.index('if [ "$ACCESS_MODE" = "lan" ]') : body.rindex("  fi")]
    assert "add_compose_profile app" not in conditional, (
        "add_compose_profile app is inside the access-mode conditional again. "
        "That is the 2026-08-02 defect: the default 'local' install starts the "
        "database, queue, storage and dashboards and no Headway, then reports "
        "success. The app profile belongs after the conditional, unconditionally."
    )


def test_the_lan_profile_is_still_conditional(source):
    """The mirror of the above, so a fix in the wrong direction is caught too:
    the office doorway (Caddy) genuinely IS mode-specific, and starting it for
    a 'local' install would publish ports 80 and 443 nobody asked for."""
    body = _function_body(source, "write_access_env")
    conditional = body[body.index('if [ "$ACCESS_MODE" = "lan" ]') : body.rindex("  fi")]
    assert "add_compose_profile lan" in conditional
    assert "remove_compose_profile lan" in conditional


def test_the_closing_summary_does_not_tell_the_operator_to_start_the_app(source):
    """The messaging half of the same defect. The summary used to hand the
    operator a `--profile app up -d --build` command as step 2, which read as
    optional feed-collection setup rather than 'your application is not
    running'. With the app profile always on, that instruction is not just
    unnecessary — repeating it would teach the wrong mental model."""
    body = _function_body(source, "print_summary")
    assert "--profile app up -d --build" not in body, (
        "print_summary tells the operator to start the app services by hand. "
        "They are started by the installer now; this instruction contradicts it."
    )


def test_the_installer_names_a_command_for_the_distro_it_is_run_on(source):
    """"Follow the upstream docs" is the wrong amount of help for an audience
    with one week of Linux and zero SQL. A person who has to work out which of
    five package managers they have has been handed the problem the installer
    exists to remove.

    ID_LIKE as well as ID, so derivatives (Linux Mint, Rocky, Pop!_OS) are
    covered by their parent rather than falling through to the generic link.
    """
    body = _function_body(source, "docker_install_hint")
    assert "/etc/os-release" in body
    assert "ID_LIKE" in body
    for family in ("ubuntu", "debian", "fedora", "rhel", "arch"):
        assert family in body, f"no install command for the {family} family"
    # A distro we do not know must still get the generic advice, never a
    # confidently wrong command.
    assert "printf '%s' \"\"" in body, (
        "docker_install_hint must return empty for an unrecognized system so "
        "check_docker falls back to the upstream docs link"
    )


def test_the_distro_command_is_printed_and_never_executed(source):
    """The standing posture, at the one place it is most tempting to break:
    the operator is stuck, the command is right there, and running it would be
    'helpful'. Installing Docker needs root, and an installer that silently
    escalates is one no IT department should accept."""
    body = _function_body(source, "docker_install_hint")
    # The hint is built with printf and returned; nothing evaluates it.
    for forbidden in ("eval", "$(sudo", "| sh", "| bash", "sh -c"):
        assert forbidden not in body, (
            f"docker_install_hint contains {forbidden!r} — it must compose a "
            f"string for a human to run, never run anything itself."
        )
    check = _function_body(source, "check_docker")
    assert "never uses them on your behalf" in check, (
        "check_docker no longer tells the operator why it will not install "
        "Docker for them. The refusal has to be explained or it reads as a gap."
    )


def test_the_owned_port_parser_understands_ranges(source):
    """MinIO publishes ``127.0.0.1:9000-9001->9000-9001/tcp`` — a RANGE. The
    first version of this parser only matched single ports, silently dropped
    both of MinIO's, and reported them as somebody else's conflict. The stack
    contains both shapes, so both have to be handled."""
    body = _function_body(source, "headway_owned_ports")
    assert "9000-9001" in body, (
        "the range shape is no longer documented in the parser; it is the "
        "case that was missed the first time"
    )
    assert "for (p = r[1]; p <= r[2]; p++)" in body, (
        "headway_owned_ports no longer expands published port RANGES, so "
        "MinIO's two ports will be reported as a foreign conflict on every "
        "running installation."
    )


def test_check_ports_does_not_call_docker_once_per_port(source):
    """Eight subprocesses to answer one question is the kind of thing that
    reads fine and makes --check feel broken on a slow machine."""
    body = _function_body(source, "check_ports")
    assert body.count("headway_owned_ports") == 1


def test_logs_are_kept_before_anything_recreates_a_container(source):
    """Container logs die with the container, and both update paths recreate
    every one of them.

    Found live 2026-08-03: a partner agency ran --update-from-source to pick up
    an adapter fix, and it took with it the transform logs holding the reason
    their file had produced no rows. The operation run to FIX a problem
    destroyed the evidence of it. There was nothing left to read.

    Asserted per call site rather than by counting: a THIRD recreate path added
    later must also capture, and a test that just counts would pass while the
    new path silently threw its logs away.
    """
    update = _function_body(source, "update_from_source")
    assert "capture_service_logs" in update, (
        "--update-from-source rebuilds every container without keeping their "
        "logs first. That is the 2026-08-03 evidence loss."
    )
    # The capture has to come BEFORE the rebuild, or it captures the new
    # containers, which have no history.
    assert update.index("capture_service_logs") < update.index("up -d --build"), (
        "capture_service_logs runs after the rebuild, so it reads the fresh "
        "containers instead of the ones being replaced."
    )


def test_keeping_logs_never_blocks_an_update(source):
    """An operator running an update needs the update. A failure to keep logs
    is worth a note, never a stop — the whole point is that it runs on a box
    already in trouble."""
    body = _function_body(source, "capture_service_logs")
    assert "return 0" in body
    for fatal in ("exit 1", "fail "):
        assert fatal not in body, (
            f"capture_service_logs can {fatal!r} — a logging failure must not "
            f"abort the update it precedes."
        )
    # Bounded: a chatty service must not fill the disk on the way out.
    assert "--tail" in body
    # And bounded in the OTHER direction. A single capture measured 3.9 MB on
    # a one-day-old installation; keeping one per update forever would be the
    # same unbounded-growth bug this change exists to fix, one level up.
    assert "LOG_KEEP_CAPTURES" in body, (
        "captures are never pruned — bounding the container logs and then "
        "leaving an unbounded pile of copies of them fixes nothing."
    )


def test_every_long_running_service_has_bounded_logs():
    """Docker's json-file default has NO rotation, so a service writes until
    something destroys its container. Two agency VMs have already hit storage
    exhaustion. Read from compose.yaml because that is where the guarantee
    lives."""
    import yaml

    compose = yaml.safe_load(
        (INSTALLER.parent.parent / "deploy" / "compose" / "compose.yaml").read_text()
    )
    missing = [
        name
        for name, svc in compose["services"].items()
        if isinstance(svc, dict)
        and svc.get("restart") == "unless-stopped"
        and "logging" not in svc
    ]
    assert missing == [], (
        f"these long-running services have unbounded logs: {missing}. "
        f"json-file with no max-size grows until the container is destroyed."
    )


def test_every_access_mode_is_handled_somewhere(source):
    """--help documents three modes. A fourth added without wiring would fall
    into the else branch silently."""
    for mode in ("local", "lan", "it"):
        assert re.search(rf"\b{mode}\b", source), f"access mode {mode} is undocumented"


def test_the_installer_never_runs_sudo_for_the_operator(source):
    """A standing posture stated in the script itself ("Firewall help is
    PRINTED, never run — this installer never runs sudo commands for you").
    Pinned because it is the kind of convenience that gets added later, and an
    installer that silently escalates is one nobody should run."""
    offenders = [
        line.strip()
        for line in source.splitlines()
        # Mentions inside printed guidance are fine; an actual invocation is not.
        if re.match(r"^\s*(sudo|.*\|\s*sudo)\s", line)
        and not re.match(r"^\s*(#|say|fixln|note|warn|echo)", line.strip())
    ]
    assert offenders == [], f"installer would run sudo itself: {offenders}"
