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
    LOCAL_ENDPOINT,
    LOCAL_PROVIDER,
    PROVIDER_CONFIGS,
    discover_local_vision_models,
    GeminiCalibrationError,
    analyze_screenshot,
    is_quota_or_credit_error,
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

    def test_strict_confidence_gate_rejects_uncertain_targets(self):
        base = {
            "screen_state": "interact_prompt",
            "summary": "Prompt visible",
            "next_instruction": "Review the visible prompt",
            "regions": [{
                "key": "center", "kind": "dot", "coords": [500, 500],
                "confidence": 0.87, "evidence": "Mostly clear",
            }],
        }
        self.assertEqual(validate_response(base)["proposals"], [])
        base["regions"][0]["confidence"] = 0.90
        self.assertEqual(len(validate_response(base)["proposals"]), 1)

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



    @unittest.skipUnless(__import__("importlib").util.find_spec("PIL") and
                         __import__("importlib").util.find_spec("numpy"),
                         "requires Pillow and NumPy")
    def test_groq_vision_provider_sends_images_and_parses_json(self):
        import numpy as np
        answer = {
            "screen_state": "reel_minigame",
            "summary": "Visible reel track.",
            "next_instruction": "Open the NPC menu next.",
            "regions": [{
                "key": "bar_search", "kind": "box",
                "coords": [35, 380, 965, 950],
                "confidence": 0.96, "evidence": "Full reel track is visible",
            }],
        }
        body = json.dumps({
            "choices": [{"message": {"content": json.dumps(answer)}}]
        }).encode("utf-8")
        fake_response = mock.MagicMock()
        fake_response.__enter__.return_value.read.return_value = body
        frame = np.zeros((480, 800, 3), dtype=np.uint8)
        with mock.patch("urllib.request.urlopen", return_value=fake_response) as opened:
            result = analyze_screenshot(
                frame, "groq-test-key-not-real", WINDOWS / "assets" / "gui",
                provider="Groq", model="qwen/qwen3.6-27b",
            )
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, PROVIDER_CONFIGS["Groq"]["endpoint"])
        self.assertEqual(request.get_header("Authorization"), "Bearer groq-test-key-not-real")
        body_sent = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body_sent["model"], "qwen/qwen3.6-27b")
        self.assertEqual(body_sent["response_format"], {"type": "json_object"})
        contents = body_sent["messages"][0]["content"]
        self.assertEqual(contents[0]["type"], "text")
        images = [part for part in contents if part.get("type") == "image_url"]
        self.assertGreaterEqual(len(images), 1)
        self.assertTrue(images[0]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(result["proposals"][0]["key"], "bar_search")


    @unittest.skipUnless(__import__("importlib").util.find_spec("PIL") and
                         __import__("importlib").util.find_spec("numpy"),
                         "requires Pillow and NumPy")
    def test_existing_local_vision_provider_needs_no_api_key(self):
        import numpy as np
        answer = {
            "screen_state": "reel_minigame",
            "summary": "The reel track is visible.",
            "next_instruction": "Open the next UI state.",
            "regions": [{
                "key": "bar_search", "kind": "box",
                "coords": [35, 380, 965, 950],
                "confidence": 0.96, "evidence": "Full reel track is visible",
            }],
        }
        body = json.dumps({
            "choices": [{"message": {"content": json.dumps(answer)}}]
        }).encode("utf-8")
        fake_response = mock.MagicMock()
        fake_response.__enter__.return_value.read.return_value = body
        frame = np.zeros((480, 800, 3), dtype=np.uint8)
        with mock.patch("urllib.request.urlopen", return_value=fake_response) as opened:
            result = analyze_screenshot(
                frame, "", WINDOWS / "assets" / "gui",
                provider=LOCAL_PROVIDER,
                model="Qwen/Qwen2.5-VL-7B-Instruct",
                local_endpoint=LOCAL_ENDPOINT,
            )
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, LOCAL_ENDPOINT)
        self.assertIsNone(request.get_header("Authorization"))
        request_body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request_body["model"], "Qwen/Qwen2.5-VL-7B-Instruct")
        images = [part for part in request_body["messages"][0]["content"]
                  if part.get("type") == "image_url"]
        self.assertGreaterEqual(len(images), 1)
        self.assertEqual(result["proposals"][0]["key"], "bar_search")

    def test_local_discovery_uses_only_already_running_loopback_vision_servers(self):
        import urllib.error

        listed = {"data": [
            {"id": "Qwen/Qwen2.5-VL-7B-Instruct"},
            {"id": "generic-text-instruct"},
        ]}
        fake_response = mock.MagicMock()
        fake_response.__enter__.return_value.read.return_value = json.dumps(listed).encode("utf-8")

        def fake_open(request, timeout=0.45):
            if request.full_url == "http://127.0.0.1:1234/v1/models":
                return fake_response
            raise urllib.error.URLError("server is not running")

        with mock.patch("urllib.request.urlopen", side_effect=fake_open) as opened:
            models = discover_local_vision_models(timeout=0.01)

        self.assertEqual(len(models), 1)
        self.assertEqual(models[0]["model"], "Qwen/Qwen2.5-VL-7B-Instruct")
        self.assertEqual(models[0]["server"], "LM Studio")
        self.assertEqual(models[0]["endpoint"], LOCAL_ENDPOINT)
        probed = [call.args[0].full_url for call in opened.call_args_list]
        self.assertTrue(all(url.startswith("http://127.0.0.1:") for url in probed))
        self.assertFalse(any("11434" in url or "ollama" in url.casefold() for url in probed))

    def test_quota_failures_are_detected_for_local_fallback(self):
        self.assertTrue(is_quota_or_credit_error(
            GeminiCalibrationError("OpenRouter rate limit or quota is exhausted.")
        ))
        self.assertTrue(is_quota_or_credit_error(
            GeminiCalibrationError("Insufficient credits for this request.")
        ))
        self.assertFalse(is_quota_or_credit_error(
            GeminiCalibrationError("The model does not support vision.")
        ))

if __name__ == "__main__":
    unittest.main()
