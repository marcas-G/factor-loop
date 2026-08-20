import tempfile
import unittest
from pathlib import Path
from unittest import mock

import core.platform.gpu as gpu
import core.stages.submit as submit


class GpuTaskParsingTest(unittest.TestCase):
    def test_parse_index_rows_with_gpu_mode(self):
        rows = """
        <tr><td>Factor_gpu_restest_AG_AU_YEAR_AG</td><td>[GPU] ridge_svd (AG/AU, 一年)</td>
        <td><a href="https://airflow.example/dags/GenerateXYsGpu/grid?dag_run_id=run-2">run-2</a></td>
        <td>running</td><td>NotReady</td><td>2026-08-20 10:00:00</td></tr>
        <tr><td>Factor_test_SHFE_AG</td><td>csv_ic</td>
        <td><a href="https://airflow.example/dags/GenerateXYsTest/grid?dag_run_id=run-1">run-1</a></td>
        <td>success</td><td><a href="/download_ic?x=1">csv_ic</a></td><td>2026-08-20 09:59:00</td></tr>
        """
        tasks = gpu._parse_tasks(rows)

        self.assertEqual(tasks[0]["feature"], "Factor_gpu_restest_AG_AU_YEAR_AG")
        self.assertEqual(tasks[0]["mode"], "[GPU] ridge_svd (AG/AU, 一年)")
        self.assertEqual(tasks[0]["job_id"], "run-2")
        self.assertEqual(tasks[1]["feature"], "Factor_test_SHFE_AG")
        self.assertEqual(tasks[1]["job_id"], "run-1")


class SubmitRoutingTest(unittest.TestCase):
    def test_platform_submit_routes_cpu_csv_and_gpu_ridge_together(self):
        tasks = {
            "csv_ic": {"feature": "Factor_test_AG", "engine": "cpu"},
            "ridge_svd": {"feature": "Factor_gpu_restest_AG", "engine": "gpu"},
        }
        result = {
            "ok": True,
            "engines": {"csv_ic": "cpu", "ridge_svd": "gpu"},
            "tasks": tasks,
        }
        with tempfile.TemporaryDirectory() as tmp:
            factor_file = Path(tmp) / "Factor.h"
            factor_file.write_text("class Factor : public FeedIndicator {};", encoding="utf-8")
            with mock.patch.object(submit, "submit_csv_and_gpu_ridge", return_value=result) as paired:
                got = submit.submit_factor_programmatic(
                    {"name": "Factor", "categories": ["AG", "CU"]},
                    str(factor_file),
                )

        paired.assert_called_once_with(
            str(factor_file), "Factor",
            "SHFE-AG,SHFE-AG@1,SHFE-CU,SHFE-CU@1",
        )
        self.assertTrue(got["ok"])
        self.assertEqual(got["tasks"], tasks)
        self.assertEqual(got["engines"]["csv_ic"], "cpu")
        self.assertEqual(got["engines"]["ridge_svd"], "gpu")


if __name__ == "__main__":
    unittest.main()
