import unittest

try:
    from runtime.context_stopgap import (
        compaction_band,
        compaction_band_for_ratio,
        summarize_tool_payload,
        truncate_tool_output,
    )
except ImportError:
    compaction_band = None
    compaction_band_for_ratio = None
    summarize_tool_payload = None
    truncate_tool_output = None

try:
    from runtime.discovery_extract import extract_discovery_summary
except ImportError:
    extract_discovery_summary = None


class ContextStopgapTests(unittest.TestCase):
    def test_truncate_tool_output_keeps_head_and_tail_windows(self) -> None:
        self.assertIsNotNone(truncate_tool_output, "truncate_tool_output must be implemented")

        text = "\n".join(f"line-{idx:02d}" for idx in range(1, 11))
        result = truncate_tool_output(
            text,
            max_lines=6,
            max_bytes=1024,
            head_lines=2,
            tail_lines=2,
        )

        self.assertTrue(result["truncated"])
        self.assertEqual(result["dropped_lines"], 6)
        self.assertGreater(result["dropped_bytes"], 0)
        self.assertIn("line-01\nline-02", result["text"])
        self.assertIn("line-09\nline-10", result["text"])
        self.assertIn("[truncated 6 lines", result["text"])
        self.assertNotIn("line-05", result["text"])

    def test_truncate_tool_output_applies_byte_ceiling(self) -> None:
        self.assertIsNotNone(truncate_tool_output, "truncate_tool_output must be implemented")

        text = "\n".join(
            [
                "head",
                "x" * 120,
                "y" * 120,
                "tail",
            ]
        )
        result = truncate_tool_output(
            text,
            max_lines=20,
            max_bytes=80,
            head_lines=1,
            tail_lines=1,
        )

        self.assertTrue(result["truncated"])
        self.assertEqual(result["dropped_lines"], 2)
        self.assertIn("head", result["text"])
        self.assertIn("tail", result["text"])
        self.assertLessEqual(len(result["text"].encode("utf-8")), 80)

    def test_summarize_tool_payload_marks_large_read_result_as_summarized(self) -> None:
        self.assertIsNotNone(summarize_tool_payload, "summarize_tool_payload must be implemented")

        text = "\n".join(f"chunk-{idx:02d}" for idx in range(1, 13))
        result = summarize_tool_payload(
            "read",
            text,
            max_lines=6,
            max_bytes=1024,
            head_lines=2,
            tail_lines=2,
        )

        self.assertEqual(result["tool_name"], "read")
        self.assertTrue(result["summarized"])
        self.assertTrue(result["truncation"]["truncated"])
        self.assertIn("已摘要", result["summary"])
        self.assertIn("chunk-01", result["text"])
        self.assertIn("chunk-12", result["text"])
        self.assertNotIn("chunk-06", result["text"])

    def test_extract_discovery_summary_keeps_only_required_fields(self) -> None:
        self.assertIsNotNone(extract_discovery_summary, "extract_discovery_summary must be implemented")

        discovery_doc = """# Discovery

## Design Read
- Bold commerce landing page
- Heavy contrast, oversized typography

## DESIGN_VARIANCE
hero-heavy

## MOTION_INTENSITY
medium

## VISUAL_DENSITY
airy

## Device Adaptation
- Mobile: stack hero content first
- Tablet: keep 2-column feature grid

## Notes
- This section should not be included.
"""
        result = extract_discovery_summary(discovery_doc)

        self.assertEqual(
            set(result.keys()),
            {
                "design_read",
                "design_variance",
                "motion_intensity",
                "visual_density",
                "device_adaptation",
            },
        )
        self.assertEqual(
            result["design_read"],
            [
                "Bold commerce landing page",
                "Heavy contrast, oversized typography",
            ],
        )
        self.assertEqual(result["design_variance"], "hero-heavy")
        self.assertEqual(result["motion_intensity"], "medium")
        self.assertEqual(result["visual_density"], "airy")
        self.assertEqual(
            result["device_adaptation"],
            [
                "Mobile: stack hero content first",
                "Tablet: keep 2-column feature grid",
            ],
        )

    def test_compaction_band_uses_expected_thresholds(self) -> None:
        self.assertIsNotNone(compaction_band, "compaction_band must be implemented")

        self.assertEqual(compaction_band(119999), "ok")
        self.assertEqual(compaction_band(120000), "warn")
        self.assertEqual(compaction_band(139999), "warn")
        self.assertEqual(compaction_band(140000), "compact")
        self.assertEqual(compaction_band(159999), "compact")
        self.assertEqual(compaction_band(160000), "hard-stop")

    def test_compaction_band_for_ratio_uses_expected_thresholds(self) -> None:
        self.assertIsNotNone(compaction_band_for_ratio, "compaction_band_for_ratio must be implemented")

        self.assertEqual(compaction_band_for_ratio(0.0), "ok")
        self.assertEqual(compaction_band_for_ratio(0.7999), "ok")
        self.assertEqual(compaction_band_for_ratio(0.80), "warn")
        self.assertEqual(compaction_band_for_ratio(0.8499), "warn")
        self.assertEqual(compaction_band_for_ratio(0.85), "compact")
        self.assertEqual(compaction_band_for_ratio(0.9199), "compact")
        self.assertEqual(compaction_band_for_ratio(0.92), "force-compact")

    def test_compaction_band_for_ratio_saturates_slight_overshoot_instead_of_treating_it_as_percent(self) -> None:
        self.assertIsNotNone(compaction_band_for_ratio, "compaction_band_for_ratio must be implemented")

        self.assertEqual(compaction_band_for_ratio(1.01), "force-compact")
        self.assertEqual(compaction_band_for_ratio(1.2), "force-compact")

    def test_compaction_band_for_ratio_keeps_supporting_percent_style_input(self) -> None:
        self.assertIsNotNone(compaction_band_for_ratio, "compaction_band_for_ratio must be implemented")

        self.assertEqual(compaction_band_for_ratio(79), "ok")
        self.assertEqual(compaction_band_for_ratio(80), "warn")
        self.assertEqual(compaction_band_for_ratio(85), "compact")
        self.assertEqual(compaction_band_for_ratio(92), "force-compact")


if __name__ == "__main__":
    unittest.main()
