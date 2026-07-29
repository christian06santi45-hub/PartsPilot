from __future__ import annotations

from dataclasses import dataclass

from app.models import (
    KpiSummary,
    PartRecord,
    PartRecommendation,
    PlanConstraints,
    PlanResponse,
)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def safe_div(num: float, den: float) -> float:
    if den <= 0:
        return 0.0
    return num / den


@dataclass
class PartMetrics:
    current_turns: float
    projected_turns: float
    obsolescence_risk: float
    stockout_risk: float
    recommended_action: str
    recommended_order_qty: float
    rationale: str
    inventory_value_impact: float


def calc_turns(on_hand: float, monthly_demand_avg: float) -> float:
    annual_demand = monthly_demand_avg * 12.0
    avg_inventory = max(on_hand / 2.0, 1.0)
    return safe_div(annual_demand, avg_inventory)


def calc_obsolescence_risk(part: PartRecord) -> float:
    stale_component = clamp(part.last_sale_days / 365.0, 0.0, 1.5)
    low_demand_component = clamp(1.0 - safe_div(part.monthly_demand_avg, 6.0), 0.0, 1.0)
    stock_excess_component = clamp(
        safe_div(part.on_hand, max(part.monthly_demand_avg, 0.25)) / 12.0,
        0.0,
        1.5,
    )

    risk = (
        stale_component * 0.45
        + low_demand_component * 0.25
        + stock_excess_component * 0.30
    )
    return clamp(risk, 0.0, 1.0)


def calc_stockout_risk(part: PartRecord, constraints: PlanConstraints) -> float:
    daily_demand = part.monthly_demand_avg / 30.0
    days_supply = safe_div(part.on_hand, max(daily_demand, 0.001))
    lead_plus_review = part.lead_time_days + constraints.review_period_days

    pressure = safe_div(lead_plus_review - days_supply, max(lead_plus_review, 1.0))
    baseline = clamp(pressure, 0.0, 1.0)

    if part.monthly_demand_avg <= 0.2:
        return baseline * 0.25
    return baseline


def recommend_for_part(part: PartRecord, constraints: PlanConstraints) -> PartMetrics:
    current_turns = calc_turns(part.on_hand, part.monthly_demand_avg)
    ob_risk = calc_obsolescence_risk(part)
    so_risk = calc_stockout_risk(part, constraints)

    action = "hold"
    order_qty = 0.0
    rationale = "Balanced profile; maintain current policy."
    value_impact = 0.0
    projected_on_hand = part.on_hand

    if ob_risk >= 0.75 and so_risk <= 0.2:
        action = "return_to_vendor" if part.returnable else "liquidate"
        reduction_units = part.on_hand * 0.65
        value_impact = reduction_units * part.unit_cost
        projected_on_hand = max(part.on_hand - reduction_units, 0.0)
        rationale = (
            "High obsolescence risk with low service risk; remove majority of exposure now."
        )
    elif ob_risk >= 0.6 and so_risk <= 0.3:
        action = "stop_ordering"
        reduction_units = part.on_hand * 0.35
        value_impact = reduction_units * part.unit_cost
        projected_on_hand = max(part.on_hand - reduction_units, 0.0)
        rationale = "Aging inventory with weak demand; stop replenishment and run down stock."
    elif so_risk >= 0.65 and ob_risk <= 0.55:
        action = "buy"
        target_days = part.lead_time_days + constraints.review_period_days + 7
        daily_demand = part.monthly_demand_avg / 30.0
        target_stock = target_days * daily_demand
        order_qty = max(target_stock - (part.on_hand + part.on_order), 0.0)
        projected_on_hand = part.on_hand + order_qty
        rationale = "High stockout risk; buy enough to protect fill-rate through lead time."
    elif ob_risk >= 0.5 and part.returnable:
        action = "transfer"
        reduction_units = part.on_hand * 0.25
        value_impact = reduction_units * part.unit_cost
        projected_on_hand = max(part.on_hand - reduction_units, 0.0)
        rationale = "Moderate obsolescence risk; transfer excess to higher-demand locations."

    projected_turns = calc_turns(projected_on_hand, part.monthly_demand_avg)

    return PartMetrics(
        current_turns=round(current_turns, 2),
        projected_turns=round(projected_turns, 2),
        obsolescence_risk=round(ob_risk, 2),
        stockout_risk=round(so_risk, 2),
        recommended_action=action,
        recommended_order_qty=round(order_qty, 1),
        rationale=rationale,
        inventory_value_impact=round(value_impact, 2),
    )


def build_plan(parts: list[PartRecord], constraints: PlanConstraints) -> PlanResponse:
    recommendations: list[PartRecommendation] = []

    current_value = 0.0
    projected_value = 0.0
    current_turn_numerator = 0.0
    projected_turn_numerator = 0.0
    total_weight = 0.0
    obsolete_count = 0
    buy_count = 0

    for part in parts:
        metrics = recommend_for_part(part, constraints)

        part_value = part.on_hand * part.unit_cost
        projected_on_hand_value = (
            (part.on_hand * part.unit_cost)
            - metrics.inventory_value_impact
            + (metrics.recommended_order_qty * part.unit_cost)
        )

        weight = max(part_value, 1.0)
        current_turn_numerator += metrics.current_turns * weight
        projected_turn_numerator += metrics.projected_turns * weight
        total_weight += weight

        current_value += part_value
        projected_value += max(projected_on_hand_value, 0.0)

        if metrics.obsolescence_risk >= 0.6:
            obsolete_count += 1
        if metrics.recommended_action == "buy":
            buy_count += 1

        recommendations.append(
            PartRecommendation(
                part_number=part.part_number,
                description=part.description,
                current_turns=metrics.current_turns,
                projected_turns=metrics.projected_turns,
                obsolescence_risk=metrics.obsolescence_risk,
                stockout_risk=metrics.stockout_risk,
                recommended_action=metrics.recommended_action,
                recommended_order_qty=metrics.recommended_order_qty,
                rationale=metrics.rationale,
                inventory_value_impact=metrics.inventory_value_impact,
            )
        )

    inventory_reduction_pct = 0.0
    if current_value > 0:
        inventory_reduction_pct = ((current_value - projected_value) / current_value) * 100.0

    summary = KpiSummary(
        current_inventory_value=round(current_value, 2),
        projected_inventory_value=round(projected_value, 2),
        inventory_reduction_pct=round(inventory_reduction_pct, 2),
        current_weighted_turns=round(safe_div(current_turn_numerator, total_weight), 2),
        projected_weighted_turns=round(
            safe_div(projected_turn_numerator, total_weight),
            2,
        ),
        parts_flagged_obsolete=obsolete_count,
        parts_buy_recommended=buy_count,
    )

    recommendations.sort(
        key=lambda r: (r.recommended_action != "liquidate", -r.obsolescence_risk)
    )

    return PlanResponse(summary=summary, recommendations=recommendations)
