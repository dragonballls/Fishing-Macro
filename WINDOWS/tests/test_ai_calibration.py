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
    PROVIDER_CONFIGS,
    PROVIDERS,
    notice_x_position,
    GeminiCalibrationError,
    ScreenVideoRecorder,
    analyze_screenshot,
    analyze_screenshot_with_fallback,
    is_quota_or_credit_error,
    screen_changed,
    should_replace_proposal,
    validate_response,
)


class ProviderConfigurationTests(unittest.TestCase):
    def test_only_supported_cloud_vision_providers_are_offered(self):
        self.assertEqual(
            set(PROVIDERS), {"Gemini", "OpenRouter", "Groq", "OpenAI", "Mistral"}
        )
        self.assertNotIn("Local LLM (Ollama)", PROVIDER_CONFIGS)

    def test_default_models_use_documented_image_capable_endpoints(self):
        expected = {
            "Gemini": "gemini-3.8-flash",
            "OpenRouter": "openrouter/free",
            "Groq": "qwen/qwen3.8-27b",
            "OpenAI": "gpt-4.1-mini",
            "Mistral": "ministral-14b-2512",
        }
        self.assertEqual(
            {name: PROVIDER_CONFIGS[name]["model"] for name in expected}, expected
        )

    def test_notice_position_keeps_right_edge_visible_with_safe_inset(self):
        self.assertEqual(notice_x_position(1920, 380, right_inset=48), 1492)
        x = notice_x_position(400, 320, right_inset=48)
        self.assertEqual(x, 32)
        self.assertEqual(400 - (x + 320), 48)


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


class ProposalReplacementPolicyTests(unittest.TestCase):
    def test_better_confidence_replaces_candidate_during_normal_capture(self):
        self.assertTrue(should_replace_proposal(
            {"confidence": 0.72}, {"confidence": 0.91}))
        self.assertFalse(should_replace_proposal(
            {"confidence": 0.91}, {"confidence": 0.72}))
        self.assertFalse(should_replace_proposal(
            {"confidence": 0.91}, {"confidence": 0.91}))

    def test_explicit_retake_can_replace_candidate_even_if_confidence_is_lower(self):
        self.assertTrue(should_replace_proposal(
            {"confidence": 0.97}, {"confidence": 0.70}, force_retake=True))

    def test_first_candidate_is_accepted(self):
        self.assertTrue(should_replace_proposal(None, {"confidence": 0.70}))


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

    def test_review_floor_rejects_very_uncertain_targets_but_shows_candidates(self):
        base = {
            "screen_state": "interact_prompt",
            "summary": "Prompt visible",
            "next_instruction": "Review the visible prompt",
            "regions": [{
                "key": "center", "kind": "dot", "coords": [500, 500],
                "confidence": 0.67, "evidence": "Mostly clear",
            }],
        }
        self.assertEqual(validate_response(base)["proposals"], [])
        base["regions"][0]["confidence"] = 0.70
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

    @unittest.skipUnless(__import__("importlib").util.find_spec("numpy") and
                         __import__("importlib").util.find_spec("cv2"),
                         "requires OpenCV and NumPy")
    def test_scene_change_detects_smaller_high_contrast_ui_transition(self):
        import numpy as np
        first = np.zeros((120, 200, 3), dtype=np.uint8)
        second = first.copy()
        # A localized prompt can be only about 3% of the visible client.
        second[20:34, 40:90, :] = 255
        self.assertTrue(screen_changed(first, second))

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
                provider="Groq",
            )
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, PROVIDER_CONFIGS["Groq"]["endpoint"])
        self.assertEqual(request.get_header("Authorization"), "Bearer groq-test-key-not-real")
        body_sent = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body_sent["model"], PROVIDER_CONFIGS["Groq"]["model"])
        self.assertEqual(body_sent["response_format"], {"type": "json_object"})
        contents = body_sent["messages"][0]["content"]
        self.assertEqual(contents[0]["type"], "text")
        images = [part for part in contents if part.get("type") == "image_url"]
        self.assertGreaterEqual(len(images), 1)
        self.assertTrue(images[0]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(result["proposals"][0]["key"], "bar_search")


    def test_quota_failures_are_detected(self):
        self.assertTrue(is_quota_or_credit_error(
            GeminiCalibrationError("OpenRouter rate limit or quota is exhausted.")
        ))
        self.assertTrue(is_quota_or_credit_error(
            GeminiCalibrationError("Insufficient credits for this request.")
        ))
        self.assertFalse(is_quota_or_credit_error(
            GeminiCalibrationError("The model does not support vision.")
        ))



class ProviderFallbackTests(unittest.TestCase):
    def test_quota_error_uses_only_a_saved_openrouter_free_route(self):
        successful = {
            "screen_state": "reel_minigame",
            "summary": "Reel visible",
            "next_instruction": "Review",
            "proposals": [],
        }
        with mock.patch(
            "bloxfish.ai_calibration.analyze_screenshot",
            side_effect=[
                GeminiCalibrationError("Gemini rate limit or quota is exhausted."),
                successful,
            ],
        ) as analyze, mock.patch(
            "bloxfish.ai_calibration.get_saved_api_key",
            return_value="saved-openrouter-test-key",
        ) as key_lookup:
            result, provider, model, api_key = analyze_screenshot_with_fallback(
                object(), "primary-test-key", WINDOWS / "assets" / "gui",
                provider="Gemini",
            )
        self.assertEqual(result, successful)
        self.assertEqual(provider, "OpenRouter")
        self.assertEqual(model, "openrouter/free")
        self.assertEqual(api_key, "saved-openrouter-test-key")
        key_lookup.assert_called_once_with("OpenRouter")
        self.assertEqual(analyze.call_count, 2)
        self.assertEqual(analyze.call_args.kwargs["provider"], "OpenRouter")
        self.assertEqual(analyze.call_args.kwargs["model"], "openrouter/free")

    def test_quota_error_without_saved_openrouter_key_is_actionable(self):
        with mock.patch(
            "bloxfish.ai_calibration.analyze_screenshot",
            side_effect=GeminiCalibrationError("Gemini quota exceeded."),
        ) as analyze, mock.patch(
            "bloxfish.ai_calibration.get_saved_api_key",
            return_value=None,
        ):
            with self.assertRaisesRegex(
                GeminiCalibrationError, "needs a saved OpenRouter API key"
            ):
                analyze_screenshot_with_fallback(
                    object(), "primary-test-key", WINDOWS / "assets" / "gui",
                    provider="Gemini",
                )
        analyze.assert_called_once()

    def test_non_quota_provider_errors_do_not_trigger_fallback(self):
        with mock.patch(
            "bloxfish.ai_calibration.analyze_screenshot",
            side_effect=GeminiCalibrationError("The model does not support vision."),
        ) as analyze, mock.patch(
            "bloxfish.ai_calibration.get_saved_api_key"
        ) as key_lookup:
            with self.assertRaisesRegex(GeminiCalibrationError, "does not support vision"):
                analyze_screenshot_with_fallback(
                    object(), "primary-test-key", WINDOWS / "assets" / "gui",
                    provider="Gemini",
                )
        analyze.assert_called_once()
        key_lookup.assert_not_called()

    def test_openrouter_quota_does_not_retry_or_use_paid_provider(self):
        with mock.patch(
            "bloxfish.ai_calibration.analyze_screenshot",
            side_effect=GeminiCalibrationError("OpenRouter quota exhausted."),
        ) as analyze, mock.patch(
            "bloxfish.ai_calibration.get_saved_api_key"
        ) as key_lookup:
            with self.assertRaisesRegex(GeminiCalibrationError, "No paid provider"):
                analyze_screenshot_with_fallback(
                    object(), "openrouter-test-key", WINDOWS / "assets" / "gui",
                    provider="OpenRouter",
                )
        analyze.assert_called_once()
        key_lookup.assert_not_called()


class LocalVideoRecorderTests(unittest.TestCase):
    @unittest.skipUnless(
        __import__("importlib").util.find_spec("numpy") and
        __import__("importlib").util.find_spec("cv2"),
        "requires OpenCV and NumPy",
    )
    def test_recorder_writes_local_video_and_releases_writer(self):
        import tempfile
        from pathlib import Path
        import numpy as np

        created = {}

        class FakeWriter:
            def __init__(self, path):
                self.path = Path(path)
                self.path.write_bytes(b"video-test")
                self.write_count = 0
                self.released = False

            def isOpened(self):
                return True

            def write(self, frame):
                self.write_count += 1

            def release(self):
                self.released = True

        def writer_factory(path, fourcc, fps, size):
            created["writer"] = FakeWriter(path)
            created["fps"] = fps
            created["size"] = size
            return created["writer"]

        frame = np.zeros((90, 160, 3), dtype=np.uint8)
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "cv2.VideoWriter", side_effect=writer_factory
        ):
            recorder = ScreenVideoRecorder(output_dir=tmp, fps=5.0)
            path = recorder.start(frame)
            recorder.write(frame)
            finalized = recorder.close()
            file_exists_before_cleanup = Path(path).is_file()
            path_parent = Path(path).parent
            path_suffix = Path(path).suffix

        self.assertEqual(finalized, path)
        self.assertTrue(file_exists_before_cleanup)
        self.assertEqual(path_parent, Path(tmp))
        self.assertEqual(path_suffix, ".mp4")
        self.assertEqual(created["fps"], 5.0)
        self.assertEqual(created["size"], (160, 90))
        self.assertGreaterEqual(created["writer"].write_count, 2)
        self.assertTrue(created["writer"].released)
        self.assertIsNone(recorder._writer)

if __name__ == "__main__":
    unittest.main()
