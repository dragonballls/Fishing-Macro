from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

WINDOWS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WINDOWS))

from bloxfish.ai_calibration import (  # noqa: E402
    API_URL,
    GeminiCalibrationError,
    analyze_screenshot,
    screen_changed,
    validate_response,
)


class ConfigPreviewRollbackTests(unittest.TestCase):
    def test_restore_returns_all_ai_touched_fields_to_the_original_values(self):
        from bloxfish.config import Config
        from bloxfish.ai_calibration import capture_config_values, restore_config_values

        cfg = Config()
        cfg.detection.bar_search_left = 0.11
        cfg.shop.center = (0.44, 0.55)
        baseline = capture_config_values(
            cfg, ["detection.bar_search_left", "shop.center"]
        )
        cfg.detection.bar_search_left = 0.77
        cfg.shop.center = (0.88, 0.99)

        restore_config_values(cfg, baseline)
        self.assertEqual(cfg.detection.bar_search_left, 0.11)
        self.assertEqual(cfg.shop.center, (0.44, 0.55))

    def test_multiple_ai_proposals_keep_the_earliest_baseline(self):
        from bloxfish.config import Config
        from bloxfish.ai_calibration import capture_config_values, restore_config_values

        cfg = Config()
        cfg.detection.bar_search_left = 0.13
        baseline = capture_config_values(cfg, ["detection.bar_search_left"])
        cfg.detection.bar_search_left = 0.52
        baseline = capture_config_values(cfg, ["detection.bar_search_left"], baseline)
        cfg.detection.bar_search_left = 0.81

        restore_config_values(cfg, baseline)
        self.assertEqual(cfg.detection.bar_search_left, 0.13)


class GeminiCoordinateValidationTests(unittest.TestCase):
    def test_accepts_high_confidence_visible_reel_box_and_converts_fractions(self):
        result = validate_response({
            "screen_state": "reel_minigame",
            "summary": "Reel UI visible",
            "next_instruction": "Show the next screen",
            "regions": [{
                "key": "bar_search",
                "kind": "box",
                "coords": [40, 390, 960, 950],
                "confidence": 0.94,
                "evidence": "Full reel track is visible",
            }],
        })
        self.assertEqual(len(result["proposals"]), 1)
        self.assertEqual(result["proposals"][0]["key"], "bar_search")
        self.assertEqual(result["proposals"][0]["coords"], [0.04, 0.39, 0.96, 0.95])

    def test_rejects_low_confidence_wrong_state_and_wrong_kind(self):
        result = validate_response({
            "screen_state": "reel_minigame",
            "regions": [
                {"key": "bar_search", "kind": "box", "coords": [20, 400, 980, 960],
                 "confidence": 0.5, "evidence": "unclear"},
                {"key": "center", "kind": "dot", "coords": [500, 500],
                 "confidence": 0.99, "evidence": "not visible in reel state"},
                {"key": "bite", "kind": "dot", "coords": [500, 500],
                 "confidence": 0.99, "evidence": "wrong element kind"},
            ],
        })
        self.assertEqual(result["proposals"], [])

    def test_rejects_bad_dimensions_nonfinite_and_out_of_range_coordinates(self):
        result = validate_response({
            "screen_state": "npc_root_menu",
            "regions": [
                {"key": "menu", "kind": "box", "coords": [500, 500, 300, 900],
                 "confidence": 0.99, "evidence": "inverted"},
                {"key": "menu", "kind": "box", "coords": [30, 20, 50, 60],
                 "confidence": 0.99, "evidence": "too small"},
                {"key": "center", "kind": "dot", "coords": [1001, 450],
                 "confidence": 0.99, "evidence": "outside image"},
            ],
        })
        self.assertEqual(result["proposals"], [])

    def test_deduplicates_each_control_and_bounds_text(self):
        result = validate_response({
            "screen_state": "interact_prompt",
            "summary": "x" * 500,
            "next_instruction": "y" * 500,
            "regions": [
                {"key": "center", "kind": "dot", "coords": [500, 520],
                 "confidence": 0.9, "evidence": "first"},
                {"key": "center", "kind": "dot", "coords": [505, 520],
                 "confidence": 1.0, "evidence": "duplicate"},
            ],
        })
        self.assertEqual(len(result["proposals"]), 1)
        self.assertLessEqual(len(result["summary"]), 300)
        self.assertLessEqual(len(result["next_instruction"]), 300)

    @unittest.skipUnless(__import__("importlib").util.find_spec("numpy") and
                         __import__("importlib").util.find_spec("cv2"),
                         "requires OpenCV and NumPy")
    def test_scene_change_detector_ignores_identical_frames_and_detects_change(self):
        import numpy as np
        first = np.zeros((120, 200, 3), dtype=np.uint8)
        second = first.copy()
        third = first.copy()
        third[20:100, 30:175, :] = 255
        self.assertFalse(screen_changed(first, second))
        self.assertTrue(screen_changed(first, third))

    @unittest.skipUnless(__import__("importlib").util.find_spec("PIL") and
                         __import__("importlib").util.find_spec("numpy"),
                         "requires Pillow and NumPy")
    def test_gemini_request_uses_key_header_and_returns_validated_proposal(self):
        import numpy as np
        answer = {
            "screen_state": "reel_minigame",
            "summary": "The reel track is visible.",
            "next_instruction": "Open the NPC menu next.",
            "regions": [{
                "key": "bar_search", "kind": "box",
                "coords": [35, 380, 965, 950],
                "confidence": 0.96, "evidence": "Full bar and strip are visible",
            }],
        }
        body = json.dumps({
            "candidates": [{"content": {"parts": [{"text": json.dumps(answer)}]}}]
        }).encode("utf-8")
        fake_response = mock.MagicMock()
        fake_response.__enter__.return_value.read.return_value = body
        fake_response.__enter__.return_value.__getitem__.return_value = "200"
        frame = np.zeros((480, 800, 3), dtype=np.uint8)
        assets = WINDOWS / "assets" / "gui"
        with mock.patch("urllib.request.urlopen", return_value=fake_response) as opened:
            result = analyze_screenshot(frame, "test-not-a-real-key", assets)
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, API_URL)
        self.assertEqual(request.get_header("X-goog-api-key"), "test-not-a-real-key")
        request_body = json.loads(request.data.decode("utf-8"))
        self.assertNotIn("temperature", request_body["generationConfig"])
        parts = request_body["contents"][0]["parts"]
        self.assertTrue(parts[1]["inline_data"]["data"])
        self.assertTrue(parts[2]["inline_data"]["data"])
        self.assertEqual(result["proposals"][0]["key"], "bar_search")
        self.assertGreaterEqual(result["proposals"][0]["confidence"], 0.78)


if __name__ == "__main__":
    unittest.main()
