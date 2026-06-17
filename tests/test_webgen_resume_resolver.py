import tempfile
import unittest
from pathlib import Path
import subprocess

try:
    from runtime.webgen_resume_resolver import resolve_resume_target
except ImportError:
    resolve_resume_target = None


def _write_project(projects_root: Path, slug: str, title: str) -> None:
    project_dir = projects_root / slug
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "PROJECT.md").write_text(
        f"# {title}\n\n- `slug`：`{slug}`\n",
        encoding="utf-8",
    )


class WebgenResumeResolverTests(unittest.TestCase):
    def test_matches_explicit_project_directory(self) -> None:
        self.assertIsNotNone(resolve_resume_target, "resolve_resume_target must be implemented")

        with tempfile.TemporaryDirectory() as tmpdir:
            projects_root = Path(tmpdir) / "projects"
            _write_project(projects_root, "gshock-site", "gshock site")

            calls = []

            def fake_route(slug: str) -> dict[str, str]:
                calls.append(slug)
                return {
                    "sessionKey": "agent:webgen:proj-gshock-site",
                    "mode": "resume:gshock-site",
                    "slug": slug,
                }

            result = resolve_resume_target(
                "请继续修改 projects/gshock-site 这个老项目。",
                projects_root=projects_root,
                session_route_resolver=fake_route,
            )

        self.assertEqual(calls, ["gshock-site"])
        self.assertTrue(result["matched"])
        self.assertEqual(result["slug"], "gshock-site")
        self.assertEqual(result["sessionKey"], "agent:webgen:proj-gshock-site")
        self.assertEqual(result["mode"], "resume:gshock-site")
        self.assertEqual(result["source"], "project-dir")

    def test_matches_explicit_slug_reference(self) -> None:
        self.assertIsNotNone(resolve_resume_target, "resolve_resume_target must be implemented")

        with tempfile.TemporaryDirectory() as tmpdir:
            projects_root = Path(tmpdir) / "projects"
            _write_project(projects_root, "admin-dashboard", "Admin Dashboard")

            result = resolve_resume_target(
                "继续改这个老项目，slug: admin-dashboard",
                projects_root=projects_root,
                session_route_resolver=lambda slug: {
                    "sessionKey": f"agent:webgen:proj-{slug}",
                    "mode": f"resume:{slug}",
                    "slug": slug,
                },
            )

        self.assertTrue(result["matched"])
        self.assertEqual(result["slug"], "admin-dashboard")
        self.assertEqual(result["source"], "slug")

    def test_matches_exact_project_name_when_unique(self) -> None:
        self.assertIsNotNone(resolve_resume_target, "resolve_resume_target must be implemented")

        with tempfile.TemporaryDirectory() as tmpdir:
            projects_root = Path(tmpdir) / "projects"
            _write_project(projects_root, "gshock-site", "G-Shock Site")
            _write_project(projects_root, "admin-login", "Admin Login")

            result = resolve_resume_target(
                "请直接续做 G-Shock Site，不要新开项目。",
                projects_root=projects_root,
                session_route_resolver=lambda slug: {
                    "sessionKey": f"agent:webgen:proj-{slug}",
                    "mode": f"resume:{slug}",
                    "slug": slug,
                },
            )

        self.assertTrue(result["matched"])
        self.assertEqual(result["slug"], "gshock-site")
        self.assertEqual(result["source"], "project-name")

    def test_returns_unmatched_without_deterministic_reference(self) -> None:
        self.assertIsNotNone(resolve_resume_target, "resolve_resume_target must be implemented")

        with tempfile.TemporaryDirectory() as tmpdir:
            projects_root = Path(tmpdir) / "projects"
            _write_project(projects_root, "admin-dashboard", "Admin Dashboard")

            called = False

            def fake_route(_slug: str) -> dict[str, str]:
                nonlocal called
                called = True
                return {}

            result = resolve_resume_target(
                "继续改上次那个后台页面。",
                projects_root=projects_root,
                session_route_resolver=fake_route,
            )

        self.assertFalse(called)
        self.assertFalse(result["matched"])
        self.assertEqual(result["reason"], "no-deterministic-project-match")

    def test_returns_unmatched_when_project_name_is_ambiguous(self) -> None:
        self.assertIsNotNone(resolve_resume_target, "resolve_resume_target must be implemented")

        with tempfile.TemporaryDirectory() as tmpdir:
            projects_root = Path(tmpdir) / "projects"
            _write_project(projects_root, "admin-dashboard-a", "Admin Dashboard")
            _write_project(projects_root, "admin-dashboard-b", "Admin Dashboard")

            called = False

            def fake_route(_slug: str) -> dict[str, str]:
                nonlocal called
                called = True
                return {}

            result = resolve_resume_target(
                "继续改 Admin Dashboard。",
                projects_root=projects_root,
                session_route_resolver=fake_route,
            )

        self.assertFalse(called)
        self.assertFalse(result["matched"])
        self.assertEqual(result["reason"], "ambiguous-deterministic-project-match")

    def test_falls_back_to_session_recover_when_resume_registry_is_missing(self) -> None:
        self.assertIsNotNone(resolve_resume_target, "resolve_resume_target must be implemented")

        with tempfile.TemporaryDirectory() as tmpdir:
            projects_root = Path(tmpdir) / "projects"
            _write_project(projects_root, "gshock-site", "gshock site")

            route_calls = []
            recover_calls = []

            def failing_route(slug: str) -> dict[str, str]:
                route_calls.append(slug)
                raise subprocess.CalledProcessError(2, ["sh", "session-route.sh", "envelope", "resume", slug])

            def recover_route(slug: str) -> dict[str, str]:
                recover_calls.append(slug)
                return {
                    "sessionKey": f"agent:webgen:proj-{slug}",
                    "mode": f"resume:{slug}",
                    "slug": slug,
                    "source": "lock",
                }

            result = resolve_resume_target(
                "请继续修改 projects/gshock-site 这个老项目。",
                projects_root=projects_root,
                session_route_resolver=failing_route,
                session_recover_resolver=recover_route,
            )

        self.assertEqual(route_calls, ["gshock-site"])
        self.assertEqual(recover_calls, ["gshock-site"])
        self.assertTrue(result["matched"])
        self.assertEqual(result["sessionKey"], "agent:webgen:proj-gshock-site")
