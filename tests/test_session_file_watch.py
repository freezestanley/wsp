import json
import os
import tempfile
import unittest
from pathlib import Path


from runtime import session_file_watch


class SessionFileWatchTests(unittest.TestCase):
    def test_resolve_session_file_path_prefers_session_file_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            sessions_dir = root / "agents" / "webgen" / "sessions"
            sessions_dir.mkdir(parents=True)
            explicit_path = sessions_dir / "custom.jsonl"
            (sessions_dir / "sessions.json").write_text(
                json.dumps(
                    {
                        "agent:webgen:proj-demo": {
                            "sessionFile": str(explicit_path),
                            "sessionId": "ignored-id",
                        }
                    }
                ),
                encoding="utf-8",
            )

            resolved = session_file_watch.resolve_session_file_path(
                "agent:webgen:proj-demo",
                root=root,
            )

        self.assertEqual(resolved, explicit_path)

    def test_resolve_session_file_path_falls_back_to_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            sessions_dir = root / "agents" / "webgen" / "sessions"
            sessions_dir.mkdir(parents=True)
            (sessions_dir / "sessions.json").write_text(
                json.dumps(
                    {
                        "agent:webgen:proj-demo": {
                            "sessionId": "abc-123",
                        }
                    }
                ),
                encoding="utf-8",
            )

            resolved = session_file_watch.resolve_session_file_path(
                "agent:webgen:proj-demo",
                root=root,
            )

        self.assertEqual(resolved, sessions_dir / "abc-123.jsonl")

    def test_resolve_session_file_path_returns_none_when_session_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            sessions_dir = root / "agents" / "webgen" / "sessions"
            sessions_dir.mkdir(parents=True)
            (sessions_dir / "sessions.json").write_text(
                json.dumps({}),
                encoding="utf-8",
            )

            resolved = session_file_watch.resolve_session_file_path(
                "agent:webgen:proj-demo",
                root=root,
            )

        self.assertIsNone(resolved)

    def test_sample_session_file_returns_missing_sample_for_absent_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "missing.jsonl"

            sample = session_file_watch.sample_session_file(path)

        self.assertEqual(sample.path, path)
        self.assertFalse(sample.exists)
        self.assertEqual(sample.size, 0)
        self.assertEqual(sample.mtime, 0.0)
        self.assertEqual(sample.inode, 0)

    def test_sample_session_file_returns_file_metadata_for_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "session.jsonl"
            path.write_text('{"hello":"world"}\n', encoding="utf-8")

            sample = session_file_watch.sample_session_file(path)

        self.assertEqual(sample.path, path)
        self.assertTrue(sample.exists)
        self.assertGreater(sample.size, 0)
        self.assertGreater(sample.mtime, 0.0)
        self.assertGreater(sample.inode, 0)

    def test_detect_session_file_change_recognizes_metadata_changes(self) -> None:
        baseline = session_file_watch.SessionFileSample(
            path=Path("/tmp/demo.jsonl"),
            exists=True,
            mtime=10.0,
            size=100,
            inode=1,
            sampled_at=20.0,
        )
        changed_size = session_file_watch.SessionFileSample(
            path=Path("/tmp/demo.jsonl"),
            exists=True,
            mtime=10.0,
            size=120,
            inode=1,
            sampled_at=21.0,
        )
        changed_inode = session_file_watch.SessionFileSample(
            path=Path("/tmp/demo.jsonl"),
            exists=True,
            mtime=10.0,
            size=100,
            inode=2,
            sampled_at=21.0,
        )
        changed_exists = session_file_watch.SessionFileSample(
            path=Path("/tmp/demo.jsonl"),
            exists=False,
            mtime=0.0,
            size=0,
            inode=0,
            sampled_at=21.0,
        )

        self.assertTrue(session_file_watch.detect_session_file_change(baseline, changed_size))
        self.assertTrue(session_file_watch.detect_session_file_change(baseline, changed_inode))
        self.assertTrue(session_file_watch.detect_session_file_change(baseline, changed_exists))
        self.assertFalse(session_file_watch.detect_session_file_change(baseline, baseline))


if __name__ == "__main__":
    unittest.main()
