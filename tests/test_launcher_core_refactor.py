from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import launcher_bootstrap
from launcher_app import core as lz
from launcher_app import window as launcher_window
from launcher_core_parts import constants
from launcher_core_parts import model_api, runtime
from qt_chat_parts import api_editor
from qt_chat_parts import bridge_runtime
from qt_chat_parts.api_editor import ApiEditorMixin
from qt_chat_parts.bridge_runtime import BridgeRuntimeMixin
from qt_chat_parts import channel_runtime
from qt_chat_parts import personal_usage
from qt_chat_parts import schedule_runtime
from qt_chat_parts import settings_panel
from qt_chat_parts import session_shell
from qt_chat_parts import sidebar_sessions
from qt_chat_parts.downloads import DownloadMixin
from qt_chat_parts.navigation import NavigationMixin
from qt_chat_parts.channel_runtime import ChannelRuntimeMixin
from qt_chat_parts.personal_usage import PersonalUsageMixin
from qt_chat_parts.schedule_runtime import ScheduleRuntimeMixin
from qt_chat_parts.settings_panel import SettingsPanelMixin
from qt_chat_parts.session_shell import SessionShellMixin
from qt_chat_parts.sidebar_sessions import SidebarSessionsMixin


class LauncherCoreFacadeTests(unittest.TestCase):
    @staticmethod
    def _pid_exists(pid: int) -> bool:
        target = int(pid or 0)
        if target <= 0:
            return False
        try:
            os.kill(target, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def test_facade_exports_expected_symbols(self):
        required = [
            "load_config",
            "save_config",
            "_resolve_config_path",
            "_make_config_relative_path",
            "_normalize_token_usage_inplace",
            "terminate_process_tree",
            "list_scheduled_tasks",
            "tail_scheduler_log",
            "fold_turns",
            "serialize_mykey_py",
            "SIMPLE_FORMAT_RULES",
            "qrcode",
            "requests",
            "urlparse",
        ]
        for name in required:
            self.assertTrue(hasattr(lz, name), msg=f"missing symbol: {name}")

    def test_runtime_path_helpers_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            original_app_dir = runtime.APP_DIR
            runtime.APP_DIR = td
            try:
                nested = os.path.join(td, "agent", "launch.pyw")
                os.makedirs(os.path.dirname(nested), exist_ok=True)
                with open(nested, "w", encoding="utf-8") as f:
                    f.write("# test")

                rel = runtime._make_config_relative_path(nested)
                self.assertEqual(rel, os.path.join("agent", "launch.pyw"))

                resolved = runtime._resolve_config_path(rel)
                self.assertEqual(os.path.normpath(resolved), os.path.normpath(nested))
            finally:
                runtime.APP_DIR = original_app_dir

    def test_launcher_version_info_prefers_macos_resources_version_json(self):
        with tempfile.TemporaryDirectory() as td:
            app_dir = os.path.join(td, "GenericAgent Launcher.app", "Contents", "MacOS")
            resources_dir = os.path.join(td, "GenericAgent Launcher.app", "Contents", "Resources")
            os.makedirs(app_dir, exist_ok=True)
            os.makedirs(resources_dir, exist_ok=True)
            with open(os.path.join(app_dir, "version.json"), "w", encoding="utf-8") as f:
                json.dump({"version": "0.9.0", "channel": "stable", "commit": "old", "build_time": "old-time"}, f)
            with open(os.path.join(resources_dir, "version.json"), "w", encoding="utf-8") as f:
                json.dump({"version": "1.2.3", "channel": "stable", "commit": "new", "build_time": "new-time"}, f)

            original_app_dir = runtime.APP_DIR
            runtime.APP_DIR = app_dir
            try:
                with mock.patch.object(runtime, "IS_MACOS", True), mock.patch.object(runtime.sys, "frozen", False, create=True):
                    info = runtime.launcher_version_info()
            finally:
                runtime.APP_DIR = original_app_dir

        self.assertEqual(info["version"], "1.2.3")
        self.assertEqual(info["commit"], "new")

    def test_launcher_version_info_falls_back_to_legacy_macos_version_json(self):
        with tempfile.TemporaryDirectory() as td:
            app_dir = os.path.join(td, "GenericAgent Launcher.app", "Contents", "MacOS")
            os.makedirs(app_dir, exist_ok=True)
            with open(os.path.join(app_dir, "version.json"), "w", encoding="utf-8") as f:
                json.dump({"version": "1.0.1", "channel": "stable", "commit": "legacy", "build_time": "legacy-time"}, f)

            original_app_dir = runtime.APP_DIR
            runtime.APP_DIR = app_dir
            try:
                with mock.patch.object(runtime, "IS_MACOS", True), mock.patch.object(runtime.sys, "frozen", False, create=True):
                    info = runtime.launcher_version_info()
            finally:
                runtime.APP_DIR = original_app_dir

        self.assertEqual(info["version"], "1.0.1")
        self.assertEqual(info["commit"], "legacy")

    def test_macos_installation_status_warns_when_running_from_disk_image(self):
        bundle = f"/Volumes/GenericAgentLauncher/{runtime.APP_DISPLAY_NAME}.app"
        executable = f"{bundle}/Contents/MacOS/GenericAgentLauncher"
        with mock.patch.object(runtime, "IS_MACOS", True), mock.patch.object(
            runtime.sys, "frozen", True, create=True
        ), mock.patch.object(
            runtime, "current_launcher_bundle_path", return_value=bundle
        ), mock.patch.object(
            runtime, "current_launcher_executable_path", return_value=executable
        ), mock.patch.object(
            runtime.os.path, "expanduser", return_value="/Users/tester"
        ):
            info = runtime.macos_installation_status()

        self.assertEqual(info["status"], "warn")
        self.assertTrue(info["running_from_disk_image"])
        self.assertTrue(info["needs_relocation"])
        self.assertIn("dmg", info["summary"])

    def test_macos_installation_status_marks_system_applications_install_as_ok(self):
        bundle = os.path.join("/Applications", f"{runtime.APP_DISPLAY_NAME}.app")
        executable = f"{bundle}/Contents/MacOS/GenericAgentLauncher"
        with mock.patch.object(runtime, "IS_MACOS", True), mock.patch.object(
            runtime.sys, "frozen", True, create=True
        ), mock.patch.object(
            runtime, "current_launcher_bundle_path", return_value=bundle
        ), mock.patch.object(
            runtime, "current_launcher_executable_path", return_value=executable
        ), mock.patch.object(
            runtime.os.path, "expanduser", return_value="/Users/tester"
        ):
            info = runtime.macos_installation_status()

        self.assertEqual(info["status"], "ok")
        self.assertTrue(info["installed_to_system_applications"])
        self.assertFalse(info["needs_relocation"])
        self.assertEqual(info["recommended_install_target"], bundle)

    def test_macos_installation_status_marks_user_applications_install_as_ok(self):
        bundle = f"/Users/tester/Applications/{runtime.APP_DISPLAY_NAME}.app"
        executable = f"{bundle}/Contents/MacOS/GenericAgentLauncher"
        with mock.patch.object(runtime, "IS_MACOS", True), mock.patch.object(
            runtime.sys, "frozen", True, create=True
        ), mock.patch.object(
            runtime, "current_launcher_bundle_path", return_value=bundle
        ), mock.patch.object(
            runtime, "current_launcher_executable_path", return_value=executable
        ), mock.patch.object(
            runtime.os.path, "expanduser", return_value="/Users/tester"
        ):
            info = runtime.macos_installation_status()

        self.assertEqual(info["status"], "ok")
        self.assertTrue(info["installed_to_user_applications"])
        self.assertFalse(info["needs_relocation"])
        self.assertEqual(info["recommended_install_target"], bundle)
        self.assertIn("~/Applications", info["summary"])

    def test_macos_installation_status_warns_when_running_from_app_translocation(self):
        bundle = f"/private/var/folders/test/AppTranslocation/demo/d/{runtime.APP_DISPLAY_NAME}.app"
        executable = f"{bundle}/Contents/MacOS/GenericAgentLauncher"
        with mock.patch.object(runtime, "IS_MACOS", True), mock.patch.object(
            runtime.sys, "frozen", True, create=True
        ), mock.patch.object(
            runtime, "current_launcher_bundle_path", return_value=bundle
        ), mock.patch.object(
            runtime, "current_launcher_executable_path", return_value=executable
        ), mock.patch.object(
            runtime.os.path, "expanduser", return_value="/Users/tester"
        ):
            info = runtime.macos_installation_status()

        self.assertEqual(info["status"], "warn")
        self.assertTrue(info["running_from_translocation"])
        self.assertTrue(info["needs_relocation"])
        self.assertIn("App Translocation", info["summary"])
        self.assertIn("~/Applications", info["summary"])

    def test_build_launcher_external_update_info_keeps_macos_companion_assets(self):
        class DummyUsage(PersonalUsageMixin):
            _build_launcher_external_update_info = PersonalUsageMixin._build_launcher_external_update_info
            _compare_versions = PersonalUsageMixin._compare_versions
            _version_tuple = PersonalUsageMixin._version_tuple

        release = {
            "tag_name": "v1.2.4",
            "html_url": "https://github.com/example/release/v1.2.4",
            "assets": [
                {"name": "GenericAgentLauncher-Setup-1.2.4.exe", "browser_download_url": "https://example.com/Setup.exe"},
                {
                    "name": "GenericAgentLauncher-macos-1.2.4.dmg",
                    "browser_download_url": "https://example.com/GenericAgentLauncher-macos-1.2.4.dmg",
                },
                {
                    "name": "GenericAgentLauncher-macos-1.2.4.sha256",
                    "browser_download_url": "https://example.com/GenericAgentLauncher-macos-1.2.4.sha256",
                },
                {"name": "README-macOS.txt", "browser_download_url": "https://example.com/README-macOS.txt"},
                {"name": "install-metadata.json", "browser_download_url": "https://example.com/install-metadata.json"},
            ],
        }
        dummy = DummyUsage()
        with mock.patch.object(personal_usage.lz, "IS_MACOS", True):
            info = dummy._build_launcher_external_update_info(release, local_version="1.2.3")

        self.assertIsInstance(info, dict)
        self.assertEqual(info["install_mode"], "external")
        self.assertEqual(info["external_asset_name"], "GenericAgentLauncher-macos-1.2.4.dmg")
        self.assertEqual(info["external_url"], "https://example.com/GenericAgentLauncher-macos-1.2.4.dmg")
        self.assertEqual(info["readme_url"], "https://example.com/README-macOS.txt")
        self.assertEqual(info["sha256_url"], "https://example.com/GenericAgentLauncher-macos-1.2.4.sha256")
        self.assertEqual(info["metadata_url"], "https://example.com/install-metadata.json")

    def test_set_agent_dir_triggers_scheduler_autostart_for_valid_agent(self):
        class DummyList:
            def clear(self):
                return None

        class DummyNav(NavigationMixin):
            _set_agent_dir = NavigationMixin._set_agent_dir

            def __init__(self):
                self.agent_dir = ""
                self.cfg = {}
                self.current_session = None
                self._selected_session_id = None
                self._pending_state_session = None
                self._ignore_session_select = False
                self._last_session_list_signature = None
                self.session_list = DummyList()
                self.calls = []
                self.pages = None
                self._settings_page = None

            def _refresh_welcome_state(self):
                self.calls.append("refresh_welcome")

            def _settings_reload(self, categories=None, force=False):
                self.calls.append(("settings_reload", list(categories or []), bool(force)))

            def _schedule_session_index_warmup(self):
                self.calls.append("warmup")

            def _enforce_session_archive_limits(self, refresh=False):
                self.calls.append(("enforce_archive_limits", bool(refresh)))

            def _refresh_sessions(self):
                self.calls.append("refresh_sessions")

            def _schedule_local_channel_autostart(self):
                self.calls.append("autostart_channels")

            def _start_autostart_scheduler(self):
                self.calls.append("autostart_scheduler")

            def _schedule_lan_interface_autostart(self):
                self.calls.append("autostart_lan")

            def _stop_bridge(self):
                self.calls.append("stop_bridge")

            def _stop_all_managed_channels(self, refresh=False):
                self.calls.append(("stop_channels", bool(refresh)))

        dummy = DummyNav()
        with mock.patch.object(lz, "is_valid_agent_dir", return_value=True), mock.patch.object(
            lz, "purge_archived_sessions", return_value=0
        ):
            dummy._set_agent_dir("C:\\demo\\agent", persist=False)

        self.assertEqual(dummy.agent_dir, os.path.abspath("C:\\demo\\agent"))
        self.assertIn("autostart_channels", dummy.calls)
        self.assertIn("autostart_scheduler", dummy.calls)
        self.assertIn("autostart_lan", dummy.calls)
        self.assertLess(dummy.calls.index("autostart_channels"), dummy.calls.index("autostart_scheduler"))
        self.assertLess(dummy.calls.index("autostart_scheduler"), dummy.calls.index("autostart_lan"))

    def test_choose_python_executable_uses_all_files_filter_on_non_windows(self):
        class DummyNav(NavigationMixin):
            _choose_python_executable = NavigationMixin._choose_python_executable

            def __init__(self):
                self.locate_python_edit = mock.Mock()
                self.locate_python_edit.text.return_value = ""

        dummy = DummyNav()
        with mock.patch("qt_chat_parts.navigation.os.name", "posix"), mock.patch(
            "qt_chat_parts.navigation.QFileDialog.getOpenFileName",
            return_value=("/usr/local/bin/python3", "All Files (*)"),
        ) as picker, mock.patch.object(
            lz,
            "_make_config_relative_path",
            side_effect=lambda value: value,
        ):
            dummy._choose_python_executable()

        _args, kwargs = picker.call_args
        self.assertEqual(kwargs, {})
        self.assertEqual(_args[3], "All Files (*)")
        dummy.locate_python_edit.setText.assert_called_once_with("/usr/local/bin/python3")

    def test_notify_reply_done_falls_back_to_status_on_macos_without_tray(self):
        class DummyBridge(BridgeRuntimeMixin):
            _notify_reply_done = BridgeRuntimeMixin._notify_reply_done

            def __init__(self):
                self.cfg = {}
                self.statuses = []
                self.sound_calls = 0

            def _play_reply_done_sound(self):
                self.sound_calls += 1

            def _ensure_reply_notify_tray(self):
                return None

            def _set_status(self, text):
                self.statuses.append(str(text))

        dummy = DummyBridge()
        with mock.patch.object(bridge_runtime.lz, "IS_MACOS", True):
            dummy._notify_reply_done("hello\nworld")

        self.assertEqual(dummy.sound_calls, 1)
        self.assertEqual(dummy.statuses, ["AI 回复已完成：hello world"])

    def test_notify_reply_done_without_tray_keeps_windows_path_unchanged(self):
        class DummyBridge(BridgeRuntimeMixin):
            _notify_reply_done = BridgeRuntimeMixin._notify_reply_done

            def __init__(self):
                self.cfg = {}
                self.statuses = []
                self.sound_calls = 0

            def _play_reply_done_sound(self):
                self.sound_calls += 1

            def _ensure_reply_notify_tray(self):
                return None

            def _set_status(self, text):
                self.statuses.append(str(text))

        dummy = DummyBridge()
        with mock.patch.object(bridge_runtime.lz, "IS_MACOS", False):
            dummy._notify_reply_done("windows stays silent")

        self.assertEqual(dummy.sound_calls, 1)
        self.assertEqual(dummy.statuses, [])

    def test_notify_reply_done_skips_status_when_message_notification_disabled(self):
        class DummyBridge(BridgeRuntimeMixin):
            _notify_reply_done = BridgeRuntimeMixin._notify_reply_done

            def __init__(self):
                self.cfg = {"disable_reply_message": True}
                self.statuses = []
                self.sound_calls = 0

            def _play_reply_done_sound(self):
                self.sound_calls += 1

            def _ensure_reply_notify_tray(self):
                return None

            def _set_status(self, text):
                self.statuses.append(str(text))

        dummy = DummyBridge()
        with mock.patch.object(bridge_runtime.lz, "IS_MACOS", True):
            dummy._notify_reply_done("ignored")

        self.assertEqual(dummy.sound_calls, 1)
        self.assertEqual(dummy.statuses, [])

    def test_notify_reply_done_prefers_tray_message_when_available(self):
        class DummyBridge(BridgeRuntimeMixin):
            _notify_reply_done = BridgeRuntimeMixin._notify_reply_done

            def __init__(self):
                self.cfg = {}
                self.statuses = []
                self.sound_calls = 0

            def _play_reply_done_sound(self):
                self.sound_calls += 1

            def _ensure_reply_notify_tray(self):
                return tray

            def _set_status(self, text):
                self.statuses.append(str(text))

        tray = mock.Mock()
        dummy = DummyBridge()
        with mock.patch.object(bridge_runtime.lz, "IS_MACOS", True):
            dummy._notify_reply_done("tray preview")

        self.assertEqual(dummy.sound_calls, 1)
        self.assertEqual(dummy.statuses, [])
        tray.showMessage.assert_called_once()

    def test_bridge_runtime_state_helpers_explain_attachment_and_llm_disable_reasons(self):
        class DummyBridge(BridgeRuntimeMixin):
            _apply_bridge_widget_state = BridgeRuntimeMixin._apply_bridge_widget_state
            _bridge_attachment_remove_disabled_reason = BridgeRuntimeMixin._bridge_attachment_remove_disabled_reason
            _bridge_llm_combo_disabled_reason = BridgeRuntimeMixin._bridge_llm_combo_disabled_reason
            _sync_llm_combo = BridgeRuntimeMixin._sync_llm_combo

            def __init__(self, llms=None):
                self.llms = list(llms or [])
                self._ignore_llm_change = False
                self.sync_calls = 0
                self.llm_combo = DummyCombo()

            def _sync_floating_llm_combo(self):
                self.sync_calls += 1

        class DummyCombo:
            def __init__(self):
                self.items = []
                self.current_index = -1
                self.enabled = None
                self.tooltip = ""

            def clear(self):
                self.items.clear()
                self.current_index = -1

            def addItem(self, label, data):
                self.items.append((str(label), data))

            def setCurrentIndex(self, index):
                self.current_index = int(index)

            def setEnabled(self, enabled):
                self.enabled = bool(enabled)

            def setToolTip(self, text):
                self.tooltip = str(text)

        dummy = DummyBridge()
        self.assertEqual(
            dummy._bridge_attachment_remove_disabled_reason(active_mode=True),
            "当前这一轮还没有结束；本轮已附带图片会在回复完成后自动清除。",
        )
        self.assertEqual(dummy._bridge_llm_combo_disabled_reason(), "当前还没有可用的 LLM 配置。")
        dummy._sync_llm_combo()
        self.assertEqual(dummy.llm_combo.items, [("未配置 LLM", -1)])
        self.assertFalse(dummy.llm_combo.enabled)
        self.assertEqual(dummy.llm_combo.tooltip, "当前还没有可用的 LLM 配置。")
        self.assertEqual(dummy.sync_calls, 1)

        ready_dummy = DummyBridge(llms=[{"idx": 7, "name": "Claude", "current": True}])
        ready_dummy._sync_llm_combo()
        self.assertEqual(ready_dummy.llm_combo.items, [("Claude", 7)])
        self.assertEqual(ready_dummy.llm_combo.current_index, 0)
        self.assertTrue(ready_dummy.llm_combo.enabled)
        self.assertEqual(ready_dummy.llm_combo.tooltip, "切换当前会话使用的模型。")

    def test_set_agent_dir_stops_lan_interface_when_switching_agent(self):
        class DummyList:
            def clear(self):
                return None

        class DummyNav(NavigationMixin):
            _set_agent_dir = NavigationMixin._set_agent_dir

            def __init__(self):
                self.agent_dir = "C:\\old-agent"
                self.cfg = {}
                self.current_session = None
                self._selected_session_id = None
                self._pending_state_session = None
                self._ignore_session_select = False
                self._last_session_list_signature = None
                self.session_list = DummyList()
                self.calls = []
                self.pages = None
                self._settings_page = None

            def _stop_bridge(self):
                self.calls.append("stop_bridge")

            def _stop_all_managed_channels(self, refresh=False):
                self.calls.append(("stop_channels", bool(refresh)))

            def _stop_scheduler_process(self, refresh=False):
                self.calls.append(("stop_scheduler", bool(refresh)))

            def _stop_lan_interface_process(self, refresh=False):
                self.calls.append(("stop_lan", bool(refresh)))

            def _refresh_welcome_state(self):
                self.calls.append("refresh_welcome")

            def _settings_reload(self, categories=None, force=False):
                self.calls.append(("settings_reload", list(categories or []), bool(force)))

        dummy = DummyNav()
        with mock.patch.object(lz, "is_valid_agent_dir", return_value=False):
            dummy._set_agent_dir("C:\\new-agent", persist=False)

        self.assertIn(("stop_lan", False), dummy.calls)
        self.assertLess(dummy.calls.index(("stop_scheduler", False)), dummy.calls.index(("stop_lan", False)))

    def test_set_agent_dir_clears_scheduler_and_lan_exit_state(self):
        class DummyList:
            def clear(self):
                return None

        class DummyNav(NavigationMixin):
            _set_agent_dir = NavigationMixin._set_agent_dir

            def __init__(self):
                self.agent_dir = "C:\\old-agent"
                self.cfg = {}
                self.current_session = None
                self._selected_session_id = None
                self._pending_state_session = None
                self._ignore_session_select = False
                self._last_session_list_signature = None
                self._scheduler_last_exit_code = 23
                self._lan_interface_last_exit_code = 99
                self.session_list = DummyList()
                self.pages = None
                self._settings_page = None

            def _stop_bridge(self):
                return None

            def _stop_all_managed_channels(self, refresh=False):
                return None

            def _stop_scheduler_process(self, refresh=False):
                return None

            def _stop_lan_interface_process(self, refresh=False):
                return None

            def _refresh_welcome_state(self):
                return None

            def _settings_reload(self, categories=None, force=False):
                return None

        dummy = DummyNav()
        with mock.patch.object(lz, "is_valid_agent_dir", return_value=False):
            dummy._set_agent_dir("C:\\new-agent", persist=False)

        self.assertIsNone(dummy._scheduler_last_exit_code)
        self.assertIsNone(dummy._lan_interface_last_exit_code)

    def test_set_agent_dir_invalidates_remote_settings_load_flags_and_generation(self):
        class DummyList:
            def clear(self):
                return None

        class DummyNav(NavigationMixin):
            _set_agent_dir = NavigationMixin._set_agent_dir

            def __init__(self):
                self.agent_dir = "C:\\old-agent"
                self.cfg = {}
                self.current_session = None
                self._selected_session_id = None
                self._pending_state_session = None
                self._ignore_session_select = False
                self._last_session_list_signature = None
                self._local_channel_autostart_scheduled = True
                self._chat_runtime_bootstrap_pending = True
                self._lan_interface_autostart_scheduled = True
                self._lan_interface_autostart_running = True
                self._qt_api_remote_loading = True
                self._qt_channel_remote_loading = True
                self._settings_personal_remote_sync_running = True
                self._settings_usage_remote_sync_running = True
                self._settings_personal_remote_sync_key = "old-personal"
                self._settings_personal_remote_synced_key = "old-personal-synced"
                self._settings_usage_remote_sync_key = "old-usage"
                self._settings_usage_remote_synced_key = "old-usage-synced"
                self._remote_channel_sync_running = True
                self._remote_launcher_sync_running = True
                self._remote_launcher_sync_pending_force = True
                self._remote_launcher_sync_pending_device_id = "box-1"
                self._remote_launcher_sync_pending_refresh = True
                self._next_remote_launcher_sync_at = 12.3
                self._next_remote_channel_sync_at = 45.6
                self._settings_schedule_remote_reload_token = 99
                self._settings_target_change_token = 7
                self._runtime_context_generation = 2
                self.session_list = DummyList()
                self.pages = None
                self._settings_page = None

            def _stop_bridge(self):
                return None

            def _stop_all_managed_channels(self, refresh=False):
                return None

            def _stop_scheduler_process(self, refresh=False):
                return None

            def _stop_lan_interface_process(self, refresh=False):
                return None

            def _bump_settings_target_generation(self):
                self._settings_target_change_token += 1
                return self._settings_target_change_token

            def _refresh_welcome_state(self):
                return None

            def _settings_reload(self, categories=None, force=False):
                return None

        dummy = DummyNav()
        with mock.patch.object(lz, "is_valid_agent_dir", return_value=False):
            dummy._set_agent_dir("C:\\new-agent", persist=False)

        self.assertFalse(dummy._local_channel_autostart_scheduled)
        self.assertFalse(dummy._chat_runtime_bootstrap_pending)
        self.assertFalse(dummy._lan_interface_autostart_scheduled)
        self.assertFalse(dummy._lan_interface_autostart_running)
        self.assertFalse(dummy._qt_api_remote_loading)
        self.assertFalse(dummy._qt_channel_remote_loading)
        self.assertFalse(dummy._settings_personal_remote_sync_running)
        self.assertFalse(dummy._settings_usage_remote_sync_running)
        self.assertEqual(dummy._settings_personal_remote_sync_key, "")
        self.assertEqual(dummy._settings_personal_remote_synced_key, "")
        self.assertEqual(dummy._settings_usage_remote_sync_key, "")
        self.assertEqual(dummy._settings_usage_remote_synced_key, "")
        self.assertFalse(dummy._remote_channel_sync_running)
        self.assertFalse(dummy._remote_launcher_sync_running)
        self.assertFalse(dummy._remote_launcher_sync_pending_force)
        self.assertEqual(dummy._remote_launcher_sync_pending_device_id, "")
        self.assertFalse(dummy._remote_launcher_sync_pending_refresh)
        self.assertEqual(dummy._next_remote_launcher_sync_at, 0.0)
        self.assertEqual(dummy._next_remote_channel_sync_at, 0.0)
        self.assertEqual(dummy._settings_schedule_remote_reload_token, 0)
        self.assertEqual(dummy._settings_target_change_token, 8)
        self.assertEqual(dummy._runtime_context_generation, 3)

    def test_load_config_migrates_launcher_config_from_install_root(self):
        with tempfile.TemporaryDirectory() as td:
            install_root = os.path.join(td, "Programs", "GenericAgentLauncher")
            version_dir = os.path.join(install_root, "app", "versions", "1.2.3")
            data_root = os.path.join(td, "GenericAgentLauncherData")
            os.makedirs(version_dir, exist_ok=True)
            legacy_path = os.path.join(install_root, "launcher_config.json")
            expected = {"agent_dir": "agent", "remote_devices": [{"id": "srv-1", "host": "10.0.0.8"}]}
            with open(legacy_path, "w", encoding="utf-8") as f:
                json.dump(expected, f, ensure_ascii=False, indent=2)

            patched = {
                "APP_DIR": version_dir,
                "IS_WINDOWS": True,
                "PROGRAMS_ROOT": install_root,
                "DATA_ROOT": data_root,
                "CONFIG_PATH": os.path.join(data_root, "config", "launcher_config.json"),
                "LEGACY_CONFIG_PATH": os.path.join(version_dir, "launcher_config.json"),
                "STATE_DIR": os.path.join(data_root, "state"),
                "UPDATES_DIR": os.path.join(data_root, "updates"),
                "UPDATE_JOBS_DIR": os.path.join(data_root, "updates", "jobs"),
                "UPDATE_DOWNLOADS_DIR": os.path.join(data_root, "updates", "downloads"),
                "UPDATE_STAGING_DIR": os.path.join(data_root, "updates", "staging"),
            }
            originals = {name: getattr(runtime, name) for name in patched}
            try:
                for name, value in patched.items():
                    setattr(runtime, name, value)
                with mock.patch.dict(os.environ, {"GA_LAUNCHER_PROGRAMS_ROOT": ""}, clear=False):
                    loaded = runtime.load_config()
            finally:
                for name, value in originals.items():
                    setattr(runtime, name, value)

            self.assertEqual(loaded, expected)
            self.assertTrue(os.path.isfile(patched["CONFIG_PATH"]))
            with open(patched["CONFIG_PATH"], "r", encoding="utf-8") as f:
                persisted = json.load(f)
            self.assertEqual(persisted, expected)

    def test_refresh_settings_target_combo_auto_fallback_invalidates_target_cached_pages(self):
        class DummyCombo:
            def __init__(self):
                self.items = []
                self._current_index = 0

            def count(self):
                return len(self.items)

            def currentIndex(self):
                return self._current_index

            def blockSignals(self, _blocked):
                return None

            def setCurrentIndex(self, index):
                self._current_index = int(index)

            def clear(self):
                self.items.clear()
                self._current_index = 0

            def addItem(self, label, data):
                self.items.append((label, data))

            def itemData(self, index):
                try:
                    return self.items[int(index)][1]
                except Exception:
                    return None

        class DummySettings(SettingsPanelMixin):
            _refresh_settings_target_combo = SettingsPanelMixin._refresh_settings_target_combo
            _apply_settings_target_selection = SettingsPanelMixin._apply_settings_target_selection

            def __init__(self):
                self.cfg = {}
                self.settings_target_combo = DummyCombo()
                self._settings_target_scope = "remote"
                self._settings_target_device_id = "missing-box"
                self._settings_target_combo_signature = (("远程设备", "remote", "missing-box", "10.0.0.8"),)
                self._settings_target_change_token = 4
                self._settings_loaded_categories = {"api", "channels", "schedule", "personal", "usage", "theme"}
                self._current_settings_category = "api"
                self.calls = []

            def _normalize_settings_target(self, raw):
                data = dict(raw or {})
                scope = str(data.get("scope") or "local").strip().lower()
                device_id = str(data.get("device_id") or "local").strip() or "local"
                if scope not in ("local", "remote"):
                    scope = "local"
                    device_id = "local"
                if scope == "local":
                    device_id = "local"
                return {"scope": scope, "device_id": device_id}

            def _settings_target_combo_entries(self):
                return [("本机", {"scope": "local", "device_id": "local"})]

            def _sync_personal_target_combo(self, entries, target_index, signature, force=False):
                self.calls.append(("sync_personal", int(target_index), tuple(signature), bool(force)))

            def _dismiss_combo_popup(self, combo):
                self.calls.append("dismiss_popup")

            def _bump_settings_target_generation(self):
                self._settings_target_change_token += 1
                return self._settings_target_change_token

            def _refresh_settings_target_notice(self):
                self.calls.append("refresh_notice")

            def _refresh_settings_target_visibility(self, key=None):
                self.calls.append(("refresh_visibility", key))

            def _settings_category_uses_target_switch(self, key):
                return str(key or "").strip().lower() in {"api", "channels", "schedule", "usage"}

            def _settings_reload(self, *, categories=None, force=False):
                self.calls.append(("settings_reload", list(categories or []), bool(force)))

        dummy = DummySettings()
        with mock.patch.object(lz, "save_config") as save_config:
            dummy._refresh_settings_target_combo(force=False)

        self.assertEqual(dummy._settings_target_scope, "local")
        self.assertEqual(dummy._settings_target_device_id, "local")
        self.assertEqual(dummy._settings_target_change_token, 5)
        self.assertEqual(dummy.cfg.get("settings_target"), {"scope": "local", "device_id": "local"})
        self.assertNotIn("api", dummy._settings_loaded_categories)
        self.assertNotIn("channels", dummy._settings_loaded_categories)
        self.assertNotIn("schedule", dummy._settings_loaded_categories)
        self.assertNotIn("personal", dummy._settings_loaded_categories)
        self.assertNotIn("usage", dummy._settings_loaded_categories)
        self.assertIn("theme", dummy._settings_loaded_categories)
        save_config.assert_called_once_with(dummy.cfg)

    def test_schedule_summary_status_reports_external_running_for_local_scheduler(self):
        class DummySchedule(ScheduleRuntimeMixin):
            def __init__(self):
                self._scheduler_proc = None
                self._scheduler_last_exit_code = None

            def _scheduler_cleanup_if_exited(self):
                return None

            def _schedule_last_data(self):
                return {"enabled_count": 1}

            def _scheduler_proc_alive(self):
                return False

            def _scheduler_external_running(self):
                return True

        dummy = DummySchedule()
        summary = dummy._schedule_summary_status()
        self.assertEqual(summary["text"], "外部运行中")
        self.assertEqual(summary["code"], "running")

    def test_reload_schedule_panel_clears_stale_snapshot_when_remote_target_missing(self):
        class DummySchedule(ScheduleRuntimeMixin):
            _reload_schedule_panel = ScheduleRuntimeMixin._reload_schedule_panel
            _schedule_reset_snapshot = ScheduleRuntimeMixin._schedule_reset_snapshot

            def __init__(self):
                self.agent_dir = "C:\\demo"
                self.settings_schedule_notice = mock.Mock()
                self.settings_schedule_list_layout = object()
                self._schedule_last_data_snapshot = {"is_remote": True, "tasks": [{"id": "old"}], "runtime_status": "运行中"}
                self._schedule_task_state_rows_data = [{"task_id": "old"}]

            def _clear_layout(self, _layout):
                return None

            def _schedule_target_context(self):
                return {"is_remote": True, "device_id": "missing-box", "label": "缺失设备"}

            def _schedule_target_device(self):
                return None

        dummy = DummySchedule()
        dummy._reload_schedule_panel()

        snapshot = dummy._schedule_last_data_snapshot
        self.assertTrue(snapshot.get("is_remote"))
        self.assertEqual(snapshot.get("device_id"), "missing-box")
        self.assertEqual(snapshot.get("runtime_detail"), "当前设置目标对应的远程设备不存在。")
        self.assertEqual(snapshot.get("tasks"), [])
        self.assertEqual(dummy._schedule_task_state_rows_data, [])

    def test_reload_schedule_panel_clears_stale_snapshot_when_agent_dir_invalid(self):
        class DummySchedule(ScheduleRuntimeMixin):
            _reload_schedule_panel = ScheduleRuntimeMixin._reload_schedule_panel
            _schedule_reset_snapshot = ScheduleRuntimeMixin._schedule_reset_snapshot

            def __init__(self):
                self.agent_dir = ""
                self.settings_schedule_notice = mock.Mock()
                self.settings_schedule_list_layout = object()
                self._schedule_last_data_snapshot = {"is_remote": False, "tasks": [{"id": "old"}], "runtime_status": "运行中"}
                self._schedule_task_state_rows_data = [{"task_id": "old"}]

            def _clear_layout(self, _layout):
                return None

            def _schedule_target_context(self):
                return {"is_remote": False, "device_id": "local", "label": "本机"}

        dummy = DummySchedule()
        with mock.patch.object(lz, "is_valid_agent_dir", return_value=False):
            dummy._reload_schedule_panel()

        snapshot = dummy._schedule_last_data_snapshot
        self.assertFalse(snapshot.get("is_remote"))
        self.assertEqual(snapshot.get("runtime_detail"), "请先选择有效的 GenericAgent 目录。")
        self.assertEqual(snapshot.get("tasks"), [])
        self.assertEqual(dummy._schedule_task_state_rows_data, [])

    def test_load_mykey_source_marks_read_failures_as_load_failed(self):
        class DummySettings(SettingsPanelMixin):
            _load_mykey_source = SettingsPanelMixin._load_mykey_source

            def _settings_target_read_mykey_text(self):
                return False, "", "/remote/mykey.py", "SSH 连接失败"

        dummy = DummySettings()
        py_path, parsed = dummy._load_mykey_source()

        self.assertEqual(py_path, "/remote/mykey.py")
        self.assertTrue(parsed.get("load_failed"))
        self.assertEqual(parsed.get("error"), "SSH 连接失败")
        self.assertEqual(parsed.get("configs"), [])

    def test_schedule_run_remote_job_drops_stale_context_before_success_callback(self):
        class DummyNotice:
            def __init__(self):
                self.text = ""

            def setText(self, text):
                self.text = str(text)

        class DummySchedule(ScheduleRuntimeMixin):
            _schedule_run_remote_job = ScheduleRuntimeMixin._schedule_run_remote_job

            def __init__(self):
                self.agent_dir = "C:\\demo"
                self._runtime_context_generation = 2
                self._settings_target_change_token = 5
                self.settings_schedule_notice = DummyNotice()
                self.calls = []

            def _settings_target_generation(self):
                return self._settings_target_change_token

            def _api_on_ui_thread(self, fn):
                fn()

        class ImmediateThread:
            def __init__(self, target=None, name=None, daemon=None):
                self._target = target

            def start(self):
                dummy._runtime_context_generation += 1
                if callable(self._target):
                    self._target()

        dummy = DummySchedule()
        with mock.patch.object(schedule_runtime.threading, "Thread", ImmediateThread):
            dummy._schedule_run_remote_job(
                title="同步目录",
                notice_text="正在同步…",
                worker=lambda: ("C:\\cache", 3),
                on_success=lambda result: dummy.calls.append(result),
            )

        self.assertEqual(dummy.settings_schedule_notice.text, "正在同步…")
        self.assertEqual(dummy.calls, [])

    def test_start_scheduler_process_delayed_check_drops_stale_context(self):
        class DummyProc:
            returncode = None

            def poll(self):
                return None

        class DummySchedule(ScheduleRuntimeMixin):
            _start_scheduler_process = ScheduleRuntimeMixin._start_scheduler_process
            _after_scheduler_launch_check = ScheduleRuntimeMixin._after_scheduler_launch_check

            def __init__(self, agent_dir):
                self.agent_dir = agent_dir
                self.cfg = {"python_exe": sys.executable}
                self._runtime_context_generation = 3
                self._scheduler_proc = None
                self._scheduler_log_handle = None
                self._scheduler_last_exit_code = None
                self.reload_calls = 0

            def _schedule_target_context(self):
                return {"is_remote": False}

            def _scheduler_proc_alive(self):
                proc = getattr(self, "_scheduler_proc", None)
                return bool(proc and proc.poll() is None)

            def _scheduler_external_running(self):
                return False

            def _check_runtime_dependencies(self, purpose="", visual=True):
                return True

            def _reload_schedule_panel(self):
                self.reload_calls += 1

        with tempfile.TemporaryDirectory() as td:
            reflect_dir = os.path.join(td, "reflect")
            os.makedirs(reflect_dir, exist_ok=True)
            scheduler_py = os.path.join(reflect_dir, "scheduler.py")
            agentmain_py = os.path.join(td, "agentmain.py")
            with open(scheduler_py, "w", encoding="utf-8") as f:
                f.write("# scheduler")
            with open(agentmain_py, "w", encoding="utf-8") as f:
                f.write("# agentmain")

            dummy = DummySchedule(td)
            delayed = []
            with mock.patch.object(lz, "is_valid_agent_dir", return_value=True), mock.patch.object(
                lz, "upstream_scheduler_paths", return_value={"scheduler_py": scheduler_py}
            ), mock.patch.object(lz, "_resolve_config_path", return_value=sys.executable), mock.patch.object(
                lz, "_find_system_python", return_value=sys.executable
            ), mock.patch.object(
                lz, "_popen_external_subprocess", return_value=DummyProc()
            ), mock.patch.object(
                schedule_runtime.QTimer, "singleShot", side_effect=lambda _ms, cb: delayed.append(cb)
            ), mock.patch.object(schedule_runtime.QMessageBox, "warning") as warning_box:
                self.assertTrue(dummy._start_scheduler_process(show_errors=True))
                self.assertEqual(dummy.reload_calls, 1)
                self.assertEqual(len(delayed), 1)
                dummy._runtime_context_generation += 1
                delayed[0]()
                dummy._scheduler_close_log_handle()

            self.assertEqual(dummy.reload_calls, 1)
            warning_box.assert_not_called()

    def test_lan_interface_status_lines_report_external_running_explicitly(self):
        class DummyUsage(PersonalUsageMixin):
            def __init__(self):
                self.agent_dir = "C:\\demo"
                self.cfg = {"lan_interface": {"enabled": True, "auto_start": True, "bind_all": False, "port": 8501, "frontend": "foo.py"}}

            def _lan_interface_cfg(self):
                return dict(self.cfg.get("lan_interface") or {})

            def _lan_interface_proc_alive(self):
                return False

            def _lan_interface_external_running(self, port=None):
                return True

            def _lan_interface_urls(self, cfg=None):
                return {"local": "http://127.0.0.1:8501", "lan": []}

            def _lan_interface_log_path(self):
                return "C:\\demo\\temp\\lan.log"

        dummy = DummyUsage()
        with mock.patch.object(lz, "is_valid_agent_dir", return_value=True):
            lines = dummy._lan_interface_status_lines()

        self.assertTrue(lines)
        self.assertIn("状态：外部运行中", lines[0])

    def test_schedule_button_state_helpers_explain_disabled_reasons(self):
        class DummySchedule(ScheduleRuntimeMixin):
            _schedule_runtime_start_disabled_reason = ScheduleRuntimeMixin._schedule_runtime_start_disabled_reason
            _schedule_runtime_stop_disabled_reason = ScheduleRuntimeMixin._schedule_runtime_stop_disabled_reason
            _schedule_report_disabled_reason = ScheduleRuntimeMixin._schedule_report_disabled_reason
            _schedule_tasks_dir_disabled_reason = ScheduleRuntimeMixin._schedule_tasks_dir_disabled_reason
            _schedule_log_disabled_reason = ScheduleRuntimeMixin._schedule_log_disabled_reason

            def __init__(self):
                self.agent_dir = "C:\\demo"

            def _scheduler_proc_alive(self):
                return False

            def _scheduler_external_running(self):
                return True

        dummy = DummySchedule()
        with mock.patch.object(lz, "is_valid_agent_dir", return_value=True):
            self.assertEqual(
                dummy._schedule_runtime_start_disabled_reason(is_remote=False),
                "检测到外部调度器实例正在运行；请先关闭外部实例。",
            )
            self.assertEqual(
                dummy._schedule_runtime_stop_disabled_reason(is_remote=False),
                "当前是外部启动的调度器进程，启动器无法直接停止。",
            )
        self.assertEqual(
            dummy._schedule_runtime_start_disabled_reason(is_remote=True, runtime_code="running", scheduler_pid=123),
            "远端调度器已在运行；无需重复启动。",
        )
        self.assertEqual(
            dummy._schedule_runtime_stop_disabled_reason(is_remote=True, runtime_code="stopped", scheduler_pid=0),
            "当前未检测到远端调度器运行中进程。",
        )
        self.assertEqual(
            dummy._schedule_report_disabled_reason({"latest_report_path": ""}, is_remote=True),
            "当前远端任务还没有可同步的报告文件。",
        )
        self.assertEqual(dummy._schedule_tasks_dir_disabled_reason("", is_remote=False), "当前任务目录路径不可用。")
        self.assertEqual(
            dummy._schedule_log_disabled_reason("", is_remote=True, title="调度日志"),
            "当前远端调度日志路径不可用，暂时无法下载。",
        )

    def test_apply_schedule_button_state_sets_tooltips(self):
        class DummyButton:
            def __init__(self):
                self.enabled = None
                self.tooltip = ""

            def setEnabled(self, value):
                self.enabled = bool(value)

            def setToolTip(self, text):
                self.tooltip = str(text)

        class DummySchedule(ScheduleRuntimeMixin):
            _apply_schedule_button_state = ScheduleRuntimeMixin._apply_schedule_button_state

        dummy = DummySchedule()
        btn = DummyButton()
        dummy._apply_schedule_button_state(btn, False, enabled_tooltip="enabled", disabled_tooltip="disabled")
        self.assertFalse(btn.enabled)
        self.assertEqual(btn.tooltip, "disabled")
        dummy._apply_schedule_button_state(btn, True, enabled_tooltip="enabled", disabled_tooltip="disabled")
        self.assertTrue(btn.enabled)
        self.assertEqual(btn.tooltip, "enabled")

    def test_reload_lan_interface_panel_sets_button_tooltips_for_external_running(self):
        class DummyToggle:
            def __init__(self):
                self.checked = None
                self.enabled = None

            def blockSignals(self, _blocked):
                return None

            def setChecked(self, value):
                self.checked = bool(value)

            def setEnabled(self, value):
                self.enabled = bool(value)

        class DummySpin:
            def __init__(self):
                self.value = None
                self.enabled = None

            def blockSignals(self, _blocked):
                return None

            def setValue(self, value):
                self.value = int(value)

            def setEnabled(self, value):
                self.enabled = bool(value)

        class DummyCombo:
            def __init__(self):
                self.enabled = None
                self.index = 0
                self.items = [("默认", "foo.py")]

            def blockSignals(self, _blocked):
                return None

            def count(self):
                return len(self.items)

            def itemData(self, index):
                return self.items[int(index)][1]

            def setCurrentIndex(self, index):
                self.index = int(index)

            def setEnabled(self, value):
                self.enabled = bool(value)

        class DummyButton:
            def __init__(self):
                self.enabled = None
                self.tooltip = ""

            def setEnabled(self, value):
                self.enabled = bool(value)

            def setToolTip(self, text):
                self.tooltip = str(text)

        class DummyLabel:
            def __init__(self):
                self.text = ""

            def setText(self, text):
                self.text = str(text)

        class DummyUsage(PersonalUsageMixin):
            _reload_lan_interface_panel = PersonalUsageMixin._reload_lan_interface_panel
            _apply_personal_button_state = PersonalUsageMixin._apply_personal_button_state
            _lan_interface_form_disabled_reason = PersonalUsageMixin._lan_interface_form_disabled_reason
            _lan_interface_toggle_disabled_reason = PersonalUsageMixin._lan_interface_toggle_disabled_reason

            def __init__(self):
                self.agent_dir = "C:\\demo"
                self.cfg = {"lan_interface": {"enabled": True, "auto_start": True, "bind_all": False, "port": 8501, "frontend": "foo.py"}}
                self.settings_lan_status = DummyLabel()
                self.settings_lan_enabled = DummyToggle()
                self.settings_lan_bind_all = DummyToggle()
                self.settings_lan_autostart = DummyToggle()
                self.settings_lan_port_spin = DummySpin()
                self.settings_lan_frontend_combo = DummyCombo()
                self.settings_lan_save_btn = DummyButton()
                self.settings_lan_start_btn = DummyButton()
                self.settings_lan_stop_btn = DummyButton()
                self.settings_lan_open_btn = DummyButton()
                self.settings_lan_log_btn = DummyButton()

            def _lan_interface_cfg(self):
                return dict(self.cfg.get("lan_interface") or {})

            def _lan_interface_proc_alive(self):
                return False

            def _lan_interface_external_running(self, port=None):
                return True

            def _lan_interface_log_path(self):
                return ""

            def _lan_interface_status_lines(self):
                return ["状态：外部运行中"]

        dummy = DummyUsage()
        with mock.patch.object(lz, "is_valid_agent_dir", return_value=True):
            dummy._reload_lan_interface_panel()

        self.assertFalse(dummy.settings_lan_start_btn.enabled)
        self.assertFalse(dummy.settings_lan_stop_btn.enabled)
        self.assertFalse(dummy.settings_lan_log_btn.enabled)
        self.assertIn("请先关闭外部进程", dummy.settings_lan_start_btn.tooltip)
        self.assertIn("启动器无法直接停止", dummy.settings_lan_stop_btn.tooltip)
        self.assertIn("当前还没有可用的局域网 Web 日志文件", dummy.settings_lan_log_btn.tooltip)
        self.assertEqual(dummy.settings_lan_status.text, "状态：外部运行中")

    def test_reload_lan_interface_panel_sets_invalid_dir_tooltips(self):
        class DummyToggle:
            def blockSignals(self, _blocked):
                return None

            def setChecked(self, value):
                return None

            def setEnabled(self, value):
                return None

        class DummySpin:
            def blockSignals(self, _blocked):
                return None

            def setValue(self, value):
                return None

            def setEnabled(self, value):
                return None

        class DummyCombo:
            def __init__(self):
                self.items = [("默认", "foo.py")]

            def blockSignals(self, _blocked):
                return None

            def count(self):
                return len(self.items)

            def itemData(self, index):
                return self.items[int(index)][1]

            def setCurrentIndex(self, index):
                return None

            def setEnabled(self, value):
                return None

        class DummyButton:
            def __init__(self):
                self.enabled = None
                self.tooltip = ""

            def setEnabled(self, value):
                self.enabled = bool(value)

            def setToolTip(self, text):
                self.tooltip = str(text)

        class DummyLabel:
            def __init__(self):
                self.text = ""

            def setText(self, text):
                self.text = str(text)

        class DummyUsage(PersonalUsageMixin):
            _reload_lan_interface_panel = PersonalUsageMixin._reload_lan_interface_panel
            _apply_personal_button_state = PersonalUsageMixin._apply_personal_button_state
            _lan_interface_form_disabled_reason = PersonalUsageMixin._lan_interface_form_disabled_reason
            _lan_interface_toggle_disabled_reason = PersonalUsageMixin._lan_interface_toggle_disabled_reason

            def __init__(self):
                self.agent_dir = ""
                self.cfg = {"lan_interface": {"enabled": True, "auto_start": False, "bind_all": False, "port": 8501, "frontend": "foo.py"}}
                self.settings_lan_status = DummyLabel()
                self.settings_lan_enabled = DummyToggle()
                self.settings_lan_bind_all = DummyToggle()
                self.settings_lan_autostart = DummyToggle()
                self.settings_lan_port_spin = DummySpin()
                self.settings_lan_frontend_combo = DummyCombo()
                self.settings_lan_save_btn = DummyButton()
                self.settings_lan_start_btn = DummyButton()
                self.settings_lan_stop_btn = DummyButton()
                self.settings_lan_open_btn = DummyButton()
                self.settings_lan_log_btn = DummyButton()

            def _lan_interface_cfg(self):
                return dict(self.cfg.get("lan_interface") or {})

            def _lan_interface_proc_alive(self):
                return False

            def _lan_interface_external_running(self, port=None):
                return False

            def _lan_interface_log_path(self):
                return ""

            def _lan_interface_status_lines(self):
                return ["请先选择有效的 GenericAgent 目录。"]

        dummy = DummyUsage()
        with mock.patch.object(lz, "is_valid_agent_dir", return_value=False):
            dummy._reload_lan_interface_panel()

        self.assertFalse(dummy.settings_lan_save_btn.enabled)
        self.assertFalse(dummy.settings_lan_start_btn.enabled)
        self.assertFalse(dummy.settings_lan_open_btn.enabled)
        self.assertFalse(dummy.settings_lan_log_btn.enabled)
        self.assertEqual(dummy.settings_lan_save_btn.tooltip, "请先选择有效的 GenericAgent 目录。")
        self.assertEqual(dummy.settings_lan_start_btn.tooltip, "请先选择有效的 GenericAgent 目录。")
        self.assertEqual(dummy.settings_lan_open_btn.tooltip, "请先选择有效的 GenericAgent 目录。")
        self.assertEqual(dummy.settings_lan_log_btn.tooltip, "请先选择有效的 GenericAgent 目录。")

    def test_personal_usage_helpers_explain_lan_toggle_and_langfuse_clear_states(self):
        class DummyUsage(PersonalUsageMixin):
            _lan_interface_form_disabled_reason = PersonalUsageMixin._lan_interface_form_disabled_reason
            _lan_interface_toggle_disabled_reason = PersonalUsageMixin._lan_interface_toggle_disabled_reason
            _langfuse_clear_disabled_reason = PersonalUsageMixin._langfuse_clear_disabled_reason

        dummy = DummyUsage()
        self.assertEqual(dummy._lan_interface_form_disabled_reason(valid_agent_dir=False), "请先选择有效的 GenericAgent 目录。")
        self.assertEqual(dummy._lan_interface_form_disabled_reason(valid_agent_dir=True), "")
        self.assertEqual(
            dummy._lan_interface_toggle_disabled_reason(valid_agent_dir=False, feature_enabled=True),
            "请先选择有效的 GenericAgent 目录。",
        )
        self.assertEqual(
            dummy._lan_interface_toggle_disabled_reason(valid_agent_dir=True, feature_enabled=False),
            "请先开启局域网 Web 接口，再调整这个选项。",
        )
        self.assertEqual(dummy._lan_interface_toggle_disabled_reason(valid_agent_dir=True, feature_enabled=True), "")
        self.assertEqual(
            dummy._langfuse_clear_disabled_reason(configured=False),
            "当前还没有已保存的 Langfuse 配置可清除。",
        )
        self.assertEqual(dummy._langfuse_clear_disabled_reason(configured=True), "")

    def test_start_lan_interface_process_delayed_check_drops_stale_context(self):
        class DummyProc:
            returncode = None

            def poll(self):
                return None

        class DummyUsage(PersonalUsageMixin):
            _start_lan_interface_process = PersonalUsageMixin._start_lan_interface_process
            _after_lan_interface_launch_check = PersonalUsageMixin._after_lan_interface_launch_check

            def __init__(self, agent_dir):
                self.agent_dir = agent_dir
                self.cfg = {"python_exe": sys.executable, "lan_interface": {"enabled": True, "auto_start": True, "bind_all": False, "port": 8501, "frontend": "stapp.py"}}
                self._runtime_context_generation = 2
                self._lan_interface_proc = None
                self._lan_interface_log_handle = None
                self._lan_interface_last_exit_code = None
                self.reload_calls = 0
                self.statuses = []

            def _lan_interface_cfg(self):
                return dict(self.cfg.get("lan_interface") or {})

            def _lan_interface_proc_alive(self):
                proc = getattr(self, "_lan_interface_proc", None)
                return bool(proc and proc.poll() is None)

            def _lan_interface_external_running(self, port=None):
                return False

            def _lan_interface_frontend_path(self, frontend):
                return os.path.join(self.agent_dir, "frontends", str(frontend or ""))

            def _check_runtime_dependencies(self, purpose="", extra_packages=None, visual=True):
                return True

            def _lan_interface_port_in_use(self, port):
                return False

            def _lan_interface_health_ok(self, port):
                return False

            def _lan_interface_log_path(self):
                return os.path.join(self.agent_dir, "temp", "lan.log")

            def _lan_interface_command(self, py, cfg, script_path):
                return [py, script_path]

            def _lan_interface_urls(self, cfg=None):
                return {"local": "http://127.0.0.1:8501", "lan": []}

            def _set_status(self, text):
                self.statuses.append(str(text))

            def _reload_lan_interface_panel(self):
                self.reload_calls += 1

        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "frontends"), exist_ok=True)
            os.makedirs(os.path.join(td, "temp"), exist_ok=True)
            frontend = os.path.join(td, "frontends", "stapp.py")
            with open(frontend, "w", encoding="utf-8") as f:
                f.write("# streamlit")

            dummy = DummyUsage(td)
            delayed = []
            with mock.patch.object(lz, "is_valid_agent_dir", return_value=True), mock.patch.object(
                lz, "_resolve_config_path", return_value=sys.executable
            ), mock.patch.object(
                lz, "_find_system_python", return_value=sys.executable
            ), mock.patch.object(
                lz, "_popen_external_subprocess", return_value=DummyProc()
            ), mock.patch.object(
                personal_usage.QApplication, "instance", return_value=object()
            ), mock.patch.object(
                personal_usage.QTimer, "singleShot", side_effect=lambda _ms, cb: delayed.append(cb)
            ), mock.patch.object(personal_usage.QMessageBox, "warning") as warning_box:
                self.assertTrue(dummy._start_lan_interface_process(show_errors=True, skip_dependency_check=False, refresh=True))
                self.assertEqual(dummy.reload_calls, 1)
                self.assertEqual(len(delayed), 1)
                dummy._runtime_context_generation += 1
                delayed[0]()
            dummy._lan_interface_close_log_handle()

            self.assertEqual(dummy.reload_calls, 1)
            warning_box.assert_not_called()

    def test_trigger_settings_remote_session_sync_still_calls_done_without_blocking_syncers(self):
        class DummyUsage(PersonalUsageMixin):
            _trigger_settings_remote_session_sync = PersonalUsageMixin._trigger_settings_remote_session_sync

            def __init__(self):
                self.calls = []

        dummy = DummyUsage()

        def mark_done():
            dummy.calls.append("done")

        with mock.patch.object(personal_usage.QTimer, "singleShot", side_effect=lambda _ms, cb: cb()):
            dummy._trigger_settings_remote_session_sync(device_id="srv-1", on_done=mark_done, include_all_channels=True)

        self.assertEqual(dummy.calls, ["done"])

    def test_trigger_settings_remote_session_sync_passes_captured_agent_dir_and_context(self):
        class ImmediateThread:
            def __init__(self, target=None, name=None, daemon=None):
                self._target = target

            def start(self):
                if callable(self._target):
                    self._target()

        class DummyUsage(PersonalUsageMixin):
            _trigger_settings_remote_session_sync = PersonalUsageMixin._trigger_settings_remote_session_sync

            def __init__(self):
                self.agent_dir = "C:\\demo" if os.name == "nt" else os.path.join(os.sep, "tmp", "demo")
                self._runtime_context_generation = 4
                self._settings_target_change_token = 9
                self.calls = []

            def _settings_target_generation(self):
                return self._settings_target_change_token

            def _sync_remote_device_launcher_sessions_blocking(self, **kwargs):
                self.calls.append(("launcher", dict(kwargs)))

            def _sync_remote_device_channel_process_sessions_blocking(self, **kwargs):
                self.calls.append(("channel", dict(kwargs)))

            def _api_on_ui_thread(self, fn):
                fn()

        dummy = DummyUsage()
        with mock.patch.object(personal_usage.threading, "Thread", ImmediateThread):
            dummy._trigger_settings_remote_session_sync(
                device_id="srv-1",
                on_done=lambda: dummy.calls.append(("done", {})),
                include_all_channels=True,
                include_usage=True,
            )

        launcher_call = next(payload for name, payload in dummy.calls if name == "launcher")
        channel_call = next(payload for name, payload in dummy.calls if name == "channel")
        expected_agent_dir = os.path.abspath(dummy.agent_dir)
        self.assertEqual(launcher_call["agent_dir"], expected_agent_dir)
        self.assertEqual(channel_call["agent_dir"], expected_agent_dir)
        self.assertEqual(launcher_call["runtime_context"]["agent_dir"], expected_agent_dir)
        self.assertEqual(launcher_call["runtime_context"]["runtime_generation"], 4)
        self.assertEqual(launcher_call["runtime_context"]["settings_target_generation"], 9)
        self.assertIn(("done", {}), dummy.calls)

    def test_terminate_process_tree_kills_spawned_child_process(self):
        script = (
            "import subprocess, sys, time\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            "print(child.pid, flush=True)\n"
            "time.sleep(60)\n"
        )
        proc = subprocess.Popen(
            [sys.executable, "-u", "-c", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            start_new_session=False if os.name == "nt" else True,
        )
        try:
            child_line = str(proc.stdout.readline() if proc.stdout is not None else "").strip()
            self.assertTrue(child_line.isdigit(), msg=f"unexpected child pid line: {child_line!r}")
            child_pid = int(child_line)
            self.assertTrue(runtime.terminate_process_tree(proc, terminate_timeout=0.3, kill_timeout=1.5))
            proc.wait(timeout=5)
            self.assertFalse(self._pid_exists(child_pid), msg=f"child process still alive: {child_pid}")
        finally:
            try:
                runtime.terminate_process_tree(proc, terminate_timeout=0.1, kill_timeout=0.2)
            except Exception:
                pass

    def test_popen_external_subprocess_uses_new_session_on_posix(self):
        popen_mock = mock.Mock(return_value=object())
        with mock.patch.object(runtime.os, "name", "posix"), mock.patch.object(runtime.subprocess, "Popen", popen_mock):
            runtime._popen_external_subprocess(["python", "-V"])

        _args, kwargs = popen_mock.call_args
        self.assertTrue(kwargs.get("start_new_session"))
        self.assertIn("env", kwargs)

    def test_terminate_process_tree_uses_process_group_on_posix(self):
        state = {"alive": True}

        class FakeProc:
            def __init__(self):
                self.pid = 999
                self.stdout = None
                self.stderr = None
                self.stdin = None

            def poll(self):
                return None if state["alive"] else 0

            def wait(self, timeout=None):
                if state["alive"]:
                    raise subprocess.TimeoutExpired(cmd="fake", timeout=timeout)
                return 0

        proc = FakeProc()

        def fake_getpgid(value):
            return 4321 if int(value) == 999 else 1234

        def fake_kill(pid, sig):
            if int(sig) == 0:
                if state["alive"]:
                    return None
                raise ProcessLookupError()
            state["alive"] = False
            return None

        def fake_killpg(pgid, sig):
            self.assertEqual(int(pgid), 4321)
            expected_term = int(getattr(runtime.signal, "SIGTERM", 15))
            expected_kill = int(getattr(runtime.signal, "SIGKILL", expected_term))
            self.assertIn(int(sig), (expected_term, expected_kill))
            state["alive"] = False
            return None

        with mock.patch.object(runtime.os, "name", "posix"), mock.patch.object(
            runtime.os, "getpgid", side_effect=fake_getpgid, create=True
        ), mock.patch.object(runtime.os, "kill", side_effect=fake_kill) as kill_mock, mock.patch.object(
            runtime.os, "killpg", side_effect=fake_killpg, create=True
        ) as killpg_mock:
            ok = runtime.terminate_process_tree(proc, terminate_timeout=0.1, kill_timeout=0.1)

        self.assertTrue(ok)
        self.assertGreaterEqual(killpg_mock.call_count, 1)
        self.assertGreaterEqual(kill_mock.call_count, 1)

    def test_bridge_script_path_points_to_repo_root_bridge(self):
        bridge_path = lz._bridge_script_path()
        expected = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bridge.py")
        self.assertEqual(os.path.normpath(bridge_path), os.path.normpath(expected))
        self.assertTrue(os.path.isfile(bridge_path), msg=f"missing bridge.py: {bridge_path}")

    def test_launcher_bootstrap_avoids_launcher_core_facade_import(self):
        root = os.path.dirname(os.path.dirname(__file__))
        path = os.path.join(root, "launcher_bootstrap.py")
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        self.assertIn("from launcher_core_parts.constants import MAIN_EXE_NAME", src)
        self.assertIn("from launcher_core_parts.runtime import (", src)
        self.assertNotIn("from launcher_app import core as lz", src)

    def test_updater_avoids_launcher_core_facade_import(self):
        root = os.path.dirname(os.path.dirname(__file__))
        path = os.path.join(root, "updater.py")
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        self.assertIn("from launcher_core_parts.runtime import updater_log", src)
        self.assertIn("from launcher_core_parts.update_manager import apply_update_job", src)
        self.assertNotIn("from launcher_app import core as lz", src)

    def test_launcher_bootstrap_falls_back_to_dev_onedir_layout(self):
        with tempfile.TemporaryDirectory() as td:
            bootstrap_exe = os.path.join(td, "LauncherBootstrap.exe")
            app_dir = os.path.join(td, "GenericAgentLauncher")
            main_exe_name = "GenericAgentLauncher.exe"
            app_exe = os.path.join(app_dir, main_exe_name)
            os.makedirs(app_dir, exist_ok=True)
            with open(bootstrap_exe, "wb") as f:
                f.write(b"bootstrap")
            with open(app_exe, "wb") as f:
                f.write(b"main")

            with mock.patch.object(launcher_bootstrap, "MAIN_EXE_NAME", main_exe_name), mock.patch.object(
                launcher_bootstrap, "load_version_state", return_value={}
            ), mock.patch.object(
                launcher_bootstrap, "resolved_versions_dir", return_value=os.path.join(td, "missing_versions")
            ), mock.patch.object(launcher_bootstrap.sys, "frozen", True, create=True), mock.patch.object(
                launcher_bootstrap.sys, "executable", bootstrap_exe
            ):
                picked = launcher_bootstrap._pick_target_executable()

            self.assertEqual(os.path.normcase(os.path.normpath(picked)), os.path.normcase(os.path.normpath(app_exe)))

    def test_launcher_bootstrap_rejects_self_target(self):
        with tempfile.TemporaryDirectory() as td:
            bootstrap_exe = os.path.join(td, "LauncherBootstrap.exe")
            with open(bootstrap_exe, "wb") as f:
                f.write(b"bootstrap")

            with mock.patch.object(launcher_bootstrap, "MAIN_EXE_NAME", "LauncherBootstrap.exe"), mock.patch.object(
                launcher_bootstrap, "load_version_state", return_value={}
            ), mock.patch.object(
                launcher_bootstrap, "resolved_versions_dir", return_value=os.path.join(td, "missing_versions")
            ), mock.patch.object(
                launcher_bootstrap.sys, "frozen", True, create=True
            ), mock.patch.object(
                launcher_bootstrap.sys, "executable", bootstrap_exe
            ):
                picked = launcher_bootstrap._pick_target_executable()

            self.assertEqual(picked, "")

    def test_navigation_quick_enter_only_skips_dependency_check_with_fresh_cache(self):
        class DummyNav(NavigationMixin):
            def __init__(self):
                self.calls = []
                self._last_dependency_check = {}

            def _dependency_check_cache_key(self, extra_packages=None):
                extras = tuple(extra_packages or [])
                return ("demo", extras)

            def _enter_chat(self, *, skip_dependency_check=False):
                self.calls.append(bool(skip_dependency_check))

        dummy = DummyNav()
        dummy._quick_enter_chat()
        self.assertEqual(dummy.calls[-1], False)

        dummy._last_dependency_check = {"ok": True, "extra_packages": [], "key": ("stale", ())}
        dummy._quick_enter_chat()
        self.assertEqual(dummy.calls[-1], False)

        dummy._last_dependency_check = {"ok": True, "extra_packages": [], "key": ("demo", ())}
        dummy._quick_enter_chat()
        self.assertEqual(dummy.calls[-1], True)

    def test_refresh_welcome_state_sets_enter_chat_button_tooltip(self):
        class DummyButton:
            def __init__(self):
                self.enabled = None
                self.tooltip = ""

            def setEnabled(self, enabled):
                self.enabled = bool(enabled)

            def setToolTip(self, text):
                self.tooltip = str(text)

        class DummyNav(NavigationMixin):
            _refresh_welcome_state = NavigationMixin._refresh_welcome_state
            _apply_navigation_widget_state = NavigationMixin._apply_navigation_widget_state

            def __init__(self):
                self.agent_dir = ""
                self.cfg = {}
                self.enter_chat_btn = DummyButton()

            def _refresh_download_state(self):
                return None

        dummy = DummyNav()
        with mock.patch.object(lz, "is_valid_agent_dir", return_value=False):
            dummy._refresh_welcome_state()
        self.assertFalse(dummy.enter_chat_btn.enabled)
        self.assertEqual(dummy.enter_chat_btn.tooltip, "请先选择有效的 GenericAgent 目录。")

        dummy.agent_dir = "C:\\demo"
        with mock.patch.object(lz, "is_valid_agent_dir", return_value=True):
            dummy._refresh_welcome_state()
        self.assertTrue(dummy.enter_chat_btn.enabled)
        self.assertEqual(dummy.enter_chat_btn.tooltip, "进入聊天页并开始准备当前内核环境。")

    def test_download_cleanup_removes_invalid_target_directory(self):
        class DummyDownload(DownloadMixin):
            pass

        dummy = DummyDownload()
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "GenericAgent")
            os.makedirs(os.path.join(target, "partial"), exist_ok=True)
            with open(os.path.join(target, "partial", "leftover.txt"), "w", encoding="utf-8") as f:
                f.write("stale")

            ok, detail = dummy._remove_download_target_path(target)

            self.assertTrue(ok, msg=detail)
            self.assertFalse(os.path.exists(target))

    def test_download_success_text_uses_system_python_guidance_without_private_installer(self):
        class DummyDownload(DownloadMixin):
            def _supports_private_python_installer(self):
                return False

        dummy = DummyDownload()
        self.assertTrue(dummy._uses_system_python_download_mode())
        self.assertEqual(
            dummy._download_existing_target_ready_text(),
            "已使用现有目录。请使用系统 Python 进入聊天；首次载入时会自动执行依赖检查。",
        )
        self.assertEqual(
            dummy._download_clone_ready_text(),
            "下载完成，已设置为当前 GenericAgent 目录。请使用系统 Python 进入聊天；首次载入时会自动执行依赖检查。",
        )
        self.assertEqual(dummy._download_git_missing_message(), "未检测到 Git。请先安装 Git：\nhttps://git-scm.com/downloads")

    def test_refresh_download_state_tolerates_missing_private_controls(self):
        class DummyLabel:
            def __init__(self):
                self.text = ""

            def setText(self, text):
                self.text = str(text)

        class DummyButton:
            def __init__(self):
                self.enabled = None
                self.text = ""

            def setEnabled(self, enabled):
                self.enabled = bool(enabled)

            def setText(self, text):
                self.text = str(text)

        class DummyProgress:
            def __init__(self):
                self.range = None
                self.value = None

            def setRange(self, left, right):
                self.range = (int(left), int(right))

            def setValue(self, value):
                self.value = int(value)

        class DummyDownload(DownloadMixin):
            _refresh_download_state = DownloadMixin._refresh_download_state

            def __init__(self):
                self.install_parent = "/tmp"
                self._download_running = False
                self._download_mode = ""
                self.download_parent_label = DummyLabel()
                self.download_parent_value = DummyLabel()
                self.download_btn = DummyButton()
                self.download_progress = DummyProgress()

        dummy = DummyDownload()
        dummy._refresh_download_state()
        self.assertIn("GenericAgent", dummy.download_parent_label.text)
        self.assertEqual(dummy.download_parent_value.text, "/tmp")
        self.assertTrue(dummy.download_btn.enabled)
        self.assertEqual(dummy.download_btn.text, "开始下载")
        self.assertEqual(dummy.download_progress.range, (0, 1))
        self.assertEqual(dummy.download_progress.value, 0)

    def test_channel_runtime_detects_local_wechat_processes_on_posix(self):
        class DummyChannel(ChannelRuntimeMixin):
            def __init__(self, agent_dir):
                self.agent_dir = agent_dir
                self.cfg = {}
                self._channel_procs = {}

        dummy = DummyChannel("/tmp/GenericAgent")
        fake_output = "\n".join(
            [
                "101 /usr/bin/python3 /tmp/GenericAgent/frontends/wechatapp.py",
                "202 python3 frontends/wechatapp.py",
                "303 python3 /somewhere/else.py",
            ]
        )

        result = mock.Mock(returncode=0, stdout=fake_output, stderr="")
        with mock.patch.object(channel_runtime.os, "name", "posix"), mock.patch.object(
            channel_runtime.subprocess, "run", return_value=result
        ):
            pids = dummy._find_local_wechat_process_pids()

        self.assertEqual(pids, [101, 202])

    def test_channel_runtime_refreshes_wechat_external_running_from_lock_or_process(self):
        class DummyChannel(ChannelRuntimeMixin):
            def __init__(self):
                self.agent_dir = ""
                self.cfg = {}
                self._channel_procs = {}

        dummy = DummyChannel()
        with mock.patch.object(dummy, "_find_local_wechat_process_pids", return_value=[321]), mock.patch.object(
            dummy, "_wechat_singleton_locked", return_value=False
        ):
            self.assertTrue(dummy._refresh_wechat_external_running())
            self.assertTrue(dummy._channel_external_running("wechat"))

    def test_channel_runtime_terminate_pid_force_uses_shared_tree_terminator_on_posix(self):
        class DummyChannel(ChannelRuntimeMixin):
            pass

        dummy = DummyChannel()
        with mock.patch.object(channel_runtime.os, "name", "posix"), mock.patch.object(
            channel_runtime.lz, "terminate_process_tree", return_value=True
        ) as terminator:
            self.assertTrue(dummy._terminate_pid_force(456))
        terminator.assert_called_once_with(456, terminate_timeout=0.8, kill_timeout=0.8)

    def test_start_wechat_health_watch_drops_stale_runtime_before_ui_callback(self):
        class DummyProc:
            pid = 321

            def poll(self):
                return None

        class ImmediateThread:
            def __init__(self, target=None, name=None, daemon=None):
                self._target = target

            def start(self):
                if callable(self._target):
                    self._target()

        class DummyChannel(ChannelRuntimeMixin):
            _start_wechat_health_watch = ChannelRuntimeMixin._start_wechat_health_watch

            def __init__(self):
                self.agent_dir = "C:\\demo"
                self._runtime_context_generation = 5
                self._channel_procs = {"wechat": {"proc": DummyProc(), "log_start_pos": 0}}
                self.calls = []
                self.statuses = []

            def _channel_log_since(self, channel_id, start_pos=0, limit=16000):
                return "[getUpdates] err: -14 session timeout"

            def _wechat_session_timeout_log_hit(self, text):
                return True

            def _stop_channel_process(self, channel_id):
                self.calls.append(("stop", str(channel_id)))

            def _clear_wx_token_info(self):
                self.calls.append("clear_token")

            def _set_status(self, text):
                self.statuses.append(str(text))

            def _channel_warning(self, title, text, detail=""):
                self.calls.append(("warning", str(title), str(text), str(detail)))

            def _channel_post_ui(self, callback, action_name="界面刷新"):
                self._runtime_context_generation += 1
                if callable(callback):
                    callback()

        dummy = DummyChannel()
        with mock.patch.object(channel_runtime.threading, "Thread", ImmediateThread), mock.patch.object(
            channel_runtime.time, "sleep", side_effect=lambda _secs: None
        ):
            dummy._start_wechat_health_watch(show_errors=True)

        self.assertEqual(dummy.calls, [])
        self.assertEqual(dummy.statuses, [])

    def test_start_wechat_health_watch_still_stops_and_clears_current_runtime(self):
        class DummyProc:
            pid = 654

            def poll(self):
                return None

        class ImmediateThread:
            def __init__(self, target=None, name=None, daemon=None):
                self._target = target

            def start(self):
                if callable(self._target):
                    self._target()

        class DummyChannel(ChannelRuntimeMixin):
            _start_wechat_health_watch = ChannelRuntimeMixin._start_wechat_health_watch

            def __init__(self):
                self.agent_dir = "C:\\demo"
                self._runtime_context_generation = 3
                self._channel_procs = {"wechat": {"proc": DummyProc(), "log_start_pos": 0}}
                self.calls = []
                self.statuses = []

            def _channel_log_since(self, channel_id, start_pos=0, limit=16000):
                return "[getUpdates] err: -14 session timeout"

            def _wechat_session_timeout_log_hit(self, text):
                return True

            def _stop_channel_process(self, channel_id):
                self.calls.append(("stop", str(channel_id)))

            def _clear_wx_token_info(self):
                self.calls.append("clear_token")

            def _set_status(self, text):
                self.statuses.append(str(text))

            def _channel_warning(self, title, text, detail=""):
                self.calls.append(("warning", str(title), str(text), str(detail)))

            def _channel_post_ui(self, callback, action_name="界面刷新"):
                if callable(callback):
                    callback()

        dummy = DummyChannel()
        with mock.patch.object(channel_runtime.threading, "Thread", ImmediateThread), mock.patch.object(
            channel_runtime.time, "sleep", side_effect=lambda _secs: None
        ):
            dummy._start_wechat_health_watch(show_errors=True)

        self.assertEqual(dummy.calls[0], ("stop", "wechat"))
        self.assertIn("clear_token", dummy.calls)
        self.assertTrue(dummy.statuses)
        self.assertIn("本地微信绑定已失效", dummy.statuses[0])
        self.assertTrue(any(isinstance(item, tuple) and item[0] == "warning" for item in dummy.calls))

    def test_start_channel_process_autostart_explains_manual_bind_when_wechat_not_bound(self):
        class ImmediateThread:
            def __init__(self, target=None, name=None, daemon=None):
                self._target = target

            def start(self):
                if callable(self._target):
                    self._target()

        class DummyChannel(ChannelRuntimeMixin):
            _start_channel_process_autostart = ChannelRuntimeMixin._start_channel_process_autostart

            def __init__(self):
                self.agent_dir = "C:\\demo"
                self._runtime_context_generation = 1
                self._channel_procs = {}
                self.statuses = []
                self.done_values = []

            def _channel_proc_alive(self, channel_id):
                return False

            def _wx_token_info(self):
                return {}

            def _channel_post_ui(self, callback, action_name="界面刷新"):
                if callable(callback):
                    callback()

            def _set_status(self, text):
                self.statuses.append(str(text))

        dummy = DummyChannel()
        with mock.patch.object(channel_runtime.threading, "Thread", ImmediateThread), mock.patch.object(
            channel_runtime.lz, "is_valid_agent_dir", return_value=True
        ), mock.patch.object(
            channel_runtime.lz, "COMM_CHANNEL_INDEX", {"wechat": {"label": "微信", "id": "wechat"}}
        ):
            dummy._start_channel_process_autostart("wechat", done=lambda started: dummy.done_values.append(bool(started)))

        self.assertEqual(dummy.statuses, ["本地微信未绑定，自动启动已跳过；如需启动请先手动扫码绑定。"])
        self.assertEqual(dummy.done_values, [False])

    def test_open_wechat_qr_dialog_drops_stale_local_status_callback(self):
        class DummySignal:
            def __init__(self):
                self.callbacks = []

            def connect(self, callback):
                self.callbacks.append(callback)

        class DummyButton:
            def __init__(self, text=""):
                self.text = str(text)
                self.clicked = DummySignal()

            def setStyleSheet(self, _style):
                return None

        class DummyLabel:
            instances = []

            def __init__(self, text=""):
                self.text = str(text)
                DummyLabel.instances.append(self)

            def setObjectName(self, _name):
                return None

            def setWordWrap(self, _enabled):
                return None

            def setAlignment(self, _alignment):
                return None

            def setPixmap(self, _pixmap):
                return None

            def setText(self, text):
                self.text = str(text)

        class DummyLayout:
            def __init__(self, _parent=None):
                return None

            def setContentsMargins(self, *_args):
                return None

            def setSpacing(self, _value):
                return None

            def addWidget(self, _widget, *_args):
                return None

            def addLayout(self, _layout, *_args):
                return None

            def addStretch(self, _value):
                return None

        class DummyDialog:
            def __init__(self, _parent=None):
                self.result_code = 0

            def setWindowTitle(self, _title):
                return None

            def setModal(self, _modal):
                return None

            def resize(self, _w, _h):
                return None

            def accept(self):
                self.result_code = 1

            def reject(self):
                self.result_code = 0

            def done(self, code):
                self.result_code = int(code)

            def exec(self):
                return self.result_code

        class DummyCard:
            pass

        class DummyPixmap:
            def loadFromData(self, _data, _fmt):
                return True

            def scaled(self, *_args):
                return self

        class DummyQrImage:
            def convert(self, _mode):
                return self

            def save(self, buf, format="PNG"):
                buf.write(b"png")
                return True

        class SelectiveThread:
            def __init__(self, target=None, name=None, daemon=None):
                self._target = target
                self._name = name

            def start(self):
                if self._name is None and callable(self._target):
                    self._target()

        class DummyChannel(ChannelRuntimeMixin):
            _open_wechat_qr_dialog = ChannelRuntimeMixin._open_wechat_qr_dialog

            def __init__(self):
                self.agent_dir = "C:\\demo"
                self._runtime_context_generation = 4
                self.statuses = []
                self.warnings = []

            def _local_begin_wechat_qr_login(self, timeout=45):
                return True, {"qrcode": "qr-1", "qrcode_img_content": "content", "login_id": "login-1", "issued_at": 1.0}, ""

            def _local_wechat_qr_state(self, login_id):
                return True, {"status": "expired", "error": "", "login_id": str(login_id), "qrcode": "qr-1"}, ""

            def _channel_post_ui(self, callback, action_name="界面刷新"):
                self._runtime_context_generation += 1
                if callable(callback):
                    callback()

            def _panel_card(self):
                return DummyCard()

            def _action_button_style(self, primary=False):
                return "primary" if primary else "default"

            def _channel_warning(self, title, text, detail=""):
                self.warnings.append((str(title), str(text), str(detail)))

        DummyLabel.instances = []
        dummy = DummyChannel()
        with mock.patch.object(channel_runtime, "QDialog", DummyDialog), mock.patch.object(
            channel_runtime, "QVBoxLayout", DummyLayout
        ), mock.patch.object(channel_runtime, "QHBoxLayout", DummyLayout), mock.patch.object(
            channel_runtime, "QLabel", DummyLabel
        ), mock.patch.object(channel_runtime, "QPushButton", DummyButton), mock.patch.object(
            channel_runtime, "QPixmap", DummyPixmap
        ), mock.patch.object(channel_runtime.threading, "Thread", SelectiveThread), mock.patch.object(
            channel_runtime.time, "sleep", side_effect=lambda _secs: None
        ), mock.patch.object(channel_runtime.lz.qrcode, "make", return_value=DummyQrImage()):
            ok = dummy._open_wechat_qr_dialog(show_errors=True)

        self.assertFalse(ok)
        label_texts = [item.text for item in DummyLabel.instances]
        self.assertIn("请使用微信扫码，确认后会自动完成绑定。", label_texts)
        self.assertNotIn("二维码已过期，请点“重新获取”。", label_texts)

    def test_open_wechat_qr_dialog_keeps_local_status_callback_for_current_runtime(self):
        class DummySignal:
            def __init__(self):
                self.callbacks = []

            def connect(self, callback):
                self.callbacks.append(callback)

        class DummyButton:
            def __init__(self, text=""):
                self.text = str(text)
                self.clicked = DummySignal()

            def setStyleSheet(self, _style):
                return None

        class DummyLabel:
            instances = []

            def __init__(self, text=""):
                self.text = str(text)
                DummyLabel.instances.append(self)

            def setObjectName(self, _name):
                return None

            def setWordWrap(self, _enabled):
                return None

            def setAlignment(self, _alignment):
                return None

            def setPixmap(self, _pixmap):
                return None

            def setText(self, text):
                self.text = str(text)

        class DummyLayout:
            def __init__(self, _parent=None):
                return None

            def setContentsMargins(self, *_args):
                return None

            def setSpacing(self, _value):
                return None

            def addWidget(self, _widget, *_args):
                return None

            def addLayout(self, _layout, *_args):
                return None

            def addStretch(self, _value):
                return None

        class DummyDialog:
            def __init__(self, _parent=None):
                self.result_code = 0

            def setWindowTitle(self, _title):
                return None

            def setModal(self, _modal):
                return None

            def resize(self, _w, _h):
                return None

            def accept(self):
                self.result_code = 1

            def reject(self):
                self.result_code = 0

            def done(self, code):
                self.result_code = int(code)

            def exec(self):
                return self.result_code

        class DummyCard:
            pass

        class DummyPixmap:
            def loadFromData(self, _data, _fmt):
                return True

            def scaled(self, *_args):
                return self

        class DummyQrImage:
            def convert(self, _mode):
                return self

            def save(self, buf, format="PNG"):
                buf.write(b"png")
                return True

        class SelectiveThread:
            def __init__(self, target=None, name=None, daemon=None):
                self._target = target
                self._name = name

            def start(self):
                if self._name is None and callable(self._target):
                    self._target()

        class DummyChannel(ChannelRuntimeMixin):
            _open_wechat_qr_dialog = ChannelRuntimeMixin._open_wechat_qr_dialog

            def __init__(self):
                self.agent_dir = "C:\\demo"
                self._runtime_context_generation = 4
                self.statuses = []
                self.warnings = []

            def _local_begin_wechat_qr_login(self, timeout=45):
                return True, {"qrcode": "qr-1", "qrcode_img_content": "content", "login_id": "login-1", "issued_at": 1.0}, ""

            def _local_wechat_qr_state(self, login_id):
                return True, {"status": "expired", "error": "", "login_id": str(login_id), "qrcode": "qr-1"}, ""

            def _channel_post_ui(self, callback, action_name="界面刷新"):
                if callable(callback):
                    callback()

            def _panel_card(self):
                return DummyCard()

            def _action_button_style(self, primary=False):
                return "primary" if primary else "default"

            def _channel_warning(self, title, text, detail=""):
                self.warnings.append((str(title), str(text), str(detail)))

        DummyLabel.instances = []
        dummy = DummyChannel()
        with mock.patch.object(channel_runtime, "QDialog", DummyDialog), mock.patch.object(
            channel_runtime, "QVBoxLayout", DummyLayout
        ), mock.patch.object(channel_runtime, "QHBoxLayout", DummyLayout), mock.patch.object(
            channel_runtime, "QLabel", DummyLabel
        ), mock.patch.object(channel_runtime, "QPushButton", DummyButton), mock.patch.object(
            channel_runtime, "QPixmap", DummyPixmap
        ), mock.patch.object(channel_runtime.threading, "Thread", SelectiveThread), mock.patch.object(
            channel_runtime.time, "sleep", side_effect=lambda _secs: None
        ), mock.patch.object(channel_runtime.lz.qrcode, "make", return_value=DummyQrImage()):
            ok = dummy._open_wechat_qr_dialog(show_errors=True)

        self.assertFalse(ok)
        label_texts = [item.text for item in DummyLabel.instances]
        self.assertIn("二维码已过期，请点“重新获取”。", label_texts)

    def test_channel_status_reports_external_running_for_local_channel(self):
        class DummyChannel(ChannelRuntimeMixin):
            def __init__(self):
                self.agent_dir = ""
                self.cfg = {}
                self._channel_procs = {}

            def _channel_target_context(self):
                return False, None, {"is_remote": False}

            def _channel_proc_alive(self, _channel_id):
                return False

            def _channel_external_running(self, channel_id):
                return str(channel_id) == "wechat"

            def _channel_conflict_message(self, _channel_id):
                return ""

            def _channel_missing_required(self, _channel_id, _values):
                return []

            def _channel_is_auto_start(self, _channel_id):
                return False

        dummy = DummyChannel()
        text, _color = dummy._channel_status("wechat", {})
        self.assertEqual(text, "外部运行中")

    def test_autostart_channels_skips_channels_marked_external_running(self):
        class DummyChannel(ChannelRuntimeMixin):
            def __init__(self):
                self.agent_dir = "C:\\demo"
                self.cfg = {}
                self._channel_procs = {}
                self._autostart_channels_running = False
                self._autostart_channel_pending_ids = set()
                self._autostart_channel_current = ""
                self.calls = []

            def _channel_is_auto_start(self, channel_id):
                return str(channel_id) == "wechat"

            def _channel_proc_alive(self, _channel_id):
                return False

            def _channel_external_running(self, channel_id):
                return str(channel_id) == "wechat"

            def _refresh_wechat_external_running(self, *, persist=False):
                self.calls.append("refresh_wechat")
                return True

            def _refresh_channels_runtime_status_labels(self):
                return None

        dummy = DummyChannel()
        specs = [{"id": "wechat"}, {"id": "telegram"}]
        with mock.patch.object(channel_runtime.lz, "is_valid_agent_dir", return_value=True), mock.patch.object(
            channel_runtime.lz, "COMM_CHANNEL_SPECS", specs
        ):
            dummy._start_autostart_channels()

        self.assertIn("refresh_wechat", dummy.calls)
        self.assertEqual(dummy._autostart_channel_pending_ids, set())
        self.assertEqual(dummy._autostart_channel_current, "")

    def test_stop_all_managed_channels_clears_autostart_queue_state(self):
        class DummyChannel(ChannelRuntimeMixin):
            _stop_all_managed_channels = ChannelRuntimeMixin._stop_all_managed_channels

            def __init__(self):
                self._autostart_channels_run_id = 4
                self._autostart_channels_running = True
                self._autostart_channel_pending_ids = {"wechat", "telegram"}
                self._autostart_channel_current = "wechat"
                self._channel_procs = {"wechat": object(), "telegram": object()}
                self.stopped = []

            def _stop_channel_process(self, channel_id):
                self.stopped.append(str(channel_id))
                return str(channel_id) == "wechat"

        dummy = DummyChannel()
        stopped = dummy._stop_all_managed_channels(refresh=False)

        self.assertEqual(stopped, 1)
        self.assertEqual(dummy.stopped, ["wechat", "telegram"])
        self.assertEqual(dummy._autostart_channels_run_id, 5)
        self.assertFalse(dummy._autostart_channels_running)
        self.assertEqual(dummy._autostart_channel_pending_ids, set())
        self.assertEqual(dummy._autostart_channel_current, "")

    def test_autostart_queue_does_not_continue_after_stop_all_managed_channels(self):
        class DummyChannel(ChannelRuntimeMixin):
            _start_autostart_channels = ChannelRuntimeMixin._start_autostart_channels
            _stop_all_managed_channels = ChannelRuntimeMixin._stop_all_managed_channels

            def __init__(self):
                self.agent_dir = "C:\\demo"
                self.cfg = {}
                self._channel_procs = {}
                self._autostart_channels_run_id = 0
                self._autostart_channels_running = False
                self._autostart_channel_pending_ids = set()
                self._autostart_channel_current = ""
                self.started = []
                self.callbacks = {}
                self.status_refreshes = 0

            def _channel_is_auto_start(self, channel_id):
                return str(channel_id) in {"wechat", "telegram"}

            def _channel_proc_alive(self, _channel_id):
                return False

            def _channel_external_running(self, _channel_id):
                return False

            def _refresh_wechat_external_running(self, *, persist=False):
                return False

            def _refresh_channels_runtime_status_labels(self):
                self.status_refreshes += 1

            def _channel_post_ui(self, fn, action_name=""):
                fn()

            def _start_channel_process_autostart(self, channel_id, done=None):
                self.started.append(str(channel_id))
                self.callbacks[str(channel_id)] = done

            def _stop_channel_process(self, _channel_id):
                return False

        dummy = DummyChannel()
        specs = [{"id": "wechat"}, {"id": "telegram"}]
        with mock.patch.object(channel_runtime.lz, "is_valid_agent_dir", return_value=True), mock.patch.object(
            channel_runtime.lz, "COMM_CHANNEL_SPECS", specs
        ):
            dummy._start_autostart_channels()

        self.assertEqual(dummy.started, ["wechat"])
        self.assertTrue(dummy._autostart_channels_running)
        self.assertEqual(dummy._autostart_channel_pending_ids, {"wechat", "telegram"})
        self.assertEqual(dummy._autostart_channel_current, "wechat")

        dummy._stop_all_managed_channels(refresh=False)
        stale_done = dummy.callbacks["wechat"]
        stale_done(True)

        self.assertEqual(dummy.started, ["wechat"])
        self.assertFalse(dummy._autostart_channels_running)
        self.assertEqual(dummy._autostart_channel_pending_ids, set())
        self.assertEqual(dummy._autostart_channel_current, "")

    def test_remote_channel_start_drops_stale_context_before_ui_refresh(self):
        class ImmediateThread:
            def __init__(self, target=None, name=None, daemon=None):
                self._target = target

            def start(self):
                dummy._runtime_context_generation += 1
                if callable(self._target):
                    self._target()

        class DummyChannel(ChannelRuntimeMixin):
            _start_remote_channel_process = ChannelRuntimeMixin._start_remote_channel_process

            def __init__(self):
                self.agent_dir = "C:\\demo"
                self._runtime_context_generation = 1
                self._settings_target_change_token = 2
                self._qt_channel_extras = {}
                self._last_session_list_signature = "sig"
                self.calls = []
                self.statuses = []

            def _settings_target_generation(self):
                return self._settings_target_change_token

            def _channel_target_context(self):
                return True, {"id": "box-1"}, {"is_remote": True, "device_id": "box-1"}

            def _qt_channels_save(self, silent=True, apply_running=False):
                self.calls.append(("save", bool(silent), bool(apply_running)))
                return True

            def _channel_missing_required(self, channel_id, values):
                return []

            def _remote_channel_conflict_message(self, did, channel_id):
                return ""

            def _remote_start_channel_process_blocking(self, device, channel_id, spec):
                return True, "", {"pid": 321}

            def _set_status(self, text):
                self.statuses.append(str(text))

            def _force_remote_channel_sync(self):
                self.calls.append("sync")

            def _refresh_channels_runtime_status_labels(self):
                self.calls.append("refresh_labels")

            def _reload_channels_editor_state(self):
                self.calls.append("reload_editor")

            def _refresh_sessions(self):
                self.calls.append("refresh_sessions")

            def _channel_info(self, title, text, detail=""):
                self.calls.append(("info", str(title), str(text)))

            def _channel_warning(self, title, text, detail=""):
                self.calls.append(("warning", str(title), str(text)))

            def _channel_post_ui(self, callback, action_name="界面刷新"):
                if callable(callback):
                    callback()

        dummy = DummyChannel()
        with mock.patch.object(channel_runtime.threading, "Thread", ImmediateThread):
            self.assertTrue(dummy._start_remote_channel_process("wechat", show_errors=True))

        self.assertEqual(dummy.calls, [("save", True, False)])
        self.assertEqual(len(dummy.statuses), 1)
        self.assertIn("正在启动远端", dummy.statuses[0])

    def test_remote_channel_stop_drops_stale_context_before_ui_refresh(self):
        class ImmediateThread:
            def __init__(self, target=None, name=None, daemon=None):
                self._target = target

            def start(self):
                dummy._runtime_context_generation += 1
                if callable(self._target):
                    self._target()

        class DummyChannel(ChannelRuntimeMixin):
            _stop_remote_channel_process = ChannelRuntimeMixin._stop_remote_channel_process

            def __init__(self):
                self.agent_dir = "C:\\demo"
                self._runtime_context_generation = 4
                self._settings_target_change_token = 7
                self.calls = []
                self.statuses = []

            def _settings_target_generation(self):
                return self._settings_target_change_token

            def _channel_target_context(self):
                return True, {"id": "box-1"}, {"is_remote": True, "device_id": "box-1"}

            def _remote_stop_channel_process_blocking(self, device, channel_id):
                return True, "", {"was_running": True}

            def _set_status(self, text):
                self.statuses.append(str(text))

            def _force_remote_channel_sync(self):
                self.calls.append("sync")

            def _refresh_channels_runtime_status_labels(self):
                self.calls.append("refresh_labels")

            def _reload_channels_editor_state(self):
                self.calls.append("reload_editor")

            def _refresh_sessions(self):
                self.calls.append("refresh_sessions")

            def _channel_info(self, title, text, detail=""):
                self.calls.append(("info", str(title), str(text)))

            def _channel_warning(self, title, text, detail=""):
                self.calls.append(("warning", str(title), str(text)))

            def _channel_post_ui(self, callback, action_name="界面刷新"):
                if callable(callback):
                    callback()

        dummy = DummyChannel()
        with mock.patch.object(channel_runtime.threading, "Thread", ImmediateThread):
            self.assertTrue(dummy._stop_remote_channel_process("wechat"))

        self.assertEqual(dummy.calls, [])
        self.assertEqual(len(dummy.statuses), 1)
        self.assertIn("正在停止远端", dummy.statuses[0])

    def test_remote_channel_log_read_drops_stale_context_before_ui_refresh(self):
        class ImmediateThread:
            def __init__(self, target=None, name=None, daemon=None):
                self._target = target

            def start(self):
                dummy._runtime_context_generation += 1
                if callable(self._target):
                    self._target()

        class DummyChannel(ChannelRuntimeMixin):
            _show_remote_channel_log_tail = ChannelRuntimeMixin._show_remote_channel_log_tail

            def __init__(self):
                self.agent_dir = "C:\\demo"
                self._runtime_context_generation = 6
                self._settings_target_change_token = 8
                self.calls = []
                self.statuses = []

            def _settings_target_generation(self):
                return self._settings_target_change_token

            def _channel_target_context(self):
                return True, {"id": "box-1"}, {"is_remote": True, "device_id": "box-1"}

            def _remote_tail_channel_log_blocking(self, device, channel_id):
                return True, "tail content", "运行中", ""

            def _set_status(self, text):
                self.statuses.append(str(text))

            def _channel_info(self, title, text, detail=""):
                self.calls.append(("info", str(title), str(text), str(detail)))

            def _channel_warning(self, title, text, detail=""):
                self.calls.append(("warning", str(title), str(text), str(detail)))

            def _channel_post_ui(self, callback, action_name="界面刷新"):
                if callable(callback):
                    callback()

        dummy = DummyChannel()
        with mock.patch.object(channel_runtime.threading, "Thread", ImmediateThread):
            self.assertTrue(dummy._show_remote_channel_log_tail("wechat", "微信"))

        self.assertEqual(dummy.calls, [])
        self.assertEqual(len(dummy.statuses), 1)
        self.assertIn("正在读取远端", dummy.statuses[0])

    def test_remote_channel_start_reports_success_with_log_hint(self):
        class ImmediateThread:
            def __init__(self, target=None, name=None, daemon=None):
                self._target = target

            def start(self):
                if callable(self._target):
                    self._target()

        class DummyChannel(ChannelRuntimeMixin):
            _start_remote_channel_process = ChannelRuntimeMixin._start_remote_channel_process
            _remote_channel_label_text = ChannelRuntimeMixin._remote_channel_label_text

            def __init__(self):
                self.agent_dir = "C:\\demo"
                self._runtime_context_generation = 1
                self._settings_target_change_token = 2
                self._qt_channel_extras = {}
                self._last_session_list_signature = "sig"
                self.calls = []
                self.statuses = []

            def _settings_target_generation(self):
                return self._settings_target_change_token

            def _channel_target_context(self):
                return True, {"id": "box-1"}, {"is_remote": True, "device_id": "box-1"}

            def _qt_channels_save(self, silent=True, apply_running=False):
                self.calls.append(("save", bool(silent), bool(apply_running)))
                return True

            def _channel_missing_required(self, channel_id, values):
                return []

            def _remote_channel_conflict_message(self, did, channel_id):
                return ""

            def _remote_start_channel_process_blocking(self, device, channel_id, spec):
                return True, "", {"pid": 321}

            def _set_status(self, text):
                self.statuses.append(str(text))

            def _force_remote_channel_sync(self):
                self.calls.append("sync")

            def _refresh_channels_runtime_status_labels(self):
                self.calls.append("refresh_labels")

            def _reload_channels_editor_state(self):
                self.calls.append("reload_editor")

            def _refresh_sessions(self):
                self.calls.append("refresh_sessions")

            def _channel_info(self, title, text, detail=""):
                self.calls.append(("info", str(title), str(text)))

            def _channel_warning(self, title, text, detail=""):
                self.calls.append(("warning", str(title), str(text)))

            def _channel_post_ui(self, callback, action_name="界面刷新"):
                if callable(callback):
                    callback()

        dummy = DummyChannel()
        with mock.patch.object(channel_runtime.threading, "Thread", ImmediateThread):
            self.assertTrue(dummy._start_remote_channel_process("wechat", show_errors=True))

        self.assertEqual(
            dummy.statuses,
            [
                "正在启动远端 微信 渠道…",
                "已启动远端 微信 渠道（PID 321）；如无新消息可再查看远端日志。",
            ],
        )
        self.assertIn(("info", "启动成功", "远端 微信 已启动；如无响应可继续查看远端日志。"), dummy.calls)

    def test_remote_channel_start_reports_already_running_with_reuse_hint(self):
        class ImmediateThread:
            def __init__(self, target=None, name=None, daemon=None):
                self._target = target

            def start(self):
                if callable(self._target):
                    self._target()

        class DummyChannel(ChannelRuntimeMixin):
            _start_remote_channel_process = ChannelRuntimeMixin._start_remote_channel_process
            _remote_channel_label_text = ChannelRuntimeMixin._remote_channel_label_text

            def __init__(self):
                self.agent_dir = "C:\\demo"
                self._runtime_context_generation = 1
                self._settings_target_change_token = 2
                self._qt_channel_extras = {}
                self.calls = []
                self.statuses = []

            def _settings_target_generation(self):
                return self._settings_target_change_token

            def _channel_target_context(self):
                return True, {"id": "box-1"}, {"is_remote": True, "device_id": "box-1"}

            def _qt_channels_save(self, silent=True, apply_running=False):
                return True

            def _channel_missing_required(self, channel_id, values):
                return []

            def _remote_channel_conflict_message(self, did, channel_id):
                return ""

            def _remote_start_channel_process_blocking(self, device, channel_id, spec):
                return True, "", {"already_running": True, "pid": 321}

            def _set_status(self, text):
                self.statuses.append(str(text))

            def _force_remote_channel_sync(self):
                self.calls.append("sync")

            def _refresh_channels_runtime_status_labels(self):
                self.calls.append("refresh_labels")

            def _reload_channels_editor_state(self):
                self.calls.append("reload_editor")

            def _refresh_sessions(self):
                self.calls.append("refresh_sessions")

            def _channel_info(self, title, text, detail=""):
                self.calls.append(("info", str(title), str(text)))

            def _channel_warning(self, title, text, detail=""):
                self.calls.append(("warning", str(title), str(text)))

            def _channel_post_ui(self, callback, action_name="界面刷新"):
                if callable(callback):
                    callback()

        dummy = DummyChannel()
        with mock.patch.object(channel_runtime.threading, "Thread", ImmediateThread):
            self.assertTrue(dummy._start_remote_channel_process("wechat", show_errors=True))

        self.assertEqual(
            dummy.statuses,
            [
                "正在启动远端 微信 渠道…",
                "远端 微信 已在运行；当前会继续复用现有进程。",
            ],
        )
        self.assertIn(("info", "已在运行", "远端 微信 已在运行，无需重复启动；当前会继续复用现有进程。"), dummy.calls)

    def test_remote_channel_start_wechat_unbound_reopens_qr_before_retry(self):
        class ImmediateThread:
            def __init__(self, target=None, name=None, daemon=None):
                self._target = target

            def start(self):
                if callable(self._target):
                    self._target()

        class DummyChannel(ChannelRuntimeMixin):
            _start_remote_channel_process = ChannelRuntimeMixin._start_remote_channel_process
            _remote_channel_label_text = ChannelRuntimeMixin._remote_channel_label_text

            def __init__(self):
                self.agent_dir = "C:\\demo"
                self._runtime_context_generation = 1
                self._settings_target_change_token = 2
                self._qt_channel_extras = {}
                self.calls = []
                self.statuses = []
                self.start_attempts = 0

            def _settings_target_generation(self):
                return self._settings_target_change_token

            def _channel_target_context(self):
                return True, {"id": "box-1"}, {"is_remote": True, "device_id": "box-1"}

            def _qt_channels_save(self, silent=True, apply_running=False):
                self.calls.append(("save", bool(silent), bool(apply_running)))
                return True

            def _channel_missing_required(self, channel_id, values):
                return []

            def _remote_channel_conflict_message(self, did, channel_id):
                return ""

            def _remote_start_channel_process_blocking(self, device, channel_id, spec):
                self.start_attempts += 1
                if self.start_attempts == 1:
                    return False, "远端微信未绑定。", {}
                return True, "", {"pid": 456}

            def _open_wechat_qr_dialog(self, show_errors=True, remote_device=None):
                self.calls.append(("open_qr", bool(show_errors), dict(remote_device or {})))
                return True

            def _set_status(self, text):
                self.statuses.append(str(text))

            def _force_remote_channel_sync(self):
                self.calls.append("sync")

            def _refresh_channels_runtime_status_labels(self):
                self.calls.append("refresh_labels")

            def _reload_channels_editor_state(self):
                self.calls.append("reload_editor")

            def _refresh_sessions(self):
                self.calls.append("refresh_sessions")

            def _channel_info(self, title, text, detail=""):
                self.calls.append(("info", str(title), str(text)))

            def _channel_warning(self, title, text, detail=""):
                self.calls.append(("warning", str(title), str(text)))

            def _channel_post_ui(self, callback, action_name="界面刷新"):
                if callable(callback):
                    callback()

        dummy = DummyChannel()
        with mock.patch.object(channel_runtime.threading, "Thread", ImmediateThread):
            self.assertTrue(dummy._start_remote_channel_process("wechat", show_errors=True))

        self.assertEqual(dummy.start_attempts, 2)
        self.assertIn("远端微信未绑定，已转入远端扫码绑定；完成后会继续尝试启动。", dummy.statuses)
        self.assertIn(("open_qr", True, {"id": "box-1"}), dummy.calls)
        self.assertEqual(dummy.statuses[-1], "已启动远端 微信 渠道（PID 456）；如无新消息可再查看远端日志。")

    def test_remote_stop_blocking_reports_failure_when_process_still_running(self):
        class DummyChannel(ChannelRuntimeMixin):
            _remote_stop_channel_process_blocking = ChannelRuntimeMixin._remote_stop_channel_process_blocking

            def _remote_exec_json_script(self, device, script, timeout=80):
                return True, {"ok": True, "was_running": True, "stopped": False, "status": "停止失败"}, ""

        dummy = DummyChannel()
        ok, msg, payload = dummy._remote_stop_channel_process_blocking({"id": "box-1"}, "wechat")

        self.assertFalse(ok)
        self.assertEqual(msg, "远端停止失败，进程可能仍在运行。")
        self.assertEqual(payload["status"], "停止失败")

    def test_remote_channel_stop_reports_not_running_without_redundant_stop(self):
        class ImmediateThread:
            def __init__(self, target=None, name=None, daemon=None):
                self._target = target

            def start(self):
                if callable(self._target):
                    self._target()

        class DummyChannel(ChannelRuntimeMixin):
            _stop_remote_channel_process = ChannelRuntimeMixin._stop_remote_channel_process
            _remote_channel_label_text = ChannelRuntimeMixin._remote_channel_label_text

            def __init__(self):
                self.agent_dir = "C:\\demo"
                self._runtime_context_generation = 4
                self._settings_target_change_token = 7
                self.calls = []
                self.statuses = []

            def _settings_target_generation(self):
                return self._settings_target_change_token

            def _channel_target_context(self):
                return True, {"id": "box-1"}, {"is_remote": True, "device_id": "box-1"}

            def _remote_stop_channel_process_blocking(self, device, channel_id):
                return True, "", {"was_running": False}

            def _set_status(self, text):
                self.statuses.append(str(text))

            def _force_remote_channel_sync(self):
                self.calls.append("sync")

            def _refresh_channels_runtime_status_labels(self):
                self.calls.append("refresh_labels")

            def _reload_channels_editor_state(self):
                self.calls.append("reload_editor")

            def _refresh_sessions(self):
                self.calls.append("refresh_sessions")

            def _channel_info(self, title, text, detail=""):
                self.calls.append(("info", str(title), str(text)))

            def _channel_warning(self, title, text, detail=""):
                self.calls.append(("warning", str(title), str(text)))

            def _channel_post_ui(self, callback, action_name="界面刷新"):
                if callable(callback):
                    callback()

        dummy = DummyChannel()
        with mock.patch.object(channel_runtime.threading, "Thread", ImmediateThread):
            self.assertTrue(dummy._stop_remote_channel_process("wechat"))

        self.assertEqual(
            dummy.statuses,
            [
                "正在停止远端 微信 渠道…",
                "远端 微信 当前未运行；无需重复停止。",
            ],
        )
        self.assertIn(("info", "未运行", "远端 微信 当前未运行，无需重复停止。"), dummy.calls)

    def test_remote_channel_log_read_reports_tail_hint(self):
        class ImmediateThread:
            def __init__(self, target=None, name=None, daemon=None):
                self._target = target

            def start(self):
                if callable(self._target):
                    self._target()

        class DummyChannel(ChannelRuntimeMixin):
            _show_remote_channel_log_tail = ChannelRuntimeMixin._show_remote_channel_log_tail
            _remote_channel_log_loaded_status = ChannelRuntimeMixin._remote_channel_log_loaded_status

            def __init__(self):
                self.agent_dir = "C:\\demo"
                self._runtime_context_generation = 6
                self._settings_target_change_token = 8
                self.calls = []
                self.statuses = []

            def _settings_target_generation(self):
                return self._settings_target_change_token

            def _channel_target_context(self):
                return True, {"id": "box-1"}, {"is_remote": True, "device_id": "box-1"}

            def _remote_tail_channel_log_blocking(self, device, channel_id):
                return True, "tail content", "运行中", ""

            def _set_status(self, text):
                self.statuses.append(str(text))

            def _channel_info(self, title, text, detail=""):
                self.calls.append(("info", str(title), str(text), str(detail)))

            def _channel_warning(self, title, text, detail=""):
                self.calls.append(("warning", str(title), str(text), str(detail)))

            def _channel_post_ui(self, callback, action_name="界面刷新"):
                if callable(callback):
                    callback()

        dummy = DummyChannel()
        with mock.patch.object(channel_runtime.threading, "Thread", ImmediateThread):
            self.assertTrue(dummy._show_remote_channel_log_tail("wechat", "微信"))

        self.assertEqual(
            dummy.statuses,
            [
                "正在读取远端 微信 日志…",
                "已读取远端 微信 日志；可直接查看末尾输出继续排查。",
            ],
        )
        self.assertIn(("info", "微信 远端日志尾部", "状态：运行中；以下为远端日志末尾输出。", "tail content"), dummy.calls)

    def test_remote_channel_log_read_failure_explains_retry(self):
        class ImmediateThread:
            def __init__(self, target=None, name=None, daemon=None):
                self._target = target

            def start(self):
                if callable(self._target):
                    self._target()

        class DummyChannel(ChannelRuntimeMixin):
            _show_remote_channel_log_tail = ChannelRuntimeMixin._show_remote_channel_log_tail

            def __init__(self):
                self.agent_dir = "C:\\demo"
                self._runtime_context_generation = 6
                self._settings_target_change_token = 8
                self.calls = []
                self.statuses = []

            def _settings_target_generation(self):
                return self._settings_target_change_token

            def _channel_target_context(self):
                return True, {"id": "box-1"}, {"is_remote": True, "device_id": "box-1"}

            def _remote_tail_channel_log_blocking(self, device, channel_id):
                return False, "", "", "SSH 超时"

            def _set_status(self, text):
                self.statuses.append(str(text))

            def _channel_info(self, title, text, detail=""):
                self.calls.append(("info", str(title), str(text), str(detail)))

            def _channel_warning(self, title, text, detail=""):
                self.calls.append(("warning", str(title), str(text), str(detail)))

            def _channel_post_ui(self, callback, action_name="界面刷新"):
                if callable(callback):
                    callback()

        dummy = DummyChannel()
        with mock.patch.object(channel_runtime.threading, "Thread", ImmediateThread):
            self.assertTrue(dummy._show_remote_channel_log_tail("wechat", "微信"))

        self.assertEqual(
            dummy.statuses,
            [
                "正在读取远端 微信 日志…",
                "读取远端 微信 日志失败；请检查 SSH 连接后重试：SSH 超时",
            ],
        )
        self.assertIn(("warning", "读取失败", "读取远端 微信 日志失败；请检查 SSH 连接后重试：SSH 超时", ""), dummy.calls)

    def test_remote_channel_log_loaded_status_distinguishes_empty_tail(self):
        class DummyChannel(ChannelRuntimeMixin):
            _remote_channel_log_loaded_status = ChannelRuntimeMixin._remote_channel_log_loaded_status

        dummy = DummyChannel()
        self.assertEqual(dummy._remote_channel_log_loaded_status("微信", "tail"), "已读取远端 微信 日志；可直接查看末尾输出继续排查。")
        self.assertEqual(dummy._remote_channel_log_loaded_status("微信", ""), "已读取远端 微信 日志；当前还没有新的日志输出。")

    def test_after_channel_launch_check_drops_stale_context(self):
        class DummyProc:
            returncode = 9

            def poll(self):
                return self.returncode

        class DummyChannel(ChannelRuntimeMixin):
            _after_channel_launch_check = ChannelRuntimeMixin._after_channel_launch_check

            def __init__(self):
                self.agent_dir = "C:\\demo"
                self._runtime_context_generation = 5
                self._channel_procs = {"wechat": {"proc": DummyProc()}}
                self._last_session_list_signature = "sig"
                self.calls = []

            def _sync_channel_process_session(self, channel_id, final=False, exit_code=None):
                self.calls.append(("sync", channel_id, bool(final), exit_code))

            def _close_channel_log_handle(self, channel_id):
                self.calls.append(("close_log", channel_id))

            def _channel_tail_log(self, channel_id):
                return "tail"

            def _channel_set_external_running(self, channel_id, enabled, persist=False):
                self.calls.append(("external", channel_id, bool(enabled), bool(persist)))

            def _reload_channels_editor_state(self):
                self.calls.append("reload")

            def _refresh_sessions(self):
                self.calls.append("refresh_sessions")

            def _channel_warning(self, title, text, detail=""):
                self.calls.append(("warning", str(title), str(text), str(detail)))

        dummy = DummyChannel()
        stale_context = {"agent_dir": "C:\\demo", "runtime_generation": 4, "settings_target_generation": 0}
        dummy._after_channel_launch_check("wechat", show_errors=True, context=stale_context)

        self.assertEqual(dummy.calls, [])
        self.assertIn("wechat", dummy._channel_procs)

    def test_refresh_channel_runtime_status_disables_start_for_external_local_channel(self):
        class DummyLabel:
            def __init__(self):
                self.text = ""
                self.style = ""
                self.visible = None

            def setText(self, text):
                self.text = str(text)

            def setStyleSheet(self, style):
                self.style = str(style)

            def setVisible(self, visible):
                self.visible = bool(visible)

        class DummyButton:
            def __init__(self):
                self.enabled = None
                self.tooltip = ""
                self.text = ""

            def setEnabled(self, enabled):
                self.enabled = bool(enabled)

            def setToolTip(self, text):
                self.tooltip = str(text)

            def setText(self, text):
                self.text = str(text)

        class DummyChannel(ChannelRuntimeMixin):
            def __init__(self):
                self.agent_dir = "C:\\demo"
                self.cfg = {}
                self._qt_channel_extras = {}
                self._qt_channel_states = {
                    "wechat": {
                        "status_label": DummyLabel(),
                        "status_hint_label": DummyLabel(),
                        "start_btn": DummyButton(),
                        "stop_btn": DummyButton(),
                    }
                }

            def _channel_target_context(self):
                return False, None, {"is_remote": False}

            def _refresh_wechat_external_running(self, *, persist=False):
                return True

            def _channel_status(self, channel_id, values, *, target_ctx=None):
                return ("外部运行中", "#999999")

            def _channel_proc_alive(self, _channel_id):
                return False

            def _channel_external_running(self, channel_id):
                return str(channel_id) == "wechat"

            def _channel_conflict_message(self, _channel_id):
                return ""

            def _channel_missing_required(self, _channel_id, _values):
                return []

        dummy = DummyChannel()
        with mock.patch.object(channel_runtime.lz, "COMM_CHANNEL_SPECS", [{"id": "wechat", "fields": []}]), mock.patch.object(
            channel_runtime.lz, "is_valid_agent_dir", return_value=True
        ):
            dummy._refresh_channels_runtime_status_labels()

        state = dummy._qt_channel_states["wechat"]
        self.assertFalse(state["start_btn"].enabled)
        self.assertFalse(state["stop_btn"].enabled)
        self.assertEqual(state["status_label"].text, "外部运行中")
        self.assertIn("外部 微信 进程正在运行", state["start_btn"].tooltip)
        self.assertIn("启动器无法直接停止", state["stop_btn"].tooltip)

    def test_refresh_channel_runtime_status_sets_remote_button_tooltips_when_device_missing(self):
        class DummyLabel:
            def __init__(self):
                self.text = ""
                self.style = ""
                self.visible = None

            def setText(self, text):
                self.text = str(text)

            def setStyleSheet(self, style):
                self.style = str(style)

            def setVisible(self, visible):
                self.visible = bool(visible)

        class DummyButton:
            def __init__(self):
                self.enabled = None
                self.tooltip = ""
                self.text = ""

            def setEnabled(self, enabled):
                self.enabled = bool(enabled)

            def setToolTip(self, text):
                self.tooltip = str(text)

            def setText(self, text):
                self.text = str(text)

        class DummyChannel(ChannelRuntimeMixin):
            def __init__(self):
                self.agent_dir = "C:\\demo"
                self.cfg = {}
                self._qt_channel_extras = {}
                self._qt_channel_states = {
                    "wechat": {
                        "status_label": DummyLabel(),
                        "status_hint_label": DummyLabel(),
                        "start_btn": DummyButton(),
                        "stop_btn": DummyButton(),
                        "bind_btn": DummyButton(),
                        "log_btn": DummyButton(),
                        "detail_btn": DummyButton(),
                    }
                }

            def _settings_target_context(self):
                return {"is_remote": True, "device_id": "missing-box", "device": None}

            def _remote_channel_device_sync_state(self, _did):
                return {}

            def _channel_status(self, channel_id, values, *, target_ctx=None):
                return ("正在校验远端状态", "#999999")

            def _remote_channel_check_hint(self, did, cid):
                return "等待首次校验服务器状态。"

            def _remote_channel_is_running(self, did, cid):
                return False

        dummy = DummyChannel()
        with mock.patch.object(channel_runtime.lz, "COMM_CHANNEL_SPECS", [{"id": "wechat", "label": "微信", "fields": []}]):
            dummy._refresh_channels_runtime_status_labels()

        state = dummy._qt_channel_states["wechat"]
        self.assertFalse(state["start_btn"].enabled)
        self.assertFalse(state["stop_btn"].enabled)
        self.assertFalse(state["bind_btn"].enabled)
        self.assertFalse(state["log_btn"].enabled)
        self.assertFalse(state["detail_btn"].enabled)
        self.assertIn("远端设备信息不可用", state["start_btn"].tooltip)
        self.assertIn("远端设备信息不可用", state["stop_btn"].tooltip)
        self.assertIn("无法为 微信 打开远端扫码", state["bind_btn"].tooltip)
        self.assertIn("无法读取 微信 的远端状态或日志", state["log_btn"].tooltip)
        self.assertIn("无法读取 微信 的远端状态或日志", state["detail_btn"].tooltip)

    def test_reload_channels_editor_state_clears_stale_source_when_agent_dir_invalid(self):
        class DummyChannel(ChannelRuntimeMixin):
            _reload_channels_editor_state = ChannelRuntimeMixin._reload_channels_editor_state
            _reset_channels_source_state = ChannelRuntimeMixin._reset_channels_source_state

            def __init__(self):
                self.agent_dir = ""
                self.settings_channels_notice = mock.Mock()
                self.settings_channels_list_layout = object()
                self._qt_channel_py_path = "C:\\demo\\mykey.py"
                self._qt_channel_parse_error = ""
                self._qt_channel_configs = [{"id": "wechat"}]
                self._qt_channel_passthrough = ["old"]
                self._qt_channel_extras = {"bot_token": "abc"}
                self._qt_channel_states = {"wechat": {"start_btn": object()}}

            def _clear_layout(self, _layout):
                return None

            def _settings_target_context(self):
                return {"is_remote": False}

        dummy = DummyChannel()
        with mock.patch.object(channel_runtime.lz, "is_valid_agent_dir", return_value=False):
            dummy._reload_channels_editor_state()

        self.assertEqual(dummy._qt_channel_py_path, "")
        self.assertEqual(dummy._qt_channel_parse_error, "请先选择有效的 GenericAgent 目录。")
        self.assertEqual(dummy._qt_channel_configs, [])
        self.assertEqual(dummy._qt_channel_passthrough, [])
        self.assertEqual(dummy._qt_channel_extras, {})
        self.assertEqual(dummy._qt_channel_states, {})

    def test_reload_api_editor_state_clears_stale_source_when_agent_dir_invalid(self):
        class DummyApi(ApiEditorMixin):
            _reload_api_editor_state = ApiEditorMixin._reload_api_editor_state
            _reset_api_source_state = ApiEditorMixin._reset_api_source_state

            def __init__(self):
                self.agent_dir = ""
                self.settings_api_notice = mock.Mock()
                self.settings_api_list_layout = object()
                self._qt_api_py_path = "C:\\demo\\mykey.py"
                self._qt_api_parse_error = ""
                self._qt_api_hidden_configs = [{"var": "legacy", "kind": "custom", "data": {"x": 1}}]
                self._qt_api_state = [{"var": "claude", "kind": "native_claude"}]
                self._qt_api_extras = {"bot_token": "abc"}
                self._qt_api_passthrough = ["old"]

            def _clear_layout(self, _layout):
                return None

            def _settings_target_context(self):
                return {"is_remote": False}

        dummy = DummyApi()
        with mock.patch.object(lz, "is_valid_agent_dir", return_value=False):
            dummy._reload_api_editor_state()

        self.assertEqual(dummy._qt_api_py_path, "")
        self.assertEqual(dummy._qt_api_parse_error, "请先选择有效的 GenericAgent 目录。")
        self.assertEqual(dummy._qt_api_hidden_configs, [])
        self.assertEqual(dummy._qt_api_state, [])
        self.assertEqual(dummy._qt_api_extras, {})
        self.assertEqual(dummy._qt_api_passthrough, [])

    def test_apply_loaded_api_source_keeps_page_read_only_when_mykey_read_failed(self):
        class DummyApi(ApiEditorMixin):
            _apply_loaded_api_source = ApiEditorMixin._apply_loaded_api_source
            _reset_api_source_state = ApiEditorMixin._reset_api_source_state

            def __init__(self):
                self.settings_api_notice = mock.Mock()
                self._qt_api_py_path = "C:\\demo\\mykey.py"
                self._qt_api_parse_error = ""
                self._qt_api_hidden_configs = [{"var": "legacy", "kind": "custom", "data": {"x": 1}}]
                self._qt_api_state = [{"var": "claude", "kind": "native_claude"}]
                self._qt_api_extras = {"bot_token": "abc"}
                self._qt_api_passthrough = ["old"]
                self.render_calls = 0

            def _render_api_cards(self):
                self.render_calls += 1

        dummy = DummyApi()
        dummy._apply_loaded_api_source(
            "/remote/mykey.py",
            {"error": "SSH 连接失败", "configs": [], "extras": {}, "passthrough": [], "load_failed": True},
        )

        self.assertEqual(dummy._qt_api_py_path, "")
        self.assertEqual(dummy._qt_api_parse_error, "SSH 连接失败")
        self.assertEqual(dummy._qt_api_hidden_configs, [])
        self.assertEqual(dummy._qt_api_state, [])
        self.assertEqual(dummy._qt_api_extras, {})
        self.assertEqual(dummy._qt_api_passthrough, [])
        self.assertEqual(dummy.render_calls, 0)
        notice_text = dummy.settings_api_notice.setText.call_args[0][0]
        self.assertIn("/remote/mykey.py", notice_text)
        self.assertIn("当前读取失败：SSH 连接失败", notice_text)

    def test_refresh_api_source_actions_disables_remote_restart_and_load_failed_save(self):
        class DummyButton:
            def __init__(self):
                self.enabled = None
                self.tooltip = ""

            def setEnabled(self, enabled):
                self.enabled = bool(enabled)

            def setToolTip(self, text):
                self.tooltip = str(text)

        class DummyApi(ApiEditorMixin):
            _refresh_api_source_actions = ApiEditorMixin._refresh_api_source_actions
            _api_source_status = ApiEditorMixin._api_source_status
            _api_source_disabled_reason = ApiEditorMixin._api_source_disabled_reason
            _apply_api_button_state = ApiEditorMixin._apply_api_button_state

            def __init__(self, *, is_remote, status):
                self._qt_api_source_status = str(status)
                self.settings_api_add_btn = DummyButton()
                self.settings_api_save_btn = DummyButton()
                self.settings_api_restart_btn = DummyButton()
                self.settings_api_raw_btn = DummyButton()
                self._is_remote = bool(is_remote)

            def _settings_target_context(self):
                return {"is_remote": self._is_remote}

        remote_dummy = DummyApi(is_remote=True, status="ready")
        remote_dummy._refresh_api_source_actions()
        self.assertTrue(remote_dummy.settings_api_save_btn.enabled)
        self.assertFalse(remote_dummy.settings_api_restart_btn.enabled)
        self.assertIn("服务器侧重启对应进程", remote_dummy.settings_api_restart_btn.tooltip)
        self.assertEqual(remote_dummy.settings_api_add_btn.tooltip, "新增一张 API 配置卡片。")
        self.assertEqual(remote_dummy.settings_api_save_btn.tooltip, "把当前 API 配置写回 mykey.py。")
        self.assertEqual(remote_dummy.settings_api_raw_btn.tooltip, "直接编辑当前目标的 mykey.py 原文。")

        failed_dummy = DummyApi(is_remote=False, status="load_failed")
        failed_dummy._refresh_api_source_actions()
        self.assertFalse(failed_dummy.settings_api_add_btn.enabled)
        self.assertFalse(failed_dummy.settings_api_save_btn.enabled)
        self.assertFalse(failed_dummy.settings_api_restart_btn.enabled)
        self.assertTrue(failed_dummy.settings_api_raw_btn.enabled)
        self.assertIn("请先用“直接编辑文件”处理原文", failed_dummy.settings_api_add_btn.tooltip)
        self.assertIn("请先用“直接编辑文件”处理原文", failed_dummy.settings_api_save_btn.tooltip)
        self.assertIn("请先用“直接编辑文件”处理原文", failed_dummy.settings_api_restart_btn.tooltip)

    def test_refresh_api_source_actions_explains_invalid_dir_and_loading_states(self):
        class DummyButton:
            def __init__(self):
                self.enabled = None
                self.tooltip = ""

            def setEnabled(self, enabled):
                self.enabled = bool(enabled)

            def setToolTip(self, text):
                self.tooltip = str(text)

        class DummyApi(ApiEditorMixin):
            _refresh_api_source_actions = ApiEditorMixin._refresh_api_source_actions
            _api_source_status = ApiEditorMixin._api_source_status
            _api_source_disabled_reason = ApiEditorMixin._api_source_disabled_reason
            _apply_api_button_state = ApiEditorMixin._apply_api_button_state

            def __init__(self, *, status):
                self._qt_api_source_status = str(status)
                self.settings_api_add_btn = DummyButton()
                self.settings_api_save_btn = DummyButton()
                self.settings_api_restart_btn = DummyButton()
                self.settings_api_raw_btn = DummyButton()

            def _settings_target_context(self):
                return {"is_remote": False}

        invalid_dummy = DummyApi(status="invalid_dir")
        invalid_dummy._refresh_api_source_actions()
        self.assertFalse(invalid_dummy.settings_api_add_btn.enabled)
        self.assertFalse(invalid_dummy.settings_api_save_btn.enabled)
        self.assertFalse(invalid_dummy.settings_api_restart_btn.enabled)
        self.assertFalse(invalid_dummy.settings_api_raw_btn.enabled)
        self.assertEqual(invalid_dummy.settings_api_save_btn.tooltip, "请先选择有效的 GenericAgent 目录。")
        self.assertEqual(invalid_dummy.settings_api_raw_btn.tooltip, "请先选择有效的 GenericAgent 目录。")

        loading_dummy = DummyApi(status="loading")
        loading_dummy._refresh_api_source_actions()
        self.assertFalse(loading_dummy.settings_api_add_btn.enabled)
        self.assertFalse(loading_dummy.settings_api_save_btn.enabled)
        self.assertFalse(loading_dummy.settings_api_restart_btn.enabled)
        self.assertFalse(loading_dummy.settings_api_raw_btn.enabled)
        self.assertEqual(loading_dummy.settings_api_add_btn.tooltip, "正在读取当前目标的 mykey.py，请稍候。")
        self.assertEqual(loading_dummy.settings_api_raw_btn.tooltip, "正在读取当前目标的 mykey.py，请稍候。")

    def test_api_model_fetch_disabled_reason_explains_fetching_state(self):
        class DummyApi(ApiEditorMixin):
            _api_model_fetch_disabled_reason = ApiEditorMixin._api_model_fetch_disabled_reason

        dummy = DummyApi()
        self.assertEqual(dummy._api_model_fetch_disabled_reason({"model_fetching": True}), "当前正在拉取该配置的模型列表，请稍候。")
        self.assertEqual(dummy._api_model_fetch_disabled_reason({"model_fetching": False}), "")

    def test_qt_api_fetch_models_drops_result_when_state_is_no_longer_active(self):
        class ImmediateThread:
            def __init__(self, target=None, name=None, daemon=None):
                self._target = target

            def start(self):
                if callable(self._target):
                    self._target()

        class DummyApi(ApiEditorMixin):
            _qt_api_fetch_models = ApiEditorMixin._qt_api_fetch_models

            def __init__(self):
                self.agent_dir = "C:\\demo"
                self._runtime_context_generation = 1
                self._settings_target_change_token = 3
                self.render_calls = 0
                self.state = {
                    "format": "oai_chat",
                    "apibase": "https://api.example.com/v1",
                    "apikey": "k",
                    "model": "",
                    "model_choices": [],
                    "model_status": "",
                    "model_fetching": False,
                }
                self._qt_api_state = [self.state]

            def _settings_target_generation(self):
                return self._settings_target_change_token

            def _render_api_cards(self):
                self.render_calls += 1

            def _api_on_ui_thread(self, fn):
                self._qt_api_state = []
                fn()

        dummy = DummyApi()
        with mock.patch.object(api_editor.threading, "Thread", ImmediateThread), mock.patch.object(
            api_editor.lz, "_fetch_remote_models", return_value=["gpt-5"]
        ):
            dummy._qt_api_fetch_models(dummy.state)

        self.assertEqual(dummy.render_calls, 1)
        self.assertEqual(dummy._qt_api_state, [])
        self.assertEqual(dummy.state["model_status"], "正在拉取模型列表…")
        self.assertTrue(dummy.state["model_fetching"])

    def test_apply_loaded_channels_source_refreshes_local_wechat_state_before_render(self):
        class DummyChannel(ChannelRuntimeMixin):
            def __init__(self):
                self.agent_dir = "C:\\demo"
                self.cfg = {}
                self._channel_procs = {}
                self.settings_channels_notice = mock.Mock()
                self.calls = []

            def _settings_target_context(self):
                return {"is_remote": False}

            def _refresh_wechat_external_running(self, *, persist=False):
                self.calls.append("refresh_wechat")
                return True

            def _render_channel_cards(self):
                self.calls.append("render_cards")

            def _refresh_channels_runtime_status_labels(self):
                self.calls.append("refresh_runtime_labels")

        dummy = DummyChannel()
        dummy._apply_loaded_channels_source("C:\\demo\\mykey.py", {"error": "", "configs": [], "passthrough": [], "extras": {}})
        self.assertEqual(dummy.calls, ["refresh_wechat", "render_cards", "refresh_runtime_labels"])

    def test_apply_loaded_channels_source_keeps_page_read_only_when_mykey_read_failed(self):
        class DummyChannel(ChannelRuntimeMixin):
            _apply_loaded_channels_source = ChannelRuntimeMixin._apply_loaded_channels_source
            _reset_channels_source_state = ChannelRuntimeMixin._reset_channels_source_state

            def __init__(self):
                self.settings_channels_notice = mock.Mock()
                self._qt_channel_py_path = "C:\\demo\\mykey.py"
                self._qt_channel_parse_error = ""
                self._qt_channel_configs = [{"id": "wechat"}]
                self._qt_channel_passthrough = ["old"]
                self._qt_channel_extras = {"bot_token": "abc"}
                self._qt_channel_states = {"wechat": {"start_btn": object()}}
                self.calls = []

            def _render_channel_cards(self):
                self.calls.append("render_cards")

            def _refresh_channels_runtime_status_labels(self):
                self.calls.append("refresh_runtime_labels")

        dummy = DummyChannel()
        dummy._apply_loaded_channels_source(
            "/remote/mykey.py",
            {"error": "SSH 连接失败", "configs": [], "extras": {}, "passthrough": [], "load_failed": True},
        )

        self.assertEqual(dummy._qt_channel_py_path, "")
        self.assertEqual(dummy._qt_channel_parse_error, "SSH 连接失败")
        self.assertEqual(dummy._qt_channel_configs, [])
        self.assertEqual(dummy._qt_channel_passthrough, [])
        self.assertEqual(dummy._qt_channel_extras, {})
        self.assertEqual(dummy._qt_channel_states, {})
        self.assertEqual(dummy.calls, [])
        notice_text = dummy.settings_channels_notice.setText.call_args[0][0]
        self.assertIn("/remote/mykey.py", notice_text)
        self.assertIn("当前读取失败：SSH 连接失败", notice_text)

    def test_refresh_channel_source_actions_disables_remote_stop_all_and_load_failed_save(self):
        class DummyButton:
            def __init__(self):
                self.enabled = None
                self.tooltip = ""

            def setEnabled(self, enabled):
                self.enabled = bool(enabled)

            def setToolTip(self, text):
                self.tooltip = str(text)

        class DummyChannel(ChannelRuntimeMixin):
            _refresh_channel_source_actions = ChannelRuntimeMixin._refresh_channel_source_actions
            _channel_source_status = ChannelRuntimeMixin._channel_source_status
            _channel_source_action_disabled_reason = ChannelRuntimeMixin._channel_source_action_disabled_reason
            _apply_channel_button_state = ChannelRuntimeMixin._apply_channel_button_state

            def __init__(self, *, is_remote, status):
                self._qt_channel_source_status = str(status)
                self.settings_channels_save_btn = DummyButton()
                self.settings_channels_refresh_btn = DummyButton()
                self.settings_channels_stop_all_btn = DummyButton()
                self._is_remote = bool(is_remote)

            def _settings_target_context(self):
                return {"is_remote": self._is_remote}

        remote_dummy = DummyChannel(is_remote=True, status="ready")
        remote_dummy._refresh_channel_source_actions()
        self.assertTrue(remote_dummy.settings_channels_save_btn.enabled)
        self.assertFalse(remote_dummy.settings_channels_stop_all_btn.enabled)
        self.assertIn("远端目标", remote_dummy.settings_channels_stop_all_btn.tooltip)

        failed_dummy = DummyChannel(is_remote=False, status="load_failed")
        failed_dummy._refresh_channel_source_actions()
        self.assertFalse(failed_dummy.settings_channels_save_btn.enabled)
        self.assertTrue(failed_dummy.settings_channels_refresh_btn.enabled)
        self.assertTrue(failed_dummy.settings_channels_stop_all_btn.enabled)
        self.assertEqual(failed_dummy.settings_channels_save_btn.tooltip, "当前状态不可保存通讯配置。")
        self.assertEqual(failed_dummy.settings_channels_refresh_btn.tooltip, "重新读取当前目标的通讯配置。")

    def test_show_settings_category_forces_live_reload_for_dynamic_pages(self):
        class DummyStack:
            def __init__(self):
                self.current = None

            def setCurrentWidget(self, widget):
                self.current = widget

        class DummyButton:
            def __init__(self):
                self.styles = []

            def setStyleSheet(self, style):
                self.styles.append(style)

        class DummySettings(SettingsPanelMixin):
            def __init__(self):
                self.settings_stack = DummyStack()
                self._settings_pages = {"channels": {"widget": object()}, "vps": {"widget": object()}, "api": {"widget": object()}}
                self._settings_nav_buttons = {"channels": DummyButton(), "vps": DummyButton(), "api": DummyButton()}
                self.calls = []

            def _refresh_settings_target_visibility(self, key):
                self.calls.append(("visibility", key))

            def _sidebar_button_style(self, *, selected=False, subtle=False):
                if selected:
                    return "selected"
                if subtle:
                    return "subtle"
                return "default"

            def _settings_reload(self, *, categories=None, force=False):
                self.calls.append(("reload", list(categories or []), bool(force)))

        dummy = DummySettings()
        dummy._show_settings_category("channels", reload=True)
        self.assertIn(("reload", ["channels"], True), dummy.calls)

        dummy.calls.clear()
        dummy._show_settings_category("vps", reload=True)
        self.assertIn(("reload", ["vps"], True), dummy.calls)

        dummy.calls.clear()
        dummy._show_settings_category("api", reload=True)
        self.assertIn(("reload", ["api"], False), dummy.calls)

    def test_vps_disabled_reason_helpers_cover_connection_and_deploy_prerequisites(self):
        class DummySettings(SettingsPanelMixin):
            _normalize_vps_connection_cfg = SettingsPanelMixin._normalize_vps_connection_cfg
            _normalize_vps_deploy_cfg = SettingsPanelMixin._normalize_vps_deploy_cfg
            _vps_connection_incomplete_reason = SettingsPanelMixin._vps_connection_incomplete_reason
            _vps_auth_missing_reason = SettingsPanelMixin._vps_auth_missing_reason
            _vps_runtime_connection_disabled_reason = SettingsPanelMixin._vps_runtime_connection_disabled_reason
            _vps_deploy_validation_error = SettingsPanelMixin._vps_deploy_validation_error
            _validate_vps_docker_image_name = SettingsPanelMixin._validate_vps_docker_image_name

            def __init__(self):
                self.cfg = {}

            def _collect_vps_form_data(self):
                return {}

            def _collect_vps_deploy_form_data(self):
                return {}

        dummy = DummySettings()
        self.assertEqual(dummy._vps_connection_incomplete_reason({}), "请先填写服务器地址和用户名。")
        self.assertEqual(
            dummy._vps_connection_incomplete_reason({"host": "10.0.0.8"}),
            "服务器地址和用户名需要同时填写。",
        )
        self.assertEqual(
            dummy._vps_runtime_connection_disabled_reason({"host": "10.0.0.8", "username": "root"}),
            "请至少提供 SSH 私钥路径或密码。",
        )
        with mock.patch.object(settings_panel.os.path, "isfile", return_value=False):
            self.assertEqual(
                dummy._vps_auth_missing_reason(
                    {"host": "10.0.0.8", "username": "root", "ssh_key_path": "keys/missing.pem"}
                ),
                "SSH 私钥路径不存在，请检查后重试。",
            )
        self.assertEqual(
            dummy._vps_deploy_validation_error(
                {
                    "source": "git",
                    "remote_dir": "/srv/genericagent",
                    "docker_image": "genericagent",
                    "docker_container": "",
                    "repo_url": "https://example.com/repo.git",
                }
            ),
            "请先填写容器名称。",
        )
        self.assertEqual(
            dummy._vps_deploy_validation_error(
                {
                    "source": "git",
                    "remote_dir": "/srv/genericagent",
                    "docker_image": "GenericAgent",
                    "docker_container": "genericagent",
                    "repo_url": "https://example.com/repo.git",
                }
            ),
            "镜像名称的仓库部分必须全小写，例如 `genericagent` 或 `registry.example.com/team/genericagent:latest`。",
        )
        with mock.patch.object(settings_panel.os.path, "isdir", return_value=False):
            self.assertEqual(
                dummy._vps_deploy_validation_error(
                    {
                        "source": "upload",
                        "remote_dir": "/srv/genericagent",
                        "docker_image": "genericagent",
                        "docker_container": "genericagent",
                        "local_agent_dir": "missing-agent",
                    }
                ),
                "上传模式下，本地 agant 目录不存在。",
            )
        self.assertEqual(
            dummy._vps_deploy_validation_error(
                {
                    "source": "git",
                    "remote_dir": "/srv/genericagent",
                    "docker_image": "genericagent",
                    "docker_container": "genericagent",
                    "repo_url": "https://example.com/repo.git",
                    "dep_install_mode": "mirror",
                    "pip_mirror_url": "ftp://mirror.example.com/simple",
                }
            ),
            "pip 镜像地址格式无效，请填写 http(s) URL。",
        )

    def test_refresh_vps_action_buttons_explains_missing_profiles_and_busy_states(self):
        class DummyWidget:
            def __init__(self):
                self.enabled = None
                self.tooltip = ""
                self.text = ""

            def setEnabled(self, enabled):
                self.enabled = bool(enabled)

            def setToolTip(self, text):
                self.tooltip = str(text)

            def setText(self, text):
                self.text = str(text)

        class DummySettings(SettingsPanelMixin):
            _refresh_vps_action_buttons = SettingsPanelMixin._refresh_vps_action_buttons
            _apply_vps_button_state = SettingsPanelMixin._apply_vps_button_state
            _normalize_vps_connection_cfg = SettingsPanelMixin._normalize_vps_connection_cfg
            _normalize_vps_deploy_cfg = SettingsPanelMixin._normalize_vps_deploy_cfg
            _vps_busy_reason = SettingsPanelMixin._vps_busy_reason
            _vps_connection_incomplete_reason = SettingsPanelMixin._vps_connection_incomplete_reason
            _vps_auth_missing_reason = SettingsPanelMixin._vps_auth_missing_reason
            _vps_runtime_connection_disabled_reason = SettingsPanelMixin._vps_runtime_connection_disabled_reason
            _vps_terminal_connect_disabled_reason = SettingsPanelMixin._vps_terminal_connect_disabled_reason
            _vps_terminal_disconnect_disabled_reason = SettingsPanelMixin._vps_terminal_disconnect_disabled_reason
            _vps_terminal_send_disabled_reason = SettingsPanelMixin._vps_terminal_send_disabled_reason
            _vps_deploy_validation_error = SettingsPanelMixin._vps_deploy_validation_error
            _vps_deploy_disabled_reason = SettingsPanelMixin._vps_deploy_disabled_reason
            _vps_profile_action_disabled_reason = SettingsPanelMixin._vps_profile_action_disabled_reason
            _validate_vps_docker_image_name = SettingsPanelMixin._validate_vps_docker_image_name

            def __init__(self):
                self.cfg = {}
                self._profiles = []
                self._form_data = {}
                self._deploy_data = {}
                self._vps_form_profile_id = ""
                self._vps_connect_running = False
                self._vps_dep_install_running = False
                self._vps_terminal_connecting = False
                self._vps_terminal_connected = False
                self._vps_deploy_running = False
                self._vps_terminal_profile_id = ""
                self._vps_terminal_channel = None
                self.settings_vps_save_btn = DummyWidget()
                self.settings_vps_install_dep_btn = DummyWidget()
                self.settings_vps_test_btn = DummyWidget()
                self.settings_vps_terminal_connect_btn = DummyWidget()
                self.settings_vps_terminal_disconnect_btn = DummyWidget()
                self.settings_vps_terminal_send_btn = DummyWidget()
                self.settings_vps_terminal_input = DummyWidget()
                self.settings_vps_deploy_btn = DummyWidget()
                self.settings_vps_profile_combo = DummyWidget()
                self.settings_vps_profile_new_btn = DummyWidget()
                self.settings_vps_profile_rename_btn = DummyWidget()
                self.settings_vps_profile_delete_btn = DummyWidget()

            def _vps_profiles(self):
                return list(self._profiles)

            def _collect_vps_form_data(self):
                return dict(self._form_data)

            def _collect_vps_deploy_form_data(self):
                return dict(self._deploy_data)

            def _current_vps_profile_id(self):
                return str(self._vps_form_profile_id or "")

        empty_dummy = DummySettings()
        empty_dummy._refresh_vps_action_buttons()
        self.assertFalse(empty_dummy.settings_vps_save_btn.enabled)
        self.assertEqual(empty_dummy.settings_vps_save_btn.tooltip, "请先新建至少一个服务器配置。")
        self.assertFalse(empty_dummy.settings_vps_profile_combo.enabled)
        self.assertEqual(empty_dummy.settings_vps_profile_combo.tooltip, "当前还没有服务器配置可切换。")
        self.assertTrue(empty_dummy.settings_vps_profile_new_btn.enabled)
        self.assertFalse(empty_dummy.settings_vps_terminal_disconnect_btn.enabled)
        self.assertEqual(empty_dummy.settings_vps_terminal_disconnect_btn.tooltip, "当前没有已连接的远程终端。")
        self.assertFalse(empty_dummy.settings_vps_terminal_send_btn.enabled)
        self.assertEqual(empty_dummy.settings_vps_terminal_send_btn.tooltip, "请先连接远程终端。")

        busy_dummy = DummySettings()
        busy_dummy._profiles = [{"id": "srv-1"}]
        busy_dummy._form_data = {"host": "10.0.0.8", "username": "root", "password": "pw"}
        busy_dummy._deploy_data = {
            "source": "git",
            "repo_url": "https://example.com/repo.git",
            "remote_dir": "/srv/genericagent",
            "docker_image": "genericagent",
            "docker_container": "genericagent",
        }
        busy_dummy._vps_dep_install_running = True
        busy_dummy._refresh_vps_action_buttons()
        self.assertEqual(busy_dummy.settings_vps_install_dep_btn.text, "安装中…")
        self.assertFalse(busy_dummy.settings_vps_save_btn.enabled)
        self.assertEqual(busy_dummy.settings_vps_save_btn.tooltip, "正在安装 SSH 依赖，请等待当前任务完成。")
        self.assertFalse(busy_dummy.settings_vps_profile_new_btn.enabled)
        self.assertEqual(busy_dummy.settings_vps_profile_new_btn.tooltip, "正在安装 SSH 依赖，请等待当前任务完成。")
        self.assertFalse(busy_dummy.settings_vps_terminal_send_btn.enabled)
        self.assertEqual(busy_dummy.settings_vps_terminal_send_btn.tooltip, "正在安装 SSH 依赖，请等待当前任务完成。")

    def test_refresh_vps_action_buttons_handles_cross_server_terminal_and_deploy_validation(self):
        class DummyWidget:
            def __init__(self):
                self.enabled = None
                self.tooltip = ""
                self.text = ""

            def setEnabled(self, enabled):
                self.enabled = bool(enabled)

            def setToolTip(self, text):
                self.tooltip = str(text)

            def setText(self, text):
                self.text = str(text)

        class DummySettings(SettingsPanelMixin):
            _refresh_vps_action_buttons = SettingsPanelMixin._refresh_vps_action_buttons
            _apply_vps_button_state = SettingsPanelMixin._apply_vps_button_state
            _normalize_vps_connection_cfg = SettingsPanelMixin._normalize_vps_connection_cfg
            _normalize_vps_deploy_cfg = SettingsPanelMixin._normalize_vps_deploy_cfg
            _vps_busy_reason = SettingsPanelMixin._vps_busy_reason
            _vps_connection_incomplete_reason = SettingsPanelMixin._vps_connection_incomplete_reason
            _vps_auth_missing_reason = SettingsPanelMixin._vps_auth_missing_reason
            _vps_runtime_connection_disabled_reason = SettingsPanelMixin._vps_runtime_connection_disabled_reason
            _vps_terminal_connect_disabled_reason = SettingsPanelMixin._vps_terminal_connect_disabled_reason
            _vps_terminal_disconnect_disabled_reason = SettingsPanelMixin._vps_terminal_disconnect_disabled_reason
            _vps_terminal_send_disabled_reason = SettingsPanelMixin._vps_terminal_send_disabled_reason
            _vps_deploy_validation_error = SettingsPanelMixin._vps_deploy_validation_error
            _vps_deploy_disabled_reason = SettingsPanelMixin._vps_deploy_disabled_reason
            _vps_profile_action_disabled_reason = SettingsPanelMixin._vps_profile_action_disabled_reason
            _validate_vps_docker_image_name = SettingsPanelMixin._validate_vps_docker_image_name

            def __init__(self):
                self.cfg = {}
                self._profiles = [{"id": "srv-2"}]
                self._form_data = {"host": "10.0.0.9", "username": "root", "password": "pw"}
                self._deploy_data = {
                    "source": "upload",
                    "local_agent_dir": "missing-agent",
                    "remote_dir": "/srv/genericagent",
                    "docker_image": "genericagent",
                    "docker_container": "genericagent",
                }
                self._vps_form_profile_id = "srv-2"
                self._vps_connect_running = False
                self._vps_dep_install_running = False
                self._vps_terminal_connecting = False
                self._vps_terminal_connected = True
                self._vps_deploy_running = False
                self._vps_terminal_profile_id = "srv-1"
                self._vps_terminal_channel = object()
                self.settings_vps_save_btn = DummyWidget()
                self.settings_vps_install_dep_btn = DummyWidget()
                self.settings_vps_test_btn = DummyWidget()
                self.settings_vps_terminal_connect_btn = DummyWidget()
                self.settings_vps_terminal_disconnect_btn = DummyWidget()
                self.settings_vps_terminal_send_btn = DummyWidget()
                self.settings_vps_terminal_input = DummyWidget()
                self.settings_vps_deploy_btn = DummyWidget()
                self.settings_vps_profile_combo = DummyWidget()
                self.settings_vps_profile_new_btn = DummyWidget()
                self.settings_vps_profile_rename_btn = DummyWidget()
                self.settings_vps_profile_delete_btn = DummyWidget()

            def _vps_profiles(self):
                return list(self._profiles)

            def _collect_vps_form_data(self):
                return dict(self._form_data)

            def _collect_vps_deploy_form_data(self):
                return dict(self._deploy_data)

            def _current_vps_profile_id(self):
                return str(self._vps_form_profile_id or "")

        dummy = DummySettings()
        with mock.patch.object(settings_panel.os.path, "isdir", return_value=False):
            dummy._refresh_vps_action_buttons()
        self.assertFalse(dummy.settings_vps_terminal_connect_btn.enabled)
        self.assertIn("另一台服务器", dummy.settings_vps_terminal_connect_btn.tooltip)
        self.assertTrue(dummy.settings_vps_terminal_disconnect_btn.enabled)
        self.assertTrue(dummy.settings_vps_terminal_send_btn.enabled)
        self.assertTrue(dummy.settings_vps_terminal_input.enabled)
        self.assertFalse(dummy.settings_vps_deploy_btn.enabled)
        self.assertEqual(dummy.settings_vps_deploy_btn.tooltip, "上传模式下，本地 agant 目录不存在。")

    def test_sync_draft_from_floating_propagates_empty_text_back_to_main_editor(self):
        class DummyEditor:
            def __init__(self, text=""):
                self._text = str(text)

            def toPlainText(self):
                return self._text

            def setPlainText(self, text):
                self._text = str(text)

        class DummyFloating:
            def __init__(self, text=""):
                self.input_box = DummyEditor(text)

        class DummyHost:
            def __init__(self):
                self._floating_chat_window = DummyFloating("")
                self.input_box = DummyEditor("stale draft")

        dummy = DummyHost()
        launcher_window.QtChatWindow._sync_draft_from_floating(dummy)
        self.assertEqual(dummy.input_box.toPlainText(), "")

    def test_refresh_composer_enabled_explains_channel_remote_and_busy_states(self):
        class DummyInput:
            def __init__(self):
                self.read_only = None
                self.placeholder = ""
                self.tooltip = ""

            def setReadOnly(self, value):
                self.read_only = bool(value)

            def setPlaceholderText(self, text):
                self.placeholder = str(text)

            def setToolTip(self, text):
                self.tooltip = str(text)

        class DummyWidget:
            def __init__(self):
                self.enabled = None
                self.tooltip = ""

            def setEnabled(self, enabled):
                self.enabled = bool(enabled)

            def setToolTip(self, text):
                self.tooltip = str(text)

        class DummySession(SessionShellMixin):
            _refresh_composer_enabled = SessionShellMixin._refresh_composer_enabled
            _apply_composer_widget_state = SessionShellMixin._apply_composer_widget_state
            _composer_send_disabled_reason = SessionShellMixin._composer_send_disabled_reason
            _composer_stop_disabled_reason = SessionShellMixin._composer_stop_disabled_reason
            _composer_llm_disabled_reason = SessionShellMixin._composer_llm_disabled_reason

            def __init__(self, *, channel_process=False, remote=False, busy=False, abort_requested=False, llms=None):
                self._channel_process = bool(channel_process)
                self._remote = bool(remote)
                self._busy = bool(busy)
                self._abort_requested = bool(abort_requested)
                self.llms = list(llms or [])
                self.input_box = DummyInput()
                self.send_btn = DummyWidget()
                self.stop_btn = DummyWidget()
                self.llm_combo = DummyWidget()
                self.sync_calls = 0
                self.refresh_calls = 0

            def _is_channel_process_session(self, session=None):
                return self._channel_process

            def _is_remote_session(self):
                return self._remote

            def _sync_floating_llm_combo(self):
                self.sync_calls += 1

            def _refresh_floating_chat_window(self):
                self.refresh_calls += 1

        channel_dummy = DummySession(channel_process=True, llms=[{"idx": 0}])
        channel_dummy._refresh_composer_enabled()
        self.assertTrue(channel_dummy.input_box.read_only)
        self.assertIn("不能在这里继续发送消息", channel_dummy.input_box.placeholder)
        self.assertFalse(channel_dummy.send_btn.enabled)
        self.assertEqual(channel_dummy.send_btn.tooltip, "渠道进程会话仅用于回顾日志与快照，不能在这里继续发送消息。")
        self.assertFalse(channel_dummy.stop_btn.enabled)
        self.assertEqual(channel_dummy.stop_btn.tooltip, "渠道进程会话仅用于回顾日志与快照，不能在这里停止任务。")
        self.assertFalse(channel_dummy.llm_combo.enabled)
        self.assertEqual(channel_dummy.llm_combo.tooltip, "渠道进程会话仅支持查看日志，不能切换模型。")

        remote_busy_dummy = DummySession(remote=True, busy=True, llms=[{"idx": 0}])
        remote_busy_dummy._refresh_composer_enabled()
        self.assertFalse(remote_busy_dummy.send_btn.enabled)
        self.assertEqual(remote_busy_dummy.send_btn.tooltip, "当前正在等待模型回复，请稍候或先停止当前任务。")
        self.assertFalse(remote_busy_dummy.stop_btn.enabled)
        self.assertEqual(remote_busy_dummy.stop_btn.tooltip, "当前会话在远程设备执行，这里不支持直接停止远端任务。")
        self.assertTrue(remote_busy_dummy.llm_combo.enabled)
        self.assertEqual(remote_busy_dummy.llm_combo.tooltip, "切换当前会话使用的模型。")
        self.assertIn("远程设备执行", remote_busy_dummy.input_box.placeholder)

        local_idle_dummy = DummySession(remote=False, busy=False, llms=[])
        local_idle_dummy._refresh_composer_enabled()
        self.assertTrue(local_idle_dummy.send_btn.enabled)
        self.assertEqual(local_idle_dummy.send_btn.tooltip, "发送当前输入内容。")
        self.assertFalse(local_idle_dummy.stop_btn.enabled)
        self.assertEqual(local_idle_dummy.stop_btn.tooltip, "当前没有正在执行的本地回复任务。")
        self.assertFalse(local_idle_dummy.llm_combo.enabled)
        self.assertEqual(local_idle_dummy.llm_combo.tooltip, "当前还没有可用的 LLM 配置。")

    def test_sync_draft_to_floating_force_uses_main_editor_as_source_of_truth(self):
        class DummyEditor:
            def __init__(self, text=""):
                self._text = str(text)

            def toPlainText(self):
                return self._text

            def setPlainText(self, text):
                self._text = str(text)

        class DummyFloating:
            def __init__(self, text=""):
                self.input_box = DummyEditor(text)

        class DummyHost:
            def __init__(self):
                self._floating_chat_window = DummyFloating("stale floating draft")
                self.input_box = DummyEditor("")

        dummy = DummyHost()
        launcher_window.QtChatWindow._sync_draft_to_floating(dummy, force=True)
        self.assertEqual(dummy._floating_chat_window.input_box.toPlainText(), "")

    def test_floating_window_clamp_uses_target_screen_geometry_for_saved_position(self):
        class DummyScreen:
            def __init__(self, rect):
                self._rect = rect

            def availableGeometry(self):
                return self._rect

        class DummyFloating:
            _available_geometry_for_target = launcher_window.FloatingOrbWindow._available_geometry_for_target
            _clamp_pos = launcher_window.FloatingOrbWindow._clamp_pos

            def __init__(self, fallback_screen):
                self._fallback_screen = fallback_screen

            def _best_screen_for_window(self):
                return self._fallback_screen

            def geometry(self):
                return launcher_window.QRect(0, 0, 300, 300)

        primary = DummyScreen(launcher_window.QRect(0, 0, 1920, 1080))
        secondary = DummyScreen(launcher_window.QRect(1920, 0, 1440, 900))
        dummy = DummyFloating(primary)

        def fake_screen_at(point):
            return secondary if int(point.x()) >= 1920 else primary

        with mock.patch.object(launcher_window.QGuiApplication, "screenAt", side_effect=fake_screen_at):
            clamped = dummy._clamp_pos(launcher_window.QPoint(2500, 120), launcher_window.QSize(56, 56))

        self.assertGreaterEqual(clamped.x(), 1920 + 12)
        self.assertLessEqual(clamped.x(), (1920 + 1440) - 56 - 12)

    def test_floating_expand_panel_focuses_input_when_editable(self):
        class DummyPanel:
            def show(self):
                return None

        class DummyBall:
            def show(self):
                return None

        class DummyEditor:
            def __init__(self):
                self.focus_calls = []

            def isReadOnly(self):
                return False

            def setFocus(self, reason):
                self.focus_calls.append(reason)

        class DummyFloating:
            expand_panel = launcher_window.FloatingOrbWindow.expand_panel

            def __init__(self):
                self._expanded = False
                self.panel = DummyPanel()
                self.ball_btn = DummyBall()
                self._expanded_size = launcher_window.QSize(480, 760)
                self.input_box = DummyEditor()
                self.calls = []

            def _apply_window_size(self, size):
                self.calls.append(("size", size.width(), size.height()))

            def _place_ball(self):
                self.calls.append("place_ball")

            def _apply_native_window_style(self):
                self.calls.append("native_style")

            def raise_(self):
                self.calls.append("raise")

            def activateWindow(self):
                self.calls.append("activate")

            def _scroll_to_bottom(self):
                self.calls.append("scroll_bottom")

            def update(self):
                self.calls.append("update")

        dummy = DummyFloating()
        with mock.patch.object(launcher_window.QTimer, "singleShot", side_effect=lambda _ms, cb: cb()):
            dummy.expand_panel()

        self.assertTrue(dummy._expanded)
        self.assertTrue(dummy.input_box.focus_calls)

    def test_restore_from_tray_mode_focuses_main_input_when_editable(self):
        class DummyEditor:
            def __init__(self):
                self.focus_calls = []

            def setFocus(self, reason):
                self.focus_calls.append(reason)

        class DummyFloating:
            def hide(self):
                return None

        class DummyHost:
            def __init__(self):
                self._tray_mode_active = True
                self._tray_restore_to_fullscreen = False
                self._floating_chat_window = DummyFloating()
                self.input_box = DummyEditor()
                self.calls = []

            def isVisible(self):
                return False

            def _sync_draft_from_floating(self):
                self.calls.append("sync_from_floating")

            def showNormal(self):
                self.calls.append("show_normal")

            def showFullScreen(self):
                self.calls.append("show_fullscreen")

            def raise_(self):
                self.calls.append("raise")

            def activateWindow(self):
                self.calls.append("activate")

            def _show_chat_page(self):
                self.calls.append("show_chat_page")

            def _refresh_floating_chat_window(self):
                self.calls.append("refresh_floating")

            def _refresh_launcher_tray_menu(self):
                self.calls.append("refresh_tray")

            def _is_channel_process_session(self):
                return False

        dummy = DummyHost()
        with mock.patch.object(launcher_window.QTimer, "singleShot", side_effect=lambda _ms, cb: cb()):
            launcher_window.QtChatWindow._restore_from_tray_mode(dummy)

        self.assertFalse(dummy._tray_mode_active)
        self.assertEqual(dummy.input_box.focus_calls, [launcher_window.Qt.OtherFocusReason])

    def test_show_floating_chat_window_only_preserves_maximized_restore_state(self):
        class DummyHost:
            _show_floating_chat_window_only = launcher_window.QtChatWindow._show_floating_chat_window_only

            def __init__(self):
                self._tray_restore_to_fullscreen = False
                self._tray_restore_to_maximized = False
                self._tray_mode_active = False
                self.calls = []
                self._visible = True

            def isFullScreen(self):
                return False

            def isMaximized(self):
                return True

            def isVisible(self):
                return self._visible

            def _show_floating_chat_window(self):
                self.calls.append("show_floating")

            def hide(self):
                self._visible = False
                self.calls.append("hide")

            def _refresh_floating_chat_window(self):
                self.calls.append("refresh_floating")

        dummy = DummyHost()
        launcher_window.QtChatWindow._show_floating_chat_window_only(dummy)

        self.assertFalse(dummy._tray_restore_to_fullscreen)
        self.assertTrue(dummy._tray_restore_to_maximized)
        self.assertTrue(dummy._tray_mode_active)
        self.assertEqual(dummy.calls, ["show_floating", "hide", "refresh_floating"])

    def test_show_floating_chat_window_falls_back_without_tray_on_macos(self):
        class DummyFloating:
            def __init__(self):
                self.calls = []

            def show(self):
                self.calls.append("show")

            def raise_(self):
                self.calls.append("raise")

            def activateWindow(self):
                self.calls.append("activate")

        class DummyHost:
            _show_floating_chat_window = launcher_window.QtChatWindow._show_floating_chat_window

            def __init__(self):
                self._tray_mode_active = True
                self.calls = []
                self.statuses = []
                self.win = DummyFloating()

            def _ensure_launcher_tray_icon(self):
                return None

            def _ensure_floating_default_session(self):
                self.calls.append("ensure_default_session")

            def _ensure_floating_chat_window(self):
                self.calls.append("ensure_floating_window")
                return self.win

            def _sync_draft_to_floating(self, *, force=False):
                self.calls.append(("sync_draft", bool(force)))

            def _refresh_floating_chat_window(self):
                self.calls.append("refresh_floating")

            def _focus_floating_input_if_possible(self):
                self.calls.append("focus_floating")

            def _refresh_launcher_tray_menu(self):
                self.calls.append("refresh_tray")

            def _set_status(self, text):
                self.statuses.append(str(text))

        dummy = DummyHost()
        with mock.patch.object(launcher_window.lz, "IS_MACOS", True), mock.patch.object(
            launcher_window.QMessageBox, "warning"
        ) as warning_box:
            launcher_window.QtChatWindow._show_floating_chat_window(dummy)

        self.assertFalse(dummy._tray_mode_active)
        self.assertEqual(
            dummy.calls,
            [
                "ensure_default_session",
                "ensure_floating_window",
                ("sync_draft", True),
                "refresh_floating",
                "focus_floating",
                "refresh_tray",
            ],
        )
        self.assertEqual(dummy.win.calls, ["show", "raise", "activate"])
        self.assertEqual(dummy.statuses, ["当前系统未提供托盘图标，已直接打开悬浮窗。"])
        warning_box.assert_not_called()

    def test_show_floating_chat_window_keeps_tray_mode_inactive_when_main_window_visible(self):
        class DummyTray:
            def __init__(self):
                self.calls = []

            def show(self):
                self.calls.append("show")

        class DummyFloating:
            def __init__(self):
                self.calls = []

            def show(self):
                self.calls.append("show")

            def raise_(self):
                self.calls.append("raise")

            def activateWindow(self):
                self.calls.append("activate")

        class DummyHost:
            _show_floating_chat_window = launcher_window.QtChatWindow._show_floating_chat_window

            def __init__(self):
                self._tray_mode_active = False
                self.calls = []
                self.tray = DummyTray()
                self.win = DummyFloating()

            def isVisible(self):
                return True

            def _ensure_launcher_tray_icon(self):
                return self.tray

            def _ensure_floating_default_session(self):
                self.calls.append("ensure_default_session")

            def _ensure_floating_chat_window(self):
                self.calls.append("ensure_floating_window")
                return self.win

            def _sync_draft_to_floating(self, *, force=False):
                self.calls.append(("sync_draft", bool(force)))

            def _refresh_floating_chat_window(self):
                self.calls.append("refresh_floating")

            def _focus_floating_input_if_possible(self):
                self.calls.append("focus_floating")

            def _refresh_launcher_tray_menu(self):
                self.calls.append("refresh_tray")

        dummy = DummyHost()
        launcher_window.QtChatWindow._show_floating_chat_window(dummy)

        self.assertFalse(dummy._tray_mode_active)
        self.assertEqual(dummy.tray.calls, ["show"])
        self.assertEqual(dummy.win.calls, ["show", "raise", "activate"])

    def test_show_floating_chat_window_only_refreshes_status_and_tooltip_after_hiding_main_window(self):
        class DummyStatus:
            def text(self):
                return ""

        class DummyFloating:
            def __init__(self, host):
                self._host = host
                self.tooltip = ""
                self.kwargs = None

            def refresh_action_texts(self):
                self.tooltip = self._host._floating_hide_action_tooltip()

            def sync_view(self, **kwargs):
                self.kwargs = dict(kwargs)

        class DummyHost:
            _show_floating_chat_window_only = launcher_window.QtChatWindow._show_floating_chat_window_only
            _refresh_floating_chat_window = launcher_window.QtChatWindow._refresh_floating_chat_window
            _floating_default_status_text = launcher_window.QtChatWindow._floating_default_status_text
            _floating_hide_action_tooltip = launcher_window.QtChatWindow._floating_hide_action_tooltip

            def __init__(self):
                self._tray_restore_to_fullscreen = False
                self._tray_restore_to_maximized = False
                self._tray_mode_active = False
                self._visible = True
                self.current_session = {}
                self.status_label = DummyStatus()
                self._busy = False
                self._abort_requested = False
                self.calls = []
                self._floating_chat_window = DummyFloating(self)

            def isFullScreen(self):
                return False

            def isMaximized(self):
                return False

            def isVisible(self):
                return self._visible

            def _show_floating_chat_window(self):
                self.calls.append("show_floating")

            def hide(self):
                self._visible = False
                self.calls.append("hide")

            def _system_tray_available(self):
                return True

            def _is_channel_process_session(self, session=None):
                return False

            def _floating_chat_title(self):
                return "title"

            def _floating_chat_subtitle(self):
                return "subtitle"

            def _floating_chat_transcript(self):
                return "transcript"

            def _floating_chat_meta(self):
                return "meta"

            def _refresh_launcher_tray_menu(self):
                self.calls.append("refresh_tray")

        dummy = DummyHost()
        dummy._show_floating_chat_window_only()

        self.assertTrue(dummy._tray_mode_active)
        self.assertEqual(dummy._floating_chat_window.kwargs["status"], "已隐藏主窗口，悬浮窗可继续对话。")
        self.assertEqual(dummy._floating_chat_window.tooltip, "隐藏完整界面，仅保留托盘或悬浮窗入口。")
        self.assertEqual(dummy.calls, ["show_floating", "hide", "refresh_tray"])

    def test_enter_tray_floating_mode_keeps_windows_warning_when_tray_missing(self):
        class DummyHost:
            _enter_tray_floating_mode = launcher_window.QtChatWindow._enter_tray_floating_mode

            def _ensure_launcher_tray_icon(self):
                return None

        dummy = DummyHost()
        with mock.patch.object(launcher_window.lz, "IS_MACOS", False), mock.patch.object(
            launcher_window.QMessageBox, "warning"
        ) as warning_box:
            launcher_window.QtChatWindow._enter_tray_floating_mode(dummy)

        warning_box.assert_called_once()

    def test_enter_tray_floating_mode_falls_back_to_floating_on_macos_without_tray(self):
        class DummyHost:
            _enter_tray_floating_mode = launcher_window.QtChatWindow._enter_tray_floating_mode

            def __init__(self):
                self.calls = []

            def _ensure_launcher_tray_icon(self):
                return None

            def _show_floating_chat_window(self):
                self.calls.append("show_floating")

        dummy = DummyHost()
        with mock.patch.object(launcher_window.lz, "IS_MACOS", True), mock.patch.object(
            launcher_window.QMessageBox, "information"
        ) as info_box, mock.patch.object(launcher_window.QMessageBox, "warning") as warning_box:
            launcher_window.QtChatWindow._enter_tray_floating_mode(dummy)

        self.assertEqual(dummy.calls, ["show_floating"])
        info_box.assert_called_once()
        warning_box.assert_not_called()

    def test_hide_floating_chat_window_keeps_tray_mode_inactive_when_main_window_visible(self):
        class DummyFloating:
            def __init__(self):
                self.calls = []

            def hide(self):
                self.calls.append("hide")

        class DummyHost:
            _hide_floating_chat_window = launcher_window.QtChatWindow._hide_floating_chat_window

            def __init__(self):
                self._floating_chat_window = DummyFloating()
                self._tray_mode_active = True
                self.calls = []

            def isVisible(self):
                return True

            def _refresh_launcher_tray_menu(self):
                self.calls.append("refresh_tray")

        dummy = DummyHost()
        launcher_window.QtChatWindow._hide_floating_chat_window(dummy)

        self.assertEqual(dummy._floating_chat_window.calls, ["hide"])
        self.assertFalse(dummy._tray_mode_active)
        self.assertEqual(dummy.calls, ["refresh_tray"])

    def test_hide_floating_chat_window_keeps_tray_mode_active_when_main_window_hidden(self):
        class DummyFloating:
            def __init__(self):
                self.calls = []

            def hide(self):
                self.calls.append("hide")

        class DummyHost:
            _hide_floating_chat_window = launcher_window.QtChatWindow._hide_floating_chat_window

            def __init__(self):
                self._floating_chat_window = DummyFloating()
                self._tray_mode_active = False
                self.calls = []

            def isVisible(self):
                return False

            def _refresh_launcher_tray_menu(self):
                self.calls.append("refresh_tray")

        dummy = DummyHost()
        launcher_window.QtChatWindow._hide_floating_chat_window(dummy)

        self.assertEqual(dummy._floating_chat_window.calls, ["hide"])
        self.assertTrue(dummy._tray_mode_active)
        self.assertEqual(dummy.calls, ["refresh_tray"])

    def test_floating_hide_action_text_uses_hide_label_without_tray_on_macos(self):
        class DummyHost:
            _floating_hide_action_text = launcher_window.QtChatWindow._floating_hide_action_text
            _floating_hide_action_tooltip = launcher_window.QtChatWindow._floating_hide_action_tooltip

            def isVisible(self):
                return False

            def _system_tray_available(self):
                return False

        dummy = DummyHost()
        with mock.patch.object(launcher_window.lz, "IS_MACOS", True):
            self.assertEqual(dummy._floating_hide_action_text(), "隐藏悬浮窗")
            self.assertIn("主窗口会继续保留", dummy._floating_hide_action_tooltip())

    def test_floating_hide_action_text_uses_hide_label_when_main_window_visible(self):
        class DummyHost:
            _floating_hide_action_text = launcher_window.QtChatWindow._floating_hide_action_text
            _floating_hide_action_tooltip = launcher_window.QtChatWindow._floating_hide_action_tooltip

            def isVisible(self):
                return True

            def _system_tray_available(self):
                return True

        dummy = DummyHost()
        self.assertEqual(dummy._floating_hide_action_text(), "隐藏悬浮窗")
        self.assertEqual(dummy._floating_hide_action_tooltip(), "隐藏当前悬浮窗，主窗口会继续保留。")

    def test_refresh_floating_chat_window_uses_visible_main_window_status_text(self):
        class DummyStatus:
            def text(self):
                return ""

        class DummyFloating:
            def __init__(self):
                self.kwargs = None
                self.refreshed = 0

            def refresh_action_texts(self):
                self.refreshed += 1

            def sync_view(self, **kwargs):
                self.kwargs = dict(kwargs)

        class DummyHost:
            _refresh_floating_chat_window = launcher_window.QtChatWindow._refresh_floating_chat_window
            _floating_default_status_text = launcher_window.QtChatWindow._floating_default_status_text

            def __init__(self):
                self._floating_chat_window = DummyFloating()
                self._tray_mode_active = False
                self.status_label = DummyStatus()
                self.current_session = {}
                self._busy = False
                self._abort_requested = False

            def isVisible(self):
                return True

            def _is_channel_process_session(self, session=None):
                return False

            def _floating_chat_title(self):
                return "title"

            def _floating_chat_subtitle(self):
                return "subtitle"

            def _floating_chat_transcript(self):
                return "transcript"

            def _floating_chat_meta(self):
                return "meta"

            def _refresh_launcher_tray_menu(self):
                return None

        dummy = DummyHost()
        launcher_window.QtChatWindow._refresh_floating_chat_window(dummy)

        self.assertEqual(dummy._floating_chat_window.refreshed, 1)
        self.assertEqual(dummy._floating_chat_window.kwargs["status"], "主窗口仍在显示，可继续使用悬浮窗对话。")

    def test_floating_default_status_text_prefers_visible_main_window_over_tray_flag(self):
        class DummyHost:
            _floating_default_status_text = launcher_window.QtChatWindow._floating_default_status_text

            def __init__(self):
                self._tray_mode_active = True

            def isVisible(self):
                return True

        dummy = DummyHost()
        self.assertEqual(dummy._floating_default_status_text(), "主窗口仍在显示，可继续使用悬浮窗对话。")

    def test_functions_menu_floating_action_text_uses_non_tray_label_on_macos_without_tray(self):
        class DummyHost:
            _functions_menu_floating_action_text = launcher_window.QtChatWindow._functions_menu_floating_action_text
            _floating_window_visible = launcher_window.QtChatWindow._floating_window_visible

            def __init__(self):
                self._floating_chat_window = None

            def _system_tray_available(self):
                return False

        dummy = DummyHost()
        with mock.patch.object(launcher_window.lz, "IS_MACOS", True):
            self.assertEqual(dummy._functions_menu_floating_action_text(), "◱  打开悬浮窗，主窗口继续保留")

    def test_functions_menu_floating_action_text_uses_focus_label_when_floating_visible_without_tray(self):
        class DummyFloating:
            def isVisible(self):
                return True

        class DummyHost:
            _functions_menu_floating_action_text = launcher_window.QtChatWindow._functions_menu_floating_action_text
            _floating_window_visible = launcher_window.QtChatWindow._floating_window_visible

            def __init__(self):
                self._floating_chat_window = DummyFloating()

            def _system_tray_available(self):
                return False

        dummy = DummyHost()
        with mock.patch.object(launcher_window.lz, "IS_MACOS", True):
            self.assertEqual(dummy._functions_menu_floating_action_text(), "◱  聚焦悬浮窗，主窗口继续保留")

    def test_handle_functions_menu_floating_action_uses_tray_mode_when_tray_available(self):
        class DummyHost:
            _handle_functions_menu_floating_action = launcher_window.QtChatWindow._handle_functions_menu_floating_action

            def __init__(self):
                self.calls = []

            def _system_tray_available(self):
                return True

            def _enter_tray_floating_mode(self):
                self.calls.append("enter_tray")

            def _show_floating_chat_window(self):
                self.calls.append("show_floating")

        dummy = DummyHost()
        dummy._handle_functions_menu_floating_action()

        self.assertEqual(dummy.calls, ["enter_tray"])

    def test_handle_functions_menu_floating_action_opens_floating_without_tray(self):
        class DummyHost:
            _handle_functions_menu_floating_action = launcher_window.QtChatWindow._handle_functions_menu_floating_action

            def __init__(self):
                self.calls = []

            def _system_tray_available(self):
                return False

            def _enter_tray_floating_mode(self):
                self.calls.append("enter_tray")

            def _show_floating_chat_window(self):
                self.calls.append("show_floating")

        dummy = DummyHost()
        dummy._handle_functions_menu_floating_action()

        self.assertEqual(dummy.calls, ["show_floating"])

    def test_handle_functions_menu_floating_action_focuses_visible_floating_without_tray(self):
        class DummyHost:
            _handle_functions_menu_floating_action = launcher_window.QtChatWindow._handle_functions_menu_floating_action

            def __init__(self):
                self.calls = []

            def _system_tray_available(self):
                return False

            def _focus_visible_floating_chat_window(self):
                self.calls.append("focus_floating")
                return True

            def _enter_tray_floating_mode(self):
                self.calls.append("enter_tray")

            def _show_floating_chat_window(self):
                self.calls.append("show_floating")

        dummy = DummyHost()
        dummy._handle_functions_menu_floating_action()

        self.assertEqual(dummy.calls, ["focus_floating"])

    def test_new_session_from_floating_refocuses_expanded_floating_input(self):
        class DummyHost:
            def __init__(self):
                self.calls = []

            def _new_session(self):
                self.calls.append("new_session")

            def _refresh_floating_chat_window(self):
                self.calls.append("refresh_floating")

            def _focus_floating_input_if_possible(self):
                self.calls.append("focus_floating")

        dummy = DummyHost()
        launcher_window.QtChatWindow._new_session_from_floating(dummy)

        self.assertEqual(dummy.calls, ["new_session", "refresh_floating", "focus_floating"])

    def test_floating_session_change_refocuses_expanded_input_after_switch(self):
        class DummyCombo:
            def itemData(self, index):
                return "target-session" if index == 1 else ""

        class DummyFloating:
            def __init__(self):
                self.session_combo = DummyCombo()

        class DummyHost:
            def __init__(self):
                self._busy = False
                self._floating_chat_window = DummyFloating()
                self.current_session = {"id": "current-session"}
                self._last_session_list_signature = "cached"
                self.calls = []

            def _load_session_by_id(self, sid):
                self.calls.append(("load", sid))

            def _refresh_sessions(self):
                self.calls.append("refresh_sessions")

            def _refresh_floating_chat_window(self):
                self.calls.append("refresh_floating")

            def _focus_floating_input_if_possible(self):
                self.calls.append("focus_floating")

        dummy = DummyHost()
        launcher_window.QtChatWindow._on_floating_session_changed(dummy, 1)

        self.assertIsNone(dummy._last_session_list_signature)
        self.assertEqual(
            dummy.calls,
            [("load", "target-session"), "refresh_sessions", "refresh_floating", "focus_floating"],
        )

    def test_load_session_by_id_aligns_sidebar_context_to_loaded_session(self):
        class DummySidebar(SidebarSessionsMixin):
            _load_session_by_id = SidebarSessionsMixin._load_session_by_id
            _align_sidebar_to_session = SidebarSessionsMixin._align_sidebar_to_session

            def __init__(self):
                self.agent_dir = "C:\\demo"
                self._busy = False
                self.current_session = None
                self._selected_session_id = None
                self._sidebar_device_scope = "local"
                self._sidebar_device_id = "local"
                self._sidebar_channel_id = "launcher"
                self._sidebar_view_mode = "roots"
                self._last_session_list_signature = "cached"
                self.rendered = None

            def _session_device_scope_id(self, session):
                return ("remote", "box-1")

            def _remote_device_by_id(self, device_id):
                return {"id": device_id, "name": "Mac Mini"}

            def _render_session(self, session):
                self.rendered = dict(session)

            def _refresh_composer_enabled(self):
                return None

            def _is_channel_process_session(self, session=None):
                return False

            def _bind_session_to_current_bridge(self, session):
                return None

            def _refresh_remote_session_cache_async(self, session):
                self.remote_refresh = dict(session)

            def _set_status(self, text):
                self.status_text = str(text)

            @property
            def _bridge_ready(self):
                return False

        dummy = DummySidebar()
        payload = {"id": "sess-1", "title": "Remote session", "channel_id": "wechat"}
        with mock.patch.object(lz, "load_session", return_value=dict(payload)):
            dummy._load_session_by_id("sess-1")

        self.assertEqual(dummy._selected_session_id, "sess-1")
        self.assertEqual(dummy._sidebar_device_scope, "remote")
        self.assertEqual(dummy._sidebar_device_id, "box-1")
        self.assertEqual(dummy._sidebar_channel_id, "wechat")
        self.assertEqual(dummy._sidebar_view_mode, "sessions")
        self.assertIsNone(dummy._last_session_list_signature)
        self.assertEqual(dummy.status_text, "已载入远程会话缓存，正在后台同步；可继续发送，新内容会尝试写回远端。")

    def test_refresh_remote_session_cache_async_updates_status_when_sync_succeeds(self):
        class ImmediateThread:
            def __init__(self, target=None, name=None, daemon=None):
                self._target = target

            def start(self):
                if callable(self._target):
                    self._target()

        class DummySidebar(SidebarSessionsMixin):
            _refresh_remote_session_cache_async = SidebarSessionsMixin._refresh_remote_session_cache_async

            def __init__(self):
                self.agent_dir = "C:\\demo"
                self._runtime_context_generation = 2
                self.current_session = {"id": "sess-1", "device_scope": "remote", "device_id": "box-1"}
                self._remote_session_refresh_inflight = set()
                self._last_session_list_signature = "cached"
                self.statuses = []
                self.rendered = None
                self.refresh_calls = 0
                self.composer_refreshes = 0

            def _session_device_scope_id(self, session):
                return ("remote", "box-1")

            def _refresh_remote_session_cache(self, session, *, agent_dir="", runtime_context=None):
                return {"id": "sess-1", "title": "Fresh", "device_scope": "remote", "device_id": "box-1"}, ""

            def _sidebar_post_ui(self, callback):
                if callable(callback):
                    callback()

            def _render_session(self, session):
                self.rendered = dict(session)

            def _refresh_composer_enabled(self):
                self.composer_refreshes += 1

            def _refresh_sessions(self):
                self.refresh_calls += 1

            def _set_status(self, text):
                self.statuses.append(str(text))

        dummy = DummySidebar()
        with mock.patch.object(sidebar_sessions.threading, "Thread", ImmediateThread):
            dummy._refresh_remote_session_cache_async({"id": "sess-1", "device_scope": "remote", "device_id": "box-1"})

        self.assertEqual(dummy.current_session["title"], "Fresh")
        self.assertEqual(dummy.rendered["title"], "Fresh")
        self.assertEqual(dummy.statuses, ["已同步远程会话；后续发送会继续写回远端。"])
        self.assertEqual(dummy.refresh_calls, 1)
        self.assertEqual(dummy.composer_refreshes, 1)
        self.assertEqual(dummy._remote_session_refresh_inflight, set())

    def test_refresh_remote_session_cache_async_updates_status_when_sync_fails(self):
        class ImmediateThread:
            def __init__(self, target=None, name=None, daemon=None):
                self._target = target

            def start(self):
                if callable(self._target):
                    self._target()

        class DummySidebar(SidebarSessionsMixin):
            _refresh_remote_session_cache_async = SidebarSessionsMixin._refresh_remote_session_cache_async

            def __init__(self):
                self.agent_dir = "C:\\demo"
                self._runtime_context_generation = 2
                self.current_session = {"id": "sess-1", "device_scope": "remote", "device_id": "box-1"}
                self._remote_session_refresh_inflight = set()
                self.statuses = []

            def _session_device_scope_id(self, session):
                return ("remote", "box-1")

            def _refresh_remote_session_cache(self, session, *, agent_dir="", runtime_context=None):
                return None, "SSH 超时"

            def _sidebar_post_ui(self, callback):
                if callable(callback):
                    callback()

            def _set_status(self, text):
                self.statuses.append(str(text))

        dummy = DummySidebar()
        with mock.patch.object(sidebar_sessions.threading, "Thread", ImmediateThread):
            dummy._refresh_remote_session_cache_async({"id": "sess-1", "device_scope": "remote", "device_id": "box-1"})

        self.assertEqual(dummy.statuses, ["远端同步失败，当前仍使用本地缓存：SSH 超时；可稍后重试或先检查 SSH。"])
        self.assertEqual(dummy._remote_session_refresh_inflight, set())

    def test_save_remote_session_source_async_reports_local_cache_preserved_on_failure(self):
        class ImmediateThread:
            def __init__(self, target=None, name=None, daemon=None):
                self._target = target

            def start(self):
                if callable(self._target):
                    self._target()

        class DummySidebar(SidebarSessionsMixin):
            _save_remote_session_source_async = SidebarSessionsMixin._save_remote_session_source_async

            def __init__(self):
                self.agent_dir = "C:\\demo"
                self._runtime_context_generation = 2
                self.statuses = []

            def _session_device_scope_id(self, session):
                return ("remote", "box-1")

            def _save_remote_session_source(self, session, *, agent_dir="", runtime_context=None):
                return False, "SSH 超时"

            def _sidebar_post_ui(self, callback):
                if callable(callback):
                    callback()

            def _set_status(self, text):
                self.statuses.append(str(text))

        dummy = DummySidebar()
        with mock.patch.object(sidebar_sessions.threading, "Thread", ImmediateThread):
            dummy._save_remote_session_source_async({"id": "sess-1", "device_scope": "remote", "device_id": "box-1"})

        self.assertEqual(dummy.statuses, ["远端会话写回失败，当前内容仍保留在本地缓存：SSH 超时；可稍后重试同步或检查 SSH。"])

    def test_reload_personal_panel_remote_sync_notice_and_completion_status(self):
        class DummyLabel:
            def __init__(self):
                self.text = ""

            def setText(self, text):
                self.text = str(text)

        class DummyUsage(PersonalUsageMixin):
            _reload_personal_panel = PersonalUsageMixin._reload_personal_panel

            def __init__(self):
                self.agent_dir = "C:\\demo"
                self.cfg = {}
                self._runtime_context_generation = 2
                self._settings_target_change_token = 4
                self._settings_personal_remote_sync_running = False
                self._settings_personal_remote_sync_key = ""
                self._settings_personal_remote_synced_key = ""
                self.settings_personal_notice = DummyLabel()
                self.settings_personal_scope_hint = DummyLabel()
                self.settings_personal_list_layout = object()
                self.statuses = []
                self.trigger_calls = []
                self.pending_done = None

            def _settings_target_generation(self):
                return self._settings_target_change_token

            def _reload_personal_preferences(self):
                return None

            def _reload_lan_interface_panel(self):
                return None

            def _clear_layout(self, _layout):
                return None

            def _settings_data_target_context(self):
                return {"is_remote": True, "device_id": "box-1", "scope": "remote", "label": "Mac Mini"}

            def _settings_remote_sync_key(self, target, *, kind="personal"):
                return f"{kind}:{target['device_id']}"

            def _trigger_settings_remote_session_sync(self, *, device_id="", on_done=None, include_all_channels=False, include_usage=False):
                self.trigger_calls.append((device_id, bool(include_all_channels), bool(include_usage)))
                self.pending_done = on_done

            def _set_status(self, text):
                self.statuses.append(str(text))

            def _collect_archive_stats(self, scope, device_id):
                return {"active": {}}

            def _archive_known_channel_ids(self, scope, device_id):
                return []

        dummy = DummyUsage()
        with mock.patch.object(lz, "is_valid_agent_dir", return_value=False):
            dummy._reload_personal_panel()
            self.assertEqual(dummy.settings_personal_notice.text, "正在同步 Mac Mini 的会话缓存；完成后会自动刷新，随后可继续调整会话上限。")
            self.assertTrue(callable(dummy.pending_done))
            dummy.pending_done()

        self.assertEqual(dummy.trigger_calls, [("box-1", True, False)])
        self.assertEqual(dummy.statuses, ["已同步 Mac Mini 的远端会话缓存；当前页面已刷新，可继续调整会话上限。"])
        self.assertEqual(dummy._settings_personal_remote_synced_key, "personal:box-1")

    def test_reload_usage_panel_remote_sync_notice_and_completion_status(self):
        class DummyLabel:
            def __init__(self):
                self.text = ""

            def setText(self, text):
                self.text = str(text)

        class DummyUsage(PersonalUsageMixin):
            _reload_usage_panel = PersonalUsageMixin._reload_usage_panel

            def __init__(self):
                self.agent_dir = "C:\\demo"
                self.cfg = {}
                self._runtime_context_generation = 2
                self._settings_target_change_token = 4
                self._settings_usage_remote_sync_running = False
                self._settings_usage_remote_sync_key = ""
                self._settings_usage_remote_synced_key = ""
                self.settings_usage_notice = DummyLabel()
                self.settings_usage_list_layout = object()
                self.statuses = []
                self.trigger_calls = []
                self.pending_done = None

            def _settings_target_generation(self):
                return self._settings_target_change_token

            def _clear_layout(self, _layout):
                return None

            def _settings_data_target_context(self):
                return {"is_remote": True, "device_id": "box-1", "scope": "remote", "label": "Mac Mini"}

            def _settings_remote_sync_key(self, target, *, kind="usage"):
                return f"{kind}:{target['device_id']}"

            def _trigger_settings_remote_session_sync(self, *, device_id="", on_done=None, include_all_channels=False, include_usage=False):
                self.trigger_calls.append((device_id, bool(include_all_channels), bool(include_usage)))
                self.pending_done = on_done

            def _set_status(self, text):
                self.statuses.append(str(text))

        dummy = DummyUsage()
        with mock.patch.object(lz, "is_valid_agent_dir", return_value=False):
            dummy._reload_usage_panel()
            self.assertEqual(dummy.settings_usage_notice.text, "正在同步 Mac Mini 的远端使用日志、会话与渠道快照；完成后会自动刷新，可能需要数秒。")
            self.assertTrue(callable(dummy.pending_done))
            dummy.pending_done()

        self.assertEqual(dummy.trigger_calls, [("box-1", True, True)])
        self.assertEqual(dummy.statuses, ["已同步 Mac Mini 的远端使用日志、会话与渠道快照；当前页面已刷新。"])
        self.assertEqual(dummy._settings_usage_remote_synced_key, "usage:box-1")

    def test_remote_launcher_sync_blocking_drops_stale_context_before_local_cache_write(self):
        class DummySidebar(SidebarSessionsMixin):
            _sync_remote_device_launcher_sessions_blocking = SidebarSessionsMixin._sync_remote_device_launcher_sessions_blocking

            def __init__(self):
                self.agent_dir = "C:\\new-agent"
                self._runtime_context_generation = 8
                self.current_session = None

            def _current_device_context(self):
                return ("remote", "box-1")

            def _session_device_scope_id(self, _session):
                return ("remote", "box-1")

            def _auto_ssh_remote_devices(self, _target_id=""):
                return [{"id": "box-1", "name": "Mac Mini"}]

            def _fetch_remote_launcher_session_metas(self, _dev, **_kwargs):
                return True, [{"id": "sess-1", "remote_session_id": "sess-1", "updated_at": 1.0, "channel_id": "launcher"}], ""

            def _normalize_remote_session_id(self, value, fallback=""):
                return str(value or fallback)

            def _remote_cache_session_id(self, did, remote_sid):
                return f"rchat_{did}_{remote_sid}"

            def _remote_session_cache_payload(self, _dev, row, _old):
                return {
                    "id": "rchat_box-1_sess-1",
                    "title": "Remote Session",
                    "updated_at": float(row.get("updated_at", 0) or 0),
                    "pinned": False,
                    "remote_session_id": "sess-1",
                    "device_id": "box-1",
                    "channel_id": "launcher",
                }

        dummy = DummySidebar()
        stale_context = {"agent_dir": "C:\\old-agent", "runtime_generation": 7, "settings_target_generation": 0}
        with mock.patch.object(lz, "load_session") as load_session, mock.patch.object(lz, "save_session") as save_session:
            changed = dummy._sync_remote_device_launcher_sessions_blocking(
                force=True,
                device_id="box-1",
                agent_dir="C:\\old-agent",
                runtime_context=stale_context,
            )

        self.assertFalse(changed)
        load_session.assert_not_called()
        save_session.assert_not_called()

    def test_restore_from_tray_mode_restores_maximized_window_state(self):
        class DummyEditor:
            def __init__(self):
                self.focus_calls = []

            def setFocus(self, reason):
                self.focus_calls.append(reason)

        class DummyFloating:
            def hide(self):
                return None

        class DummyHost:
            def __init__(self):
                self._tray_mode_active = True
                self._tray_restore_to_fullscreen = False
                self._tray_restore_to_maximized = True
                self._floating_chat_window = DummyFloating()
                self.input_box = DummyEditor()
                self.calls = []

            def isVisible(self):
                return False

            def _sync_draft_from_floating(self):
                self.calls.append("sync_from_floating")

            def showNormal(self):
                self.calls.append("show_normal")

            def showMaximized(self):
                self.calls.append("show_maximized")

            def showFullScreen(self):
                self.calls.append("show_fullscreen")

            def raise_(self):
                self.calls.append("raise")

            def activateWindow(self):
                self.calls.append("activate")

            def _show_chat_page(self):
                self.calls.append("show_chat_page")

            def _refresh_floating_chat_window(self):
                self.calls.append("refresh_floating")

            def _refresh_launcher_tray_menu(self):
                self.calls.append("refresh_tray")

            def _is_channel_process_session(self):
                return False

        dummy = DummyHost()
        with mock.patch.object(launcher_window.QTimer, "singleShot", side_effect=lambda _ms, cb: cb()):
            launcher_window.QtChatWindow._restore_from_tray_mode(dummy)

        self.assertFalse(dummy._tray_mode_active)
        self.assertFalse(dummy._tray_restore_to_maximized)
        self.assertIn("show_maximized", dummy.calls)
        self.assertNotIn("show_normal", dummy.calls)

    def test_lan_interface_external_running_requires_health_without_managed_proc(self):
        class DummyUsage(PersonalUsageMixin):
            def __init__(self):
                self._lan_interface_proc = None
                self._lan_interface_log_handle = None
                self._lan_interface_last_exit_code = None
                self.cfg = {"lan_interface": {"enabled": True, "auto_start": True, "bind_all": True, "port": 8501, "frontend": "foo.py"}}

            def _lan_interface_cfg(self):
                return dict(self.cfg.get("lan_interface") or {})

        dummy = DummyUsage()
        with mock.patch.object(dummy, "_lan_interface_proc_alive", return_value=False), mock.patch.object(
            dummy, "_lan_interface_health_ok", return_value=True
        ):
            self.assertTrue(dummy._lan_interface_external_running(8501))
        with mock.patch.object(dummy, "_lan_interface_proc_alive", return_value=True), mock.patch.object(
            dummy, "_lan_interface_health_ok", return_value=True
        ):
            self.assertFalse(dummy._lan_interface_external_running(8501))

    def test_format_launcher_installation_text_includes_manual_macos_install_contract(self):
        class DummyUsage(PersonalUsageMixin):
            _format_launcher_installation_text = PersonalUsageMixin._format_launcher_installation_text

        dummy = DummyUsage()
        status = {
            "summary": "当前仍在 dmg 挂载目录中运行，建议先拖到 /Applications；如果只想安装到当前用户，也可以改放 ~/Applications，然后重新打开。",
            "app_bundle_path": f"/Volumes/GenericAgentLauncher/{runtime.APP_DISPLAY_NAME}.app",
            "executable_path": f"/Volumes/GenericAgentLauncher/{runtime.APP_DISPLAY_NAME}.app/Contents/MacOS/GenericAgentLauncher",
            "recommended_install_target": f"/Applications/{runtime.APP_DISPLAY_NAME}.app",
            "user_applications_target": f"/Users/tester/Applications/{runtime.APP_DISPLAY_NAME}.app",
            "data_root": "/Users/tester/Library/Application Support/GenericAgentLauncher",
            "running_from_disk_image": True,
            "running_from_translocation": True,
            "needs_relocation": True,
        }
        with mock.patch.object(personal_usage.lz, "IS_MACOS", True), mock.patch.object(
            personal_usage.lz, "DATA_ROOT", status["data_root"]
        ), mock.patch.object(
            personal_usage.lz, "macos_installation_status", return_value=status
        ):
            text = dummy._format_launcher_installation_text()

        self.assertIn("安装方式：未做 Apple Developer 签名 / 未 notarize 的 dmg 手动安装 / 手动替换 .app 升级", text)
        self.assertIn("推荐安装位置：/Applications", text)
        self.assertIn("`/Volumes/...`", text)
        self.assertIn("App Translocation", text)
        self.assertIn("拖到 `/Applications`", text)
        self.assertIn("`~/Applications`", text)

    def test_schedule_startup_install_hint_posts_warn_summary_to_status_bar(self):
        class DummyUsage(PersonalUsageMixin):
            _schedule_startup_install_hint = PersonalUsageMixin._schedule_startup_install_hint

            def __init__(self):
                self._startup_install_hint_scheduled = False
                self._closing_in_progress = False
                self.statuses = []

            def _set_status(self, text):
                self.statuses.append(str(text))

        dummy = DummyUsage()
        with mock.patch.object(personal_usage.lz, "IS_MACOS", True), mock.patch.object(
            personal_usage.lz,
            "macos_installation_status",
            return_value={"status": "warn", "summary": "请先把 app 移动到 /Applications。"},
        ), mock.patch.object(personal_usage.QTimer, "singleShot", side_effect=lambda _ms, cb: cb()):
            dummy._schedule_startup_install_hint()

        self.assertEqual(dummy.statuses, ["请先把 app 移动到 /Applications。"])
        self.assertFalse(dummy._startup_install_hint_scheduled)

    def test_launcher_manual_update_payload_describes_manual_macos_install_contract(self):
        class DummyUsage(PersonalUsageMixin):
            _display_local_user_path = PersonalUsageMixin._display_local_user_path
            _launcher_manual_update_payload = PersonalUsageMixin._launcher_manual_update_payload

        dummy = DummyUsage()
        install_state = {
            "recommended_install_target": "/Applications/GenericAgent Launcher.app",
            "data_root": "/Users/tester/Library/Application Support/GenericAgentLauncher",
        }
        info = {
            "target_version": "1.2.4",
            "external_url": "https://example.com/GenericAgentLauncher-macos-1.2.4.dmg",
            "external_asset_name": "GenericAgentLauncher-macos-1.2.4.dmg",
            "release_url": "https://github.com/example/release/v1.2.4",
            "readme_url": "https://example.com/README-macOS.txt",
            "sha256_url": "https://example.com/GenericAgentLauncher-macos-1.2.4.sha256",
            "metadata_url": "https://example.com/install-metadata.json",
        }
        with mock.patch.object(personal_usage.lz, "IS_MACOS", True), mock.patch.object(
            personal_usage.lz, "DATA_ROOT", install_state["data_root"]
        ), mock.patch.object(
            personal_usage.lz, "macos_installation_status", return_value=install_state
        ):
            payload = dummy._launcher_manual_update_payload(info, launcher_row={"latest_release_tag": "v1.2.4"})

        self.assertEqual(payload["recommended_install_target"], "/Applications/GenericAgent Launcher.app")
        self.assertEqual(payload["data_root"], install_state["data_root"])
        self.assertEqual(payload["readme_url"], "https://example.com/README-macOS.txt")
        self.assertEqual(payload["sha256_url"], "https://example.com/GenericAgentLauncher-macos-1.2.4.sha256")
        self.assertEqual(payload["metadata_url"], "https://example.com/install-metadata.json")
        self.assertIn("目标版本：1.2.4", payload["detail_text"])
        self.assertIn("建议替换路径：/Applications/GenericAgent Launcher.app", payload["detail_text"])
        self.assertIn("用户数据目录：/Users/tester/Library/Application Support/GenericAgentLauncher", payload["detail_text"])
        self.assertIn("优先推荐放到 /Applications", payload["detail_text"])
        self.assertIn("README-macOS.txt", payload["detail_text"])
        self.assertIn("install-metadata.json", payload["detail_text"])
        self.assertIn("System Settings -> Privacy & Security -> Open Anyway", payload["detail_text"])
        self.assertIn("Finder 右键应用并选择 Open", payload["detail_text"])

    def test_launcher_manual_update_payload_uses_user_install_target_and_release_page_fallback(self):
        class DummyUsage(PersonalUsageMixin):
            _display_local_user_path = PersonalUsageMixin._display_local_user_path
            _launcher_manual_update_payload = PersonalUsageMixin._launcher_manual_update_payload

        dummy = DummyUsage()
        install_state = {
            "recommended_install_target": "/Users/tester/Applications/GenericAgent Launcher.app",
            "user_applications_target": "/Users/tester/Applications/GenericAgent Launcher.app",
            "installed_to_user_applications": True,
            "data_root": "/Users/tester/Library/Application Support/GenericAgentLauncher",
        }
        with mock.patch.object(personal_usage.lz, "IS_MACOS", True), mock.patch.object(
            personal_usage.lz, "DATA_ROOT", install_state["data_root"]
        ), mock.patch.object(
            personal_usage.lz, "macos_installation_status", return_value=install_state
        ), mock.patch.object(
            personal_usage.os.path, "expanduser", return_value="/Users/tester"
        ):
            payload = dummy._launcher_manual_update_payload(
                {},
                launcher_row={
                    "latest_release_tag": "v1.2.4",
                    "latest_release_url": "https://github.com/example/release/v1.2.4",
                },
            )

        self.assertEqual(payload["target_version"], "1.2.4")
        self.assertEqual(payload["recommended_install_target"], "/Users/tester/Applications/GenericAgent Launcher.app")
        self.assertEqual(payload["release_url"], "https://github.com/example/release/v1.2.4")
        self.assertIn("建议替换路径：~/Applications/GenericAgent Launcher.app", payload["detail_text"])
        self.assertIn("当前检测到的用户级安装路径：~/Applications/GenericAgent Launcher.app", payload["detail_text"])
        self.assertIn("当前未识别到可直接安装的 macOS .dmg，请改用 Release 页面或 Actions 构建产物。", payload["detail_text"])

    def test_refresh_about_update_widgets_sets_disabled_tooltips_while_check_running(self):
        class DummyLabel:
            def __init__(self):
                self.text = ""

            def setText(self, text):
                self.text = str(text)

        class DummyButton:
            def __init__(self):
                self.enabled = None
                self.tooltip = ""
                self.text = ""

            def setEnabled(self, value):
                self.enabled = bool(value)

            def setToolTip(self, text):
                self.tooltip = str(text)

            def setText(self, text):
                self.text = str(text)

        class DummyUsage(PersonalUsageMixin):
            _refresh_about_update_widgets = PersonalUsageMixin._refresh_about_update_widgets
            _refresh_about_update_diagnostics_widgets = PersonalUsageMixin._refresh_about_update_diagnostics_widgets
            _apply_personal_button_state = PersonalUsageMixin._apply_personal_button_state
            _about_update_check_disabled_reason = PersonalUsageMixin._about_update_check_disabled_reason
            _about_update_install_disabled_reason = PersonalUsageMixin._about_update_install_disabled_reason
            _kernel_sync_disabled_reason = PersonalUsageMixin._kernel_sync_disabled_reason

            def __init__(self):
                self.agent_dir = "C:\\demo"
                self._update_check_running = True
                self._kernel_repo_sync_running = False
                self._last_update_check_result = {
                    "launcher": {
                        "status": "behind",
                        "update_info": {"install_mode": "external", "external_url": "https://example.com/update.exe"},
                    }
                }
                self.settings_about_update_status = DummyLabel()
                self.settings_about_update_diag_status = DummyLabel()
                self.settings_about_check_updates_btn = DummyButton()
                self.settings_about_install_update_btn = DummyButton()
                self.settings_about_sync_kernel_fetch_btn = DummyButton()
                self.settings_about_sync_kernel_pull_btn = DummyButton()

            def _update_history_brief_text(self, limit=3):
                return "history"

        dummy = DummyUsage()
        with mock.patch.object(lz, "is_valid_agent_dir", return_value=True), mock.patch.object(
            personal_usage.os.path, "isfile", return_value=True
        ), mock.patch.object(
            lz, "updater_executable_path", return_value="C:\\demo\\updater.exe"
        ), mock.patch.object(
            lz, "PLATFORM_SUPPORTS_INTERNAL_UPDATER", True
        ):
            dummy._refresh_about_update_widgets()

        self.assertFalse(dummy.settings_about_check_updates_btn.enabled)
        self.assertEqual(dummy.settings_about_check_updates_btn.text, "正在检测…")
        self.assertEqual(dummy.settings_about_check_updates_btn.tooltip, "当前正在检测 GitHub 更新，请稍候。")
        self.assertFalse(dummy.settings_about_install_update_btn.enabled)
        self.assertEqual(dummy.settings_about_install_update_btn.tooltip, "当前正在检测 GitHub 更新，请稍候。")
        self.assertFalse(dummy.settings_about_sync_kernel_fetch_btn.enabled)
        self.assertFalse(dummy.settings_about_sync_kernel_pull_btn.enabled)
        self.assertEqual(dummy.settings_about_sync_kernel_fetch_btn.tooltip, "当前正在检测 GitHub 更新，请稍后再执行仓库同步。")
        self.assertEqual(dummy.settings_about_sync_kernel_pull_btn.tooltip, "当前正在检测 GitHub 更新，请稍后再执行仓库同步。")

    def test_refresh_about_update_widgets_explains_missing_updater_and_repo_dir(self):
        class DummyLabel:
            def __init__(self):
                self.text = ""

            def setText(self, text):
                self.text = str(text)

        class DummyButton:
            def __init__(self):
                self.enabled = None
                self.tooltip = ""
                self.text = ""

            def setEnabled(self, value):
                self.enabled = bool(value)

            def setToolTip(self, text):
                self.tooltip = str(text)

            def setText(self, text):
                self.text = str(text)

        class DummyUsage(PersonalUsageMixin):
            _refresh_about_update_widgets = PersonalUsageMixin._refresh_about_update_widgets
            _refresh_about_update_diagnostics_widgets = PersonalUsageMixin._refresh_about_update_diagnostics_widgets
            _apply_personal_button_state = PersonalUsageMixin._apply_personal_button_state
            _about_update_check_disabled_reason = PersonalUsageMixin._about_update_check_disabled_reason
            _about_update_install_disabled_reason = PersonalUsageMixin._about_update_install_disabled_reason
            _kernel_sync_disabled_reason = PersonalUsageMixin._kernel_sync_disabled_reason

            def __init__(self):
                self.agent_dir = ""
                self._update_check_running = False
                self._kernel_repo_sync_running = False
                self._last_update_check_result = {
                    "launcher": {
                        "status": "behind",
                        "update_info": {"install_mode": "internal"},
                    }
                }
                self.settings_about_update_status = DummyLabel()
                self.settings_about_update_diag_status = DummyLabel()
                self.settings_about_check_updates_btn = DummyButton()
                self.settings_about_install_update_btn = DummyButton()
                self.settings_about_sync_kernel_fetch_btn = DummyButton()
                self.settings_about_sync_kernel_pull_btn = DummyButton()

            def _update_history_brief_text(self, limit=3):
                return "history"

        dummy = DummyUsage()
        with mock.patch.object(lz, "is_valid_agent_dir", return_value=False), mock.patch.object(
            personal_usage.os.path, "isfile", return_value=False
        ), mock.patch.object(
            lz, "updater_executable_path", return_value="C:\\missing\\updater.exe"
        ), mock.patch.object(
            lz, "PLATFORM_SUPPORTS_INTERNAL_UPDATER", True
        ):
            dummy._refresh_about_update_widgets()

        self.assertFalse(dummy.settings_about_install_update_btn.enabled)
        self.assertEqual(dummy.settings_about_install_update_btn.tooltip, "当前缺少内置 updater，暂时不能直接安装更新。")
        self.assertFalse(dummy.settings_about_sync_kernel_fetch_btn.enabled)
        self.assertFalse(dummy.settings_about_sync_kernel_pull_btn.enabled)
        self.assertEqual(dummy.settings_about_sync_kernel_fetch_btn.tooltip, "当前没有可用的内核 Git 仓库目录。")
        self.assertEqual(dummy.settings_about_sync_kernel_pull_btn.tooltip, "当前没有可用的内核 Git 仓库目录。")

    def test_refresh_about_update_widgets_enables_manual_macos_update_when_release_page_exists(self):
        class DummyLabel:
            def __init__(self):
                self.text = ""

            def setText(self, text):
                self.text = str(text)

        class DummyButton:
            def __init__(self):
                self.enabled = None
                self.tooltip = ""
                self.text = ""

            def setEnabled(self, value):
                self.enabled = bool(value)

            def setToolTip(self, text):
                self.tooltip = str(text)

            def setText(self, text):
                self.text = str(text)

        class DummyUsage(PersonalUsageMixin):
            _refresh_about_update_widgets = PersonalUsageMixin._refresh_about_update_widgets
            _refresh_about_update_diagnostics_widgets = PersonalUsageMixin._refresh_about_update_diagnostics_widgets
            _apply_personal_button_state = PersonalUsageMixin._apply_personal_button_state
            _about_update_check_disabled_reason = PersonalUsageMixin._about_update_check_disabled_reason
            _about_update_install_disabled_reason = PersonalUsageMixin._about_update_install_disabled_reason
            _kernel_sync_disabled_reason = PersonalUsageMixin._kernel_sync_disabled_reason

            def __init__(self):
                self.agent_dir = ""
                self._update_check_running = False
                self._kernel_repo_sync_running = False
                self._last_update_check_result = {
                    "launcher": {
                        "status": "behind",
                        "latest_release_url": "https://github.com/example/release/v1.2.4",
                        "update_info": None,
                    }
                }
                self.settings_about_update_status = DummyLabel()
                self.settings_about_update_diag_status = DummyLabel()
                self.settings_about_check_updates_btn = DummyButton()
                self.settings_about_install_update_btn = DummyButton()
                self.settings_about_sync_kernel_fetch_btn = DummyButton()
                self.settings_about_sync_kernel_pull_btn = DummyButton()

            def _update_history_brief_text(self, limit=3):
                return "history"

        dummy = DummyUsage()
        with mock.patch.object(lz, "is_valid_agent_dir", return_value=False), mock.patch.object(
            personal_usage.os.path, "isfile", return_value=False
        ), mock.patch.object(
            lz, "updater_executable_path", return_value=""
        ), mock.patch.object(
            lz, "PLATFORM_SUPPORTS_INTERNAL_UPDATER", False
        ):
            dummy._refresh_about_update_widgets()

        self.assertTrue(dummy.settings_about_install_update_btn.enabled)
        self.assertEqual(dummy.settings_about_install_update_btn.text, "查看手动升级说明")
        self.assertEqual(dummy.settings_about_install_update_btn.tooltip, "查看当前版本对应的手动升级说明。")

    def test_about_update_install_disabled_reason_requires_manual_update_link_for_partial_macos_metadata(self):
        class DummyUsage(PersonalUsageMixin):
            _about_manual_update_action_target = PersonalUsageMixin._about_manual_update_action_target
            _about_update_install_disabled_reason = PersonalUsageMixin._about_update_install_disabled_reason

        dummy = DummyUsage()
        reason = dummy._about_update_install_disabled_reason(
            behind=True,
            update_info={"install_mode": "external", "target_version": "1.2.4"},
            supports_internal_update=False,
            manual_release_url="",
        )

        self.assertEqual(reason, "当前未拿到可用的发布页面或安装包链接，请先重新检测。")

    def test_open_launcher_install_recommended_dir_uses_user_applications_for_user_level_install(self):
        class DummyUsage(PersonalUsageMixin):
            _launcher_install_recommended_directory = PersonalUsageMixin._launcher_install_recommended_directory
            _open_launcher_install_recommended_dir = PersonalUsageMixin._open_launcher_install_recommended_dir

        dummy = DummyUsage()
        with mock.patch.object(personal_usage.lz, "IS_MACOS", True), mock.patch.object(
            personal_usage.lz,
            "macos_installation_status",
            return_value={
                "recommended_install_target": "/Users/tester/Applications/GenericAgent Launcher.app",
            },
        ), mock.patch.object(
            dummy, "_open_local_directory_path"
        ) as open_dir:
            dummy._open_launcher_install_recommended_dir()

        open_dir.assert_called_once_with("/Users/tester/Applications")

    def test_refresh_about_update_widgets_disables_manual_macos_update_without_links(self):
        class DummyLabel:
            def __init__(self):
                self.text = ""

            def setText(self, text):
                self.text = str(text)

        class DummyButton:
            def __init__(self):
                self.enabled = None
                self.tooltip = ""
                self.text = ""

            def setEnabled(self, value):
                self.enabled = bool(value)

            def setToolTip(self, text):
                self.tooltip = str(text)

            def setText(self, text):
                self.text = str(text)

        class DummyUsage(PersonalUsageMixin):
            _refresh_about_update_widgets = PersonalUsageMixin._refresh_about_update_widgets
            _refresh_about_update_diagnostics_widgets = PersonalUsageMixin._refresh_about_update_diagnostics_widgets
            _apply_personal_button_state = PersonalUsageMixin._apply_personal_button_state
            _about_update_check_disabled_reason = PersonalUsageMixin._about_update_check_disabled_reason
            _about_update_install_disabled_reason = PersonalUsageMixin._about_update_install_disabled_reason
            _kernel_sync_disabled_reason = PersonalUsageMixin._kernel_sync_disabled_reason

            def __init__(self):
                self.agent_dir = ""
                self._update_check_running = False
                self._kernel_repo_sync_running = False
                self._last_update_check_result = {
                    "launcher": {
                        "status": "behind",
                        "latest_release_url": "",
                        "update_info": None,
                    }
                }
                self.settings_about_update_status = DummyLabel()
                self.settings_about_update_diag_status = DummyLabel()
                self.settings_about_check_updates_btn = DummyButton()
                self.settings_about_install_update_btn = DummyButton()
                self.settings_about_sync_kernel_fetch_btn = DummyButton()
                self.settings_about_sync_kernel_pull_btn = DummyButton()

            def _update_history_brief_text(self, limit=3):
                return "history"

        dummy = DummyUsage()
        with mock.patch.object(lz, "is_valid_agent_dir", return_value=False), mock.patch.object(
            personal_usage.os.path, "isfile", return_value=False
        ), mock.patch.object(
            lz, "updater_executable_path", return_value=""
        ), mock.patch.object(
            lz, "PLATFORM_SUPPORTS_INTERNAL_UPDATER", False
        ):
            dummy._refresh_about_update_widgets()

        self.assertFalse(dummy.settings_about_install_update_btn.enabled)
        self.assertEqual(dummy.settings_about_install_update_btn.text, "查看手动升级说明")
        self.assertEqual(dummy.settings_about_install_update_btn.tooltip, "当前未拿到可用的发布页面或安装包链接，请先重新检测。")

    def test_refresh_about_update_widgets_disables_manual_macos_update_for_partial_metadata_without_links(self):
        class DummyLabel:
            def __init__(self):
                self.text = ""

            def setText(self, text):
                self.text = str(text)

        class DummyButton:
            def __init__(self):
                self.enabled = None
                self.tooltip = ""
                self.text = ""

            def setEnabled(self, value):
                self.enabled = bool(value)

            def setToolTip(self, text):
                self.tooltip = str(text)

            def setText(self, text):
                self.text = str(text)

        class DummyUsage(PersonalUsageMixin):
            _about_manual_update_action_target = PersonalUsageMixin._about_manual_update_action_target
            _refresh_about_update_widgets = PersonalUsageMixin._refresh_about_update_widgets
            _refresh_about_update_diagnostics_widgets = PersonalUsageMixin._refresh_about_update_diagnostics_widgets
            _apply_personal_button_state = PersonalUsageMixin._apply_personal_button_state
            _about_update_check_disabled_reason = PersonalUsageMixin._about_update_check_disabled_reason
            _about_update_install_disabled_reason = PersonalUsageMixin._about_update_install_disabled_reason
            _kernel_sync_disabled_reason = PersonalUsageMixin._kernel_sync_disabled_reason

            def __init__(self):
                self.agent_dir = ""
                self._update_check_running = False
                self._kernel_repo_sync_running = False
                self._last_update_check_result = {
                    "launcher": {
                        "status": "behind",
                        "latest_release_url": "",
                        "update_info": {
                            "install_mode": "external",
                            "target_version": "1.2.4",
                        },
                    }
                }
                self.settings_about_update_status = DummyLabel()
                self.settings_about_update_diag_status = DummyLabel()
                self.settings_about_check_updates_btn = DummyButton()
                self.settings_about_install_update_btn = DummyButton()
                self.settings_about_sync_kernel_fetch_btn = DummyButton()
                self.settings_about_sync_kernel_pull_btn = DummyButton()

            def _update_history_brief_text(self, limit=3):
                return "history"

        dummy = DummyUsage()
        with mock.patch.object(lz, "is_valid_agent_dir", return_value=False), mock.patch.object(
            personal_usage.os.path, "isfile", return_value=False
        ), mock.patch.object(
            lz, "updater_executable_path", return_value=""
        ), mock.patch.object(
            lz, "PLATFORM_SUPPORTS_INTERNAL_UPDATER", False
        ):
            dummy._refresh_about_update_widgets()

        self.assertFalse(dummy.settings_about_install_update_btn.enabled)
        self.assertEqual(dummy.settings_about_install_update_btn.text, "查看手动升级说明")
        self.assertEqual(dummy.settings_about_install_update_btn.tooltip, "当前未拿到可用的发布页面或安装包链接，请先重新检测。")

    def test_launcher_bootstrap_uses_semver_like_sort_for_versions(self):
        with tempfile.TemporaryDirectory() as td:
            versions_dir = os.path.join(td, "app", "versions")
            os.makedirs(os.path.join(versions_dir, "1.9.9"), exist_ok=True)
            os.makedirs(os.path.join(versions_dir, "1.10.0"), exist_ok=True)
            main_exe_name = "GenericAgentLauncher.exe"
            older_exe = os.path.join(versions_dir, "1.9.9", main_exe_name)
            newer_exe = os.path.join(versions_dir, "1.10.0", main_exe_name)
            for path in (older_exe, newer_exe):
                with open(path, "wb") as f:
                    f.write(b"main")

            with mock.patch.object(launcher_bootstrap, "MAIN_EXE_NAME", main_exe_name), mock.patch.object(
                launcher_bootstrap, "load_version_state", return_value={}
            ), mock.patch.object(
                launcher_bootstrap, "resolved_versions_dir", return_value=versions_dir
            ), mock.patch.object(launcher_bootstrap, "set_current_version") as set_current:
                picked = launcher_bootstrap._pick_target_executable()

            self.assertEqual(os.path.normcase(os.path.normpath(picked)), os.path.normcase(os.path.normpath(newer_exe)))
            set_current.assert_called_once_with("1.10.0", previous_version="", pending_update={})

    def test_update_public_key_loader_walks_up_from_version_dir(self):
        with tempfile.TemporaryDirectory() as td:
            install_root = os.path.join(td, "Programs", "GenericAgentLauncher")
            version_dir = os.path.join(install_root, "app", "versions", "1.2.3")
            os.makedirs(version_dir, exist_ok=True)
            key_path = os.path.join(install_root, "update_public_key.pem")
            expected = "-----BEGIN PUBLIC KEY-----\nabc123\n-----END PUBLIC KEY-----"
            with open(key_path, "w", encoding="utf-8") as f:
                f.write(expected + "\n")

            with mock.patch.object(constants, "APP_DIR", version_dir), mock.patch.dict(
                os.environ, {"GA_LAUNCHER_UPDATE_PUBLIC_KEY_PEM": ""}, clear=False
            ):
                loaded = constants._load_update_public_key()

            self.assertEqual(loaded, expected)

    def test_installer_uninstall_cleans_runtime_version_tree(self):
        root = os.path.dirname(os.path.dirname(__file__))
        path = os.path.join(root, "installer", "GenericAgentLauncher.iss")
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        self.assertIn("CloseApplications=yes", src)
        self.assertIn("RestartApplications=no", src)
        self.assertIn('Type: filesandordirs; Name: "{app}\\app"', src)
        self.assertIn('StateDir := ExpandConstant(\'{localappdata}\\GenericAgentLauncher\\state\');', src)
        self.assertIn('SaveStringToFile(StatePath, LauncherStateJson(), False)', src)
        self.assertIn('"current_version": "{#MyVersion}"', src)

    def test_cleanup_old_versions_uses_version_aware_sort(self):
        with tempfile.TemporaryDirectory() as td:
            versions_dir = os.path.join(td, "app", "versions")
            os.makedirs(os.path.join(versions_dir, "1.9.9"), exist_ok=True)
            os.makedirs(os.path.join(versions_dir, "1.10.0"), exist_ok=True)
            os.makedirs(os.path.join(versions_dir, "1.10.1"), exist_ok=True)

            with mock.patch.object(runtime, "resolved_versions_dir", return_value=versions_dir), mock.patch.object(
                runtime, "load_version_state", return_value={"current_version": "1.10.1", "previous_version": "1.10.0"}
            ):
                removed = runtime.cleanup_old_versions(keep_count=2)

            self.assertEqual(removed, ["1.9.9"])
            self.assertFalse(os.path.isdir(os.path.join(versions_dir, "1.9.9")))
            self.assertTrue(os.path.isdir(os.path.join(versions_dir, "1.10.0")))
            self.assertTrue(os.path.isdir(os.path.join(versions_dir, "1.10.1")))

    def test_normalize_token_usage_from_bubbles(self):
        session = {
            "id": "s1",
            "channel_id": "unknown",
            "bubbles": [
                {"role": "user", "text": "hello"},
                {"role": "assistant", "text": "world"},
            ],
        }
        lz._normalize_token_usage_inplace(session)

        usage = session["token_usage"]
        self.assertEqual(session["channel_id"], "launcher")
        self.assertEqual(usage["mode"], "estimate_chars_div_2_5")
        self.assertEqual(usage["turns"], 1)
        self.assertEqual(len(usage["events"]), 1)
        self.assertGreater(usage["total_tokens"], 0)

    def test_fold_turns_returns_fold_section(self):
        text = (
            "prefix\n"
            "**LLM Running (Turn 1) ...**"
            "<summary>first turn summary</summary>\n"
            "turn1 body\n"
            "**LLM Running (Turn 2) ...**"
            "final body"
        )
        segments = lz.fold_turns(text)
        self.assertGreaterEqual(len(segments), 2)
        self.assertTrue(any(seg.get("type") == "fold" for seg in segments))

    def test_model_api_helpers(self):
        payload = {
            "data": [
                {"id": "gpt-4.1"},
                {"id": "gpt-4.1"},
                {"name": "claude-opus"},
            ]
        }
        models = model_api._extract_model_ids(payload)
        self.assertEqual(models, ["gpt-4.1", "claude-opus"])

        base = model_api._oai_models_base("https://api.openai.com/v1/chat/completions")
        self.assertEqual(base, "https://api.openai.com/v1")

    def test_save_then_load_session(self):
        with tempfile.TemporaryDirectory() as td:
            session = {
                "id": "case1",
                "title": "demo",
                "channel_id": "launcher",
                "bubbles": [
                    {"role": "user", "text": "u"},
                    {"role": "assistant", "text": "a"},
                ],
            }
            lz.save_session(td, session, touch=False)
            loaded = lz.load_session(td, "case1")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["id"], "case1")
            self.assertIn("token_usage", loaded)

    def test_list_scheduled_tasks_reads_upstream_style_json(self):
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "reflect"), exist_ok=True)
            os.makedirs(os.path.join(td, "sche_tasks", "done"), exist_ok=True)
            with open(os.path.join(td, "reflect", "scheduler.py"), "w", encoding="utf-8") as f:
                f.write("# scheduler")
            with open(os.path.join(td, "sche_tasks", "morning.json"), "w", encoding="utf-8") as f:
                f.write(
                    '{"schedule":"08:00","repeat":"daily","enabled":true,"prompt":"生成晨报","max_delay_hours":6}'
                )
            with open(os.path.join(td, "sche_tasks", "done", "2026-04-22_0800_morning.md"), "w", encoding="utf-8") as f:
                f.write("done")

            data = lz.list_scheduled_tasks(td, now=None)

        self.assertTrue(data["supported"])
        self.assertEqual(len(data["tasks"]), 1)
        self.assertEqual(data["tasks"][0]["id"], "morning")
        self.assertEqual(data["tasks"][0]["repeat"], "daily")
        self.assertEqual(data["tasks"][0]["schedule"], "08:00")
        self.assertEqual(data["tasks"][0]["report_count"], 1)
        self.assertEqual(data["enabled_count"], 1)

    def test_scheduled_task_save_load_delete_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            payload = {
                "schedule": "09:30",
                "repeat": "weekday",
                "enabled": True,
                "prompt": "生成日报",
                "max_delay_hours": 4,
                "extra_fields": {"priority": "high"},
            }
            result = lz.save_scheduled_task(td, "day report", payload)
            loaded = lz.load_scheduled_task(td, result["task_id"])

            self.assertEqual(result["task_id"], "day_report")
            self.assertEqual(loaded["schedule"], "09:30")
            self.assertEqual(loaded["repeat"], "weekday")
            self.assertTrue(loaded["enabled"])
            self.assertEqual(loaded["extra_fields"]["priority"], "high")
            self.assertTrue(lz.delete_scheduled_task(td, result["task_id"]))
            self.assertFalse(os.path.exists(os.path.join(td, "sche_tasks", "day_report.json")))

    def test_normalize_scheduled_task_id_strips_invalid_filename_chars(self):
        self.assertEqual(lz.normalize_scheduled_task_id(' 早报 : 任务 ? '), "早报_任务")


if __name__ == "__main__":
    unittest.main()
