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


if __name__ == "__main__":
    unittest.main()