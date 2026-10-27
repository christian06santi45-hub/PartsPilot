from __future__ import annotations

import csv
import datetime
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


@app.middleware("http")
async def disable_browser_cache(request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/web/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


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
    "part_number": ["part_number", "part-no", "part no", "partno", "part_no"],
    "description": ["description", "current-rpt", "current_rpt", "desc"],
    "on_hand": ["on_hand", "qoh", "tqty", "tot-stk-qty", "qty_on_hand", "qty-on-hand"],
    "on_order": ["on_order", "po-qpr-dr", "po_qpr_dr"],
    "monthly_demand_avg": [
        "monthly_demand_avg",
        "monthly-demand-avg",
        "monthly demand avg",
        "monthly_demand",
        "monthly-demand",
        "avg-sls",
        "avg_sls",
        "avg-sls-12m",
        "avg_sls_12m",
        "avg-sls-12mo",
        "avg_sls_12mo",
        "avg-sls-12month",
        "avg_sls_12month",
        "avg-sls-annual",
        "avg_sls_annual",
        "avg_sls_annualized",
        "hist",
        "hist-sum",
        "hist_sum",
        "hist-total",
        "hist_total",
        "hist-year",
        "hist_year",
        "avg_12m",
        "avg_12_month",
        "demand",
    ],
    "last_sale_days": [
        "last_sale_days",
        "last-sale-days",
        "last sale days",
        "last sale day",
        "last-sale",
        "last-sale-date",
        "last_sale_date",
        "last sale date",
        "last-sale-dt",
        "last_sale_dt",
        "last-sales-date",
        "last_sls_date",
        "last-sls-date",
        "last_sls_days",
        "days-since-last-sale",
        "days_since_last_sale",
        "days-since-last-sold",
        "days_since_last_sold",
        "days_since_last_sale_days",
        "age-dr",
        "age_dr",
        "age",
        "last_sale",
    ],
    "unit_cost": ["unit_cost", "unit-cost", "base-cost", "base_cost"],
    "lead_time_days": ["lead_time_days", "lead_time", "lead-time-days", "lead_time_days"],
    "returnable": ["returnable", "returnable_flag"],
}


def _normalize_header(name: str) -> str:
    lowered = (name or "").strip().lower()
    return re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")


def _alias_to_normalized(alias: str) -> str:
    return _normalize_header(alias)


def _is_hist_total_key(key: str) -> bool:
    normalized = key.strip().lower()
    if normalized == "hist":
        return True
    return bool(re.search(r"(?:^|[_-])(sum|total|annual|year|yr)(?:$|[_-])", normalized))


def _header_name_matches_alias(header_name: str, alias: str) -> bool:
    normalized_name = _normalize_header(header_name)
    normalized_alias = _normalize_header(alias)
    if normalized_name == normalized_alias:
        return True

    name_parts = set(part for part in normalized_name.split("_") if part)
    alias_parts = set(part for part in normalized_alias.split("_") if part)
    if alias_parts.issubset(name_parts):
        return True

    if normalized_alias in normalized_name or normalized_name in normalized_alias:
        return True

    if normalized_alias.startswith("hist") and normalized_name.startswith("hist"):
        return True

    return False


def _get_from_aliases(normalized_row: dict[str, str], aliases: list[str]) -> str | None:
    for alias in aliases:
        for key, value in normalized_row.items():
            if not _header_name_matches_alias(key, alias):
                continue
            if key.startswith("hist") and key not in {"hist", "hist_sum", "hist_total", "hist_year", "hist_annual"}:
                continue
            stripped = value.strip()
            if stripped == "":
                continue
            if key.startswith("hist") and _is_hist_total_key(key):
                return str(float(stripped) / 12)
            return stripped
    return None


def _is_hist_key(key: str) -> bool:
    return bool(re.fullmatch(r"hist(?:[0-9]+|(?:[-_][a-z0-9]+)*)", key))


def _get_monthly_demand_from_hist_fields(normalized_row: dict[str, str]) -> str | None:
    hist_entries: list[tuple[str, float]] = []
    for key, value in normalized_row.items():
        if not _is_hist_key(key):
            continue
        stripped = value.strip()
        if stripped == "":
            continue
        try:
            hist_entries.append((key, float(stripped)))
        except ValueError:
            continue

    if not hist_entries:
        return None

    if len(hist_entries) == 1:
        key, value = hist_entries[0]
        if re.search(r"(?:sum|total|annual|year)", key):
            return str(value / 12)
        return str(value)

    total = sum(value for _, value in hist_entries)
    return str(total / len(hist_entries))


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


def _coerce_non_negative(value: str, field_name: str) -> float:
    numeric = float(value)
    if numeric < 0:
        return 0.0
    return numeric


def _parse_date_like_to_days(value: str) -> int | None:
    if value is None:
        return None

    text = value.strip()
    if text == "":
        return None

    try:
        num = float(text)
        if num > 100000:
            return max(0, int((datetime.date.today() - datetime.date(1899, 12, 30)).days - num))
        return None
    except ValueError:
        pass

    for fmt in (
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%m-%d-%Y",
        "%m-%d-%y",
        "%Y/%m/%d",
        "%m/%d/%y %H:%M:%S",
        "%m/%d/%Y %H:%M:%S",
        "%m-%d-%Y %H:%M:%S",
    ):
        try:
            parsed = datetime.datetime.strptime(text, fmt).date()
            return max(0, (datetime.date.today() - parsed).days)
        except ValueError:
            continue

    try:
        parsed = datetime.date.fromisoformat(text)
        return max(0, (datetime.date.today() - parsed).days)
    except ValueError:
        return None


def _coerce_last_sale_days(raw_value: str | None) -> str:
    if raw_value is None:
        return "365"

    text = raw_value.strip()
    if text == "":
        return "365"

    try:
        return str(max(0, int(float(text))))
    except ValueError:
        parsed_days = _parse_date_like_to_days(text)
        if parsed_days is not None:
            return str(parsed_days)
        return "365"


def _resolve_last_sale_days(normalized_row: dict[str, str]) -> str | None:
    direct_aliases = [
        "last_sale_days",
        "last-sale-days",
        "last sale days",
        "last-sale",
        "last-sale-date",
        "last_sale_date",
        "last sale date",
        "last-sale-dt",
        "last_sale_dt",
        "last-sales-date",
        "last_sls_date",
        "days-since-last-sale",
        "days_since_last_sale",
    ]
    age_aliases = ["age-dr", "age_dr", "age"]

    direct_value = _get_from_aliases(normalized_row, direct_aliases)
    if direct_value is not None:
        return _coerce_last_sale_days(direct_value)

    for age_alias in age_aliases:
        age_value = _get_from_aliases(normalized_row, [age_alias])
        if age_value is not None:
            return str(max(0, int(float(age_value) * 30)))

    return None


def _csv_row_to_part(row: dict[str, str], row_number: int) -> PartRecord:
    try:
        normalized_row = {
            _normalize_header(key): (value or "").strip()
            for key, value in row.items()
            if key is not None
        }

        monthly_demand = _get_from_aliases(normalized_row, CSV_COLUMN_ALIASES["monthly_demand_avg"])
        if monthly_demand is None:
            monthly_demand = _get_monthly_demand_from_hist_fields(normalized_row)

        last_sale_days = _resolve_last_sale_days(normalized_row)

        # Some dealership report rows omit age values; treat as stale by default.
        if last_sale_days is None:
            last_sale_days = "365"

        part_number = _get_from_aliases(normalized_row, CSV_COLUMN_ALIASES["part_number"])
        if part_number is None:
            raise KeyError("part_number")
        on_hand = _get_from_aliases(normalized_row, CSV_COLUMN_ALIASES["on_hand"])
        if on_hand is None:
            raise KeyError("on_hand")
        if monthly_demand is None:
            raise KeyError("monthly_demand_avg")
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
            "on_hand": _coerce_non_negative(on_hand, "on_hand"),
            "on_order": _coerce_non_negative(on_order, "on_order"),
            "monthly_demand_avg": _coerce_non_negative(monthly_demand, "monthly_demand_avg"),
            "last_sale_days": max(0, int(float(last_sale_days))),
            "unit_cost": max(0.0, float(unit_cost)),
            "lead_time_days": max(0, int(float(lead_time_days))),
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
    hist_columns_present = any(_is_hist_key(name) for name in normalized_fieldnames)

    def has_compatible_field(field_name: str, aliases: list[str]) -> bool:
        for alias in aliases:
            for header_name in normalized_fieldnames:
                if _header_name_matches_alias(header_name, alias):
                    return True
        if field_name == "monthly_demand_avg" and hist_columns_present:
            return True
        return False

    required_sources = {
        "part_number": ["part_number", "part-no", "part_no"],
        "on_hand": ["on_hand", "qoh", "tqty", "tot-stk-qty", "qty_on_hand", "qty-on-hand"],
        "monthly_demand_avg": [
            "monthly_demand_avg",
            "monthly-demand-avg",
            "monthly demand avg",
            "avg-sls",
            "avg_sls",
            "hist",
            "hist-sum",
            "hist_sum",
            "hist-total",
            "hist_total",
            "demand",
            "monthly_demand",
        ],
        "last_sale_days": [
            "last_sale_days",
            "last-sale-days",
            "last sale days",
            "last-sale",
            "last-sale-date",
            "last_sale_date",
            "last sale date",
            "last-sale-dt",
            "last_sale_dt",
            "last-sales-date",
            "last_sls_date",
            "last-sls-date",
            "age-dr",
            "age_dr",
            "age",
            "days-since-last-sale",
            "days_since_last_sale",
            "sale_days",
            "last_sale",
        ],
        "unit_cost": ["unit_cost", "unit-cost", "base-cost", "base_cost"],
    }

    missing_columns: list[str] = []
    for internal_name, aliases in required_sources.items():
        if not has_compatible_field(internal_name, aliases):
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
