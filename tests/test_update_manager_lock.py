from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from launcher_core_parts import update_manager


class UpdateManagerLockTests(unittest.TestCase):
    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tempdir.cleanup)
        self.root = self._tempdir.name
        self.updates_dir = os.path.join(self.root, "updates")
        os.makedirs(self.updates_dir, exist_ok=True)
        self.lock_path = os.path.join(self.updates_dir, "update.lock")

    def _launcher_data_path(self, *parts):
        return os.path.join(self.root, *parts)

    def test_update_lock_acquires_and_cleans_up_normally(self):
        with mock.patch.object(update_manager, "launcher_data_path", side_effect=self._launcher_data_path):
            with update_manager._update_lock(timeout_seconds=3) as lock_path:
                self.assertEqual(os.path.normpath(lock_path), os.path.normpath(self.lock_path))
                self.assertTrue(os.path.isfile(lock_path))
                with open(lock_path, "r", encoding="utf-8") as f:
                    self.assertEqual(f.read().strip(), str(os.getpid()))

        self.assertFalse(os.path.exists(self.lock_path))

    def test_update_lock_removes_stale_pid_lock_and_recovers(self):
        with open(self.lock_path, "w", encoding="utf-8") as f:
            f.write("424242")

        with mock.patch.object(update_manager, "launcher_data_path", side_effect=self._launcher_data_path), mock.patch.object(
            update_manager, "_update_lock_owner_running", return_value=False
        ), mock.patch.object(update_manager, "updater_log") as updater_log:
            with update_manager._update_lock(timeout_seconds=3) as lock_path:
                self.assertEqual(os.path.normpath(lock_path), os.path.normpath(self.lock_path))
                with open(lock_path, "r", encoding="utf-8") as f:
                    self.assertEqual(f.read().strip(), str(os.getpid()))

        self.assertFalse(os.path.exists(self.lock_path))
        self.assertTrue(any("removed stale update.lock" in str(call.args[0]) for call in updater_log.call_args_list))

    def test_update_lock_active_owner_still_times_out(self):
        with open(self.lock_path, "w", encoding="utf-8") as f:
            f.write("424242")

        fake_times = iter([100.0, 100.5, 103.2])
        with mock.patch.object(update_manager, "launcher_data_path", side_effect=self._launcher_data_path), mock.patch.object(
            update_manager, "_update_lock_owner_running", return_value=True
        ), mock.patch.object(update_manager.time, "time", side_effect=lambda: next(fake_times)), mock.patch.object(
            update_manager.time, "sleep", return_value=None
        ):
            with self.assertRaises(update_manager.UpdateError) as cm:
                with update_manager._update_lock(timeout_seconds=3):
                    pass

        self.assertEqual(cm.exception.code, update_manager.ERR_LOCK_TIMEOUT)
        self.assertEqual(cm.exception.phase, "prepare")
        self.assertIn("active: pid=424242", cm.exception.detail)
        self.assertTrue(os.path.exists(self.lock_path))

    def test_update_lock_removes_old_malformed_payload_and_recovers(self):
        with open(self.lock_path, "w", encoding="utf-8") as f:
            f.write("{broken")
        stale_time = os.path.getmtime(self.lock_path) - 10
        os.utime(self.lock_path, (stale_time, stale_time))

        with mock.patch.object(update_manager, "launcher_data_path", side_effect=self._launcher_data_path), mock.patch.object(
            update_manager, "updater_log"
        ) as updater_log:
            with update_manager._update_lock(timeout_seconds=3) as lock_path:
                self.assertEqual(os.path.normpath(lock_path), os.path.normpath(self.lock_path))
                with open(lock_path, "r", encoding="utf-8") as f:
                    self.assertEqual(f.read().strip(), str(os.getpid()))

        self.assertFalse(os.path.exists(self.lock_path))
        self.assertTrue(any("invalid lock payload" in str(call.args[0]) for call in updater_log.call_args_list))

    def test_classify_update_lock_keeps_recent_malformed_payload_uncertain(self):
        with open(self.lock_path, "w", encoding="utf-8") as f:
            f.write("{broken")
        os.utime(self.lock_path, (100.0, 100.0))

        with mock.patch.object(update_manager.time, "time", return_value=101.0):
            state, detail = update_manager._classify_update_lock(self.lock_path)

        self.assertEqual(state, "uncertain")
        self.assertEqual(detail, "lock payload not ready")

    def test_update_lock_stale_cleanup_failure_times_out_with_detail(self):
        with open(self.lock_path, "w", encoding="utf-8") as f:
            f.write("424242")

        fake_times = iter([100.0, 100.5, 103.2])
        with mock.patch.object(update_manager, "launcher_data_path", side_effect=self._launcher_data_path), mock.patch.object(
            update_manager, "_classify_update_lock", return_value=("stale", "pid=424242 not running")
        ), mock.patch.object(update_manager.os, "remove", side_effect=PermissionError("denied")), mock.patch.object(
            update_manager.time, "time", side_effect=lambda: next(fake_times)
        ), mock.patch.object(update_manager.time, "sleep", return_value=None):
            with self.assertRaises(update_manager.UpdateError) as cm:
                with update_manager._update_lock(timeout_seconds=3):
                    pass

        self.assertEqual(cm.exception.code, update_manager.ERR_LOCK_TIMEOUT)
        self.assertIn("stale cleanup failed", cm.exception.detail)
        self.assertIn("denied", cm.exception.detail)
        self.assertTrue(os.path.exists(self.lock_path))

    def test_windows_owner_probe_treats_invalid_pid_as_not_running(self):
        class FakeKernel32:
            def OpenProcess(self, _access, _inherit, _pid):
                return 0

            def GetLastError(self):
                return 87

            def GetExitCodeProcess(self, _handle, _code):
                return 0

            def CloseHandle(self, _handle):
                return 1

        import ctypes

        with mock.patch.object(update_manager.os, "name", "nt"), mock.patch.object(
            ctypes, "WinDLL", return_value=FakeKernel32(), create=True
        ), mock.patch.object(ctypes, "get_last_error", return_value=0, create=True), mock.patch.object(
            ctypes, "set_last_error", return_value=None, create=True
        ):
            self.assertFalse(update_manager._update_lock_owner_running(424242))

    def test_launch_update_job_records_preflight_lock_failure(self):
        job = {
            "job_id": "job-preflight",
            "target_version": "1.2.4",
            "package_url": "https://example.com/update.zip",
            "package_sha256": "a" * 64,
            "status": "queued",
            "phase": "queued",
            "error_code": "",
            "error_detail": "",
        }
        job_path = os.path.join(self.updates_dir, "job-preflight.json")
        update_manager._atomic_write_json(job_path, job)
        err = update_manager.UpdateError(
            update_manager.ERR_LOCK_TIMEOUT,
            "更新锁等待超时",
            phase="prepare",
            detail="uncertain: pid=424242 status unknown",
        )

        with mock.patch.object(update_manager, "_update_lock", side_effect=err), mock.patch.object(
            update_manager, "launch_installed_updater"
        ) as launch_installed:
            with self.assertRaises(update_manager.UpdateError):
                update_manager.launch_update_job(job_path)

        launch_installed.assert_not_called()
        payload = update_manager._read_json_file(job_path, {})
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["phase"], "prepare")
        self.assertEqual(payload["error_code"], update_manager.ERR_LOCK_TIMEOUT)
        self.assertIn("uncertain: pid=424242", payload["error_detail"])

    def test_launch_update_job_records_missing_updater_failure(self):
        job = {
            "job_id": "job-launch",
            "target_version": "1.2.4",
            "package_url": "https://example.com/update.zip",
            "package_sha256": "a" * 64,
            "status": "queued",
            "phase": "queued",
            "error_code": "",
            "error_detail": "",
        }
        job_path = os.path.join(self.updates_dir, "job-launch.json")
        update_manager._atomic_write_json(job_path, job)

        with mock.patch.object(update_manager, "_update_lock") as update_lock, mock.patch.object(
            update_manager, "launch_installed_updater", side_effect=FileNotFoundError("Updater.exe 不存在")
        ):
            update_lock.return_value.__enter__.return_value = self.lock_path
            update_lock.return_value.__exit__.return_value = False
            with self.assertRaises(FileNotFoundError):
                update_manager.launch_update_job(job_path)

        payload = update_manager._read_json_file(job_path, {})
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["phase"], "launch")
        self.assertEqual(payload["error_code"], update_manager.ERR_UPDATER_LAUNCH)
        self.assertIn("Updater.exe 不存在", payload["error_detail"])

    def test_launch_update_job_records_successful_updater_handoff(self):
        job = {
            "job_id": "job-handoff",
            "target_version": "1.2.4",
            "package_url": "https://example.com/update.zip",
            "package_sha256": "a" * 64,
            "status": "queued",
            "phase": "queued",
            "error_code": "",
            "error_detail": "",
        }
        job_path = os.path.join(self.updates_dir, "job-handoff.json")
        update_manager._atomic_write_json(job_path, job)

        with mock.patch.object(update_manager, "_update_lock") as update_lock, mock.patch.object(
            update_manager, "launch_installed_updater", return_value=object()
        ) as launch_installed, mock.patch.object(update_manager, "updater_log") as updater_log:
            update_lock.return_value.__enter__.return_value = self.lock_path
            update_lock.return_value.__exit__.return_value = False
            update_manager.launch_update_job(job_path)

        launch_installed.assert_called_once_with(job_path)
        payload = update_manager._read_json_file(job_path, {})
        self.assertEqual(payload["status"], "handoff")
        self.assertEqual(payload["phase"], "updater-launched")
        self.assertEqual(payload["error_code"], "")
        self.assertGreater(float(payload.get("handoff_at") or 0.0), 0.0)
        self.assertTrue(any("updater handoff launched" in str(call.args[0]) for call in updater_log.call_args_list))

    def test_signed_release_metadata_uses_internal_install_mode(self):
        release = {
            "tag_name": "v1.2.4",
            "html_url": "https://github.com/example/launcher/releases/tag/v1.2.4",
            "body": "notes",
            "assets": [
                {
                    "name": "manifest.json",
                    "browser_download_url": "https://example.com/manifest.json",
                },
                {
                    "name": "launcher-update-1.2.4.zip",
                    "browser_download_url": "https://example.com/launcher-update-1.2.4.zip",
                },
            ],
        }
        manifest = (
            b'{"version":"1.2.4","channel":"stable",'
            b'"signature":"signed",'
            b'"package":{"name":"launcher-update-1.2.4.zip","sha256":"'
            + (b"a" * 64)
            + b'"},'
            b'"security":{"health_min_alive_seconds":7,"health_startup_timeout_seconds":30}}'
        )

        with mock.patch.object(update_manager, "_fetch_text", return_value=manifest), mock.patch.object(
            update_manager, "verify_manifest_signature"
        ) as verify_signature:
            info = update_manager._release_to_launcher_update_info(
                release,
                public_key_pem="-----BEGIN PUBLIC KEY-----\nabc\n-----END PUBLIC KEY-----",
            )

        verify_signature.assert_called_once_with(
            manifest,
            "signed",
            "-----BEGIN PUBLIC KEY-----\nabc\n-----END PUBLIC KEY-----",
        )
        self.assertEqual(info["install_mode"], "internal")
        self.assertEqual(info["target_version"], "1.2.4")
        self.assertEqual(info["package_url"], "https://example.com/launcher-update-1.2.4.zip")
        self.assertEqual(info["package_sha256"], "a" * 64)
        self.assertEqual(info["health_min_alive_seconds"], 7)
        self.assertEqual(info["health_startup_timeout_seconds"], 30)


if __name__ == "__main__":
    unittest.main()
