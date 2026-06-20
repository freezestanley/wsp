import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from runtime.live_watch import WatchState, save_watch_state


def load_rechain_watch_module():
    module_path = Path(__file__).resolve().parent.parent / "runtime" / "rechain-watch.py"
    spec = importlib.util.spec_from_file_location("rechain_watch_script", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load runtime/rechain-watch.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RechainWatchTests(unittest.TestCase):
    def test_resolve_rechain_invocation_returns_none_when_state_not_pending(self) -> None:
        module = load_rechain_watch_module()
        self.assertTrue(
            hasattr(module, "resolve_rechain_invocation"),
            "resolve_rechain_invocation must be implemented",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "watch-demo.json"
            save_watch_state(
                state_file,
                WatchState(
                    watch_id="watch-demo",
                    target_session_key="agent:webgen:proj-demo",
                ),
            )

            invocation = module.resolve_rechain_invocation(
                state_file=state_file,
                watch_id="watch-demo",
            )

        self.assertIsNone(invocation)

    def test_resolve_rechain_invocation_reads_resume_spec_from_state(self) -> None:
        module = load_rechain_watch_module()
        self.assertTrue(
            hasattr(module, "resolve_rechain_invocation"),
            "resolve_rechain_invocation must be implemented",
        )

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

            invocation = module.resolve_rechain_invocation(
                state_file=state_file,
                watch_id="watch-demo",
            )

        self.assertIsNotNone(invocation)
        assert invocation is not None
        self.assertEqual(invocation["reason"], "♻️ cron 受限：当前回合只能操作当前 cron job，已标记待补链。")
        self.assertEqual(invocation["command"][0], "python3")
        self.assertEqual(invocation["env"], {"OPENCLAW_ORIGIN_SESSION_KEY": "agent:main:discord:dm:buddy"})

    def test_main_dry_run_json_outputs_invocation(self) -> None:
        module = load_rechain_watch_module()

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
                        "--state-file",
                        str(state_file),
                        "--watch-id",
                        "watch-demo",
                        "--dry-run",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["status"], "ready")
        self.assertTrue(payload["legacy"])
        self.assertEqual(payload["recommendedEntry"], "runtime/ensure-live-watch.py")
        self.assertEqual(payload["invocation"]["command"][0], "python3")
        self.assertEqual(
            payload["invocation"]["env"],
            {"OPENCLAW_ORIGIN_SESSION_KEY": "agent:main:discord:dm:buddy"},
        )

    def test_main_ok_if_idle_json_returns_noop_payload(self) -> None:
        module = load_rechain_watch_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "watch-demo.json"
            save_watch_state(
                state_file,
                WatchState(
                    watch_id="watch-demo",
                    target_session_key="agent:webgen:proj-demo",
                ),
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = module.main(
                    [
                        "--state-file",
                        str(state_file),
                        "--watch-id",
                        "watch-demo",
                        "--ok-if-idle",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["status"], "idle")
        self.assertTrue(payload["legacy"])
        self.assertEqual(payload["recommendedEntry"], "runtime/ensure-live-watch.py")
        self.assertEqual(payload["watchId"], "watch-demo")

    def test_main_dry_run_json_wraps_payload_with_resumed_status(self) -> None:
        module = load_rechain_watch_module()

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
                        "--state-file",
                        str(state_file),
                        "--watch-id",
                        "watch-demo",
                        "--dry-run",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["status"], "ready")
        self.assertTrue(payload["legacy"])
        self.assertEqual(payload["watchId"], "watch-demo")
        self.assertEqual(payload["invocation"]["command"][0], "python3")


if __name__ == "__main__":
    unittest.main()
