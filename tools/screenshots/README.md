# Refreshing the README screenshots

The screenshots in `docs/images/` are captured from a **real running
installation with real data** — never from a mockup or a preview harness, so a
screenshot cannot flatter something the product does not actually do.

## The one trap

The session token lives **in memory only**. A page load after signing in lands
back on `/login`, so a capture script that navigates by URL silently
photographs the sign-in screen instead of the page you asked for. That mistake
produced a useless set once. `capture.mjs` therefore signs in exactly once and
reaches every other surface by **clicking the nav link by its visible text**.

## Running it

Requires a running stack (`--profile app`), Google Chrome, and the `ws` package
(installed into a scratch directory — deliberately NOT a repo dependency, so
the license gate and the shipped bundle stay untouched).

```sh
# 1. a headless Chrome with the DevTools protocol open
google-chrome --headless=new --remote-debugging-port=9333 --no-sandbox \
  --disable-gpu --hide-scrollbars --user-data-dir=/tmp/hw-shot about:blank &

# 2. somewhere outside the repo
mkdir -p /tmp/hw-shot-driver && cd /tmp/hw-shot-driver && npm init -y && npm i ws@8

# 3. capture (SHOT_PASS: use install.sh --reset-admin-password to set one)
cd /tmp/hw-shot-driver
SHOT_BASE=http://127.0.0.1:8080 \
SHOT_USER=<user> SHOT_PASS=<password> \
SHOT_OUT=<repo>/docs/images SHOT_DARK=1 \
SHOT_PLAN='[{"nav":"Dashboard","file":"dashboard.png","wait":4500}]' \
node <repo>/tools/screenshots/capture.mjs
```

`SHOT_PLAN` is a JSON array; each entry names the nav link to click, the output
file, how long to wait, and an optional `then` expression evaluated in the page
before the shot (used to scroll a section into frame, or to switch the map to
its dark street style).

Captured at 1440×960 with `deviceScaleFactor: 2`, so the PNGs are 2880×1920 and
stay sharp on a high-density display.

## Before committing

Look at every image. A capture that technically succeeded can still be a bad
screenshot — an empty period, a `0.00` figure, or a table overflowing its
frame. One was discarded on exactly those grounds during the 2026-08-02
refresh; prefer a surface with real figures on it.
