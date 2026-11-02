"""Build an sdist and wheel, then exercise only the installed wheel's resources."""

import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import venv
import zipfile
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
DISTROS = ("humble", "jazzy", "kilted", "rolling")
RESOURCES = tuple(
    f"nav2lint/{directory}/{distro}.{suffix}"
    for directory, suffix in (("refs", "yaml"), ("data", "json"))
    for distro in DISTROS
)


def run(command, cwd):
    env = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME"):
        env.pop(key, None)
    temp = cwd.parent / "temp"
    temp.mkdir(exist_ok=True)
    env.update({
        "TEMP": str(temp), "TMP": str(temp), "TMPDIR": str(temp),
        "PIP_CACHE_DIR": str(cwd.parent / "pip-cache"),
        "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PYTHONUTF8": "1",
    })
    result = subprocess.run(
        [str(part) for part in command], cwd=cwd, env=env,
        capture_output=True, text=True, encoding="utf-8", timeout=180,
    )
    assert result.returncode == 0, (
        f"Command failed: {command}\n{result.stdout}\n{result.stderr}"
    )
    return result.stdout


@pytest.fixture(scope="module")
def installed_wheel(tmp_path_factory):
    work = tmp_path_factory.mktemp("wheel smoke")
    source = work / "source"
    shutil.copytree(
        ROOT, source,
        ignore=shutil.ignore_patterns(
            ".git", ".venv", ".pytest_cache", "__pycache__", "*.egg-info", "build", "dist",
        ),
    )
    outside = work / "outside source"
    outside.mkdir()
    dist = work / "dist"
    # The default build creates the wheel from the newly built sdist. Build
    # dependencies are installed by CI; no backend writes into the real checkout.
    run([sys.executable, "-I", "-m", "build", "--no-isolation", "--outdir", dist, source], outside)
    wheels = list(dist.glob("*.whl"))
    sdists = list(dist.glob("*.tar.gz"))
    assert len(wheels) == len(sdists) == 1
    wheel = wheels[0]
    with zipfile.ZipFile(wheel) as archive:
        for name in RESOURCES:
            assert archive.read(name) == (ROOT / "src" / name).read_bytes(), name
        metadata_names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        assert len(metadata_names) == 1
        metadata = archive.read(metadata_names[0]).decode("utf-8")
        version_match = re.search(r"^Version: (.+)$", metadata, re.MULTILINE)
        assert version_match is not None
        version = version_match.group(1).strip()
    with tarfile.open(sdists[0]) as archive:
        members = {member.name.split("/", 1)[-1]: member for member in archive.getmembers()}
        for name in RESOURCES:
            member = members[f"src/{name}"]
            with archive.extractfile(member) as resource:
                assert resource.read() == (ROOT / "src" / name).read_bytes(), name

    environment = work / "venv"
    venv.EnvBuilder(with_pip=True).create(environment)
    scripts = environment / ("Scripts" if os.name == "nt" else "bin")
    python = scripts / ("python.exe" if os.name == "nt" else "python")
    cli = scripts / ("nav2lint.exe" if os.name == "nt" else "nav2lint")
    # Install into a clean environment, not the editable checkout. PyYAML is the
    # only runtime dependency; any downloads and caches remain under basetemp.
    run([python, "-I", "-m", "pip", "install", wheel], outside)
    return {
        "python": python, "cli": cli, "cwd": outside,
        "environment": environment, "version": version,
    }


def test_pre_commit_hook_contract():
    hooks = yaml.safe_load((ROOT / ".pre-commit-hooks.yaml").read_text(encoding="utf-8"))
    assert len(hooks) == 1
    hook = hooks[0]
    assert hook["id"] == hook["entry"] == "nav2lint"
    assert hook["language"] == "python"
    assert hook["types"] == ["file"]
    assert hook["pass_filenames"] is False
    assert hook["args"] == ["."]
    assert not hook.get("always_run", False)
    include = re.compile(hook["files"])
    exclude = re.compile(hook["exclude"])
    for name in ("nav2.yaml", "config/nav2.yml", "map.yaml"):
        assert include.search(name) and not exclude.search(name)
    for name in ("nav2.yaml.bak", "yaml.txt", "nav2.xml", "config/notyaml"):
        assert not include.search(name)
    for name in (".nav2lint.yaml", ".nav2lint.yml", "config/.nav2lint.yaml", "config/.nav2lint.yml"):
        assert exclude.search(name)
    assert not exclude.search("config/custom.nav2lint.yaml")


def test_pre_commit_directory_discovery_skips_map_yaml(installed_wheel, tmp_path):
    install = installed_wheel
    repository = tmp_path / "consumer"
    repository.mkdir()
    # A map is a valid YAML file but not a ROS parameter document. Passing it as
    # an explicit filename would incorrectly produce a lint finding.
    (repository / "map.yaml").write_text("image: map.pgm\nresolution: 0.05\n", encoding="utf-8")
    (repository / ".nav2lint.yaml").write_text("distro: humble\n", encoding="utf-8")
    navigation = repository / "navigation.yaml"
    navigation.write_text("amcl:\n  ros__parameters:\n    max_particles: 2000\n", encoding="utf-8")
    hook = yaml.safe_load((ROOT / ".pre-commit-hooks.yaml").read_text(encoding="utf-8"))[0]
    output = run([install["cli"], *hook["args"], "--format", "json"], repository)
    results = json.loads(output)
    assert len(results) == 1
    assert Path(results[0]["path"]).name == navigation.name
    assert results[0]["distro"] == "humble"
    assert navigation.read_text(encoding="utf-8") == "amcl:\n  ros__parameters:\n    max_particles: 2000\n"


def test_installed_wheel_version_and_resource_location(installed_wheel):
    install = installed_wheel
    output = run([install["cli"], "--version"], install["cwd"])
    assert output.strip() == f"nav2lint {install['version']}"
    location = run(
        [install["python"], "-I", "-c", "import nav2lint; print(nav2lint.__file__)"],
        install["cwd"],
    )
    assert install["environment"].resolve() in Path(location.strip()).resolve().parents
    assert ROOT.resolve() not in install["cwd"].resolve().parents


def test_installed_wheel_queries_and_initialization(installed_wheel):
    install = installed_wheel
    rule = json.loads(run([install["cli"], "--explain", "T404", "--format", "json"], install["cwd"]))
    assert rule["rule"] == "T404" and "not proof" in rule["action"]
    info = json.loads(run([install["cli"], "--describe", "amcl.alpha1", "--distro", "humble", "--format", "json"], install["cwd"]))
    assert info["status"] == "known" and info["types"] == ["float"]
    workspace = install["cwd"] / "consumer workspace"
    result = json.loads(run([install["cli"], "--init-vscode", workspace, "--format", "json"], install["cwd"]))
    target = workspace / ".vscode" / "tasks.json"
    assert Path(result["tasks_file"]) == target
    tasks = json.loads(target.read_text(encoding="utf-8"))["tasks"]
    for task in tasks:
        assert Path(task["command"]).resolve() == install["python"].resolve()
        assert "runOptions" not in task


@pytest.mark.parametrize("distro", DISTROS)
def test_installed_wheel_lints_bundled_reference(installed_wheel, distro):
    install = installed_wheel
    reference = install["cwd"] / f"{distro}.yaml"
    # Export via the installed package, never read a reference from the checkout.
    script = """
import json
import sys
from importlib import resources
from pathlib import Path
from nav2lint.schema import declared, reference

distro, destination = sys.argv[1:]
package = resources.files("nav2lint")
data = json.loads(package.joinpath("data").joinpath(distro + ".json").read_text(encoding="utf-8"))
assert data["distro"] == distro
assert data["nodes"] and data["plugins"] and data["nav2_commit"]
assert declared(distro).tables and reference(distro).nodes
text = package.joinpath("refs").joinpath(distro + ".yaml").read_text(encoding="utf-8")
Path(destination).write_text(text, encoding="utf-8")
"""
    run(
        [install["python"], "-I", "-c", script, distro, reference],
        install["cwd"],
    )
    output = run(
        [install["cli"], "--no-config", "--strict", "--distro", distro, "--format", "json", reference],
        install["cwd"],
    )
    results = json.loads(output)
    assert len(results) == 1
    assert results[0]["distro"] == distro
    assert Path(results[0]["path"]) == reference
    assert not [finding for finding in results[0]["findings"] if finding["severity"] != "info"]
