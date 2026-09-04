import os
import sys
import tempfile
from types import ModuleType
import unittest
from pathlib import Path
from unittest.mock import patch

from desktop.credentials import CredentialStore
from desktop.paths import app_root, resource_path, state_db_path, temp_root
from desktop.tempfiles import TaskTempFiles


class MemoryKeyring:
    def __init__(self):
        self.values = {}

    def set_password(self, service, name, secret):
        self.values[(service, name)] = secret

    def get_password(self, service, name):
        return self.values.get((service, name))

    def delete_password(self, service, name):
        del self.values[(service, name)]


class WindowsBackend:
    __module__ = "keyring.backends.Windows.WinVaultKeyring"


class NonWindowsBackend:
    __module__ = "keyring.backends.SecretService"


class FailingKeyring:
    def set_password(self, service, name, secret):
        raise RuntimeError("refused " + secret)


class DesktopSecurityTests(unittest.TestCase):
    def test_credentials_use_injected_backend_reject_blank_and_keep_secret_out_of_errors(self):
        backend = MemoryKeyring()
        store = CredentialStore(backend)
        store.set_api_key("profile", "sk-synthetic-secret")
        self.assertEqual(store.get_api_key("profile"), "sk-synthetic-secret")
        store.delete_api_key("profile")
        self.assertIsNone(store.get_api_key("profile"))
        for value in (None, "", "  "):
            with self.assertRaises(ValueError) as raised:
                store.set_api_key("profile", value)
            self.assertNotIn("sk-synthetic-secret", str(raised.exception))
        self.assertNotIn("sk-synthetic-secret", repr(store))

    def test_credential_backend_error_does_not_echo_secret(self):
        with self.assertRaises(RuntimeError) as raised:
            CredentialStore(FailingKeyring()).set_api_key("profile", "sk-synthetic-secret")
        self.assertNotIn("sk-synthetic-secret", str(raised.exception))

    def test_windows_backend_validation_checks_backend_module(self):
        CredentialStore(WindowsBackend()).assert_windows_backend()
        with self.assertRaisesRegex(RuntimeError, "Windows Credential Locker") as raised:
            CredentialStore(NonWindowsBackend()).assert_windows_backend()
        self.assertNotIn("sk-synthetic-secret", str(raised.exception))

    def test_default_store_lazily_resolves_actual_keyring_backend(self):
        keyring_module = ModuleType("keyring")
        backend = WindowsBackend()
        keyring_module.get_keyring = lambda: backend
        with patch.dict(sys.modules, {"keyring": keyring_module}):
            CredentialStore().assert_windows_backend()

    def test_local_app_paths_never_fall_back_when_localappdata_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "LOCALAPPDATA"):
                app_root()
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {"LOCALAPPDATA": td}, clear=True):
            root = app_root()
            self.assertEqual(root, Path(td) / "RiskAssessmentHeatMap")
            self.assertEqual(state_db_path(), root / "state.db")
            self.assertEqual(temp_root(), root / "temp")

    def test_resource_path_rejects_absolute_and_traversal(self):
        safe = resource_path("web/risk_heatmap.html")
        self.assertTrue(safe.is_absolute())
        for unsafe in ("../secret", "web/../../secret", "/absolute", "C:\\absolute"):
            with self.assertRaises(ValueError):
                resource_path(unsafe)

    def test_resource_path_uses_meipass_when_frozen(self):
        with tempfile.TemporaryDirectory() as td, patch.object(sys, "frozen", True, create=True), patch.object(sys, "_MEIPASS", td, create=True):
            resolved = resource_path("assets/icon.png")
            self.assertEqual(resolved, (Path(td) / "assets" / "icon.png").resolve())
            self.assertIn(Path(td).resolve(), resolved.parents)

    def test_task_temp_files_create_cleanup_and_reject_invalid_ids(self):
        with tempfile.TemporaryDirectory() as td:
            temp = TaskTempFiles(Path(td) / "temp")
            target = temp.create("task_1-OK")
            self.assertTrue(target.is_dir())
            self.assertEqual(temp.task_dir("task_1-OK"), target)
            self.assertEqual(temp.cleanup("task_1-OK"), [])
            self.assertFalse(target.exists())
            self.assertEqual(temp.cleanup("task_1-OK"), [])
            for unsafe in ("", "../escape", "a/b", "a\\b", ".", "space id"):
                with self.assertRaises(ValueError):
                    temp.create(unsafe)

    def test_temp_cleanup_returns_residual_without_deleting_root_on_failure(self):
        with tempfile.TemporaryDirectory() as td:
            temp = TaskTempFiles(Path(td) / "temp")
            target = temp.create("T1")
            with patch("desktop.tempfiles.shutil.rmtree", side_effect=OSError("blocked")):
                self.assertEqual(temp.cleanup("T1"), [target])
            self.assertTrue(target.exists())
            self.assertTrue(temp.root.exists())


if __name__ == "__main__":
    unittest.main()
