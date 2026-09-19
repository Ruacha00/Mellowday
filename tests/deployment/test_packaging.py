"""Packaging contract for the browser client.

An installed (non-editable) MellowDay serves the management page straight out of
``mellowday/web_app/static``: :func:`mellowday.paths.static_dir` resolves inside
the *installed* package, so those files only exist at run time if setuptools put
them in the wheel.  Setuptools copies them solely because
``[tool.setuptools.package-data]`` declares ``web_app/static/*``; when that
declaration is missing the failure is silent and confusing - ``/api/health``
answers 200 while ``/`` answers "static assets not installed" (or 404), which is
exactly what a container deployment hits.

These assertions are deliberately static: no wheel is built, nothing is
downloaded, and no Docker daemon is needed, so this runs in the offline suite.
``tests/deployment`` is the home for deployment-shape checks like this one.
"""
from __future__ import annotations

import fnmatch
import tomllib
from pathlib import Path

from mellowday import paths

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"

# The files index.html pulls in by name; losing any one of them leaves a page
# that loads and then does nothing.
EXPECTED_ASSETS = ("index.html", "app.js", "styles.css")

STATIC_GLOB = "web_app/static/*"


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))


def _package_data() -> dict[str, list[str]]:
    data = _pyproject().get("tool", {}).get("setuptools", {}).get("package-data")
    assert data, (
        "pyproject.toml has no [tool.setuptools.package-data] section; the browser "
        "client would be dropped from the wheel and an installed deployment would "
        "serve no interface at all."
    )
    return {package: list(patterns) for package, patterns in data.items()}


def test_package_data_declares_the_browser_client():
    """The wheel needs an explicit declaration: .js/.css/.html are not packages."""
    declared = [pattern for patterns in _package_data().values() for pattern in patterns]
    assert STATIC_GLOB in declared, (
        f"[tool.setuptools.package-data] must declare {STATIC_GLOB!r} for the "
        f"mellowday package, found: {declared!r}"
    )
    assert STATIC_GLOB in _package_data().get("mellowday", []), (
        "the static assets live under src/mellowday/web_app/static, so the pattern "
        "belongs to the 'mellowday' package entry"
    )


def test_declared_pattern_matches_every_shipped_asset():
    """A pattern that does not actually cover the files is as bad as no pattern."""
    patterns = _package_data().get("mellowday", [])
    for name in EXPECTED_ASSETS:
        relative = f"web_app/static/{name}"
        assert any(fnmatch.fnmatch(relative, pattern) for pattern in patterns), (
            f"{relative} is not matched by any pattern in package-data: {patterns!r}"
        )


def test_static_assets_exist_in_the_source_tree():
    """The files the pattern promises must be there before any build can copy them."""
    static = paths.static_dir()
    missing = [name for name in EXPECTED_ASSETS if not (static / name).is_file()]
    assert not missing, f"missing static assets in {static}: {missing}"


def test_static_dir_resolves_inside_the_package():
    """static_dir() is what the web app mounts, so it must be the packaged directory.

    A path outside the package (for example a repository-relative one) would work
    from a source checkout and 404 from an installed deployment.
    """
    package_dir = paths.package_dir()
    static = paths.static_dir()
    assert static == package_dir / "web_app" / "static"
    assert static.is_relative_to(package_dir)


def test_index_page_carries_the_application_name():
    """Cheap end-to-end anchor: the page mounted at / is MellowDay's own page."""
    html = (paths.static_dir() / "index.html").read_text(encoding="utf-8")
    assert "MellowDay" in html
