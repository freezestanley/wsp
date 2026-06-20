import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from runtime.live_watch import WatchState, load_watch_state, save_watch_state


def load_ensure_live_watch_module():
    module_path = Path(__file__).resolve().parent.parent / "runtime" / "ensure-live-watch.py"
    spec = importlib.util.spec_from_file_location("ensure_live_watch_script", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load runtime/ensure-live-watch.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EnsureLiveWatchTests(unittest.TestCase):
    def test_resolve_watch_action_auto_discovers_origin_but_keeps_manual_pull_without_gateway_allow(self) -> None:
        module = load_ensure_live_watch_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / ".openclaw"
            (root / "agents" / "main" / "sessions").mkdir(parents=True)
            (root / "tui").mkdir(parents=True)
            (root / "openclaw.json").write_text(
                json.dumps(
                    {
                        "tools": {
                            "agentToAgent": {"enabled": True},
                            "sessions": {"visibility": "all"},
                        },
                        "gateway": {},
                    }
                ),
                encoding="utf-8",
            )
            (root / "agents" / "main" / "sessions" / "sessions.json").write_text(
                json.dumps(
                    {
                        "agent:main:main": {
                            "updatedAt": 1000,
                        }
                    }
                ),
                encoding="utf-8",
            )
            state_file = Path(tmpdir) / "watch-demo.json"
            with patch.dict(os.environ, {"OPENCLAW_HOME": str(root)}, clear=False):
                payload = module.resolve_watch_action(
                    session_key="agent:webgen:proj-demo",
                    state_file=state_file,
                    watch_id="watch-demo",
                    origin_session_key="",
                    delivery_strategy="auto",
                    supports_hidden_wake=False,
                    supports_sessions_send=False,
                    now=100.0,
                )

        self.assertEqual(payload["status"], "start")
        self.assertEqual(payload["originSessionKey"], "agent:main:main")
        self.assertEqual(payload["deliveryStrategy"], "manual_pull")
        self.assertEqual(
            payload["invocation"]["env"],
            {"OPENCLAW_ORIGIN_SESSION_KEY": "agent:main:main"},
        )

    def test_resolve_watch_action_auto_discovers_rebroadcast_when_gateway_explicitly_allows_it(self) -> None:
        module = load_ensure_live_watch_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / ".openclaw"
            (root / "agents" / "main" / "sessions").mkdir(parents=True)
            (root / "openclaw.json").write_text(
                json.dumps(
                    {
                        "tools": {
                            "agentToAgent": {"enabled": True},
                            "sessions": {"visibility": "all"},
                        },
                        "gateway": {
                            "tools": {
                                "allow": ["sessions_send"],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            (root / "agents" / "main" / "sessions" / "sessions.json").write_text(
                json.dumps(
                    {
                        "agent:main:main": {
                            "updatedAt": 1000,
                        }
                    }
                ),
                encoding="utf-8",
            )
            state_file = Path(tmpdir) / "watch-demo.json"
            with patch.dict(os.environ, {"OPENCLAW_HOME": str(root)}, clear=False):
                payload = module.resolve_watch_action(
                    session_key="agent:webgen:proj-demo",
                    state_file=state_file,
                    watch_id="watch-demo",
                    origin_session_key="",
                    delivery_strategy="auto",
                    supports_hidden_wake=False,
                    supports_sessions_send=False,
                    now=100.0,
                )

        self.assertEqual(payload["status"], "start")
        self.assertEqual(payload["originSessionKey"], "agent:main:main")
        self.assertEqual(payload["deliveryStrategy"], "rebroadcast")
        self.assertEqual(
            payload["invocation"]["env"],
            {"OPENCLAW_ORIGIN_SESSION_KEY": "agent:main:main"},
        )

    def test_resolve_watch_action_returns_start_for_missing_state(self) -> None:
        module = load_ensure_live_watch_module()
        self.assertTrue(
            hasattr(module, "resolve_watch_action"),
            "resolve_watch_action must be implemented",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "watch-demo.json"
            payload = module.resolve_watch_action(
                session_key="agent:webgen:proj-demo",
                state_file=state_file,
                watch_id="watch-demo",
                origin_session_key="agent:main:discord:dm:buddy",
                delivery_strategy="auto",
                supports_hidden_wake=False,
                supports_sessions_send=True,
                now=100.0,
            )
            loaded = load_watch_state(state_file, "watch-demo")

        self.assertEqual(payload["status"], "start")
        self.assertEqual(payload["watchId"], "watch-demo")
        self.assertEqual(payload["stateFile"], str(state_file))
        self.assertEqual(payload["deliveryStrategy"], "rebroadcast")
        self.assertEqual(payload["invocation"]["command"][1], "runtime/live-watch-supervisor.py")
        self.assertIn("--state-root", payload["invocation"]["command"])
        self.assertIn(str(state_file.parent), payload["invocation"]["command"])
        self.assertEqual(
            payload["invocation"]["env"],
            {"OPENCLAW_ORIGIN_SESSION_KEY": "agent:main:discord:dm:buddy"},
        )
        self.assertEqual(loaded.target_session_key, "agent:webgen:proj-demo")
        self.assertEqual(loaded.origin_session_key, "agent:main:discord:dm:buddy")
        self.assertEqual(loaded.delivery_strategy, "rebroadcast")

    def test_resolve_watch_action_threads_file_watch_tuning_into_invocation(self) -> None:
        module = load_ensure_live_watch_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "watch-demo.json"
            payload = module.resolve_watch_action(
                session_key="agent:webgen:proj-demo",
                state_file=state_file,
                watch_id="watch-demo",
                origin_session_key="agent:main:discord:dm:buddy",
                delivery_strategy="auto",
                supports_hidden_wake=False,
                supports_sessions_send=True,
                interval=5.0,
                limit=30,
                max_items=3,
                debounce_ms=650,
                fallback_history_interval_seconds=22.0,
                now=100.0,
            )

        self.assertEqual(payload["status"], "start")
        self.assertIn("--debounce-ms", payload["invocation"]["command"])
        self.assertIn("650", payload["invocation"]["command"])
        self.assertIn("--fallback-history-interval-seconds", payload["invocation"]["command"])
        self.assertIn("22.0", payload["invocation"]["command"])

    def test_resolve_watch_action_returns_resume_for_pending_rechain(self) -> None:
        module = load_ensure_live_watch_module()

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

            payload = module.resolve_watch_action(
                session_key="agent:webgen:proj-demo",
                state_file=state_file,
                watch_id="watch-demo",
                origin_session_key="agent:main:discord:dm:buddy",
                delivery_strategy="auto",
                supports_hidden_wake=False,
                supports_sessions_send=True,
                now=100.0,
            )

        self.assertEqual(payload["status"], "resume")
        self.assertEqual(payload["reason"], "♻️ cron 受限：当前回合只能操作当前 cron job，已标记待补链。")
        self.assertEqual(payload["invocation"]["command"][0], "python3")

    def test_resolve_watch_action_returns_active_for_existing_nonterminal_watch(self) -> None:
        module = load_ensure_live_watch_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "watch-demo.json"
            save_watch_state(
                state_file,
                WatchState(
                    watch_id="watch-demo",
                    target_session_key="agent:webgen:proj-demo",
                    origin_session_key="agent:main:discord:dm:buddy",
                    delivery_strategy="rebroadcast",
                    status="running",
                    lease_owner="worker-1",
                    lease_until=180.0,
                    phase="implementing",
                    last_seen_seq=42,
                    last_delivered_seq=42,
                    supervisor_pid=4321,
                    supervisor_started_at=90.0,
                    supervisor_heartbeat_at=95.0,
                ),
            )

            payload = module.resolve_watch_action(
                session_key="agent:webgen:proj-demo",
                state_file=state_file,
                watch_id="watch-demo",
                origin_session_key="agent:main:discord:dm:buddy",
                delivery_strategy="auto",
                supports_hidden_wake=False,
                supports_sessions_send=True,
                now=100.0,
            )

        self.assertEqual(payload["status"], "active")
        self.assertEqual(payload["phase"], "implementing")
        self.assertEqual(payload["lastSeenSeq"], 42)
        self.assertNotIn("invocation", payload)

    def test_resolve_watch_action_marks_manual_pull_watch_as_degraded(self) -> None:
        module = load_ensure_live_watch_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "watch-demo.json"
            save_watch_state(
                state_file,
                WatchState(
                    watch_id="watch-demo",
                    target_session_key="agent:webgen:proj-demo",
                    origin_session_key="agent:main:discord:dm:buddy",
                    delivery_strategy="manual_pull",
                    status="running",
                    lease_owner="worker-1",
                    lease_until=180.0,
                    phase="implementing",
                    last_seen_seq=42,
                    supervisor_pid=4321,
                    supervisor_started_at=90.0,
                    supervisor_heartbeat_at=95.0,
                ),
            )

            payload = module.resolve_watch_action(
                session_key="agent:webgen:proj-demo",
                state_file=state_file,
                watch_id="watch-demo",
                origin_session_key="agent:main:discord:dm:buddy",
                delivery_strategy="auto",
                supports_hidden_wake=False,
                supports_sessions_send=False,
                now=100.0,
            )

        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["phase"], "implementing")
        self.assertEqual(payload["deliveryStrategy"], "manual_pull")
        self.assertEqual(payload["lastSeenSeq"], 42)

    def test_resolve_watch_action_returns_resume_for_expired_lease(self) -> None:
        module = load_ensure_live_watch_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "watch-demo.json"
            save_watch_state(
                state_file,
                WatchState(
                    watch_id="watch-demo",
                    target_session_key="agent:webgen:proj-demo",
                    origin_session_key="agent:main:discord:dm:buddy",
                    delivery_strategy="rebroadcast",
                    status="running",
                    lease_owner="worker-1",
                    lease_until=10.0,
                    phase="implementing",
                    supervisor_pid=4321,
                    supervisor_started_at=90.0,
                    supervisor_heartbeat_at=95.0,
                ),
            )

            payload = module.resolve_watch_action(
                session_key="agent:webgen:proj-demo",
                state_file=state_file,
                watch_id="watch-demo",
                origin_session_key="agent:main:discord:dm:buddy",
                delivery_strategy="auto",
                supports_hidden_wake=False,
                supports_sessions_send=True,
                now=100.0,
            )

        self.assertEqual(payload["status"], "resume")
        self.assertEqual(payload["reason"], "lease_expired")
        self.assertEqual(payload["invocation"]["command"][1], "runtime/live-watch-supervisor.py")

    def test_resolve_watch_action_returns_resume_when_supervisor_heartbeat_is_stale(self) -> None:
        module = load_ensure_live_watch_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "watch-demo.json"
            save_watch_state(
                state_file,
                WatchState(
                    watch_id="watch-demo",
                    target_session_key="agent:webgen:proj-demo",
                    origin_session_key="agent:main:discord:dm:buddy",
                    delivery_strategy="rebroadcast",
                    status="running",
                    phase="implementing",
                    lease_owner="worker-1",
                    lease_until=180.0,
                    supervisor_pid=4321,
                    supervisor_started_at=40.0,
                    supervisor_heartbeat_at=50.0,
                ),
            )

            payload = module.resolve_watch_action(
                session_key="agent:webgen:proj-demo",
                state_file=state_file,
                watch_id="watch-demo",
                origin_session_key="agent:main:discord:dm:buddy",
                delivery_strategy="auto",
                supports_hidden_wake=False,
                supports_sessions_send=True,
                now=100.0,
            )

        self.assertEqual(payload["status"], "resume")
        self.assertEqual(payload["reason"], "supervisor_inactive")
        self.assertEqual(payload["invocation"]["command"][1], "runtime/live-watch-supervisor.py")

    def test_resolve_watch_action_returns_resume_when_final_summary_not_delivered(self) -> None:
        module = load_ensure_live_watch_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "watch-demo.json"
            save_watch_state(
                state_file,
                WatchState(
                    watch_id="watch-demo",
                    target_session_key="agent:webgen:proj-demo",
                    origin_session_key="agent:main:discord:dm:buddy",
                    delivery_strategy="rebroadcast",
                    status="done",
                    phase="done",
                    final_delivered=False,
                    final_summary="✅ 已完成最终交付",
                ),
            )

            payload = module.resolve_watch_action(
                session_key="agent:webgen:proj-demo",
                state_file=state_file,
                watch_id="watch-demo",
                origin_session_key="agent:main:discord:dm:buddy",
                delivery_strategy="auto",
                supports_hidden_wake=False,
                supports_sessions_send=True,
            )

        self.assertEqual(payload["status"], "resume")
        self.assertEqual(payload["reason"], "final_delivery_pending")

    def test_resolve_watch_action_returns_degraded_when_backlog_pending(self) -> None:
        module = load_ensure_live_watch_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "watch-demo.json"
            save_watch_state(
                state_file,
                WatchState(
                    watch_id="watch-demo",
                    target_session_key="agent:webgen:proj-demo",
                    origin_session_key="agent:main:discord:dm:buddy",
                    delivery_strategy="manual_pull",
                    status="running",
                    phase="implementing",
                    pending_broadcast_items=[{"seq": 43, "summary": "✅ 构建完成"}],
                    pending_count=1,
                    last_pending_summary="✅ 构建完成",
                    supervisor_pid=4321,
                    supervisor_started_at=90.0,
                    supervisor_heartbeat_at=95.0,
                ),
            )

            payload = module.resolve_watch_action(
                session_key="agent:webgen:proj-demo",
                state_file=state_file,
                watch_id="watch-demo",
                origin_session_key="agent:main:discord:dm:buddy",
                delivery_strategy="auto",
                supports_hidden_wake=False,
                supports_sessions_send=False,
                now=100.0,
            )

        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["pendingCount"], 1)
        self.assertEqual(payload["lastPendingSummary"], "✅ 构建完成")

    def test_resolve_watch_action_returns_degraded_when_rebroadcast_delivery_lags(self) -> None:
        module = load_ensure_live_watch_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "watch-demo.json"
            save_watch_state(
                state_file,
                WatchState(
                    watch_id="watch-demo",
                    target_session_key="agent:webgen:proj-demo",
                    origin_session_key="agent:main:discord:dm:buddy",
                    delivery_strategy="rebroadcast",
                    status="running",
                    phase="implementing",
                    lease_owner="worker-1",
                    lease_until=130.0,
                    supervisor_pid=4321,
                    supervisor_started_at=90.0,
                    supervisor_heartbeat_at=100.0,
                    last_seen_seq=42,
                    last_delivered_seq=41,
                    pending_broadcast_items=[{"seq": 42, "summary": "✅ 构建完成"}],
                    pending_count=1,
                    last_pending_summary="✅ 构建完成",
                    delivery_failure_count=2,
                    delivery_backlog_since=95.0,
                    last_delivery_error="delivery_failed",
                ),
            )

            payload = module.resolve_watch_action(
                session_key="agent:webgen:proj-demo",
                state_file=state_file,
                watch_id="watch-demo",
                origin_session_key="agent:main:discord:dm:buddy",
                delivery_strategy="auto",
                supports_hidden_wake=False,
                supports_sessions_send=True,
                now=110.0,
            )

        self.assertEqual(payload["status"], "degraded")
        self.assertEqual(payload["lastSeenSeq"], 42)
        self.assertEqual(payload["lastDeliveredSeq"], 41)
        self.assertEqual(payload["deliveryFailureCount"], 2)
        self.assertEqual(payload["deliveryBacklogSince"], 95.0)
        self.assertEqual(payload["lastDeliveryError"], "delivery_failed")

    def test_resolve_watch_action_returns_active_when_delivery_is_fresh(self) -> None:
        module = load_ensure_live_watch_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "watch-demo.json"
            save_watch_state(
                state_file,
                WatchState(
                    watch_id="watch-demo",
                    target_session_key="agent:webgen:proj-demo",
                    origin_session_key="agent:main:discord:dm:buddy",
                    delivery_strategy="rebroadcast",
                    status="running",
                    phase="implementing",
                    lease_owner="worker-1",
                    lease_until=130.0,
                    supervisor_pid=4321,
                    supervisor_started_at=90.0,
                    supervisor_heartbeat_at=100.0,
                    last_seen_seq=42,
                    last_delivered_seq=42,
                    last_delivery_success_at=101.0,
                ),
            )

            payload = module.resolve_watch_action(
                session_key="agent:webgen:proj-demo",
                state_file=state_file,
                watch_id="watch-demo",
                origin_session_key="agent:main:discord:dm:buddy",
                delivery_strategy="auto",
                supports_hidden_wake=False,
                supports_sessions_send=True,
                now=110.0,
            )

        self.assertEqual(payload["status"], "active")

    def test_resolve_watch_action_returns_idle_for_terminal_watch_after_final_delivery(self) -> None:
        module = load_ensure_live_watch_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "watch-demo.json"
            save_watch_state(
                state_file,
                WatchState(
                    watch_id="watch-demo",
                    target_session_key="agent:webgen:proj-demo",
                    origin_session_key="agent:main:discord:dm:buddy",
                    delivery_strategy="rebroadcast",
                    status="done",
                    phase="done",
                    final_delivered=True,
                    final_summary="✅ 已完成最终交付",
                ),
            )

            payload = module.resolve_watch_action(
                session_key="agent:webgen:proj-demo",
                state_file=state_file,
                watch_id="watch-demo",
                origin_session_key="agent:main:discord:dm:buddy",
                delivery_strategy="auto",
                supports_hidden_wake=False,
                supports_sessions_send=True,
            )

        self.assertEqual(payload["status"], "idle")

    def test_resolve_watch_action_resumes_waiting_user_watch_when_supervisor_is_stale(self) -> None:
        module = load_ensure_live_watch_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "watch-demo.json"
            save_watch_state(
                state_file,
                WatchState(
                    watch_id="watch-demo",
                    target_session_key="agent:webgen:proj-demo",
                    origin_session_key="agent:main:discord:dm:buddy",
                    delivery_strategy="rebroadcast",
                    status="running",
                    phase="waiting_user",
                    final_delivered=True,
                    final_summary="❓ 需要澄清：请确认页面范围",
                    supervisor_pid=4321,
                    supervisor_started_at=40.0,
                    supervisor_heartbeat_at=50.0,
                ),
            )

            payload = module.resolve_watch_action(
                session_key="agent:webgen:proj-demo",
                state_file=state_file,
                watch_id="watch-demo",
                origin_session_key="agent:main:discord:dm:buddy",
                delivery_strategy="auto",
                supports_hidden_wake=False,
                supports_sessions_send=True,
                now=100.0,
            )

        self.assertEqual(payload["status"], "resume")
        self.assertEqual(payload["reason"], "supervisor_inactive")

    def test_main_dry_run_json_outputs_resume_payload(self) -> None:
        module = load_ensure_live_watch_module()

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

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = module.main(
                    [
                        "--session-key",
                        "agent:webgen:proj-demo",
                        "--state-file",
                        str(state_file),
                        "--watch-id",
                        "watch-demo",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["status"], "resume")
        self.assertEqual(payload["watchId"], "watch-demo")


if __name__ == "__main__":
    unittest.main()
