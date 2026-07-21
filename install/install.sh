#!/usr/bin/env bash
# =============================================================================
# Headway guided installer.
#
# Audience: an IT generalist at a transit agency. Every message this script
# prints is written to be readable by a transit operations manager: each
# failure names the problem AND the fix. No raw stack traces.
#
# Usage:
#   ./install/install.sh            guided install (asks questions)
#   ./install/install.sh --check    only check this computer; change nothing
#   ./install/install.sh --yes      no questions; inputs come from environment
#                                   variables (see --help or install/README.md)
#   ./install/install.sh --reconfigure-access
#                                   change the answer to "Where will people
#                                   use Headway from?" on an existing
#                                   installation (both directions, any time)
#   ./install/install.sh --check-updates
#                                   read-only: compare this installation's
#                                   version with the newest Headway release
#                                   (asks GitHub only when YOU run this)
#   ./install/install.sh --upgrade [vX.Y.Z]
#                                   update an existing installation to a
#                                   release: verify every image signature
#                                   (cosign), pull, switch, migrate,
#                                   health-check, print how to go back
#
# SECRETS POLICY (no secrets in the log, by construction):
#   - Generated passwords and typed passwords exist only in shell variables
#     and in deploy/compose/.env (created with file permissions 600).
#   - Secrets are handed to helper containers via environment inheritance
#     ("docker run -e NAME" with no value, plus a VAR=... command prefix),
#     so they never appear on a command line or in process listings.
#   - The log receives only fixed messages plus the output of commands that
#     do not echo credentials (docker compose, pip, the migration runner).
#     Nothing in this script ever prints a secret.
# =============================================================================

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
# The HEADWAY_* overrides below are TEST SEAMS, not user options: they let a
# disposable verification stack (its own compose dir, project name and log)
# exercise this script without touching a live installation — see handoff
# 0022. Production installs never set them; the defaults are the real paths.
COMPOSE_DIR="${HEADWAY_COMPOSE_DIR:-$REPO_DIR/deploy/compose}"
COMPOSE_PROJECT="${HEADWAY_COMPOSE_PROJECT:-headway}"
ENV_EXAMPLE="$COMPOSE_DIR/.env.example"
ENV_FILE="$COMPOSE_DIR/.env"
LOG_FILE="${HEADWAY_LOG_FILE:-$SCRIPT_DIR/install.log}"

# Where releases live. HEADWAY_UPGRADE_REPO exists for forks that run their
# own releases: it changes BOTH where --check-updates/--upgrade look for
# releases AND the signing identity --upgrade demands of every image — a
# fork's images signed by the fork's own release workflow verify against the
# fork, never silently against ours (or vice versa).
UPGRADE_REPO="${HEADWAY_UPGRADE_REPO:-headway-transit/headway}"
# Image namespace is fixed to the upstream project: the signed images the
# stack runs are published by headway-transit's release pipeline.
IMAGE_NAMESPACE="ghcr.io/headway-transit"
# The app services --upgrade switches to released images. web is deliberately
# absent: its API address is baked in at build time, so it is REBUILT locally
# from the release's source instead of pulled (docs/updating.md explains).
UPGRADE_IMAGES=(ingestion transform api)

# Files this script creates (the log, .env) are private to your user account.
umask 077

CHECK_ONLY=0
ASSUME_YES=0
RECONFIGURE=0
CHECK_UPDATES=0
UPGRADE=0
UPGRADE_TARGET=""
FAILURES=0
WARNINGS=0

# Network access ("Where will people use Headway from?"), see docs/network-access.md.
#   local = just this computer (default)   lan = other computers in the office
#   it    = IT staff set up access themselves
ACCESS_MODE="local"
LAN_ADDRESS=""

# Ports the Headway stack needs on this computer, and what each one is for.
REQUIRED_PORTS=(5432 8000 9000 9090 3000 29092 8081 9001)
port_label() {
  case "$1" in
    5432)  echo "the database (PostgreSQL/TimescaleDB)" ;;
    8000)  echo "the Headway API" ;;
    9000)  echo "file storage (MinIO)" ;;
    9001)  echo "the file-storage web console (MinIO)" ;;
    9090)  echo "system metrics (Prometheus)" ;;
    3000)  echo "the dashboards website (Grafana)" ;;
    29092) echo "the message queue (Kafka)" ;;
    8081)  echo "the data-format catalog (Apicurio Registry)" ;;
    80|443) echo "the secure office doorway (Caddy)" ;;
    *)     echo "a Headway service" ;;
  esac
}

# Long-running services that must report healthy after start.
HEALTH_SERVICES=(timescaledb kafka apicurio minio prometheus grafana)
service_label() {
  case "$1" in
    timescaledb) echo "the database" ;;
    kafka)       echo "the message queue" ;;
    apicurio)    echo "the data-format catalog" ;;
    minio)       echo "file storage" ;;
    prometheus)  echo "system metrics" ;;
    grafana)     echo "the dashboards website" ;;
    api)         echo "the Headway sign-in service (API)" ;;
    web)         echo "the Headway website" ;;
    caddy)       echo "the secure office doorway (Caddy)" ;;
    *)           echo "$1" ;;
  esac
}

usage() {
  cat <<'EOF'
Headway guided installer

Usage:
  ./install/install.sh            Guided install. Asks a few questions, then
                                  sets everything up. Takes about 30 minutes
                                  on a typical internet connection.
  ./install/install.sh --check    Only check whether this computer is ready.
                                  Changes nothing. Safe to run any time.
  ./install/install.sh --yes      Non-interactive install (for automation).
                                  Answers come from environment variables:
                                    HEADWAY_AGENCY_ID          (required)
                                    HEADWAY_ADMIN_USERNAME     (required)
                                    HEADWAY_ADMIN_PASSWORD     (required)
                                    HEADWAY_GTFS_STATIC_URL    (optional)
                                    HEADWAY_GTFS_RT_VEHICLE_POSITIONS_URL
                                                               (optional)
                                    HEADWAY_ACCESS_MODE        (optional:
                                      local = just this computer [default],
                                      lan   = other computers in the office,
                                      it    = IT staff set up access)
                                    HEADWAY_LAN_ADDRESS        (required when
                                      HEADWAY_ACCESS_MODE=lan: the address
                                      coworkers' browsers will use — the
                                      installer never guesses it silently)
  ./install/install.sh --reconfigure-access
                                  Change the answer to "Where will people
                                  use Headway from?" on an installation that
                                  already exists. Works in both directions —
                                  opening Headway to the office, or making it
                                  private to this computer again — and is
                                  safe to run repeatedly.
  ./install/install.sh --check-updates
                                  Read-only. Compares this installation's
                                  version with the newest Headway release and
                                  prints where to read what changed. Headway
                                  NEVER checks on its own — the internet is
                                  contacted only when you run this command,
                                  and nothing about your installation is sent.
  ./install/install.sh --upgrade [vX.Y.Z]
                                  Update an existing installation. Without a
                                  version it asks GitHub for the newest
                                  release; with one (like v0.3.0) it updates
                                  to exactly that. Every downloaded image's
                                  signature is verified before anything
                                  changes; your data is never touched. The
                                  full story, including how to go back, is
                                  in docs/updating.md.
  ./install/install.sh --help     Show this message.

Everything the installer does is recorded in install/install.log.
That log never contains passwords, so it is safe to share when asking
for help. Full guide: install/README.md
EOF
}

for arg in "$@"; do
  case "$arg" in
    --check) CHECK_ONLY=1 ;;
    --yes)   ASSUME_YES=1 ;;
    --reconfigure-access) RECONFIGURE=1 ;;
    --check-updates) CHECK_UPDATES=1 ;;
    --upgrade) UPGRADE=1 ;;
    v[0-9]*)
      # A release version like v0.2.0-alpha — only meaningful with --upgrade.
      if ! printf '%s' "$arg" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9.-]+)?$'; then
        echo "That does not look like a Headway release version: $arg"
        echo "Versions look like v0.2.0 or v0.2.0-alpha."
        exit 1
      fi
      UPGRADE_TARGET="$arg"
      ;;
    --help|-h) usage; exit 0 ;;
    *)
      echo "Unknown option: $arg"
      echo "Run './install/install.sh --help' to see the available options."
      exit 1
      ;;
  esac
done

if [ -n "$UPGRADE_TARGET" ] && [ "$UPGRADE" -ne 1 ]; then
  echo "A version ($UPGRADE_TARGET) only makes sense together with --upgrade."
  echo "Did you mean: ./install/install.sh --upgrade $UPGRADE_TARGET"
  exit 1
fi

# --- Logging and output helpers ----------------------------------------------

log()  { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" >>"$LOG_FILE"; }
say()  { printf '%s\n' "$1"; log "$1"; }
blank(){ printf '\n'; }
ok()   { say "  OK       $1"; }
note() { say "  NOTE     $1"; }
warn() { say "  WARNING  $1"; WARNINGS=$((WARNINGS + 1)); }
fail() { say "  PROBLEM  $1"; FAILURES=$((FAILURES + 1)); }
fixln(){ say "           $1"; }

on_unexpected_error() {
  blank
  say "The installer stopped because a step failed (script line $1)."
  say "Nothing on this computer has been half-deleted; it is safe."
  say "What happened is recorded in: $LOG_FILE"
  say "That log contains no passwords, so you can share it when asking for"
  say "help. See install/README.md, section 'If the installer stops'."
  exit 1
}
trap 'on_unexpected_error $LINENO' ERR

if ! touch "$LOG_FILE" 2>/dev/null; then
  echo "PROBLEM: cannot write the log file at $LOG_FILE."
  echo "To fix: make sure your user account can write inside $SCRIPT_DIR"
  echo "(for example: sudo chown \"$USER\" \"$SCRIPT_DIR\")."
  exit 1
fi
log "================================================================"
log "installer started: check-only=$CHECK_ONLY non-interactive=$ASSUME_YES reconfigure-access=$RECONFIGURE"

# --- Small utilities ----------------------------------------------------------

dc() { docker compose -p "$COMPOSE_PROJECT" --project-directory "$COMPOSE_DIR" "$@"; }

# The Docker network helper containers join (migrations, admin account).
# Matches compose.yaml's `networks.headway.name` default; a disposable test
# stack overrides it via HEADWAY_NETWORK in its own .env (see handoff 0022).
compose_network() {
  local net=""
  [ -f "$ENV_FILE" ] && net="$(read_env_value HEADWAY_NETWORK)"
  printf '%s' "${net:-headway}"
}

port_in_use() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -Hltn 2>/dev/null | awk '{print $4}' | grep -Eq "[:.]${port}\$"
  else
    # Fallback: try to connect. If something answers, the port is taken.
    timeout 2 bash -c "exec 3<>/dev/tcp/127.0.0.1/${port}" 2>/dev/null
  fi
}

# Replace (or append) KEY=value in $ENV_FILE. The value travels through the
# environment (ENVIRON), never through a shell-interpolated pattern, so any
# characters are safe and nothing is echoed.
set_env_value() {
  local key="$1"
  NEWVAL="$2" awk -v key="$key" '
    BEGIN { done = 0 }
    substr($0, 1, length(key) + 1) == key "=" && !done {
      print key "=" ENVIRON["NEWVAL"]; done = 1; next
    }
    { print }
    END { if (!done) print key "=" ENVIRON["NEWVAL"] }
  ' "$ENV_FILE" >"$ENV_FILE.new"
  mv "$ENV_FILE.new" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
}

read_env_value() {
  local line
  line="$(grep -E "^${1}=" "$ENV_FILE" | tail -n 1 || true)"
  printf '%s' "${line#*=}"
}

# --- Step 1: prerequisite checks ----------------------------------------------

docker_is_snap() {
  case "$(command -v docker 2>/dev/null || true)" in
    /snap/*) return 0 ;;
  esac
  command -v snap >/dev/null 2>&1 && snap list docker >/dev/null 2>&1
}

check_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    fail "Docker is not installed. Headway runs inside Docker containers,"
    fixln "so Docker is required."
    fixln "To fix: install Docker for your Linux distribution by following"
    fixln "https://docs.docker.com/engine/install/ then run this installer"
    fixln "again. (On Ubuntu, 'sudo snap install docker' also works; this"
    fixln "installer knows how to guide you through snap's extra setup.)"
    return
  fi
  ok "Docker is installed ($(docker --version 2>/dev/null || echo 'version unknown'))."

  if ! docker compose version >/dev/null 2>&1; then
    fail "The 'docker compose' command is missing. It is the part of Docker"
    fixln "that starts several containers together, and Headway needs it."
    fixln "To fix: install the Docker Compose plugin:"
    fixln "https://docs.docker.com/compose/install/linux/"
    fixln "then run this installer again."
  else
    ok "Docker Compose is installed ($(docker compose version --short 2>/dev/null || echo 'version unknown'))."
  fi

  if docker info >/dev/null 2>&1; then
    ok "Docker is running and your user account can use it."
    return
  fi

  # Docker exists but we cannot talk to it. Explain exactly why and how to fix.
  local sock=""
  for candidate in /var/run/docker.sock /run/docker.sock; do
    [ -S "$candidate" ] && { sock="$candidate"; break; }
  done

  if [ -z "$sock" ]; then
    fail "Docker is installed but not running (its control socket is missing)."
    if docker_is_snap; then
      fixln "To fix, start it with:   sudo snap start docker"
    else
      fixln "To fix, start it with:   sudo systemctl start docker"
      fixln "and enable it at boot:   sudo systemctl enable docker"
    fi
    fixln "Then run this installer again."
    return
  fi

  local sock_group
  sock_group="$(stat -c '%G' "$sock" 2>/dev/null || echo unknown)"

  if ! getent group docker >/dev/null 2>&1; then
    # Snap quirk 1: snap-installed Docker does not create the 'docker' group.
    fail "Docker is installed but your user account cannot reach it yet."
    if docker_is_snap; then
      fixln "Docker was installed with snap, which does not create the"
      fixln "'docker' user group that normally grants access. Run these"
      fixln "commands, then log out and back in:"
    else
      fixln "The 'docker' user group is missing. Run these commands, then"
      fixln "log out and back in:"
    fi
    fixln ""
    fixln "    sudo addgroup --system docker"
    fixln "    sudo adduser $USER docker"
    if docker_is_snap; then
      fixln "    sudo snap disable docker && sudo snap enable docker"
    else
      fixln "    sudo systemctl restart docker"
    fi
    fixln ""
    fixln "After logging back in, run this installer again."
    return
  fi

  if ! getent group docker | cut -d: -f4 | tr ',' '\n' | grep -qx "$USER"; then
    fail "Docker is running, but your user account ($USER) is not in the"
    fixln "'docker' group, so it is not allowed to use Docker."
    fixln "To fix, run:"
    fixln ""
    fixln "    sudo adduser $USER docker"
    fixln ""
    fixln "then log out and back in, and run this installer again."
    return
  fi

  if ! id -nG | tr ' ' '\n' | grep -qx docker; then
    fail "Your user account was added to the 'docker' group, but this login"
    fixln "session started before that happened, so the permission has not"
    fixln "taken effect yet."
    fixln "To fix: log out and back in (or reboot), then run this installer"
    fixln "again. To continue right now without logging out, run:"
    fixln ""
    fixln "    sg docker -c '$SCRIPT_DIR/install.sh'"
    return
  fi

  if [ "$sock_group" = "root" ]; then
    # Snap quirk 2: after the snap Docker daemon restarts (including snap
    # auto-updates), the socket ownership reverts to root:root.
    fail "Docker is running, but its control socket ($sock) is owned by"
    fixln "root:root, so regular users cannot reach it. This is a known"
    fixln "quirk of snap-installed Docker: every time the Docker service"
    fixln "restarts (including automatic snap updates), the socket's group"
    fixln "resets to root."
    fixln "To fix right now, run:"
    fixln ""
    fixln "    sudo chgrp docker $sock"
    fixln ""
    fixln "and run this installer again. If this keeps happening after"
    fixln "Docker restarts, re-run that same command each time, or run:"
    fixln "    sudo snap disable docker && sudo snap enable docker"
    fixln "after the 'docker' group exists, which makes snap set the group"
    fixln "correctly on startup."
    return
  fi

  fail "Docker is installed but did not answer ($(docker info 2>&1 | head -n 1))."
  fixln "To fix: make sure the Docker service is running:"
  if docker_is_snap; then
    fixln "    sudo snap restart docker"
  else
    fixln "    sudo systemctl restart docker"
  fi
  fixln "then run this installer again. If it still fails, see"
  fixln "install/README.md, section 'Getting help'."
}

check_ports() {
  local busy=0
  for port in "${REQUIRED_PORTS[@]}"; do
    if port_in_use "$port"; then
      fail "Port $port is already in use. Headway needs it for $(port_label "$port")."
      busy=1
    fi
  done
  if [ "$busy" -eq 1 ]; then
    fixln "A 'port' is a numbered door programs use to talk on this computer;"
    fixln "two programs cannot use the same one. Something already running is"
    fixln "using the port(s) above — often a previous or currently running"
    fixln "Headway installation, or another database/web server."
    fixln "To fix: if Headway is already installed here, do not reinstall —"
    fixln "see install/README.md. Otherwise find what is using a port with:"
    fixln "    sudo ss -ltnp | grep <port number>"
    fixln "and stop that program, then run this installer again."
  else
    ok "All the network ports Headway needs are free (${REQUIRED_PORTS[*]})."
  fi
}

check_resources() {
  local mem_kb mem_gb
  mem_kb="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)"
  mem_gb=$((mem_kb / 1024 / 1024))
  if [ "$mem_kb" -lt 3900000 ]; then
    warn "This computer has about ${mem_gb} GB of memory; Headway recommends"
    fixln "at least 4 GB. It may still run, but slowly. Consider a machine"
    fixln "with more memory for daily use."
  else
    ok "Memory: about ${mem_gb} GB (4 GB or more recommended)."
  fi

  local disk_kb disk_gb
  disk_kb="$(df -Pk "$REPO_DIR" 2>/dev/null | awk 'NR==2 {print $4}' || echo 0)"
  disk_gb=$((disk_kb / 1024 / 1024))
  if [ "$disk_kb" -lt $((20 * 1024 * 1024)) ]; then
    warn "Only about ${disk_gb} GB of disk space is free here; Headway"
    fixln "recommends at least 20 GB so there is room for your transit data"
    fixln "to grow. Free up space or use a larger disk before relying on"
    fixln "this installation."
  else
    ok "Disk space: about ${disk_gb} GB free (20 GB or more recommended)."
  fi

  if ! command -v openssl >/dev/null 2>&1; then
    fail "The 'openssl' tool is missing. The installer uses it to create"
    fixln "strong random passwords."
    fixln "To fix on Ubuntu/Debian:   sudo apt install openssl"
    fixln "To fix on RHEL/Fedora:     sudo dnf install openssl"
  else
    ok "openssl is available (used to generate strong passwords)."
  fi
}

run_prereq_checks() {
  blank
  say "--- Checking this computer ---"
  check_docker
  check_ports
  check_resources

  if [ "$CHECK_ONLY" -eq 1 ]; then
    if [ -f "$ENV_FILE" ]; then
      note "A Headway configuration file already exists at"
      fixln "$ENV_FILE — this computer appears to already have"
      fixln "Headway installed (or a previous install attempt). The full"
      fixln "installer will refuse to overwrite it; see install/README.md."
      local mode
      mode="$(read_env_value HEADWAY_ACCESS_MODE)"
      case "${mode:-local}" in
        lan) note "Its network access is set to: other computers in the office"
             fixln "(https://$(read_env_value HEADWAY_LAN_ADDRESS)). Change it any time with:"
             fixln "./install/install.sh --reconfigure-access" ;;
        it)  note "Its network access is set to: IT staff manage access."
             fixln "Change it any time with: ./install/install.sh --reconfigure-access" ;;
        *)   note "Its network access is set to: just this computer (the default)."
             fixln "Change it any time with: ./install/install.sh --reconfigure-access" ;;
      esac
    fi
  fi
}

# --- Step 2: existing-installation detection -----------------------------------

refuse_existing_install() {
  blank
  say "--- Headway is already installed on this computer ---"
  say ""
  say "$1"
  say ""
  say "To protect your data, this installer will not overwrite an existing"
  say "installation. What you can do instead:"
  say ""
  say "  - If you want to UPDATE Headway to a newer release: run"
  say "    ./install/install.sh --check-updates   (read-only, shows versions)"
  say "    ./install/install.sh --upgrade         (does the update)"
  say "    What an update does — and how to go back — is explained in plain"
  say "    words in docs/updating.md."
  say "  - If a previous install attempt stopped partway and you want to"
  say "    start over: run ./install/uninstall.sh first. It will ask before"
  say "    deleting anything, and your data is only removed if you say so."
  say "  - If you just want to check this computer: run"
  say "    ./install/install.sh --check (it changes nothing)."
  log "refused: existing installation detected"
  exit 2
}

detect_existing_install() {
  if [ -f "$ENV_FILE" ]; then
    refuse_existing_install \
"A Headway configuration file already exists at:
  $ENV_FILE
That file is created during installation and holds this installation's
passwords, so a Headway installation (or a previous attempt) is present."
  fi
  # Only consult Docker if we can actually reach it; if we cannot, the
  # prerequisite checks that follow will explain that problem properly.
  if docker info >/dev/null 2>&1; then
    local containers
    containers="$(docker ps -aq --filter "label=com.docker.compose.project=$COMPOSE_PROJECT" 2>/dev/null || true)"
    if [ -n "$containers" ]; then
      refuse_existing_install \
"Docker containers belonging to a Headway installation (project '$COMPOSE_PROJECT')
already exist on this computer:
$(docker ps -a --filter "label=com.docker.compose.project=$COMPOSE_PROJECT" --format '  - {{.Names}} ({{.Status}})' 2>/dev/null)"
    fi
  fi
}

# --- Step 3: configuration (.env) ----------------------------------------------

AGENCY_ID=""
GTFS_STATIC_URL_IN=""
GTFS_RT_VP_URL_IN=""

gather_inputs() {
  blank
  say "--- A few questions about your agency ---"
  if [ "$ASSUME_YES" -eq 1 ]; then
    AGENCY_ID="${HEADWAY_AGENCY_ID:-}"
    GTFS_STATIC_URL_IN="${HEADWAY_GTFS_STATIC_URL:-}"
    GTFS_RT_VP_URL_IN="${HEADWAY_GTFS_RT_VEHICLE_POSITIONS_URL:-}"
    if [ -z "$AGENCY_ID" ]; then
      fail "Running with --yes, but the HEADWAY_AGENCY_ID environment"
      fixln "variable is not set. In non-interactive mode the installer"
      fixln "cannot ask questions, so it needs this value up front."
      fixln "To fix: HEADWAY_AGENCY_ID=myagency ./install/install.sh --yes"
      exit 1
    fi
    if ! printf '%s' "$AGENCY_ID" | grep -Eq '^[A-Za-z0-9._-]+$'; then
      fail "HEADWAY_AGENCY_ID may only contain letters, numbers, dots,"
      fixln "hyphens and underscores (no spaces). Got: '$AGENCY_ID'"
      exit 1
    fi
    say "Agency ID (from HEADWAY_AGENCY_ID): $AGENCY_ID"
    read_access_mode_from_env
    return
  fi

  say ""
  say "1) A short name (ID) for your agency. This tags every piece of data"
  say "   Headway stores as belonging to your agency. Use letters, numbers,"
  say "   dots, hyphens or underscores — no spaces. Example: metro-transit"
  while true; do
    printf '   Agency ID: '
    read -r AGENCY_ID
    if printf '%s' "$AGENCY_ID" | grep -Eq '^[A-Za-z0-9._-]+$'; then
      break
    fi
    say "   That name will not work. Please use only letters, numbers, dots,"
    say "   hyphens or underscores, with no spaces. Example: metro-transit"
  done
  log "agency id entered"

  say ""
  say "2) (Optional) Your agency's GTFS schedule feed. GTFS is the standard"
  say "   file format for transit schedules — most agencies already publish"
  say "   one for trip planners like Google Maps. It is a web address ending"
  say "   in .zip. If you do not know it, just press Enter to skip; you can"
  say "   add it later in deploy/compose/.env."
  printf '   GTFS schedule address (or press Enter to skip): '
  read -r GTFS_STATIC_URL_IN

  say ""
  say "3) (Optional) Your agency's GTFS-Realtime vehicle positions feed."
  say "   This is a live web address that reports where your vehicles are"
  say "   right now — it usually comes from your AVL/CAD vendor. Press"
  say "   Enter to skip if you do not know it."
  printf '   Vehicle positions address (or press Enter to skip): '
  read -r GTFS_RT_VP_URL_IN
  log "feed urls entered (static: $([ -n "$GTFS_STATIC_URL_IN" ] && echo provided || echo skipped), vehicle positions: $([ -n "$GTFS_RT_VP_URL_IN" ] && echo provided || echo skipped))"

  ask_access_mode
}

# --- Step 3b: network access ("Where will people use Headway from?") ------------
# Design contract: docs/handoffs/0016-…-lan-access.md. Plain-language guide
# for every option: docs/network-access.md. The same question is re-runnable
# any time on an existing installation via --reconfigure-access, in BOTH
# directions (open to the office / back to this computer only).

# Non-interactive answers (--yes). The installer never guesses the office
# address in unattended mode: lan requires HEADWAY_LAN_ADDRESS explicitly.
read_access_mode_from_env() {
  ACCESS_MODE="${HEADWAY_ACCESS_MODE:-local}"
  case "$ACCESS_MODE" in
    local|it) : ;;
    lan)
      LAN_ADDRESS="${HEADWAY_LAN_ADDRESS:-}"
      if [ -z "$LAN_ADDRESS" ]; then
        fail "HEADWAY_ACCESS_MODE=lan also needs HEADWAY_LAN_ADDRESS — the"
        fixln "address coworkers' browsers will use. In non-interactive mode"
        fixln "the installer cannot ask, and it never guesses an address"
        fixln "silently (a wrong guess would strand every coworker)."
        fixln "To fix: HEADWAY_LAN_ADDRESS=192.168.1.50 (your address) ..."
        exit 1
      fi
      if ! printf '%s' "$LAN_ADDRESS" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9.-]*$'; then
        fail "HEADWAY_LAN_ADDRESS does not look like a network address."
        fixln "Use the numbers-and-dots form (like 192.168.1.50) or a"
        fixln "computer name (like headway-box.office.local) — no spaces,"
        fixln "no slashes, no https:// prefix. Got: '$LAN_ADDRESS'"
        exit 1
      fi
      ;;
    *)
      fail "HEADWAY_ACCESS_MODE must be 'local', 'lan' or 'it' (got"
      fixln "'$ACCESS_MODE'). local = just this computer; lan = other"
      fixln "computers in the office; it = IT staff set up access."
      exit 1
      ;;
  esac
  say "Network access (from HEADWAY_ACCESS_MODE): $ACCESS_MODE"
  log "access mode chosen: $ACCESS_MODE (non-interactive)"
}

# Best guess at this computer's office-network address. Only ever a
# suggestion — a human confirms it (never assume; a wrong address strands
# every coworker with no error message anywhere).
detect_lan_address() {
  local addr=""
  addr="$(ip -4 route get 1.1.1.1 2>/dev/null \
          | awk '{for (i = 1; i < NF; i++) if ($i == "src") print $(i + 1)}' \
          | head -n 1)"
  if [ -z "$addr" ]; then
    addr="$(hostname -I 2>/dev/null | awk '{print $1}')"
  fi
  printf '%s' "$addr"
}

# Is OUR office doorway already running? (Then ports 80/443 being busy is
# expected, not a conflict — matters when --reconfigure-access re-picks lan.)
caddy_is_ours_running() {
  docker ps --filter "name=$COMPOSE_PROJECT-caddy-1" --format '{{.Names}}' 2>/dev/null \
    | grep -qx "$COMPOSE_PROJECT-caddy-1"
}

# Option (b) details: ports free? address detected + human-confirmed?
# Returns 1 (with a plain-language explanation) if (b) cannot work right now.
configure_lan_address() {
  if ! caddy_is_ours_running; then
    local busy=""
    for port in 80 443; do
      if port_in_use "$port"; then busy="${busy:+$busy and }port $port"; fi
    done
    if [ -n "$busy" ]; then
      say ""
      say "   PROBLEM  Something on this computer is already using $busy."
      say "   The office doorway needs ports 80 and 443 (the standard web"
      say "   ports every browser expects). Usually another web server"
      say "   (Apache, nginx, ...) is running here. Find it with:"
      say "       sudo ss -ltnp | grep -E ':(80|443) '"
      say "   and stop it, then try again — or pick a different answer."
      return 1
    fi
  fi

  local detected typed
  detected="$(detect_lan_address)"
  say ""
  say "   Headway needs this computer's address on your office network —"
  say "   that is the address coworkers' browsers will connect to."
  if [ -n "$detected" ]; then
    say "   This computer's network address looks like: $detected"
    printf '   Press Enter to use it, or type a different address: '
  else
    say "   The installer could not detect an address by itself."
    printf '   Type this computer'"'"'s network address (like 192.168.1.50): '
  fi
  while true; do
    read -r typed
    LAN_ADDRESS="${typed:-$detected}"
    if printf '%s' "$LAN_ADDRESS" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9.-]*$'; then
      break
    fi
    say "   That does not look like a network address. Use the numbers-and-"
    say "   dots form (like 192.168.1.50) or a computer name (like"
    say "   headway-box.office.local) — no spaces, no slashes, no https://."
    printf '   Address: '
  done
  say "   Coworkers will reach Headway at: https://$LAN_ADDRESS"
  log "lan address confirmed: $LAN_ADDRESS"
  return 0
}

ask_access_mode() {
  blank
  say "--- Where will people use Headway from? ---"
  say ""
  say "Headway keeps everything private to this computer unless you say"
  say "otherwise. Pick what matches your office — you can change this"
  say "answer any time with: ./install/install.sh --reconfigure-access"
  say ""
  say "  a) Just this computer  (the safe default)"
  say "     Only web browsers running on this machine can open Headway."
  say ""
  say "  b) Other computers in our office"
  say "     Headway gets a secure https:// address that coworkers on your"
  say "     office network can open in their browsers. Their first visit"
  say "     shows a one-time certificate warning; the installer explains"
  say "     it and how to remove it for good. Nothing is ever exposed to"
  say "     the internet."
  say ""
  say "  c) Our IT staff will set up access"
  say "     Headway stays private to this computer, and you hand your IT"
  say "     team docs/network-access.md — it tells them exactly what to"
  say "     connect and what must never be exposed."
  say ""
  local access_answer
  while true; do
    printf '   Your answer (a, b or c) [a]: '
    read -r access_answer
    case "${access_answer:-a}" in
      a|A) ACCESS_MODE="local"; break ;;
      c|C) ACCESS_MODE="it"; break ;;
      b|B)
        if configure_lan_address; then
          ACCESS_MODE="lan"
          break
        fi
        say ""
        say "   Let's pick again."
        ;;
      *) say "   Please answer a, b or c (or press Enter for a)." ;;
    esac
  done
  log "access mode chosen: $ACCESS_MODE"
}

# Add/remove one profile token in COMPOSE_PROFILES (comma-separated) in .env,
# preserving whatever else is there. Idempotent by construction.
add_compose_profile() {
  local current
  current="$(read_env_value COMPOSE_PROFILES)"
  case ",$current," in
    *",$1,"*) : ;;
    *) set_env_value COMPOSE_PROFILES "${current:+$current,}$1" ;;
  esac
}

remove_compose_profile() {
  local current rebuilt="" token
  current="$(read_env_value COMPOSE_PROFILES)"
  local IFS=','
  for token in $current; do
    if [ -n "$token" ] && [ "$token" != "$1" ]; then
      rebuilt="${rebuilt:+$rebuilt,}$token"
    fi
  done
  set_env_value COMPOSE_PROFILES "$rebuilt"
}

# Write the whole network-access answer into .env in one place, so the four
# values that must move together (mode, address, browser origins, the
# address baked into the website) can never drift apart — the wave-14
# lesson: this wiring is owned by the installer, never by memory.
write_access_env() {
  set_env_value HEADWAY_ACCESS_MODE "$ACCESS_MODE"
  if [ "$ACCESS_MODE" = "lan" ]; then
    set_env_value HEADWAY_LAN_ADDRESS "$LAN_ADDRESS"
    # Web + API share ONE https:// origin behind the doorway, so browser
    # calls are same-origin by construction; the origins list is kept in
    # lockstep anyway (belt and suspenders), and localhost:8080 keeps a
    # browser on this box working against the same rebuilt website.
    set_env_value HEADWAY_CORS_ORIGINS "https://$LAN_ADDRESS,http://localhost:8080"
    set_env_value VITE_API_BASE_URL "https://$LAN_ADDRESS/api"
    add_compose_profile app
    add_compose_profile lan
  else
    set_env_value HEADWAY_LAN_ADDRESS ""
    set_env_value HEADWAY_CORS_ORIGINS ""
    set_env_value VITE_API_BASE_URL "http://localhost:8000"
    remove_compose_profile lan
  fi
  log "network access wired in .env (mode: $ACCESS_MODE; values not logged: none are secret, but passwords never are)"
}

# Firewall help is PRINTED, never run — this installer never runs sudo
# commands for you (its standing posture).
print_firewall_guidance() {
  if command -v ufw >/dev/null 2>&1 && systemctl is-active --quiet ufw 2>/dev/null; then
    say "This computer's firewall (ufw) is on, and it will block coworkers"
    say "until the two standard web ports are opened. Run this yourself —"
    say "the installer never runs sudo commands for you:"
    say ""
    say "    sudo ufw allow 80,443/tcp"
    say ""
  elif systemctl is-active --quiet firewalld 2>/dev/null; then
    say "This computer's firewall (firewalld) is on, and it will block"
    say "coworkers until the two standard web ports are opened. Run these"
    say "yourself — the installer never runs sudo commands for you:"
    say ""
    say "    sudo firewall-cmd --permanent --add-service=http --add-service=https"
    say "    sudo firewall-cmd --reload"
    say ""
  else
    say "No active firewall was detected on this computer. If your office"
    say "network has one elsewhere, ask whoever runs it to allow ports 80"
    say "and 443 to this machine."
    say ""
  fi
}

print_access_summary() {
  case "$ACCESS_MODE" in
    lan)
      say "--- Using Headway from other computers in your office ---"
      say ""
      say "The address to share with coworkers:"
      say ""
      say "    https://$LAN_ADDRESS"
      say ""
      say "It works from any computer on your office network — including"
      say "this one. The connection is encrypted."
      say ""
      print_firewall_guidance
      say "About the one-time browser warning: the first visit shows a"
      say "security warning such as \"Your connection is not private\"."
      say "That is expected, and here is why: Headway created its own"
      say "certificate for your office network, because the public"
      say "certificate authorities browsers trust out of the box can only"
      say "vouch for addresses on the public internet — never for private"
      say "office addresses like this one. The connection is still"
      say "encrypted either way. On your own office network, choosing"
      say "'Advanced' and then 'Proceed' (the wording varies by browser)"
      say "is a reasonable, informed thing to do."
      say ""
      say "To make the warning go away for good, install Headway's"
      say "certificate on each person's computer — step-by-step Windows,"
      say "Mac and Linux instructions are in docs/network-access.md,"
      say "section 'Removing the browser warning'."
      say ""
      say "What is deliberately NOT shared with the office: the dashboards"
      say "(Grafana), file storage, system metrics and the database stay"
      say "reachable only from this computer. docs/network-access.md"
      say "explains how an administrator reaches them remotely."
      ;;
    it)
      say "--- Access will be set up by your IT staff ---"
      say ""
      say "Headway stays private to this computer until they connect it."
      say "Hand them docs/network-access.md — it lists exactly what to"
      say "publish (the website on 127.0.0.1:8080 and the API on"
      say "127.0.0.1:8000, both on this machine only), what must never be"
      say "exposed, and the ready-made office option they can turn on with"
      say "one command if it fits your network."
      ;;
    *)
      say "--- Headway is private to this computer ---"
      say ""
      say "Only web browsers on this machine can reach it (the safe"
      say "default). To let coworkers in your office use it later, run:"
      say "    ./install/install.sh --reconfigure-access"
      say "docs/network-access.md explains every option in plain words."
      ;;
  esac
}

write_env_file() {
  blank
  say "--- Creating the configuration file ---"
  say "Writing $ENV_FILE"
  say "with strong, randomly generated passwords. Only your user account can"
  say "read this file (permissions 600). The passwords are NOT written to"
  say "the install log."

  cp "$ENV_EXAMPLE" "$ENV_FILE"
  chmod 600 "$ENV_FILE"

  # Hex output only (letters a-f and digits): safe in .env files, URLs and
  # shells with no escaping traps. 48 hex characters = 192 random bits.
  local pg_pass minio_pass grafana_pass
  pg_pass="$(openssl rand -hex 24)"
  minio_pass="$(openssl rand -hex 24)"
  grafana_pass="$(openssl rand -hex 24)"

  set_env_value POSTGRES_PASSWORD "$pg_pass"
  set_env_value MINIO_ROOT_PASSWORD "$minio_pass"
  set_env_value GRAFANA_ADMIN_PASSWORD "$grafana_pass"
  set_env_value AGENCY_ID "$AGENCY_ID"
  [ -n "$GTFS_STATIC_URL_IN" ] && set_env_value GTFS_STATIC_URL "$GTFS_STATIC_URL_IN"
  [ -n "$GTFS_RT_VP_URL_IN" ] && set_env_value GTFS_RT_VEHICLE_POSITIONS_URL "$GTFS_RT_VP_URL_IN"

  # The API needs a signing secret for sign-in sessions; generate one like
  # the passwords above (it is a secret; it is never logged).
  set_env_value HEADWAY_SESSION_SECRET "$(openssl rand -hex 32)"

  # The installation's certification signing key (handoff 0019): a 32-byte
  # Ed25519 seed as 64 hex characters. Generated HERE, at install — it
  # lives only in .env (mode 600), never in the database or the repo, and
  # it is never logged. Rotating it later changes the key fingerprint on
  # new certificates; old ones verify only against the old key.
  set_env_value HEADWAY_SIGNING_KEY "$(openssl rand -hex 32)"

  write_access_env

  ok "Configuration file created."
  log "wrote $ENV_FILE (values not logged)"
}

# --- Step 4: start the stack ---------------------------------------------------

start_stack() {
  blank
  say "--- Starting Headway ---"
  say "Docker will now download and start Headway's building blocks: the"
  say "database, the message queue, file storage, metrics and dashboards."
  if [ "$ACCESS_MODE" = "lan" ]; then
    say "Because you chose office access, the Headway website, its sign-in"
    say "service and the secure office doorway are also built and started"
    say "now — that adds some one-time build work."
  fi
  say "The first start downloads about 2 GB of software, so this can take"
  say "10 to 20 minutes depending on your internet connection."
  blank
  if ! dc up -d 2>&1 | tee -a "$LOG_FILE"; then
    blank
    fail "Docker could not start the Headway services."
    fixln "The full details are in $LOG_FILE."
    fixln "Common causes: no internet connection (the download failed), or"
    fixln "not enough disk space. Fix the cause, then run"
    fixln "./install/uninstall.sh followed by ./install/install.sh to retry."
    exit 1
  fi
}

wait_for_healthy() {
  blank
  say "--- Waiting for every service to report healthy ---"
  # In office-access mode the website, sign-in service and doorway are part
  # of the stack and must come up healthy too.
  local expected=("${HEALTH_SERVICES[@]}")
  if [ "$ACCESS_MODE" = "lan" ]; then
    expected+=(api web caddy)
  fi
  local deadline=$((SECONDS + 420)) all_ok=0
  while [ "$SECONDS" -lt "$deadline" ]; do
    local not_ready=()
    for svc in "${expected[@]}"; do
      local status
      status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
        "$COMPOSE_PROJECT-$svc-1" 2>/dev/null || echo "not started")"
      [ "$status" = "healthy" ] || not_ready+=("$(service_label "$svc")")
    done
    if [ "${#not_ready[@]}" -eq 0 ]; then all_ok=1; break; fi
    local joined=""
    for item in "${not_ready[@]}"; do joined="${joined:+$joined, }$item"; done
    say "  Still starting: $joined — this is normal, please wait..."
    sleep 15
  done

  if [ "$all_ok" -ne 1 ]; then
    blank
    fail "Some services did not become healthy within 7 minutes."
    fixln "To see what a service is reporting, run for example:"
    fixln "    docker compose --project-directory $COMPOSE_DIR logs timescaledb"
    fixln "Then see install/README.md, section 'If the installer stops'."
    exit 1
  fi
  ok "All services are healthy."

  # The stack includes two one-shot setup helpers (they create Kafka topics
  # and the storage bucket, then exit). Confirm they finished successfully —
  # a silent failure here would surface much later as missing data.
  for helper in bootstrap-kafka bootstrap-minio; do
    local hdl=$((SECONDS + 120)) state="" code=""
    while [ "$SECONDS" -lt "$hdl" ]; do
      state="$(docker inspect --format '{{.State.Status}}' "$COMPOSE_PROJECT-$helper-1" 2>/dev/null || echo missing)"
      [ "$state" = "exited" ] && break
      sleep 5
    done
    code="$(docker inspect --format '{{.State.ExitCode}}' "$COMPOSE_PROJECT-$helper-1" 2>/dev/null || echo 1)"
    if [ "$state" != "exited" ] || [ "$code" != "0" ]; then
      fail "The one-time setup helper '$helper' did not finish cleanly."
      fixln "See its messages with:"
      fixln "    docker logs $COMPOSE_PROJECT-$helper-1"
      fixln "and install/README.md, section 'If the installer stops'."
      exit 1
    fi
  done
  ok "One-time setup helpers (message-queue topics, storage bucket) finished."
}

# --- Step 5: database migrations -----------------------------------------------

run_migrations() {
  blank
  say "--- Setting up the database tables ---"
  say "Headway now creates its database tables. This runs inside a small"
  say "temporary helper container, so nothing extra is installed on this"
  say "computer. A short download happens the first time."
  blank
  local pg_user pg_db pg_pass
  pg_user="$(read_env_value POSTGRES_USER)"; pg_user="${pg_user:-headway}"
  pg_db="$(read_env_value POSTGRES_DB)";     pg_db="${pg_db:-headway}"
  pg_pass="$(read_env_value POSTGRES_PASSWORD)"

  # PGPASSWORD travels via environment inheritance (-e with no value):
  # it never appears in the command line or the log.
  if ! PGPASSWORD="$pg_pass" docker run --rm \
      --network "$(compose_network)" \
      -v "$REPO_DIR/db:/db:ro" \
      -e PGHOST=timescaledb \
      -e PGPORT=5432 \
      -e PGUSER="$pg_user" \
      -e PGPASSWORD \
      -e PGDATABASE="$pg_db" \
      python:3.12-slim \
      bash -c "pip install -q 'psycopg[binary]' && python /db/migrate.py" \
      2>&1 | tee -a "$LOG_FILE"; then
    blank
    fail "Setting up the database tables failed."
    fixln "The details are just above and in $LOG_FILE."
    fixln "This step is safe to repeat. See install/README.md, section"
    fixln "'If the installer stops'."
    exit 1
  fi
  ok "Database tables are in place."
}

# --- Step 6: first administrator account ----------------------------------------

ADMIN_USERNAME=""
ADMIN_PASSWORD=""

gather_admin_credentials() {
  blank
  say "--- Creating your administrator account ---"
  say "This is the account you will use to sign in to Headway. It gets the"
  say "'certifying official' role — the highest level, which can approve"
  say "reports and manage other accounts."
  if [ "$ASSUME_YES" -eq 1 ]; then
    ADMIN_USERNAME="${HEADWAY_ADMIN_USERNAME:-}"
    ADMIN_PASSWORD="${HEADWAY_ADMIN_PASSWORD:-}"
    if [ -z "$ADMIN_USERNAME" ] || [ -z "$ADMIN_PASSWORD" ]; then
      fail "Running with --yes, but HEADWAY_ADMIN_USERNAME and/or"
      fixln "HEADWAY_ADMIN_PASSWORD are not set. Both are required in"
      fixln "non-interactive mode."
      exit 1
    fi
  else
    while true; do
      printf '   Choose a username (letters/numbers, no spaces): '
      read -r ADMIN_USERNAME
      if printf '%s' "$ADMIN_USERNAME" | grep -Eq '^[A-Za-z0-9._-]+$'; then
        break
      fi
      say "   Please use only letters, numbers, dots, hyphens or underscores."
    done
    while true; do
      printf '   Choose a password (at least 8 characters; it will not be shown as you type): '
      read -rs ADMIN_PASSWORD; printf '\n'
      if [ "${#ADMIN_PASSWORD}" -lt 8 ]; then
        say "   That password is too short. Please use at least 8 characters."
        continue
      fi
      if [ "$(printf '%s' "$ADMIN_PASSWORD" | wc -c)" -gt 72 ]; then
        say "   That password is too long (the sign-in system supports up to"
        say "   72 characters). Please choose a shorter one."
        continue
      fi
      printf '   Type the same password again to confirm: '
      local confirm; read -rs confirm; printf '\n'
      if [ "$ADMIN_PASSWORD" = "$confirm" ]; then break; fi
      say "   The two passwords did not match. Let's try again."
    done
  fi
  if [ "$(printf '%s' "$ADMIN_PASSWORD" | wc -c)" -gt 72 ]; then
    fail "The administrator password is longer than 72 bytes, which the"
    fixln "sign-in system does not support. Please choose a shorter one."
    exit 1
  fi
  log "administrator username chosen (password not logged)"
}

create_admin_user() {
  local pg_user pg_db pg_pass
  pg_user="$(read_env_value POSTGRES_USER)"; pg_user="${pg_user:-headway}"
  pg_db="$(read_env_value POSTGRES_DB)";     pg_db="${pg_db:-headway}"
  pg_pass="$(read_env_value POSTGRES_PASSWORD)"

  # The password is hashed with bcrypt INSIDE the helper container (matching
  # services/api/headway_api/auth.py) and only the hash is stored. Both the
  # password and the database password travel via environment inheritance.
  if ! PGPASSWORD="$pg_pass" \
       HEADWAY_ADMIN_USERNAME="$ADMIN_USERNAME" \
       HEADWAY_ADMIN_PASSWORD="$ADMIN_PASSWORD" \
       docker run --rm -i \
      --network "$(compose_network)" \
      -e PGHOST=timescaledb \
      -e PGPORT=5432 \
      -e PGUSER="$pg_user" \
      -e PGPASSWORD \
      -e PGDATABASE="$pg_db" \
      -e HEADWAY_ADMIN_USERNAME \
      -e HEADWAY_ADMIN_PASSWORD \
      python:3.12-slim \
      bash -c "pip install -q bcrypt 'psycopg[binary]' && python -" \
      <<'PYEOF' 2>&1 | tee -a "$LOG_FILE"; then
import os, sys
import bcrypt
import psycopg

username = os.environ["HEADWAY_ADMIN_USERNAME"]
password = os.environ["HEADWAY_ADMIN_PASSWORD"].encode("utf-8")

# bcrypt reads only the first 72 bytes; reject loudly rather than truncate
# (same rule as services/api/headway_api/auth.py).
if len(password) > 72:
    print("PROBLEM  The password is longer than 72 bytes, which the sign-in")
    print("         system does not support. Please choose a shorter one.")
    sys.exit(1)

password_hash = bcrypt.hashpw(password, bcrypt.gensalt()).decode("ascii")

with psycopg.connect() as conn:  # connection settings come from PG* variables
    cur = conn.execute(
        "INSERT INTO auth.users (username, password_hash, role) "
        "VALUES (%s, %s, 'certifying_official') "
        "ON CONFLICT (username) DO NOTHING",
        (username, password_hash),
    )
    conn.commit()
    if cur.rowcount == 0:
        print(f"NOTE     A user named '{username}' already exists in this")
        print("         Headway database, so the installer did NOT change")
        print("         that account or its password. Sign in with the")
        print("         password that account already has. To add a")
        print("         different administrator, run the installer's user")
        print("         step again with another username.")
    else:
        print(f"OK       Administrator account '{username}' created with the")
        print("         'certifying_official' role.")
PYEOF
    blank
    fail "Creating the administrator account failed."
    fixln "The details are just above and in $LOG_FILE."
    fixln "See install/README.md, section 'If the installer stops'."
    exit 1
  fi
}

# --- Step 7: summary -------------------------------------------------------------

print_summary() {
  blank
  say "=================================================================="
  say " Headway is installed and running"
  say "=================================================================="
  say ""
  say "What is running on this computer (all inside Docker):"
  say "  - the database (PostgreSQL + TimescaleDB) — your transit data"
  say "  - the message queue (Kafka) — moves data between services"
  say "  - file storage (MinIO) — raw feed files"
  say "  - the data-format catalog (Apicurio Registry)"
  say "  - system metrics and dashboards (Prometheus + Grafana)"
  say ""
  say "Addresses you can open in a web browser ON THIS computer:"
  say "  - Dashboards (Grafana):        http://localhost:3000"
  say "      sign in as 'admin'; the password is the GRAFANA_ADMIN_PASSWORD"
  say "      line in $ENV_FILE"
  say "  - File storage console:        http://localhost:9001"
  say "  - System metrics (Prometheus): http://localhost:9090"
  say ""
  say "Where your data lives: in Docker 'volumes' on this computer's disk"
  say "(list them with: docker volume ls). They survive restarts and"
  say "reboots. Only ./install/uninstall.sh deletes them, and only after"
  say "you confirm."
  say ""
  say "Your configuration and passwords: $ENV_FILE"
  say "(readable only by your user account — keep it safe, do not email it)."
  say ""
  print_access_summary
  say ""
  say "Your next steps:"
  say "  1. Read install/README.md — it explains day-to-day basics."
  if [ "$ACCESS_MODE" = "lan" ]; then
    say "  2. The Headway website, sign-in service, feed collector and the"
    say "     office doorway are already running. Sign in as"
    say "     '$ADMIN_USERNAME' at https://$LAN_ADDRESS — and see"
    say "     deploy/compose/README.md for what each service is."
  else
    say "  2. To start collecting your agency's live feed data, see"
    say "     deploy/compose/README.md (the 'app' services, which include the"
    say "     feed collector, are started with:"
    say "     docker compose --project-directory $COMPOSE_DIR --profile app up -d --build )"
    say "  3. The Headway sign-in website/API ships with the app services;"
    say "     your administrator account ('$ADMIN_USERNAME') is already set up"
    say "     and ready for it."
  fi
  say ""
  say "Everything above was recorded (without passwords) in:"
  say "  $LOG_FILE"
  log "install completed successfully"
}

# --- Reconfigure network access on an existing installation ---------------------

NEEDS_WEB_REBUILD=0

apply_access_change() {
  local old_mode="$1"
  if ! docker info >/dev/null 2>&1; then
    warn "Docker is not reachable right now, so the running services were"
    fixln "not updated — but your answer is saved. Once Docker works again"
    fixln "(./install/install.sh --check will tell you), run"
    fixln "./install/install.sh --reconfigure-access once more and apply."
    return
  fi
  blank
  if [ "$old_mode" = "lan" ] && [ "$ACCESS_MODE" != "lan" ]; then
    say "Closing the office doorway..."
    dc --profile lan stop caddy 2>&1 | tee -a "$LOG_FILE" || true
    dc --profile lan rm -f caddy 2>&1 | tee -a "$LOG_FILE" || true
    ok "The office doorway is closed; other computers can no longer reach Headway."
  fi
  if [ "$NEEDS_WEB_REBUILD" -eq 1 ]; then
    say "Rebuilding the Headway website with its new address baked in (the"
    say "address the website calls is fixed when it is built) — this is the"
    say "slow part, usually a few minutes..."
    blank
    if ! dc --profile app build web 2>&1 | tee -a "$LOG_FILE"; then
      blank
      fail "Rebuilding the website failed."
      fixln "The details are just above and in $LOG_FILE. Nothing has been"
      fixln "half-changed; it is safe to run"
      fixln "./install/install.sh --reconfigure-access again."
      exit 1
    fi
  fi
  say "Updating the running services..."
  blank
  if ! dc up -d 2>&1 | tee -a "$LOG_FILE"; then
    blank
    fail "Docker could not update the Headway services."
    fixln "The details are just above and in $LOG_FILE. It is safe to run"
    fixln "./install/install.sh --reconfigure-access again."
    exit 1
  fi
  if [ "$ACCESS_MODE" = "lan" ]; then
    wait_for_healthy
  fi
  ok "The change is live."
}

reconfigure_access() {
  blank
  say "--- Changing where people use Headway from ---"
  if [ ! -f "$ENV_FILE" ]; then
    blank
    fail "No Headway configuration file was found at"
    fixln "$ENV_FILE, so there is nothing to reconfigure."
    fixln "This option changes an installation that already exists. To"
    fixln "install Headway, run: ./install/install.sh"
    exit 1
  fi
  local old_mode old_vite new_vite
  old_mode="$(read_env_value HEADWAY_ACCESS_MODE)"; old_mode="${old_mode:-local}"
  old_vite="$(read_env_value VITE_API_BASE_URL)"
  say ""
  case "$old_mode" in
    lan) say "Right now, other computers in your office can use Headway at:"
         say "    https://$(read_env_value HEADWAY_LAN_ADDRESS)" ;;
    it)  say "Right now, Headway is private to this computer (connecting it"
         say "to your network is in your IT staff's hands)." ;;
    *)   say "Right now, Headway is private to this computer." ;;
  esac

  if [ "$ASSUME_YES" -eq 1 ]; then
    read_access_mode_from_env
  else
    ask_access_mode
  fi
  write_access_env
  new_vite="$(read_env_value VITE_API_BASE_URL)"
  NEEDS_WEB_REBUILD=0
  [ "$old_vite" != "$new_vite" ] && NEEDS_WEB_REBUILD=1

  blank
  say "Your answer is saved in the configuration file."
  if [ "$old_mode" = "$ACCESS_MODE" ] && [ "$NEEDS_WEB_REBUILD" -eq 0 ] \
     && { [ "$ACCESS_MODE" != "lan" ] || caddy_is_ours_running; }; then
    say "It matches what was already set up, so nothing needs to change."
    log "reconfigure-access: no change (mode $ACCESS_MODE)"
    blank
    print_access_summary
    exit 0
  fi

  local apply_answer="yes"
  if [ "$ASSUME_YES" -ne 1 ]; then
    say "To make it take effect, Headway's running services need to be"
    if [ "$NEEDS_WEB_REBUILD" -eq 1 ]; then
      say "updated, and the website rebuilt (a few minutes)."
    else
      say "updated (usually under a minute)."
    fi
    printf 'Apply the change now? (yes/no): '
    read -r apply_answer
  fi
  case "$apply_answer" in
    y|Y|yes|YES|Yes)
      apply_access_change "$old_mode"
      blank
      print_access_summary
      say ""
      say "Everything above was recorded (without passwords) in:"
      say "  $LOG_FILE"
      log "reconfigure-access completed (mode: $ACCESS_MODE)"
      ;;
    *)
      say "Not applied — nothing running was touched. Your answer is saved;"
      say "make it take effect any time by running"
      say "./install/install.sh --reconfigure-access again and choosing to"
      say "apply."
      log "reconfigure-access: saved but not applied (mode: $ACCESS_MODE)"
      ;;
  esac
}

# --- Updates: --check-updates (read-only) and --upgrade --------------------------
# Design contract: docs/handoffs/0022-from-devops-to-devops-updates.md.
# Plain-language guide for agencies: docs/updating.md.
#
# Privacy posture, stated once and honored everywhere: Headway NEVER contacts
# the internet on its own to look for updates. The one and only version query
# happens when a person runs one of these two commands, and it is a plain
# read of the public release list — nothing about this installation is sent.

require_curl() {
  if ! command -v curl >/dev/null 2>&1; then
    fail "The 'curl' tool is missing. It is used (only when you run this"
    fixln "command) to read the public list of Headway releases."
    fixln "To fix on Ubuntu/Debian:   sudo apt install curl"
    fixln "To fix on RHEL/Fedora:     sudo dnf install curl"
    exit 1
  fi
}

require_cosign() {
  if command -v cosign >/dev/null 2>&1; then
    ok "cosign is installed ($(cosign version 2>/dev/null | awk '/GitVersion/ {print $2; exit}' || true))."
    return
  fi
  fail "The 'cosign' tool is not installed. Headway will not switch to"
  fixln "downloaded software whose signature it cannot check, so upgrades"
  fixln "require cosign — the standard open-source tool (from the Sigstore"
  fixln "project) that verifies each Headway image really was built and"
  fixln "signed by the Headway release pipeline."
  fixln "To fix: install cosign, then run this command again. Options:"
  fixln "  - Your package manager, if it has it (e.g. 'sudo dnf install"
  fixln "    cosign' on recent Fedora)."
  fixln "  - The official release binary: download 'cosign-linux-amd64'"
  fixln "    (or -arm64) from https://github.com/sigstore/cosign/releases,"
  fixln "    then run:"
  fixln "        chmod +x cosign-linux-amd64"
  fixln "        sudo mv cosign-linux-amd64 /usr/local/bin/cosign"
  fixln "    (The installer never runs sudo commands for you.)"
  exit 1
}

# Ask GitHub (only now, because a person ran this) for the newest release tag.
fetch_latest_release_tag() {
  local body
  if ! body="$(curl -fsS --max-time 30 \
      "https://api.github.com/repos/$UPGRADE_REPO/releases/latest" 2>>"$LOG_FILE")"; then
    fail "Could not read the release list from GitHub."
    fixln "Usually this means no internet connection from this computer, or"
    fixln "GitHub is briefly unreachable. Nothing was changed; try again"
    fixln "later. (The address asked was:"
    fixln "https://api.github.com/repos/$UPGRADE_REPO/releases/latest )"
    exit 1
  fi
  local tag
  tag="$(printf '%s' "$body" | sed -n 's/.*"tag_name" *: *"\([^"]*\)".*/\1/p' | head -n 1)"
  if [ -z "$tag" ]; then
    fail "GitHub answered, but no release could be found for $UPGRADE_REPO."
    fixln "Nothing was changed. If this persists, ask for help"
    fixln "(install/README.md, section 'Getting help')."
    exit 1
  fi
  printf '%s' "$tag"
}

current_version_label() {
  local cur=""
  [ -f "$ENV_FILE" ] && cur="$(read_env_value HEADWAY_IMAGE_TAG)"
  case "${cur:-local}" in
    local|"") echo "built from the source code on this computer (no release version recorded)" ;;
    *)        echo "$cur" ;;
  esac
}

check_updates() {
  blank
  say "--- Checking for Headway updates (read-only) ---"
  say ""
  say "Headway never checks for updates by itself; this question is being"
  say "asked now only because you ran this command, and nothing about your"
  say "installation is sent — it is a plain read of the public release list."
  blank
  require_curl
  local latest current
  latest="$(fetch_latest_release_tag)"
  if [ ! -f "$ENV_FILE" ]; then
    note "Headway is not installed on this computer (no configuration file"
    fixln "at $ENV_FILE)."
  fi
  current="$(current_version_label)"
  say "  This installation is running:  $current"
  say "  The newest Headway release is: $latest"
  say "  What changed in it:            https://github.com/$UPGRADE_REPO/releases/tag/$latest"
  blank
  case "$current" in
    "$latest")
      say "You are on the newest release. Nothing to do."
      ;;
    *)
      say "To update, when you are ready (updates never touch your data,"
      say "and docs/updating.md explains every step first):"
      say "    ./install/install.sh --upgrade"
      ;;
  esac
  log "check-updates: current='$current' latest='$latest'"
}

# Verify ONE image's signature, then pull exactly the bytes that were
# verified (by digest, not by movable tag), then give them the tag locally.
# Refuses loudly on any mismatch; nothing running has changed at this point.
verify_and_pull_image() {
  local name="$1" target="$2"
  local ref="$IMAGE_NAMESPACE/headway-$name:$target"
  local tag_re="${target//./\\.}"
  local identity_re="^https://github.com/$UPGRADE_REPO/\\.github/workflows/release\\.yml@refs/tags/$tag_re\$"
  local verify_out
  say "  Checking the signature of headway-$name $target ..."
  if ! verify_out="$(cosign verify \
      --certificate-oidc-issuer https://token.actions.githubusercontent.com \
      --certificate-identity-regexp "$identity_re" \
      "$ref" 2>>"$LOG_FILE")"; then
    blank
    fail "The signature on $ref"
    fixln "did NOT verify. Headway REFUSES to install it, and nothing on"
    fixln "this computer has been changed."
    fixln ""
    fixln "What this means: the image could not be proven to come from the"
    fixln "Headway release pipeline (expected signer:"
    fixln "https://github.com/$UPGRADE_REPO/.github/workflows/release.yml"
    fixln "for release $target). That can be a wrong version name, a"
    fixln "network problem — or someone offering you software that is not"
    fixln "Headway's. Details are in $LOG_FILE."
    fixln "If this persists on a version you took from"
    fixln "https://github.com/$UPGRADE_REPO/releases, please report it"
    fixln "(SECURITY.md) — do not work around it."
    exit 1
  fi
  local digest
  digest="$(printf '%s' "$verify_out" \
    | sed -n 's/.*"docker-manifest-digest" *: *"\(sha256:[a-f0-9]*\)".*/\1/p' | head -n 1)"
  if [ -z "$digest" ]; then
    fail "The signature check passed but did not name the exact image it"
    fixln "verified (its digest), so Headway cannot guarantee it would run"
    fixln "the same bytes that were checked. Refusing to continue; nothing"
    fixln "was changed. Details in $LOG_FILE."
    exit 1
  fi
  ok "Signature verified for headway-$name $target (digest ${digest:0:19}...)."
  log "verified $ref digest $digest"
  say "  Downloading exactly what was verified ..."
  if ! docker pull "$IMAGE_NAMESPACE/headway-$name@$digest" >>"$LOG_FILE" 2>&1; then
    fail "Downloading headway-$name $target failed after its signature"
    fixln "verified. Nothing running has changed; it is safe to run"
    fixln "./install/install.sh --upgrade again. Details in $LOG_FILE."
    exit 1
  fi
  docker tag "$IMAGE_NAMESPACE/headway-$name@$digest" "$ref"
  ok "Downloaded headway-$name $target."
}

# After the switch: every long-running service must come back healthy.
# Services that publish no health endpoint (the two pipeline loops) must at
# least be running. Fails loudly with the go-back instructions.
upgrade_health_gate() {
  blank
  say "--- Waiting for every service to report healthy on the new version ---"
  local expected=("${HEALTH_SERVICES[@]}") running_only=()
  local profiles
  profiles="$(read_env_value COMPOSE_PROFILES)"
  case ",$profiles," in *",app,"*)
    expected+=(api web)
    running_only=(ingestion transform)
  ;; esac
  case ",$profiles," in *",lan,"*) expected+=(caddy) ;; esac

  local deadline=$((SECONDS + 420)) all_ok=0
  while [ "$SECONDS" -lt "$deadline" ]; do
    local not_ready=()
    for svc in "${expected[@]}"; do
      local status
      status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
        "$COMPOSE_PROJECT-$svc-1" 2>/dev/null || echo "not started")"
      [ "$status" = "healthy" ] || not_ready+=("$(service_label "$svc")")
    done
    for svc in "${running_only[@]}"; do
      local status
      status="$(docker inspect --format '{{.State.Status}}' \
        "$COMPOSE_PROJECT-$svc-1" 2>/dev/null || echo "not started")"
      [ "$status" = "running" ] || not_ready+=("$svc (pipeline service)")
    done
    if [ "${#not_ready[@]}" -eq 0 ]; then all_ok=1; break; fi
    local joined=""
    for item in "${not_ready[@]}"; do joined="${joined:+$joined, }$item"; done
    say "  Still starting: $joined — this is normal, please wait..."
    sleep 15
  done

  if [ "$all_ok" -ne 1 ]; then
    blank
    fail "Some services did not become healthy within 7 minutes of the"
    fixln "update. Your data is untouched. To see what a service says:"
    fixln "    docker compose --project-directory $COMPOSE_DIR logs api"
    fixln "You can go back to the previous version's app images — the"
    fixln "'going back' section of docs/updating.md has the exact steps,"
    fixln "and the previous version is recorded in $ENV_FILE"
    fixln "as HEADWAY_PREVIOUS_IMAGE_TAG."
    exit 1
  fi
  ok "All services are healthy on the new version."
}

print_rollback_info() {
  local prev="$1" target="$2"
  say "--- If something seems wrong after this update ---"
  say ""
  say "Your data was not touched — updates never delete the data volumes,"
  say "and going back never does either."
  case "$prev" in
    local|"")
      say "Before this update, Headway ran images built from the source code"
      say "on this computer. To go back to that:"
      say "    1. Put the Headway folder back on your previous version"
      say "       (if you use git: git checkout <the commit you were on>)."
      say "    2. In $ENV_FILE set HEADWAY_IMAGE_TAG=local"
      say "    3. Run: docker compose --project-directory $COMPOSE_DIR --profile app up -d --build"
      ;;
    *)
      say "The version you were on before ($prev) is recorded in"
      say "$ENV_FILE as HEADWAY_PREVIOUS_IMAGE_TAG."
      say "To go back to it (signatures are verified again on the way back):"
      say "    ./install/install.sh --upgrade $prev"
      ;;
  esac
  say ""
  say "One honest limit, so nothing surprises you: database table changes"
  say "are forward-only. Going back swaps the app software; the database"
  say "keeps any new tables the update added. Headway updates only ever ADD"
  say "tables and columns — your recorded data is not rewritten — so older"
  say "app versions keep working against the newer tables."
}

run_upgrade() {
  blank
  say "--- Updating Headway ---"
  if [ ! -f "$ENV_FILE" ]; then
    blank
    fail "No Headway configuration file was found at"
    fixln "$ENV_FILE, so there is nothing to update."
    fixln "To install Headway on this computer, run: ./install/install.sh"
    exit 1
  fi
  if ! docker info >/dev/null 2>&1; then
    fail "Docker did not answer, and the update needs it. Run"
    fixln "./install/install.sh --check — it explains exactly what is wrong"
    fixln "with Docker and how to fix it. Nothing was changed."
    exit 1
  fi
  require_cosign

  # Which version are we going to?
  local target="$UPGRADE_TARGET"
  if [ -z "$target" ]; then
    require_curl
    say "No version was named, so the newest release will be used."
    say "(Asking GitHub now — only because you ran this command.)"
    target="$(fetch_latest_release_tag)"
  fi
  local current
  current="$(read_env_value HEADWAY_IMAGE_TAG)"; current="${current:-local}"
  blank
  say "  This installation is running:  $(current_version_label)"
  say "  Updating to:                   $target"
  say "  What changed in it:            https://github.com/$UPGRADE_REPO/releases/tag/$target"
  if [ "$current" = "$target" ]; then
    note "That is the version already recorded here. Continuing is safe —"
    fixln "the images are re-verified and re-applied, which also repairs an"
    fixln "installation where a previous update stopped partway."
  fi

  # The migrations and the website are built from THIS folder, so the folder
  # should hold the release being installed. Verify when we can (a git
  # checkout); warn loudly when it does not match, and never guess silently.
  if [ -d "$REPO_DIR/.git" ] && command -v git >/dev/null 2>&1; then
    local head_rev tag_rev
    head_rev="$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || true)"
    tag_rev="$(git -C "$REPO_DIR" rev-parse -q --verify "refs/tags/$target^{commit}" 2>/dev/null || true)"
    if [ -n "$tag_rev" ] && [ "$tag_rev" = "$head_rev" ]; then
      ok "This Headway folder is on release $target — folder and images match."
    else
      warn "This Headway folder does not appear to be on release $target."
      fixln "The database table updates and the website are built from this"
      fixln "folder, so folder and images should match. To put the folder on"
      fixln "the release first:"
      fixln "    git -C $REPO_DIR fetch --tags"
      fixln "    git -C $REPO_DIR checkout $target"
      fixln "then run this update again."
      if [ "$ASSUME_YES" -eq 1 ]; then
        if [ "${HEADWAY_UPGRADE_SOURCE_MISMATCH_OK:-}" != "yes" ]; then
          fail "Running with --yes, so nobody can confirm this mismatch is"
          fixln "intended. Refusing; nothing was changed. (Automation that"
          fixln "really means it sets HEADWAY_UPGRADE_SOURCE_MISMATCH_OK=yes.)"
          exit 1
        fi
        note "Continuing despite the mismatch (HEADWAY_UPGRADE_SOURCE_MISMATCH_OK=yes)."
      else
        printf 'Continue anyway? (yes/no): '
        local answer; read -r answer
        case "$answer" in
          y|Y|yes|YES|Yes) note "Continuing at your request despite the mismatch." ;;
          *) say "Stopping at your request. Nothing was changed."; exit 0 ;;
        esac
      fi
    fi
  else
    note "This folder is not a git checkout, so the installer cannot prove"
    fixln "it holds release $target. Please make sure you downloaded the"
    fixln "$target source before updating (docs/updating.md, step 1)."
  fi

  # 1. Verify every signature, then pull — BEFORE anything switches.
  blank
  say "--- Verifying release signatures (before anything changes) ---"
  say "Each downloaded piece of Headway is checked against the Headway"
  say "release pipeline's signing identity. If any check fails, the update"
  say "stops and nothing on this computer changes."
  for name in "${UPGRADE_IMAGES[@]}"; do
    verify_and_pull_image "$name" "$target"
  done

  # 2. Record the way back, then switch the version in the configuration.
  blank
  say "--- Switching to $target ---"
  set_env_value HEADWAY_PREVIOUS_IMAGE_TAG "$current"
  set_env_value HEADWAY_IMAGE_TAG "$target"
  ok "Configuration now points at $target (previous: $current, recorded)."
  log "upgrade: switched HEADWAY_IMAGE_TAG $current -> $target"

  # 3. The website is rebuilt on this computer from the release's source,
  #    because the address it calls is baked in when it is built — this
  #    keeps your answer to "Where will people use Headway from?" exactly
  #    as it was (nothing about network access is changed by an update).
  local profiles
  profiles="$(read_env_value COMPOSE_PROFILES)"
  case ",$profiles," in *",app,"*)
    say "Rebuilding the Headway website from the release's source (its"
    say "address settings are kept exactly as they were) — this is usually"
    say "the slowest step, a few minutes..."
    blank
    if ! dc --profile app build web 2>&1 | tee -a "$LOG_FILE"; then
      blank
      fail "Rebuilding the website failed. The services were NOT restarted;"
      fixln "the previous version is still running. Details are above and in"
      fixln "$LOG_FILE. It is safe to run this update again."
      exit 1
    fi
  ;; esac

  # 4. Restart onto the new images.
  say "Restarting Headway's services on the new version..."
  blank
  if ! dc up -d 2>&1 | tee -a "$LOG_FILE"; then
    blank
    fail "Docker could not restart the Headway services on the new version."
    fixln "Details are above and in $LOG_FILE. Your data is untouched."
    print_rollback_info "$current" "$target"
    exit 1
  fi

  # 5. Database table updates (idempotent; safe to repeat).
  run_migrations

  # 6. Nothing is declared done until every service reports healthy.
  upgrade_health_gate

  blank
  say "=================================================================="
  say " Headway is updated to $target"
  say "=================================================================="
  blank
  print_rollback_info "$current" "$target"
  say ""
  say "Everything above was recorded (without passwords) in:"
  say "  $LOG_FILE"
  log "upgrade completed: $current -> $target"
}

# =============================================================================
# Main
# =============================================================================

blank
say "Headway installer — $(date '+%Y-%m-%d %H:%M')"
say "A record of this run (with no passwords) is kept in $LOG_FILE"

if [ ! -f "$ENV_EXAMPLE" ]; then
  fail "The template file $ENV_EXAMPLE is missing."
  fixln "This installer must run from inside a complete copy of the Headway"
  fixln "project. Please re-download Headway and try again."
  exit 1
fi

# Modes are one at a time; each promises something different (--check and
# --check-updates promise to change nothing; --upgrade and
# --reconfigure-access exist to change things).
MODES=$((CHECK_ONLY + RECONFIGURE + CHECK_UPDATES + UPGRADE))
if [ "$MODES" -gt 1 ]; then
  fail "Those options cannot be combined. Please run one at a time:"
  fixln "--check, --check-updates, --upgrade, or --reconfigure-access."
  exit 1
fi

if [ "$CHECK_UPDATES" -eq 1 ]; then
  check_updates
  exit 0
fi

if [ "$UPGRADE" -eq 1 ]; then
  run_upgrade
  exit 0
fi

if [ "$RECONFIGURE" -eq 1 ]; then
  reconfigure_access
  exit 0
fi

if [ "$CHECK_ONLY" -eq 1 ]; then
  run_prereq_checks
  blank
  if [ "$FAILURES" -gt 0 ]; then
    say "Result: this computer is NOT ready yet — $FAILURES problem(s) found."
    say "Each problem above includes the exact commands to fix it. Fix them,"
    say "then run './install/install.sh --check' again. Nothing was changed."
    exit 1
  fi
  if [ "$WARNINGS" -gt 0 ]; then
    say "Result: this computer can run Headway, with $WARNINGS warning(s)"
    say "above worth reading. Nothing was changed. When you are ready,"
    say "run: ./install/install.sh"
  else
    say "Result: this computer is ready. Nothing was changed. When you are"
    say "ready, run: ./install/install.sh"
  fi
  exit 0
fi

# Full install. Refuse politely if Headway is already here — before anything
# else, so an existing installation is reported as exactly that (and not as
# a confusing pile of busy-port errors).
detect_existing_install

run_prereq_checks
blank
if [ "$FAILURES" -gt 0 ]; then
  say "The installer stopped before making any changes: $FAILURES problem(s)"
  say "were found above, each with the exact commands to fix it. Fix them,"
  say "then run ./install/install.sh again. You can re-check any time with:"
  say "    ./install/install.sh --check"
  exit 1
fi
if [ "$WARNINGS" -gt 0 ] && [ "$ASSUME_YES" -ne 1 ]; then
  blank
  printf 'There are warnings above. Continue anyway? (yes/no): '
  read -r answer
  case "$answer" in
    y|Y|yes|YES|Yes) : ;;
    *) say "Stopping at your request. Nothing was changed."; exit 0 ;;
  esac
fi

gather_inputs
gather_admin_credentials   # ask everything up front; then no babysitting
write_env_file
start_stack
wait_for_healthy
run_migrations
create_admin_user
print_summary
