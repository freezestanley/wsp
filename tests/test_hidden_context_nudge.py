import unittest

from runtime.live_watch import WatchState, build_broadcast_batch

try:
    from runtime.context_nudge import (
        build_hidden_context_nudge_message,
        clear_context_ack,
        maybe_plan_hidden_context_nudge,
    )
except ImportError:
    build_hidden_context_nudge_message = None
    clear_context_ack = None
    maybe_plan_hidden_context_nudge = None


class HiddenContextNudgeTests(unittest.TestCase):
    def test_hidden_nudge_message_is_short_and_stable(self) -> None:
        self.assertIsNotNone(
            build_hidden_context_nudge_message,
            "build_hidden_context_nudge_message must be implemented",
        )

        self.assertEqual(
            build_hidden_context_nudge_message("warn"),
            "检查 context；>=80% 先/compact，再继续。",
        )
        self.assertEqual(
            build_hidden_context_nudge_message("compact"),
            "检查 context；>=85% 先/compact，再继续。",
        )
        self.assertEqual(
            build_hidden_context_nudge_message("force-compact"),
            "检查 context；>=92% 立刻/compact，再继续。",
        )
        self.assertLessEqual(len(build_hidden_context_nudge_message("warn")), 32)
        self.assertLessEqual(len(build_hidden_context_nudge_message("compact")), 32)
        self.assertLessEqual(len(build_hidden_context_nudge_message("force-compact")), 32)

    def test_hidden_nudge_message_has_short_stable_fallback(self) -> None:
        self.assertIsNotNone(
            build_hidden_context_nudge_message,
            "build_hidden_context_nudge_message must be implemented",
        )

        message = build_hidden_context_nudge_message("unexpected")

        self.assertEqual(
            message,
            "检查 context；必要时先/compact，再继续。",
        )
        self.assertLessEqual(len(message), 32)

    def test_ok_to_warn_triggers_single_hidden_nudge(self) -> None:
        self.assertIsNotNone(maybe_plan_hidden_context_nudge, "maybe_plan_hidden_context_nudge must be implemented")
        self.assertIn("last_context_band", WatchState.__dataclass_fields__)
        self.assertIn("last_context_nudge_at", WatchState.__dataclass_fields__)
        self.assertIn("awaiting_context_ack", WatchState.__dataclass_fields__)

        state = WatchState(
            watch_id="watch-ctx-1",
            target_session_key="agent:webgen:proj-demo",
        )

        action, updated = maybe_plan_hidden_context_nudge(
            state,
            context_band="warn",
            now=100.0,
            cooldown_seconds=300.0,
        )

        self.assertIsNotNone(action)
        assert action is not None
        self.assertEqual(action["kind"], "context_nudge")
        self.assertEqual(action["delivery"], "hidden")
        self.assertEqual(action["band"], "warn")
        self.assertEqual(updated.last_context_band, "warn")
        self.assertEqual(updated.last_context_nudge_at, 100.0)
        self.assertTrue(updated.awaiting_context_ack)

    def test_repeating_same_band_inside_cooldown_does_not_renudge(self) -> None:
        self.assertIsNotNone(maybe_plan_hidden_context_nudge, "maybe_plan_hidden_context_nudge must be implemented")

        state = WatchState(
            watch_id="watch-ctx-2",
            target_session_key="agent:webgen:proj-demo",
        )
        _, warned = maybe_plan_hidden_context_nudge(
            state,
            context_band="warn",
            now=100.0,
            cooldown_seconds=300.0,
        )

        action, updated = maybe_plan_hidden_context_nudge(
            warned,
            context_band="warn",
            now=120.0,
            cooldown_seconds=300.0,
        )

        self.assertIsNone(action)
        self.assertEqual(updated.last_context_band, "warn")
        self.assertEqual(updated.last_context_nudge_at, 100.0)
        self.assertTrue(updated.awaiting_context_ack)

    def test_warn_to_compact_triggers_stronger_nudge(self) -> None:
        self.assertIsNotNone(maybe_plan_hidden_context_nudge, "maybe_plan_hidden_context_nudge must be implemented")

        state = WatchState(
            watch_id="watch-ctx-3",
            target_session_key="agent:webgen:proj-demo",
            last_context_band="warn",
            last_context_nudge_at=100.0,
            awaiting_context_ack=True,
        )

        action, updated = maybe_plan_hidden_context_nudge(
            state,
            context_band="compact",
            now=120.0,
            cooldown_seconds=300.0,
        )

        self.assertIsNotNone(action)
        assert action is not None
        self.assertEqual(action["band"], "compact")
        self.assertEqual(updated.last_context_band, "compact")
        self.assertEqual(updated.last_context_nudge_at, 120.0)
        self.assertTrue(updated.awaiting_context_ack)

    def test_ack_detection_clears_awaiting_context_ack(self) -> None:
        self.assertIsNotNone(clear_context_ack, "clear_context_ack must be implemented")

        state = WatchState(
            watch_id="watch-ctx-4",
            target_session_key="agent:webgen:proj-demo",
            last_context_band="compact",
            last_context_nudge_at=100.0,
            awaiting_context_ack=True,
        )

        updated = clear_context_ack(
            state,
            [
                {
                    "summary": "✅ 已执行 /compact，继续当前任务",
                }
            ],
        )

        self.assertFalse(updated.awaiting_context_ack)
        self.assertEqual(updated.last_context_band, "compact")
        self.assertEqual(updated.last_context_nudge_at, 100.0)

    def test_ack_detection_does_not_clear_on_echoed_instruction_text(self) -> None:
        self.assertIsNotNone(clear_context_ack, "clear_context_ack must be implemented")

        state = WatchState(
            watch_id="watch-ctx-4b",
            target_session_key="agent:webgen:proj-demo",
            last_context_band="compact",
            last_context_nudge_at=100.0,
            awaiting_context_ack=True,
        )

        updated = clear_context_ack(
            state,
            [
                {
                    "summary": "请先检查当前 context；若已进入 compact 区间，请先执行 /compact，再继续当前任务。",
                    "raw": "echo: 执行 /compact 然后继续",
                }
            ],
        )

        self.assertTrue(updated.awaiting_context_ack)

    def test_ack_detection_requires_explicit_compact_completion_signal(self) -> None:
        self.assertIsNotNone(clear_context_ack, "clear_context_ack must be implemented")

        state = WatchState(
            watch_id="watch-ctx-4c",
            target_session_key="agent:webgen:proj-demo",
            last_context_band="compact",
            last_context_nudge_at=100.0,
            awaiting_context_ack=True,
        )

        updated = clear_context_ack(
            state,
            [
                {
                    "summary": "Context compacted successfully. Continuing with the current task.",
                }
            ],
        )

        self.assertFalse(updated.awaiting_context_ack)

    def test_silent_nudge_only_produces_no_user_visible_broadcast(self) -> None:
        self.assertIsNotNone(maybe_plan_hidden_context_nudge, "maybe_plan_hidden_context_nudge must be implemented")

        state = WatchState(
            watch_id="watch-ctx-5",
            target_session_key="agent:webgen:proj-demo",
        )

        action, updated = maybe_plan_hidden_context_nudge(
            state,
            context_band="warn",
            now=100.0,
            cooldown_seconds=300.0,
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
        self.assertEqual(batch, [])
        self.assertTrue(post_batch.awaiting_context_ack)

    def test_returning_to_ok_clears_awaiting_context_ack(self) -> None:
        self.assertIsNotNone(maybe_plan_hidden_context_nudge, "maybe_plan_hidden_context_nudge must be implemented")

        state = WatchState(
            watch_id="watch-ctx-6",
            target_session_key="agent:webgen:proj-demo",
            last_context_band="warn",
            last_context_nudge_at=100.0,
            awaiting_context_ack=True,
        )

        action, updated = maybe_plan_hidden_context_nudge(
            state,
            context_band="ok",
            now=200.0,
            cooldown_seconds=300.0,
        )

        self.assertIsNone(action)
        self.assertEqual(updated.last_context_band, "ok")
        self.assertFalse(updated.awaiting_context_ack)


if __name__ == "__main__":
    unittest.main()
