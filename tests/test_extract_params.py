"""Exercise the extractor with small, local C++ fixtures, never Nav2 downloads."""

import json
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest


ROOT = Path(__file__).resolve().parents[1]
EXTRACTOR = ROOT / "tools" / "extract_params.py"
COMMIT = "0123456789abcdef0123456789abcdef01234567"


def write(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(text).strip() + "\n", encoding="utf-8")
    return path


def package(root, name, plugins=()):
    pkg = root / name
    write(pkg, "package.xml", f'''
        <package format="3">
          <name>{name}</name>
          <version>0.0.0</version>
          <description>Local extractor test fixture.</description>
          <maintainer email="fixture@example.com">Fixture Maintainer</maintainer>
          <license>Apache-2.0</license>
        </package>
    ''')
    if plugins:
        classes = "\n".join(
            f'<class name="{key}" type="{typ}" base_class_type="{base}" />'
            for key, typ, base in plugins
        )
        write(pkg, "plugin.xml", f'<library path="fixture">{classes}</library>')
    return pkg


@pytest.fixture
def extract(tmp_path):
    source = tmp_path / "source tree"
    source.mkdir()
    cwd = tmp_path / "independent working directory"
    cwd.mkdir()
    output = tmp_path / "output" / "table.json"
    # These would fail the process if cwd or fixture imports were not isolated.
    for directory in (source, cwd):
        write(directory, "json.py", 'raise RuntimeError("untrusted import")')

    def run(*, commit=COMMIT):
        command = [sys.executable, "-I", str(EXTRACTOR), str(source), "fixture", str(output)]
        if commit is not None:
            command.extend(["--commit", commit])
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "fixture:" in result.stderr
        return json.loads(output.read_text(encoding="utf-8"))

    return source, run


def test_default_types_templates_vectors_and_unknown_names(extract):
    source, run = extract
    pkg = package(source, "fixture_node")
    write(pkg, "src/node.cpp", r'''
        #include <rclcpp/rclcpp.hpp>
        #include <string>
        #include <vector>
        class FixtureNode : public rclcpp::Node {
        public:
          FixtureNode() : rclcpp::Node("fixture_node") {
            declare_parameter("enabled", true);
            declare_parameter("retries", -3);
            declare_parameter("distance", 0.25);
            declare_parameter("timeout", 1e-3);
            declare_parameter("frame", std::string("map"));
            declare_parameter("wrapped", rclcpp::ParameterValue(false));
            declare_parameter("typed_array", rclcpp::ParameterType::PARAMETER_DOUBLE_ARRAY);
            declare_parameter<bool>("explicit_bool", false);
            declare_parameter<int64_t>("explicit_integer", 0);
            declare_parameter<double>("explicit_double", 1);
            declare_parameter<std::string>("explicit_string", "base_link");
            declare_parameter<std::vector<double>>("explicit_vector", std::vector<double>{});
            declare_parameter("integers", std::vector<int>{1, 2});
            declare_parameter("frames", std::vector<std::string>{"map", "odom"});
            declare_parameter("flags", std::vector<bool>{true, false});
            declare_parameter("unknown_default", compute_default());
            declare_parameter("unknown_type", rclcpp::ParameterValue());
            declare_parameter("merged", 1);
            declare_parameter("merged", 1.0);
            // declare_parameter("line_comment", true);
            /* declare_parameter("block_comment", false); */
          }
        };
    ''')
    data = run()
    assert data["distro"] == "fixture"
    assert data["nav2_commit"] == COMMIT
    assert data["nodes"] == {"fixture_node": {
        "enabled": ["bool"], "retries": ["int"], "distance": ["float"],
        "timeout": ["float"], "frame": ["str"], "wrapped": ["bool"],
        "typed_array": ["list[float]"], "explicit_bool": ["bool"], "explicit_integer": ["int"],
        "explicit_double": ["float"], "explicit_string": ["str"],
        "explicit_vector": ["list[float]"], "integers": ["list[int]"],
        "frames": ["list[str]"], "flags": ["list[bool]"],
        "unknown_default": [], "unknown_type": [], "merged": ["float", "int"],
    }}
    assert data["plugins"] == {}


def test_node_plugin_and_nested_group_scopes(extract):
    source, run = extract
    pkg = package(source, "fixture_controller", [
        ("fixture/Controller", "fixture::Controller", "nav2_core::Controller"),
    ])
    write(pkg, "src/controller.cpp", '''
        void Controller::configure() {
          node->declare_parameter("controller_frequency", 20.0);
          node->declare_parameter(name_ + ".speed", 0.5);
          node->declare_parameter(name_ + ".limits.acceleration", 1.5);
          node->declare_parameter(name_ + ".unknown_gain", default_gain());
        }
    ''')
    node = package(source, "fixture_server")
    write(node, "src/server.cpp", '''
        FixtureServer::FixtureServer() : LifecycleNode("fixture_server") {
          declare_parameter("enabled", true);
          declare_parameter("limits.velocity", 2.0);
        }
    ''')
    data = run()
    assert data["nodes"] == {
        "controller_server": {"controller_frequency": ["float"]},
        "fixture_server": {"enabled": ["bool"]},
    }
    assert data["plugins"] == {"fixture::Controller": {
        "plugin": ["str"], "speed": ["float"], "unknown_gain": [],
    }}
    assert data["scopes"] == {
        "node:fixture_server/limits": {"velocity": ["float"]},
        "plugin:fixture::Controller/limits": {"acceleration": ["float"]},
    }


def test_layer_api_observation_source_scope_and_node_aliases(extract):
    source, run = extract
    pkg = package(source, "fixture_costmap", [
        ("nav2_costmap_2d/ObstacleLayer", "nav2_costmap_2d::ObstacleLayer", "nav2_costmap_2d::Layer"),
    ])
    write(pkg, "src/layer.cpp", '''
        void ObstacleLayer::onInitialize() {
          declareParameter("enabled", rclcpp::ParameterValue(true));
          declareParameter(source + ".topic", rclcpp::ParameterValue("scan"));
        }
    ''')
    write(pkg, "src/costmap.cpp", '''
        Costmap::Costmap() : LifecycleNode("costmap") {
          declare_parameter("resolution", 0.05);
        }
    ''')
    data = run()
    assert data["nodes"] == {
        "local_costmap": {"resolution": ["float"]},
        "global_costmap": {"resolution": ["float"]},
    }
    assert data["plugins"] == {"nav2_costmap_2d::ObstacleLayer": {
        "plugin": ["str"], "enabled": ["bool"],
    }}
    assert data["scopes"] == {
        "plugin:nav2_costmap_2d::ObstacleLayer/observation_sources": {"topic": ["str"]},
    }


def test_separate_class_files_inheritance_and_package_helpers(extract):
    source, run = extract
    pkg = package(source, "fixture_plugins", [
        ("fixture/First", "fixture::First", "nav2_core::Controller"),
        ("fixture/Second", "fixture::Second", "nav2_core::Controller"),
        ("fixture/Derived", "fixture::Derived", "nav2_core::Controller"),
    ])
    write(pkg, "include/plugins.hpp", '''
        class Base : public nav2_core::Controller {};
        class First : public Base {};
        class Second : public nav2_core::Controller {};
        class Derived : public First {};
    ''')
    # Keep methods in separate files: attribution is file-level, not a C++ AST.
    for cls, param in [("Base", "base_gain"), ("First", "first_gain"), ("Second", "second_gain")]:
        write(pkg, f"src/{cls.lower()}.cpp", f'''
            void {cls}::configure() {{
              node->declare_parameter(name_ + ".{param}", 1.0);
            }}
        ''')
    write(pkg, "src/helper.cpp", '''
        void ParameterHelper::initialize() {
          node->declare_parameter(name_ + ".helper_gain", 2.0);
        }
    ''')
    write(pkg, "src/free_helper.cpp", '''
        void configureSharedParameters() {
          node->declare_parameter(name_ + ".shared_gain", 3.0);
        }
    ''')
    other = package(source, "unrelated_plugins", [
        ("other/Other", "other::Other", "nav2_core::GlobalPlanner"),
    ])
    write(other, "src/helper.cpp", '''
        void ParameterHelper::initialize() {
          node->declare_parameter(name_ + ".other_gain", 4.0);
        }
    ''')
    common = {"plugin": ["str"], "helper_gain": ["float"], "shared_gain": ["float"]}
    first = {**common, "base_gain": ["float"], "first_gain": ["float"]}
    assert run()["plugins"] == {
        "fixture::First": first,
        "fixture::Derived": first,
        "fixture::Second": {**common, "second_gain": ["float"]},
        "other::Other": {"plugin": ["str"], "other_gain": ["float"]},
    }


def test_test_directories_are_skipped_and_commit_defaults_to_empty(extract):
    source, run = extract
    pkg = package(source, "fixture_node")
    write(pkg, "src/node.cpp", '''
        Fixture::Fixture() : LifecycleNode("fixture_node") {
          declare_parameter("real_parameter", true);
        }
    ''')
    for directory in ("test", "tests", "nav2_system_tests", "nav2_rviz_plugins", "nav2_simple_commander"):
        ignored = package(source, directory, [
            ("ignored/Plugin", "ignored::Plugin", "nav2_core::Controller"),
        ])
        write(ignored, "fake.cpp", '''
            Fake::Fake() : LifecycleNode("ignored_node") {
              declare_parameter("ignored", true);
            }
        ''')
    data = run(commit=None)
    assert data["nav2_commit"] == ""
    assert data["nodes"] == {"fixture_node": {"real_parameter": ["bool"]}}
    assert data["plugins"] == {}
    assert data["scopes"] == {}


def test_python_node_literal_declarations(extract):
    source, run = extract
    pkg = package(source, "fixture_py_sim")
    write(pkg, "fixture_py_sim/sim.py", '''
        class Sim(Node):
            def __init__(self):
                super().__init__(node_name='fixture_sim')
                self.declare_parameter('rate', 0.01)
                self.declare_parameter('frame', "base")  # trailing comment
                self.declare_parameter('stamped', False)
                self.declare_parameter('count', 3)
                self.declare_parameter('angle_min', -math.pi)
                self.declare_parameter('weights', [0.1, 0.2])
                self.declare_parameter('opaque', compute())
    ''')
    write(pkg, "fixture_py_sim/two_nodes.py", '''
        a = Node('first')
        b = Node('second')
        self.declare_parameter('ambiguous', 1)
    ''')
    data = run()
    assert data["nodes"] == {"fixture_sim": {
        "angle_min": ["float"], "count": ["int"], "frame": ["str"], "opaque": [],
        "rate": ["float"], "stamped": ["bool"], "weights": ["list[float]"],
    }}
