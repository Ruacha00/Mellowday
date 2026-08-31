import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


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
        python_sources = "\n".join(
            archive.read(name).decode("utf-8")
            for name in packaged_files
            if name.endswith(".py")
        )

    assert "mellowday/web_app/static/index.html" in packaged_files
    assert all(not name.startswith("chatbot/") for name in packaged_files)
    assert "import chatbot" not in python_sources
    assert "from chatbot" not in python_sources
