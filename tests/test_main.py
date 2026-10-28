import datetime
import csv
import io
import unittest

from fastapi.testclient import TestClient

from app.main import app


class CsvImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_import_csv_parses_parts_from_json_payload(self) -> None:
        csv_text = (
            "part_number,description,on_hand,on_order,monthly_demand_avg,last_sale_days,"
            "unit_cost,lead_time_days,returnable\n"
            "BRK-1001,Brake Pad Front,42,10,16,11,36.5,9,true\n\n"
        )

        response = self.client.post("/api/parts/import-csv", json={"csv_text": csv_text})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["parts"]), 1)
        self.assertEqual(body["parts"][0]["part_number"], "BRK-1001")

    def test_import_csv_parses_parts_from_multiple_payloads(self) -> None:
        first_csv = (
            "part_number,description,on_hand,on_order,monthly_demand_avg,last_sale_days,"
            "unit_cost,lead_time_days,returnable\n"
            "BRK-1001,Brake Pad Front,42,10,16,11,36.5,9,true\n"
        )
        second_csv = (
            "part_number,description,on_hand,on_order,monthly_demand_avg,last_sale_days,"
            "unit_cost,lead_time_days,returnable\n"
            "FLTR-8840,Oil Filter Premium,210,0,5,98,7.2,6,true\n"
        )

        response = self.client.post(
            "/api/parts/import-csv",
            json={"csv_texts": [first_csv, second_csv]},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["parts"]), 2)
        self.assertEqual(
            {part["part_number"] for part in body["parts"]},
            {"BRK-1001", "FLTR-8840"},
        )

    def test_import_csv_supports_report_headers(self) -> None:
        csv_text = (
            "PART-NO,CURRENT-RPT,QOH,PO-QPR-DR,AVG-SLS,BASE-COST,AGE-DR\n"
            "ALT-001,Alternator,8,2,1.5,120.0,2\n"
        )

        response = self.client.post("/api/parts/import-csv", json={"csv_text": csv_text})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["parts"]), 1)
        self.assertEqual(body["parts"][0]["part_number"], "ALT-001")
        self.assertEqual(body["parts"][0]["description"], "Alternator")
        self.assertEqual(body["parts"][0]["on_hand"], 8.0)
        self.assertEqual(body["parts"][0]["on_order"], 2.0)
        self.assertEqual(body["parts"][0]["monthly_demand_avg"], 1.5)
        self.assertEqual(body["parts"][0]["unit_cost"], 120.0)
        self.assertEqual(body["parts"][0]["last_sale_days"], 60)
        self.assertEqual(body["parts"][0]["lead_time_days"], 7)
        self.assertEqual(body["parts"][0]["returnable"], True)

    def test_import_csv_defaults_missing_age_dr(self) -> None:
        csv_text = (
            "PART-NO,CURRENT-RPT,QOH,PO-QPR-DR,AVG-SLS,BASE-COST,AGE-DR\n"
            "ALT-002,Alternator Plus,8,2,1.5,120.0,\n"
        )

        response = self.client.post("/api/parts/import-csv", json={"csv_text": csv_text})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["parts"]), 1)
        self.assertEqual(body["parts"][0]["part_number"], "ALT-002")
        self.assertEqual(body["parts"][0]["last_sale_days"], 365)

    def test_import_csv_supports_hist_and_last_sale_date_variants(self) -> None:
        csv_text = (
            "PART-NO,CURRENT-RPT,QOH,PO-QPR-DR,HIST-SUM,BASE-COST,LAST SALE DATE\n"
            "ALT-004,Alternator Plus,8,2,24,120.0,2023-10-01\n"
        )

        response = self.client.post("/api/parts/import-csv", json={"csv_text": csv_text})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["parts"]), 1)
        self.assertEqual(body["parts"][0]["monthly_demand_avg"], 2.0)
        self.assertEqual(
            body["parts"][0]["last_sale_days"],
            (datetime.date.today() - datetime.date(2023, 10, 1)).days,
        )

    def test_import_csv_supports_hist_monthly_series(self) -> None:
        csv_text = (
            "PART-NO,CURRENT-RPT,QOH,PO-QPR-DR,HIST-1,HIST-2,HIST-3,BASE-COST,LAST-SALE-DAYS\n"
            "ALT-005,Alternator Plus,8,2,12,18,30,120.0,14\n"
        )

        response = self.client.post("/api/parts/import-csv", json={"csv_text": csv_text})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["parts"]), 1)
        self.assertEqual(body["parts"][0]["monthly_demand_avg"], 20.0)
        self.assertEqual(body["parts"][0]["last_sale_days"], 14)

    def test_import_csv_accepts_demand_alias_variants(self) -> None:
        csv_text = (
            "PART-NO,CURRENT-RPT,QOH,PO-QPR-DR,AVG-SLS-12M,BASE-COST,LAST SALE DATE\n"
            "ALT-006,Alternator Plus,8,2,24,120.0,2024-01-01\n"
        )

        response = self.client.post("/api/parts/import-csv", json={"csv_text": csv_text})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["parts"][0]["monthly_demand_avg"], 24.0)

    def test_import_csv_clamps_negative_on_hand_to_zero(self) -> None:
        csv_text = (
            "PART-NO,CURRENT-RPT,QOH,PO-QPR-DR,AVG-SLS,BASE-COST,AGE-DR\n"
            "ALT-003,Alternator Minus,-585,0,1.5,120.0,30\n"
        )

        response = self.client.post("/api/parts/import-csv", json={"csv_text": csv_text})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["parts"]), 1)
        self.assertEqual(body["parts"][0]["on_hand"], 0.0)

    def test_import_csv_supports_thousands_separators_and_whitespace_tables(self) -> None:
        whitespace_csv = (
            "PART-NO      CURRENT-RPT      QOH      PO-QPR-DR      AVG-SLS      BASE-COST      AGE-DR\n"
            "ALT-007      Booster Pump      1,250      120      18.5      2,490.50      14\n"
        )

        response = self.client.post("/api/parts/import-csv", json={"csv_text": whitespace_csv})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["parts"]), 1)
        self.assertEqual(body["parts"][0]["part_number"], "ALT-007")
        self.assertEqual(body["parts"][0]["on_hand"], 1250.0)
        self.assertEqual(body["parts"][0]["on_order"], 120.0)
        self.assertEqual(body["parts"][0]["monthly_demand_avg"], 18.5)
        self.assertEqual(body["parts"][0]["unit_cost"], 2490.5)
        self.assertEqual(body["parts"][0]["last_sale_days"], 420)

    def test_import_csv_supports_erp_style_headers(self) -> None:
        csv_text = (
            "PART-NO,DESC,OOH,QPR,MNS,BASE-COS,AGE-DR\n"
            "ALT-008,Water Pump,42,7,9.5,188.25,32\n"
        )

        response = self.client.post("/api/parts/import-csv", json={"csv_text": csv_text})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["parts"]), 1)
        self.assertEqual(body["parts"][0]["part_number"], "ALT-008")
        self.assertEqual(body["parts"][0]["description"], "Water Pump")
        self.assertEqual(body["parts"][0]["on_hand"], 42.0)
        self.assertEqual(body["parts"][0]["on_order"], 7.0)
        self.assertEqual(body["parts"][0]["monthly_demand_avg"], 9.5)
        self.assertEqual(body["parts"][0]["unit_cost"], 188.25)
        self.assertEqual(body["parts"][0]["last_sale_days"], 960)

    def test_import_csv_supports_tab_delimited_exports(self) -> None:
        csv_text = (
            "PART-NO\tDESC\tOOH\tQPR\tMNS\tBASE-COS\tAGE-DR\n"
            "ALT-009\tFan Belt\t18\t2\t4.0\t27.99\t10\n"
        )

        response = self.client.post("/api/parts/import-csv", json={"csv_text": csv_text})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["parts"]), 1)
        self.assertEqual(body["parts"][0]["part_number"], "ALT-009")
        self.assertEqual(body["parts"][0]["monthly_demand_avg"], 4.0)

    def test_import_csv_defaults_monthly_demand_to_zero_when_missing(self) -> None:
        csv_text = (
            "PART-NO,DESC,OOH,QPR,BASE-COS,AGE-DR\n"
            "ALT-010,No Demand Column,5,1,19.99,8\n"
        )

        response = self.client.post("/api/parts/import-csv", json={"csv_text": csv_text})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["parts"]), 1)
        self.assertEqual(body["parts"][0]["part_number"], "ALT-010")
        self.assertEqual(body["parts"][0]["monthly_demand_avg"], 0.0)

    def test_import_csv_defaults_last_sale_days_when_column_missing(self) -> None:
        csv_text = (
            "PART-NO,DESC,OOH,QPR,MNS,BASE-COS\n"
            "ALT-011,No Age Column,12,0,3.5,45.50\n"
        )

        response = self.client.post("/api/parts/import-csv", json={"csv_text": csv_text})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["parts"]), 1)
        self.assertEqual(body["parts"][0]["part_number"], "ALT-011")
        self.assertEqual(body["parts"][0]["last_sale_days"], 365)

    def test_import_csv_defaults_non_numeric_monthly_demand_to_zero(self) -> None:
        csv_text = (
            "PART-NO,DESC,OOH,QPR,MNS,BASE-COS,AGE-DR\n"
            "ALT-013,Bad MNS Value,10,1,GNBULK,15.00,5\n"
        )

        response = self.client.post("/api/parts/import-csv", json={"csv_text": csv_text})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["parts"]), 1)
        self.assertEqual(body["parts"][0]["part_number"], "ALT-013")
        self.assertEqual(body["parts"][0]["monthly_demand_avg"], 0.0)


class ExportPlanCsvTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_export_plan_csv_includes_dollar_and_fill_rate_columns(self) -> None:
        demo = self.client.get("/api/demo-data").json()
        payload = {"parts": demo["parts"], "constraints": demo["constraints"], "action_filter": "all"}

        response = self.client.post("/api/plan/export-csv", json=payload)

        self.assertEqual(response.status_code, 200)
        text = response.text
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertGreater(len(rows), 0)
        first_row = rows[0]
        self.assertIn("fill_rate_pct", first_row)
        self.assertIn("unit_cost_usd", first_row)
        self.assertIn("on_hand_value_usd", first_row)
        self.assertIn("on_order_value_usd", first_row)
        self.assertIn("inventory_value_impact_usd", first_row)
        self.assertTrue(first_row["unit_cost_usd"].startswith("$"))

    def test_export_plan_csv_respects_action_filter(self) -> None:
        demo = self.client.get("/api/demo-data").json()
        plan = self.client.post("/api/plan", json={"parts": demo["parts"], "constraints": demo["constraints"]}).json()
        target_action = plan["recommendations"][0]["recommended_action"]

        response = self.client.post(
            "/api/plan/export-csv",
            json={"parts": demo["parts"], "constraints": demo["constraints"], "action_filter": target_action},
        )

        self.assertEqual(response.status_code, 200)
        rows = list(csv.DictReader(io.StringIO(response.text)))
        self.assertGreater(len(rows), 0)
        self.assertTrue(all(row["recommended_action"] == target_action for row in rows))


if __name__ == "__main__":
    unittest.main()