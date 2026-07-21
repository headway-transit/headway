# Using Headway from other computers

Headway installs in the safest possible posture: everything answers only to
web browsers **on the Headway computer itself**. Nothing is reachable from
the network until you decide it should be. This page explains your three
options in plain words, how to turn office access on and off, how to remove
the one-time browser warning, and what should never be done.

You do not need to be a programmer for options 1 and 2. Option 3 is the
hand-this-page-to-IT path.

## The three options, honestly

**Option 1 — Just this computer** (the default)

- *Good:* the safest choice, with nothing to set up and nothing exposed.
- *Honest limits:* people have to sit at that machine. If you occasionally
  need to check Headway from your own desk, the "secure tunnel" section
  below gets one person in at a time without opening anything up.

**Option 2 — Other computers in our office**

- *Good:* everyone on your office network opens one `https://` address in a
  normal browser. The connection is encrypted. Nothing is exposed to the
  internet. Turning it on (or off again) is one command.
- *Honest limits:* the first visit shows a browser certificate warning
  until you install Headway's certificate on each computer (explained
  below — it is a one-time step per computer, and the connection is
  encrypted either way). Also, anyone plugged into your office network can
  *reach the sign-in page* — accounts and passwords still protect the data,
  but if your office network has guests on it, know that they can see the
  door.

**Option 3 — Our IT staff will set up access**

- *Good:* the right choice when your organization already has IT staff, a
  DNS name to use, company-issued certificates, or a VPN. They can do it
  properly with their own tools, and the "For IT staff" section below tells
  them exactly what to connect.
- *Honest limits:* it needs those skills. Until IT connects it, Headway
  behaves exactly like option 1.

## Turning office access on (option 2)

During installation, the installer asks **"Where will people use Headway
from?"** — answer **b**. On an installation that already exists, run:

```
./install/install.sh --reconfigure-access
```

and answer **b**. Either way the installer:

1. Detects this computer's office-network address and **asks you to
   confirm it** (it never guesses silently).
2. Starts a secure doorway (the Caddy web server, running in Docker like
   everything else) that encrypts traffic and forwards exactly two things:
   the Headway website and its API. Everything else stays private to the
   Headway computer.
3. Rebuilds the website so it calls the API at the new shared address, and
   wires the matching browser-origin settings — you never manage those by
   hand.
4. Prints the `https://` address to share, and — if this computer runs a
   firewall — prints the one command that opens the standard web ports.
   The installer never runs commands with `sudo` for you; it prints them
   so you stay in control.

To go back to "just this computer", run the same command and answer **a**.
Both directions are safe to run as many times as you like.

Your answer also survives updates: `./install/install.sh --upgrade` (see
[`docs/updating.md`](updating.md)) rebuilds the website with the same
address and changes nothing about network access — you never re-answer
this question because of an update.

## The browser warning, and removing it for good

The first time anyone opens the shared address, their browser shows a
warning such as **"Your connection is not private"**. That is expected.
Here is what is actually happening:

Browsers ship trusting a list of public certificate authorities, and those
authorities can only vouch for addresses on the public internet. A private
office address (like `192.168.1.50`) can never get such a certificate, so
Headway creates its own — the traffic **is** encrypted; the browser just
has no one it already trusts vouching for who is on the other end. On your
own office network, where you know exactly which machine you are talking
to, clicking **Advanced** and then **Proceed** (wording varies by browser)
is a reasonable, informed choice.

To make the warning disappear permanently, install Headway's certificate
on each person's computer — once per computer:

**First, get the certificate file** (on the Headway computer, from the
Headway folder):

```
docker compose --project-directory deploy/compose --profile lan \
  cp caddy:/data/caddy/pki/authorities/local/root.crt ./headway-office.crt
```

This produces `headway-office.crt`. It contains no secrets — it is the
public half of the certificate, safe to email around your office or put on
a shared drive. (The private half never leaves the Headway computer.)

**Windows (Chrome and Edge use this automatically):**

1. Copy `headway-office.crt` to the computer and double-click it.
2. Click **Install Certificate…**
3. Choose **Local Machine** (needs administrator rights; choose **Current
   User** if you don't have them — it then covers just that account),
   then **Next**.
4. Choose **Place all certificates in the following store**, click
   **Browse…**, pick **Trusted Root Certification Authorities**, **OK**,
   **Next**, **Finish**.
5. Close and reopen the browser.

**Mac (Safari and Chrome use this automatically):**

1. Double-click `headway-office.crt` — Keychain Access opens.
2. If asked which keychain, choose **System** (covers every account on the
   Mac; **login** covers just yours).
3. In Keychain Access, find the certificate (its name mentions "Caddy
   Local Authority"), double-click it, expand **Trust**, and set **When
   using this certificate** to **Always Trust**.
4. Close the window and enter your Mac password when asked.

**Linux (Ubuntu/Debian, for the system and most tools):**

```
sudo cp headway-office.crt /usr/local/share/ca-certificates/headway-office.crt
sudo update-ca-certificates
```

**Firefox (any operating system)** keeps its own list and needs one more
step: **Settings → Privacy & Security → scroll to Certificates → View
Certificates… → Authorities → Import…**, pick `headway-office.crt`, tick
**Trust this CA to identify websites**, **OK**. Chrome on Linux works the
same way via **Settings → Privacy and security → Security → Manage
certificates → Authorities → Import**.

One more honest note: the certificate authority lives on the Headway
computer in a Docker volume (`caddy-data`). If that volume is ever deleted,
Headway mints a fresh certificate and the warnings come back until the new
file is installed the same way.

## A secure tunnel for one person (any option)

Sometimes one person occasionally needs Headway from their own desk and
office-wide access is not wanted. An **SSH tunnel** carries your browser's
traffic to the Headway computer through one encrypted connection, without
opening anything for anyone else.

What you need: the Headway computer must accept SSH sign-ins (on Ubuntu:
`sudo apt install openssh-server`, run once by whoever manages it), and
you need a username and password on that computer.

**Mac or Linux** — open Terminal and run (replace the name and address):

```
ssh -L 8080:localhost:8080 -L 8000:localhost:8000 yourname@192.168.1.50
```

Enter your password, **leave that window open**, and browse to
`http://localhost:8080`. Closing the window closes the tunnel.

**Windows — PuTTY, click by click** (written for someone who has never
opened it):

1. Download PuTTY from https://www.putty.org and open `putty.exe`. A
   window titled **PuTTY Configuration** appears.
2. In **Host Name (or IP address)** type the Headway computer's address,
   for example `192.168.1.50`. Leave **Port** at `22` and **Connection
   type** on **SSH**.
3. In the tree on the left, click the small **+** next to **SSH** (under
   **Connection**), then click **Tunnels**.
4. In **Source port** type `8080`. In **Destination** type
   `localhost:8080`. Click **Add**. The list titled **Forwarded ports**
   now shows `L8080  localhost:8080`.
5. Do it again: **Source port** `8000`, **Destination** `localhost:8000`,
   click **Add**.
6. In the tree on the left, click **Session** (at the very top). In
   **Saved Sessions** type `Headway` and click **Save** — next time you
   can just double-click `Headway` in the list instead of repeating steps
   2–5.
7. Click **Open**. The first time, a **PuTTY Security Alert** asks whether
   to trust the computer's key — this is normal on a first connection;
   click **Accept**.
8. A black window asks `login as:` — type your username **on the Headway
   computer** and press Enter, then type your password (nothing appears
   while you type; that is normal) and press Enter.
9. Leave the black window open — minimized is fine. Closing it closes the
   tunnel.
10. Open your browser and go to `http://localhost:8080`. That is Headway.

Why both `8080` and `8000`: `8080` is the Headway website and `8000` is
the service the website talks to; the website expects to find it at
`localhost:8000`, so the tunnel carries both.

(This tunnel reaches the website and API. An administrator can use the
same trick with source port `3000` and destination `localhost:3000` to
reach the Grafana dashboards, which are never shared with the office.)

## For IT staff (option 3)

Everything binds to loopback on the Headway host; publish access with
whatever proxy/VPN your organization standardizes on.

- **Upstreams:** the web app (static files behind nginx) on
  `127.0.0.1:8080`; the API (FastAPI) on `127.0.0.1:8000`.
- **The web bundle bakes its API base URL at build time** (Vite). Set
  `VITE_API_BASE_URL` in `deploy/compose/.env` and run
  `docker compose --project-directory deploy/compose --profile app build web`,
  then `up -d`. If you serve both under one name with the API at a path
  prefix (recommended — it keeps browser calls same-origin), set e.g.
  `VITE_API_BASE_URL=https://headway.example.gov/api` and strip the
  `/api` prefix at your proxy.
- **If you split web and API across origins instead**, set
  `HEADWAY_CORS_ORIGINS` (comma-separated browser origins) in
  `deploy/compose/.env` so the API answers cross-origin browser calls.
- **A ready-made internal option exists:** the Compose profile `lan` runs
  a pinned Caddy (Apache-2.0) that terminates HTTPS with a local CA and
  proxies `/` → web and `/api/*` → API. `install/install.sh
  --reconfigure-access` manages it end to end; see
  `deploy/compose/caddy/Caddyfile`. Adopt or replace it freely.
- **Public DNS + real certificates:** not automated in this release. If
  you have a public DNS name, Caddy can do ACME/Let's Encrypt with a small
  Caddyfile change — planned as a supported path in a future release; for
  now that configuration is yours to own.
- **Never publish:** Grafana `3000`, MinIO `9000`/`9001`, Prometheus
  `9090`, Apicurio `8081`, Postgres `5432`, Kafka `29092`. These are
  operator/admin surfaces with their own credentials and no
  agency-user-facing purpose; they deliberately stay loopback-only.

## Do not put Headway on the internet

Headway holds your agency's operating data and your staff's accounts. If
you connect it directly to the internet — for example by telling your
office router to forward ports 80 or 443 to the Headway computer — then
every person and every automated scanning program in the world can knock
on its door and try passwords forever. No password screen should be asked
to hold that line alone.

Office access (option 2) never involves the internet: the doorway answers
only inside your building's network. If people genuinely need Headway from
home or on the road, the right tools are a **VPN** — a virtual private
network, which makes a far-away laptop behave as if it were plugged in at
the office — or a reverse proxy that your IT staff run and watch, with
real certificates and their own protections in front of it. Both of those
are option 3: jobs for your IT staff, not for a router setting.

## What stays private on purpose

Sharing Headway with the office shares exactly two things: the website
people sign in to, and the API it talks to. The administrative surfaces —
Grafana dashboards, the MinIO file-storage console, Prometheus metrics,
the schema catalog, the database and the message queue — remain reachable
only from the Headway computer itself, on purpose: they have their own
separate credentials, they are tools for whoever operates the machine, and
every door not opened is a door nobody has to guard. Administrators reach
them with the tunnel described above.
