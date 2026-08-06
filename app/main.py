from __future__ import annotations

import csv
import io
import re
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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

CSV_COLUMN_ALIASES: dict[str, list[str]] = {
    "part_number": ["part_number", "part-no", "part no", "partno"],
    "description": ["description", "current-rpt", "desc"],
    "on_hand": ["on_hand", "qoh", "tqty", "tot-stk-qty"],
    "on_order": ["on_order", "po-qpr-dr"],
    "monthly_demand_avg": ["monthly_demand_avg", "avg-sls"],
    "last_sale_days": ["last_sale_days", "age-dr"],
    "unit_cost": ["unit_cost", "base-cost"],
    "lead_time_days": ["lead_time_days", "lead_time", "lead-time-days"],
    "returnable": ["returnable"],
}


def _normalize_header(name: str) -> str:
    lowered = (name or "").strip().lower()
    return re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")


def _alias_to_normalized(alias: str) -> str:
    return _normalize_header(alias)


def _get_from_aliases(normalized_row: dict[str, str], aliases: list[str]) -> str | None:
    for alias in aliases:
        key = _alias_to_normalized(alias)
        if key in normalized_row and normalized_row[key].strip() != "":
            return normalized_row[key].strip()
    return None


class ImportCsvRequest(BaseModel):
    csv_text: str | None = None
    csv_texts: list[str] | None = None


def _coerce_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise ValueError(f"Invalid boolean value: {value}")


def _csv_row_to_part(row: dict[str, str], row_number: int) -> PartRecord:
    try:
        normalized_row = {
            _normalize_header(key): (value or "").strip()
            for key, value in row.items()
            if key is not None
        }

        monthly_demand = _get_from_aliases(normalized_row, CSV_COLUMN_ALIASES["monthly_demand_avg"])
        if monthly_demand is None:
            hist_sum = _get_from_aliases(normalized_row, ["hist-sum"])
            if hist_sum is not None:
                monthly_demand = str(float(hist_sum) / 12)

        last_sale_days = _get_from_aliases(normalized_row, ["last_sale_days"])
        if last_sale_days is None:
            age_dr_months = _get_from_aliases(normalized_row, ["age-dr"])
            if age_dr_months is not None:
                last_sale_days = str(float(age_dr_months) * 30)

        part_number = _get_from_aliases(normalized_row, CSV_COLUMN_ALIASES["part_number"])
        if part_number is None:
            raise KeyError("part_number")
        on_hand = _get_from_aliases(normalized_row, CSV_COLUMN_ALIASES["on_hand"])
        if on_hand is None:
            raise KeyError("on_hand")
        if monthly_demand is None:
            raise KeyError("monthly_demand_avg")
        if last_sale_days is None:
            raise KeyError("last_sale_days")
        unit_cost = _get_from_aliases(normalized_row, CSV_COLUMN_ALIASES["unit_cost"])
        if unit_cost is None:
            raise KeyError("unit_cost")

        description = _get_from_aliases(normalized_row, CSV_COLUMN_ALIASES["description"]) or ""
        on_order = _get_from_aliases(normalized_row, CSV_COLUMN_ALIASES["on_order"]) or "0"
        lead_time_days = _get_from_aliases(normalized_row, CSV_COLUMN_ALIASES["lead_time_days"]) or "7"
        returnable_raw = _get_from_aliases(normalized_row, CSV_COLUMN_ALIASES["returnable"]) or "true"

        payload: dict[str, Any] = {
            "part_number": part_number,
            "description": description,
            "on_hand": float(on_hand),
            "on_order": float(on_order),
            "monthly_demand_avg": float(monthly_demand),
            "last_sale_days": int(float(last_sale_days)),
            "unit_cost": float(unit_cost),
            "lead_time_days": int(float(lead_time_days)),
            "returnable": _coerce_bool(returnable_raw),
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


def _parse_parts_csv(content: str) -> list[PartRecord]:
    reader = csv.DictReader(io.StringIO(content))
    if reader.fieldnames is None:
        raise HTTPException(status_code=400, detail="CSV appears to be empty.")

    normalized_fieldnames = {_normalize_header(name) for name in reader.fieldnames if name is not None}

    required_sources = {
        "part_number": ["part_number", "part-no"],
        "on_hand": ["on_hand", "qoh", "tqty", "tot-stk-qty"],
        "monthly_demand_avg": ["monthly_demand_avg", "avg-sls", "hist-sum"],
        "last_sale_days": ["last_sale_days", "age-dr"],
        "unit_cost": ["unit_cost", "base-cost"],
    }

    missing_columns: list[str] = []
    for internal_name, aliases in required_sources.items():
        alias_keys = {_alias_to_normalized(alias) for alias in aliases}
        if normalized_fieldnames.isdisjoint(alias_keys):
            missing_columns.append(internal_name)

    if missing_columns:
        raise HTTPException(
            status_code=400,
            detail=(
                "CSV missing required data for: "
                f"{', '.join(missing_columns)}. "
                "Supported report headers include PART-NO, CURRENT-RPT, QOH, PO-QPR-DR, AVG-SLS, BASE-COST, AGE-DR."
            ),
        )

    parts: list[PartRecord] = []
    for index, row in enumerate(reader, start=2):
        if not any((value or "").strip() for value in row.values()):
            continue
        parts.append(_csv_row_to_part(row, row_number=index))

    return parts


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
def import_parts_csv(payload: ImportCsvRequest) -> dict[str, Any]:
    sources = payload.csv_texts or []
    if payload.csv_text is not None:
        sources = [payload.csv_text] + sources

    if not sources:
        raise HTTPException(status_code=400, detail="No CSV content provided.")

    all_parts: list[PartRecord] = []
    for content in sources:
        cleaned_content = content.lstrip("\ufeff")
        all_parts.extend(_parse_parts_csv(cleaned_content))

    return {"parts": [part.model_dump() for part in all_parts]}


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
            "confidence_score",
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
                rec.confidence_score,
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
