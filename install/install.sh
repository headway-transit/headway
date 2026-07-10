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
COMPOSE_DIR="$REPO_DIR/deploy/compose"
ENV_EXAMPLE="$COMPOSE_DIR/.env.example"
ENV_FILE="$COMPOSE_DIR/.env"
LOG_FILE="$SCRIPT_DIR/install.log"

# Files this script creates (the log, .env) are private to your user account.
umask 077

CHECK_ONLY=0
ASSUME_YES=0
FAILURES=0
WARNINGS=0

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
    --help|-h) usage; exit 0 ;;
    *)
      echo "Unknown option: $arg"
      echo "Run './install/install.sh --help' to see the available options."
      exit 1
      ;;
  esac
done

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
log "installer started: check-only=$CHECK_ONLY non-interactive=$ASSUME_YES"

# --- Small utilities ----------------------------------------------------------

dc() { docker compose --project-directory "$COMPOSE_DIR" "$@"; }

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
  say "  - If you want to UPGRADE Headway: an '--upgrade' option is planned"
  say "    for a future release. Until then, please follow the upgrade notes"
  say "    in deploy/compose/README.md, or ask for help (install/README.md,"
  say "    section 'Getting help')."
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
    containers="$(docker ps -aq --filter label=com.docker.compose.project=headway 2>/dev/null || true)"
    if [ -n "$containers" ]; then
      refuse_existing_install \
"Docker containers belonging to a Headway installation (project 'headway')
already exist on this computer:
$(docker ps -a --filter label=com.docker.compose.project=headway --format '  - {{.Names}} ({{.Status}})' 2>/dev/null)"
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

  ok "Configuration file created."
  log "wrote $ENV_FILE (values not logged)"
}

# --- Step 4: start the stack ---------------------------------------------------

start_stack() {
  blank
  say "--- Starting Headway ---"
  say "Docker will now download and start Headway's building blocks: the"
  say "database, the message queue, file storage, metrics and dashboards."
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
  local deadline=$((SECONDS + 420)) all_ok=0
  while [ "$SECONDS" -lt "$deadline" ]; do
    local not_ready=()
    for svc in "${HEALTH_SERVICES[@]}"; do
      local status
      status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
        "headway-$svc-1" 2>/dev/null || echo "not started")"
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
      state="$(docker inspect --format '{{.State.Status}}' "headway-$helper-1" 2>/dev/null || echo missing)"
      [ "$state" = "exited" ] && break
      sleep 5
    done
    code="$(docker inspect --format '{{.State.ExitCode}}' "headway-$helper-1" 2>/dev/null || echo 1)"
    if [ "$state" != "exited" ] || [ "$code" != "0" ]; then
      fail "The one-time setup helper '$helper' did not finish cleanly."
      fixln "See its messages with:"
      fixln "    docker logs headway-$helper-1"
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
      --network headway \
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
      --network headway \
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
  say "Your next steps:"
  say "  1. Read install/README.md — it explains day-to-day basics."
  say "  2. To start collecting your agency's live feed data, see"
  say "     deploy/compose/README.md (the 'app' services, which include the"
  say "     feed collector, are started with:"
  say "     docker compose --project-directory $COMPOSE_DIR --profile app up -d --build )"
  say "  3. The Headway sign-in website/API ships with the app services;"
  say "     your administrator account ('$ADMIN_USERNAME') is already set up"
  say "     and ready for it."
  say ""
  say "Everything above was recorded (without passwords) in:"
  say "  $LOG_FILE"
  log "install completed successfully"
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
