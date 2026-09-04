"""API-key storage backed by Windows Credential Locker through keyring."""

from typing import Any


SERVICE_NAME = "RiskAssessmentHeatMap"


class CredentialStore:
    """Keep model API keys out of application state and diagnostics."""

    def __init__(self, backend: Any | None = None) -> None:
        if backend is None:
            # Import only at runtime: unit tests and non-model actions need no keyring package.
            import keyring

            backend = keyring.get_keyring()
        self._backend = backend

    @staticmethod
    def _profile_name(profile_name: str) -> str:
        if not isinstance(profile_name, str) or not profile_name.strip():
            raise ValueError("profile name is required")
        return profile_name.strip()

    def set_api_key(self, profile_name: str, api_key: str) -> None:
        profile = self._profile_name(profile_name)
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("API key is required")
        try:
            self._backend.set_password(SERVICE_NAME, profile, api_key)
        except Exception:
            raise RuntimeError("unable to store API key") from None

    def get_api_key(self, profile_name: str) -> str | None:
        try:
            return self._backend.get_password(SERVICE_NAME, self._profile_name(profile_name))
        except Exception:
            raise RuntimeError("unable to retrieve API key") from None

    def delete_api_key(self, profile_name: str) -> None:
        try:
            self._backend.delete_password(SERVICE_NAME, self._profile_name(profile_name))
        except Exception as exc:
            # Missing credentials are already absent; do not leak backend details or secrets.
            if exc.__class__.__name__ not in {"PasswordDeleteError", "KeyError"}:
                raise RuntimeError("unable to delete API key") from None

    def assert_windows_backend(self) -> None:
        module = self._backend.__class__.__module__
        if not module.startswith("keyring.backends.Windows"):
            raise RuntimeError("模型密钥必须使用 Windows Credential Locker")
