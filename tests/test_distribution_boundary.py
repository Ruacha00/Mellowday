import json
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path


_FORBIDDEN_IMPLEMENTATION_MARKERS = (
    "chatbot/",
    "from chatbot",
    "import chatbot",
    "onebot",
    "qq",
    "group_chat",
    "group-chat",
    "group-learning",
    "group_learning",
    "gateway",
    "plugin",
    "mcp",
    "skill.md",
)


def _copy_distribution_project(destination: Path) -> Path:
    isolated_project = destination / "project"
    isolated_project.mkdir()
    shutil.copy2("build_backend.py", isolated_project)
    shutil.copy2("pyproject.toml", isolated_project)
    shutil.copy2("README.md", isolated_project)
    shutil.copytree("src", isolated_project / "src")
    return isolated_project


def _build_wheel(project: Path, wheelhouse: Path) -> subprocess.CompletedProcess[str]:
    wheelhouse.mkdir()
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            ".",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheelhouse),
        ],
        cwd=project,
        check=False,
        capture_output=True,
        text=True,
    )


def test_distribution_builds_without_the_reference_tree(tmp_path: Path) -> None:
    isolated_project = _copy_distribution_project(tmp_path)
    wheelhouse = tmp_path / "wheelhouse"
    completed = _build_wheel(isolated_project, wheelhouse)

    assert completed.returncode == 0, completed.stderr
    wheel = next(wheelhouse.glob("mellowday-*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        packaged_files = archive.namelist()
        shipped_implementation = "\n".join(
            archive.read(name).decode("utf-8", errors="replace")
            for name in packaged_files
            if name.startswith("mellowday/")
            and name.endswith((".py", ".js", ".css", ".html", ".json"))
        )
        metadata_name = next(
            name for name in packaged_files if name.endswith(".dist-info/METADATA")
        )
        metadata = archive.read(metadata_name).decode("utf-8")

    assert "mellowday/web_app/static/index.html" in packaged_files
    replacement_root = "mellowday/web_app/static/replacement/"
    replacement_files = [
        name for name in packaged_files if name.startswith(replacement_root)
    ]
    replacement_output = (
        isolated_project
        / "src"
        / "mellowday"
        / "web_app"
        / "static"
        / "replacement"
    )
    expected_replacement_files = {
        replacement_root + path.relative_to(replacement_output).as_posix()
        for path in replacement_output.rglob("*")
        if path.is_file()
    }
    assert set(replacement_files) == expected_replacement_files
    assert f"{replacement_root}index.html" in replacement_files
    assert f"{replacement_root}.vite/manifest.json" in replacement_files
    assert any(name.endswith(".css") for name in replacement_files)
    assert any(name.endswith(".js") for name in replacement_files)
    assert any("/assets/chunks/" in name for name in replacement_files)
    assert any("/assets/fonts/" in name for name in replacement_files)
    assert f"{replacement_root}runtime/status/ready.svg" in replacement_files
    assert f"{replacement_root}runtime/licenses/inter.txt" in replacement_files
    assert all("/static/prototypes/" not in name for name in packaged_files)
    assert all(not name.startswith(("frontend/", "docs/")) for name in packaged_files)
    assert all(not name.endswith((".ts", ".tsx")) for name in packaged_files)
    assert all(not name.startswith("chatbot/") for name in packaged_files)
    lowered_implementation = shipped_implementation.casefold()
    assert all(
        marker not in lowered_implementation
        for marker in _FORBIDDEN_IMPLEMENTATION_MARKERS
    )
    requirements = [
        line.removeprefix("Requires-Dist: ").casefold()
        for line in metadata.splitlines()
        if line.startswith("Requires-Dist: ")
    ]
    assert all("chatbot" not in requirement for requirement in requirements)
    project = tomllib.loads(
        (isolated_project / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert all(
        "chatbot" not in dependency.casefold()
        for dependency in project["project"]["dependencies"]
    )


def test_distribution_rejects_a_missing_referenced_frontend_artifact(
    tmp_path: Path,
) -> None:
    isolated_project = _copy_distribution_project(tmp_path)

    output = (
        isolated_project
        / "src"
        / "mellowday"
        / "web_app"
        / "static"
        / "replacement"
    )
    manifest = json.loads(
        (output / ".vite" / "manifest.json").read_text(encoding="utf-8")
    )
    dynamic_entry = next(
        entry for entry in manifest.values() if entry.get("isDynamicEntry")
    )
    chunk_path = dynamic_entry["file"]
    (output / chunk_path).unlink()

    completed = _build_wheel(isolated_project, tmp_path / "wheelhouse")

    assert completed.returncode != 0
    assert "Frontend build artifact is missing" in (
        completed.stdout + completed.stderr
    )
