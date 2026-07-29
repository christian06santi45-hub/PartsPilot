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
    confidence_score: float
    rationale: str
    inventory_value_impact: float


def calc_turns(on_hand: float, monthly_demand_avg: float) -> float:
    annual_demand = monthly_demand_avg * 12.0
    avg_inventory = max(on_hand / 2.0, 1.0)
    return safe_div(annual_demand, avg_inventory)


def calc_days_supply(on_hand: float, monthly_demand_avg: float) -> float:
    return safe_div(on_hand, max(monthly_demand_avg / 30.0, 0.001))


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
    days_supply = calc_days_supply(part.on_hand, part.monthly_demand_avg)
    lead_plus_review = part.lead_time_days + constraints.review_period_days

    pressure = safe_div(lead_plus_review - days_supply, max(lead_plus_review, 1.0))
    baseline = clamp(pressure, 0.0, 1.0)

    service_buffer = 1.0 + max(0.0, (constraints.min_fill_rate_pct - 94.0) / 100.0) * 0.4
    adjusted = clamp(baseline * service_buffer, 0.0, 1.0)

    if part.monthly_demand_avg <= 0.2:
        return adjusted * 0.25
    return adjusted


def calc_confidence_score(
    action: str,
    ob_risk: float,
    so_risk: float,
    days_supply: float,
    constraints: PlanConstraints,
) -> float:
    separation = abs(ob_risk - so_risk)

    if action == "buy":
        raw = 0.42 + (so_risk * 0.45) + ((1.0 - ob_risk) * 0.13)
    elif action in {"liquidate", "return_to_vendor"}:
        raw = 0.46 + (ob_risk * 0.39) + ((1.0 - so_risk) * 0.15)
    elif action in {"stop_ordering", "transfer"}:
        raw = 0.44 + (ob_risk * 0.31) + ((1.0 - so_risk) * 0.12)
    else:
        raw = 0.45 + ((1.0 - separation) * 0.2)

    if action in {"stop_ordering", "transfer", "liquidate", "return_to_vendor"}:
        threshold = max(constraints.excess_days_supply_threshold, 1)
        raw += clamp((days_supply - threshold) / threshold, 0.0, 0.12)

    if action == "hold" and so_risk >= 0.4:
        raw += 0.08

    return clamp(raw, 0.05, 0.99)


def recommend_for_part(part: PartRecord, constraints: PlanConstraints) -> PartMetrics:
    current_turns = calc_turns(part.on_hand, part.monthly_demand_avg)
    ob_risk = calc_obsolescence_risk(part)
    so_risk = calc_stockout_risk(part, constraints)

    action = "hold"
    order_qty = 0.0
    rationale = "Balanced profile; maintain current policy."
    value_impact = 0.0
    projected_on_hand = part.on_hand

    reduction_pressure = clamp(constraints.target_inventory_reduction_pct / 100.0, 0.0, 1.0)
    max_reduction_pct = clamp(constraints.max_single_part_reduction_pct / 100.0, 0.0, 1.0)
    days_supply = calc_days_supply(part.on_hand, part.monthly_demand_avg)
    high_velocity = part.monthly_demand_avg >= constraints.high_velocity_demand_threshold
    fresh_sales = part.last_sale_days <= 14
    emergency_floor = max(0.0, float(constraints.emergency_stock_days))
    excess_days = days_supply >= constraints.excess_days_supply_threshold

    def apply_reduction(raw_units: float) -> float:
        capped_units = min(raw_units, part.on_hand * max_reduction_pct)
        return clamp(capped_units, 0.0, part.on_hand)

    if high_velocity and fresh_sales and so_risk >= 0.35:
        action = "buy"
        coverage_days = part.lead_time_days + constraints.review_period_days + emergency_floor
        daily_demand = part.monthly_demand_avg / 30.0
        service_bias = max(0.0, (constraints.min_fill_rate_pct - 94.0) / 100.0)
        target_stock = coverage_days * daily_demand * (1.0 + service_bias)
        order_qty = max(target_stock - (part.on_hand + part.on_order), 0.0)
        projected_on_hand = part.on_hand + order_qty
        rationale = (
            "Fast-moving part with recent demand and service pressure; protect availability."
        )

    elif ob_risk >= 0.75 and so_risk <= 0.2:
        action = "return_to_vendor" if part.returnable else "liquidate"
        reduction_units = apply_reduction(part.on_hand * (0.65 + reduction_pressure * 0.2))
        value_impact = reduction_units * part.unit_cost
        projected_on_hand = max(part.on_hand - reduction_units, 0.0)
        rationale = (
            "High obsolescence risk with low service risk; remove majority of exposure now."
        )
    elif ob_risk >= 0.6 and so_risk <= 0.3:
        action = "stop_ordering"
        reduction_units = apply_reduction(part.on_hand * (0.35 + reduction_pressure * 0.15))
        value_impact = reduction_units * part.unit_cost
        projected_on_hand = max(part.on_hand - reduction_units, 0.0)
        rationale = "Aging inventory with weak demand; stop replenishment and run down stock."
    elif excess_days and part.monthly_demand_avg <= 3.0 and so_risk <= 0.45:
        action = "stop_ordering"
        reduction_units = apply_reduction(part.on_hand * (0.2 + reduction_pressure * 0.2))
        value_impact = reduction_units * part.unit_cost
        projected_on_hand = max(part.on_hand - reduction_units, 0.0)
        rationale = "Excess days of supply exceeds policy threshold; reduce depth gradually."
    elif so_risk >= 0.65 and ob_risk <= 0.55:
        action = "buy"
        target_days = part.lead_time_days + constraints.review_period_days + emergency_floor
        daily_demand = part.monthly_demand_avg / 30.0
        target_stock = target_days * daily_demand
        service_buffer = 1.0 + max(0.0, (constraints.min_fill_rate_pct - 94.0) / 100.0) * 1.2
        order_qty = max(target_stock * service_buffer - (part.on_hand + part.on_order), 0.0)
        projected_on_hand = part.on_hand + order_qty
        rationale = "High stockout risk; buy enough to protect fill-rate through lead time."
    elif ob_risk >= 0.5 and part.returnable:
        action = "transfer"
        reduction_units = apply_reduction(part.on_hand * (0.25 + reduction_pressure * 0.1))
        value_impact = reduction_units * part.unit_cost
        projected_on_hand = max(part.on_hand - reduction_units, 0.0)
        rationale = "Moderate obsolescence risk; transfer excess to higher-demand locations."

    if action in {"liquidate", "return_to_vendor", "transfer", "stop_ordering"} and so_risk >= 0.4:
        action = "hold"
        projected_on_hand = part.on_hand
        value_impact = 0.0
        rationale = "Inventory risk is elevated but service risk is material; avoid depletion action."

    projected_turns = calc_turns(projected_on_hand, part.monthly_demand_avg)
    confidence = calc_confidence_score(action, ob_risk, so_risk, days_supply, constraints)

    return PartMetrics(
        current_turns=round(current_turns, 2),
        projected_turns=round(projected_turns, 2),
        obsolescence_risk=round(ob_risk, 2),
        stockout_risk=round(so_risk, 2),
        recommended_action=action,
        recommended_order_qty=round(order_qty, 1),
        confidence_score=round(confidence, 2),
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
                confidence_score=metrics.confidence_score,
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
