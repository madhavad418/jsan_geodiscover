# Deploying JSAN GeoDiscover to Railway

The application ships as one web service backed by one PostgreSQL database.
Every deploy migrates the schema, seeds the users and reloads the workbooks, so
a redeploy is safe to repeat.

---

## 1. Create the project

1. Push this repository to GitHub.
2. In Railway choose **New Project → Deploy from GitHub repo** and pick it.
3. Railway reads `railway.json` and builds the root `Dockerfile`. No build
   settings need changing.

## 2. Add the database

In the same project choose **New → Database → Add PostgreSQL**. Railway creates
it and exposes `DATABASE_URL` to the project.

## 3. Set the variables

On the web service, **Variables → Raw Editor**, paste this and fill in the
secrets:

```
DATABASE_URL=${{Postgres.DATABASE_URL}}
ENGINE_DATABASE_URL=${{Postgres.DATABASE_URL}}

JWT_SECRET=<64+ random characters>
DEMO_ADMIN_EMAIL=admin@jsanconsulting.com
DEMO_ADMIN_PASSWORD=<strong password>

DEMO_MANAGER_EMAIL=manager@jsanconsulting.com
DEMO_MANAGER_PASSWORD=<strong password>
DEMO_ANALYST_EMAIL=analyst@jsanconsulting.com
DEMO_ANALYST_PASSWORD=<strong password>

CORS_ORIGINS=http://localhost:8000
EVIDENCE_STORAGE_PATH=/app/evidence_storage_customer
```

Generate the secret with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

`${{Postgres.DATABASE_URL}}` is Railway's reference syntax — it resolves to the
database in the same project. Both variables point at the same database on
purpose; see *Why one database is enough* below.

Optional provider keys, all off by default:

```
GOOGLE_PLACES_API_KEY=
GOOGLE_MAPS_API_KEY=
AWS_LOCATION_API_KEY=
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
```

## 4. Deploy and open it

Deploy, then **Settings → Networking → Generate Domain**. The service answers on
`/` and reports health at `/integrated-health`.

The deployment's own domain is added to the allowed CORS origins automatically
from Railway's `RAILWAY_PUBLIC_DOMAIN`, so `CORS_ORIGINS` only needs any *extra*
front ends you serve from elsewhere.

---

## Sign-ins created on first boot

| Account | Role | Password |
|---|---|---|
| `DEMO_ADMIN_EMAIL` | Super admin | `DEMO_ADMIN_PASSWORD` |
| `DEMO_MANAGER_EMAIL` | Project manager | `DEMO_MANAGER_PASSWORD` |
| `DEMO_ANALYST_EMAIL` | Discovery analyst | `DEMO_ANALYST_PASSWORD` |

The manager and analyst passwords fall back to the admin password if left unset,
so nothing breaks if you skip them — but set them if the admin password should
not be shared around.

Passwords are reapplied on every boot, so rotating a variable and redeploying
changes the password. Four further demo accounts (validator, QA, researcher) are
seeded with the admin password for the workflow screens.

---

## What each deploy does

`release.py` runs on boot and is safe to repeat:

1. Waits for the database (up to `DB_WAIT_SECONDS`, default 60).
2. `alembic upgrade head`.
3. `bootstrap.py` — seeds users and the demo project, loads the validation
   workbooks from `backend/misseddata/`, and the benchmark exports from
   `backend/other_cities/`.
4. Starts uvicorn on `$PORT` with proxy headers enabled.

Adding a city later means committing its workbook to the right folder and
redeploying. Existing rows are refreshed rather than duplicated, and saved
validation answers for columns the workbook does not carry are preserved.

---

## Why one database is enough

The discovery engine reuses seven table names from the customer schema —
`users`, `projects`, `poi_candidates`, `google_checks`, `raw_source_records`,
`exports`, `audit_logs`. On SQLite they are separate files. On PostgreSQL they
would collide, so the engine is confined to its own `engine` schema, created
automatically on boot. Point both URLs at the same database and the two stay
apart.

If you would rather have two databases, add a second PostgreSQL service and set
`ENGINE_DATABASE_URL=${{Postgres-2.DATABASE_URL}}`. Nothing else changes.

---

## Things to know

**Uploaded evidence is not durable.** The container filesystem is replaced on
every deploy, so anything written to `EVIDENCE_STORAGE_PATH` is lost. Attach a
Railway Volume mounted at `/app/evidence_storage_customer` if you need it kept.
Everything in the database — cities, validation answers, scrape findings — is
durable and unaffected.

**The bundled discovery-engine sample data is SQLite-only.** `/engine/` starts
with an empty schema on PostgreSQL rather than the sample rows you see locally.
The customer-facing screens are unaffected.

**Scraping runs in-process.** A job runs on a background thread inside the web
container, so a redeploy mid-run cancels it; just start it again. Records
already processed keep their findings.

---

## Running the same image locally

```bash
docker build -t geodiscover .
docker run --rm -p 8000:8000 \
  -e JWT_SECRET=local-dev-secret-change-me \
  -e DEMO_ADMIN_PASSWORD=local-admin-pass \
  -e DATABASE_URL=sqlite:////app/data/customer_demo.db \
  -e ENGINE_DATABASE_URL=sqlite:////app/data/discovery_engine.db \
  geodiscover
```

Then open <http://localhost:8000>. `docker-compose.yml` still runs the previous
SQLite setup for local work.

---

## If a deploy fails

| Symptom | Cause |
|---|---|
| `Database not reachable after 60s` | `DATABASE_URL` unset or the database still starting. Check the reference resolves, or raise `DB_WAIT_SECONDS`. |
| `Can't load plugin: sqlalchemy.dialects:postgres` | A URL bypassed normalisation. Confirm `DATABASE_URL` starts with `postgres://`, `postgresql://` or `postgresql+psycopg://`. |
| `relation "users" already exists` | The engine URL is not schema-isolated. Confirm you deployed the current `discovery_engine/database.py`. |
| Health check times out | First boot seeds ~2,900 rows. `healthcheckTimeout` is 300s; raise it if the database is slow. |
| Login fails after changing a password | Redeploy — passwords are applied at boot. |
