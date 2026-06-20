import importlib.util
import io
import tempfile
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
    def test_run_watch_cycle_startup_resolves_session_file_and_pulls_via_fallback(self) -> None:
        module = load_live_webgen_progress_module()
        self.assertTrue(
            hasattr(module, "run_watch_cycle"),
            "run_watch_cycle must be implemented",
        )

        state = WatchState(
            watch_id="watch-webgen-demo",
            target_session_key="agent:webgen:proj-demo",
        )
        sample = module.SessionFileSample(
            path=Path("/tmp/proj-demo.jsonl"),
            exists=True,
            mtime=11.0,
            size=110,
            inode=2,
            sampled_at=100.0,
        )

        updated, last_seen, batch, pulled = module.run_watch_cycle(
            watch_state=state,
            current_session_key="agent:webgen:proj-demo",
            last_seen=-1,
            now=100.0,
            limit=30,
            max_items=3,
            heartbeat_idle_polls=3,
            heartbeat_interval_seconds=60.0,
            fallback_history_interval_seconds=30.0,
            session_file_resolver=lambda _session_key: Path("/tmp/proj-demo.jsonl"),
            sample_session_file_fn=lambda _path: sample,
            invoke_sessions_history_fn=lambda _session_key, _include_tools, _limit: {
                "messages": [
                    {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "已完成首版实现，正在截图验证"}],
                        "__openclaw": {"seq": 12},
                    }
                ]
            },
            debounce_seconds=0.0,
            sleep_fn=lambda _seconds: None,
        )

        self.assertTrue(pulled)
        self.assertEqual(updated.session_file_path, "/tmp/proj-demo.jsonl")
        self.assertEqual(updated.session_file_size, 110)
        self.assertEqual(updated.last_history_pull_at, 100.0)
        self.assertEqual(last_seen, 12)
        self.assertEqual(len(batch), 1)
        self.assertIn("截图验证", batch[0]["summary"])

    def test_run_watch_cycle_file_change_triggers_history_pull_and_updates_sample(self) -> None:
        module = load_live_webgen_progress_module()

        state = WatchState(
            watch_id="watch-webgen-demo",
            target_session_key="agent:webgen:proj-demo",
            session_file_path="/tmp/proj-demo.jsonl",
            session_file_mtime=10.0,
            session_file_size=100,
            session_file_inode=1,
            last_history_pull_at=95.0,
        )
        changed_sample = module.SessionFileSample(
            path=Path("/tmp/proj-demo.jsonl"),
            exists=True,
            mtime=11.0,
            size=110,
            inode=1,
            sampled_at=100.0,
        )

        updated, last_seen, batch, pulled = module.run_watch_cycle(
            watch_state=state,
            current_session_key="agent:webgen:proj-demo",
            last_seen=11,
            now=100.0,
            limit=30,
            max_items=3,
            heartbeat_idle_polls=3,
            heartbeat_interval_seconds=60.0,
            fallback_history_interval_seconds=30.0,
            session_file_resolver=lambda _session_key: Path("/tmp/proj-demo.jsonl"),
            sample_session_file_fn=lambda _path: changed_sample,
            invoke_sessions_history_fn=lambda _session_key, _include_tools, _limit: {
                "messages": [
                    {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "已进入验证阶段，正在截图检查"}],
                        "__openclaw": {"seq": 12},
                    }
                ]
            },
            debounce_seconds=0.0,
            sleep_fn=lambda _seconds: None,
        )

        self.assertTrue(pulled)
        self.assertEqual(updated.session_file_mtime, 11.0)
        self.assertEqual(updated.session_file_size, 110)
        self.assertEqual(updated.last_history_pull_at, 100.0)
        self.assertEqual(last_seen, 12)
        self.assertEqual(len(batch), 1)
        self.assertIn("截图检查", batch[0]["summary"])

    def test_run_watch_cycle_re_resolves_session_file_when_saved_path_missing(self) -> None:
        module = load_live_webgen_progress_module()

        state = WatchState(
            watch_id="watch-webgen-demo",
            target_session_key="agent:webgen:proj-demo",
            session_file_path="/tmp/old.jsonl",
            session_file_mtime=10.0,
            session_file_size=100,
            session_file_inode=1,
            last_session_event_at=95.0,
            last_history_pull_at=95.0,
        )
        samples = {
            "/tmp/old.jsonl": module.SessionFileSample(
                path=Path("/tmp/old.jsonl"),
                exists=False,
                mtime=0.0,
                size=0,
                inode=0,
                sampled_at=100.0,
            ),
            "/tmp/new.jsonl": module.SessionFileSample(
                path=Path("/tmp/new.jsonl"),
                exists=True,
                mtime=11.0,
                size=110,
                inode=2,
                sampled_at=101.0,
            ),
        }

        updated, last_seen, batch, pulled = module.run_watch_cycle(
            watch_state=state,
            current_session_key="agent:webgen:proj-demo",
            last_seen=11,
            now=100.0,
            limit=30,
            max_items=3,
            heartbeat_idle_polls=3,
            heartbeat_interval_seconds=60.0,
            fallback_history_interval_seconds=30.0,
            session_file_resolver=lambda _session_key: Path("/tmp/new.jsonl"),
            sample_session_file_fn=lambda path: samples[str(path)],
            invoke_sessions_history_fn=lambda _session_key, _include_tools, _limit: {
                "messages": [
                    {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "已切到新 session 文件，继续验证"}],
                        "__openclaw": {"seq": 12},
                    }
                ]
            },
            debounce_seconds=0.0,
            sleep_fn=lambda _seconds: None,
        )

        self.assertTrue(pulled)
        self.assertEqual(updated.session_file_path, "/tmp/new.jsonl")
        self.assertEqual(updated.session_file_mtime, 11.0)
        self.assertEqual(updated.session_file_size, 110)
        self.assertEqual(updated.session_file_inode, 2)
        self.assertEqual(updated.last_history_pull_at, 100.0)
        self.assertEqual(last_seen, 12)
        self.assertEqual(len(batch), 1)
        self.assertIn("继续验证", batch[0]["summary"])

    def test_run_watch_cycle_does_not_rebroadcast_when_history_has_no_new_messages(self) -> None:
        module = load_live_webgen_progress_module()

        state = WatchState(
            watch_id="watch-webgen-demo",
            target_session_key="agent:webgen:proj-demo",
            session_file_path="/tmp/proj-demo.jsonl",
            session_file_mtime=10.0,
            session_file_size=100,
            session_file_inode=1,
            last_history_pull_at=95.0,
        )
        changed_sample = module.SessionFileSample(
            path=Path("/tmp/proj-demo.jsonl"),
            exists=True,
            mtime=11.0,
            size=110,
            inode=1,
            sampled_at=100.0,
        )

        updated, last_seen, batch, pulled = module.run_watch_cycle(
            watch_state=state,
            current_session_key="agent:webgen:proj-demo",
            last_seen=12,
            now=100.0,
            limit=30,
            max_items=3,
            heartbeat_idle_polls=3,
            heartbeat_interval_seconds=60.0,
            fallback_history_interval_seconds=30.0,
            session_file_resolver=lambda _session_key: Path("/tmp/proj-demo.jsonl"),
            sample_session_file_fn=lambda _path: changed_sample,
            invoke_sessions_history_fn=lambda _session_key, _include_tools, _limit: {
                "messages": [
                    {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "已进入验证阶段，正在截图检查"}],
                        "__openclaw": {"seq": 12},
                    }
                ]
            },
            debounce_seconds=0.0,
            sleep_fn=lambda _seconds: None,
        )

        self.assertTrue(pulled)
        self.assertEqual(last_seen, 12)
        self.assertEqual(batch, [])
        self.assertEqual(updated.last_history_pull_at, 100.0)

    def test_resolve_or_refresh_session_file_updates_state_from_resolver(self) -> None:
        module = load_live_webgen_progress_module()
        self.assertTrue(
            hasattr(module, "resolve_or_refresh_session_file"),
            "resolve_or_refresh_session_file must be implemented",
        )

        state = WatchState(
            watch_id="watch-webgen-demo",
            target_session_key="agent:webgen:proj-demo",
        )

        updated = module.resolve_or_refresh_session_file(
            state,
            session_key="agent:webgen:proj-demo",
            resolver=lambda session_key: Path(f"/tmp/{session_key.split(':')[-1]}.jsonl"),
        )

        self.assertEqual(updated.session_file_path, "/tmp/proj-demo.jsonl")

    def test_should_pull_history_from_file_event_detects_changed_sample(self) -> None:
        module = load_live_webgen_progress_module()
        self.assertTrue(
            hasattr(module, "should_pull_history_from_file_event"),
            "should_pull_history_from_file_event must be implemented",
        )

        previous = module.SessionFileSample(
            path=Path("/tmp/demo.jsonl"),
            exists=True,
            mtime=10.0,
            size=100,
            inode=1,
            sampled_at=20.0,
        )
        current = module.SessionFileSample(
            path=Path("/tmp/demo.jsonl"),
            exists=True,
            mtime=11.0,
            size=110,
            inode=1,
            sampled_at=21.0,
        )

        self.assertTrue(module.should_pull_history_from_file_event(previous, current))
        self.assertFalse(module.should_pull_history_from_file_event(current, current))

    def test_should_run_fallback_history_pull_respects_interval(self) -> None:
        module = load_live_webgen_progress_module()
        self.assertTrue(
            hasattr(module, "should_run_fallback_history_pull"),
            "should_run_fallback_history_pull must be implemented",
        )

        stale = WatchState(
            watch_id="watch-webgen-demo",
            target_session_key="agent:webgen:proj-demo",
            last_history_pull_at=50.0,
        )
        fresh = WatchState(
            watch_id="watch-webgen-fresh",
            target_session_key="agent:webgen:proj-demo",
            last_history_pull_at=95.0,
        )

        self.assertTrue(
            module.should_run_fallback_history_pull(
                stale,
                now=100.0,
                fallback_history_interval_seconds=30.0,
            )
        )
        self.assertFalse(
            module.should_run_fallback_history_pull(
                fresh,
                now=100.0,
                fallback_history_interval_seconds=30.0,
            )
        )

    def test_claim_worker_lease_marks_running_and_sets_expiry(self) -> None:
        module = load_live_webgen_progress_module()
        self.assertTrue(
            hasattr(module, "claim_worker_lease"),
            "claim_worker_lease must be implemented",
        )

        state = WatchState(
            watch_id="watch-webgen-demo",
            target_session_key="agent:webgen:proj-demo",
            status="pending",
        )

        updated = module.claim_worker_lease(
            state,
            worker_id="worker-1",
            now=100.0,
            lease_seconds=30.0,
        )

        self.assertEqual(updated.status, "running")
        self.assertEqual(updated.lease_owner, "worker-1")
        self.assertEqual(updated.lease_until, 130.0)
        self.assertEqual(updated.last_worker_heartbeat_at, 100.0)

    def test_record_delivery_outcome_marks_terminal_summary_delivered_after_rebroadcast(self) -> None:
        module = load_live_webgen_progress_module()
        self.assertTrue(
            hasattr(module, "record_delivery_outcome"),
            "record_delivery_outcome must be implemented",
        )

        state = WatchState(
            watch_id="watch-webgen-demo",
            target_session_key="agent:webgen:proj-demo",
            status="done",
            phase="done",
            final_delivered=False,
        )

        updated = module.record_delivery_outcome(
            state,
            batch=[{"kind": "assistant", "summary": "✅ 已完成最终交付"}],
            delivered=True,
        )

        self.assertTrue(updated.final_delivered)
        self.assertEqual(updated.final_summary, "✅ 已完成最终交付")

    def test_record_delivery_outcome_keeps_terminal_summary_pending_when_not_sent(self) -> None:
        module = load_live_webgen_progress_module()

        state = WatchState(
            watch_id="watch-webgen-demo",
            target_session_key="agent:webgen:proj-demo",
            status="done",
            phase="done",
            final_delivered=False,
        )

        updated = module.record_delivery_outcome(
            state,
            batch=[{"kind": "assistant", "summary": "✅ 已完成最终交付"}],
            delivered=False,
        )

        self.assertFalse(updated.final_delivered)
        self.assertEqual(updated.final_summary, "✅ 已完成最终交付")

    def test_should_exit_worker_respects_idle_threshold_and_final_delivery(self) -> None:
        module = load_live_webgen_progress_module()
        self.assertTrue(
            hasattr(module, "should_exit_worker"),
            "should_exit_worker must be implemented",
        )

        idle_state = WatchState(
            watch_id="watch-webgen-demo",
            target_session_key="agent:webgen:proj-demo",
            status="running",
            idle_poll_count=4,
        )
        pending_final_state = WatchState(
            watch_id="watch-webgen-final",
            target_session_key="agent:webgen:proj-demo",
            status="done",
            phase="done",
            idle_poll_count=10,
            final_delivered=False,
            final_summary="✅ 已完成最终交付",
        )

        self.assertTrue(module.should_exit_worker(idle_state, idle_exit_polls=4))
        self.assertFalse(module.should_exit_worker(pending_final_state, idle_exit_polls=4))

    def test_resolve_gateway_sessions_send_support_respects_default_http_deny(self) -> None:
        module = load_live_webgen_progress_module()
        self.assertTrue(
            hasattr(module, "resolve_gateway_sessions_send_support"),
            "resolve_gateway_sessions_send_support must be implemented",
        )

        self.assertFalse(module.resolve_gateway_sessions_send_support({}))
        self.assertFalse(
            module.resolve_gateway_sessions_send_support(
                {"gateway": {"tools": {"allow": [], "deny": []}}}
            )
        )
        self.assertTrue(
            module.resolve_gateway_sessions_send_support(
                {"gateway": {"tools": {"allow": ["sessions_send"]}}}
            )
        )
        self.assertFalse(
            module.resolve_gateway_sessions_send_support(
                {"gateway": {"tools": {"allow": ["sessions_send"], "deny": ["sessions_send"]}}}
            )
        )

    def test_resolve_origin_session_key_prefers_cli_then_env(self) -> None:
        module = load_live_webgen_progress_module()
        self.assertTrue(
            hasattr(module, "resolve_origin_session_key"),
            "resolve_origin_session_key must be implemented",
        )

        self.assertEqual(
            module.resolve_origin_session_key("agent:main:cli", {"OPENCLAW_ORIGIN_SESSION_KEY": "agent:main:env"}),
            "agent:main:cli",
        )
        self.assertEqual(
            module.resolve_origin_session_key("", {"OPENCLAW_ORIGIN_SESSION_KEY": "agent:main:env"}),
            "agent:main:env",
        )
        self.assertEqual(module.resolve_origin_session_key("", {}), "")

    def test_resolve_watch_runtime_config_derives_state_file_when_missing(self) -> None:
        module = load_live_webgen_progress_module()
        self.assertTrue(
            hasattr(module, "resolve_watch_runtime_config"),
            "resolve_watch_runtime_config must be implemented",
        )

        cfg = {"gateway": {"tools": {"allow": ["sessions_send"]}}}
        resolved = module.resolve_watch_runtime_config(
            cfg=cfg,
            session_key="agent:webgen:proj-demo",
            state_file="",
            watch_id="default",
            origin_session_key="",
            requested_origin_session_key="",
            env={"OPENCLAW_ORIGIN_SESSION_KEY": "agent:main:discord:dm:buddy"},
            delivery_strategy="auto",
            supports_hidden_wake=False,
            supports_sessions_send=False,
        )

        self.assertEqual(resolved["watch_id"], "watch-agent-webgen-proj-demo")
        self.assertEqual(resolved["origin_session_key"], "agent:main:discord:dm:buddy")
        self.assertEqual(resolved["delivery_strategy"], "rebroadcast")
        self.assertTrue(str(resolved["state_file"]).endswith("/watch-agent-webgen-proj-demo.json"))

    def test_render_batch_text_joins_summaries_for_rebroadcast(self) -> None:
        module = load_live_webgen_progress_module()
        self.assertTrue(
            hasattr(module, "render_batch_text"),
            "render_batch_text must be implemented",
        )

        text = module.render_batch_text(
            [
                {"summary": "✅ 构建成功：vite build"},
                {"summary": "💬 已完成首版实现，正在截图验证"},
            ]
        )

        self.assertEqual(text, "✅ 构建成功：vite build\n💬 已完成首版实现，正在截图验证")

    def test_deliver_batch_rebroadcasts_to_origin_session(self) -> None:
        module = load_live_webgen_progress_module()
        self.assertTrue(
            hasattr(module, "deliver_batch"),
            "deliver_batch must be implemented",
        )

        calls: list[tuple[str, str]] = []

        def fake_send(_url: str, _headers: dict[str, str], session_key: str, message: str) -> None:
            calls.append((session_key, message))

        output = io.StringIO()
        delivered = module.deliver_batch(
            [
                {"summary": "✅ 构建成功：vite build"},
                {"summary": "💬 已完成首版实现，正在截图验证"},
            ],
            delivery_strategy="rebroadcast",
            origin_session_key="chat:current",
            url="http://127.0.0.1:1/tools/invoke",
            headers={},
            send_fn=fake_send,
            jsonl=False,
            stream=output,
        )

        self.assertTrue(delivered)
        self.assertEqual(
            calls,
            [("chat:current", "✅ 构建成功：vite build\n💬 已完成首版实现，正在截图验证")],
        )
        self.assertEqual(output.getvalue(), "")

    def test_deliver_batch_manual_pull_writes_locally(self) -> None:
        module = load_live_webgen_progress_module()
        self.assertTrue(
            hasattr(module, "deliver_batch"),
            "deliver_batch must be implemented",
        )

        calls: list[tuple[str, str]] = []

        def fake_send(_url: str, _headers: dict[str, str], session_key: str, message: str) -> None:
            calls.append((session_key, message))

        output = io.StringIO()
        delivered = module.deliver_batch(
            [{"seq": 12, "kind": "assistant", "summary": "💬 已完成首版实现，正在截图验证"}],
            delivery_strategy="manual_pull",
            origin_session_key="chat:current",
            url="http://127.0.0.1:1/tools/invoke",
            headers={},
            send_fn=fake_send,
            jsonl=False,
            stream=output,
        )

        self.assertFalse(delivered)
        self.assertEqual(calls, [])
        self.assertIn("正在截图验证", output.getvalue())

    def test_handle_rebroadcast_failure_downgrades_when_sessions_send_is_unavailable(self) -> None:
        module = load_live_webgen_progress_module()
        self.assertTrue(
            hasattr(module, "handle_delivery_failure"),
            "handle_delivery_failure must be implemented",
        )

        state = WatchState(
            watch_id="watch-webgen-demo",
            target_session_key="agent:webgen:proj-demo",
            origin_session_key="agent:main:main",
            delivery_strategy="rebroadcast",
            phase="implementing",
            status="running",
        )

        updated = module.handle_delivery_failure(
            state,
            RuntimeError('{"message":"Tool not available: sessions_send"}'),
        )

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.delivery_strategy, "manual_pull")
        self.assertEqual(updated.origin_session_key, "agent:main:main")
        self.assertIn("sessions_send", updated.pending_control_summary)
        self.assertIn("manual_pull", updated.pending_control_summary)

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
