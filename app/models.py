from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ActionType = Literal[
    "liquidate",
    "return_to_vendor",
    "transfer",
    "hold",
    "buy",
    "stop_ordering",
]


class PartRecord(BaseModel):
    part_number: str = Field(..., min_length=1)
    description: str = ""
    on_hand: float = Field(..., ge=0)
    on_order: float = Field(0, ge=0)
    monthly_demand_avg: float = Field(..., ge=0)
    last_sale_days: int = Field(..., ge=0)
    unit_cost: float = Field(..., ge=0)
    lead_time_days: int = Field(..., ge=0)
    returnable: bool = True


class PlanConstraints(BaseModel):
    target_inventory_reduction_pct: float = Field(15, ge=0, le=100)
    min_fill_rate_pct: float = Field(94, ge=0, le=100)
    review_period_days: int = Field(14, ge=1)


class PlanRequest(BaseModel):
    parts: list[PartRecord]
    constraints: PlanConstraints = PlanConstraints()


class PartRecommendation(BaseModel):
    part_number: str
    description: str
    current_turns: float
    projected_turns: float
    obsolescence_risk: float
    stockout_risk: float
    recommended_action: ActionType
    recommended_order_qty: float
    rationale: str
    inventory_value_impact: float


class KpiSummary(BaseModel):
    current_inventory_value: float
    projected_inventory_value: float
    inventory_reduction_pct: float
    current_weighted_turns: float
    projected_weighted_turns: float
    parts_flagged_obsolete: int
    parts_buy_recommended: int


class PlanResponse(BaseModel):
    summary: KpiSummary
    recommendations: list[PartRecommendation]
