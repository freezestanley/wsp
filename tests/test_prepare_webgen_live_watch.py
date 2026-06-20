import importlib.util
import tempfile
import unittest
from pathlib import Path


def load_prepare_webgen_live_watch_module():
    module_path = Path(__file__).resolve().parent.parent / "runtime" / "prepare-webgen-live-watch.py"
    spec = importlib.util.spec_from_file_location("prepare_webgen_live_watch_script", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load runtime/prepare-webgen-live-watch.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PrepareWebgenLiveWatchTests(unittest.TestCase):
    def test_resolve_prepared_watch_uses_explicit_session_key_without_resume_lookup(self) -> None:
        module = load_prepare_webgen_live_watch_module()
        self.assertTrue(
            hasattr(module, "resolve_prepared_watch"),
            "resolve_prepared_watch must be implemented",
        )

        called = False

        def fake_resume(_message: str) -> dict[str, str | bool]:
            nonlocal called
            called = True
            return {"matched": False, "reason": "should-not-run"}

        payload = module.resolve_prepared_watch(
            message="给 webgen 做个新页面",
            session_key="agent:webgen:proj-demo",
            slug="",
            origin_session_key="agent:main:discord:dm:buddy",
            delivery_strategy="auto",
            supports_hidden_wake=False,
            supports_sessions_send=True,
            resume_resolver=fake_resume,
            ensure_resolver=lambda **kwargs: {
                "status": "start",
                "watchId": "watch-demo",
                "targetSessionKey": kwargs["session_key"],
            },
        )

        self.assertFalse(called)
        self.assertEqual(payload["targetSessionKey"], "agent:webgen:proj-demo")
        self.assertEqual(payload["routing"]["mode"], "direct-session")
        self.assertEqual(payload["watch"]["status"], "start")

    def test_resolve_prepared_watch_uses_deterministic_resume_match(self) -> None:
        module = load_prepare_webgen_live_watch_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = str(Path(tmpdir) / "watch-demo.json")

            payload = module.resolve_prepared_watch(
                message="继续改 projects/gshock-site",
                session_key="",
                slug="",
                origin_session_key="agent:main:discord:dm:buddy",
                delivery_strategy="auto",
                supports_hidden_wake=False,
                supports_sessions_send=True,
                state_file=state_file,
                resume_resolver=lambda _message: {
                    "matched": True,
                    "slug": "gshock-site",
                    "sessionKey": "agent:webgen:proj-gshock-site",
                    "mode": "resume:gshock-site",
                },
                ensure_resolver=lambda **kwargs: {
                    "status": "resume",
                    "watchId": "watch-gshock-site",
                    "targetSessionKey": kwargs["session_key"],
                    "stateFile": kwargs["state_file"],
                },
            )

        self.assertEqual(payload["targetSessionKey"], "agent:webgen:proj-gshock-site")
        self.assertEqual(payload["routing"]["mode"], "resume:gshock-site")
        self.assertTrue(payload["routing"]["resumeMatched"])
        self.assertEqual(payload["watch"]["status"], "resume")
        self.assertEqual(payload["watch"]["stateFile"], state_file)

    def test_resolve_prepared_watch_falls_back_to_new_project_slug_when_resume_unmatched(self) -> None:
        module = load_prepare_webgen_live_watch_module()

        payload = module.resolve_prepared_watch(
            message="做个新官网",
            session_key="",
            slug="brand-site",
            origin_session_key="agent:main:discord:dm:buddy",
            delivery_strategy="auto",
            supports_hidden_wake=False,
            supports_sessions_send=True,
            resume_resolver=lambda _message: {
                "matched": False,
                "reason": "no-deterministic-project-match",
            },
            ensure_resolver=lambda **kwargs: {
                "status": "start",
                "watchId": "watch-brand-site",
                "targetSessionKey": kwargs["session_key"],
            },
        )

        self.assertEqual(payload["targetSessionKey"], "agent:webgen:proj-brand-site")
        self.assertEqual(payload["routing"]["mode"], "new:brand-site")
        self.assertFalse(payload["routing"]["resumeMatched"])
        self.assertEqual(payload["watch"]["status"], "start")

    def test_resolve_prepared_watch_returns_unresolved_when_no_resume_and_no_target(self) -> None:
        module = load_prepare_webgen_live_watch_module()

        payload = module.resolve_prepared_watch(
            message="继续改上次那个项目",
            session_key="",
            slug="",
            origin_session_key="agent:main:discord:dm:buddy",
            delivery_strategy="auto",
            supports_hidden_wake=False,
            supports_sessions_send=True,
            resume_resolver=lambda _message: {
                "matched": False,
                "reason": "no-deterministic-project-match",
            },
            ensure_resolver=lambda **kwargs: {
                "status": "start",
                "watchId": "should-not-run",
                "targetSessionKey": kwargs["session_key"],
            },
        )

        self.assertEqual(payload["status"], "unresolved")
        self.assertEqual(payload["reason"], "no_target_session")
        self.assertNotIn("watch", payload)


if __name__ == "__main__":
    unittest.main()
