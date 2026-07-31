# JSAN GeoDiscover™ — Executive Customer Demo v5.0

A simplified customer-facing demonstration focused on the current Denpasar salon POI requirement.

## Current customer story

- Compare 400 Grab records with 562 Google records.
- Show 53 matched pairs.
- Separate 39 Tier-1 direct-probe candidates from 139 Tier-2 area-supported leads.
- Keep 266 possible pairings and unresolved records outside the incremental claim.
- Prioritise a Strong 10/25 validation sprint.
- Show real coordinates, evidence reasons, cost controls and release gates.

The UI intentionally hides operational modules that complicate the customer narrative. The team’s detailed discovery engine and production scaffolding remain in the codebase for later phases.

## Start

Windows users should open `START_HERE.txt` and run `START_GEODISCOVER_WINDOWS.bat`.

Manual start:

```powershell
cd backend
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe bootstrap.py
.\.venv\Scripts\python.exe -m uvicorn gateway:app --host 127.0.0.1 --port 8000
```

Open `http://localhost:8000`.

## Customer workbook

`sample_output/GeoDiscover_Executive_Customer_Sample_v5.xlsx`

## Critical claim controls

- 178 means potential Grab-side incremental candidates, not confirmed active non-Google salons.
- Tier 1 means direct-probe evidence and priority validation.
- Tier 2 means area-supported evidence and requires direct probing.
- Customer release remains zero until category, contact, activity, all 16 Google checks and independent QA are complete.
