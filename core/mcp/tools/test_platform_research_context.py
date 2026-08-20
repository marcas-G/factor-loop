import unittest
from unittest.mock import patch
from contextlib import contextmanager

from core.mcp.tools import platform as platform_tool


class PlatformResearchContextTest(unittest.TestCase):
    def test_multiple_testing_context_is_saved_into_eval_metrics(self):
        state = {
            "idea_id": 7,
            "run_dir": "/unused",
            "factors": [{"name": "NewImb", "formula": "imb"}, {"name": "NewImb2"}],
        }
        result = {
            "failureLayer": "check_done",
            "summary": "done",
            "evidence": {"eval_metrics": {"core_metrics": {}}},
        }
        saved = {}
        context = {"available": True, "lineage_prior_attempt_count": 2}

        with patch.object(platform_tool, "check_factor_programmatic", return_value=result), \
             patch.object(platform_tool.run_store, "run_load", return_value=state), \
             patch.object(platform_tool, "_attach_research_context", wraps=platform_tool._attach_research_context), \
             patch.object(platform_tool, "build_multiple_testing_context", return_value=context), \
             patch("core.db.db.get_conn", return_value=_fake_conn()), \
             patch.object(platform_tool.run_store, "run_save", side_effect=lambda _run_id, patch: saved.update(patch)):
            output = platform_tool.platform_check_factor(
                "NewImb", {}, "/check", "run-test", 0
            )

        self.assertEqual(output["failureLayer"], "check_done")
        evidence = saved["factors.0.evidence"]
        self.assertEqual(evidence["eval_metrics"]["research_context"], context)

    def test_state_load_failure_does_not_break_check(self):
        result = {
            "failureLayer": "check_done",
            "summary": "done",
            "evidence": {"eval_metrics": {}},
        }

        def fail_load(_run_id):
            raise FileNotFoundError("state missing")

        with patch.object(platform_tool, "check_factor_programmatic", return_value=result), \
             patch.object(platform_tool.run_store, "run_load", side_effect=fail_load), \
             patch.object(platform_tool.run_store, "run_save", return_value={"ok": False}), \
             patch("core.db.db.get_conn", return_value=_fake_conn()):
            output = platform_tool.platform_check_factor(
                "NewImb", {}, "/check", "run-test", 0
            )

        self.assertEqual(output["failureLayer"], "check_done")


@contextmanager
def _fake_conn():
    yield object()


if __name__ == "__main__":
    unittest.main()
