"""Create/check only explicitly marked synthetic state for installer acceptance."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop.credentials import CredentialStore
from desktop.models import ModelProfile
from desktop.storage import DesktopStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("seed", "check", "cleanup"))
    parser.add_argument("root", type=Path)
    parser.add_argument("token")
    args = parser.parse_args()
    root = args.root.resolve()
    if not args.token.isalnum() or not root.name.startswith("rahm-release-"):
        raise SystemExit("SYNTHETIC_ROOT_REQUIRED")
    marker = root / "acceptance-marker.txt"
    if not marker.is_file() or marker.read_text(encoding="utf-8") != args.token:
        raise SystemExit("SYNTHETIC_MARKER_REQUIRED")
    profile_name = "rahm-release-synthetic-" + args.token
    credential = "synthetic-not-a-real-api-key-" + args.token
    credentials = CredentialStore()
    credentials.assert_windows_backend()
    if args.action == "cleanup":
        credentials.delete_api_key(profile_name)
        print("SYNTHETIC_CREDENTIAL_REMOVED")
        return
    state = root / "user-state" / "RiskAssessmentHeatMap"
    manifest_path = root / "synthetic-state-hashes.json"
    if args.action == "seed":
        store = DesktopStore(state / "state.db")
        store.save_model_profile(ModelProfile(profile_name, "https://model.example.test/v1", "synthetic-model", False))
        store.set_setting("catalog_root", str(root / "catalog"))
        catalog = root / "catalog"
        catalog.mkdir(exist_ok=True)
        (catalog / "retained-synthetic-report.json").write_text(
            json.dumps({"entity":"SYNTHETIC ONLY", "finding":"fictional audit finding"}), encoding="utf-8")
        credentials.set_api_key(profile_name, credential)
        paths = [state / "state.db", catalog / "retained-synthetic-report.json"]
        hashes = {str(path.relative_to(root)):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        manifest_path.write_text(json.dumps(hashes), encoding="utf-8")
        print("SYNTHETIC_STATE_SEEDED")
    else:
        hashes = json.loads(manifest_path.read_text(encoding="utf-8"))
        for name, expected in hashes.items():
            path = (root / name).resolve()
            if root not in path.parents or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise SystemExit("SYNTHETIC_STATE_CHANGED")
        profiles = DesktopStore(state / "state.db").list_model_profiles()
        if len(profiles) != 1 or profiles[0].name != profile_name:
            raise SystemExit("SYNTHETIC_PROFILE_CHANGED")
        if credentials.get_api_key(profile_name) != credential:
            raise SystemExit("SYNTHETIC_CREDENTIAL_CHANGED")
        print("SYNTHETIC_STATE_AND_CREDENTIAL_PRESERVED")


if __name__ == "__main__":
    main()
