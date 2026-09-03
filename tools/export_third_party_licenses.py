"""Export redistributable notices from the exact installed wheel contents.

This tool deliberately does not use ``THIRD_PARTY_NOTICES.md`` as a source of
license text.  A metadata License-Expression is useful evidence, but it cannot
replace a file that must be shipped with a binary or model.
"""

from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
from pathlib import Path
import re
import shutil
import sys
from typing import Iterable


CRITICAL_PACKAGES = ("pypdfium2", "RapidOCR", "onnxruntime", "pywebview", "keyring", "PyInstaller")
NOTICE_NAME = re.compile(r"(?:^|/)(?:LICENSE[^/]*|COPYING[^/]*|NOTICE[^/]*)$", re.IGNORECASE)
RAPIDOCR_TAG = "v3.9.2"
RAPIDOCR_COMMIT = "095232a4c94f7f0e6600ba5bba1177010ad696d4"
RAPIDOCR_LICENSE_SHA256 = "3e0af25fdd06aa9586ae97adb00ea927ebe5a3805ac77d2d3a81ce5f55693333"
RAPIDOCR_MODELS = ("PP-OCRv6_det_small.onnx", "PP-OCRv6_rec_small.onnx", "ch_ppocr_mobile_v2.0_cls_mobile.onnx")
RAPIDOCR_LICENSE_URL = "https://raw.githubusercontent.com/RapidAI/RapidOCR/v3.9.2/LICENSE"


class LicenseMaterialUnavailable(RuntimeError):
    """A required wheel notice was absent; packaging must not continue."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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


def _verified_rapidocr_vendor() -> tuple[list[Path], dict[str, object]]:
    directory = Path(__file__).resolve().parents[1] / "licenses" / "RapidOCR-3.9.2"
    license_file, model_notice = directory / "LICENSE", directory / "MODEL_NOTICE.md"
    if not license_file.is_file():
        raise LicenseMaterialUnavailable("BLOCKED package=RapidOCR/model file=licenses/RapidOCR-3.9.2/LICENSE")
    if _sha256(license_file) != RAPIDOCR_LICENSE_SHA256:
        raise LicenseMaterialUnavailable("BLOCKED package=RapidOCR/model file=licenses/RapidOCR-3.9.2/LICENSE hash-mismatch")
    body = license_file.read_text(encoding="utf-8")
    if "Apache License" not in body or "Version 2.0" not in body:
        raise LicenseMaterialUnavailable("BLOCKED package=RapidOCR/model file=licenses/RapidOCR-3.9.2/LICENSE invalid-apache-text")
    if not model_notice.is_file():
        raise LicenseMaterialUnavailable("BLOCKED package=RapidOCR/model file=licenses/RapidOCR-3.9.2/MODEL_NOTICE.md")
    notice = model_notice.read_text(encoding="utf-8")
    required = (RAPIDOCR_TAG, RAPIDOCR_COMMIT, RAPIDOCR_LICENSE_URL, *RAPIDOCR_MODELS, "Baidu", "Apache-2.0")
    if any(value not in notice for value in required):
        raise LicenseMaterialUnavailable("BLOCKED package=RapidOCR/model file=licenses/RapidOCR-3.9.2/MODEL_NOTICE.md provenance-invalid")
    return [license_file, model_notice], {
        "tag": RAPIDOCR_TAG,
        "commit": RAPIDOCR_COMMIT,
        "source_url": RAPIDOCR_LICENSE_URL,
        "models": list(RAPIDOCR_MODELS),
    }


def _copy_package(name: str, output: Path) -> dict[str, object]:
    try:
        distribution = metadata.distribution(name)
    except metadata.PackageNotFoundError as exc:
        raise LicenseMaterialUnavailable(f"BLOCKED package={name} file=distribution-metadata") from exc
    files = _license_files(distribution)
    normalized = name.lower()
    vendored_provenance: dict[str, object] | None = None
    if normalized == "rapidocr":
        vendor_files, vendored_provenance = _verified_rapidocr_vendor()
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
            "source_file": str(source),
            "sha256": _sha256(target),
        })
    record: dict[str, object] = {
        "name": distribution.metadata["Name"],
        "version": distribution.version,
        "metadata_license": distribution.metadata.get("License-Expression") or distribution.metadata.get("License") or None,
        "files": manifest_files,
    }
    if vendored_provenance is not None:
        record["vendored_provenance"] = vendored_provenance
    return record


def export_licenses(output: Path, packages: Iterable[str], *, require_critical: bool = True) -> dict[str, object]:
    """Copy actual wheel notice files and return the deterministic manifest."""
    output = output.resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    requested = tuple(packages)
    records: list[dict[str, object]] = []
    try:
        for package in requested:
            records.append(_copy_package(package, output))
        if require_critical:
            requested_names = {name.lower() for name in requested}
            missing = [name for name in CRITICAL_PACKAGES if name.lower() not in requested_names]
            if missing:
                raise LicenseMaterialUnavailable(f"BLOCKED package={missing[0]} file=required-package-not-requested")
    except Exception:
        # An incomplete notices directory must never look release-ready.
        shutil.rmtree(output, ignore_errors=True)
        raise
    manifest = {"schema": 1, "packages": records}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--packages", nargs="+", default=list(CRITICAL_PACKAGES))
    parser.add_argument("--allow-noncritical", action="store_true")
    args = parser.parse_args(argv)
    try:
        manifest = export_licenses(args.output, args.packages, require_critical=not args.allow_noncritical)
    except LicenseMaterialUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"LICENSE_EXPORT_OK packages={len(manifest['packages'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
