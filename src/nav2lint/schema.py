"""Walk the structure of a Nav2 params file and load the known parameters of each scope.

Known parameters come from the tables extracted from the Nav2 sources (data/*.json) and from
the types used in the official nav2_params.yaml of each distro (refs/*.yaml).

A Nav2 params file has two kinds of nested mappings:
- plugin instances: named by a list parameter (plugins, controller_plugins, ...) or carrying a `plugin` field;
- plain groups: e.g. MPPI's TrajectoryVisualizer or docking_server's controller.
Every scope gets a schema key; scopes of the same kind (same plugin type, same node) share one parameter table.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources

from .loader import Node, load

DISTROS = ["humble", "jazzy", "kilted", "rolling"]

# Parameters whose value is a list of child scope names.
REGISTRY_KEYS = {
    "plugins",
    "filters",
    "controller_plugins",
    "planner_plugins",
    "smoother_plugins",
    "behavior_plugins",
    "goal_checker_plugins",
    "progress_checker_plugins",
    "progress_checker_plugin",
    "waypoint_task_executor_plugin",
    "navigators",
    "dock_plugins",
    "docks",
    "polygons",
    "observation_sources",
    "operations",
    "edge_cost_functions",
    "critics",
}
# Lists whose named children must define a `plugin` field.
PLUGIN_REGISTRIES = REGISTRY_KEYS - {"polygons", "observation_sources", "critics", "docks"}


def normalize_plugin(name: str) -> str:
    """Humble uses pkg/Class, Jazzy+ uses pkg::Class; normalize to :: so tables are shared across distros."""
    return name.replace("/", "::")


def registry_names(node: Node) -> list[str]:
    if node.kind == "scalar" and isinstance(node.value, str):
        # costmap observation_sources is a space-separated string
        return node.value.split()
    if node.kind == "seq":
        return [str(n.value) for n in node.value if n.kind == "scalar"]
    return []


@dataclass
class Scope:
    node: str  # node name, e.g. controller_server
    path: str  # dotted path inside the node params, "" at top level
    schema: str  # parameter table key
    params: Node  # mapping node
    registered_by: str | None = None  # name of the list parameter that names this scope
    plugin: str | None = None  # raw `plugin` string
    line: int = 1  # line of the scope's key
    children: list["Scope"] = field(default_factory=list)
    primary: str | None = None  # RotationShim: the wrapped controller (primary_controller)
    extra_schema: str | None = None  # RotationShim: the shim's own parameter table

    def full(self, key: str) -> str:
        return f"{self.path}.{key}" if self.path else key


@dataclass
class NodeSection:
    name: str  # node name (the key right above ros__parameters)
    yaml_path: list[str]  # key path from the root to the key above ros__parameters
    params: Node  # the ros__parameters mapping
    line: int  # line of the ros__parameters key
    root: Scope
    key_line: int = 1  # line of the node name key


def find_nodes(root: Node | None) -> list[NodeSection]:
    out: list[NodeSection] = []

    def rec(n: Node, path: list[str], key_line: int) -> None:
        if n.kind != "map":
            return
        rp = n.get("ros__parameters")
        if rp is not None and path:
            if rp.kind == "map":
                name = path[-1]
                line = n.key_lines["ros__parameters"]
                out.append(NodeSection(name, path, rp, line, build_scopes(name, rp, line), key_line))
            return
        for k, v in n.value.items():
            rec(v, path + [k], n.key_lines[k])

    if root is not None:
        rec(root, [], 1)
    return out


def build_scopes(node_name: str, params: Node, line: int = 1) -> Scope:
    root = Scope(node_name, "", f"node:{node_name}", params, line=line)
    _fill(root)
    return root


def _fill(scope: Scope) -> None:
    named: dict[str, str] = {}
    for k, v in scope.params.value.items():
        if k in REGISTRY_KEYS:
            for name in registry_names(v):
                named.setdefault(name, k)
    for k, v in scope.params.value.items():
        if v.kind != "map":
            continue
        plugin_node = v.get("plugin")
        plugin = plugin_node.value if plugin_node is not None and plugin_node.kind == "scalar" else None
        reg = named.get(k)
        primary = None
        if isinstance(plugin, str) and normalize_plugin(plugin).endswith("RotationShimController"):
            # The shim forwards its namespace to the wrapped controller, so the scope holds both sets of params.
            prim = v.get("primary_controller")
            if prim is not None and prim.kind == "scalar" and isinstance(prim.value, str):
                primary = prim.value
        if primary:
            schema = f"plugin:{normalize_plugin(primary)}"
        elif isinstance(plugin, str):
            schema = f"plugin:{normalize_plugin(plugin)}"
        elif reg is not None and not (reg == "critics" and scope.schema.endswith("DWBLocalPlanner")):
            schema = f"{scope.schema}/{reg}"
        else:
            # plain groups, and DWB critics, which each have their own parameters
            schema = f"{scope.schema}/{k}"
        child = Scope(
            scope.node, scope.full(k), schema, v, reg, plugin if isinstance(plugin, str) else None, scope.params.key_lines[k]
        )
        if primary:
            child.primary = primary
            child.extra_schema = f"plugin:{normalize_plugin(plugin)}"
        _fill(child)
        scope.children.append(child)


def walk(scope: Scope):
    yield scope
    for c in scope.children:
        yield from walk(c)


def ros_type(n: Node) -> str:
    """Map a YAML value to a ROS 2 parameter type name."""
    if n.kind == "map":
        return "map"
    if n.kind == "seq":
        if not n.value:
            return "list"
        if any(e.kind != "scalar" for e in n.value):
            return "nested"
        ts = {ros_type(e) for e in n.value}
        return f"list[{ts.pop()}]" if len(ts) == 1 else "mixed"
    v = n.value
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if v is None:
        return "null"
    return "str"


def is_placeholder(n: Node) -> bool:
    """Launch-time placeholders (KEEPOUT_ZONE_ENABLED in the kilted reference) or $(...) substitutions."""
    if n.kind != "scalar" or not isinstance(n.value, str):
        return False
    v = n.value
    return (v.isupper() and "_" in v) or "$(" in v


@dataclass
class Reference:
    # types[schema][param] = {type names}
    types: dict[str, dict[str, set[str]]]
    nodes: set[str]
    plugins: set[str]  # normalized plugin types


def _learn(text: str) -> Reference:
    root, _ = load(text)
    types: dict[str, dict[str, set[str]]] = {}
    nodes: set[str] = set()
    plugins: set[str] = set()
    for sec in find_nodes(root):
        nodes.add(sec.name)
        for sc in walk(sec.root):
            if sc.plugin:
                plugins.add(normalize_plugin(sc.plugin))
            table = types.setdefault(sc.schema, {})
            for k, v in sc.params.value.items():
                if v.kind == "map" or is_placeholder(v):
                    continue
                table.setdefault(k, set()).add(ros_type(v))
    return Reference(types, nodes, plugins)


@lru_cache(maxsize=None)
def reference(distro: str) -> Reference:
    text = resources.files("nav2lint").joinpath("refs", f"{distro}.yaml").read_text(encoding="utf-8")
    return _learn(text)


# Parameters every rclcpp node accepts.
RCLCPP_PARAMS = {"use_sim_time": {"bool"}, "start_type_description_service": {"bool"}}


@dataclass
class Declared:
    """Parameters declared in the Nav2 C++ sources (generated by tools/extract_params.py)."""

    tables: dict[str, dict[str, set[str]]]  # schema -> param -> types (empty set: type unknown)
    commit: str


@lru_cache(maxsize=None)
def source_data(distro: str) -> dict:
    """Read the bundled snapshot without importing or executing external code."""
    if distro not in DISTROS:
        raise ValueError(f"Unsupported distro: {distro}")
    return json.loads(resources.files("nav2lint").joinpath("data", f"{distro}.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def declared(distro: str) -> Declared:
    raw = source_data(distro)
    common = {k: set(v) for k, v in raw["global"].items()} | RCLCPP_PARAMS
    tables: dict[str, dict[str, set[str]]] = {}
    for name, params in raw["nodes"].items():
        tables[f"node:{name}"] = {**{k: set(v) for k, v in common.items()}, **{k: set(v) for k, v in params.items()}}
    for name, params in raw["plugins"].items():
        tables[f"plugin:{name}"] = {k: set(v) for k, v in params.items()}
    for name, params in raw["scopes"].items():
        tables.setdefault(name, {}).update({k: set(v) for k, v in params.items()})
    return Declared(tables, raw.get("nav2_commit", ""))


def parameter_info(distro: str, schema: str, key: str) -> dict:
    """Describe available evidence; no bundled scope is claimed to be complete."""
    raw = source_data(distro)
    source = declared(distro).tables.get(schema)
    ref = reference(distro).types.get(schema)
    sources = []
    if source is not None and key in source:
        types = sorted(source[key])
        if schema.startswith("node:") and key in RCLCPP_PARAMS:
            kind = "built_in_convention"
            types = sorted(RCLCPP_PARAMS[key])
        else:
            kind = "source_table"
            # Global lifecycle declarations are merged into each extracted node.
            if schema.startswith("node:") and key in raw["global"]:
                kind = "source_table_global"
        entry = {"kind": kind, "types": types}
        if kind != "built_in_convention":
            entry.update({"nav2_commit": raw.get("nav2_commit", ""), "artifact": f"data/{distro}.json"})
        sources.append(entry)
    if ref is not None and key in ref:
        sources.append({"kind": "reference_yaml", "types": sorted(ref[key]), "artifact": f"refs/{distro}.yaml"})
    types = sorted({t for source in sources for t in source["types"]})
    known_scope = source is not None or ref is not None
    # A source-only empty type list is distinct from a parameter absent from the tables.
    return {
        "distro": distro, "schema": schema, "parameter": key,
        "status": "known" if sources else "not_in_tables" if known_scope else "unknown_scope",
        "types": types, "type_known": bool(types), "scope_complete": False,
        "sources": sources,
        "other_distros": [d for d in DISTROS if d != distro and
                           (key in declared(d).tables.get(schema, {}) or key in reference(d).types.get(schema, {}))],
        "limitation": "Bundled tables are static approximations. Absence does not prove that Nav2 ignores a parameter.",
    }


@lru_cache(maxsize=None)
def declared_union() -> dict[str, dict[str, set[str]]]:
    out: dict[str, dict[str, set[str]]] = {}
    for d in DISTROS:
        for sch, table in declared(d).tables.items():
            dst = out.setdefault(sch, {})
            for k, ts in table.items():
                dst.setdefault(k, set()).update(ts)
    return out


@lru_cache(maxsize=None)
def nav2_nodes() -> frozenset[str]:
    """Node names that Nav2 itself runs (from the source tables and the official configs)."""
    names = {sch[len("node:") :].split("/")[0] for sch in declared_union() if sch.startswith("node:")}
    for d in DISTROS:
        names |= reference(d).nodes
    return frozenset(names)


@lru_cache(maxsize=None)
def nav2_plugin_packages() -> frozenset[str]:
    """Packages whose plugins Nav2 itself ships (from the source tables and the official configs)."""
    names = {sch[len("plugin:") :].split("::")[0] for sch in declared_union() if sch.startswith("plugin:")}
    names |= {p.split("::")[0] for p in union_reference().plugins}
    return frozenset(names)


def distros_declaring(schema: str, key: str) -> list[str]:
    return [d for d in DISTROS if key in declared(d).tables.get(schema, {})]


@lru_cache(maxsize=None)
def union_reference() -> Reference:
    types: dict[str, dict[str, set[str]]] = {}
    nodes: set[str] = set()
    plugins: set[str] = set()
    for d in DISTROS:
        r = reference(d)
        nodes |= r.nodes
        plugins |= r.plugins
        for sch, table in r.types.items():
            dst = types.setdefault(sch, {})
            for k, ts in table.items():
                dst.setdefault(k, set()).update(ts)
    return Reference(types, nodes | EXTRA_NODES, plugins | {normalize_plugin(p) for p in EXTRA_PLUGINS})


# Common nodes and plugins missing from the official reference files; used only for spell checking.
EXTRA_NODES = {
    "slam_toolbox",
    "lifecycle_manager",
    "lifecycle_manager_navigation",
    "lifecycle_manager_localization",
    "robot_state_publisher",
    "bt_navigator_navigate_to_pose_rclcpp_node",
    "bt_navigator_navigate_through_poses_rclcpp_node",
    "costmap_filter_info_server",
    "filter_mask_server",
    # Foxy/Galactic-era node names that still show up in Humble configs
    "global_costmap_client",
    "local_costmap_client",
    "global_costmap_rclcpp_node",
    "local_costmap_rclcpp_node",
    "recoveries_server",
}
EXTRA_PLUGINS = {
    "nav2_smac_planner::SmacPlannerHybrid",
    "nav2_smac_planner::SmacPlanner2D",
    "nav2_smac_planner::SmacPlannerLattice",
    "nav2_theta_star_planner::ThetaStarPlanner",
    "nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController",
    "nav2_rotation_shim_controller::RotationShimController",
    "nav2_graceful_controller::GracefulController",
    "nav2_controller::StoppedGoalChecker",
    "nav2_controller::PoseProgressChecker",
    "nav2_costmap_2d::DenoiseLayer",
    "nav2_costmap_2d::RangeSensorLayer",
    "nav2_costmap_2d::BinaryFilter",
    "nav2_smoother::SavitzkyGolaySmoother",
    "nav2_constrained_smoother::ConstrainedSmoother",
    "nav2_waypoint_follower::PhotoAtWaypoint",
    "nav2_waypoint_follower::InputAtWaypoint",
    "opennav_docking::SimpleNonChargingDock",
}
