import json
import tempfile
import unittest
from pathlib import Path

from fishfight.settings import (
    DEFAULT_CONFIG,
    load_config,
    normalize_config,
    save_config,
)


class SettingsTests(unittest.TestCase):
    def test_defaults_are_disarmed_and_dry_run(self):
        config, warnings = normalize_config({})
        self.assertTrue(config["dry_run"])
        self.assertIsNone(config["roi"])
        self.assertEqual(config["poll_hz"], 90)
        self.assertEqual(warnings, [])

    def test_mouse_action_requires_a_valid_calibrated_target(self):
        config, warnings = normalize_config({"input_mode": "mouse_click"})
        self.assertEqual(config["input_mode"], "spacebar")
        self.assertTrue(any("without a calibrated target" in warning for warning in warnings))

        point = {"x": -1920, "y": 520}
        config, warnings = normalize_config({"input_mode": "mouse_click", "action_point": point})
        self.assertEqual(config["input_mode"], "mouse_click")
        self.assertEqual(config["action_point"], point)
        self.assertEqual(warnings, [])

    def test_invalid_mouse_target_is_discarded_and_requires_recalibration(self):
        config, warnings = normalize_config({
            "input_mode": "mouse_click",
            "action_point": {"x": "bad", "y": 50},
        })
        self.assertIsNone(config["action_point"])
        self.assertEqual(config["input_mode"], "spacebar")
        self.assertTrue(any("action_point is malformed" in warning for warning in warnings))

    def test_invalid_dry_run_never_enables_live_input(self):
        config, warnings = normalize_config({"dry_run": "false"})
        self.assertIs(config["dry_run"], True)
        self.assertTrue(any("dry_run" in warning for warning in warnings))

    def test_invalid_roi_requires_recalibration(self):
        config, warnings = normalize_config({
            "roi": {"left": 10, "top": 10, "width": -1, "height": 500},
            "dry_run": False,
        })
        self.assertIsNone(config["roi"])
        self.assertIs(config["dry_run"], True)
        self.assertTrue(any("ROI" in warning for warning in warnings))

    def test_valid_negative_monitor_origin_is_preserved(self):
        roi = {"left": -1920, "top": 0, "width": 1920, "height": 1080}
        config, warnings = normalize_config({"roi": roi})
        self.assertEqual(config["roi"], roi)
        self.assertEqual(warnings, [])

    def test_numeric_values_are_bounded(self):
        config, warnings = normalize_config({
            "poll_hz": 999,
            "prediction_horizon_s": 90,
            "press_lead_s": 0.5,
            "zone_row_fraction": 5,
        })
        self.assertEqual(config["poll_hz"], 180)
        self.assertEqual(config["prediction_horizon_s"], 2.0)
        self.assertEqual(config["press_lead_s"], 0.045)
        self.assertEqual(config["zone_row_fraction"], 1.0)
        self.assertGreaterEqual(len(warnings), 4)

    def test_non_finite_or_wrong_type_values_use_defaults(self):
        config, warnings = normalize_config({
            "prediction_horizon_s": float("nan"),
            "poll_hz": "90",
            "green_h_min": 150,
            "green_h_max": 30,
        })
        self.assertEqual(config["prediction_horizon_s"], DEFAULT_CONFIG["prediction_horizon_s"])
        self.assertEqual(config["poll_hz"], DEFAULT_CONFIG["poll_hz"])
        self.assertEqual(config["green_h_min"], DEFAULT_CONFIG["green_h_min"])
        self.assertEqual(config["green_h_max"], DEFAULT_CONFIG["green_h_max"])
        self.assertTrue(warnings)

    def test_missing_file_creates_atomic_default_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            config = load_config(path)
            self.assertTrue(path.exists())
            self.assertTrue(config["dry_run"])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), config)
            self.assertFalse(path.with_name("config.json.tmp").exists())

    def test_malformed_json_falls_back_without_crashing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text("{not json", encoding="utf-8")
            config = load_config(path)
            self.assertTrue(config["dry_run"])
            self.assertIsNone(config["roi"])

    def test_save_config_round_trips(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            config = dict(DEFAULT_CONFIG)
            save_config(config, path)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), config)
            self.assertFalse(path.with_name("config.json.tmp").exists())

    def test_unknown_keys_are_ignored(self):
        config, warnings = normalize_config({"unexpected": float("nan")})
        self.assertNotIn("unexpected", config)
        self.assertTrue(any("unknown setting" in warning for warning in warnings))

    def test_invalid_utf8_falls_back_without_crashing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_bytes(b"\xff\xfe\xfa")
            config = load_config(path)
            self.assertTrue(config["dry_run"])
            self.assertIsNone(config["roi"])


if __name__ == "__main__":
    unittest.main()
