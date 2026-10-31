import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import coolix_states as coolix


class CoolixStatesTest(unittest.TestCase):
    def test_against_both_physical_remote_captures(self):
        captures = json.loads((ROOT / "captures/2026-11-01-york-rg94a.json").read_text())["captures"]
        for capture in captures:
            expected = capture["analysis"]
            code = coolix.encode("cool", expected["setpoint_celsius"], "high")
            self.assertEqual(f"0x{code:06X}", expected["state_hex"])
            wire = " ".join(f"{b:02X}" for b in coolix.wire_bytes(code))
            self.assertEqual(wire, expected["wire_frame_hex"][0])

    def test_published_default_and_fan_only_states(self):
        self.assertEqual(coolix.encode("auto", 25, "auto"), 0xB21FC8)
        self.assertEqual(coolix.encode("fan", None, "auto"), 0xB2BFE4)

    def test_observed_remote_modes_fans_and_temperature_sweep(self):
        captures = json.loads((ROOT / "captures/york-remote-characterization.json").read_text())["captures"]
        samples = {c["device_capture_id"]: c for c in captures}
        expected = {1: ("auto", 23, "auto"), 2: ("cool", 23, "high"),
                    3: ("dry", 23, "auto"), 5: ("fan", None, "high"),
                    26: ("heat", 28, "high")}
        expected.update({i: ("cool", 23, fan) for i, fan in
                         zip(range(6, 10), ("auto", "low", "medium", "high"))})
        expected.update({(24 if t == 28 else t - 7): ("cool", t, "high") for t in range(17, 31)})
        for capture_id, state in expected.items():
            analysis = samples[capture_id]["analysis"]
            self.assertTrue(analysis["complete"])
            self.assertTrue(analysis["frames_identical"])
            for frame in analysis["frames"]:
                self.assertTrue(frame["inverse_valid"])
                self.assertEqual(coolix.encode(*state), int(frame["code"], 16))

    def test_evidence_excludes_partial_samples_and_preserves_fan_naming(self):
        index = coolix.capture_index()
        self.assertNotIn("0xB23F5C", index)  # HEAT 23C only had a damaged repeat.
        self.assertIn("0xB23F8C", index)  # HEAT 28C was recaptured cleanly.
        self.assertNotIn(21, [r["capture_id"] for r in index["0xB23F80"]])
        self.assertIn(24, [r["capture_id"] for r in index["0xB23F80"]])
        first_level = coolix.state_record("cool", 23, "auto", index)
        self.assertEqual(first_level["fan_field"], 5)
        self.assertEqual(first_level["user_fan_label_zh"], "微风（用户称呼）")
        self.assertTrue(first_level["manual_fan_adjustable"])
        for mode in ("auto", "dry"):
            locked = coolix.state_record(mode, 23, "auto", index)
            self.assertEqual(locked["fan_field"], 0)
            self.assertFalse(locked["manual_fan_adjustable"])

    def test_catalog_constraints_uniqueness_and_roundtrip(self):
        states = coolix.catalog()["states"]
        self.assertEqual(len(states), 144)
        self.assertEqual(len({s["code"] for s in states}), 144)
        for state in states:
            actual = coolix.decode(int(state["code"], 16))
            self.assertEqual(actual, {k: state[k] for k in actual})
            self.assertEqual(state["temperature_celsius"] is None, state["mode"] == "fan")
            if state["mode"] in ("auto", "dry"):
                self.assertEqual(state["fan"], "auto")

    def test_rejects_invalid_or_misleading_combinations(self):
        for mode, temp, fan in [("cool", 16, "auto"), ("cool", 31, "auto"),
                                ("auto", 25, "high"), ("dry", 25, "low"),
                                ("fan", 25, "high"), ("heat", None, "high"),
                                ("cool", True, "high")]:
            with self.assertRaises(ValueError):
                coolix.encode(mode, temp, fan)
        for value in (0xB27BE0, 0xB5F5A5, 0xFFFFFF, -1, 0x1B23FC0):
            with self.assertRaises(ValueError):
                coolix.decode(value)


if __name__ == "__main__":
    unittest.main()
