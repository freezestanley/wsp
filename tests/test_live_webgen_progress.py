import importlib.util
import io
import unittest
from pathlib import Path

from runtime.live_watch import WatchState, build_broadcast_batch


def load_live_webgen_progress_module():
    module_path = Path(__file__).resolve().parent.parent / "runtime" / "live-webgen-progress.py"
    spec = importlib.util.spec_from_file_location("live_webgen_progress_script", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load runtime/live-webgen-progress.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LiveWebgenProgressTests(unittest.TestCase):
    def test_context_usage_ratio_none_is_true_noop_even_with_ack_like_items(self) -> None:
        module = load_live_webgen_progress_module()
        self.assertTrue(
            hasattr(module, "evaluate_silent_context_nudge_cycle"),
            "evaluate_silent_context_nudge_cycle must be implemented",
        )

        state = WatchState(
            watch_id="watch-webgen-demo",
            target_session_key="agent:webgen:proj-demo",
            last_context_band="compact",
            last_context_nudge_at=40.0,
            awaiting_context_ack=True,
        )

        action, updated = module.evaluate_silent_context_nudge_cycle(
            state,
            items=[{"summary": "✅ 已执行 /compact，继续当前任务"}],
            now=100.0,
            context_usage_ratio=None,
        )

        self.assertIsNone(action)
        self.assertEqual(updated, state)

    def test_negative_or_zero_cooldown_is_sanitized_to_safe_minimum(self) -> None:
        module = load_live_webgen_progress_module()
        self.assertTrue(
            hasattr(module, "sanitize_context_nudge_cooldown_seconds"),
            "sanitize_context_nudge_cooldown_seconds must be implemented",
        )

        self.assertEqual(module.sanitize_context_nudge_cooldown_seconds(-5.0), 1.0)
        self.assertEqual(module.sanitize_context_nudge_cooldown_seconds(0.0), 1.0)
        self.assertEqual(module.sanitize_context_nudge_cooldown_seconds(2.5), 2.5)

    def test_context_usage_ratio_is_normalized_in_module_path(self) -> None:
        module = load_live_webgen_progress_module()
        self.assertTrue(
            hasattr(module, "normalize_context_usage_ratio"),
            "normalize_context_usage_ratio must be implemented",
        )

        self.assertAlmostEqual(module.normalize_context_usage_ratio(0.82), 0.82)
        self.assertAlmostEqual(module.normalize_context_usage_ratio(82.0), 0.82)
        with self.assertRaises(ValueError):
            module.normalize_context_usage_ratio(1.2)

    def test_silent_context_nudge_cycle_updates_state_without_visible_batch(self) -> None:
        module = load_live_webgen_progress_module()
        self.assertTrue(
            hasattr(module, "evaluate_silent_context_nudge_cycle"),
            "evaluate_silent_context_nudge_cycle must be implemented",
        )

        state = WatchState(
            watch_id="watch-webgen-demo",
            target_session_key="agent:webgen:proj-demo",
        )

        action, updated = module.evaluate_silent_context_nudge_cycle(
            state,
            items=[],
            now=100.0,
            context_usage_ratio=0.82,
        )
        batch, post_batch = build_broadcast_batch(
            updated,
            [],
            now=100.0,
            max_items=3,
            min_idle_polls=3,
            min_heartbeat_interval_seconds=60.0,
        )

        self.assertIsNotNone(action)
        assert action is not None
        self.assertEqual(action["kind"], "context_nudge")
        self.assertEqual(action["delivery"], "hidden")
        self.assertEqual(action["band"], "warn")
        self.assertEqual(updated.last_context_band, "warn")
        self.assertEqual(updated.last_context_nudge_at, 100.0)
        self.assertTrue(updated.awaiting_context_ack)
        self.assertEqual(batch, [])
        self.assertTrue(post_batch.awaiting_context_ack)

    def test_render_batch_emits_nothing_for_empty_batch(self) -> None:
        module = load_live_webgen_progress_module()
        self.assertTrue(
            hasattr(module, "emit_batch"),
            "emit_batch must be implemented",
        )

        output = io.StringIO()
        module.emit_batch([], jsonl=False, stream=output)

        self.assertEqual(output.getvalue(), "")

    def test_missing_context_usage_ratio_leaves_state_unchanged(self) -> None:
        module = load_live_webgen_progress_module()
        self.assertTrue(
            hasattr(module, "evaluate_silent_context_nudge_cycle"),
            "evaluate_silent_context_nudge_cycle must be implemented",
        )

        state = WatchState(
            watch_id="watch-webgen-demo",
            target_session_key="agent:webgen:proj-demo",
            last_context_band="warn",
            last_context_nudge_at=40.0,
            awaiting_context_ack=True,
        )

        action, updated = module.evaluate_silent_context_nudge_cycle(
            state,
            items=[],
            now=100.0,
            context_usage_ratio=None,
        )

        self.assertIsNone(action)
        self.assertEqual(updated, state)

    def test_repeated_cycle_inside_cooldown_does_not_re_nudge(self) -> None:
        module = load_live_webgen_progress_module()
        self.assertTrue(
            hasattr(module, "evaluate_silent_context_nudge_cycle"),
            "evaluate_silent_context_nudge_cycle must be implemented",
        )

        state = WatchState(
            watch_id="watch-webgen-demo",
            target_session_key="agent:webgen:proj-demo",
        )

        first_action, warned = module.evaluate_silent_context_nudge_cycle(
            state,
            items=[],
            now=100.0,
            context_usage_ratio=82.0,
            cooldown_seconds=30.0,
        )
        second_action, repeated = module.evaluate_silent_context_nudge_cycle(
            warned,
            items=[],
            now=110.0,
            context_usage_ratio=0.82,
            cooldown_seconds=30.0,
        )

        self.assertIsNotNone(first_action)
        self.assertIsNone(second_action)
        self.assertEqual(repeated.last_context_band, "warn")
        self.assertEqual(repeated.last_context_nudge_at, 100.0)
        self.assertTrue(repeated.awaiting_context_ack)


if __name__ == "__main__":
    unittest.main()
