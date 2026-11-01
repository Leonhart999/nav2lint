import json
import re
import subprocess
import sys
import time
from pathlib import Path

from nav2lint.cli import collect, main

ROOT = Path(__file__).resolve().parents[1]
REFS = ROOT / "src" / "nav2lint" / "refs"
BROKEN = ROOT / "examples" / "broken_humble.yaml"


def _matcher_regex() -> re.Pattern:
    text = (ROOT / "editors" / "vscode" / "tasks.json").read_text(encoding="utf-8")
    text = "\n".join(line for line in text.splitlines() if not line.strip().startswith("//"))
    tasks = json.loads(text)["tasks"]
    patterns = {t["problemMatcher"]["pattern"]["regexp"] for t in tasks}
    assert len(patterns) == 1
    return re.compile(patterns.pop())


def test_line_format_matches_vscode_problem_matcher(capsys):
    main([str(BROKEN), "--format", "line", "--distro", "humble"])
    lines = capsys.readouterr().out.splitlines()
    rx = _matcher_regex()
    matched = [rx.match(line) for line in lines]
    assert lines and all(matched), [l for l, m in zip(lines, matched) if not m]
    # Windows drive letters contain a colon; the file group must still be the whole path
    assert all(Path(m.group(1)) == BROKEN for m in matched)
    first = matched[0]
    assert first.group(3) in ("error", "warning", "info") and re.fullmatch(r"[A-Z]\d{3}", first.group(4))


def test_line_format_puts_hint_inline(capsys):
    main([str(BROKEN), "--format", "line", "--distro", "humble"])
    out = capsys.readouterr().out
    assert "inflation_radius` should be float but is int; Nav2 will fail with a parameter type mismatch -- write 1.0" in out


def test_collect_finds_only_nav2_files(tmp_path):
    (tmp_path / "nav").mkdir()
    (tmp_path / "nav" / "nav2.yaml").write_text((REFS / "humble.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "slam.yaml").write_text("slam_toolbox:\n  ros__parameters:\n    resolution: 0.05\n", encoding="utf-8")
    (tmp_path / "map.yaml").write_text("image: map.pgm\nresolution: 0.05\n", encoding="utf-8")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "copy.yaml").write_text((REFS / "humble.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    assert collect([str(tmp_path)]) == [tmp_path / "nav" / "nav2.yaml"]
    # an explicit file is always linted
    assert collect([str(tmp_path / "map.yaml")]) == [tmp_path / "map.yaml"]


def test_watch_relints_on_change(tmp_path):
    f = tmp_path / "nav2.yaml"
    f.write_text("amcl:\n  ros__parameters:\n    max_particles: 2000\n", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "nav2lint", "--watch", "--interval", "0.1", "--format", "line", "--distro", "humble", str(tmp_path)],
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    try:
        out = []

        def read_round():
            while True:
                line = proc.stdout.readline()
                assert line, "watch process exited"
                out.append(line)
                if line.startswith("nav2lint: done"):
                    return

        read_round()
        assert not any("[E102]" in l for l in out)
        time.sleep(0.2)
        f.write_text("amcl:\n  ros__parameters:\n    max_particles: 2000.0\n", encoding="utf-8")
        out.clear()
        read_round()
        assert out[0].startswith("nav2lint: checking 1 file")
        assert any("[E102]" in l for l in out)
    finally:
        proc.kill()
        proc.wait()
