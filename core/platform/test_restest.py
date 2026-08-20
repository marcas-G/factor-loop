import threading
import time
import unittest
from unittest import mock
from pathlib import Path
from tempfile import TemporaryDirectory

import core.platform.restest as restest


class RestestSubmitLockTest(unittest.TestCase):
    def test_submit_critical_section_is_serialized(self):
        with TemporaryDirectory() as tmp:
            restest.SUBMIT_LOCK_FILE = str(Path(tmp) / "restest.lock")

            active = 0
            max_active = 0
            lock = threading.Lock()

            @restest._serialize_submit
            def submit(item):
                nonlocal active, max_active
                with lock:
                    active += 1
                    max_active = max(max_active, active)
                time.sleep(0.05)
                with lock:
                    active -= 1
                return {"item": item}

            threads = [
                threading.Thread(target=submit, args=(item,))
                for item in range(4)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(max_active, 1)

    def test_submit_lock_is_released_after_exception(self):
        with TemporaryDirectory() as tmp:
            restest.SUBMIT_LOCK_FILE = str(Path(tmp) / "restest.lock")

            @restest._serialize_submit
            def fail():
                raise RuntimeError("submit failed")

            with self.assertRaises(RuntimeError):
                fail()

            @restest._serialize_submit
            def succeed():
                return {"ok": True}
            self.assertEqual(succeed(), {"ok": True})


class RestestPostDiagnosticsTest(unittest.TestCase):
    def test_post_submit_captures_curl_metadata(self):
        result = mock.Mock(returncode=28, stdout="body\n__CURL_META__000 https://example.invalid/submit", stderr="connection timeout")
        with TemporaryDirectory() as tmp, mock.patch.object(restest.subprocess, "run", return_value=result) as run:
            got = restest._post_submit("cookie", "https://example.invalid", str(Path(tmp) / "f.h"), "Factor")

        cmd = run.call_args.args[0]
        self.assertEqual(cmd[-1], "https://example.invalid")
        self.assertFalse(got["ok"])
        self.assertEqual(got["returncode"], 28)
        self.assertEqual(got["http_code"], "000")
        self.assertEqual(got["effective_url"], "https://example.invalid/submit")
        self.assertEqual(got["stderr"], "connection timeout")
        self.assertEqual(got["html"], "body")

    def test_transport_failure_fails_before_task_appear_poll(self):
        form_html = '<input name="_formkey" value="abc123">'
        post = {
            "ok": False, "html": "", "returncode": 28, "stderr": "timeout",
            "http_code": "000", "effective_url": "https://example.invalid/submit_restest",
        }
        with TemporaryDirectory() as tmp:
            factor_file = Path(tmp) / "Factor.h"
            factor_file.write_text("class Factor {};", encoding="utf-8")
            with mock.patch.object(restest, "SUBMIT_LOCK_FILE", str(Path(tmp) / "restest.lock")), \
                 mock.patch.object(restest, "TASK_APPEAR_TIMEOUT_SEC", 300), \
                 mock.patch.object(restest, "ensure_cookie", return_value="cookie"), \
                 mock.patch.object(restest, "fetch", return_value=form_html), \
                 mock.patch.object(restest, "_post_submit", return_value=post), \
                 mock.patch.object(restest.time, "sleep") as sleep:
                got = restest.submit_restest(str(factor_file), "Factor")

        self.assertFalse(got["ok"])
        self.assertIn("restest POST 未成功", got["error"])
        self.assertIn("rc=28", got["error"])
        sleep.assert_not_called()



if __name__ == "__main__":
    unittest.main()
