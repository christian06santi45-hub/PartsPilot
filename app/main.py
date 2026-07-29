from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.engine import build_plan
from app.models import PartRecord, PlanConstraints, PlanRequest, PlanResponse

app = FastAPI(title="PartsPilot", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/web", StaticFiles(directory="web"), name="web")

CSV_COLUMNS = [
    "part_number",
    "description",
    "on_hand",
    "on_order",
    "monthly_demand_avg",
    "last_sale_days",
    "unit_cost",
    "lead_time_days",
    "returnable",
]


def _coerce_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise ValueError(f"Invalid boolean value: {value}")


def _csv_row_to_part(row: dict[str, str], row_number: int) -> PartRecord:
    try:
        payload: dict[str, Any] = {
            "part_number": row["part_number"],
            "description": row.get("description", ""),
            "on_hand": float(row["on_hand"]),
            "on_order": float(row.get("on_order", "0") or 0),
            "monthly_demand_avg": float(row["monthly_demand_avg"]),
            "last_sale_days": int(float(row["last_sale_days"])),
            "unit_cost": float(row["unit_cost"]),
            "lead_time_days": int(float(row["lead_time_days"])),
            "returnable": _coerce_bool(row.get("returnable", "true")),
        }
        return PartRecord(**payload)
    except KeyError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required CSV column: {exc.args[0]}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid value at CSV row {row_number}: {exc}",
        ) from exc


@app.get("/")
def index() -> FileResponse:
    return FileResponse("web/index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/demo-data")
def demo_data() -> dict[str, list[PartRecord] | PlanConstraints]:
    sample_parts = [
        PartRecord(
            part_number="BRK-1001",
            description="Brake Pad Front",
            on_hand=42,
            on_order=10,
            monthly_demand_avg=16,
            last_sale_days=11,
            unit_cost=36.5,
            lead_time_days=9,
            returnable=True,
        ),
        PartRecord(
            part_number="FLTR-8840",
            description="Oil Filter Premium",
            on_hand=210,
            on_order=0,
            monthly_demand_avg=5,
            last_sale_days=98,
            unit_cost=7.2,
            lead_time_days=6,
            returnable=True,
        ),
        PartRecord(
            part_number="SNSR-2219",
            description="O2 Sensor Rear",
            on_hand=18,
            on_order=2,
            monthly_demand_avg=1.2,
            last_sale_days=140,
            unit_cost=58,
            lead_time_days=14,
            returnable=False,
        ),
        PartRecord(
            part_number="CLIP-0099",
            description="Trim Clip Pack",
            on_hand=550,
            on_order=0,
            monthly_demand_avg=3,
            last_sale_days=315,
            unit_cost=0.9,
            lead_time_days=21,
            returnable=False,
        ),
        PartRecord(
            part_number="BAT-7002",
            description="12V Battery",
            on_hand=9,
            on_order=0,
            monthly_demand_avg=7,
            last_sale_days=6,
            unit_cost=95,
            lead_time_days=4,
            returnable=True,
        ),
    ]

    return {"parts": sample_parts, "constraints": PlanConstraints()}


@app.get("/api/csv-template")
def csv_template() -> StreamingResponse:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    writer.writerow(
        {
            "part_number": "BRK-1001",
            "description": "Brake Pad Front",
            "on_hand": "42",
            "on_order": "10",
            "monthly_demand_avg": "16",
            "last_sale_days": "11",
            "unit_cost": "36.5",
            "lead_time_days": "9",
            "returnable": "true",
        }
    )

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=partspilot_template.csv"},
    )


@app.post("/api/parts/import-csv")
async def import_parts_csv(file: UploadFile = File(...)) -> dict[str, Any]:
    raw_bytes = await file.read()
    try:
        content = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded.") from exc

    reader = csv.DictReader(io.StringIO(content))
    if reader.fieldnames is None:
        raise HTTPException(status_code=400, detail="CSV appears to be empty.")

    missing_columns = [col for col in CSV_COLUMNS if col not in reader.fieldnames]
    if missing_columns:
        raise HTTPException(
            status_code=400,
            detail=f"CSV missing columns: {', '.join(missing_columns)}",
        )

    parts = [_csv_row_to_part(row, row_number=i + 2) for i, row in enumerate(reader)]
    return {"parts": [part.model_dump() for part in parts]}


@app.post("/api/plan", response_model=PlanResponse)
def create_plan(payload: PlanRequest) -> PlanResponse:
    if not payload.parts:
        return PlanResponse(
            summary={
                "current_inventory_value": 0,
                "projected_inventory_value": 0,
                "inventory_reduction_pct": 0,
                "current_weighted_turns": 0,
                "projected_weighted_turns": 0,
                "parts_flagged_obsolete": 0,
                "parts_buy_recommended": 0,
            },
            recommendations=[],
        )

    return build_plan(payload.parts, payload.constraints)


@app.post("/api/plan/export-csv")
def export_plan_csv(payload: PlanRequest) -> StreamingResponse:
    plan = create_plan(payload)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "part_number",
            "description",
            "recommended_action",
            "obsolescence_risk",
            "stockout_risk",
            "current_turns",
            "projected_turns",
            "recommended_order_qty",
            "inventory_value_impact",
            "rationale",
        ]
    )

    for rec in plan.recommendations:
        writer.writerow(
            [
                rec.part_number,
                rec.description,
                rec.recommended_action,
                rec.obsolescence_risk,
                rec.stockout_risk,
                rec.current_turns,
                rec.projected_turns,
                rec.recommended_order_qty,
                rec.inventory_value_impact,
                rec.rationale,
            ]
        )

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=partspilot_plan.csv"},
    )
