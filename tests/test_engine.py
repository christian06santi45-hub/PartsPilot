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


if __name__ == "__main__":
    unittest.main()
