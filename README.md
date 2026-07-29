# PartsPilot

PartsPilot is a web application MVP for dealership parts departments.
It uses an AI-style planning engine to recommend how to reduce obsolete inventory,
improve turn rate, and keep fill-rate risk under control.

## What This MVP Does

- Ingests parts data (demo data included).
- Scores each part for obsolescence risk and stockout risk.
- Recommends concrete actions:
	- `liquidate`
	- `return_to_vendor`
	- `transfer`
	- `hold`
	- `buy`
	- `stop_ordering`
- Produces KPI estimates for current vs projected inventory value and turns.
- Supports dealership-style file workflow:
	- Download import CSV template
	- Upload filled parts CSV
	- Export recommendation plan CSV

## Tech Stack

- Backend: FastAPI
- Frontend: Vanilla HTML/CSS/JS dashboard

## Run Locally

1. Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Start the app:

```bash
uvicorn app.main:app --reload
```

4. Open in your browser:

```text
http://127.0.0.1:8000
```

## Input Schema (Per Part)

Each part record should contain:

- `part_number` (string)
- `description` (string)
- `on_hand` (number)
- `on_order` (number)
- `monthly_demand_avg` (number)
- `last_sale_days` (number)
- `unit_cost` (number)
- `lead_time_days` (number)
- `returnable` (boolean)

Planner constraints now support advanced tuning fields in addition to the core controls:

- `emergency_stock_days` (integer, default `3`)
- `max_single_part_reduction_pct` (number, default `70`)
- `excess_days_supply_threshold` (integer, default `120`)
- `high_velocity_demand_threshold` (number, default `12`)

## CSV Workflow

1. Open the app and click `Download CSV Template`.
2. Fill your part records in the CSV.
3. Click `Import CSV` to load records into planner input.
4. Click `Run Plan` for recommendations.
5. Click `Export Plan CSV` to download output.

## API Endpoints

- `GET /health` - health check
- `GET /api/demo-data` - returns sample parts and constraints
- `POST /api/plan` - returns KPI summary and recommendations
- `GET /api/csv-template` - downloadable import template
- `POST /api/parts/import-csv` - parses CSV into parts payload
- `POST /api/plan/export-csv` - returns recommendations as CSV file

## Notes

- This is a practical MVP using deterministic scoring and optimization heuristics.
- You can later swap scoring components for ML models and connect your DMS/ERP.