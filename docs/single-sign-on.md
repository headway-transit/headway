# Single sign-on

**For:** the person who administers Headway at an agency. You do not need to
know SQL, and you do not need to have configured OpenID Connect before.

**What it does:** lets your staff sign in with the account they already have
— Microsoft Entra ID, Google Workspace, Okta, or Keycloak — instead of a
separate Headway password. Their password policy, multi-factor sign-in and
offboarding stay where your IT team already manages them.

---

## Read this first: you cannot lock yourself out

**Headway usernames and passwords keep working, always.** Single sign-on is
added *beside* them, never instead of them. Three reasons, and all three
matter on a real deployment:

- **No internet, or your provider is having a bad morning.** Headway runs on
  a single box at small agencies. It has to stay operable when the identity
  provider is not reachable.
- **The first attempt at this configuration will be wrong.** Everyone's is.
  You need a way in that does not depend on the thing you are configuring.
- **`./install/install.sh --reset-admin-password` keeps working**, on the
  server, for the local administrator account.

So: set this up, get it wrong, and nothing is lost. You still sign in.

If you ever need to turn single sign-on off from the server without opening
Headway at all, set `HEADWAY_OIDC_DISABLED=1` in the environment and restart
the API. That works even when the configuration in the database is wrong.

---

## What you need before you start

Ask whoever administers your identity provider for four things. The names in
brackets are what different providers call them.

| You need | Entra ID calls it | Okta / Keycloak call it |
|---|---|---|
| The discovery address | "OpenID Connect metadata document" | "Well-known / OpenID configuration" |
| The application id | "Application (client) ID" | "Client ID" |
| The client secret | "Client secret value" | "Client secret" |
| The group field | "Groups claim" | "Groups" |

You will also give them **one** thing: the **sign-in return address** (the
"redirect URI"). It is your Headway address followed by `/auth/callback`, for
example:

```
https://headway.yourcity.gov/auth/callback
```

It must match at both ends *exactly* — every character, including `https://`
and the path.

### A note on Microsoft Entra ID

Use the discovery address **that contains your tenant id**, like:

```
https://login.microsoftonline.com/<your-tenant-id>/v2.0/.well-known/openid-configuration
```

Headway deliberately **refuses** the shared `common` address. That address
would admit any Microsoft account anywhere in the world, which is not what
anyone means by "our staff sign in with Entra ID".

---

## Step by step

1. Sign in to Headway as a certifying official and open **Admin → Single
   sign-on → Set up single sign-on**.
2. Fill in the discovery address, application id, client secret and the
   sign-in return address. Leave **"Turn single sign-on on"** unticked.
3. Press **Save settings**.
4. Press **Test this configuration**. Read every line. Fix anything that says
   "Needs attention" and test again.
5. Add at least one group under **Who gets which role** (see below).
6. Tick **"Turn single sign-on on"** and save.

### The client secret is shown once

Headway stores it encrypted and **will never show it to you again**. Keep
your own copy somewhere safe until sign-in works. If you lose it, generate a
new one at your provider and paste the new one in — you are not stuck.

If the settings screen says *"This server has nowhere safe to keep a secret
yet"*, Headway has no encryption key and will **refuse to save the secret at
all** rather than store it in plain text. Ask whoever runs the server to set
`HEADWAY_SECRET_ENCRYPTION_KEY` (64 hex characters, e.g.
`openssl rand -hex 32`) or `HEADWAY_SECRET_ENCRYPTION_KEY_FILE`, and restart.

---

## Who gets which role

**Nobody gets in unless you say so.** Headway does not guess. A person whose
groups match none of your entries is refused, and **no account is created for
them**. There is no fallback, deliberately: a fallback is how a group nobody
audited turns into access nobody granted.

Use **the groups your directory already has**. Headway does not require any
particular naming, expects no group of its own, and you never need to create
one for it. `Transit-Data-Stewards`, `GIS-Admins`, `Finance` — whatever you
already use is fine. Entra ID usually sends a group's object id (a long
code) rather than its name; that is fine too, and the **Note** field is there
so you can write "Finance team" beside a code that means nothing to a human.

Matching is **exact and case-sensitive**. No wildcards, no patterns.

The roles you can grant from a group:

| Role | Can |
|---|---|
| Viewer | Read the figures, receipts, lineage and findings |
| Auditor | Read all of that **plus the audit trail**, and change nothing at all |
| Data steward | Everything a viewer can, plus resolve findings and run calculations |
| Report preparer | Everything a data steward can, plus complete sampling work |

If someone's groups match more than one entry, Headway gives them the
**least** privileged of them, and records every entry that matched — so an
accidental double-grant is visible instead of quietly resolved upward.

### Why "certifying official" is not in that list

Certifying is a legal attestation that the figures you send to the federal
government are correct. It is signed, and it is what a triennial review looks
at.

If it could be granted by a group membership, then the set of people allowed
to sign a federal submission would be edited in a directory Headway does not
control, by administrators the transit department may never see, with nothing
in Headway's audit trail to show the change. So it is granted **only inside
Headway**, under **Admin → Users**, by an existing certifying official, and
that grant is audited with who did it, when, and what it changed from.

Those people still sign in through your identity provider. Only the *granting*
is local.

The same rule works the other way: removing someone's group membership does
**not** strip their certifying role. Otherwise a directory change could leave
your agency with nobody able to certify.

---

## When it does not work

### "Headway could not verify the security certificate…"

This is the most common failure, and it is almost always real: your network
inspects encrypted traffic and re-signs it with your organisation's own
certificate authority, which Headway does not yet trust.

**The fix:** ask your network administrator for that authority's certificate
file (a `.pem`), put it **on the Headway server** (inside the container, if
Headway runs in one), and enter its full path in **Certificate authority
file**.

**Headway will not offer to skip certificate checking**, and you should not
look for a way to. Skipping it would let anyone on your network impersonate
your identity provider and sign in as anybody.

### "Nobody can sign in, but the test passes"

Almost always the **group field**. Your provider may call it `groups`,
`roles`, or `wids`, and it may not send groups at all unless someone enables
it at the provider. Check the group field name first, then check that the
values you entered match what your provider actually sends.

### "Sign-in fails and I cannot see why"

That is deliberate. The sign-in page gives everyone the **same** message,
whatever went wrong, so that someone probing it cannot learn whether an
account exists.

**The real reason is in Headway's audit trail** — every attempt, successful
and failed, is recorded there with the specific cause. An auditor or a
certifying official can read it.

### Sign-ins fail with a clock or "expired" error

Headway allows the clocks on your server and your provider to differ by 120
seconds by default. You can raise that on the settings screen, but the real
fix is to run a time service on the Headway server.

---

## What happens when someone signs in

1. Headway sends them to your provider (authorization code flow with PKCE —
   never the implicit flow).
2. Your provider signs them in and sends them back.
3. Headway checks the returned token completely: the signature against your
   provider's published keys, who issued it, who it was issued for, and that
   it belongs to *this* sign-in and no other.
4. Headway reads their groups and finds your mapping. **No mapping, no
   access, no account.**
5. On a first successful sign-in, an account is created with the role you
   mapped. It has no password — it signs in only through your provider.
6. Every sign-in, successful or refused, is written to the audit trail with
   both the Headway username and your provider's own subject identifier.

That last point matters more than it looks. Under single sign-on, a
certification records **who signed** with both identifiers, inside the signed
document itself. A signature whose signer cannot be resolved years later —
after the person has left, after a username has been reused, after a tenant
migration — is not a signature.

### When your provider rotates its signing keys

Nothing happens. Headway re-reads them automatically. You do not need to do
anything, and sign-in is not interrupted.

### Removing access

Remove the person (or the group) at your identity provider — that is the
point of federating in the first place. Their next sign-in is refused.

Removing a mapping in Headway stops future sign-ins for that group but does
**not** delete the accounts it already created; manage those under **Admin →
Users** like any other account. Deleting people's accounts as a side effect
of editing a configuration would be a surprise, and a destructive one.

---

## SAML

Headway speaks OpenID Connect natively. If your identity provider is
SAML-only, run the optional Keycloak profile: Keycloak talks SAML to your
provider and OpenID Connect to Headway, and nothing on this page changes —
Keycloak simply becomes the provider you configure here. See ADR-0011.
