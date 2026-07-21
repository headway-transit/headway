# Updating Headway

This page explains, in plain words, how an installed Headway gets updated:
what an update actually is, the two commands involved, what happens to your
data (nothing), and how to go back if an update does not agree with you. It
is written for the same person `install/README.md` is written for — whoever
looks after the Headway computer. You do not need to be a programmer.

## What an update is

Headway runs as a set of sealed software packages ("container images").
When the project publishes a new release, it publishes **new images** —
your installation never patches software in place, and nothing inside your
running installation is edited. An update means: download the new images,
**check their signatures**, switch over to them, apply any new database
tables, and confirm everything reports healthy. Your recorded transit data
is not part of the images; it lives in Docker volumes on your disk and no
update touches it.

Every released image is signed by the Headway release pipeline when it is
built (the details live in [`docs/supply-chain.md`](supply-chain.md)). The
updater verifies each image's signature **before anything switches** —
using `cosign`, the standard open-source verification tool — and if any
signature does not check out, it refuses loudly and changes nothing. You
are never asked to trust a download; it has to prove itself.

## Headway never phones home

Headway does not check for updates on its own — not on a timer, not at
start-up, not ever. The one and only version check happens when **you** run
the command below, and it is a plain read of the public release list on
GitHub. Nothing about your installation — not its version, not its agency
ID, not even the fact that it exists — is sent anywhere.

There is deliberately **no automatic updater**: transit agencies control
their own change windows, and an update should happen when you decide it
does, ideally not the week a report is due.

## The two commands

**See where you stand** (read-only, changes nothing):

```
./install/install.sh --check-updates
```

It prints the version you are running, the newest release, and the address
of that release's notes so you can read what changed before doing anything.

**Do the update** (when you are ready):

```
cd <your Headway folder>
git fetch --tags && git checkout vX.Y.Z    # step 1: put the folder on the release
./install/install.sh --upgrade vX.Y.Z      # step 2: run the update
```

(Leaving the version off `--upgrade` uses the newest release. Step 1
matters because the database-table updates and the website are built from
your Headway folder — the updater checks that folder and release match, and
tells you the exact commands if they do not. If you did not install from
git, download the release's source from its notes page instead.)

## What `--upgrade` does, step by step

1. **Verifies every image's signature** against the Headway release
   pipeline's signing identity, before anything changes. Any mismatch stops
   the update with nothing altered — and a mismatch on software you took
   from the official releases page is worth reporting (`SECURITY.md`), not
   working around.
2. **Downloads exactly the bytes that were verified** (by their
   fingerprint, not by their name).
3. **Records the version you are on now** in the configuration file, so
   the way back is always written down.
4. **Rebuilds the website on your computer** from the release's source.
   This is the one piece not used as a downloaded image, for an honest
   technical reason: the address the website calls is baked into it when it
   is built, and that address is yours (it is how your answer to "Where
   will people use Headway from?" keeps working). Your network-access
   settings are carried through updates untouched — see
   [`docs/network-access.md`](network-access.md).
5. **Switches the running services** to the new version.
6. **Applies new database tables** using the same small throwaway helper
   container the installer used — safe to repeat, and it only ever *adds*
   tables and columns.
7. **Waits until every service reports healthy**, and says so. A service
   that does not come back healthy is reported loudly, with the go-back
   steps printed — the update is never silently declared done.

Everything is recorded (never any passwords) in `install/install.log`.

## Going back

The version you were on is recorded in `deploy/compose/.env` as
`HEADWAY_PREVIOUS_IMAGE_TAG`, and the updater prints the go-back steps at
the end of every run. Going back to a released version is the same command
pointed backwards — signatures are verified again on the way back:

```
./install/install.sh --upgrade vX.Y.Z      # the version you came from
```

Two honest limits, so nothing surprises you:

- **Database changes are forward-only.** Going back swaps the app
  software; the database keeps any tables the update added. Because
  updates only ever add — your recorded data is never rewritten — older
  app versions keep working against the newer tables. What is *not*
  offered, and we say so plainly, is rewinding the database itself.
- **Your data is untouched in both directions.** Neither updating nor
  going back deletes data volumes. Only `./install/uninstall.sh` can do
  that, and only after you type a confirmation.

## How often, and what triggers a security update

Headway is young; expect releases every few weeks, each with plain-word
release notes. Security has its own trigger: every week, an automatic check
on the project's side re-scans the published images against the latest
vulnerability knowledge. If a published image is found to carry a fixable
vulnerability of high severity or above, that raises an alarm with the
maintainers and the fix ships as a **patch release** — a normal release you
update to with the same two commands above, whose notes say it is a
security update. That weekly check runs on the project's servers, not
yours: it involves your installation in nothing.

If a release's notes mark it as a security update, please schedule the
update promptly rather than waiting for a convenient week.

## For maintainers: how updates reach the project itself

The agency-facing story above is the last step of a chain documented in
[`docs/supply-chain.md`](supply-chain.md): grouped weekly dependency
update PRs (Dependabot, `.github/dependabot.yml` — no auto-merge, every PR
gated by the full CI including the license gate and vulnerability scan),
and the weekly published-image scan
(`.github/workflows/rebuild-scan.yml`) that is the alarm behind the
security-update policy in the previous section.
