import tempfile
import unittest
from pathlib import Path
from unittest import mock

import core.platform.gpu as gpu
import core.stages.submit as submit


class GpuTaskParsingTest(unittest.TestCase):
    def test_parse_index_rows_with_gpu_mode(self):
        rows = """
        <tr><td>Factor_gpu_restest_AG_AU_HALF_AG</td><td>[GPU] ridge_svd (AG/AU, 一年)</td>
        <td><a href="https://airflow.example/dags/GenerateXYsGpu/grid?dag_run_id=run-2">run-2</a></td>
        <td>running</td><td>NotReady</td><td>2026-08-20 10:00:00</td></tr>
        <tr><td>Factor_test_SHFE_AG</td><td>csv_ic</td>
        <td><a href="https://airflow.example/dags/GenerateXYsTest/grid?dag_run_id=run-1">run-1</a></td>
        <td>success</td><td><a href="/download_ic?x=1">csv_ic</a></td><td>2026-08-20 09:59:00</td></tr>
        """
        tasks = gpu._parse_tasks(rows)

        self.assertEqual(tasks[0]["feature"], "Factor_gpu_restest_AG_AU_HALF_AG")
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


class GpuEntryUpdateTest(unittest.TestCase):
    def test_gpu_feature_mode_maps_ridge_svd_to_restest(self):
        self.assertEqual(gpu._gpu_feature_mode("ridge_svd"), "restest")
        self.assertEqual(gpu._gpu_feature_mode("restest"), "restest")

    def test_gpu_entry_rejects_removed_csv_ic_mode(self):
        got = gpu.submit_gpu_tasks("/tmp/does-not-exist.h", "Factor<>", ["csv_ic"])

        self.assertFalse(got["ok"])
        self.assertIn("ridge_svd", got["error"])
        self.assertIn("ictest", got["error"])

    def test_post_gpu_uses_new_restest_form_fields(self):
        captured = {}

        class FakeResult:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_run(cmd, capture_output=False, text=False, timeout=None):
            captured["cmd"] = cmd
            return FakeResult()

        with mock.patch.object(gpu.subprocess, "run", side_effect=fake_run):
            gpu._post_gpu("cookie", "/tmp/Factor.h", "Factor<>", "ridge_svd", "formkey")

        fields = {}
        cmd = captured["cmd"]
        for i, token in enumerate(cmd):
            if token == "-F":
                key, value = cmd[i + 1].split("=", 1)
                fields[key] = value

        self.assertEqual(fields["features"], "Factor<>")
        self.assertEqual(fields["alpha"], "0.1")
        self.assertEqual(fields["lib_key"], "AG_AU")
        self.assertEqual(fields["n_workers"], "12")
        self.assertNotIn("mode", fields)
        self.assertNotIn("Feeds", fields)
        self.assertNotIn("start_date", fields)
        self.assertNotIn("end_date", fields)
        self.assertNotIn("date_key", fields)
        self.assertTrue(cmd[-1].endswith("/submit_gpu"))


if __name__ == "__main__":
    unittest.main()
