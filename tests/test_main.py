import datetime
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


if __name__ == "__main__":
    unittest.main()