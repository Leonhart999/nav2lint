from pathlib import Path

import pytest

from nav2lint import fix_text, lint_text
from nav2lint.cli import main
from nav2lint.config import ConfigError, find_config, load_config

REFS = Path(__file__).resolve().parents[1] / "src" / "nav2lint" / "refs"


def rules_of(text, distro=None, config=None):
    return [f.rule for f in lint_text(text, distro, config=config).findings]


# ---------- --fix ----------

def test_fix_types_keeps_comments_and_layout():
    text = """velocity_smoother:
  ros__parameters:
    max_velocity: [0.26, 0, 1]   # m/s
    max_decel: [2.5, 0.0, 3.2]
global_costmap:
  global_costmap:
    ros__parameters:
      footprint: [[0.2, 0.2], [0.2, -0.2]]
      plugins: ["inflation_layer"]
      inflation_layer:
        plugin: "nav2_costmap_2d::InflationLayer"
        inflation_radius: 1  # keep me
"""
    new, n, res = fix_text(text, "humble")
    assert n == 4
    assert "max_velocity: [0.26, 0.0, 1.0]   # m/s" in new
    assert "max_decel: [-2.5, 0.0, -3.2]" in new
    assert 'footprint: "[[0.2, 0.2], [0.2, -0.2]]"' in new
    assert "inflation_radius: 1.0  # keep me" in new
    assert [f for f in res.findings if f.severity == "error"] == []


def test_fix_float_to_int():
    new, n, _ = fix_text("amcl:\n  ros__parameters:\n    max_particles: 2000.0\n", "humble")
    assert n == 1 and "max_particles: 2000\n" in new


def test_fix_does_not_touch_scientific_notation():
    text = "velocity_smoother:\n  ros__parameters:\n    max_velocity: [1e-3, 0, 2.0]\n"
    new, _, _ = fix_text(text, "humble")
    assert "max_velocity: [1e-3, 0.0, 2.0]" in new


def test_fix_migrates_humble_reference_to_jazzy():
    text = (REFS / "humble.yaml").read_text(encoding="utf-8")
    new, n, res = fix_text(text, "jazzy")
    assert n >= 10
    assert "plugin_lib_names" not in new
    assert 'progress_checker_plugins: ["progress_checker"]' in new
    assert "nav2_behaviors::Spin" in new and "nav2_behaviors/Spin" not in new
    assert "local_frame: odom" in new and "global_frame: map" in new
    assert [f for f in res.findings if f.severity != "info"] == []


def test_fix_jazzy_back_to_humble_progress_checker():
    text = 'controller_server:\n  ros__parameters:\n    progress_checker_plugins: ["progress_checker"]\n'
    new, n, _ = fix_text(text, "humble")
    assert n == 1 and 'progress_checker_plugin: "progress_checker"' in new


def test_fix_collision_points_both_ways():
    flat = 'collision_monitor:\n  ros__parameters:\n    polygons: ["Stop"]\n    Stop:\n      type: "polygon"\n      points: [0.3, 0.3, 0.3, -0.3]\n'
    new, n, _ = fix_text(flat, "jazzy")
    assert n == 1 and 'points: "[[0.3, 0.3], [0.3, -0.3]]"' in new
    back, n, _ = fix_text(new, "humble")
    assert n == 1 and "points: [0.3, 0.3, 0.3, -0.3]" in back


def test_fix_ros_parameters_typo():
    new, n, res = fix_text("amcl:\n  ros_parameters:\n    alpha1: 0.2\n", "humble")
    assert n == 1 and "  ros__parameters:\n" in new and res.findings == []


def test_fix_keeps_crlf():
    text = "amcl:\r\n  ros__parameters:\r\n    max_particles: 2000.0\r\n"
    new, n, _ = fix_text(text, "humble")
    assert n == 1 and new == "amcl:\r\n  ros__parameters:\r\n    max_particles: 2000\r\n"


def test_unsafe_findings_are_not_fixed():
    # a typo suggestion may be wrong, so T404 has no automatic fix
    text = "amcl:\n  ros__parameters:\n    max_particle: 2000\n"
    new, n, res = fix_text(text, "humble")
    assert n == 0 and new == text and "T404" in [f.rule for f in res.findings]


def test_cli_fix_and_diff(tmp_path, capsys):
    f = tmp_path / "p.yaml"
    f.write_text("amcl:\n  ros__parameters:\n    max_particles: 2000.0\n", encoding="utf-8")
    assert main([str(f), "--distro", "humble", "--diff"]) == 0
    out = capsys.readouterr().out
    assert "-    max_particles: 2000.0" in out and "+    max_particles: 2000" in out
    assert "2000.0" in f.read_text(encoding="utf-8")  # --diff does not write
    assert main([str(f), "--distro", "humble", "--fix"]) == 0
    assert "max_particles: 2000\n" in f.read_text(encoding="utf-8")


# ---------- inline suppression ----------

SIM = """amcl:
  ros__parameters:
    use_sim_time: True
bt_navigator:
  ros__parameters:
    use_sim_time: True
planner_server:
  ros__parameters:
    use_sim_time: False{comment}
"""


def test_disable_same_line():
    assert "S301" in rules_of(SIM.format(comment=""), "humble")
    res = lint_text(SIM.format(comment="  # nav2lint: disable=S301"), "humble")
    assert res.findings == [] and res.suppressed == 1


def test_disable_other_rule_does_not_hide():
    assert "S301" in rules_of(SIM.format(comment="  # nav2lint: disable=T404"), "humble")


def test_disable_next_line_and_file():
    text = "amcl:\n  ros__parameters:\n    # nav2lint: disable-next-line=T404\n    max_particle: 2000\n    min_particle: 10\n"
    assert rules_of(text, "humble") == ["T404"]  # only the second one
    text = "# nav2lint: disable-file=T404\n" + text
    assert rules_of(text, "humble") == []


def test_disable_all_and_free_text_after_ids():
    assert rules_of(SIM.format(comment="  # nav2lint: disable"), "humble") == []
    assert rules_of(SIM.format(comment="  # nav2lint: disable=S301 launch sets use_sim_time"), "humble") == []


def test_unknown_rule_in_comment():
    f = lint_text(SIM.format(comment="  # nav2lint: disable=S399"), "humble").findings
    assert [x.rule for x in f] == ["N005", "S301"]


def test_suppressed_findings_are_not_fixed():
    text = "amcl:\n  ros__parameters:\n    max_particles: 2000.0  # nav2lint: disable=E102\n"
    new, n, _ = fix_text(text, "humble")
    assert n == 0 and new == text


# ---------- .nav2lint.yaml ----------

def test_config_found_upwards_and_applied(tmp_path):
    (tmp_path / ".nav2lint.yaml").write_text("distro: jazzy\ndisable: [S301]\nseverity:\n  P103: warning\n", encoding="utf-8")
    sub = tmp_path / "pkg" / "config"
    sub.mkdir(parents=True)
    f = sub / "nav2.yaml"
    f.write_text((REFS / "humble.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    cfg = find_config(f)
    assert cfg is not None and cfg.distro == "jazzy"
    res = lint_text(f.read_text(encoding="utf-8"), None, str(f), cfg)
    assert res.distro == "jazzy"  # config distro used instead of auto-detection
    assert "D201" in [x.rule for x in res.findings]
    assert any(x.rule == "P103" and x.severity == "warning" for x in res.findings)
    # --distro still wins over the config
    assert lint_text(f.read_text(encoding="utf-8"), "humble", str(f), cfg).distro == "humble"


def test_config_disable(tmp_path):
    p = tmp_path / ".nav2lint.yaml"
    p.write_text("disable: S301\n", encoding="utf-8")
    res = lint_text(SIM.format(comment=""), "humble", config=load_config(p))
    assert res.findings == [] and res.suppressed == 1


@pytest.mark.parametrize(
    "content,msg",
    [
        ("distro: foxy\n", "distro must be"),
        ("disable: [X123]\n", "unknown rule"),
        ("severity: {S301: fatal}\n", "error, warning or info"),
        ("rules: []\n", "unknown key"),
    ],
)
def test_config_errors(tmp_path, content, msg):
    p = tmp_path / ".nav2lint.yaml"
    p.write_text(content, encoding="utf-8")
    with pytest.raises(ConfigError, match=msg):
        load_config(p)


def test_cli_config_error_exit_code(tmp_path, capsys):
    (tmp_path / ".nav2lint.yaml").write_text("distro: foxy\n", encoding="utf-8")
    f = tmp_path / "nav2.yaml"
    f.write_text("amcl:\n  ros__parameters:\n    alpha1: 0.2\n", encoding="utf-8")
    assert main([str(f)]) == 2
    assert "config error" in capsys.readouterr().err
    assert main([str(f), "--no-config"]) == 0


def test_cli_fix_leaves_non_utf8_file_alone(tmp_path, capsys):
    f = tmp_path / "gbk.yaml"
    data = "# 中文注释\namcl:\n  ros__parameters:\n    max_particles: 2000.0\n".encode("gbk")
    f.write_bytes(data)
    assert main([str(f), "--distro", "humble", "--fix"]) == 1
    assert f.read_bytes() == data
    assert "N001" in capsys.readouterr().out
