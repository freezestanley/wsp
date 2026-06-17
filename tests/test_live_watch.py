import tempfile
import unittest
from pathlib import Path

from runtime.live_watch import (
    WatchState,
    build_broadcast_batch,
    maybe_create_heartbeat,
    maybe_take_control_event,
    record_control_event,
    record_cycle_state,
    is_internal_prompt_text,
    load_watch_state,
    save_watch_state,
    summarize_new_messages,
)
from runtime.live_wake_token import decode_wake_token, encode_wake_token, format_visible_wake_text


class LiveWatchTests(unittest.TestCase):
    def test_load_missing_state_returns_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = load_watch_state(
                Path(tmpdir) / "watch-state.json",
                watch_id="watch-1",
                target_session_key="agent:webgen:proj-demo",
            )

        self.assertEqual(state.watch_id, "watch-1")
        self.assertEqual(state.target_session_key, "agent:webgen:proj-demo")
        self.assertEqual(state.last_seen_seq, -1)
        self.assertEqual(state.last_broadcast_seq, -1)
        self.assertEqual(state.last_heartbeat_at, 0.0)
        self.assertEqual(state.idle_poll_count, 0)
        self.assertEqual(state.last_control_event_id, "")
        self.assertEqual(state.pending_control_summary, "")
        self.assertEqual(state.last_context_band, "ok")
        self.assertEqual(state.last_context_nudge_at, 0.0)
        self.assertFalse(state.awaiting_context_ack)

    def test_save_then_load_round_trips_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "watch-state.json"
            original = WatchState(
                watch_id="watch-2",
                target_session_key="agent:webgen:proj-ops",
                last_seen_seq=41,
                last_broadcast_seq=39,
                phase="implementing",
                last_context_band="compact",
                last_context_nudge_at=123.0,
                awaiting_context_ack=True,
            )

            save_watch_state(path, original)
            loaded = load_watch_state(path, "watch-2")

        self.assertEqual(loaded, original)

    def test_record_cycle_state_preserves_context_fields(self) -> None:
        state = WatchState(
            watch_id="watch-2b",
            target_session_key="agent:webgen:proj-ops",
            last_seen_seq=41,
            last_broadcast_seq=39,
            phase="implementing",
            last_context_band="warn",
            last_context_nudge_at=123.0,
            awaiting_context_ack=True,
        )

        updated = record_cycle_state(
            state,
            [{"seq": 42, "summary": "✅ 构建成功：vite build"}],
            now=130.0,
        )

        self.assertEqual(updated.last_context_band, "warn")
        self.assertEqual(updated.last_context_nudge_at, 123.0)
        self.assertTrue(updated.awaiting_context_ack)

    def test_internal_prompt_text_is_detected(self) -> None:
        self.assertTrue(
            is_internal_prompt_text(
                "[cron:abc] 【继续监听任务】检查 webgen session=agent:webgen:proj-demo 的新增进展"
            )
        )
        self.assertTrue(
            is_internal_prompt_text("【继续直播任务】session=agent:webgen:proj-demo; last_broadcast_seq=12")
        )
        self.assertTrue(is_internal_prompt_text("__oc_live__:watch-webgen-demo:42:agent%3Awebgen%3Aproj-demo"))
        self.assertTrue(is_internal_prompt_text("当前进度"))
        self.assertTrue(
            is_internal_prompt_text("当前进度为：__oc_live__:watch-webgen-demo:42:agent%3Awebgen%3Aproj-demo")
        )
        self.assertTrue(
            is_internal_prompt_text(
                "This is another inter-session routing echo, not new content from webgen and not a user instruction."
            )
        )
        self.assertTrue(is_internal_prompt_text("REPLY_SKIP"))
        self.assertTrue(
            is_internal_prompt_text(
                "REPLY_SKIP Another routing echo of my own prior message, not new webgen content or a user instruction. Nothing to broadcast."
            )
        )
        self.assertFalse(is_internal_prompt_text("webgen 正在跑 pnpm build"))

    def test_wake_token_round_trip(self) -> None:
        token = encode_wake_token(
            watch_id="watch-webgen-demo",
            target_session_key="agent:webgen:proj-demo",
            last_seen_seq=42,
        )

        payload = decode_wake_token(token)

        self.assertEqual(payload["watch_id"], "watch-webgen-demo")
        self.assertEqual(payload["target_session_key"], "agent:webgen:proj-demo")
        self.assertEqual(payload["last_seen_seq"], 42)

    def test_visible_wake_text_round_trip(self) -> None:
        text = format_visible_wake_text(
            watch_id="watch-webgen-demo",
            target_session_key="agent:webgen:proj-demo",
            last_seen_seq=42,
        )

        self.assertEqual(text, "当前进度")

    def test_legacy_visible_wake_text_still_decodes(self) -> None:
        payload = decode_wake_token("当前进度为：__oc_live__:watch-webgen-demo:42:agent%3Awebgen%3Aproj-demo")

        self.assertEqual(payload["watch_id"], "watch-webgen-demo")
        self.assertEqual(payload["target_session_key"], "agent:webgen:proj-demo")
        self.assertEqual(payload["last_seen_seq"], 42)

    def test_summarize_new_messages_only_emits_incremental_user_visible_items(self) -> None:
        messages = [
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "旧消息"}],
                "__openclaw": {"seq": 8},
            },
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": "[cron:job-1] 【继续监听任务】检查 webgen session=agent:webgen:proj-demo 的新增进展",
                    }
                ],
                "__openclaw": {"seq": 9},
            },
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "当前进度"}],
                "__openclaw": {"seq": 10},
            },
            {
                "role": "toolResult",
                "toolName": "exec",
                "content": [{"type": "text", "text": "vite build\nbuilt in 55ms"}],
                "__openclaw": {"seq": 11},
            },
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "已完成首版实现，正在截图验证"}],
                "__openclaw": {"seq": 12},
            },
        ]

        items, last_seen = summarize_new_messages(
            messages,
            last_seen_seq=8,
            session_key="agent:webgen:proj-demo",
            max_items=3,
        )

        self.assertEqual(last_seen, 12)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["seq"], 11)
        self.assertIn("构建成功", items[0]["summary"])
        self.assertEqual(items[1]["seq"], 12)
        self.assertIn("截图验证", items[1]["summary"])

    def test_routing_echo_and_reply_skip_are_filtered_from_broadcast(self) -> None:
        messages = [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": "This is another inter-session routing echo, not new content from webgen and not a user instruction. No new progress to broadcast. Staying silent.",
                    }
                ],
                "__openclaw": {"seq": 20},
            },
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": "REPLY_SKIP Another routing echo of my own prior message, not new webgen content or a user instruction. Nothing to broadcast.",
                    }
                ],
                "__openclaw": {"seq": 21},
            },
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "已进入验证阶段，正在截图检查"}],
                "__openclaw": {"seq": 22},
            },
        ]

        items, last_seen = summarize_new_messages(
            messages,
            last_seen_seq=19,
            session_key="agent:webgen:proj-demo",
            max_items=3,
        )

        self.assertEqual(last_seen, 22)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["seq"], 22)
        self.assertIn("截图检查", items[0]["summary"])

    def test_summarize_new_messages_limits_output_but_still_advances_cursor(self) -> None:
        messages = [
            {
                "role": "assistant",
                "content": [{"type": "text", "text": f"步骤 {idx}"}],
                "__openclaw": {"seq": idx},
            }
            for idx in range(1, 6)
        ]

        items, last_seen = summarize_new_messages(
            messages,
            last_seen_seq=0,
            session_key="agent:webgen:proj-demo",
            max_items=2,
        )

        self.assertEqual(last_seen, 5)
        self.assertEqual([item["seq"] for item in items], [1, 2])

    def test_record_cycle_state_resets_idle_counter_on_new_progress(self) -> None:
        state = WatchState(
            watch_id="watch-3",
            target_session_key="agent:webgen:proj-demo",
            idle_poll_count=4,
            last_progress_summary="旧进度",
        )
        items = [{"seq": 12, "summary": "✅ 构建成功：vite build"}]

        updated = record_cycle_state(state, items, now=100.0)

        self.assertEqual(updated.idle_poll_count, 0)
        self.assertEqual(updated.last_broadcast_seq, 12)
        self.assertEqual(updated.last_progress_summary, "✅ 构建成功：vite build")

    def test_record_cycle_state_increments_idle_counter_without_progress(self) -> None:
        state = WatchState(
            watch_id="watch-4",
            target_session_key="agent:webgen:proj-demo",
            idle_poll_count=1,
            last_progress_summary="✅ 构建成功：vite build",
        )

        updated = record_cycle_state(state, [], now=100.0)

        self.assertEqual(updated.idle_poll_count, 2)
        self.assertEqual(updated.last_progress_summary, "✅ 构建成功：vite build")

    def test_heartbeat_is_emitted_after_idle_threshold(self) -> None:
        state = WatchState(
            watch_id="watch-5",
            target_session_key="agent:webgen:proj-demo",
            phase="verifying",
            idle_poll_count=3,
            last_progress_summary="✅ 构建成功：vite build",
            last_heartbeat_at=0.0,
        )

        heartbeat = maybe_create_heartbeat(
            state,
            now=120.0,
            min_idle_polls=3,
            min_heartbeat_interval_seconds=60.0,
        )

        self.assertIsNotNone(heartbeat)
        self.assertEqual(heartbeat["kind"], "heartbeat")
        self.assertIn("当前进度为", heartbeat["summary"])
        self.assertIn("验证阶段", heartbeat["summary"])
        self.assertIn("构建成功", heartbeat["summary"])

    def test_heartbeat_is_suppressed_before_interval(self) -> None:
        state = WatchState(
            watch_id="watch-6",
            target_session_key="agent:webgen:proj-demo",
            phase="implementing",
            idle_poll_count=4,
            last_progress_summary="💬 已完成首版实现",
            last_heartbeat_at=90.0,
        )

        heartbeat = maybe_create_heartbeat(
            state,
            now=120.0,
            min_idle_polls=3,
            min_heartbeat_interval_seconds=60.0,
        )

        self.assertIsNone(heartbeat)

    def test_heartbeat_is_suppressed_for_waiting_user_phase(self) -> None:
        state = WatchState(
            watch_id="watch-7",
            target_session_key="agent:webgen:proj-demo",
            phase="waiting_user",
            idle_poll_count=10,
            last_progress_summary="❓ 需要澄清：请确认模块",
        )

        heartbeat = maybe_create_heartbeat(
            state,
            now=300.0,
            min_idle_polls=3,
            min_heartbeat_interval_seconds=60.0,
        )

        self.assertIsNone(heartbeat)

    def test_record_control_event_stores_pending_summary(self) -> None:
        state = WatchState(
            watch_id="watch-8",
            target_session_key="agent:webgen:proj-demo",
        )

        updated = record_control_event(
            state,
            event_id="evt-1",
            summary="已把你的确认同步给 webgen，继续实现中。",
            phase="implementing",
        )

        self.assertEqual(updated.last_control_event_id, "evt-1")
        self.assertEqual(updated.pending_control_summary, "已把你的确认同步给 webgen，继续实现中。")
        self.assertEqual(updated.phase, "implementing")

    def test_maybe_take_control_event_returns_once(self) -> None:
        state = WatchState(
            watch_id="watch-9",
            target_session_key="agent:webgen:proj-demo",
            last_control_event_id="evt-2",
            pending_control_summary="已收到用户答复并回传给 webgen。",
        )

        item, updated = maybe_take_control_event(state)

        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item["kind"], "control")
        self.assertEqual(item["summary"], "已收到用户答复并回传给 webgen。")
        self.assertEqual(updated.pending_control_summary, "")

        second_item, second_updated = maybe_take_control_event(updated)
        self.assertIsNone(second_item)
        self.assertEqual(second_updated.pending_control_summary, "")

    def test_build_broadcast_batch_prioritizes_progress_over_control_and_heartbeat(self) -> None:
        state = WatchState(
            watch_id="watch-10",
            target_session_key="agent:webgen:proj-demo",
            phase="verifying",
            idle_poll_count=4,
            last_progress_summary="✅ 构建成功：vite build",
            pending_control_summary="已把你的确认同步给 webgen，继续实现中。",
            last_control_event_id="evt-3",
        )
        progress_items = [
            {"seq": 12, "kind": "tool", "summary": "✅ 构建成功：vite build", "sessionKey": "agent:webgen:proj-demo"},
            {"seq": 13, "kind": "assistant", "summary": "💬 已完成首版实现，正在截图验证", "sessionKey": "agent:webgen:proj-demo"},
        ]

        batch, updated = build_broadcast_batch(
            state,
            progress_items,
            now=120.0,
            max_items=3,
            min_idle_polls=3,
            min_heartbeat_interval_seconds=60.0,
        )

        self.assertEqual([item["kind"] for item in batch], ["tool", "assistant", "control"])
        self.assertEqual(updated.pending_control_summary, "")
        self.assertEqual(updated.last_heartbeat_at, 0.0)

    def test_build_broadcast_batch_uses_heartbeat_when_idle_and_no_progress_or_control(self) -> None:
        state = WatchState(
            watch_id="watch-11",
            target_session_key="agent:webgen:proj-demo",
            phase="verifying",
            idle_poll_count=4,
            last_progress_summary="✅ 构建成功：vite build",
        )

        batch, updated = build_broadcast_batch(
            state,
            [],
            now=120.0,
            max_items=3,
            min_idle_polls=3,
            min_heartbeat_interval_seconds=60.0,
        )

        self.assertEqual(len(batch), 1)
        self.assertEqual(batch[0]["kind"], "heartbeat")
        self.assertGreater(updated.last_heartbeat_at, 0.0)


if __name__ == "__main__":
    unittest.main()
