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
RESET_PASSWORD=0
UPDATE_SOURCE=0
DOWNLOAD_BASEMAP=0
CHECK_FEEDS=0
DISCOVER_FEEDS=0
UPGRADE_TARGET=""
FAILURES=0
WARNINGS=0

# --- Basemap download pins (--download-basemap; handoff 0027) -----------------
# The go-pmtiles release the basemap download uses, pinned by version AND
# by the sha256 of each Linux tarball (same rigor as the cosign story in
# --upgrade: nothing downloaded is run before it is verified). Computed
# 2026-07-28 from https://github.com/protomaps/go-pmtiles/releases v1.31.2
# and recorded here; a new version means updating all three lines together.
PMTILES_VERSION="1.31.2"
PMTILES_SHA256_X86_64="3ed7dbf4ec2e6dfe5e25b6f70d1ffc932729f93c86db353bf514dd71010a312f"
PMTILES_SHA256_ARM64="f8bd47e7ea866863489cad588fbaf2f31f42e5821f7a03f009b3769f05801cb1"
# Margin added around the stops' own bounding box, in degrees (~0.1° is
# about 7 miles north-south). Stated to the user before anything downloads.
BASEMAP_MARGIN_DEG="0.10"

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
  ./install/install.sh --update-from-source
                                  For installations that run code built on
                                  this computer (the default when you
                                  installed from a git clone): downloads
                                  the latest Headway source code, applies
                                  any new database updates, rebuilds and
                                  restarts the services, and waits until
                                  everything reports healthy again. Your
                                  data is never touched. Installations
                                  that follow signed releases update with
                                  --upgrade instead.
  ./install/install.sh --download-basemap
                                  Add (or refresh) a street map for your
                                  service area on the Live map page. This
                                  is the ONE Headway feature that fetches
                                  map data from the internet, and it only
                                  ever happens right here, after this
                                  command explains what it will download
                                  and you say yes. The map data is from
                                  OpenStreetMap (© OpenStreetMap
                                  contributors), covers just your agency's
                                  own service area, and is stored on this
                                  computer — the map page itself never
                                  contacts the internet. Safe to re-run
                                  any time you want newer map data.
  ./install/install.sh --check-feeds
                                  Re-check the feed addresses already in
                                  this installation's configuration: each
                                  one is fetched once (only because you ran
                                  this) and must answer and look like the
                                  right kind of feed. Plain-language results;
                                  exits with an error if any feed fails.
                                  This is the first command to run when the
                                  dashboard looks empty.
  ./install/install.sh --discover-feeds
                                  Look your agency up in the MobilityData
                                  Mobility Database (an open, public catalog
                                  of transit feeds) instead of typing feed
                                  addresses by hand. Asks before contacting
                                  the catalog, checks every candidate feed
                                  really answers, and only writes addresses
                                  you approve. The installer offers this
                                  same lookup during a fresh install.
  ./install/install.sh --reset-admin-password
                                  Forgot a Headway sign-in password? This
                                  sets a new one for an existing account,
                                  right here on the server — nothing is
                                  reinstalled and no data is touched. It
                                  asks for the username (and lists the
                                  existing ones if you cannot remember),
                                  then for the new password. The reset is
                                  recorded in Headway's audit trail.
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
    --reset-admin-password) RESET_PASSWORD=1 ;;
    --update-from-source) UPDATE_SOURCE=1 ;;
    --download-basemap) DOWNLOAD_BASEMAP=1 ;;
    --check-feeds) CHECK_FEEDS=1 ;;
    --discover-feeds) DISCOVER_FEEDS=1 ;;
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

# The exact command to install Docker on THIS computer, printed and never
# run. Detected from /etc/os-release (ID and ID_LIKE, so derivatives such as
# Linux Mint or Rocky are covered by their parent), because "follow the
# upstream docs" is the wrong amount of help for the audience this installer
# is written for: one week of Linux, zero SQL. A person who has to work out
# which of five package managers they have has already been handed the
# problem the installer exists to remove.
#
# PRINTED, NEVER RUN. Installing Docker needs root, and this installer's
# standing posture is that it never runs sudo for you (see
# print_firewall_guidance). An installer that silently escalates is one no IT
# department should accept, and `curl | sudo sh` is precisely the pattern
# ADR-0001's posture rejects.
docker_install_hint() {
  local id="" like=""
  if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    id="$(. /etc/os-release 2>/dev/null && printf '%s' "${ID:-}")"
    like="$(. /etc/os-release 2>/dev/null && printf '%s' "${ID_LIKE:-}")"
  fi
  case " $id $like " in
    *" ubuntu "*|*" debian "*|*" linuxmint "*|*" pop "*|*" raspbian "*)
      printf '%s' "sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 docker-buildx" ;;
    *" fedora "*)
      printf '%s' "sudo dnf install -y docker docker-compose-plugin docker-buildx-plugin" ;;
    *" rhel "*|*" centos "*|*" rocky "*|*" almalinux "*)
      printf '%s' "sudo dnf install -y docker docker-compose-plugin docker-buildx-plugin" ;;
    *" opensuse"*|*" suse "*|*" sles "*)
      printf '%s' "sudo zypper install -y docker docker-compose docker-buildx" ;;
    *" arch "*|*" manjaro "*)
      printf '%s' "sudo pacman -S --needed docker docker-compose docker-buildx" ;;
    *)
      printf '%s' "" ;;
  esac
}

check_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    local hint
    hint="$(docker_install_hint)"
    fail "Docker is not installed. Headway runs inside Docker containers,"
    fixln "so Docker is required."
    if [ -n "$hint" ]; then
      fixln "To fix on this computer, run this ONE line, then run the"
      fixln "installer again:"
      fixln ""
      fixln "    $hint"
      fixln "    sudo usermod -aG docker \$USER   # then log out and back in"
      fixln ""
      fixln "Headway will not run that for you: it needs administrator"
      fixln "rights, and this installer never uses them on your behalf."
      fixln "Other options: https://docs.docker.com/engine/install/"
    else
      fixln "To fix: install Docker for your Linux distribution by following"
      fixln "https://docs.docker.com/engine/install/ then run this installer"
      fixln "again. (On Ubuntu, 'sudo snap install docker' also works; this"
      fixln "installer knows how to guide you through snap's extra setup.)"
    fi
    return
  fi
  ok "Docker is installed ($(docker --version 2>/dev/null || echo 'version unknown'))."

  if ! docker compose version >/dev/null 2>&1; then
    fail "The 'docker compose' command is missing. It is the part of Docker"
    fixln "that starts several containers together, and Headway needs it."
    fixln "To fix on Ubuntu/Debian, run ONE of these (which one exists"
    fixln "depends on where your Docker packages came from):"
    fixln "    sudo apt install -y docker-compose-plugin"
    fixln "    sudo apt install -y docker-compose-v2"
    fixln "For other distributions: https://docs.docker.com/compose/install/linux/"
    fixln "Then run this installer again."
  else
    ok "Docker Compose is installed ($(docker compose version --short 2>/dev/null || echo 'version unknown'))."
  fi

  # A WARNING, not a failure: the build genuinely succeeds without buildx —
  # Compose falls back to the classic builder and says so. Found live
  # 2026-08-02 on a clean Ubuntu 26.04 install, where apt's `docker.io` ships
  # no buildx and every `up --build` printed "Docker Compose is configured to
  # build using Bake, but buildx isn't installed". Harmless, and alarming to
  # someone on their first install who has no way to tell harmless from not.
  if ! docker buildx version >/dev/null 2>&1; then
    local buildx_hint
    buildx_hint="$(docker_install_hint)"
    note "Docker's 'buildx' builder is not installed. Headway builds fine"
    fixln "without it — Docker falls back to its older builder — but every"
    fixln "build prints a warning about it. To silence that, install the"
    fixln "buildx package for your system (it is included in the one-line"
    fixln "command above on a fresh install)."
    if [ -n "$buildx_hint" ]; then
      fixln "Nothing is wrong if you skip this."
    fi
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

# Ports published by THIS installation's own containers, one per line.
# Empty when Docker is unavailable or nothing is running — callers treat that
# as "no port is ours", which is the pre-install case and the safe default.
headway_owned_ports() {
  # Docker prints published ports two ways, and BOTH occur in this stack:
  #     127.0.0.1:8000->8000/tcp          a single port
  #     127.0.0.1:9000-9001->9000-9001/tcp   a RANGE (MinIO publishes one)
  # A parser that only understands the first shape silently drops MinIO's two
  # ports and then reports them as somebody else's conflict — which is what the
  # first version of this function did.
  docker ps --filter "name=^/${COMPOSE_PROJECT}-" --format '{{.Ports}}' 2>/dev/null \
    | tr ',' '\n' \
    | awk -F'->' '/->/ {
        split($1, a, ":"); spec = a[length(a)]
        if (spec ~ /^[0-9]+-[0-9]+$/) {
          split(spec, r, "-")
          for (p = r[1]; p <= r[2]; p++) print p
        } else if (spec ~ /^[0-9]+$/) {
          print spec
        }
      }' \
    | sort -un
}

check_ports() {
  local busy=0 ours=0
  # Read once: `docker ps` per port would be eight subprocesses for no reason.
  local owned
  owned="$(headway_owned_ports)"
  for port in "${REQUIRED_PORTS[@]}"; do
    if port_in_use "$port"; then
      # A port held by Headway's OWN container is not a conflict, it is
      # Headway running. Reporting it as a problem told an operator with a
      # perfectly healthy installation that their computer was "NOT ready" —
      # found live 2026-08-02 by running --check on a working install, which
      # is exactly when a worried operator reaches for it.
      if printf '%s\n' "$owned" | grep -qx "$port"; then
        ours=$((ours + 1))
        continue
      fi
      fail "Port $port is already in use. Headway needs it for $(port_label "$port")."
      busy=1
    fi
  done
  if [ "$ours" -gt 0 ] && [ "$busy" -eq 0 ]; then
    ok "All the network ports Headway needs are either free or already in use"
    fixln "by this Headway installation ($ours of ${#REQUIRED_PORTS[@]} in use by"
    fixln "Headway itself, which is what a running installation looks like)."
    return
  fi
  if [ "$ours" -gt 0 ]; then
    note "$ours of the ports listed above are in use by this Headway"
    fixln "installation itself, which is expected while it is running."
  fi
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
GTFS_RT_TU_URL_IN=""
GTFS_RT_SA_URL_IN=""
# Whether typed feed addresses can be live-checked (curl present). When
# not, addresses are still spell-checked and the limit is said out loud.
FEED_LIVE_CHECKS=1

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
    # Feed addresses provided via environment are validated exactly like
    # typed ones (handoff 0037): spelling always; live check unless
    # HEADWAY_FEED_URL_UNCHECKED_OK=yes. A failing address is refused —
    # in unattended mode nobody can say "keep it anyway".
    validate_feed_url_noninteractive HEADWAY_GTFS_STATIC_URL "$GTFS_STATIC_URL_IN" static
    validate_feed_url_noninteractive HEADWAY_GTFS_RT_VEHICLE_POSITIONS_URL "$GTFS_RT_VP_URL_IN" realtime
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

  if ! command -v curl >/dev/null 2>&1; then
    FEED_LIVE_CHECKS=0
    warn "The 'curl' tool is missing, so feed addresses can only be"
    fixln "spell-checked now, not fetched to prove they answer."
    fixln "To fix on Ubuntu/Debian:   sudo apt install curl"
    fixln "(./install/install.sh --check-feeds can re-check them later.)"
  fi

  say ""
  say "2) Your agency's data feeds. Headway can LOOK THESE UP for you: with"
  say "   your consent (explained first), it searches the MobilityData"
  say "   Mobility Database — an open, public catalog of transit feeds —"
  say "   checks that every address it finds really answers, and saves only"
  say "   what you approve. Or you can type the addresses yourself."
  local lookup_answer
  if [ "$FEED_LIVE_CHECKS" -eq 1 ]; then
    printf '   Look your agency up in the public catalog? (yes/no) [yes]: '
    read -r lookup_answer
    case "${lookup_answer:-yes}" in
      y|Y|yes|YES|Yes)
        if discover_feeds_flow; then
          GTFS_STATIC_URL_IN="$DISCOVERED_STATIC"
          GTFS_RT_VP_URL_IN="$DISCOVERED_VP"
          GTFS_RT_TU_URL_IN="$DISCOVERED_TU"
          GTFS_RT_SA_URL_IN="$DISCOVERED_SA"
        else
          say ""
          say "   No problem — the addresses can also be typed by hand below,"
          say "   or added later in deploy/compose/.env."
        fi
        ;;
      *) : ;;
    esac
  else
    note "Skipping the catalog lookup (it needs curl, see above)."
  fi

  if [ -z "$GTFS_STATIC_URL_IN" ]; then
    say ""
    say "   (Optional) Your agency's GTFS schedule feed. GTFS is the standard"
    say "   file format for transit schedules — most agencies already publish"
    say "   one for trip planners like Google Maps. It is a web address ending"
    say "   in .zip. If you do not know it, just press Enter to skip; you can"
    say "   add it later in deploy/compose/.env."
    prompt_feed_url '   GTFS schedule address (or press Enter to skip): ' static GTFS_STATIC_URL_IN
  fi

  if [ -z "$GTFS_RT_VP_URL_IN" ]; then
    say ""
    say "   (Optional) Your agency's GTFS-Realtime vehicle positions feed."
    say "   This is a live web address that reports where your vehicles are"
    say "   right now — it usually comes from your AVL/CAD vendor. Press"
    say "   Enter to skip if you do not know it."
    prompt_feed_url '   Vehicle positions address (or press Enter to skip): ' realtime GTFS_RT_VP_URL_IN
  fi
  log "feed urls entered (static: $([ -n "$GTFS_STATIC_URL_IN" ] && echo provided || echo skipped), vehicle positions: $([ -n "$GTFS_RT_VP_URL_IN" ] && echo provided || echo skipped), trip updates: $([ -n "$GTFS_RT_TU_URL_IN" ] && echo provided || echo skipped), alerts: $([ -n "$GTFS_RT_SA_URL_IN" ] && echo provided || echo skipped))"

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

# Keep the running services' logs BEFORE anything recreates their containers.
#
# Docker container logs die with the container, and an update rebuilds every
# one of them. So the operation an operator runs to FIX a problem is the
# operation that destroys the evidence of it — found live 2026-08-03, when a
# partner agency ran --update-from-source to pick up an adapter fix and it
# took with it the transform logs holding the reason their file had produced
# no rows. There was nothing left to read.
#
# Written beside install.log, which is already the durable host-side record of
# an installer run. Bounded by --tail so a chatty service cannot fill the disk
# on the way out, and NEVER fatal: a failure to keep logs must not stop an
# update the operator needs.
LOG_KEEP_LINES=20000

#: How many captures to keep. Bounding the container logs and then leaving an
#: unbounded pile of copies of them would be the same bug one level up — a
#: single capture measured 3.9 MB on a one-day-old installation, and an update
#: can be run many times in a week.
LOG_KEEP_CAPTURES=10

capture_service_logs() {
  local reason="$1"
  local dir="$SCRIPT_DIR/logs"
  local stamp
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  local dest="$dir/$stamp-$reason.log"

  mkdir -p "$dir" 2>/dev/null || {
    note "Could not create $dir, so the current logs were not kept."
    return 0
  }
  # 2>&1 into the file: compose writes its own diagnostics to stderr, and a
  # log capture that drops them is the half you need when it went wrong.
  if docker compose --project-directory "$COMPOSE_DIR" logs \
       --no-color --timestamps --tail "$LOG_KEEP_LINES" > "$dest" 2>&1; then
    ok "Kept the current service logs: $dest"
    say "         Container logs are erased when services are rebuilt, so this"
    say "         copy is what remains of what happened before this run."
  else
    note "Could not read the current service logs; continuing anyway."
    rm -f "$dest" 2>/dev/null
  fi

  # Keep the newest LOG_KEEP_CAPTURES and delete the rest. Timestamped names
  # sort chronologically, so this needs no date parsing. Deletes only files
  # this function created — the glob is anchored to its own naming.
  local old_captures
  old_captures="$(ls -1 "$dir"/*-*.log 2>/dev/null | sort | head -n -"$LOG_KEEP_CAPTURES")"
  if [ -n "$old_captures" ]; then
    printf '%s\n' "$old_captures" | while IFS= read -r stale; do
      rm -f "$stale" 2>/dev/null
    done
  fi
  return 0
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
    add_compose_profile lan
  else
    set_env_value HEADWAY_LAN_ADDRESS ""
    set_env_value HEADWAY_CORS_ORIGINS ""
    set_env_value VITE_API_BASE_URL "http://localhost:8000"
    remove_compose_profile lan
  fi
  # EVERY mode, not just lan. Until 2026-08-02 this lived inside the lan
  # branch, so the DEFAULT install ('local') brought up the database, queue,
  # storage and dashboards and no Headway: no website, no API, no collector.
  # The installer then reported "All services are healthy" (true of the ones
  # it started), said "Only web browsers on this machine can reach it", and
  # exited 0. Found on the first cold-machine install, 2026-08-02 — the
  # access mode answers WHO may reach Headway, never WHETHER it runs.
  add_compose_profile app
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
  # Trip updates + service alerts arrive only via the catalog lookup today
  # (handoff 0037: v0 offers all three realtime feed types when the
  # registry has them and they verify).
  [ -n "$GTFS_RT_TU_URL_IN" ] && set_env_value GTFS_RT_TRIP_UPDATES_URL "$GTFS_RT_TU_URL_IN"
  [ -n "$GTFS_RT_SA_URL_IN" ] && set_env_value GTFS_RT_ALERTS_URL "$GTFS_RT_SA_URL_IN"

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
  say "The Headway website, its sign-in service and the feed collector are"
  say "built from source on this computer and started too."
  if [ "$ACCESS_MODE" = "lan" ]; then
    say "Because you chose office access, the secure office doorway is"
    say "started alongside them."
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

# --- Password reset (--reset-admin-password) -------------------------------------
# The same one-off-container machinery as create_admin_user: the new password
# is bcrypt-hashed INSIDE the helper container and only the hash reaches the
# database. Being able to run this is what having admin access to the server
# means — the same trust level as reading deploy/compose/.env. Every reset is
# recorded in Headway's append-only audit trail.

reset_admin_password() {
  blank
  say "--- Resetting a Headway sign-in password ---"
  say "This sets a new password for an existing Headway account on this"
  say "server. Nothing is reinstalled and no data is touched."
  blank

  local pg_pass
  pg_pass="$(read_env_value POSTGRES_PASSWORD)"
  if [ -z "$pg_pass" ]; then
    fail "No Headway installation was found on this computer (there is no"
    fixln "database password in deploy/compose/.env). If Headway was never"
    fixln "installed here, run ./install/install.sh first."
    exit 1
  fi
  if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -q 'timescaledb'; then
    fail "Headway's database container is not running, so the password"
    fixln "cannot be changed right now. Start Headway first:"
    fixln "    docker compose --project-directory deploy/compose --profile app up -d"
    fixln "then run this command again."
    exit 1
  fi

  local reset_username
  while true; do
    printf '   Which username needs a new password? '
    read -r reset_username
    if printf '%s' "$reset_username" | grep -Eq '^[A-Za-z0-9._-]+$'; then
      break
    fi
    say "   Please use only letters, numbers, dots, hyphens or underscores."
  done

  local new_password
  while true; do
    printf '   Choose the new password (at least 8 characters; it will not be shown as you type): '
    read -rs new_password; printf '\n'
    if [ "${#new_password}" -lt 8 ]; then
      say "   That password is too short. Please use at least 8 characters."
      continue
    fi
    if [ "$(printf '%s' "$new_password" | wc -c)" -gt 72 ]; then
      say "   That password is too long (the sign-in system supports up to"
      say "   72 characters). Please choose a shorter one."
      continue
    fi
    printf '   Type the same password again to confirm: '
    local confirm; read -rs confirm; printf '\n'
    if [ "$new_password" = "$confirm" ]; then break; fi
    say "   The two passwords did not match. Let's try again."
  done
  log "password reset requested for username '$reset_username' (password not logged)"

  local pg_user pg_db
  pg_user="$(read_env_value POSTGRES_USER)"; pg_user="${pg_user:-headway}"
  pg_db="$(read_env_value POSTGRES_DB)";     pg_db="${pg_db:-headway}"

  if ! PGPASSWORD="$pg_pass" \
       HEADWAY_RESET_USERNAME="$reset_username" \
       HEADWAY_RESET_PASSWORD="$new_password" \
       docker run --rm -i \
      --network "$(compose_network)" \
      -e PGHOST=timescaledb \
      -e PGPORT=5432 \
      -e PGUSER="$pg_user" \
      -e PGPASSWORD \
      -e PGDATABASE="$pg_db" \
      -e HEADWAY_RESET_USERNAME \
      -e HEADWAY_RESET_PASSWORD \
      python:3.12-slim \
      bash -c "pip install -q bcrypt 'psycopg[binary]' && python -" \
      <<'PYEOF' 2>&1 | tee -a "$LOG_FILE"; then
import json, os, sys
import bcrypt
import psycopg

username = os.environ["HEADWAY_RESET_USERNAME"]
password = os.environ["HEADWAY_RESET_PASSWORD"].encode("utf-8")

# bcrypt reads only the first 72 bytes; reject loudly rather than truncate
# (same rule as services/api/headway_api/auth.py).
if len(password) > 72:
    print("PROBLEM  The password is longer than 72 bytes, which the sign-in")
    print("         system does not support. Please choose a shorter one.")
    sys.exit(1)

password_hash = bcrypt.hashpw(password, bcrypt.gensalt()).decode("ascii")

with psycopg.connect() as conn:  # connection settings come from PG* variables
    cur = conn.execute(
        "UPDATE auth.users SET password_hash = %s WHERE username = %s",
        (password_hash, username),
    )
    if cur.rowcount == 0:
        rows = conn.execute(
            "SELECT username, role FROM auth.users ORDER BY username"
        ).fetchall()
        print(f"PROBLEM  No account named '{username}' exists in this Headway")
        print("         database, so nothing was changed. The accounts that")
        print("         DO exist here are:")
        for name, role in rows:
            print(f"             {name}  ({role.replace('_', ' ')})")
        print("         Run this command again with one of those usernames.")
        sys.exit(1)
    conn.execute(
        "INSERT INTO audit.events (actor, action, subject_kind, subject_id, detail) "
        "VALUES (%s, 'password_reset', 'auth.users', %s, %s)",
        (
            username,
            username,
            json.dumps({"method": "install.sh --reset-admin-password"}),
        ),
    )
    conn.commit()
    print(f"OK       The password for '{username}' has been changed. Sign in")
    print("         with the new password from now on. This reset was")
    print("         recorded in Headway's audit trail.")
PYEOF
    blank
    fail "The password reset did not complete. The details are just above"
    fixln "and in $LOG_FILE. Nothing was changed unless the OK message"
    fixln "printed."
    exit 1
  fi
}

# --- Source update (--update-from-source) ----------------------------------------
# For git-clone installations that build their images locally (the default:
# HEADWAY_IMAGE_TAG unset or "local"). Release-following installations are
# refused and pointed at --upgrade — the two update stories must never blur.
# Order matters: migrations run BEFORE the rebuild so old code (which ignores
# new columns — migrations are additive by policy) briefly runs against the
# new schema, never new code against the old schema.

update_from_source() {
  blank
  say "--- Updating Headway from source ---"

  local pg_pass tag
  pg_pass="$(read_env_value POSTGRES_PASSWORD)"
  if [ -z "$pg_pass" ]; then
    fail "No Headway installation was found on this computer (there is no"
    fixln "database password in deploy/compose/.env). If Headway was never"
    fixln "installed here, run ./install/install.sh first."
    exit 1
  fi
  tag="$(read_env_value HEADWAY_IMAGE_TAG)"
  if [ -n "$tag" ] && [ "$tag" != "local" ]; then
    fail "This installation runs signed release images (version $tag), not"
    fixln "code built on this computer. To update it, use:"
    fixln "    ./install/install.sh --upgrade"
    exit 1
  fi
  if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -q 'timescaledb'; then
    fail "Headway's database container is not running, so database updates"
    fixln "cannot be applied. Start Headway first:"
    fixln "    docker compose --project-directory deploy/compose --profile app up -d"
    fixln "then run this command again."
    exit 1
  fi

  say "This will do four things, in order:"
  say "  1. Download the latest Headway source code (git pull)."
  say "  2. Apply any new database updates (your data is never touched)."
  say "  3. Rebuild and restart the Headway services."
  say "  4. Wait until every service reports healthy again."
  blank

  local before after
  before="$(git -C "$REPO_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  if ! git -C "$REPO_DIR" pull --ff-only 2>&1 | tee -a "$LOG_FILE"; then
    blank
    fail "Downloading the latest source code failed (the details are just"
    fixln "above). The most common cause is a local change to a Headway"
    fixln "file on this computer. See what changed with:"
    fixln "    git -C \"$REPO_DIR\" status"
    fixln "Nothing on this computer has been modified by this command."
    exit 1
  fi
  after="$(git -C "$REPO_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  if [ "$before" = "$after" ]; then
    note "The source code was already the newest available ($after)."
    note "Checking the database and services anyway — this also finishes a"
    note "previous update that stopped partway."
  else
    ok "Source code updated: $before -> $after."
  fi

  run_migrations

  # Retro-fix for installations from before handoff 0037: Docker used to
  # create the drop-folder mounts itself, owned by root, which the
  # collector's locked-down account (uid 65532) cannot use. Detect and
  # offer the least-privilege repair before the services restart.
  ensure_drop_dirs update

  # BEFORE the rebuild: the containers about to be replaced are the only
  # place their own history exists.
  capture_service_logs "before-update"

  blank
  say "--- Rebuilding and restarting the Headway services ---"
  say "This is the slowest step (a few minutes of compiling)."
  if ! docker compose --project-directory "$COMPOSE_DIR" --profile app up -d --build 2>&1 | tee -a "$LOG_FILE"; then
    blank
    fail "Rebuilding the services failed (the details are just above and in"
    fixln "$LOG_FILE). Your data is untouched. The services keep running"
    fixln "the previous version wherever the rebuild did not reach."
    exit 1
  fi

  wait_for_healthy

  # Every source update rebuilds images, and each rebuild strands the
  # previous build's layers and build cache on disk — invisible in any
  # Headway data folder, but real growth (found live 2026-07-29: an agency
  # VM exhausted its 150 GB virtual-disk provisioning largely through
  # rebuild churn). Prune ONLY what nothing references: dangling images
  # (tagged images — including release images a rollback needs — are never
  # touched) and the builder cache (safe; the only cost is a slower next
  # rebuild). Cleanup failure never fails an otherwise-good update.
  blank
  say "--- Reclaiming disk space left by previous updates ---"
  say "Old image layers and build cache from earlier rebuilds are removed."
  say "Running services and your data are never touched by this step."
  if ! docker image prune -f 2>&1 | tail -1 | tee -a "$LOG_FILE"; then
    note "Image cleanup could not run; skipped (the update itself is fine)."
  fi
  if ! docker builder prune -f 2>&1 | tail -1 | tee -a "$LOG_FILE"; then
    note "Build-cache cleanup could not run; skipped (the update is fine)."
  fi

  blank
  say "=================================================================="
  say " Update complete — Headway is running version $after"
  say "=================================================================="
  say "Everything came back healthy. Your data, accounts and settings are"
  say "exactly as they were. If a page in the browser looks odd after an"
  say "update, reload it once (Ctrl+Shift+R) to pick up the new version."
}

# --- Basemap download (--download-basemap) ---------------------------------------
# Design contract: docs/handoffs/0027-from-platform-to-frontend-devops-basemap.md.
# Plain-language guide for agencies: docs/basemap.md.
#
# Consent posture, same as --check-updates/--upgrade: Headway NEVER fetches
# map data on its own. This command states plainly what it will download and
# from where, BEFORE any network contact, and only acts after you say yes.
# Re-running it later (for newer map data) is the same consent again.
# Everything downloaded is verified (pinned sha256) before it runs, and the
# map file is written atomically — a failed run leaves nothing half-written.

# The area to download, filled by basemap_choose_area (west,south,east,north).
BM_WEST=""; BM_SOUTH=""; BM_EAST=""; BM_NORTH=""

# Validate "a decimal number" without surprises (leading -, one dot).
is_number() { printf '%s' "$1" | grep -Eq '^-?[0-9]+(\.[0-9]+)?$'; }

# Ask for the four map-area numbers by hand (the fallback when no stop
# coordinates exist yet, or the computed box is refused). Plain words first.
basemap_ask_area() {
  say ""
  say "   Please type the map area as four numbers separated by commas:"
  say "       west,south,east,north"
  say "   'West' and 'east' are longitudes (east-west position, -180 to 180,"
  say "   negative in the Americas); 'south' and 'north' are latitudes"
  say "   (north-south position, -90 to 90). Any map website shows these —"
  say "   right-click a spot southwest of your service area for the first"
  say "   two, northeast of it for the last two."
  say "   Example (the Tri-Cities area of Washington state):"
  say "       -119.55,46.05,-118.85,46.45"
  local typed w s e n
  while true; do
    printf '   Map area (west,south,east,north): '
    read -r typed
    w="$(printf '%s' "$typed" | cut -d, -f1 | tr -d ' ')"
    s="$(printf '%s' "$typed" | cut -d, -f2 | tr -d ' ')"
    e="$(printf '%s' "$typed" | cut -d, -f3 | tr -d ' ')"
    n="$(printf '%s' "$typed" | cut -d, -f4 | tr -d ' ')"
    if is_number "$w" && is_number "$s" && is_number "$e" && is_number "$n" \
       && awk -v w="$w" -v s="$s" -v e="$e" -v n="$n" \
         'BEGIN { exit !(w >= -180 && e <= 180 && w < e && s >= -90 && n <= 90 && s < n) }'; then
      BM_WEST="$w"; BM_SOUTH="$s"; BM_EAST="$e"; BM_NORTH="$n"
      return 0
    fi
    say "   That does not look like a valid area. Four numbers, separated by"
    say "   commas; west smaller than east, south smaller than north."
  done
}

# Compute the area from the agency's OWN stop coordinates (canonical.stops)
# via the standard one-off container psql pattern, plus the stated margin.
# Falls back to asking when there are no stops (or no reachable database).
basemap_choose_area() {
  local bbox_row="" count="" minlon="" minlat="" maxlon="" maxlat=""
  if docker info >/dev/null 2>&1 \
     && docker ps --format '{{.Names}}' 2>/dev/null | grep -q 'timescaledb'; then
    local pg_user pg_db pg_pass
    pg_user="$(read_env_value POSTGRES_USER)"; pg_user="${pg_user:-headway}"
    pg_db="$(read_env_value POSTGRES_DB)";     pg_db="${pg_db:-headway}"
    pg_pass="$(read_env_value POSTGRES_PASSWORD)"
    # PGPASSWORD travels via environment inheritance; never on a command line.
    bbox_row="$(PGPASSWORD="$pg_pass" docker run --rm \
      --network "$(compose_network)" \
      -e PGHOST=timescaledb -e PGPORT=5432 \
      -e PGUSER="$pg_user" -e PGPASSWORD -e PGDATABASE="$pg_db" \
      timescale/timescaledb:latest-pg16 \
      psql -Atc "SELECT count(*), min(longitude), min(latitude), max(longitude), max(latitude) FROM canonical.stops WHERE longitude IS NOT NULL AND latitude IS NOT NULL" \
      2>>"$LOG_FILE" || true)"
    count="$(printf '%s' "$bbox_row" | cut -d'|' -f1)"
    minlon="$(printf '%s' "$bbox_row" | cut -d'|' -f2)"
    minlat="$(printf '%s' "$bbox_row" | cut -d'|' -f3)"
    maxlon="$(printf '%s' "$bbox_row" | cut -d'|' -f4)"
    maxlat="$(printf '%s' "$bbox_row" | cut -d'|' -f5)"
  else
    note "Headway's database is not running right now, so the map area"
    fixln "cannot be read from your stop locations. You can type it instead."
  fi

  if [ -n "$count" ] && [ "$count" -gt 0 ] 2>/dev/null \
     && is_number "$minlon" && is_number "$minlat" \
     && is_number "$maxlon" && is_number "$maxlat"; then
    # The stops' own box + the stated margin, rounded to 4 decimal places.
    BM_WEST="$(awk -v v="$minlon" -v m="$BASEMAP_MARGIN_DEG" 'BEGIN { printf "%.4f", v - m }')"
    BM_SOUTH="$(awk -v v="$minlat" -v m="$BASEMAP_MARGIN_DEG" 'BEGIN { printf "%.4f", v - m }')"
    BM_EAST="$(awk -v v="$maxlon" -v m="$BASEMAP_MARGIN_DEG" 'BEGIN { printf "%.4f", v + m }')"
    BM_NORTH="$(awk -v v="$maxlat" -v m="$BASEMAP_MARGIN_DEG" 'BEGIN { printf "%.4f", v + m }')"
    say ""
    say "Your map area, read from your own data: this installation has"
    say "$count stops with coordinates, spanning"
    say "    longitude $minlon to $maxlon, latitude $minlat to $maxlat."
    say "With a margin of about 7 miles ($BASEMAP_MARGIN_DEG degrees) around the"
    say "edge, the map would cover:"
    say "    west $BM_WEST   south $BM_SOUTH   east $BM_EAST   north $BM_NORTH"
    log "basemap area from canonical.stops: $count stops, bbox $BM_WEST,$BM_SOUTH,$BM_EAST,$BM_NORTH"
    local answer
    printf 'Use this area? (yes = use it / no = type a different one): '
    read -r answer
    case "$answer" in
      y|Y|yes|YES|Yes) return 0 ;;
      *) basemap_ask_area ;;
    esac
  else
    if [ "${count:-}" = "0" ]; then
      say ""
      say "No stops with coordinates exist in this installation yet (the map"
      say "area is normally read from your own schedule data). You can type"
      say "the area instead — or ingest your GTFS schedule first and re-run"
      say "this command to have it computed for you."
    fi
    basemap_ask_area
  fi

  # A very large area means a very large download; say so before consent.
  if awk -v w="$BM_WEST" -v e="$BM_EAST" -v s="$BM_SOUTH" -v n="$BM_NORTH" \
       'BEGIN { exit !((e - w) > 5 || (n - s) > 5) }'; then
    warn "That area is more than 5 degrees across — several hundred miles."
    fixln "The download will be much larger than the typical 10–50 MB, and"
    fixln "Headway's map only needs your service area. Consider re-running"
    fixln "with a smaller area unless this is intended."
  fi
}

download_basemap() {
  blank
  say "--- Adding a street map for your service area ---"

  if [ ! -f "$ENV_FILE" ]; then
    fail "No Headway configuration file was found at"
    fixln "$ENV_FILE, so there is no installation to add a"
    fixln "map to. To install Headway first, run: ./install/install.sh"
    exit 1
  fi
  if [ "$ASSUME_YES" -eq 1 ]; then
    fail "This command downloads map data from the internet, so it always"
    fixln "asks a person for consent first — it cannot run with --yes."
    fixln "Run it without --yes and answer the questions."
    exit 1
  fi
  require_curl

  local arch sha
  case "$(uname -m)" in
    x86_64|amd64)  arch="x86_64"; sha="$PMTILES_SHA256_X86_64" ;;
    aarch64|arm64) arch="arm64";  sha="$PMTILES_SHA256_ARM64" ;;
    *)
      fail "This computer's processor type ($(uname -m)) has no pinned"
      fixln "map-extract tool build. Headway supports x86_64 and arm64 here."
      fixln "See docs/basemap.md for the air-gapped path (run the extract on"
      fixln "another computer and copy the file in)."
      exit 1
      ;;
  esac

  local basemap_dir="$COMPOSE_DIR/basemap"
  local basemap_file="$basemap_dir/region.pmtiles"
  mkdir -p "$basemap_dir"
  # Unlike everything else this installer writes (umask 077 — private), the
  # basemap is PUBLIC map data the web container's own nginx user must be
  # able to read through the read-only mount. World-readable, deliberately.
  # (Found live 2026-07-28: a 600 file answers 403 through nginx.)
  chmod 755 "$basemap_dir"

  # WHAT this does — stated plainly BEFORE any network contact.
  say ""
  say "Headway's Live map normally draws only your own data. This command"
  say "adds a street map background for your service area. Here is exactly"
  say "what will happen, and nothing else:"
  say ""
  say "  1. It figures out the map area from your own stop locations (or"
  say "     asks you), and shows it to you before anything downloads."
  say "  2. With your consent, it contacts the internet ONCE, for two"
  say "     things: the map-extract tool from github.com (about 17 MB,"
  say "     checked against a pinned fingerprint before it is run), and"
  say "     your area's map data from build.protomaps.com (usually"
  say "     10–50 MB for a service area)."
  say "  3. The map data is saved as one file on this computer:"
  say "     $basemap_file"
  say "     After that, Headway never contacts either site again — the map"
  say "     page serves the file from this computer only. When you want"
  say "     newer map data (new streets get built), re-run this command."
  say ""
  say "The map data is from OpenStreetMap, © OpenStreetMap contributors,"
  say "under the Open Database License; the map will always display that"
  say "credit. The extract comes from Protomaps' daily build of it."
  say ""

  if [ -f "$basemap_file" ]; then
    local existing_size existing_date
    existing_size="$(du -h "$basemap_file" 2>/dev/null | cut -f1)"
    existing_date="$(date -r "$basemap_file" '+%Y-%m-%d' 2>/dev/null || echo unknown)"
    say "A street map already exists on this computer ($existing_size,"
    say "downloaded $existing_date). You can keep it or replace it with"
    say "fresh map data."
    local keep_answer
    printf 'Replace it with fresh map data? (yes = replace / no = keep it): '
    read -r keep_answer
    case "$keep_answer" in
      y|Y|yes|YES|Yes) : ;;
      *)
        say "Keeping the existing map. Nothing was downloaded or changed."
        log "download-basemap: kept existing $basemap_file"
        exit 0
        ;;
    esac
  fi

  basemap_choose_area

  say ""
  say "Ready to download. One more time, in one line: this contacts"
  say "github.com and build.protomaps.com once, downloads the map for the"
  say "area above, saves it on this computer, and never phones anywhere"
  say "again."
  local consent
  printf 'Download the map now? (yes/no): '
  read -r consent
  case "$consent" in
    y|Y|yes|YES|Yes) : ;;
    *)
      say "Stopping at your request. Nothing was downloaded; nothing changed."
      log "download-basemap: consent declined"
      exit 0
      ;;
  esac
  log "download-basemap: consent given for bbox $BM_WEST,$BM_SOUTH,$BM_EAST,$BM_NORTH"

  # Everything below is network + temp files. The workspace lives INSIDE
  # the basemap directory so the final move is an atomic same-filesystem
  # rename; any failure leaves the old map (if any) untouched.
  local workdir
  workdir="$(mktemp -d "$basemap_dir/.download.XXXXXX")"
  # shellcheck disable=SC2064
  trap "rm -rf '$workdir'" EXIT

  # 1. The most recent available daily build: probe today, step back a few
  # days (the day's build appears partway through the day, UTC).
  blank
  say "--- Finding the most recent map-data build ---"
  local build_day="" d candidate
  for d in 0 1 2 3 4; do
    candidate="$(date -u -d "-$d day" '+%Y%m%d')"
    if curl -sIf --max-time 20 "https://build.protomaps.com/$candidate.pmtiles" >/dev/null 2>&1; then
      build_day="$candidate"
      break
    fi
  done
  if [ -z "$build_day" ]; then
    fail "No daily map-data build from the last 5 days answered at"
    fixln "build.protomaps.com. Usually this means no internet connection"
    fixln "from this computer, or the site is briefly unreachable. Nothing"
    fixln "was changed; try again later."
    exit 1
  fi
  ok "Using the map-data build of $build_day."
  log "download-basemap: daily build $build_day"

  # 2. The map-extract tool, pinned version + pinned sha256. Nothing
  # downloaded is run before its fingerprint matches.
  blank
  say "--- Downloading the map-extract tool (verified before use) ---"
  local tool_url="https://github.com/protomaps/go-pmtiles/releases/download/v$PMTILES_VERSION/go-pmtiles_${PMTILES_VERSION}_Linux_$arch.tar.gz"
  if ! curl -fL --max-time 300 -o "$workdir/go-pmtiles.tar.gz" "$tool_url" 2>>"$LOG_FILE"; then
    fail "Downloading the map-extract tool failed (the address was"
    fixln "$tool_url )."
    fixln "Nothing was changed; it is safe to run this command again."
    exit 1
  fi
  if ! printf '%s  %s\n' "$sha" "$workdir/go-pmtiles.tar.gz" | sha256sum -c --quiet - >>"$LOG_FILE" 2>&1; then
    fail "The downloaded map-extract tool does NOT match the fingerprint"
    fixln "pinned in this installer, so Headway refuses to run it and has"
    fixln "deleted it. That can be a corrupted download — or someone"
    fixln "offering you software that is not the real tool. Try again; if"
    fixln "it keeps failing, report it (SECURITY.md) — do not work around"
    fixln "it."
    exit 1
  fi
  ok "The tool's fingerprint matches the one pinned in this installer."
  tar -xzf "$workdir/go-pmtiles.tar.gz" -C "$workdir" pmtiles
  chmod +x "$workdir/pmtiles"
  log "download-basemap: go-pmtiles v$PMTILES_VERSION ($arch) verified sha256=$sha"

  # 3. The extract itself: only the tiles inside the area are fetched (the
  # tool reads the big planet file with ranged requests — it does NOT
  # download the whole planet).
  blank
  say "--- Downloading your area's map data ---"
  say "(This reads just your area out of the big daily map file — the whole"
  say "file is never downloaded.)"
  blank
  if ! "$workdir/pmtiles" extract "https://build.protomaps.com/$build_day.pmtiles" \
      "$workdir/region.pmtiles" \
      --bbox="$BM_WEST,$BM_SOUTH,$BM_EAST,$BM_NORTH" 2>&1 | tee -a "$LOG_FILE"; then
    blank
    fail "Downloading the map data failed (details above and in $LOG_FILE)."
    fixln "Any existing map on this computer is untouched. It is safe to"
    fixln "run this command again."
    exit 1
  fi

  # 4. Sanity-check the produced archive before it replaces anything.
  if ! "$workdir/pmtiles" show "$workdir/region.pmtiles" >>"$LOG_FILE" 2>&1; then
    fail "The downloaded map file did not verify as a readable map archive."
    fixln "Any existing map on this computer is untouched. It is safe to"
    fixln "run this command again. Details are in $LOG_FILE."
    exit 1
  fi

  # 5. Atomic move into place (same filesystem, single rename). Readable by
  # everyone FIRST — it is public map data, and the web container's nginx
  # user reads it through the mount (the umask-077 default would 403).
  chmod 644 "$workdir/region.pmtiles"
  mv -f "$workdir/region.pmtiles" "$basemap_file"
  local final_size
  final_size="$(du -h "$basemap_file" | cut -f1)"
  ok "Street map saved: $basemap_file ($final_size)."
  log "download-basemap: wrote $basemap_file ($final_size, build $build_day)"

  blank
  say "=================================================================="
  say " The street map is ready"
  say "=================================================================="
  say ""
  say "Open the Live map page and reload it (Ctrl+Shift+R): streets appear"
  say "under your stops and routes, with the OpenStreetMap credit shown on"
  say "the map. No internet connection is used to draw it — ever."
  say ""
  say "If Headway's website was already running when you ran this command"
  say "for the FIRST time after updating Headway, refresh the services once"
  say "so the website container can see the new file:"
  say "    docker compose --project-directory $COMPOSE_DIR --profile app up -d"
  say ""
  say "When you want newer map data (streets change slowly — once or twice"
  say "a year is plenty), just run this command again. The full story, and"
  say "the path for computers with no internet access, is in"
  say "docs/basemap.md."
}

# --- Feed-address validation, --check-feeds, drop folders, --discover-feeds ------
# Design contract: docs/handoffs/0037-…-first-mile-hardening.md. Every rule
# here is a real first-mile failure from a live agency install: a pasted
# URL with 'https//' (no colon), a typo inside a pasted path, a drop folder
# the collector's locked-down account could not write, and 'chmod 777' as
# field advice. The posture: no address is written to .env until it has
# been checked — spelling first, then a live fetch the operator is told
# about — and no failing address is ever written silently.

# Check the SPELLING of a feed web address (no network). Returns 0 when it
# looks like a well-formed http(s) address; otherwise sets SYNTAX_PROBLEM
# to a plain-language description — the typos we have actually seen in the
# field are named specifically, never just "invalid URL" — and returns 1.
SYNTAX_PROBLEM=""
feed_url_syntax_ok() {
  local url="$1"
  SYNTAX_PROBLEM=""
  case "$url" in
    *" "*|*$'\t'*)
      SYNTAX_PROBLEM="the address contains a space. Web addresses never do — usually the copy-and-paste picked up an extra piece, or two pieces of the address got separated. Please paste it as one unbroken line." ;;
    https//*|http//*)
      SYNTAX_PROBLEM="there is a colon missing near the start. It begins '${url%%//*}//' but web addresses start 'https://' — colon first, then the two slashes." ;;
    https:/[!/]*|http:/[!/]*)
      SYNTAX_PROBLEM="the start of the address is one slash short. Web addresses start 'https://' with two slashes after the colon." ;;
    https://*|http://*)
      local rest="${url#*://}"
      case "$rest" in
        ""|/*) SYNTAX_PROBLEM="there is nothing after the 'https://' — the website part of the address is missing." ;;
        *.*)   return 0 ;;
        *)     SYNTAX_PROBLEM="the part right after https:// ('$rest') does not look like a website name (it has no dot in it). Please compare it with the address your vendor or IT contact gave you." ;;
      esac ;;
    *://*)
      SYNTAX_PROBLEM="it starts with '${url%%://*}://', which is not a kind of address Headway can fetch. Feed addresses start with https:// (or http://)." ;;
    *)
      SYNTAX_PROBLEM="it does not start with https:// — the front part of the address is probably missing. Feed addresses begin with https://" ;;
  esac
  [ -z "$SYNTAX_PROBLEM" ]
}

# Live-check one feed address: SAY what is being fetched, fetch it once,
# and confirm the answer looks like the right kind of feed.
#   $1 = url    $2 = kind: static (GTFS zip) | realtime (GTFS-Realtime)
# Returns 0 verified (an OK line was printed); 1 failed (a plain-words
# explanation of what was checked and the likely cause was printed).
#
# HONEST LIMIT, recorded: this is a bash-level shape check, not a full
# parse. A schedule feed must answer with the ZIP file signature ('PK');
# a realtime feed must answer with binary protobuf whose first byte is the
# GTFS-Realtime FeedMessage's required header field tag (0x0a). The real
# decode happens in the ingestion service; this check exists to catch
# typos and wrong-address mistakes at the moment they are typed.
feed_live_check() {
  local url="$1" kind="$2" label
  case "$kind" in
    static) label="schedule file" ;;
    *)      label="live feed" ;;
  esac
  say "   Checking the feed…"
  say "   (fetching $url once, now, only because you gave Headway this address)"
  local tmp code="" rc=0 size=0
  tmp="$(mktemp)"
  # --range asks for only the first 2 KB (plenty for a file signature);
  # servers that ignore ranges send the whole file, so size and time are
  # capped as well. A timeout or size-cap stop with bytes already received
  # still lets the signature check run.
  code="$(curl -fsSL --max-time 45 --max-filesize 268435456 --range 0-2047 \
          -o "$tmp" -w '%{http_code}' "$url" 2>>"$LOG_FILE")" || rc=$?
  size="$(stat -c %s "$tmp" 2>/dev/null || echo 0)"

  if [ "$rc" -ne 0 ] && [ "$size" -lt 4 ]; then
    case "$rc" in
      6)
        say "   PROBLEM  No website with that name could be found."
        say "            The middle part of the address (the website name,"
        say "            right after https://) is probably misspelled." ;;
      7)
        say "   PROBLEM  The website exists, but nothing answered there."
        say "            The site may be down, or a firewall on your network"
        say "            may be blocking this computer from reaching it." ;;
      28)
        say "   PROBLEM  Nothing answered within 45 seconds. The site may be"
        say "            slow or down right now, or your network may be"
        say "            blocking it. Trying again later is reasonable." ;;
      22)
        case "$code" in
          404)
            say "   PROBLEM  The website answered 'not found' (error 404) for"
            say "            this exact address. The website itself is real,"
            say "            but this path on it is not — check the part"
            say "            after the website name for a small typo." ;;
          401|403)
            say "   PROBLEM  The website refused access (error $code). Two"
            say "            common causes: a typo in the path (many sites"
            say "            answer 'access refused' for addresses that do"
            say "            not exist — check the part after the website"
            say "            name letter by letter), or a feed that needs a"
            say "            key — check with whoever gave you the address." ;;
          5*)
            say "   PROBLEM  The website reported a problem on its own side"
            say "            (error $code). The address may still be right;"
            say "            try again in a few minutes." ;;
          *)
            say "   PROBLEM  The website answered with an error (HTTP $code)."
            say "            Details are in $LOG_FILE." ;;
        esac ;;
      *)
        say "   PROBLEM  The fetch did not complete (details in"
        say "            $LOG_FILE). Check the address and your internet"
        say "            connection, then try again." ;;
    esac
    rm -f "$tmp"
    return 1
  fi

  if [ "$size" -lt 4 ]; then
    say "   PROBLEM  The address answered, but with an empty response —"
    say "            that is not a $label."
    rm -f "$tmp"
    return 1
  fi

  local sig first
  sig="$(od -An -tx1 -N4 "$tmp" 2>/dev/null | tr -d ' \n')"
  first="${sig:0:2}"
  rm -f "$tmp"

  if [ "$kind" = "static" ]; then
    if [ "$sig" = "504b0304" ]; then
      ok "The feed answered and looks like a GTFS schedule file (a ZIP archive)."
      return 0
    fi
    case "$first" in
      3c)
        say "   PROBLEM  This address answered with a web page, not a"
        say "            schedule file. That usually means it points at a"
        say "            page ABOUT the feed instead of the feed itself, or"
        say "            there is a typo in the path — a schedule feed"
        say "            address normally ends in .zip." ;;
      7b|5b)
        say "   PROBLEM  This address answered with data (JSON), not a"
        say "            schedule file. It may be a different service of"
        say "            your vendor's — a GTFS schedule feed is a .zip"
        say "            file." ;;
      0a)
        say "   PROBLEM  This address answered like a LIVE vehicle feed,"
        say "            not a schedule file. The schedule and realtime"
        say "            addresses may be swapped." ;;
      *)
        say "   PROBLEM  This address answered, but not with a schedule"
        say "            file (a GTFS schedule is a ZIP archive, and this"
        say "            response is not one). Check for a typo, or check"
        say "            with whoever gave you the address." ;;
    esac
    return 1
  fi

  # realtime
  if [ "$first" = "0a" ]; then
    ok "The feed answered and looks like a live GTFS-Realtime feed."
    return 0
  fi
  case "$first" in
    3c)
      say "   PROBLEM  This address answered with a web page, not a live"
      say "            GTFS-Realtime feed. That usually means a typo in the"
      say "            path, or an address that points at a page ABOUT the"
      say "            feed instead of the feed itself." ;;
    7b|5b)
      say "   PROBLEM  This address answered with data (JSON), not a"
      say "            GTFS-Realtime feed. GTFS-Realtime is a binary"
      say "            format — this may be a different API of your"
      say "            vendor's. Ask them for the GTFS-Realtime address." ;;
    *)
      if [ "$sig" = "504b0304" ]; then
        say "   PROBLEM  This address answered with a schedule file (ZIP)"
        say "            where a live feed was expected. The schedule and"
        say "            realtime addresses may be swapped."
      else
        say "   PROBLEM  This address answered, but the response does not"
        say "            look like a GTFS-Realtime feed. Check for a typo,"
        say "            or check the address with your AVL/CAD vendor."
      fi ;;
  esac
  return 1
}

# Ask for one feed address interactively, validating spelling and then the
# live feed before accepting it. Empty input skips. The accepted value goes
# into the global variable named by $3. A failing address is written ONLY
# after an explicit "keep it anyway" answer — never silently. Spelling
# failures get re-entry only (a misspelled address can never answer).
prompt_feed_url() {
  local prompt="$1" kind="$2" varname="$3" typed answer
  while true; do
    printf '%s' "$prompt"
    read -r typed
    if [ -z "$typed" ]; then
      printf -v "$varname" '%s' ""
      return 0
    fi
    if ! feed_url_syntax_ok "$typed"; then
      say "   That address will not work as typed: $SYNTAX_PROBLEM"
      say "   Let's try again — or press Enter to skip this feed for now."
      continue
    fi
    if [ "$FEED_LIVE_CHECKS" -eq 0 ]; then
      printf -v "$varname" '%s' "$typed"
      note "Accepted with its spelling checked only — curl is missing, so"
      fixln "it was not fetched. ./install/install.sh --check-feeds can"
      fixln "verify it once curl is installed."
      return 0
    fi
    if feed_live_check "$typed" "$kind"; then
      printf -v "$varname" '%s' "$typed"
      return 0
    fi
    say ""
    say "   The address was NOT saved. You can type it again (r), keep it"
    say "   anyway (k) — reasonable when you know the feed is only briefly"
    say "   down — or skip this feed for now (s). A kept address can be"
    say "   re-checked any time with: ./install/install.sh --check-feeds"
    printf '   Type again, keep anyway, or skip? (r/k/s) [r]: '
    read -r answer
    case "${answer:-r}" in
      k|K)
        printf -v "$varname" '%s' "$typed"
        warn "Keeping $typed although its check failed (your choice, recorded)."
        return 0
        ;;
      s|S)
        printf -v "$varname" '%s' ""
        say "   Skipped. You can add it later in $ENV_FILE."
        return 0
        ;;
      *) : ;;
    esac
  done
}

# Non-interactive (--yes) validation of one env-provided feed URL. A URL
# that fails is a hard refusal — in unattended mode nobody can confirm
# "keep it anyway", so nothing broken is ever written silently. Automation
# that really means it sets HEADWAY_FEED_URL_UNCHECKED_OK=yes (the
# HEADWAY_UPGRADE_SOURCE_MISMATCH_OK pattern) to skip only the LIVE check;
# spelling problems are always refused.
validate_feed_url_noninteractive() {
  local envname="$1" url="$2" kind="$3"
  [ -z "$url" ] && return 0
  if ! feed_url_syntax_ok "$url"; then
    fail "The address in $envname will not work as written:"
    fixln "$SYNTAX_PROBLEM"
    fixln "(Got: $url)"
    exit 1
  fi
  if [ "${HEADWAY_FEED_URL_UNCHECKED_OK:-}" = "yes" ]; then
    note "Writing $envname with its spelling checked only"
    fixln "(HEADWAY_FEED_URL_UNCHECKED_OK=yes skips the live check)."
    fixln "Re-check any time with: ./install/install.sh --check-feeds"
    return 0
  fi
  require_curl
  if ! feed_live_check "$url" "$kind"; then
    fail "Running with --yes, so nobody can confirm this address should be"
    fixln "kept despite the failed check. Refusing; nothing was written."
    fixln "Fix the address, or set HEADWAY_FEED_URL_UNCHECKED_OK=yes if the"
    fixln "feed is expected to be unreachable right now."
    exit 1
  fi
}

# --- --check-feeds: re-validate whatever .env currently holds --------------------
# The command support tells an agency to run first. Same checks, same plain
# language as install-time validation; exit 1 when any configured feed
# fails, 0 otherwise.

CF_TOTAL=0
CF_BAD=0

check_feeds_one() {
  local envkey="$1" kind="$2" label="$3" url
  url="$(read_env_value "$envkey")"
  [ -z "$url" ] && return 0
  CF_TOTAL=$((CF_TOTAL + 1))
  blank
  say "$label:"
  say "   $url"
  if ! feed_url_syntax_ok "$url"; then
    fail "That address cannot work as written: $SYNTAX_PROBLEM"
    fixln "To fix: edit the $envkey= line in"
    fixln "$ENV_FILE, then apply the change with:"
    fixln "    docker compose --project-directory $COMPOSE_DIR --profile app up -d"
    CF_BAD=$((CF_BAD + 1))
    return 0
  fi
  if ! feed_live_check "$url" "$kind"; then
    fixln "If the address is wrong, edit the $envkey= line in"
    fixln "$ENV_FILE and apply the change with:"
    fixln "    docker compose --project-directory $COMPOSE_DIR --profile app up -d"
    CF_BAD=$((CF_BAD + 1))
  fi
}

check_feeds() {
  blank
  say "--- Checking the feed addresses in this installation ---"
  if [ ! -f "$ENV_FILE" ]; then
    fail "No Headway configuration file was found at"
    fixln "$ENV_FILE, so there are no feed addresses to"
    fixln "check. To install Headway first, run: ./install/install.sh"
    exit 1
  fi
  require_curl
  say ""
  say "Each feed address in your configuration is now fetched once — only"
  say "because you ran this command — and must answer and look like the"
  say "right kind of feed. Nothing about your installation is sent anywhere."

  check_feeds_one GTFS_STATIC_URL                static   "GTFS schedule feed"
  check_feeds_one GTFS_RT_VEHICLE_POSITIONS_URL  realtime "Vehicle positions feed"
  check_feeds_one GTFS_RT_TRIP_UPDATES_URL       realtime "Trip updates feed"
  check_feeds_one GTFS_RT_ALERTS_URL             realtime "Service alerts feed"

  blank
  if [ "$CF_TOTAL" -eq 0 ]; then
    note "No feed addresses are configured yet (the GTFS_* lines in"
    fixln "$ENV_FILE are empty), so there was nothing to"
    fixln "check. ./install/install.sh --discover-feeds can look your"
    fixln "agency's feeds up in the public catalog."
    log "check-feeds: no feeds configured"
    exit 0
  fi
  if [ "$CF_BAD" -gt 0 ]; then
    say "Result: $CF_BAD of $CF_TOTAL configured feed(s) FAILED the check —"
    say "the details and the fix for each are above. Data from a failing"
    say "feed is not arriving."
    log "check-feeds: $CF_BAD of $CF_TOTAL failed"
    exit 1
  fi
  say "Result: all $CF_TOTAL configured feed(s) answered and look like the"
  say "right kind of feed."
  log "check-feeds: all $CF_TOTAL ok"
  exit 0
}

# --- Drop folders the collector can actually use ---------------------------------
# Design point 3 (handoff 0037). The collector container runs as a locked-
# down account, uid 65532 (the distroless 'nonroot' user). When Docker
# auto-creates the drop-folder mounts, they come out owned by root, and the
# collector cannot create processed/ or move a handled file — the exact
# blocker of the first live agency ingest (where the interim field advice
# was chmod 777; never that). Least-privilege layout chosen, and why:
#   owner = YOU (the installing account)  -> you can copy exports in
#                                            without sudo;
#   group = 65532 with group-write + setgid (mode 2775)
#                                         -> the collector can read drops,
#                                            create processed/, move files;
#   everyone else: read-only             -> not 777, ever.
# The fix runs through a one-off helper container (this installer never
# runs sudo for you; Docker access, which you already proved, is what
# grants this ability). The updater detects and offers to repair folders
# from older installs (Docker-created, root-owned).

COLLECTOR_UID=65532

# Is this directory usable by the collector account (uid 65532)?
drop_dir_ready() {
  local d="$1" owner group gw
  [ -d "$d" ] || return 1
  owner="$(stat -c %u "$d" 2>/dev/null || echo -1)"
  [ "$owner" = "$COLLECTOR_UID" ] && return 0
  group="$(stat -c %g "$d" 2>/dev/null || echo -1)"
  gw="$(stat -c %A "$d" 2>/dev/null | cut -c6)"
  [ "$group" = "$COLLECTOR_UID" ] && [ "$gw" = "w" ]
}

# Create/repair the drop folders. $1 = install | update. In update mode the
# repair is OFFERED (interactive) rather than just applied; --yes applies
# it with a note. Never exits: a drop-folder problem must not abort an
# install, but it is reported loudly with the manual fix.
ensure_drop_dirs() {
  local mode="${1:-install}" d s p problems=()
  for d in tides-drop vendor-drop; do
    for s in "" processed rejected; do
      p="$COMPOSE_DIR/$d${s:+/$s}"
      drop_dir_ready "$p" || problems+=("$p")
    done
  done
  if [ "${#problems[@]}" -eq 0 ]; then
    ok "The data drop folders (tides-drop, vendor-drop) are set up so both"
    fixln "you and Headway's collector can use them."
    return 0
  fi

  blank
  say "--- Setting up the data drop folders ---"
  say "These folders are where exported files (passenger counts, vendor"
  say "exports) are placed for Headway to pick up. Headway's collector runs"
  say "as a locked-down account (user id $COLLECTOR_UID) that cannot use a folder"
  say "owned by another account — so the folders are set up now with the"
  say "least privilege that works: you own them (you can copy files in),"
  say "the collector's account can read and move files (group access), and"
  say "nobody else can write. Not 777."
  if [ "$mode" = "update" ]; then
    say ""
    say "These existing folders are NOT usable by the collector right now"
    say "(usually a leftover from an earlier version, where Docker created"
    say "them owned by root):"
    for p in "${problems[@]}"; do say "    $p"; done
    if [ "$ASSUME_YES" -eq 1 ]; then
      note "Fixing them now (--yes)."
    else
      local fix_answer
      printf 'Fix their ownership now? (yes/no) [yes]: '
      read -r fix_answer
      case "${fix_answer:-yes}" in
        y|Y|yes|YES|Yes) : ;;
        *)
          warn "Skipped at your request. File drops into these folders will"
          fixln "fail with a permission error (the error itself prints this"
          fixln "same fix). To do it by hand later:"
          fixln "    sudo chown -R \$USER:$COLLECTOR_UID $COMPOSE_DIR/tides-drop $COMPOSE_DIR/vendor-drop"
          fixln "    sudo chmod 2775 $COMPOSE_DIR/tides-drop $COMPOSE_DIR/vendor-drop \\"
          fixln "        $COMPOSE_DIR/tides-drop/processed $COMPOSE_DIR/tides-drop/rejected \\"
          fixln "        $COMPOSE_DIR/vendor-drop/processed $COMPOSE_DIR/vendor-drop/rejected"
          return 0
          ;;
      esac
    fi
  fi

  # The one-off helper container (root inside, so it can repair root-owned
  # leftovers) creates the folders and hands them over: owner you, group
  # 65532, mode 2775. Same helper image the migrations already use.
  local host_uid
  host_uid="$(id -u)"
  if ! HOST_UID="$host_uid" docker run --rm \
      -v "$COMPOSE_DIR/tides-drop:/fix/tides-drop" \
      -v "$COMPOSE_DIR/vendor-drop:/fix/vendor-drop" \
      -e HOST_UID \
      -e COLLECTOR_UID="$COLLECTOR_UID" \
      python:3.12-slim bash -c '
        set -e
        for d in /fix/tides-drop /fix/vendor-drop; do
          mkdir -p "$d/processed" "$d/rejected"
          chown -R "$HOST_UID:$COLLECTOR_UID" "$d"
          chmod 2775 "$d" "$d/processed" "$d/rejected"
        done' >>"$LOG_FILE" 2>&1; then
    warn "The drop folders could not be set up automatically (details in"
    fixln "$LOG_FILE). Headway still works — but file drops will fail with"
    fixln "a permission error until this is done by hand:"
    fixln "    sudo mkdir -p $COMPOSE_DIR/tides-drop/processed $COMPOSE_DIR/tides-drop/rejected \\"
    fixln "        $COMPOSE_DIR/vendor-drop/processed $COMPOSE_DIR/vendor-drop/rejected"
    fixln "    sudo chown -R \$USER:$COLLECTOR_UID $COMPOSE_DIR/tides-drop $COMPOSE_DIR/vendor-drop"
    fixln "    sudo chmod 2775 $COMPOSE_DIR/tides-drop $COMPOSE_DIR/vendor-drop \\"
    fixln "        $COMPOSE_DIR/tides-drop/processed $COMPOSE_DIR/tides-drop/rejected \\"
    fixln "        $COMPOSE_DIR/vendor-drop/processed $COMPOSE_DIR/vendor-drop/rejected"
    return 0
  fi

  # Verify, never assume (Constraint 8): re-check every folder.
  local still=()
  for d in tides-drop vendor-drop; do
    for s in "" processed rejected; do
      p="$COMPOSE_DIR/$d${s:+/$s}"
      drop_dir_ready "$p" || still+=("$p")
    done
  done
  if [ "${#still[@]}" -gt 0 ]; then
    warn "The drop folders were set up, but these still verify as not"
    fixln "usable by the collector (details in $LOG_FILE):"
    for p in "${still[@]}"; do fixln "    $p"; done
    return 0
  fi
  ok "Drop folders ready: $COMPOSE_DIR/tides-drop and"
  fixln "$COMPOSE_DIR/vendor-drop (owner: you; group: the collector's"
  fixln "account, id $COLLECTOR_UID; mode 2775 — least privilege, not 777)."
  log "drop dirs ensured (mode $mode): owner uid $host_uid, group $COLLECTOR_UID, 2775"
}

# --- Feed auto-discovery (--discover-feeds; also offered during install) ---------
# Design point 7 (handoff 0037): nobody should have to type a feed URL.
# Registry-FIRST and registry-ONLY in v0: the single external service
# consulted is the MobilityData Mobility Database — the open, community-
# maintained catalog of the world's public transit feeds — and the operator
# consents BEFORE any network contact, with the service named (the
# --download-basemap precedent). No AI, no crawling: a registry miss is an
# honest miss (the AI-crawl fallback stays on the ROADMAP under the
# grounding contract). Every candidate is live-verified with the SAME
# checks typed URLs get, BEFORE it is offered — a stale registry entry
# (several exist per agency; older ones dead) is never shown. .env is
# written only on the operator's yes.
#
# Catalog fetch, pinned (2026-07-30): the aggregate sources.csv the
# MobilityData project publishes. Their README hands out a link-shortener
# (bit.ly/catalogs-csv); Headway pins the file it RESOLVES to instead — no
# link shortener on the path. Verified 2026-07-30 that both return the
# same bytes. If the project moves the file, this line moves with it.
MOBILITY_CATALOG_URL="https://storage.googleapis.com/storage/v1/b/mdb-csv/o/sources.csv?alt=media"

# Parse ONE CSV line (RFC-4180 quoting: quoted fields, doubled quotes) into
# the global array CSVF. Good enough for the catalog's row shape; a record
# broken across physical lines parses short and is skipped by the field-
# count guard at the call site.
csv_fields() {
  local line="$1" field="" in_quotes=0 i c n=${#1}
  CSVF=()
  i=0
  while [ "$i" -lt "$n" ]; do
    c="${line:$i:1}"
    if [ "$in_quotes" -eq 1 ]; then
      if [ "$c" = '"' ]; then
        if [ "${line:$((i+1)):1}" = '"' ]; then
          field+='"'
          i=$((i + 1))
        else
          in_quotes=0
        fi
      else
        field+="$c"
      fi
    else
      case "$c" in
        '"') in_quotes=1 ;;
        ,)   CSVF+=("$field"); field="" ;;
        *)   field+="$c" ;;
      esac
    fi
    i=$((i + 1))
  done
  CSVF+=("$field")
}

# Case-insensitive "does haystack contain needle" (pure bash).
contains_ci() {
  local hay="${1,,}" needle="${2,,}"
  [ -n "$needle" ] && [[ "$hay" == *"$needle"* ]]
}

# Catalog column positions (0-based; header verified 2026-07-30 against
# the pinned URL above): 0 mdb_source_id, 1 data_type, 2 entity_type,
# 3 country, 4 subdivision, 5 municipality, 6 provider, 9 name,
# 12 static_reference, 13 urls.direct_download, 14 urls.authentication_type,
# 24 status, 26 redirect.id. Guarded by the header check in
# discover_fetch_catalog: if MobilityData reorders columns, the wizard
# refuses loudly instead of misreading.
CATALOG_COLUMNS=28
CATALOG_HEADER_PREFIX="mdb_source_id,data_type,entity_type,"

# A catalog row is offerable when it is not redirected elsewhere, not
# marked out of date, and needs no API key (Headway's collector sends
# none). $1..$3 = status, redirect_id, auth_type.
catalog_row_offerable() {
  local status="$1" redirect="$2" auth="$3"
  [ -z "$redirect" ] || return 1
  case "$status" in ""|active) : ;; *) return 1 ;; esac
  case "$auth" in ""|0) : ;; *) return 1 ;; esac
  return 0
}

# Fetch the catalog into $1. Consent must already have been given.
discover_fetch_catalog() {
  local dest="$1"
  say ""
  say "Downloading the public catalog (about 1 MB)…"
  if ! curl -fsSL --max-time 120 -o "$dest" "$MOBILITY_CATALOG_URL" 2>>"$LOG_FILE"; then
    say ""
    fail "The catalog could not be downloaded. Usually this means no"
    fixln "internet connection from this computer, or the catalog site is"
    fixln "briefly unreachable. Nothing was changed; try again later — or"
    fixln "ask your vendor for the feed addresses and enter them yourself"
    fixln "(docs/connecting-your-data.md, section 2, explains both)."
    return 1
  fi
  if ! head -c 100 "$dest" | grep -q "^$CATALOG_HEADER_PREFIX"; then
    fail "The catalog downloaded, but its format is not the one this"
    fixln "installer knows (its column layout changed). Refusing to guess."
    fixln "Please report this (SUPPORT.md); meanwhile the feed addresses"
    fixln "can be entered by hand (docs/connecting-your-data.md, section 2)."
    return 1
  fi
  ok "Catalog downloaded."
  return 0
}

# Results of a successful discovery, consumed by the caller.
DISCOVERED_PROVIDER=""
DISCOVERED_STATIC=""
DISCOVERED_VP=""
DISCOVERED_TU=""
DISCOVERED_SA=""

# The interactive lookup. Returns 0 with the DISCOVERED_* globals filled
# when the operator accepted verified feeds; 1 otherwise (nothing written,
# reasons already printed). This wrapper only owns the catalog temp file's
# lifetime; the flow itself is in discover_feeds_flow_inner.
discover_feeds_flow() {
  local catalog rc=0
  catalog="$(mktemp)"
  discover_feeds_flow_inner "$catalog" || rc=$?
  rm -f "$catalog"
  return "$rc"
}

discover_feeds_flow_inner() {
  local catalog="$1"
  DISCOVERED_PROVIDER=""; DISCOVERED_STATIC=""
  DISCOVERED_VP=""; DISCOVERED_TU=""; DISCOVERED_SA=""

  say ""
  say "--- Looking up your agency's feeds in the public catalog ---"
  say ""
  say "Here is exactly what this does, before anything touches the network:"
  say "  1. It downloads the public catalog file of the MobilityData"
  say "     Mobility Database — an open, community-maintained list of the"
  say "     world's public transit feeds — from:"
  say "         $MOBILITY_CATALOG_URL"
  say "     Nothing about you or this computer is sent; it is a plain file"
  say "     download, and it happens only if you say yes below."
  say "  2. It looks for your agency by name in that list."
  say "  3. Each candidate feed found is fetched once to check it really"
  say "     answers and looks like the right kind of feed — a stale or dead"
  say "     catalog entry is never offered."
  say "  4. Nothing is saved until you approve what was found."
  say ""
  local consent
  printf 'Look your agency up now? (yes/no): '
  read -r consent
  case "$consent" in
    y|Y|yes|YES|Yes) : ;;
    *)
      say "Skipping the lookup — nothing was contacted."
      log "discover-feeds: consent declined"
      return 1
      ;;
  esac
  require_curl

  local agency_query
  while true; do
    printf 'Your agency'"'"'s name (as the public knows it, e.g. "Metro Transit"): '
    read -r agency_query
    [ -n "$agency_query" ] && break
    say "   Please type at least part of the agency's name."
  done
  log "discover-feeds: consent given; querying catalog"

  discover_fetch_catalog "$catalog" || return 1

  # --- Schedule (GTFS static) candidates ---------------------------------
  local -a sched_ids=() sched_urls=() sched_desc=()
  local skipped_stale=0 line
  while IFS= read -r line; do
    csv_fields "$line"
    [ "${#CSVF[@]}" -eq "$CATALOG_COLUMNS" ] || continue
    [ "${CSVF[1]}" = "gtfs" ] || continue
    contains_ci "${CSVF[6]} ${CSVF[9]}" "$agency_query" || continue
    if ! catalog_row_offerable "${CSVF[24]}" "${CSVF[26]}" "${CSVF[14]}"; then
      case "${CSVF[24]}" in deprecated|inactive) skipped_stale=$((skipped_stale + 1)) ;; esac
      continue
    fi
    [ -n "${CSVF[13]}" ] || continue
    sched_ids+=("${CSVF[0]}")
    sched_urls+=("${CSVF[13]}")
    local place="${CSVF[5]:-}"
    [ -n "${CSVF[4]}" ] && place="${place:+$place, }${CSVF[4]}"
    [ -n "${CSVF[3]}" ] && place="${place:+$place, }${CSVF[3]}"
    sched_desc+=("${CSVF[6]}${place:+ — $place}")
  done < <(grep -iF -- "$agency_query" "$catalog" || true)

  if [ "${#sched_ids[@]}" -eq 0 ]; then
    say ""
    if [ "$skipped_stale" -gt 0 ]; then
      say "The catalog knows that name, but only from entries it marks as"
      say "out of date ($skipped_stale skipped) — those are never offered, because a"
      say "stale address would fail silently later."
    else
      say "Your agency was not found in the public catalog under that name."
    fi
    say ""
    say "That is an honest miss, not a dead end. What works instead:"
    say "  - Try again with a different form of the name (the catalog often"
    say "    uses the formal name, e.g. 'Massachusetts Bay Transportation"
    say "    Authority' rather than 'the T')."
    say "  - Ask your AVL/CAD vendor or IT contact for your GTFS schedule"
    say "    address (.zip) and GTFS-Realtime addresses, then enter them —"
    say "    docs/connecting-your-data.md, section 2, says exactly what to"
    say "    ask for."
    log "discover-feeds: no match for query (stale skipped: $skipped_stale)"
    return 1
  fi

  # Too many name matches: narrow by state/region (the catalog's
  # subdivision column) before doing any live checks.
  if [ "${#sched_ids[@]}" -gt 5 ]; then
    say ""
    say "That name matches ${#sched_ids[@]} agencies in the catalog. Which state or"
    printf 'region is yours in? (e.g. Massachusetts): '
    local region
    read -r region
    if [ -n "$region" ]; then
      local -a f_ids=() f_urls=() f_desc=()
      local k
      for k in "${!sched_ids[@]}"; do
        if contains_ci "${sched_desc[$k]}" "$region"; then
          f_ids+=("${sched_ids[$k]}")
          f_urls+=("${sched_urls[$k]}")
          f_desc+=("${sched_desc[$k]}")
        fi
      done
      if [ "${#f_ids[@]}" -gt 0 ]; then
        sched_ids=("${f_ids[@]}")
        sched_urls=("${f_urls[@]}")
        sched_desc=("${f_desc[@]}")
      else
        say "   None of the matches mention that region; keeping the full list."
      fi
    fi
  fi

  # Live-verify every candidate BEFORE offering (capped at 5 so a broad
  # name never hammers anyone's servers).
  if [ "${#sched_ids[@]}" -gt 5 ]; then
    say ""
    say "Checking the first 5 of ${#sched_ids[@]} matches (narrow the name to see others)."
    sched_ids=("${sched_ids[@]:0:5}")
    sched_urls=("${sched_urls[@]:0:5}")
    sched_desc=("${sched_desc[@]:0:5}")
  fi
  blank
  say "Found ${#sched_ids[@]} possible schedule feed(s); checking each one really answers:"
  local -a v_ids=() v_urls=() v_desc=()
  local k
  for k in "${!sched_ids[@]}"; do
    say ""
    say "   ${sched_desc[$k]}"
    if feed_live_check "${sched_urls[$k]}" static; then
      v_ids+=("${sched_ids[$k]}")
      v_urls+=("${sched_urls[$k]}")
      v_desc+=("${sched_desc[$k]}")
    else
      say "   (This catalog entry was skipped: its address did not verify.)"
    fi
  done
  if [ "${#v_ids[@]}" -eq 0 ]; then
    say ""
    say "The catalog has entries for that name, but none of their addresses"
    say "answered with a real schedule feed just now — so none is offered"
    say "(a dead address saved today is an empty dashboard next week)."
    say "Try again later, or ask your vendor for the addresses directly"
    say "(docs/connecting-your-data.md, section 2)."
    log "discover-feeds: candidates found but none verified"
    return 1
  fi

  local chosen=0
  if [ "${#v_ids[@]}" -gt 1 ]; then
    say ""
    say "More than one verified match — which is your agency?"
    for k in "${!v_ids[@]}"; do
      say "   $((k + 1))) ${v_desc[$k]}"
    done
    say "   0) None of these"
    local pick
    while true; do
      printf '   Your choice: '
      read -r pick
      if [ "$pick" = "0" ]; then
        say "   Understood — nothing was saved. Ask your vendor for the"
        say "   addresses (docs/connecting-your-data.md, section 2)."
        return 1
      fi
      if printf '%s' "$pick" | grep -Eq '^[0-9]+$' \
         && [ "$pick" -ge 1 ] && [ "$pick" -le "${#v_ids[@]}" ]; then
        chosen=$((pick - 1))
        break
      fi
      say "   Please answer with one of the numbers above."
    done
  fi

  local sched_id="${v_ids[$chosen]}"
  local sched_url="${v_urls[$chosen]}"
  local provider="${v_desc[$chosen]}"

  # --- Realtime candidates linked to the chosen schedule ------------------
  # The catalog ties realtime rows to their schedule row via
  # static_reference; provider-name matches are the fallback (some RT rows
  # carry the vendor's name, not the agency's). v0 offers ALL THREE feed
  # types when present and verified: vehicle positions, trip updates,
  # service alerts.
  say ""
  say "Now looking for live (GTFS-Realtime) feeds linked to that agency…"
  local vp_url="" tu_url="" sa_url=""
  while IFS= read -r line; do
    csv_fields "$line"
    [ "${#CSVF[@]}" -eq "$CATALOG_COLUMNS" ] || continue
    [ "${CSVF[1]}" = "gtfs-rt" ] || continue
    [ -n "${CSVF[13]}" ] || continue
    catalog_row_offerable "${CSVF[24]}" "${CSVF[26]}" "${CSVF[14]}" || continue
    # Linked to the chosen schedule, or same provider/name text.
    if [ "${CSVF[12]}" != "$sched_id" ] \
       && ! contains_ci "${CSVF[6]} ${CSVF[9]}" "$agency_query"; then
      continue
    fi
    case "${CSVF[2]}" in
      vp) [ -z "$vp_url" ] && vp_url="${CSVF[13]}" ;;
      tu) [ -z "$tu_url" ] && tu_url="${CSVF[13]}" ;;
      sa) [ -z "$sa_url" ] && sa_url="${CSVF[13]}" ;;
    esac
  done < <(grep -F ",gtfs-rt," "$catalog" | grep -iF -e ",$sched_id," -e "$agency_query" || true)

  local verified_vp="" verified_tu="" verified_sa=""
  if [ -n "$vp_url" ]; then
    say ""
    say "   Vehicle positions candidate:"
    if feed_live_check "$vp_url" realtime; then
      verified_vp="$vp_url"
    else
      say "   (Skipped: the catalog's vehicle-positions address did not verify.)"
    fi
  fi
  if [ -n "$tu_url" ]; then
    say ""
    say "   Trip updates candidate:"
    if feed_live_check "$tu_url" realtime; then
      verified_tu="$tu_url"
    else
      say "   (Skipped: the catalog's trip-updates address did not verify.)"
    fi
  fi
  if [ -n "$sa_url" ]; then
    say ""
    say "   Service alerts candidate:"
    if feed_live_check "$sa_url" realtime; then
      verified_sa="$sa_url"
    else
      say "   (Skipped: the catalog's service-alerts address did not verify.)"
    fi
  fi

  # --- Present what was found and verified; save only on yes --------------
  blank
  say "=================================================================="
  say " Found and checked, for: $provider"
  say "=================================================================="
  say ""
  say "  Schedule feed (GTFS):        $sched_url"
  [ -n "$verified_vp" ] && say "  Live vehicle positions:      $verified_vp"
  [ -n "$verified_tu" ] && say "  Live trip updates:           $verified_tu"
  [ -n "$verified_sa" ] && say "  Live service alerts:         $verified_sa"
  if [ -z "$verified_vp" ]; then
    say ""
    say "  (No live vehicle-positions feed was found and verified in the"
    say "  catalog. Vehicle positions usually come from your AVL/CAD"
    say "  vendor — you can add that address later in $ENV_FILE.)"
  fi
  say ""
  say "Every address above answered its check just now. Nothing is saved yet."
  local accept
  printf 'Use these feeds for this installation? (yes/no): '
  read -r accept
  case "$accept" in
    y|Y|yes|YES|Yes) : ;;
    *)
      say "Nothing was saved."
      log "discover-feeds: verified feeds declined by operator"
      return 1
      ;;
  esac

  DISCOVERED_PROVIDER="$provider"
  DISCOVERED_STATIC="$sched_url"
  DISCOVERED_VP="$verified_vp"
  DISCOVERED_TU="$verified_tu"
  DISCOVERED_SA="$verified_sa"
  log "discover-feeds: operator accepted verified feeds for '$provider'"
  return 0
}

# The standalone --discover-feeds command: run the lookup against an
# EXISTING installation and write .env on acceptance.
discover_feeds_command() {
  blank
  say "--- Finding your agency's feeds (public catalog lookup) ---"
  if [ ! -f "$ENV_FILE" ]; then
    fail "No Headway configuration file was found at"
    fixln "$ENV_FILE. This command updates an existing"
    fixln "installation's feed addresses; the installer itself offers the"
    fixln "same lookup during a fresh install: ./install/install.sh"
    exit 1
  fi
  if [ "$ASSUME_YES" -eq 1 ]; then
    fail "This command contacts a public catalog on the internet and saves"
    fixln "only what a person approves, so it cannot run with --yes."
    fixln "Run it without --yes and answer the questions."
    exit 1
  fi
  if ! discover_feeds_flow; then
    exit 1
  fi
  set_env_value GTFS_STATIC_URL "$DISCOVERED_STATIC"
  [ -n "$DISCOVERED_VP" ] && set_env_value GTFS_RT_VEHICLE_POSITIONS_URL "$DISCOVERED_VP"
  [ -n "$DISCOVERED_TU" ] && set_env_value GTFS_RT_TRIP_UPDATES_URL "$DISCOVERED_TU"
  [ -n "$DISCOVERED_SA" ] && set_env_value GTFS_RT_ALERTS_URL "$DISCOVERED_SA"
  blank
  ok "The verified feed addresses for $DISCOVERED_PROVIDER"
  fixln "were written to $ENV_FILE."
  say ""
  say "One more step to make the collector use them (a .env change needs"
  say "'up -d', not 'restart'):"
  say "    docker compose --project-directory $COMPOSE_DIR --profile app up -d"
  say ""
  say "Then ./install/install.sh --check-feeds re-checks them any time."
  log "discover-feeds: wrote feeds to .env"
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
    say "  2. The Headway website, sign-in service and feed collector are"
    say "     already running. Sign in as '$ADMIN_USERNAME' at"
    say "     http://localhost:8080 — and see deploy/compose/README.md for"
    say "     what each service is."
    say "  3. To start collecting your agency's live feed data, put your feed"
    say "     addresses in $ENV_FILE (GTFS_STATIC_URL and the GTFS_RT_* ones)"
    say "     and restart: docker compose --project-directory $COMPOSE_DIR up -d"
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
  capture_service_logs "before-upgrade"
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
MODES=$((CHECK_ONLY + RECONFIGURE + CHECK_UPDATES + UPGRADE + RESET_PASSWORD + UPDATE_SOURCE + DOWNLOAD_BASEMAP + CHECK_FEEDS + DISCOVER_FEEDS))
if [ "$MODES" -gt 1 ]; then
  fail "Those options cannot be combined. Please run one at a time:"
  fixln "--check, --check-updates, --upgrade, --reconfigure-access,"
  fixln "--reset-admin-password, --update-from-source,"
  fixln "--download-basemap, --check-feeds, or --discover-feeds."
  exit 1
fi

if [ "$CHECK_UPDATES" -eq 1 ]; then
  check_updates
  exit 0
fi

if [ "$RESET_PASSWORD" -eq 1 ]; then
  reset_admin_password
  exit 0
fi

if [ "$UPDATE_SOURCE" -eq 1 ]; then
  update_from_source
  exit 0
fi

if [ "$DOWNLOAD_BASEMAP" -eq 1 ]; then
  download_basemap
  exit 0
fi

if [ "$CHECK_FEEDS" -eq 1 ]; then
  check_feeds   # prints results and exits 0 (all good) or 1 (failures)
fi

if [ "$DISCOVER_FEEDS" -eq 1 ]; then
  discover_feeds_command
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
# Drop folders must exist with the RIGHT ownership BEFORE the stack starts:
# if Docker creates the mounts itself, they come out owned by root and the
# collector cannot use them (handoff 0037, design point 3).
ensure_drop_dirs install
start_stack
wait_for_healthy
run_migrations
create_admin_user
print_summary
