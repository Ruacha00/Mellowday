"""PEP 517 backend that verifies the generated frontend before packaging."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, cast

from setuptools import build_meta as _setuptools  # type: ignore[import-untyped]


_PROJECT_ROOT = Path(__file__).resolve().parent
_FRONTEND_OUTPUT = (
    _PROJECT_ROOT / "src" / "mellowday" / "web_app" / "static" / "replacement"
)
_MANIFEST_PATH = _FRONTEND_OUTPUT / ".vite" / "manifest.json"
_STATIC_URL_PREFIX = "/static/replacement/"
_BUILT_URL_PATTERN = re.compile(
    r"(?:src|href)=[\"']([^\"']+)[\"']|url\(\s*[\"']?([^\"')\s]+)",
    re.IGNORECASE,
)


def _manifest_paths(manifest: Mapping[str, Any]) -> Iterable[str]:
    for source, entry in manifest.items():
        if not isinstance(entry, Mapping):
            raise RuntimeError(f"Invalid Vite manifest entry: {source}")
        file_name = entry.get("file")
        if isinstance(file_name, str):
            yield file_name
        for field in ("css", "assets"):
            paths = entry.get(field, [])
            if not isinstance(paths, list) or not all(
                isinstance(path, str) for path in paths
            ):
                raise RuntimeError(
                    f"Invalid Vite manifest {field} list: {source}"
                )
            yield from paths
        for field in ("imports", "dynamicImports"):
            sources = entry.get(field, [])
            if not isinstance(sources, list) or not all(
                isinstance(item, str) for item in sources
            ):
                raise RuntimeError(
                    f"Invalid Vite manifest {field} list: {source}"
                )
            missing_sources = [item for item in sources if item not in manifest]
            if missing_sources:
                raise RuntimeError(
                    "Vite manifest references unknown entries: "
                    + ", ".join(missing_sources)
                )


def _built_url_paths(files: Iterable[Path]) -> Iterable[str]:
    for file_path in files:
        if file_path.suffix not in {".css", ".html"}:
            continue
        content = file_path.read_text(encoding="utf-8")
        for match in _BUILT_URL_PATTERN.finditer(content):
            reference = match.group(1) or match.group(2)
            if reference.startswith(_STATIC_URL_PREFIX):
                yield reference.removeprefix(_STATIC_URL_PREFIX)


def _validate_frontend_output() -> None:
    if not _MANIFEST_PATH.is_file():
        raise RuntimeError(
            "Frontend build output is missing; run "
            "`npm --prefix frontend run build` before Python packaging."
        )

    try:
        manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise RuntimeError("Vite manifest is unreadable") from error
    if not isinstance(manifest, dict):
        raise RuntimeError("Vite manifest must contain an object")

    referenced_paths = {"index.html", ".vite/manifest.json"}
    referenced_paths.update(_manifest_paths(manifest))
    existing_references = [
        _FRONTEND_OUTPUT / Path(reference) for reference in referenced_paths
    ]
    referenced_paths.update(_built_url_paths(existing_references))

    output_root = _FRONTEND_OUTPUT.resolve()
    for reference in sorted(referenced_paths):
        artifact = (_FRONTEND_OUTPUT / Path(reference)).resolve()
        try:
            artifact.relative_to(output_root)
        except ValueError as error:
            raise RuntimeError(
                f"Frontend build reference escapes the output tree: {reference}"
            ) from error
        if not artifact.is_file():
            raise RuntimeError(
                f"Frontend build artifact is missing: {reference}. "
                "Run `npm --prefix frontend run build` before Python packaging."
            )


def build_wheel(
    wheel_directory: str,
    config_settings: dict[str, Any] | None = None,
    metadata_directory: str | None = None,
) -> str:
    _validate_frontend_output()
    return cast(
        str,
        _setuptools.build_wheel(
            wheel_directory, config_settings, metadata_directory
        ),
    )


def build_editable(
    wheel_directory: str,
    config_settings: dict[str, Any] | None = None,
    metadata_directory: str | None = None,
) -> str:
    _validate_frontend_output()
    return cast(
        str,
        _setuptools.build_editable(
            wheel_directory, config_settings, metadata_directory
        ),
    )


build_sdist = _setuptools.build_sdist
get_requires_for_build_sdist = _setuptools.get_requires_for_build_sdist
get_requires_for_build_wheel = _setuptools.get_requires_for_build_wheel
prepare_metadata_for_build_wheel = _setuptools.prepare_metadata_for_build_wheel
