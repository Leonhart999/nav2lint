from pathlib import Path

import pytest

from nav2lint import lint_text
from nav2lint.cli import main

REFS = Path(__file__).resolve().parents[1] / "src" / "nav2lint" / "refs"


def rules_of(text, distro="auto"):
    return [f.rule for f in lint_text(text, distro).findings]


@pytest.mark.parametrize("distro", ["humble", "jazzy", "kilted", "rolling"])
def test_official_reference_has_no_errors_or_warnings(distro):
    text = (REFS / f"{distro}.yaml").read_text(encoding="utf-8")
    res = lint_text(text, distro)
    assert [f for f in res.findings if f.severity != "info"] == []


@pytest.mark.parametrize("distro,expected", [("humble", "humble"), ("jazzy", "jazzy"), ("kilted", "kilted")])
def test_guess_distro(distro, expected):
    text = (REFS / f"{distro}.yaml").read_text(encoding="utf-8")
    assert lint_text(text).distro == expected


def test_humble_config_on_jazzy_reports_migrations():
    text = (REFS / "humble.yaml").read_text(encoding="utf-8")
    rules = rules_of(text, "jazzy")
    for r in ["D201", "D202", "D203", "D204", "D209"]:
        assert r in rules


def test_jazzy_config_on_kilted():
    text = (REFS / "jazzy.yaml").read_text(encoding="utf-8")
    rules = rules_of(text, "kilted")
    assert "D205" in rules and "D206" in rules


def test_yaml_syntax_error_has_line():
    res = lint_text("amcl:\n  ros__parameters:\n    alpha1: [0.2\n", "humble")
    assert res.findings[0].rule == "N001"
    assert res.findings[0].line >= 3


def test_duplicate_key():
    text = """
controller_server:
  ros__parameters:
    FollowPath:
      plugin: "nav2_rotation_shim_controller::RotationShimController"
      plugin: "dwb_core::DWBLocalPlanner"
"""
    f = [f for f in lint_text(text, "humble").findings if f.rule == "N002"]
    assert len(f) == 1 and f[0].line == 6


def test_missing_ros_parameters_typo():
    text = "amcl:\n  ros_parameters:\n    alpha1: 0.2\n"
    f = lint_text(text, "humble").findings
    assert f[0].rule == "N003" and "ros_parameters" in f[0].hint


def test_costmap_single_nesting():
    text = "local_costmap:\n  ros__parameters:\n    resolution: 0.05\n"
    assert "N004" in rules_of(text, "humble")


def test_int_where_float_expected():
    text = """
global_costmap:
  global_costmap:
    ros__parameters:
      plugins: ["inflation_layer"]
      inflation_layer:
        plugin: "nav2_costmap_2d::InflationLayer"
        inflation_radius: 1
"""
    f = [f for f in lint_text(text, "humble").findings if f.rule == "E102"]
    assert len(f) == 1 and f[0].line == 8 and "1.0" in f[0].hint


def test_mixed_list_and_nested_footprint():
    text = """
velocity_smoother:
  ros__parameters:
    max_velocity: [0.5, 0, 2.0]
local_costmap:
  local_costmap:
    ros__parameters:
      footprint: [[0.2, 0.2], [0.2, -0.2], [-0.2, -0.2], [-0.2, 0.2]]
"""
    rules = rules_of(text, "humble")
    assert rules.count("E101") == 2


def test_footprint_string_ok_and_list_wrong():
    ok = 'local_costmap:\n  local_costmap:\n    ros__parameters:\n      footprint: "[[0.2, 0.2], [0.2, -0.2]]"\n'
    bad = "local_costmap:\n  local_costmap:\n    ros__parameters:\n      footprint: [0.2, 0.2]\n"
    assert "E102" not in rules_of(ok, "humble")
    assert "E102" in rules_of(bad, "humble")


def test_scientific_notation_is_float():
    text = """
smoother_server:
  ros__parameters:
    smoother_plugins: ["simple_smoother"]
    simple_smoother:
      plugin: "nav2_smoother::SimpleSmoother"
      tolerance: 1e-10
"""
    assert rules_of(text, "humble") == []


def test_observation_sources_must_be_string_in_costmap():
    text = """
local_costmap:
  local_costmap:
    ros__parameters:
      plugins: ["obstacle_layer"]
      obstacle_layer:
        plugin: "nav2_costmap_2d::ObstacleLayer"
        observation_sources: ["scan"]
        scan:
          topic: /scan
"""
    assert "E102" in rules_of(text, "humble")


def test_listed_plugin_not_defined_and_missing_plugin_field():
    text = """
controller_server:
  ros__parameters:
    controller_plugins: ["FollowPath", "Precise"]
    goal_checker_plugins: ["my_checker"]
    my_checker:
      xy_goal_tolerance: 0.25
"""
    rules = rules_of(text, "humble")
    assert "P101" in rules  # Precise is not defined
    assert "P102" in rules  # my_checker has no plugin
    # FollowPath is a default id and is not reported


def test_layer_defined_but_not_listed():
    text = """
global_costmap:
  global_costmap:
    ros__parameters:
      plugins: ["static_layer"]
      static_layer:
        plugin: "nav2_costmap_2d::StaticLayer"
      inflation_layer:
        plugin: "nav2_costmap_2d::InflationLayer"
"""
    f = [f for f in lint_text(text, "humble").findings if f.rule == "P103"]
    assert len(f) == 1 and "inflation_layer" in f[0].message


def test_collision_polygon_points_format():
    text = """
collision_monitor:
  ros__parameters:
    polygons: ["Stop"]
    Stop:
      type: "polygon"
      points: [0.3, 0.3, 0.3, -0.3, -0.3, -0.3, -0.3, 0.3]
"""
    assert "D210" in rules_of(text, "jazzy")
    assert "D210" not in rules_of(text, "humble")


def test_recoveries_server_renamed():
    text = "recoveries_server:\n  ros__parameters:\n    cycle_frequency: 10.0\n"
    assert "D211" in rules_of(text, "humble")


def test_raytrace_shorter_than_obstacle_range():
    text = """
local_costmap:
  local_costmap:
    ros__parameters:
      plugins: ["obstacle_layer"]
      obstacle_layer:
        plugin: "nav2_costmap_2d::ObstacleLayer"
        observation_sources: scan
        scan:
          raytrace_max_range: 2.0
          obstacle_max_range: 3.0
"""
    assert "S303" in rules_of(text, "humble")


def test_inflation_smaller_than_robot():
    text = """
local_costmap:
  local_costmap:
    ros__parameters:
      footprint: "[[0.3, 0.25], [0.3, -0.25], [-0.3, -0.25], [-0.3, 0.25]]"
      plugins: ["inflation_layer"]
      inflation_layer:
        plugin: "nav2_costmap_2d::InflationLayer"
        inflation_radius: 0.3
"""
    assert "S302" in rules_of(text, "humble")


def test_velocity_smoother_signs_and_controller_limit():
    text = """
velocity_smoother:
  ros__parameters:
    max_velocity: [0.26, 0.0, 1.0]
    min_velocity: [-0.26, 0.0, -1.0]
    max_accel: [2.5, 0.0, 3.2]
    max_decel: [2.5, 0.0, 3.2]
controller_server:
  ros__parameters:
    controller_frequency: 20.0
    FollowPath:
      plugin: "nav2_mppi_controller::MPPIController"
      model_dt: 0.1
      vx_max: 0.5
      wz_max: 1.9
"""
    rules = rules_of(text, "jazzy")
    assert "S304" in rules  # positive deceleration
    assert rules.count("S305") == 2  # both linear and angular exceed the smoother
    assert "S306" in rules  # model_dt does not match 20 Hz


def test_use_sim_time_inconsistent():
    text = """
amcl:
  ros__parameters:
    use_sim_time: True
bt_navigator:
  ros__parameters:
    use_sim_time: True
planner_server:
  ros__parameters:
    use_sim_time: False
"""
    f = [f for f in lint_text(text, "humble").findings if f.rule == "S301"]
    assert len(f) == 1 and "planner_server" in f[0].message


def test_spelling():
    text = """
controler_server:
  ros__parameters:
    controller_frequency: 20.0
global_costmap:
  global_costmap:
    ros__parameters:
      plugins: ["inflation_layer"]
      inflation_layer:
        plugin: "nav2_costmap_2d::InflationLayer"
        inflation_raduis: 0.5
        cost_scaling_factor: 3.0
"""
    rules = rules_of(text, "humble")
    assert "T401" in rules
    f = [f for f in lint_text(text, "humble").findings if f.rule == "T404"]
    assert len(f) == 1 and "inflation_radius" in f[0].hint


def test_unknown_param_from_source_tables():
    # RotationShim parameters under a DWB plugin are not declared by DWB and are ignored
    text = """
controller_server:
  ros__parameters:
    controller_plugins: ["FollowPath"]
    FollowPath:
      plugin: "dwb_core::DWBLocalPlanner"
      angular_dist_threshold: 0.785
      vx_samples: 20
"""
    f = [f for f in lint_text(text, "humble").findings if f.rule == "T404"]
    assert [x.line for x in f] == [7]


def test_unknown_param_mentions_other_distros():
    text = "bt_navigator:\n  ros__parameters:\n    filter_duration: 0.3\n"
    f = [f for f in lint_text(text, "jazzy").findings if f.rule == "T404"]
    assert len(f) == 1 and "kilted" in f[0].hint
    assert "T404" not in rules_of(text, "kilted")


def test_types_from_source_for_params_missing_in_reference():
    # desired_linear_vel is not in the official humble config; its type comes from the RPP sources
    text = """
controller_server:
  ros__parameters:
    controller_plugins: ["FollowPath"]
    FollowPath:
      plugin: "nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController"
      desired_linear_vel: 1
"""
    f = [f for f in lint_text(text, "humble").findings if f.rule == "E102"]
    assert len(f) == 1 and f[0].line == 7


def test_dwb_critic_dotted_and_nested_keys():
    text = """
controller_server:
  ros__parameters:
    controller_plugins: ["FollowPath"]
    FollowPath:
      plugin: "dwb_core::DWBLocalPlanner"
      critics: ["BaseObstacle", "PathAlign"]
      BaseObstacle.scale: 1
      PathAlign:
        forward_point_distance: 0.1
        scael: 1.0
"""
    findings = lint_text(text, "humble").findings
    assert [(f.rule, f.line) for f in findings if f.rule in ("E102", "T404")] == [("E102", 8), ("T404", 11)]


@pytest.mark.parametrize("distro", ["humble", "jazzy", "kilted", "rolling"])
def test_declared_tables_cover_core_nodes(distro):
    from nav2lint.schema import declared

    tables = declared(distro).tables
    for node in ["controller_server", "planner_server", "bt_navigator", "local_costmap", "velocity_smoother"]:
        assert "use_sim_time" in tables[f"node:{node}"]
    assert "inflation_radius" in tables["plugin:nav2_costmap_2d::InflationLayer"]


def test_spelling_ignores_valid_unlisted_params():
    # A third-party controller is not in the Nav2 tables; `min_vel_theta` is made of known words,
    # so the conservative T403 check must not report it as a typo of `max_vel_theta`.
    text = """
controller_server:
  ros__parameters:
    controller_plugins: ["FollowPath"]
    FollowPath:
      plugin: "my_pkg::MyController"
      min_vel_theta: 0.0
"""
    rules = rules_of(text, "humble")
    assert "T403" not in rules and "T404" not in rules


def test_dwb_has_no_min_vel_theta():
    # DWB declares min_speed_theta, not min_vel_theta (checked in dwb_plugins/kinematic_parameters.cpp)
    text = """
controller_server:
  ros__parameters:
    controller_plugins: ["FollowPath"]
    FollowPath:
      plugin: "dwb_core::DWBLocalPlanner"
      min_vel_theta: 0.0
      min_speed_theta: 0.0
"""
    f = [(x.rule, x.line) for x in lint_text(text, "humble").findings]
    assert f == [("T404", 7)]


def test_rotation_shim_accepts_primary_controller_params():
    text = """
velocity_smoother:
  ros__parameters:
    max_velocity: [0.26, 0.0, 1.0]
controller_server:
  ros__parameters:
    controller_plugins: ["FollowPath"]
    FollowPath:
      plugin: "nav2_rotation_shim_controller::RotationShimController"
      primary_controller: "dwb_core::DWBLocalPlanner"
      angular_dist_threshold: 0.785
      max_vel_x: 0.5
      vx_samples: 20.0
      critics: ["BaseObstacle"]
      BaseObstacle.scale: 0.02
      typo_param: 1.0
"""
    f = [(x.rule, x.line) for x in lint_text(text, "humble").findings]
    # vx_samples is a DWB int (E102); max_vel_x exceeds the smoother (S305); only typo_param is unknown (T404)
    assert sorted(f) == [("E102", 13), ("S305", 8), ("T404", 16)]


def test_node_name_typo_line_with_comment_before_ros_parameters():
    text = "controler_server:\n  # tuned for the lab robot\n  ros__parameters:\n    controller_frequency: 20.0\n"
    assert [(x.rule, x.line) for x in lint_text(text, "humble").findings] == [("T401", 1)]


def test_params_next_to_ros_parameters():
    text = (
        "amcl:\n  ros__parameters:\n  alpha1: 0.2\n"
        "planner_server:\n  ros__parameters:\n    expected_planner_frequency: 20.0\n  planner_plugins: [\"GridBased\"]\n"
        "map_saver:\n  ros__parameters:\n"
    )
    f = [(x.rule, x.severity, x.line) for x in lint_text(text, "humble").findings]
    assert f == [("N006", "error", 3), ("N006", "error", 7), ("N006", "warning", 9)]


def test_non_utf8_file_is_reported_not_crashing(tmp_path):
    from nav2lint import lint_file

    p = tmp_path / "gbk.yaml"
    p.write_bytes("amcl:\n  ros__parameters:\n    # 中文注释\n    alpha1: 0.2\n".encode("gbk"))
    f = lint_file(p).findings
    assert [(x.rule, x.line) for x in f] == [("N001", 3)] and "UTF-8" in f[0].message


def test_cli_exit_codes(tmp_path, capsys):
    good = tmp_path / "good.yaml"
    good.write_text((REFS / "humble.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    bad = tmp_path / "bad.yaml"
    bad.write_text("amcl:\n  ros_parameters:\n    alpha1: 0.2\n", encoding="utf-8")
    assert main([str(good), "--distro", "humble"]) == 0
    assert main([str(bad)]) == 1
    assert main([str(good), "--distro", "jazzy", "--format", "json"]) == 1
    assert '"rule": "D201"' in capsys.readouterr().out


def test_third_party_slash_plugin_on_jazzy_is_not_an_error():
    # STVL's Jazzy plugin XML registers `spatio_temporal_voxel_layer/SpatioTemporalVoxelLayer`.
    text = ("local_costmap:\n  local_costmap:\n    ros__parameters:\n      plugins: [stvl, inflation_layer]\n"
            "      stvl:\n        plugin: spatio_temporal_voxel_layer/SpatioTemporalVoxelLayer\n"
            "      inflation_layer:\n        plugin: nav2_costmap_2d/InflationLayer\n")
    found = [f for f in lint_text(text, "jazzy").findings if f.rule == "D201"]
    assert [(f.severity, f.line, f.fix is None) for f in found] == [("info", 6, True), ("error", 8, False)]


def test_python_loopback_simulator_parameters_are_known():
    text = "loopback_simulator:\n  ros__parameters:\n    enable_stamped_cmd_vel: true\n    publish_clock: true\n"
    for distro in ("jazzy", "kilted"):
        assert rules_of(text, distro) == []
