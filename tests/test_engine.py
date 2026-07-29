import unittest

from app.engine import recommend_for_part
from app.models import PartRecord, PlanConstraints


class EngineConstraintsTests(unittest.TestCase):
    def test_high_target_reduction_triggers_aggressive_action(self) -> None:
        part = PartRecord(
            part_number="TEST-1",
            description="Test part",
            on_hand=40,
            on_order=0,
            monthly_demand_avg=2.5,
            last_sale_days=220,
            unit_cost=12.0,
            lead_time_days=7,
            returnable=True,
        )
        constraints = PlanConstraints(
            target_inventory_reduction_pct=80,
            min_fill_rate_pct=98,
            review_period_days=14,
        )

        metrics = recommend_for_part(part, constraints)

        self.assertNotEqual(metrics.recommended_action, "hold")
        self.assertIn(metrics.recommended_action, {"stop_ordering", "transfer", "return_to_vendor"})

    def test_higher_fill_rate_target_increases_buy_quantity(self) -> None:
        part = PartRecord(
            part_number="TEST-2",
            description="Fast-moving part",
            on_hand=2,
            on_order=0,
            monthly_demand_avg=10,
            last_sale_days=5,
            unit_cost=25.0,
            lead_time_days=14,
            returnable=True,
        )

        low_target = PlanConstraints(
            target_inventory_reduction_pct=15,
            min_fill_rate_pct=94,
            review_period_days=14,
        )
        high_target = PlanConstraints(
            target_inventory_reduction_pct=15,
            min_fill_rate_pct=98,
            review_period_days=14,
        )

        low_metrics = recommend_for_part(part, low_target)
        high_metrics = recommend_for_part(part, high_target)

        self.assertGreater(high_metrics.recommended_order_qty, low_metrics.recommended_order_qty)

    def test_max_single_part_reduction_cap_is_respected(self) -> None:
        part = PartRecord(
            part_number="TEST-3",
            description="Slow mover",
            on_hand=100,
            on_order=0,
            monthly_demand_avg=0.8,
            last_sale_days=400,
            unit_cost=10.0,
            lead_time_days=10,
            returnable=True,
        )
        constraints = PlanConstraints(
            target_inventory_reduction_pct=90,
            min_fill_rate_pct=94,
            review_period_days=14,
            max_single_part_reduction_pct=30,
        )

        metrics = recommend_for_part(part, constraints)
        self.assertLessEqual(metrics.inventory_value_impact, 300.0)

    def test_high_velocity_part_gets_protected_with_buy_action(self) -> None:
        part = PartRecord(
            part_number="TEST-4",
            description="Fast seller",
            on_hand=1,
            on_order=0,
            monthly_demand_avg=16,
            last_sale_days=3,
            unit_cost=28.0,
            lead_time_days=12,
            returnable=True,
        )
        constraints = PlanConstraints(
            target_inventory_reduction_pct=25,
            min_fill_rate_pct=98,
            review_period_days=14,
            emergency_stock_days=5,
            high_velocity_demand_threshold=10,
        )

        metrics = recommend_for_part(part, constraints)
        self.assertEqual(metrics.recommended_action, "buy")
        self.assertGreater(metrics.recommended_order_qty, 0.0)

    def test_high_stockout_risk_blocks_depletion_actions(self) -> None:
        part = PartRecord(
            part_number="TEST-5",
            description="Intermittent legacy part",
            on_hand=0,
            on_order=0,
            monthly_demand_avg=0.5,
            last_sale_days=400,
            unit_cost=80.0,
            lead_time_days=14,
            returnable=True,
        )
        constraints = PlanConstraints(
            target_inventory_reduction_pct=35,
            min_fill_rate_pct=95,
            review_period_days=14,
        )

        metrics = recommend_for_part(part, constraints)
        self.assertEqual(metrics.recommended_action, "hold")
        self.assertEqual(metrics.inventory_value_impact, 0.0)

    def test_confidence_score_is_bounded(self) -> None:
        part = PartRecord(
            part_number="TEST-6",
            description="General part",
            on_hand=15,
            on_order=0,
            monthly_demand_avg=4,
            last_sale_days=75,
            unit_cost=9.0,
            lead_time_days=6,
            returnable=True,
        )
        constraints = PlanConstraints()

        metrics = recommend_for_part(part, constraints)
        self.assertGreaterEqual(metrics.confidence_score, 0.0)
        self.assertLessEqual(metrics.confidence_score, 1.0)


if __name__ == "__main__":
    unittest.main()
