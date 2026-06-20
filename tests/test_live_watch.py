import tempfile
import unittest
from pathlib import Path

from runtime.live_watch import (
    build_watch_bootstrap,
    build_watch_invocation,
    build_rechain_invocation,
    load_rechain_invocation,
    prepare_watch_state,
    WatchState,
    build_broadcast_batch,
    is_cron_restricted_error_text,
    maybe_create_heartbeat,
    maybe_take_control_event,
    record_control_event,
    record_cycle_state,
    is_internal_prompt_text,
    has_active_lease,
    is_terminal_watch,
    load_watch_state,
    needs_final_delivery,
    resolve_delivery_strategy,
    resolve_visible_wake_state,
    save_watch_state,
    summarize_new_messages,
    take_pending_broadcast_batch,
    watch_is_delivery_degraded,
    watch_requires_supervisor,
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
                origin_session_key="chat:current",
                delivery_strategy="rebroadcast",
                last_seen_seq=41,
                last_broadcast_seq=39,
                phase="implementing",
                last_context_band="compact",
                last_context_nudge_at=123.0,
                awaiting_context_ack=True,
                status="running",
                lease_owner="worker-1",
                lease_until=456.0,
                last_worker_heartbeat_at=455.0,
                final_delivered=True,
                final_summary="✅ 已完成最终交付",
                session_file_path="/tmp/session.jsonl",
                session_file_mtime=789.0,
                session_file_size=321,
                session_file_inode=654,
                last_session_event_at=790.0,
                last_history_pull_at=791.0,
                last_delivered_seq=38,
                pending_broadcast_items=[{"seq": 40, "summary": "🔧 正在验证"}],
                pending_count=1,
                last_pending_summary="🔧 正在验证",
                supervisor_pid=4321,
                supervisor_started_at=792.0,
                supervisor_heartbeat_at=793.0,
                delivery_degraded_reason="manual_pull_requires_user_turn",
            )

            save_watch_state(path, original)
            loaded = load_watch_state(path, "watch-2")

        self.assertEqual(loaded, original)

    def test_load_missing_new_state_fields_keeps_backward_compatible_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "watch-state.json"
            path.write_text(
                """
{
  "watches": {
    "watch-legacy": {
      "watch_id": "watch-legacy",
      "target_session_key": "agent:webgen:proj-legacy",
      "phase": "implementing"
    }
  }
}
""".strip()
                + "\n",
                encoding="utf-8",
            )

            loaded = load_watch_state(path, "watch-legacy")

        self.assertEqual(loaded.status, "pending")
        self.assertEqual(loaded.lease_owner, "")
        self.assertEqual(loaded.lease_until, 0.0)
        self.assertEqual(loaded.last_worker_heartbeat_at, 0.0)
        self.assertFalse(loaded.final_delivered)
        self.assertEqual(loaded.final_summary, "")

    def test_watch_requires_supervisor_and_manual_pull_is_degraded(self) -> None:
        manual_pull = WatchState(
            watch_id="watch-manual",
            target_session_key="agent:webgen:proj-demo",
            delivery_strategy="manual_pull",
        )
        rebroadcast = WatchState(
            watch_id="watch-rebroadcast",
            target_session_key="agent:webgen:proj-demo",
            delivery_strategy="rebroadcast",
        )
        done = WatchState(
            watch_id="watch-done",
            target_session_key="agent:webgen:proj-demo",
            delivery_strategy="manual_pull",
            status="done",
            phase="done",
        )

        self.assertTrue(watch_requires_supervisor(manual_pull))
        self.assertTrue(watch_requires_supervisor(rebroadcast))
        self.assertFalse(watch_requires_supervisor(done))
        self.assertTrue(watch_is_delivery_degraded(manual_pull))
        self.assertFalse(watch_is_delivery_degraded(rebroadcast))

    def test_take_pending_broadcast_batch_returns_items_and_clears_backlog(self) -> None:
        state = WatchState(
            watch_id="watch-backlog",
            target_session_key="agent:webgen:proj-demo",
            pending_broadcast_items=[
                {"seq": 41, "summary": "🔧 正在构建"},
                {"seq": 42, "summary": "✅ 构建成功"},
            ],
            pending_count=2,
            last_pending_summary="✅ 构建成功",
            last_delivered_seq=40,
        )

        batch, updated = take_pending_broadcast_batch(state)

        self.assertEqual(len(batch), 2)
        self.assertEqual(batch[0]["seq"], 41)
        self.assertEqual(updated.pending_broadcast_items, [])
        self.assertEqual(updated.pending_count, 0)
        self.assertEqual(updated.last_pending_summary, "")
        self.assertEqual(updated.last_delivered_seq, 42)

    def test_take_pending_broadcast_batch_respects_max_items_and_keeps_remaining_backlog(self) -> None:
        state = WatchState(
            watch_id="watch-backlog",
            target_session_key="agent:webgen:proj-demo",
            pending_broadcast_items=[
                {"seq": 41, "summary": "🔧 正在构建"},
                {"seq": 42, "summary": "✅ 构建成功"},
                {"seq": 43, "summary": "📸 正在截图"},
            ],
            pending_count=3,
            last_pending_summary="📸 正在截图",
            last_delivered_seq=40,
        )

        batch, updated = take_pending_broadcast_batch(state, max_items=2)

        self.assertEqual(batch, [
            {"seq": 41, "summary": "🔧 正在构建"},
            {"seq": 42, "summary": "✅ 构建成功"},
        ])
        self.assertEqual(updated.pending_broadcast_items, [{"seq": 43, "summary": "📸 正在截图"}])
        self.assertEqual(updated.pending_count, 1)
        self.assertEqual(updated.last_pending_summary, "📸 正在截图")
        self.assertEqual(updated.last_delivered_seq, 42)

    def test_has_active_lease_respects_expiry(self) -> None:
        active = WatchState(
            watch_id="watch-lease-active",
            target_session_key="agent:webgen:proj-demo",
            lease_owner="worker-1",
            lease_until=150.0,
        )
        expired = WatchState(
            watch_id="watch-lease-expired",
            target_session_key="agent:webgen:proj-demo",
            lease_owner="worker-2",
            lease_until=90.0,
        )

        self.assertTrue(has_active_lease(active, now=100.0))
        self.assertFalse(has_active_lease(expired, now=100.0))

    def test_terminal_and_final_delivery_helpers_cover_done_state(self) -> None:
        state = WatchState(
            watch_id="watch-final",
            target_session_key="agent:webgen:proj-demo",
            status="done",
            phase="done",
            final_delivered=False,
            final_summary="✅ 已完成最终交付",
        )

        self.assertTrue(is_terminal_watch(state))
        self.assertTrue(needs_final_delivery(state))

    def test_delivery_strategy_prefers_hidden_wake_when_supported(self) -> None:
        self.assertEqual(
            resolve_delivery_strategy(
                requested_strategy="auto",
                supports_hidden_wake=True,
                supports_sessions_send=True,
                origin_session_key="chat:current",
            ),
            "hidden_wake",
        )

    def test_delivery_strategy_uses_rebroadcast_when_hidden_wake_unavailable(self) -> None:
        self.assertEqual(
            resolve_delivery_strategy(
                requested_strategy="auto",
                supports_hidden_wake=False,
                supports_sessions_send=True,
                origin_session_key="chat:current",
            ),
            "rebroadcast",
        )

    def test_delivery_strategy_falls_back_to_manual_pull_without_origin_or_send(self) -> None:
        self.assertEqual(
            resolve_delivery_strategy(
                requested_strategy="auto",
                supports_hidden_wake=False,
                supports_sessions_send=False,
                origin_session_key="",
            ),
            "manual_pull",
        )

    def test_prepare_watch_state_bootstraps_origin_and_rebroadcast_strategy(self) -> None:
        state = WatchState(
            watch_id="watch-bootstrap",
            target_session_key="agent:webgen:proj-demo",
        )

        updated = prepare_watch_state(
            state,
            target_session_key="agent:webgen:proj-demo",
            origin_session_key="agent:main:discord:dm:buddy",
            requested_strategy="auto",
            supports_hidden_wake=False,
            supports_sessions_send=True,
        )

        self.assertEqual(updated.origin_session_key, "agent:main:discord:dm:buddy")
        self.assertEqual(updated.delivery_strategy, "rebroadcast")

    def test_prepare_watch_state_preserves_existing_origin_when_new_origin_missing(self) -> None:
        state = WatchState(
            watch_id="watch-bootstrap-2",
            target_session_key="agent:webgen:proj-demo",
            origin_session_key="agent:main:telegram:group:-1",
            delivery_strategy="rebroadcast",
        )

        updated = prepare_watch_state(
            state,
            target_session_key="agent:webgen:proj-demo",
            origin_session_key="",
            requested_strategy="auto",
            supports_hidden_wake=False,
            supports_sessions_send=True,
        )

        self.assertEqual(updated.origin_session_key, "agent:main:telegram:group:-1")
        self.assertEqual(updated.delivery_strategy, "rebroadcast")

    def test_build_watch_bootstrap_derives_stable_watch_id_and_state_file(self) -> None:
        bootstrap = build_watch_bootstrap(
            target_session_key="agent:webgen:proj-demo",
            origin_session_key="agent:main:discord:dm:buddy",
            requested_strategy="auto",
            supports_hidden_wake=False,
            supports_sessions_send=True,
        )

        self.assertEqual(bootstrap["watch_id"], "watch-agent-webgen-proj-demo")
        self.assertEqual(bootstrap["delivery_strategy"], "rebroadcast")
        self.assertEqual(bootstrap["origin_session_key"], "agent:main:discord:dm:buddy")
        self.assertTrue(str(bootstrap["state_file"]).endswith("/watch-agent-webgen-proj-demo.json"))

    def test_build_watch_bootstrap_respects_explicit_watch_id_and_state_root(self) -> None:
        bootstrap = build_watch_bootstrap(
            target_session_key="agent:webgen:proj-demo",
            origin_session_key="",
            requested_strategy="manual_pull",
            supports_hidden_wake=False,
            supports_sessions_send=False,
            watch_id="watch-custom",
            state_root=Path("/tmp/custom-watch-root"),
        )

        self.assertEqual(bootstrap["watch_id"], "watch-custom")
        self.assertEqual(bootstrap["delivery_strategy"], "manual_pull")
        self.assertEqual(bootstrap["state_file"], Path("/tmp/custom-watch-root/watch-custom.json"))

    def test_build_watch_invocation_uses_bootstrap_and_env_for_origin_session(self) -> None:
        bootstrap = build_watch_bootstrap(
            target_session_key="agent:webgen:proj-demo",
            origin_session_key="agent:main:discord:dm:buddy",
            requested_strategy="auto",
            supports_hidden_wake=False,
            supports_sessions_send=True,
        )

        invocation = build_watch_invocation(bootstrap)

        self.assertEqual(invocation["env"], {"OPENCLAW_ORIGIN_SESSION_KEY": "agent:main:discord:dm:buddy"})
        self.assertEqual(invocation["command"][0], "python3")
        self.assertEqual(invocation["command"][1], "runtime/live-webgen-progress.py")
        self.assertEqual(invocation["command"][2], "agent:webgen:proj-demo")
        self.assertIn("--state-file", invocation["command"])
        self.assertIn("--watch-id", invocation["command"])
        self.assertIn("--delivery-strategy", invocation["command"])
        self.assertIn("rebroadcast", invocation["command"])
        self.assertNotIn("--origin-session-key", invocation["command"])

    def test_build_watch_invocation_adds_optional_flags_when_requested(self) -> None:
        bootstrap = build_watch_bootstrap(
            target_session_key="agent:webgen:proj-demo",
            origin_session_key="",
            requested_strategy="hidden_wake",
            supports_hidden_wake=True,
            supports_sessions_send=False,
            watch_id="watch-custom",
            state_root=Path("/tmp/custom-watch-root"),
        )

        invocation = build_watch_invocation(
            bootstrap,
            interval=10.0,
            limit=50,
            max_items=5,
            debounce_ms=750,
            fallback_history_interval_seconds=18.0,
            auto_switch_webgen=True,
            once=True,
            jsonl=True,
            supports_hidden_wake=True,
        )

        self.assertEqual(invocation["env"], {})
        self.assertIn("--supports-hidden-wake", invocation["command"])
        self.assertIn("--auto-switch-webgen", invocation["command"])
        self.assertIn("--once", invocation["command"])
        self.assertIn("--jsonl", invocation["command"])
        self.assertIn("10.0", invocation["command"])
        self.assertIn("50", invocation["command"])
        self.assertIn("5", invocation["command"])
        self.assertIn("--debounce-ms", invocation["command"])
        self.assertIn("750", invocation["command"])
        self.assertIn("--fallback-history-interval-seconds", invocation["command"])
        self.assertIn("18.0", invocation["command"])

    def test_build_rechain_invocation_returns_none_when_not_needed(self) -> None:
        state = WatchState(
            watch_id="watch-demo",
            target_session_key="agent:webgen:proj-demo",
            phase="implementing",
        )

        invocation = build_rechain_invocation(
            state,
            state_file=Path("/tmp/openclaw-live-watch/watch-demo.json"),
        )

        self.assertIsNone(invocation)

    def test_build_rechain_invocation_uses_state_to_resume_watch(self) -> None:
        state = WatchState(
            watch_id="watch-demo",
            target_session_key="agent:webgen:proj-demo",
            origin_session_key="agent:main:discord:dm:buddy",
            delivery_strategy="rebroadcast",
            phase="verifying",
            needs_rechain=True,
            rechain_reason="♻️ cron 受限：当前回合只能操作当前 cron job，已标记待补链。",
        )

        invocation = build_rechain_invocation(
            state,
            state_file=Path("/tmp/openclaw-live-watch/watch-demo.json"),
        )

        self.assertIsNotNone(invocation)
        assert invocation is not None
        self.assertEqual(invocation["reason"], state.rechain_reason)
        self.assertEqual(invocation["env"], {"OPENCLAW_ORIGIN_SESSION_KEY": "agent:main:discord:dm:buddy"})
        self.assertEqual(invocation["command"][0], "python3")
        self.assertEqual(invocation["command"][2], "agent:webgen:proj-demo")
        self.assertIn("--state-file", invocation["command"])
        self.assertIn("/tmp/openclaw-live-watch/watch-demo.json", invocation["command"])
        self.assertIn("--watch-id", invocation["command"])
        self.assertIn("watch-demo", invocation["command"])
        self.assertIn("--delivery-strategy", invocation["command"])
        self.assertIn("rebroadcast", invocation["command"])

    def test_load_rechain_invocation_reads_state_file_and_returns_resume_spec(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "watch-demo.json"
            save_watch_state(
                state_file,
                WatchState(
                    watch_id="watch-demo",
                    target_session_key="agent:webgen:proj-demo",
                    origin_session_key="agent:main:discord:dm:buddy",
                    delivery_strategy="rebroadcast",
                    phase="verifying",
                    needs_rechain=True,
                    rechain_reason="♻️ cron 受限：当前回合只能操作当前 cron job，已标记待补链。",
                ),
            )

            invocation = load_rechain_invocation(
                state_file=state_file,
                watch_id="watch-demo",
            )

        self.assertIsNotNone(invocation)
        assert invocation is not None
        self.assertEqual(invocation["reason"], "♻️ cron 受限：当前回合只能操作当前 cron job，已标记待补链。")
        self.assertIn(str(state_file), invocation["command"])

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

    def test_cron_restricted_error_text_is_detected(self) -> None:
        self.assertTrue(
            is_cron_restricted_error_text("Cron tool is restricted to the current cron job.")
        )
        self.assertTrue(
            is_cron_restricted_error_text("❌ cron 报错：Cron tool is restricted to the current cron job.")
        )
        self.assertFalse(is_cron_restricted_error_text("❌ cron 报错：unknown cron job id"))

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

    def test_visible_wake_text_recovers_single_watch_from_state_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "watch-state.json"
            state = WatchState(
                watch_id="watch-webgen-demo",
                target_session_key="agent:webgen:proj-demo",
                last_seen_seq=42,
                last_broadcast_seq=40,
                phase="implementing",
            )
            save_watch_state(path, state)

            resolved = resolve_visible_wake_state("当前进度", path)

        self.assertIsNotNone(resolved)
        assert resolved is not None
        self.assertEqual(resolved.watch_id, "watch-webgen-demo")
        self.assertEqual(resolved.target_session_key, "agent:webgen:proj-demo")
        self.assertEqual(resolved.last_seen_seq, 42)

    def test_visible_wake_text_prefers_latest_active_watch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "watch-state.json"
            done_state = WatchState(
                watch_id="watch-webgen-old",
                target_session_key="agent:webgen:proj-old",
                last_seen_seq=80,
                last_broadcast_seq=80,
                phase="done",
            )
            active_state = WatchState(
                watch_id="watch-webgen-new",
                target_session_key="agent:webgen:proj-new",
                last_seen_seq=12,
                last_broadcast_seq=10,
                phase="verifying",
            )
            save_watch_state(path, done_state)
            save_watch_state(path, active_state)

            resolved = resolve_visible_wake_state("当前进度", path)

        self.assertIsNotNone(resolved)
        assert resolved is not None
        self.assertEqual(resolved.watch_id, "watch-webgen-new")
        self.assertEqual(resolved.target_session_key, "agent:webgen:proj-new")
        self.assertEqual(resolved.last_seen_seq, 12)

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

    def test_record_cycle_state_marks_rechain_instead_of_blocking_on_cron_restricted_error(self) -> None:
        state = WatchState(
            watch_id="watch-cron-restricted",
            target_session_key="agent:webgen:proj-demo",
            phase="verifying",
        )
        items = [
            {
                "seq": 12,
                "summary": "♻️ cron 受限：当前回合只能操作当前 cron job，已标记待补链。",
            }
        ]

        updated = record_cycle_state(state, items, now=100.0)

        self.assertEqual(updated.phase, "verifying")
        self.assertTrue(updated.needs_rechain)
        self.assertIn("待补链", updated.rechain_reason)
        self.assertIn("待补链", updated.pending_control_summary)

    def test_build_broadcast_batch_emits_rechain_notice_once(self) -> None:
        state = WatchState(
            watch_id="watch-cron-restricted-2",
            target_session_key="agent:webgen:proj-demo",
            phase="implementing",
            needs_rechain=True,
            rechain_reason="♻️ cron 受限：当前回合只能操作当前 cron job，已标记待补链。",
            pending_control_summary="⚠️ 当前回合处于 cron 受限态，已标记待补链，需在下一次普通用户回合补链。",
        )

        batch, updated = build_broadcast_batch(
            state,
            [],
            now=100.0,
            max_items=3,
            min_idle_polls=3,
            min_heartbeat_interval_seconds=60.0,
        )

        self.assertEqual(len(batch), 1)
        self.assertEqual(batch[0]["kind"], "control")
        self.assertIn("待补链", batch[0]["summary"])
        self.assertFalse(updated.needs_rechain)
        self.assertEqual(updated.pending_control_summary, "")

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
