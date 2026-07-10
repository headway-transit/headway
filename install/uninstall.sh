#!/usr/bin/env bash
# =============================================================================
# Headway cautious uninstaller.
#
# Removes a Headway installation in three SEPARATE, individually confirmed
# stages, from least to most destructive:
#
#   1. Stop and remove the running programs (containers).
#      -> Your DATA IS NOT touched by this stage.
#   2. Delete the data volumes (the database, stored files, dashboards).
#      -> PERMANENT. Requires its own typed confirmation.
#   3. Delete the configuration file (deploy/compose/.env, which holds this
#      installation's passwords). Asked about separately; default is KEEP.
#
# Nothing is deleted without a typed confirmation. Answering anything other
# than the exact requested text skips that stage.
# =============================================================================

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_DIR="$REPO_DIR/deploy/compose"
ENV_FILE="$COMPOSE_DIR/.env"

say()  { printf '%s\n' "$1"; }
blank(){ printf '\n'; }

on_unexpected_error() {
  blank
  say "The uninstaller stopped because a step failed (script line $1)."
  say "Nothing beyond what was already confirmed has been deleted. You can"
  say "run ./install/uninstall.sh again safely."
  exit 1
}
trap 'on_unexpected_error $LINENO' ERR

blank
say "Headway uninstaller"
say "==================="
say ""
say "This tool removes Headway from this computer in three separate stages."
say "You will be asked to confirm each stage by typing an exact phrase —"
say "anything else skips that stage. Nothing has been deleted yet."
say ""
say "  Stage 1: stop and remove the running programs (containers)."
say "           Your data is NOT deleted by this stage."
say "  Stage 2: delete the data volumes — the database, stored feed files"
say "           and dashboards. This is PERMANENT and cannot be undone."
say "  Stage 3: decide what to do with the configuration file (it holds"
say "           this installation's passwords). Default is to KEEP it."

# --- Can we talk to Docker at all? -------------------------------------------

if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
  blank
  say "PROBLEM: this tool cannot reach Docker, so it cannot see or remove"
  say "Headway's containers and data. To find out exactly why (and get the"
  say "commands to fix it), run:"
  say "    ./install/install.sh --check"
  say "Then run this uninstaller again."
  if [ -f "$ENV_FILE" ]; then
    blank
    say "The configuration file $ENV_FILE"
    say "does exist. It is NOT being touched. If you only want that file"
    say "gone, you can delete it yourself once you are sure — it contains"
    say "this installation's passwords, so without it the data in Docker"
    say "cannot easily be reused."
  fi
  exit 1
fi

# --- What exists? --------------------------------------------------------------

AGENCY_ID=""
if [ -f "$ENV_FILE" ]; then
  AGENCY_ID="$(grep -E '^AGENCY_ID=' "$ENV_FILE" | tail -n 1 | cut -d= -f2- || true)"
fi
CONFIRM_NAME="${AGENCY_ID:-headway}"

CONTAINERS="$(docker ps -aq --filter label=com.docker.compose.project=headway || true)"
VOLUMES="$(docker volume ls -q --filter label=com.docker.compose.project=headway || true)"

if [ -z "$CONTAINERS" ] && [ -z "$VOLUMES" ] && [ ! -f "$ENV_FILE" ]; then
  blank
  say "Nothing to remove: no Headway containers, no Headway data volumes,"
  say "and no configuration file were found on this computer."
  exit 0
fi

blank
say "Found on this computer:"
if [ -n "$CONTAINERS" ]; then
  docker ps -a --filter label=com.docker.compose.project=headway \
    --format '  - container: {{.Names}} ({{.Status}})'
else
  say "  - containers: none"
fi
if [ -n "$VOLUMES" ]; then
  for v in $VOLUMES; do say "  - data volume: $v"; done
else
  say "  - data volumes: none"
fi
if [ -f "$ENV_FILE" ]; then
  say "  - configuration file: $ENV_FILE"
else
  say "  - configuration file: none"
fi

# --- Stage 1: containers --------------------------------------------------------

blank
say "--- Stage 1 of 3: stop and remove the running programs ---"
if [ -z "$CONTAINERS" ]; then
  say "No Headway containers found; skipping this stage."
else
  say "This stops Headway and removes its containers. Your data (the"
  say "volumes) is NOT deleted by this stage — reinstalling or upgrading"
  say "later can pick the data back up."
  blank
  printf "To proceed, type your agency name exactly: %s\n" "$CONFIRM_NAME"
  printf "Type it here (anything else skips this stage): "
  read -r answer
  if [ "$answer" = "$CONFIRM_NAME" ]; then
    say "Stopping and removing containers..."
    if [ -f "$ENV_FILE" ]; then
      docker compose --project-directory "$COMPOSE_DIR" down --remove-orphans
    else
      # No .env: Compose cannot parse its config, so remove by label instead.
      docker rm -f $CONTAINERS >/dev/null
      docker network rm headway >/dev/null 2>&1 || true
    fi
    say "Done. The containers are gone; your data volumes are untouched."
  else
    say "That did not match, so this stage was SKIPPED. Nothing was removed."
  fi
fi

# --- Stage 2: data volumes -------------------------------------------------------

blank
say "--- Stage 2 of 3: delete the data volumes (PERMANENT) ---"
VOLUMES="$(docker volume ls -q --filter label=com.docker.compose.project=headway || true)"
if [ -z "$VOLUMES" ]; then
  say "No Headway data volumes found; skipping this stage."
else
  say "This PERMANENTLY deletes everything Headway has stored on this"
  say "computer: the database (all ingested transit data, user accounts,"
  say "audit history), the raw feed files, and the dashboards. There is no"
  say "undo. If there is ANY chance you need this data — for example for a"
  say "National Transit Database report — make a backup first, or skip"
  say "this stage."
  blank
  say "Note: volumes still attached to containers cannot be deleted; run"
  say "Stage 1 first if you skipped it."
  blank
  printf "To DELETE ALL DATA, type exactly: delete %s data\n" "$CONFIRM_NAME"
  printf "Type it here (anything else skips this stage): "
  read -r answer
  if [ "$answer" = "delete $CONFIRM_NAME data" ]; then
    say "Deleting data volumes..."
    failed=0
    for v in $VOLUMES; do
      if docker volume rm "$v" >/dev/null; then
        say "  deleted: $v"
      else
        say "  PROBLEM: could not delete $v (is a container still using it?)"
        failed=1
      fi
    done
    if [ "$failed" -eq 1 ]; then
      say "Some volumes could not be deleted. Run Stage 1 (remove the"
      say "containers), then run this uninstaller again."
    else
      say "Done. All Headway data on this computer has been deleted."
    fi
  else
    say "That did not match, so this stage was SKIPPED. Your data is safe."
  fi
fi

# --- Stage 3: configuration file --------------------------------------------------

blank
say "--- Stage 3 of 3: the configuration file ---"
if [ ! -f "$ENV_FILE" ]; then
  say "No configuration file found; nothing to decide."
else
  say "The file $ENV_FILE"
  say "holds this installation's settings and passwords. KEEP it if you"
  say "kept your data or might reinstall — the data can only be reused"
  say "with these passwords. Delete it only for a truly clean removal."
  blank
  printf "Delete the configuration file? Type 'delete' to delete it, or press Enter to KEEP it: "
  read -r answer
  if [ "$answer" = "delete" ]; then
    rm -f "$ENV_FILE"
    say "Deleted $ENV_FILE."
  else
    say "Keeping the configuration file (nothing was deleted in this stage)."
  fi
fi

blank
say "Uninstall finished. Summary of what remains, if anything, is above."
say "To install Headway again later: ./install/install.sh"
