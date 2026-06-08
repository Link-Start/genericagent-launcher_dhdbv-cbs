from __future__ import annotations

import unittest
from unittest import mock

import updater


class UpdaterEntryTests(unittest.TestCase):
    def test_run_tolerates_missing_stderr_when_job_argument_is_omitted(self):
        with mock.patch.object(updater.sys, "stderr", None):
            exit_code = updater.run([])

        self.assertEqual(exit_code, 2)

    def test_run_tolerates_missing_stdout_for_result_reporting(self):
        for result, expected_code in (
            ({"ok": True, "job_id": "job-1"}, 0),
            ({"ok": False, "job_id": "job-1", "error_code": "ERR_UNEXPECTED"}, 3),
        ):
            with self.subTest(expected_code=expected_code):
                with mock.patch.object(
                    updater, "apply_update_job", return_value=result
                ), mock.patch.object(
                    updater.sys, "stdout", None
                ):
                    exit_code = updater.run(["--job", "job.json"])

                self.assertEqual(exit_code, expected_code)

    def test_run_tolerates_missing_stderr_when_update_job_raises(self):
        with mock.patch.object(
            updater, "apply_update_job", side_effect=RuntimeError("boom")
        ), mock.patch.object(
            updater, "updater_log"
        ) as updater_log, mock.patch.object(
            updater.sys, "stderr", None
        ):
            exit_code = updater.run(["--job", "job.json"])

        self.assertEqual(exit_code, 1)
        updater_log.assert_any_call("[fatal] updater failed: boom")

    def test_run_tolerates_missing_stderr_for_blank_job_argument(self):
        with mock.patch.object(updater.sys, "stderr", None):
            exit_code = updater.run(["--job", " "])

        self.assertEqual(exit_code, 2)


if __name__ == "__main__":
    unittest.main()
