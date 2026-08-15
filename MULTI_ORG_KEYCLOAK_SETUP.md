# Multi-Org Keycloak Setup (SoldierIQ-SD)

This app uses a **dedicated Keycloak** with the [`keycloak-orgs`](https://github.com/p2-inc/keycloak-orgs)
extension so one person can belong to **multiple organizations**, hold a
**role per org** (admin / user), **switch** the active org without re-login, and
**invite** teammates. The extension ships pre-bundled in Phase Two's Keycloak
image, and Railway has a one-click template for it.

> This is a **separate, fresh** Keycloak just for SoldierIQ-SD. Your existing
> Knowledge-Management Keycloak is untouched, and there is no user migration.

---

## Step 1 — Deploy the PhaseTwo Keycloak template on Railway (one click)

Use Railway's official template: **https://railway.com/deploy/phasetwo-keycloak**

It deploys **two services, pre-wired**:
- **PhaseTwo Keycloak** (`quay.io/phasetwo/phasetwo-keycloak`) with `keycloak-orgs` bundled
- **PostgreSQL 17**

It gives a **public domain automatically** and works behind Railway's proxy out
of the box — you do **not** need to hand-set `KC_PROXY_HEADERS` / `KC_HOSTNAME` /
ports.

Set the admin login before deploying (default is `admin` / `railway` — change the
password):
```
KC_BOOTSTRAP_ADMIN_USERNAME=admin
KC_BOOTSTRAP_ADMIN_PASSWORD=<a-strong-password>
```

> ⚠️ **Path gotcha:** this image serves Keycloak under an **`/auth`** base path
> (its health check is `/auth/health`). So the base URL everywhere is
> `https://<your-domain>/auth` — including the admin console
> (`https://<your-domain>/auth/admin`) and the backend config in Step 5.

## Step 2 — First login + harden

- Open `https://<your-domain>/auth/admin`, log in with the Step 1 credentials.
- Create your own admin user, then delete the bootstrap `admin` account.
- *(Optional — skip unless you want to eyeball orgs by hand)* **Realm settings →
  Themes → Admin console theme = `phasetwo.v2`** adds a manual Organizations
  management section to **this admin console only**. It does **not** touch your
  app's own login/signup pages, and the app does not require it — the REST API,
  the `active_organization` token mapper, and invitations all work without it.

## Step 3 — Realm + client (Keycloak Admin UI)

Only **one** client is needed: the backend brokers all login (password grant),
so the browser never talks to Keycloak directly — no separate frontend client.

1. **Create a realm** — e.g. `soldieriq` (any name; the backend just points at it).
   Switch into it before continuing.
2. **Backend client** `soldieriq-backend`:
   - Client authentication: **On** (confidential)
   - **Direct access grants: On** (so the backend can log users in by password)
   - **Service accounts roles: On** (so the backend gets an admin token for org calls)
   - Save → **Service account roles** tab → **Assign role** → filter **by clients**
     → assign from `realm-management`:
     `manage-users`, `manage-organizations`, `view-organizations`, `query-users`.
   - Copy the **Client secret** (Credentials tab).

## Step 4 — Turn on org behavior

1. **Authentication → Required actions** → enable **`Invitation`** (lets invited
   users accept and join on first login).
2. **Active Organization token mapper** — so tokens carry the active org + role:
   - Clients → `soldieriq-backend` → **Client scopes**
     → the `soldieriq-backend-dedicated` scope → **Add mapper → By configuration →
     Active Organization**.
   - Enable the **id**, **name**, and **role** properties.
   - Result: access tokens include
     ```json
     "active_organization": { "id": "...", "name": "...", "role": ["..."] }
     ```
   The backend reads the active org and the user's role straight from this claim.

## Step 5 — Hand these back to me (go into SoldierIQ-SD backend env)

```
KEYCLOAK_SERVER_URL=https://<your-domain>/auth     # note the /auth suffix
KEYCLOAK_REALM=soldieriq
KEYCLOAK_CLIENT_ID=soldieriq-backend
KEYCLOAK_CLIENT_SECRET=<from Step 3.2>
KEYCLOAK_ADMIN_USERNAME=<your admin user>
KEYCLOAK_ADMIN_PASSWORD=<your admin password>
```

Once this Keycloak is live and I have the URL + realm + backend client id, I wire
the SoldierIQ-SD backend to it: signup creates the personal org, `/workspace`
lists + switches orgs (returning fresh tokens), invitations, and the frontend
org switcher + accept page.

---

### Notes
- **Roles:** `keycloak-orgs` has built-in org permission roles. We map our two
  tiers as: **admin** = member granted `manage-organization` (can invite / manage
  members); **user** = a plain member (view only). The `active_organization.role`
  claim tells the backend which one applies.
- **Switching orgs** calls `PUT /realms/{realm}/users/switch-organization` and
  returns a **new access + refresh token** — no re-login.
- The FalkorDB graph is still `org_<organization_id>`; with a fresh Keycloak the
  org IDs are new, so ingest happens under the new org IDs from day one.
- **Health check** for Railway: `/auth/health`.
