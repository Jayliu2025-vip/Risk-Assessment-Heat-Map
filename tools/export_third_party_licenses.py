"""Export redistributable notices from the exact installed wheel contents.

This tool deliberately does not use ``THIRD_PARTY_NOTICES.md`` as a source of
license text.  A metadata License-Expression is useful evidence, but it cannot
replace a file that must be shipped with a binary or model.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
from importlib import metadata
import json
from pathlib import Path
import re
import shutil
import sys
from typing import Iterable

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


LOCK_PATH = Path(__file__).resolve().parents[1] / "packaging" / "distribution_packages.lock.json"
NOTICE_NAME = re.compile(r"(?:^|/)(?:LICENSE[^/]*|LICENCE[^/]*|COPYING[^/]*|NOTICE[^/]*)$", re.IGNORECASE)


class LicenseMaterialUnavailable(RuntimeError):
    """A required wheel notice was absent; packaging must not continue."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_lock() -> dict[str, object]:
    try:
        payload = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise LicenseMaterialUnavailable("BLOCKED package=distribution-lock file=packaging/distribution_packages.lock.json") from exc
    if payload.get("schema") != 2:
        raise LicenseMaterialUnavailable("BLOCKED package=distribution-lock file=schema")
    packages = payload.get("packages")
    if not packages or any(not isinstance(item, dict) or not item.get("name") or not item.get("version") for item in packages):
        raise LicenseMaterialUnavailable("BLOCKED package=distribution-lock file=invalid")
    return payload


def _locked_packages() -> tuple[dict[str, object], ...]:
    return tuple(_load_lock()["packages"])


def _resolved_distribution_closure(lock: dict[str, object]) -> dict[str, metadata.Distribution]:
    """Resolve the exact active-marker closure for this Windows/Python target."""
    target = lock["target"]
    if sys.platform != target["sys_platform"] or f"{sys.version_info.major}.{sys.version_info.minor}" != target["python_version"]:
        raise LicenseMaterialUnavailable(
            f"BLOCKED package=distribution-lock file=target expected={target['sys_platform']}/py{target['python_version']}"
        )
    installed = {canonicalize_name(item.metadata["Name"]): item for item in metadata.distributions()}
    environment = default_environment()
    resolved: dict[str, metadata.Distribution] = {}
    pending = [item["name"] for item in lock["roots"]]
    while pending:
        requested = canonicalize_name(pending.pop())
        if requested in resolved:
            continue
        distribution = installed.get(requested)
        if distribution is None:
            raise LicenseMaterialUnavailable(f"BLOCKED package={requested} file=distribution-metadata")
        resolved[requested] = distribution
        for raw_requirement in distribution.requires or ():
            requirement = Requirement(raw_requirement)
            if requirement.marker and not requirement.marker.evaluate(environment):
                continue
            pending.append(requirement.name)
    locked = {canonicalize_name(item["name"]): item["version"] for item in lock["packages"]}
    actual = {name: distribution.version for name, distribution in resolved.items()}
    if actual != locked:
        missing = sorted(set(actual) - set(locked))
        surplus = sorted(set(locked) - set(actual))
        mismatched = sorted(name for name in set(actual) & set(locked) if actual[name] != locked[name])
        detail = f"missing={missing} surplus={surplus} version_mismatch={mismatched}"
        raise LicenseMaterialUnavailable(f"BLOCKED package=distribution-lock file=closure {detail}")
    return resolved


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def _license_files(distribution: metadata.Distribution) -> list[Path]:
    files: list[Path] = []
    for relative in distribution.files or ():
        rendered = relative.as_posix()
        if NOTICE_NAME.search(rendered) or "BUILD_LICENSES" in rendered.upper():
            located = Path(distribution.locate_file(relative))
            if located.is_file():
                files.append(located)
    return sorted(set(files), key=lambda path: str(path).lower())


def _artifact_sha256(distribution: metadata.Distribution) -> str:
    """Hash the installed wheel payload selected by the distribution RECORD."""
    digest = hashlib.sha256()
    for relative in sorted(distribution.files or (), key=lambda item: item.as_posix().lower()):
        path = Path(distribution.locate_file(relative))
        if not path.is_file():
            continue
        digest.update(relative.as_posix().encode("utf-8") + b"\0")
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def _source_identifier(source: Path, distribution: metadata.Distribution) -> str:
    """Return stable package-relative or repository-relative provenance only."""
    source = source.resolve()
    site_root = Path(distribution.locate_file(".")).resolve()
    repo_root = Path(__file__).resolve().parents[1]
    try:
        return "distribution:" + source.relative_to(site_root).as_posix()
    except ValueError:
        try:
            return "vendor:" + source.relative_to(repo_root).as_posix()
        except ValueError:
            raise LicenseMaterialUnavailable(f"BLOCKED package={distribution.metadata['Name']} file=untraceable-license-source")


def _verified_locked_vendor(package: dict[str, object]) -> tuple[list[Path], dict[str, object] | None]:
    provenance = package.get("vendored_provenance")
    if provenance is None:
        return [], None
    if not isinstance(provenance, dict):
        raise LicenseMaterialUnavailable(f"BLOCKED package={package['name']} file=vendored-provenance")
    required = ("provenance_type", "source_url", "source_filename", "source_sha256", "license_path", "license_sha256")
    if any(not provenance.get(field) for field in required):
        raise LicenseMaterialUnavailable(f"BLOCKED package={package['name']} file=vendored-provenance-incomplete")
    repo_root = Path(__file__).resolve().parents[1]
    specifications = [provenance, *provenance.get("additional_license_files", [])]
    files: list[Path] = []
    for specification in specifications:
        relative = Path(specification["license_path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise LicenseMaterialUnavailable(f"BLOCKED package={package['name']} file=unsafe-vendor-path")
        source = repo_root / relative
        if not source.is_file() or _sha256(source) != specification["license_sha256"]:
            raise LicenseMaterialUnavailable(f"BLOCKED package={package['name']} file={relative.as_posix()} hash-mismatch")
        files.append(source)
    rendered = dict(provenance)
    if rendered["provenance_type"] == "pypi_sdist":
        rendered["sdist_sha256"] = rendered["source_sha256"]
    return files, rendered


def _copy_package(
    name: str,
    output: Path,
    expected_version: str | None = None,
    lock_package: dict[str, object] | None = None,
) -> dict[str, object]:
    try:
        distribution = metadata.distribution(name)
    except metadata.PackageNotFoundError as exc:
        raise LicenseMaterialUnavailable(f"BLOCKED package={name} file=distribution-metadata") from exc
    files = _license_files(distribution)
    if expected_version is not None and distribution.version != expected_version:
        raise LicenseMaterialUnavailable(f"BLOCKED package={name} file=version expected={expected_version} actual={distribution.version}")
    normalized = canonicalize_name(name)
    vendored_provenance: dict[str, object] | None = None
    if lock_package is not None:
        vendor_files, vendored_provenance = _verified_locked_vendor(lock_package)
        files.extend(vendor_files)
    if not files:
        expression = distribution.metadata.get("License-Expression") or distribution.metadata.get("License") or ""
        raise LicenseMaterialUnavailable(
            f"BLOCKED package={name} file=LICENSE* metadata_license={expression or 'missing'}"
        )
    if normalized == "pypdfium2" and not any("BUILD_LICENSES" in str(path).upper() for path in files):
        raise LicenseMaterialUnavailable("BLOCKED package=pypdfium2/PDFium file=BUILD_LICENSES")
    if normalized == "rapidocr":
        model_files = [Path(distribution.locate_file(relative)) for relative in distribution.files or ()
                       if "/models/" in relative.as_posix().lower() and relative.suffix.lower() in {".onnx", ".bin"}]
        if model_files and not files:
            raise LicenseMaterialUnavailable("BLOCKED package=RapidOCR/model file=LICENSE-or-NOTICE")
    package_root = output / _safe_name(distribution.metadata["Name"]) / distribution.version
    manifest_files: list[dict[str, str]] = []
    for source in files:
        relative = source.name
        # Preserve enough source structure to prevent collisions among BUILD_LICENSES.
        source_text = str(source).replace("\\", "/")
        marker = "/licenses/"
        suffix = source_text.split(marker, 1)[1] if marker in source_text else source.name
        target = package_root / _sha256(source)[:16] / Path(suffix)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        manifest_files.append({
            "path": target.relative_to(output).as_posix(),
            "source_file": _source_identifier(source, distribution),
            "sha256": _sha256(target),
        })
    record: dict[str, object] = {
        "name": distribution.metadata["Name"],
        "version": distribution.version,
        "metadata_license": distribution.metadata.get("License-Expression") or distribution.metadata.get("License") or None,
        "artifact_sha256": _artifact_sha256(distribution),
        "files": manifest_files,
    }
    if vendored_provenance is not None:
        record["vendored_provenance"] = vendored_provenance
    return record


def _copy_component(component: dict[str, object], output: Path) -> dict[str, object]:
    name = str(component["name"])
    raw_locators = component.get("artifact_locators") or component.get("ambient_native_names") or [component.get("artifact_locator")]
    locators = [Path(value) for value in raw_locators]
    if not locators or any(str(locator) in {"", "None"} for locator in locators):
        raise LicenseMaterialUnavailable(f"BLOCKED package={name} file=artifact-locator")
    files: list[Path]
    source_ids: dict[Path, str] = {}
    provenance: dict[str, object] | None = None
    if name == "CPython":
        artifacts = [Path(sys.base_prefix) / locator for locator in locators]
        files, provenance = _verified_locked_vendor(
            {"name": name, "vendored_provenance": component["vendored_provenance"]}
        )
        repo_root = Path(__file__).resolve().parents[1]
        source_ids = {path: "vendor:" + path.relative_to(repo_root).as_posix() for path in files}
    elif name == "PyInstaller bootloader":
        distribution = metadata.distribution(str(component["license_distribution"]))
        if distribution.version != component["version"]:
            raise LicenseMaterialUnavailable(
                f"BLOCKED package={name} file=version expected={component['version']} actual={distribution.version}"
            )
        artifacts = [Path(distribution.locate_file(locator)) for locator in locators]
        files = _license_files(distribution)
        source_ids = {path: _source_identifier(path, distribution) for path in files}
    elif component.get("artifact_distribution"):
        distribution = metadata.distribution(str(component["artifact_distribution"]))
        artifacts = [Path(distribution.locate_file(locator)) for locator in locators]
        files, provenance = _verified_locked_vendor(
            {"name": name, "vendored_provenance": component["vendored_provenance"]}
        )
        repo_root = Path(__file__).resolve().parents[1]
        source_ids = {path: "vendor:" + path.relative_to(repo_root).as_posix() for path in files}
    elif component.get("artifact_source") == "packaging-cache":
        repo_root = Path(__file__).resolve().parents[1]
        artifacts = [repo_root / "packaging" / "cache" / locator for locator in locators]
        for locator, artifact in zip(locators, artifacts, strict=True):
            if not artifact.is_file() or component.get("artifact_sha256") != _sha256(artifact):
                raise LicenseMaterialUnavailable(f"BLOCKED package={name} file={locator.as_posix()} hash-mismatch")
        files, provenance = _verified_locked_vendor(
            {"name": name, "vendored_provenance": component["vendored_provenance"]}
        )
        source_ids = {path: "vendor:" + path.relative_to(repo_root).as_posix() for path in files}
    else:
        raise LicenseMaterialUnavailable(f"BLOCKED package={name} file=unknown-component")
    for locator, artifact in zip(locators, artifacts, strict=True):
        if not artifact.is_file():
            raise LicenseMaterialUnavailable(f"BLOCKED package={name} file={locator.as_posix()}")
    if not files:
        raise LicenseMaterialUnavailable(f"BLOCKED package={name} file=LICENSE*")
    component_root = output / "components" / _safe_name(name) / str(component["version"])
    manifest_files: list[dict[str, str]] = []
    for source in files:
        target = component_root / _sha256(source)[:16] / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        manifest_files.append(
            {
                "path": target.relative_to(output).as_posix(),
                "source_file": source_ids[source],
                "sha256": _sha256(target),
            }
        )
    artifact_digest = hashlib.sha256()
    artifact_files: list[dict[str, str]] = []
    for locator, artifact in zip(locators, artifacts, strict=True):
        file_hash = _sha256(artifact)
        artifact_digest.update(locator.as_posix().encode("utf-8") + b"\0" + bytes.fromhex(file_hash))
        artifact_files.append({"path": locator.as_posix(), "sha256": file_hash})
    artifact_hash = artifact_files[0]["sha256"] if len(artifact_files) == 1 else artifact_digest.hexdigest()
    record: dict[str, object] = {
        "name": name,
        "version": component["version"],
        "kind": component["kind"],
        "artifact_sha256": artifact_hash,
        "artifacts": artifact_files,
        "files": manifest_files,
    }
    if provenance is not None:
        record["vendored_provenance"] = provenance
    return record


def export_licenses(output: Path, packages: Iterable[str] | None = None, *, require_critical: bool = True) -> dict[str, object]:
    """Copy actual wheel notice files and return the deterministic manifest."""
    output = output.resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    lock = _load_lock()
    locked = tuple(lock["packages"])
    if packages is None:
        _resolved_distribution_closure(lock)
    requested = tuple(packages) if packages is not None else tuple(item["name"] for item in locked)
    lock_by_name = {canonicalize_name(item["name"]): item for item in locked}
    expected_versions = {name: item["version"] for name, item in lock_by_name.items()}
    records: list[dict[str, object]] = []
    components: list[dict[str, object]] = []
    try:
        for package in requested:
            normalized = canonicalize_name(package)
            records.append(_copy_package(package, output, expected_versions.get(normalized), lock_by_name.get(normalized)))
        if require_critical:
            requested_names = {canonicalize_name(name) for name in requested}
            missing = [item["name"] for item in locked if canonicalize_name(item["name"]) not in requested_names]
            if missing:
                raise LicenseMaterialUnavailable(f"BLOCKED package={missing[0]} file=required-package-not-requested")
            components = [_copy_component(item, output) for item in lock["components"]]
    except Exception:
        # An incomplete notices directory must never look release-ready.
        shutil.rmtree(output, ignore_errors=True)
        raise
    manifest = {
        "schema": 2,
        "target": lock["target"],
        "packages": records,
        "components": components,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def _walk_strings(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _walk_strings(item)
    elif isinstance(value, dict):
        for item in value.items():
            yield from _walk_strings(item)


def _installed_file_owners() -> dict[Path, set[str]]:
    owners: dict[Path, set[str]] = {}
    for distribution in metadata.distributions():
        name = canonicalize_name(distribution.metadata["Name"])
        for relative in distribution.files or ():
            located = Path(distribution.locate_file(relative))
            try:
                resolved = located.resolve(strict=True)
            except OSError:
                continue
            owners.setdefault(resolved, set()).add(name)
    return owners


def audit_analysis_toc(
    toc_path: Path,
    lock: dict[str, object] | None = None,
    dist_root: Path | None = None,
    collect_toc_path: Path | None = None,
) -> dict[str, object]:
    """Block a build when its PyInstaller inputs expose an unlocked distribution."""
    lock = _load_lock() if lock is None else lock
    try:
        payload = ast.literal_eval(toc_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError) as exc:
        raise LicenseMaterialUnavailable(f"BLOCKED package=pyinstaller-analysis file={toc_path.name}") from exc
    native_payload = payload
    if collect_toc_path is not None:
        try:
            native_payload = ast.literal_eval(collect_toc_path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError) as exc:
            raise LicenseMaterialUnavailable(f"BLOCKED package=pyinstaller-collect file={collect_toc_path.name}") from exc
    owners = _installed_file_owners()
    detected: set[str] = set()
    ambient_native: set[str] = set()
    python_base = Path(sys.base_prefix).resolve()
    declared_component_binaries = {
        value.lower()
        for component in lock.get("components", [])
        for value in component.get("collect_native_names", [])
    }
    for value in _walk_strings(payload):
        candidate = Path(value)
        if not candidate.is_absolute():
            continue
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        file_owners = owners.get(resolved, ())
        detected.update(file_owners)
    for value in _walk_strings(native_payload):
        candidate = Path(value)
        if not candidate.is_absolute():
            continue
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        file_owners = owners.get(resolved, ())
        if (
            resolved.suffix.lower() in {".dll", ".exe", ".pyd", ".so", ".dylib"}
            and not file_owners
            and not resolved.is_relative_to(python_base)
            and resolved.name.lower() not in declared_component_binaries
        ):
            ambient_native.add(resolved.name)
    locked = {canonicalize_name(item["name"]): item for item in lock["packages"]}
    unknown = sorted(detected - set(locked))
    if unknown:
        raise LicenseMaterialUnavailable(f"BLOCKED package={unknown[0]} file=unlocked-pyinstaller-input")
    if ambient_native:
        first = sorted(ambient_native, key=str.lower)[0]
        raise LicenseMaterialUnavailable(f"BLOCKED package={first} file=ambient-native-runtime")
    missing_required = sorted(
        name for name, item in locked.items() if item.get("audit_required") and name not in detected
    )
    if missing_required:
        raise LicenseMaterialUnavailable(f"BLOCKED package={missing_required[0]} file=missing-pyinstaller-input")
    if dist_root is not None:
        dist_root = dist_root.resolve()
        manifest_path = dist_root / "_internal" / "licenses" / "manifest.json"
        expected = {
            "PyInstaller bootloader": dist_root / "RiskAssessmentHeatMap.exe",
            "CPython": dist_root / "_internal" / "python313.dll",
            "license manifest": manifest_path,
        }
        for component, path in expected.items():
            if not path.is_file():
                raise LicenseMaterialUnavailable(f"BLOCKED package={component} file=missing-packaged-component")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise LicenseMaterialUnavailable("BLOCKED package=license-manifest file=invalid") from exc
        manifest_packages = {canonicalize_name(item["name"]) for item in manifest.get("packages", [])}
        missing_manifest_package = sorted(set(locked) - manifest_packages)
        if missing_manifest_package:
            raise LicenseMaterialUnavailable(
                f"BLOCKED package={missing_manifest_package[0]} file=missing-license-manifest-package"
            )
        expected_components = {item["name"] for item in lock.get("components", [])}
        manifest_components = {item["name"] for item in manifest.get("components", [])}
        missing_manifest_component = sorted(expected_components - manifest_components)
        if missing_manifest_component:
            raise LicenseMaterialUnavailable(
                f"BLOCKED package={missing_manifest_component[0]} file=missing-license-manifest-component"
            )
    return {
        "detected_distributions": sorted(detected),
        "locked_distributions": len(locked),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--packages", nargs="+")
    parser.add_argument("--allow-noncritical", action="store_true")
    parser.add_argument("--audit-analysis", type=Path)
    parser.add_argument("--audit-collect", type=Path)
    parser.add_argument("--dist-root", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.audit_analysis:
            result = audit_analysis_toc(
                args.audit_analysis,
                dist_root=args.dist_root,
                collect_toc_path=args.audit_collect,
            )
            print(
                "PACKAGED_DISTRIBUTION_AUDIT_OK "
                f"detected={len(result['detected_distributions'])} locked={result['locked_distributions']}"
            )
            return 0
        if args.output is None:
            parser.error("--output is required unless --audit-analysis is used")
        manifest = export_licenses(args.output, args.packages, require_critical=not args.allow_noncritical)
    except LicenseMaterialUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"LICENSE_EXPORT_OK packages={len(manifest['packages'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
