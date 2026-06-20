import importlib.util
import unittest
from pathlib import Path


def load_rechain_watch_once_module():
    module_path = Path(__file__).resolve().parent.parent / "runtime" / "rechain-watch-once.py"
    spec = importlib.util.spec_from_file_location("rechain_watch_once_script", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load runtime/rechain-watch-once.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RechainWatchOnceTests(unittest.TestCase):
    def test_normalize_args_adds_ok_if_idle_when_missing(self) -> None:
        module = load_rechain_watch_once_module()
        self.assertTrue(
            hasattr(module, "normalize_args"),
            "normalize_args must be implemented",
        )

        args = module.normalize_args(
            [
                "--state-file",
                "/tmp/watch-demo.json",
                "--watch-id",
                "watch-demo",
            ]
        )

        self.assertIn("--ok-if-idle", args)

    def test_normalize_args_does_not_duplicate_ok_if_idle(self) -> None:
        module = load_rechain_watch_once_module()

        args = module.normalize_args(
            [
                "--state-file",
                "/tmp/watch-demo.json",
                "--watch-id",
                "watch-demo",
                "--ok-if-idle",
            ]
        )

        self.assertEqual(args.count("--ok-if-idle"), 1)


if __name__ == "__main__":
    unittest.main()
