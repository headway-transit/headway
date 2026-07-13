# Installing Headway

This guide walks you through installing Headway on one Linux computer.
It is written for the person at a transit agency who looks after the
computers — you do not need to be a programmer. Plan for about **30
minutes**, most of it waiting for downloads.

Headway is the platform that collects your agency's operations data and
prepares the numbers you report to the National Transit Database (NTD).

## What you need before starting

- **A Linux computer** you can sit at or log in to. Ubuntu 22.04 or newer
  is what we test on; other mainstream distributions work too.
- **At least 4 GB of memory and 20 GB of free disk space.** More disk is
  better — your transit data grows over time. The installer checks both
  and warns you if the machine is small. Sizing a VM properly for a real
  evaluation or pilot? See the measured recommendations in
  [`docs/sizing.md`](../docs/sizing.md) — short version: 4 CPUs, 16 GB of
  memory, and 100 GB of disk make a comfortable pilot.
- **An internet connection.** The first install downloads about 2 GB of
  software.
- **Administrator ("sudo") access** on that computer, in case a fix-up
  command is needed. The installer itself never asks for your sudo
  password; when something needs sudo, it prints the exact command for
  you to run yourself.
- **Docker installed.** Docker is the industry-standard tool that runs
  each part of Headway in its own sealed box (a "container"), so nothing
  else needs to be installed on the computer itself. If Docker is missing
  or not set up right, the installer tells you exactly what to run — it
  will not leave you guessing.
- Optional, nice to have: the web addresses (URLs) of your agency's GTFS
  schedule feed and GTFS-Realtime vehicle positions feed. See "What the
  installer will ask you" below. You can skip both and add them later.

## Try a dry run first (recommended)

From the Headway folder, run:

```
./install/install.sh --check
```

This **changes nothing**. It only checks the computer — Docker, network
ports, memory, disk — and prints either "ready" or a list of problems,
each with the exact commands that fix it. Run it as many times as you
like.

## Installing

```
./install/install.sh
```

The installer does seven things, telling you what is happening at each
step:

1. **Checks the computer** (same checks as `--check`).
2. **Checks for an existing installation.** If Headway is already on this
   computer, the installer stops and explains your options instead of
   overwriting anything.
3. **Creates the configuration file** (`deploy/compose/.env`) with strong
   randomly generated passwords. The file is readable only by your user
   account.
4. **Starts Headway** — the database, message queue, file storage,
   metrics and dashboards — and waits until every part reports healthy.
   The first start downloads software and can take 10–20 minutes.
5. **Sets up the database tables** using a small temporary helper
   container (nothing extra is installed on the computer itself).
6. **Creates your administrator account** with the username and password
   you choose.
7. **Prints a summary**: what is running, the web addresses, where your
   data lives, and what to do next.

## What the installer will ask you

- **An agency ID** — a short name for your agency, like `metro-transit`.
  Letters, numbers, dots, hyphens and underscores only; no spaces. It
  tags every piece of data as belonging to your agency.
- **(Optional) Your GTFS schedule feed address.** GTFS is the standard
  file format for transit schedules; most agencies already publish one so
  trip planners like Google Maps can use it. It is a web address ending
  in `.zip`. Don't know it? Press Enter to skip — you can add it later.
- **(Optional) Your GTFS-Realtime vehicle positions feed address.** A
  live web address that reports where your vehicles are right now,
  usually provided by your AVL/CAD vendor. Skippable, same as above.
- **An administrator username and password.** This account gets the
  "certifying official" role — the highest level, able to approve reports
  and manage other accounts. The password is hidden while you type and
  asked twice to catch typos. Use at least 8 characters (72 at most).
- **Where will people use Headway from?** Three answers: (a) just this
  computer — the safe default; (b) other computers in our office —
  Headway gets a secure `https://` address coworkers can open, and the
  installer walks you through the one-time browser-certificate step;
  (c) our IT staff will set up access. The trade-offs of each, in plain
  words, are in [`docs/network-access.md`](../docs/network-access.md).
  You can change this answer any time — in either direction — with:

  ```
  ./install/install.sh --reconfigure-access
  ```

Nothing you type is sent anywhere; it all stays on this computer.

## If the installer stops

The installer never fails silently: whenever it stops, it names the
problem **and** prints the commands that fix it. The common cases:

- **"Docker is installed but your user account cannot reach it yet."**
  Common on Ubuntu when Docker came from snap: snap does not create the
  `docker` permission group, and after Docker restarts (including snap's
  automatic updates) it can reset its socket so only root can use it.
  The installer detects each of these and prints the two or three exact
  commands to run. After fixing, log out and back in, then run the
  installer again.
- **"Port … is already in use."** A "port" is a numbered door programs
  use to talk on a computer; two programs cannot share one. Usually this
  means Headway (or another database/web server) is already running here.
  The message tells you how to find the program using the port.
- **"Headway is already installed on this computer."** The installer
  refuses to overwrite an existing installation, to protect your data.
  Upgrading in place will be handled by a future `--upgrade` option. If a
  previous install attempt stopped partway and you want a clean start,
  run `./install/uninstall.sh` first — it asks before deleting anything.
- **A step fails partway** (download interrupted, disk filled up, …).
  Fix the cause, run `./install/uninstall.sh` to clear the partial
  install (you can keep the data volumes if any), then run the installer
  again.

Everything the installer does is recorded in `install/install.log`.
**Passwords are never written to that log**, so it is safe to attach when
asking for help.

## After installing

- Dashboards: open `http://localhost:3000` in a browser on that computer
  (user `admin`; the password is the `GRAFANA_ADMIN_PASSWORD` line in
  `deploy/compose/.env`).
- Your data lives in Docker "volumes" on the computer's disk. It survives
  restarts and reboots; only the uninstaller deletes it, and only after
  you confirm.
- **Connect your data.** The step-by-step guide to hooking up your GTFS
  feeds and passenger counts (including exports from SQL Server or a data
  lake) is [`docs/connecting-your-data.md`](../docs/connecting-your-data.md).
  For the mechanics of the stack itself, see `deploy/compose/README.md` —
  the feed collector runs under the `app` services profile.
- **Let coworkers use Headway** (or make it private again) whenever you
  are ready: `./install/install.sh --reconfigure-access`. What it does,
  the browser-warning explanation, the certificate install steps per
  operating system, and the secure-tunnel alternative are all in
  [`docs/network-access.md`](../docs/network-access.md).
- Keep `deploy/compose/.env` safe. It holds this installation's
  passwords. Do not email it or commit it anywhere.

## Installing without questions (for IT automation)

`./install/install.sh --yes` asks nothing and reads its answers from
environment variables instead:

| Variable | Required? | Meaning |
| --- | --- | --- |
| `HEADWAY_AGENCY_ID` | yes | the agency ID |
| `HEADWAY_ADMIN_USERNAME` | yes | administrator username |
| `HEADWAY_ADMIN_PASSWORD` | yes | administrator password |
| `HEADWAY_GTFS_STATIC_URL` | no | GTFS schedule feed address |
| `HEADWAY_GTFS_RT_VEHICLE_POSITIONS_URL` | no | vehicle positions feed address |
| `HEADWAY_ACCESS_MODE` | no | where people use Headway from: `local` (default), `lan` (other office computers), or `it` (IT staff set up access) |
| `HEADWAY_LAN_ADDRESS` | with `lan` | the office-network address coworkers' browsers will use — required because the installer never guesses it silently |

## Uninstalling

```
./install/uninstall.sh
```

Removal happens in three separately confirmed stages: (1) stop and remove
the running programs — your data is untouched; (2) delete the data
volumes — permanent, requires typing a confirmation phrase; (3) decide
whether to keep the configuration file (default: keep). Nothing is
deleted without a typed confirmation.

## Getting help

Open an issue on the Headway project's issue tracker and attach
`install/install.log` (it contains no passwords). Include what the
installer printed when it stopped — the last screenful is usually enough.
