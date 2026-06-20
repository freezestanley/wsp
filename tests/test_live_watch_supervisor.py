import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout

from runtime.live_watch import WatchState, load_watch_state, save_watch_state


def load_live_watch_supervisor_module():
    module_path = Path(__file__).resolve().parent.parent / "runtime" / "live-watch-supervisor.py"
    spec = importlib.util.spec_from_file_location("live_watch_supervisor_script", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load runtime/live-watch-supervisor.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LiveWatchSupervisorTests(unittest.TestCase):
    def test_deliver_or_queue_batch_queues_manual_pull_items_without_delivery(self) -> None:
        module = load_live_watch_supervisor_module()

        delivered_batches: list[list[dict[str, object]]] = []
        state = WatchState(
            watch_id="watch-demo",
            target_session_key="agent:webgen:proj-demo",
            delivery_strategy="manual_pull",
            last_delivered_seq=40,
        )

        updated, delivered = module.deliver_or_queue_batch(
            state,
            [{"seq": 41, "summary": "✅ 构建成功"}],
            deliver_batch_fn=lambda batch: delivered_batches.append(batch) or True,
        )

        self.assertFalse(delivered)
        self.assertEqual(delivered_batches, [])
        self.assertEqual(updated.status, "degraded")
        self.assertEqual(updated.pending_count, 1)
        self.assertEqual(updated.pending_broadcast_items, [{"seq": 41, "summary": "✅ 构建成功"}])
        self.assertEqual(updated.last_pending_summary, "✅ 构建成功")
        self.assertEqual(updated.last_delivered_seq, 40)

    def test_deliver_or_queue_batch_advances_last_delivered_seq_on_success(self) -> None:
        module = load_live_watch_supervisor_module()

        delivered_batches: list[list[dict[str, object]]] = []
        state = WatchState(
            watch_id="watch-demo",
            target_session_key="agent:webgen:proj-demo",
            delivery_strategy="rebroadcast",
            last_delivered_seq=40,
        )

        updated, delivered = module.deliver_or_queue_batch(
            state,
            [{"seq": 41, "summary": "✅ 构建成功"}],
            deliver_batch_fn=lambda batch: delivered_batches.append(batch) or True,
        )

        self.assertTrue(delivered)
        self.assertEqual(len(delivered_batches), 1)
        self.assertEqual(updated.pending_count, 0)
        self.assertEqual(updated.pending_broadcast_items, [])
        self.assertEqual(updated.last_delivered_seq, 41)

    def test_deliver_or_queue_batch_does_not_duplicate_existing_backlog(self) -> None:
        module = load_live_watch_supervisor_module()

        state = WatchState(
            watch_id="watch-demo",
            target_session_key="agent:webgen:proj-demo",
            delivery_strategy="manual_pull",
            pending_broadcast_items=[{"seq": 41, "summary": "✅ 构建成功"}],
            pending_count=1,
            last_pending_summary="✅ 构建成功",
        )

        updated, delivered = module.deliver_or_queue_batch(
            state,
            [{"seq": 41, "summary": "✅ 构建成功"}],
            deliver_batch_fn=lambda _batch: True,
        )

        self.assertFalse(delivered)
        self.assertEqual(updated.pending_count, 1)
        self.assertEqual(updated.pending_broadcast_items, [{"seq": 41, "summary": "✅ 构建成功"}])

    def test_process_watch_once_preserves_re_resolved_session_file_and_degrades_on_delivery_failure(self) -> None:
        module = load_live_watch_supervisor_module()

        state = WatchState(
            watch_id="watch-demo",
            target_session_key="agent:webgen:proj-demo",
            delivery_strategy="rebroadcast",
            last_seen_seq=41,
            session_file_path="/tmp/old.jsonl",
        )

        def fake_run_watch_cycle(**kwargs):
            self.assertEqual(kwargs["last_seen"], 41)
            updated_state = kwargs["watch_state"]
            updated_state = updated_state.__class__(
                **{
                    **updated_state.__dict__,
                    "session_file_path": "/tmp/new.jsonl",
                    "last_seen_seq": 42,
                }
            )
            return (
                updated_state,
                42,
                [{"seq": 42, "summary": "🔧 继续验证"}],
                True,
            )

        updated, batch, delivered = module.process_watch_once(
            state,
            now=100.0,
            run_watch_cycle_fn=fake_run_watch_cycle,
            deliver_batch_fn=lambda _batch: False,
        )

        self.assertFalse(delivered)
        self.assertEqual(batch, [{"seq": 42, "summary": "🔧 继续验证"}])
        self.assertEqual(updated.session_file_path, "/tmp/new.jsonl")
        self.assertEqual(updated.pending_count, 1)
        self.assertEqual(updated.status, "degraded")
        self.assertEqual(updated.delivery_degraded_reason, "delivery_failed")

    def test_process_watch_once_uses_default_progress_wrapper_when_not_overridden(self) -> None:
        module = load_live_watch_supervisor_module()

        state = WatchState(
            watch_id="watch-demo",
            target_session_key="agent:webgen:proj-demo",
            delivery_strategy="rebroadcast",
            last_seen_seq=8,
        )

        def fake_progress_watch_cycle(**kwargs):
            self.assertEqual(kwargs["current_session_key"], "agent:webgen:proj-demo")
            return kwargs["watch_state"], 9, [{"seq": 9, "summary": "🔧 继续执行"}], True

        original = module.run_progress_watch_cycle
        module.run_progress_watch_cycle = fake_progress_watch_cycle
        try:
            updated, batch, delivered = module.process_watch_once(
                state,
                now=100.0,
                deliver_batch_fn=lambda _batch: True,
            )
        finally:
            module.run_progress_watch_cycle = original

        self.assertTrue(delivered)
        self.assertEqual(batch, [{"seq": 9, "summary": "🔧 继续执行"}])
        self.assertEqual(updated.last_seen_seq, 9)
        self.assertEqual(updated.last_delivered_seq, 9)

    def test_collect_supervisable_watches_only_returns_nonterminal_states(self) -> None:
        module = load_live_watch_supervisor_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            state_root = Path(tmpdir)
            active_file = state_root / "active.json"
            done_file = state_root / "done.json"
            degraded_file = state_root / "degraded.json"
            save_watch_state(
                active_file,
                WatchState(
                    watch_id="watch-active",
                    target_session_key="agent:webgen:proj-active",
                    status="running",
                    phase="implementing",
                ),
            )
            save_watch_state(
                done_file,
                WatchState(
                    watch_id="watch-done",
                    target_session_key="agent:webgen:proj-done",
                    status="done",
                    phase="done",
                ),
            )
            save_watch_state(
                degraded_file,
                WatchState(
                    watch_id="watch-degraded",
                    target_session_key="agent:webgen:proj-degraded",
                    status="degraded",
                    phase="implementing",
                ),
            )

            collected = module.collect_supervisable_watches(state_root)

        self.assertEqual(
            [(path.name, state.watch_id) for path, state in collected],
            [
                ("active.json", "watch-active"),
                ("degraded.json", "watch-degraded"),
            ],
        )

    def test_claim_supervisor_lock_prevents_second_owner_until_expired(self) -> None:
        module = load_live_watch_supervisor_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            lock_file = Path(tmpdir) / "supervisor.lock"
            claimed_first = module.claim_supervisor_lock(
                lock_file,
                owner="pid-1",
                now=100.0,
                lease_seconds=30.0,
            )
            claimed_second = module.claim_supervisor_lock(
                lock_file,
                owner="pid-2",
                now=110.0,
                lease_seconds=30.0,
            )
            claimed_after_expiry = module.claim_supervisor_lock(
                lock_file,
                owner="pid-2",
                now=131.0,
                lease_seconds=30.0,
            )

        self.assertTrue(claimed_first)
        self.assertFalse(claimed_second)
        self.assertTrue(claimed_after_expiry)

    def test_mark_watch_supervisor_heartbeat_persists_pid_and_timestamp(self) -> None:
        module = load_live_watch_supervisor_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "watch-demo.json"
            save_watch_state(
                state_file,
                WatchState(
                    watch_id="watch-demo",
                    target_session_key="agent:webgen:proj-demo",
                ),
            )

            module.mark_watch_supervisor_heartbeat(
                state_file,
                watch_id="watch-demo",
                pid=4321,
                now=100.0,
                started_at=90.0,
            )
            loaded = load_watch_state(state_file, "watch-demo")

        self.assertEqual(loaded.supervisor_pid, 4321)
        self.assertEqual(loaded.supervisor_started_at, 90.0)
        self.assertEqual(loaded.supervisor_heartbeat_at, 100.0)

    def test_run_supervisor_cycle_processes_nonterminal_watches_and_persists_updates(self) -> None:
        module = load_live_watch_supervisor_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            state_root = Path(tmpdir)
            active_file = state_root / "active.json"
            done_file = state_root / "done.json"
            save_watch_state(
                active_file,
                WatchState(
                    watch_id="watch-active",
                    target_session_key="agent:webgen:proj-active",
                    status="running",
                    phase="implementing",
                    last_seen_seq=40,
                ),
            )
            save_watch_state(
                done_file,
                WatchState(
                    watch_id="watch-done",
                    target_session_key="agent:webgen:proj-done",
                    status="done",
                    phase="done",
                    last_seen_seq=10,
                ),
            )

            processed_watch_ids: list[str] = []

            def fake_process_watch_once(state, *, now, deliver_batch_fn, **_kwargs):
                processed_watch_ids.append(state.watch_id)
                updated = state.__class__(**{**state.__dict__, "last_seen_seq": state.last_seen_seq + 1})
                return updated, [{"seq": 41, "summary": "🔧 执行中"}], True

            payload = module.run_supervisor_cycle(
                state_root,
                now=100.0,
                owner="pid-1",
                lease_seconds=30.0,
                started_at=90.0,
                process_watch_once_fn=fake_process_watch_once,
                deliver_batch_fn=lambda _batch: True,
            )

            loaded_active = load_watch_state(active_file, "watch-active")
            loaded_done = load_watch_state(done_file, "watch-done")

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["processed"], 1)
        self.assertEqual(processed_watch_ids, ["watch-active"])
        self.assertEqual(loaded_active.last_seen_seq, 41)
        self.assertEqual(loaded_active.supervisor_pid, 0)
        self.assertEqual(loaded_active.supervisor_heartbeat_at, 100.0)
        self.assertEqual(loaded_done.last_seen_seq, 10)

    def test_run_supervisor_cycle_skips_when_lock_is_held_by_another_owner(self) -> None:
        module = load_live_watch_supervisor_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            state_root = Path(tmpdir)
            save_watch_state(
                state_root / "active.json",
                WatchState(
                    watch_id="watch-active",
                    target_session_key="agent:webgen:proj-active",
                    status="running",
                    phase="implementing",
                ),
            )
            module.claim_supervisor_lock(
                state_root / "supervisor.lock",
                owner="pid-1",
                now=100.0,
                lease_seconds=30.0,
            )
            called = False

            def fake_process_watch_once(*_args, **_kwargs):
                nonlocal called
                called = True
                raise AssertionError("should not be called while lock is held")

            payload = module.run_supervisor_cycle(
                state_root,
                now=110.0,
                owner="pid-2",
                lease_seconds=30.0,
                started_at=90.0,
                process_watch_once_fn=fake_process_watch_once,
                deliver_batch_fn=lambda _batch: True,
            )

        self.assertEqual(payload["status"], "locked")
        self.assertFalse(called)

    def test_main_once_json_outputs_supervisor_cycle_payload(self) -> None:
        module = load_live_watch_supervisor_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            state_root = Path(tmpdir)
            original = module.run_supervisor_cycle
            module.run_supervisor_cycle = lambda *args, **kwargs: {"status": "ok", "processed": 2}
            buffer = io.StringIO()
            try:
                with redirect_stdout(buffer):
                    exit_code = module.main(
                        [
                            "--state-root",
                            str(state_root),
                            "--once",
                            "--json",
                        ]
                    )
            finally:
                module.run_supervisor_cycle = original

        self.assertEqual(exit_code, 0)
        self.assertEqual(buffer.getvalue().strip(), '{"status": "ok", "processed": 2}')


if __name__ == "__main__":
    unittest.main()
