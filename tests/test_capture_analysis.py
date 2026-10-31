import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from analyze_capture_log import analyze_raw, parse_log


class CaptureAnalysisTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = json.loads((ROOT / "captures/2026-11-01-york-rg94a.json").read_text())["captures"][1]["raw_us"]

    def test_real_complete_two_frame_packet(self):
        result = analyze_raw(self.raw)
        self.assertTrue(result["complete"])
        self.assertTrue(result["frames_identical"])
        self.assertEqual(result["frames"][0]["code"], "0xB23FC0")

    def test_truncated_repeat_preserves_evidence_without_claiming_complete(self):
        result = analyze_raw(self.raw[:159])
        self.assertFalse(result["complete"])
        self.assertIsNone(result["frames_identical"])
        self.assertEqual(len(result["frames"]), 1)

    def test_corrupt_complement_not_promoted_to_normal_state(self):
        raw = copy.copy(self.raw)
        raw[19] = 550 if raw[19] > 1000 else 1600
        result = analyze_raw(raw)
        self.assertFalse(result["frames"][0]["inverse_valid"])
        self.assertNotIn("normal_state", result["frames"][0])

    def test_declared_count_mismatch_is_rejected(self):
        text = "[2026-11-01 01:00:00] BEGIN_CAPTURE\nCOUNT=3\nRAW_US=500,500,500,500,500\nEND_CAPTURE"
        with self.assertRaises(ValueError):
            parse_log(text)


if __name__ == "__main__":
    unittest.main()
