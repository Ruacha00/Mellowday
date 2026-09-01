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


def test_distribution_builds_without_the_reference_tree(tmp_path: Path) -> None:
    isolated_project = tmp_path / "project"
    isolated_project.mkdir()
    shutil.copy2("pyproject.toml", isolated_project)
    shutil.copy2("README.md", isolated_project)
    shutil.copytree("src", isolated_project / "src")
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()

    completed = subprocess.run(
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
        cwd=isolated_project,
        check=False,
        capture_output=True,
        text=True,
    )

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
