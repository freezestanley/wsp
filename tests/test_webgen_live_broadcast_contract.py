import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


class WebgenLiveBroadcastContractTests(unittest.TestCase):
    def test_agents_forbids_dashboard_routing_for_current_dialog_wake(self) -> None:
        text = _read("AGENTS.md")

        self.assertIn(
            "禁止使用 `sessionTarget:\"main\"` + `payload.kind:\"systemEvent\"` 作为“继续在当前对话里直播”的续航方式。",
            text,
        )
        self.assertIn(
            "若 wake 回合命中 `Cron tool is restricted to the current cron job.`",
            text,
        )

    def test_delegated_live_broadcasting_skill_documents_cron_restricted_strategy(self) -> None:
        text = _read("skills/delegated-live-broadcasting/SKILL.md")

        self.assertIn(
            "禁止使用 `sessionTarget:\"main\"` + `payload.kind:\"systemEvent\"` 来尝试回到当前用户对话继续直播。",
            text,
        )
        self.assertIn(
            "若 wake 回合命中 `Cron tool is restricted to the current cron job.`",
            text,
        )

    def test_webgen_skill_repeats_live_broadcast_guardrails(self) -> None:
        text = _read("skills/webgen/SKILL.md")

        self.assertIn(
            "禁止使用 `sessionTarget:\"main\"` + `payload.kind:\"systemEvent\"` 冒充“回到当前对话继续播报”。",
            text,
        )
        self.assertIn(
            "若当前 wake 回合命中 `Cron tool is restricted to the current cron job.`",
            text,
        )

    def test_migration_doc_records_both_known_failure_modes(self) -> None:
        text = _read("docs/webgen-live-broadcast-migration.md")

        self.assertIn(
            "错误路径一：`sessionTarget:\"main\"` + `payload.kind:\"systemEvent\"` 把 wake 建进 dashboard/background session",
            text,
        )
        self.assertIn(
            "错误路径二：wake 回合命中 `Cron tool is restricted to the current cron job.` 后又错误地再次 `cron.add`",
            text,
        )


if __name__ == "__main__":
    unittest.main()
