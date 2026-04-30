import unittest

from server.realtime_density import (
    build_latest_sequence_rows,
    calculate_density,
    feeding_from_density,
)


class RealtimeDensityTests(unittest.TestCase):
    def test_empty_window_is_insufficient(self):
        summary = calculate_density([], expected_chunks=30)
        self.assertEqual(summary["density_60s"], 0)
        self.assertEqual(summary["completeness_60s"], 0)
        self.assertEqual(summary["fish_chunks_60s"], 0)
        self.assertEqual(summary["received_chunks_60s"], 0)

        feeding = feeding_from_density(summary["density_60s"], summary["completeness_60s"])
        self.assertEqual(feeding["level"], "minimal")
        self.assertEqual(feeding["confidence"], "insufficient")
        self.assertIn("数据不足", feeding["message"])

    def test_density_counts_only_received_chunks(self):
        chunks = [
            {"sequence": 1, "predicted_class": "fish"},
            {"sequence": 2, "predicted_class": "background"},
            {"sequence": 3, "predicted_class": "fish"},
        ]
        summary = calculate_density(chunks, expected_chunks=30)
        self.assertEqual(summary["fish_chunks_60s"], 2)
        self.assertEqual(summary["received_chunks_60s"], 3)
        self.assertAlmostEqual(summary["density_60s"], 0.6667)
        self.assertAlmostEqual(summary["completeness_60s"], 0.1)

    def test_feeding_confidence_tracks_completeness(self):
        high_low_confidence = feeding_from_density(0.2, 0.7)
        self.assertEqual(high_low_confidence["level"], "high")
        self.assertEqual(high_low_confidence["confidence"], "low")

        high_normal = feeding_from_density(0.2, 0.9)
        self.assertEqual(high_normal["level"], "high")
        self.assertEqual(high_normal["amount_kg"], 0.8)
        self.assertEqual(high_normal["confidence"], "normal")

    def test_latest_rows_include_missing_placeholders(self):
        rows = build_latest_sequence_rows(
            [
                {"sequence": 3, "status": "analyzed"},
                {"sequence": 5, "status": "analyzed"},
            ],
            limit=4,
        )
        self.assertEqual([row["sequence"] for row in rows], [2, 3, 4, 5])
        self.assertEqual(rows[0]["status"], "missing")
        self.assertEqual(rows[1]["status"], "analyzed")
        self.assertEqual(rows[2]["status"], "missing")
        self.assertEqual(rows[3]["status"], "analyzed")


if __name__ == "__main__":
    unittest.main()
