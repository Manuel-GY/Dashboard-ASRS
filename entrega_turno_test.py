import unittest
from datetime import datetime
from unittest.mock import patch

import serve_web


class EntregaTurnoTests(unittest.TestCase):
    def test_current_shift_includes_grace_and_night_closing_date(self):
        cases = [
            ("2026-10-19 00:00:00", "2026-10-19", "T1"),
            ("2026-10-19 06:00:00", "2026-10-19", "T1"),
            ("2026-10-19 06:58:59", "2026-10-19", "T1"),
            ("2026-10-19 06:59:00", "2026-10-19", "T2"),
            ("2026-10-19 14:00:00", "2026-10-19", "T2"),
            ("2026-10-19 14:58:59", "2026-10-19", "T2"),
            ("2026-10-19 14:59:00", "2026-10-19", "T3"),
            ("2026-10-19 22:00:00", "2026-10-19", "T3"),
            ("2026-10-19 22:58:59", "2026-10-19", "T3"),
            ("2026-10-19 22:59:00", "2026-10-20", "T1"),
            ("2026-12-31 23:30:00", "2027-01-01", "T1"),
        ]
        for timestamp, fecha, turno in cases:
            with self.subTest(timestamp=timestamp):
                result = serve_web.get_entrega_turno_context(datetime.fromisoformat(timestamp))
                self.assertEqual((result["fecha"], result["turno"]), (fecha, turno))
                today = timestamp[:10]
                self.assertEqual(result["max_fechas"], {
                    "T1": max(today, fecha), "T2": today, "T3": today,
                })

    def test_current_endpoint_uses_plant_clock_not_saved_metrics(self):
        with patch("scheduler_service.get_target_now", return_value=datetime(2026, 10, 19, 6, 30)), \
                patch("serve_web.get_capped_now", side_effect=AssertionError("stale clock")):
            response = serve_web.app.test_client().get("/api/entrega-turno/actual")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["fecha"], "2026-10-19")
        self.assertEqual(response.json["turno"], "T1")
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_future_dates_rejected_before_fetching_metrics(self):
        with patch("scheduler_service.get_target_now", return_value=datetime(2026, 10, 19, 23)), \
                patch("serve_web.fetch_json") as fetch:
            client = serve_web.app.test_client()
            for fecha, turno in [
                ("2026-10-20", "T2"), ("2026-10-20", "T3"),
                ("2026-10-21", "T1"), ("invalid", "T1"), ("2026-10-19", "T4"),
            ]:
                with self.subTest(fecha=fecha, turno=turno):
                    response = client.get("/api/consolidado-turno", query_string={
                        "fecha": fecha, "turno": turno,
                    })
                    self.assertEqual(response.status_code, 400)
                    self.assertIn("error", response.json)
            fetch.assert_not_called()

    def test_default_query_and_night_exception_use_closing_date(self):
        with patch("scheduler_service.get_target_now", return_value=datetime(2026, 10, 19, 23)), \
                patch("serve_web.fetch_json", return_value={}), \
                patch("scheduler_service.consultar_ticket_programado", return_value=(0, "0", True)):
            client = serve_web.app.test_client()
            for query in ["", "?fecha=2026-10-20&turno=T1"]:
                with self.subTest(query=query):
                    response = client.get("/api/consolidado-turno" + query)
                    self.assertEqual(response.status_code, 200)
                    consulta = response.json["consulta"]
                    self.assertEqual(consulta["fecha"], "2026-10-20")
                    self.assertEqual(consulta["turno"], "T1")
                    self.assertEqual(consulta["start_dt"], "2026-10-19 22:00:00")
                    self.assertEqual(consulta["end_dt"], "2026-10-20 06:00:00")


if __name__ == "__main__":
    unittest.main()
