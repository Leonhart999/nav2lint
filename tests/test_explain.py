import json

import pytest

from nav2lint import lint_text
from nav2lint.cli import main
from nav2lint.explain import describe_parameter, explain_rule
from nav2lint.rules import RULE_IDS
from nav2lint.schema import DISTROS, declared, parameter_info, reference


@pytest.mark.parametrize("rule", sorted(RULE_IDS))
def test_every_rule_has_guidance(rule):
    info = explain_rule(rule.lower())
    assert info["rule"] == rule
    assert all(info[k] for k in ("title", "check", "action", "automatic_fix"))


def test_rule_query_has_no_path_requirement(capsys):
    assert main(["--explain", "t404"]) == 0
    out = capsys.readouterr().out
    assert "T404" in out and "not proof" in out and "No automatic fix" in out
    assert main(["--explain", "N999"]) == 2
    assert "Unknown rule" in capsys.readouterr().err


@pytest.mark.parametrize("distro", DISTROS)
def test_parameter_query_has_source_snapshot(distro):
    info = describe_parameter("controller_server.controller_frequency", distro)
    assert info["status"] == "known"
    assert info["types"] == ["float"] and info["type_known"]
    assert not info["scope_complete"]
    source = next(s for s in info["sources"] if s["kind"] == "source_table")
    assert source["nav2_commit"] == declared(distro).commit
    assert source["artifact"] == f"data/{distro}.json"
    assert any(s["kind"] == "reference_yaml" for s in info["sources"])


def test_builtin_convention_is_not_claimed_as_extracted_source():
    info = describe_parameter("amcl.use_sim_time", "humble")
    builtin = next(s for s in info["sources"] if s["kind"] == "built_in_convention")
    assert builtin["types"] == ["bool"]
    assert "nav2_commit" not in builtin


def test_plugin_group_and_node_group_queries():
    assert describe_parameter("plugin:nav2_costmap_2d::InflationLayer.inflation_radius", "humble")["types"] == ["float"]
    info = describe_parameter("plugin:dwb_core::DWBLocalPlanner/PathAlign.scale", "humble")
    assert info["schema"].endswith("/PathAlign") and info["status"] == "known"
    info = describe_parameter("amcl.initial_pose.x", "humble")
    assert info["schema"] == "node:amcl/initial_pose" and info["status"] == "known"


def test_absent_parameters_are_not_runtime_claims():
    info = describe_parameter("amcl.not_a_parameter", "humble")
    assert info["status"] == "not_in_tables" and not info["sources"]
    assert not info["type_known"] and not info["scope_complete"]
    assert "does not prove" in info["limitation"]
    assert describe_parameter("my_node.speed", "humble")["status"] == "unknown_scope"


def test_unknown_type_is_distinct_from_unknown_parameter():
    for schema, params in declared("humble").tables.items():
        for key, types in params.items():
            if not types and not reference("humble").types.get(schema, {}).get(key):
                info = parameter_info("humble", schema, key)
                assert info["status"] == "known" and not info["type_known"]
                assert info["sources"] and info["types"] == []
                return
    pytest.fail("Expected at least one extracted parameter with unknown type")


def test_other_distro_evidence():
    info = describe_parameter("bt_navigator.filter_duration", "jazzy")
    assert info["status"] == "not_in_tables" and "kilted" in info["other_distros"]


@pytest.mark.parametrize("target", ["", "amcl", ".x", "amcl.", "amcl..x", "plugin:Foo.x", "plugin:pkg::Foo/.x"])
def test_bad_queries_are_rejected(target):
    with pytest.raises(ValueError):
        describe_parameter(target, "humble")


@pytest.mark.parametrize("distro", [None, "auto", "unknown"])
def test_queries_require_explicit_distro(distro):
    with pytest.raises(ValueError):
        describe_parameter("amcl.alpha1", distro)


@pytest.mark.parametrize("args", [["--explain", ""], ["--describe", "", "--distro", "humble"]])
def test_empty_query_returns_controlled_error(args, capsys):
    assert main(args) == 2
    assert "nav2lint:" in capsys.readouterr().err


def test_query_json_and_exit_codes(capsys):
    assert main(["--describe", "amcl.alpha1", "--distro", "humble", "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["schema"] == "node:amcl" and data["parameter"] == "alpha1"
    assert main(["--describe", "amcl.alpha1"]) == 2
    assert "explicit" in capsys.readouterr().err
    assert main(["--explain", "E102", "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["rule"] == "E102"


@pytest.mark.parametrize("args", [[], ["--explain", "T404", "file.yaml"], ["--explain", "T404", "--fix"],
                                   ["--python", "python3", "file.yaml"], ["--explain", "T404", "--format", "line"]])
def test_invalid_mode_combinations(args):
    with pytest.raises(SystemExit) as err:
        main(args)
    assert err.value.code == 2


def test_diagnostic_evidence_and_cautious_unknown_wording(tmp_path, capsys):
    path = tmp_path / "nav2.yaml"
    path.write_text("amcl:\n  ros__parameters:\n    alpha1: 1\n    alpha_typo: 0.2\n", encoding="utf-8")
    assert main([str(path), "--distro", "humble", "--format", "json"]) == 1
    findings = json.loads(capsys.readouterr().out)[0]["findings"]
    typed = next(f for f in findings if f["rule"] == "E102")
    unknown = next(f for f in findings if f["rule"] == "T404")
    assert typed["evidence"][0]["parameter"] == "alpha1"
    assert typed["evidence"][0]["sources"]
    assert unknown["evidence"][0]["status"] == "not_in_tables"
    assert "ignored" not in unknown["message"] and "incomplete" in unknown["hint"]


def test_initialization_cli(tmp_path, capsys):
    workspace = tmp_path / "workspace"
    assert main(["--init-vscode", str(workspace), "--python", "python3", "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    tasks_file = workspace / ".vscode" / "tasks.json"
    assert data["tasks_file"] == str(tasks_file)
    assert all(t["command"] == "python3" for t in json.loads(tasks_file.read_text())["tasks"])
    original = tasks_file.read_bytes()
    assert main(["--init-vscode", str(workspace)]) == 0
    assert tasks_file.read_bytes() == original
    tasks_file.write_text("{broken", encoding="utf-8")
    assert main(["--init-vscode", str(workspace)]) == 2
    assert tasks_file.read_text() == "{broken"
    assert "Cannot safely initialize" in capsys.readouterr().err


def test_initialization_defaults_to_current_directory(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["--init-vscode"]) == 0
    assert (tmp_path / ".vscode" / "tasks.json").is_file()
    assert "New tasks start manually" in capsys.readouterr().out


def test_wrapped_controller_evidence_names_both_schemas():
    text = ('controller_server:\n  ros__parameters:\n    FollowPath:\n'
            '      plugin: nav2_rotation_shim_controller::RotationShimController\n'
            '      primary_controller: dwb_core::DWBLocalPlanner\n'
            '      vx_samples: 20.0\n')
    finding = next(f for f in lint_text(text, "humble").findings if f.rule == "E102")
    assert {e["schema"] for e in finding.evidence} == {
        "plugin:dwb_core::DWBLocalPlanner", "plugin:nav2_rotation_shim_controller::RotationShimController"}
