"""Extract the parameter declarations of a Nav2 source tree into a JSON table.

Usage:
    python tools/extract_params.py SRC_DIR DISTRO OUT_JSON [--commit SHA]

The output lists, per node and per plugin type, every parameter that Nav2 declares
together with the ROS 2 type implied by its default value. nav2lint ships these tables
so that users do not need the Nav2 sources.

Attribution rules:
- A name made only of string literals, declared in a node's own package, belongs to that node.
  Literal names declared inside a plugin belong to the node that hosts the plugin.
- A name built from a prefix variable (`name_ + ".x"`) belongs to the plugin class whose
  methods are defined in that file, to subclasses of that class, and, for helper files that
  define no plugin, to every plugin of the package.
- `declareParameter` (costmap layers) prefixes the layer name itself, so a literal name there is
  layer-level and `source + "." + "x"` is a sub-scope (observation source) parameter.
- MPPI `getParam(var, "x", default)` is scoped by the getter it was obtained from.
- Python nodes (the Jazzy/Kilted loopback simulator): literal `self.declare_parameter("x", default)`
  calls belong to the node named in `super().__init__(node_name=...)` or `Node(...)`.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

CALLS = (
    "declare_parameter_if_not_declared",
    "declare_parameter",
    "declareParameter",
    "getParam",
    "declare_or_get_parameter",
    "add_parameter",
    "searchAndGetParam",
)
CALL_RE = re.compile(r"\b(" + "|".join(CALLS) + r")\s*(<(?:[^<>;()]|<[^<>;()]*>)*>)?\s*\(")
STRING_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
IDENT_RE = re.compile(r"[A-Za-z_]\w*")
PY_NODE_RE = re.compile(r"""(?:super\(\)\.__init__|\bNode)\s*\(\s*(?:node_name\s*=\s*)?['"](\w+)['"]""")
PY_DECLARE_RE = re.compile(r"""\bself\.declare_parameter\(\s*['"]([\w.]+)['"]\s*(?:,\s*(.*?))?\)\s*(?:#.*)?$""", re.M)
NOT_VARS = {"std", "string", "rclcpp", "ParameterValue", "c_str", "nav2_util", "nav2"}

# Which node hosts plugins of a given base class.
HOSTS = {
    "nav2_core::Controller": ["controller_server"],
    "nav2_core::GoalChecker": ["controller_server"],
    "nav2_core::ProgressChecker": ["controller_server"],
    "nav2_core::GlobalPlanner": ["planner_server"],
    "nav2_core::Smoother": ["smoother_server"],
    "nav2_core::Behavior": ["behavior_server"],
    "nav2_core::WaypointTaskExecutor": ["waypoint_follower"],
    "nav2_costmap_2d::Layer": ["local_costmap", "global_costmap"],
    "nav2_costmap_2d::CostmapFilter": ["local_costmap", "global_costmap"],
}
# Nodes whose name is passed in at runtime.
NODE_ALIASES = {"costmap": ["local_costmap", "global_costmap"]}
# Packages that contribute plugin-level parameters to another package's plugins.
PACKAGE_EXTRAS = {"dwb_core": ["dwb_plugins"]}
# Packages whose literal declarations belong to another node.
PACKAGE_NODE = {"nav2_behavior_tree": ["bt_navigator"]}
# Classes (or their ancestors) whose prefixed parameters form a named child scope of a node.
CLASS_SCOPES = {
    "Polygon": ["node:collision_monitor/polygons", "node:collision_detector/polygons"],
    "Source": ["node:collision_monitor/observation_sources", "node:collision_detector/observation_sources"],
}
# Packages whose literal declarations apply to every node (lifecycle node base classes).
GLOBAL_PACKAGES = {"nav2_util", "nav2_ros_common"}


def strip_comments(src: str) -> str:
    out = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == '"':
            j = i + 1
            while j < n and src[j] != '"':
                j += 2 if src[j] == "\\" else 1
            out.append(src[i : j + 1])
            i = j + 1
        elif src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            out.append("\n" * src.count("\n", i, n if j < 0 else j))
            i = n if j < 0 else j + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def call_args(src: str, start: int) -> tuple[list[str], int] | None:
    """Split the arguments of the call whose '(' is at src[start-1]. Returns (args, end)."""
    depth, i, cur, args = 0, start, [], []
    while i < len(src):
        c = src[i]
        if c == '"':
            j = i + 1
            while j < len(src) and src[j] != '"':
                j += 2 if src[j] == "\\" else 1
            cur.append(src[i : j + 1])
            i = j + 1
            continue
        if c in "({[":
            depth += 1
        elif c in ")}]":
            if depth == 0:
                args.append("".join(cur).strip())
                return args, i
            depth -= 1
        elif c == "," and depth == 0:
            args.append("".join(cur).strip())
            cur = []
            i += 1
            continue
        cur.append(c)
        i += 1
    return None


def infer_type(expr: str, template: str | None = None) -> str | None:
    """ROS 2 parameter type implied by a default value expression."""
    if template:
        tpl = template[1:-1].strip()
        m = re.fullmatch(r"std::vector\s*<\s*([\w:]+)\s*>", tpl)
        if m:
            t = infer_type_name(m.group(1))
            return f"list[{t}]" if t else None
        return infer_type_name(tpl)
    e = expr.strip()
    m = re.fullmatch(r"rclcpp::ParameterValue\s*\((.*)\)", e, re.S)
    if m:
        return infer_type(m.group(1))
    m = re.search(r"PARAMETER_(BOOL|INTEGER|DOUBLE|STRING)(_ARRAY)?\b", e)
    if m:
        base = {"BOOL": "bool", "INTEGER": "int", "DOUBLE": "float", "STRING": "str"}[m.group(1)]
        return f"list[{base}]" if m.group(2) else base
    if e in ("true", "false"):
        return "bool"
    if re.fullmatch(r'(std::string\s*[({]\s*)?"(?:[^"\\]|\\.)*"\s*[)}]?', e):
        return "str"
    m = re.match(r"std::vector\s*<\s*([\w:]+)\s*>", e)
    if m:
        t = infer_type_name(m.group(1))
        return f"list[{t}]" if t else None
    m = re.match(r"static_cast\s*<\s*([\w:]+)\s*>", e)
    if m:
        return infer_type_name(m.group(1))
    if re.fullmatch(r"-?\d+[uUlL]*", e):
        return "int"
    if re.fullmatch(r"-?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?[fF]?", e) or e in ("M_PI", "-M_PI"):
        return "float"
    if re.fullmatch(r"[-+*/ ().\d]+", e) and "." in e:
        return "float"
    return None


def infer_type_name(name: str) -> str | None:
    name = name.split("::")[-1]
    if name == "bool":
        return "bool"
    if name in ("int", "int64_t", "int32_t", "unsigned", "size_t", "long", "uint64_t", "uint32_t", "int16_t"):
        return "int"
    if name in ("double", "float"):
        return "float"
    if name == "string":
        return "str"
    return None


def infer_py_type(expr: str) -> str | None:
    """ROS 2 parameter type implied by a Python default value."""
    e = expr.strip()
    if e in ("True", "False"):
        return "bool"
    if re.fullmatch(r"""(['"]).*\1""", e):
        return "str"
    if re.fullmatch(r"-?\d+", e):
        return "int"
    if re.fullmatch(r"-?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?", e) or e in ("math.pi", "-math.pi"):
        return "float"
    m = re.fullmatch(r"\[(.+)\]", e)
    if m:
        types = {infer_py_type(x) for x in m.group(1).split(",") if x.strip()}
        return f"list[{types.pop()}]" if len(types) == 1 and None not in types else None
    return None


def classify_name(expr: str) -> tuple[str, list[str]]:
    """Return (relative name from literals, identifiers used in the name expression)."""
    lits = STRING_RE.findall(expr)
    no_str = STRING_RE.sub(" ", expr)
    idents = [i for i in IDENT_RE.findall(no_str) if i not in NOT_VARS]
    return "".join(lits), idents


class Table:
    def __init__(self) -> None:
        self.params: dict[str, set[str]] = defaultdict(set)

    def add(self, name: str, typ: str | None) -> None:
        if not name or not re.fullmatch(r"[\w.]+", name):
            return
        self.params[name]  # register the name even when the type is unknown
        if typ:
            self.params[name].add(typ)


def package_of(path: Path, roots: list[Path]) -> Path:
    best = None
    for r in roots:
        if r in path.parents and (best is None or len(r.parts) > len(best.parts)):
            best = r
    return best or path.parent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("distro")
    ap.add_argument("out", type=Path)
    ap.add_argument("--commit", default="")
    args = ap.parse_args(argv)
    src: Path = args.src.resolve()

    roots = sorted({p.parent for p in src.rglob("package.xml")})

    def skip(p: Path) -> bool:
        parts = {x.lower() for x in p.relative_to(src).parts}
        return bool(parts & {"test", "tests", "nav2_system_tests", "nav2_rviz_plugins", "nav2_simple_commander"})

    # plugin XMLs: plugin key -> (type, base, package)
    plugins: dict[str, dict] = {}
    for xml in src.rglob("*.xml"):
        if skip(xml):
            continue
        text = xml.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"<class\b([^>]*)>", text):
            attrs = dict(re.findall(r'(\w+)\s*=\s*"([^"]*)"', m.group(1)))
            typ = attrs.get("type")
            if not typ:
                continue
            key = (attrs.get("name") or typ).replace("/", "::")
            typ = re.sub(r"(&lt;|<).*", "", typ)
            plugins[key] = {"type": typ, "base": attrs.get("base_class_type", ""), "pkg": package_of(xml, roots)}

    files = [p for p in src.rglob("*") if p.suffix in (".cpp", ".hpp", ".h") and not skip(p)]
    texts = {p: strip_comments(p.read_text(encoding="utf-8", errors="ignore")) for p in files}

    # class -> bases (unqualified names)
    bases: dict[str, set[str]] = defaultdict(set)
    for t in texts.values():
        for m in re.finditer(r"\bclass\s+(\w+)\s*(?:final\s*)?:\s*([^{;]+)\{", t):
            for b in re.findall(r"(?:public|protected|private)\s+([\w:]+)", m.group(2)):
                bases[m.group(1)].add(b.split("::")[-1])

    def ancestors(cls: str) -> set[str]:
        seen, todo = set(), [cls]
        while todo:
            c = todo.pop()
            for b in bases.get(c, ()):
                if b not in seen:
                    seen.add(b)
                    todo.append(b)
        return seen

    # file -> classes whose methods it defines
    file_classes: dict[Path, set[str]] = {}
    for p, t in texts.items():
        file_classes[p] = set(re.findall(r"\b(\w+)::\1\s*\(", t)) | set(
            re.findall(r"\b(\w+)::(?:onInitialize|configure|initialize|on_configure|activate|setup|getParameters|declareParameters)\s*\(", t)
        )

    # file -> node names it constructs
    file_nodes: dict[Path, list[str]] = {}
    for p, t in texts.items():
        names = re.findall(r'(?:LifecycleNode|rclcpp::Node)\s*\(\s*"(\w+)"', t)
        out = []
        for n in names:
            out.extend(NODE_ALIASES.get(n, [n]))
        if out:
            file_nodes[p] = out

    plugin_classes = {info["type"].split("::")[-1]: key for key, info in plugins.items()}
    nodes: dict[str, Table] = defaultdict(Table)
    global_params = Table()
    plugin_tables: dict[str, Table] = defaultdict(Table)
    sub_tables: dict[str, Table] = defaultdict(Table)  # "<plugin>/*" child scopes
    group_tables: dict[str, Table] = defaultdict(Table)  # "<schema>/<group>" nested groups

    # Per-class declarations (plugin-relative), keyed by (class, package) because helper
    # class names such as ParameterHandler repeat across packages.
    class_params: dict[tuple, Table] = defaultdict(Table)
    class_subs: dict[tuple, Table] = defaultdict(Table)
    helper_params: dict[Path, Table] = defaultdict(Table)  # package -> params from helper files
    helper_subs: dict[Path, Table] = defaultdict(Table)
    pkg_literals: dict[Path, Table] = defaultdict(Table)  # package -> literal names in plugin files
    mppi_critics = Table()
    mppi_groups: dict[str, Table] = defaultdict(Table)

    for p, t in texts.items():
        pkg = package_of(p, roots)
        pkg_name = pkg.name
        classes = file_classes[p]
        own_nodes = file_nodes.get(p)
        is_mppi = pkg_name == "nav2_mppi_controller"
        getters: dict[str, str] = {}
        if is_mppi:
            for m in re.finditer(r"auto\s+(\w+)\s*=\s*[\w>.\-]*getParamGetter\s*\(([^;]*)\)\s*;", t):
                lits, idents = classify_name(m.group(2))
                if ("critics" in p.parts or p.name == "critic_function.hpp") and "parent_name_" not in idents:
                    getters[m.group(1)] = "critic"
                elif lits.strip("."):
                    getters[m.group(1)] = "group:" + lits.strip(".")
                elif not idents:
                    getters[m.group(1)] = "node"
                else:
                    getters[m.group(1)] = "plugin"

        for m in CALL_RE.finditer(t):
            fn, template = m.group(1), m.group(2)
            res = call_args(t, m.end())
            if not res:
                continue
            a = res[0]
            # figure out (name_expr, default_expr) per API
            if fn in ("declare_parameter_if_not_declared", "searchAndGetParam"):
                if len(a) < 2:
                    continue
                name_expr, default = a[1], a[2] if len(a) > 2 else ""
            elif fn == "getParam":
                # MPPI: `auto getParam = handler->getParamGetter(ns); getParam(var, "x", default);`
                scope = getters.get("getParam")
                if not is_mppi or len(a) < 3 or scope is None:
                    continue
                lits, _ = classify_name(a[1])
                typ = infer_type(a[2])
                if scope == "critic":
                    mppi_critics.add(lits, typ)
                elif scope.startswith("group:"):
                    mppi_groups[scope[6:]].add(lits, typ)
                elif scope == "plugin":
                    helper_params[pkg].add(lits, typ)
                continue
            elif fn == "declare_or_get_parameter":
                if len(a) == 3 and not STRING_RE.search(a[0]) and STRING_RE.search(a[1]):
                    name_expr, default = a[1], a[2]
                elif len(a) >= 1:
                    name_expr, default = a[0], a[1] if len(a) > 1 else ""
                else:
                    continue
            else:  # declare_parameter / declareParameter / add_parameter
                if not a or not a[0]:
                    continue
                name_expr, default = a[0], a[1] if len(a) > 1 else ""

            lits, idents = classify_name(name_expr)
            typ = infer_type(default, template)
            rel = lits.lstrip(".")
            if not rel:
                continue

            if fn == "declareParameter":  # costmap Layer API, prefixed by the layer name
                target_cls = classes or {None}
                for c in target_cls:
                    tbl = (class_subs[(c, pkg)] if c else helper_subs[pkg]) if idents else (class_params[(c, pkg)] if c else helper_params[pkg])
                    tbl.add(rel, typ)
                continue

            if not idents:  # literal name: node-level
                if own_nodes:
                    for n in own_nodes:
                        nodes[n].add(rel, typ)
                elif pkg_name in GLOBAL_PACKAGES:
                    global_params.add(rel, typ)
                elif pkg_name in PACKAGE_NODE:
                    for n in PACKAGE_NODE[pkg_name]:
                        nodes[n].add(rel, typ)
                else:
                    pkg_literals[pkg].add(rel, typ)
                continue

            sub = len(idents) > 1 and not lits.startswith(".") and lits.count(".") >= 1 and not name_expr.lstrip().startswith(("name", "plugin_name", "dwb_plugin_name", "parent_name"))
            if len(idents) >= 2 and re.search(r"\+\s*[A-Za-z_]\w*\s*\+", name_expr):
                sub = True  # prefix + sub_name + ".x"
            if own_nodes:
                # node file with a variable prefix, e.g. navigator / polygon names
                for n in own_nodes:
                    sub_tables[f"node:{n}/*"].add(rel, typ)
                continue
            targets = classes or {None}
            for c in targets:
                if sub:
                    (class_subs[(c, pkg)] if c else helper_subs[pkg]).add(rel, typ)
                else:
                    (class_params[(c, pkg)] if c else helper_params[pkg]).add(rel, typ)

    for p in src.rglob("*.py"):
        if skip(p):
            continue
        t = p.read_text(encoding="utf-8", errors="ignore")
        py_nodes = PY_NODE_RE.findall(t)
        if len(set(py_nodes)) != 1:
            continue  # no node, or several nodes in one file: attribution would be a guess
        for m in PY_DECLARE_RE.finditer(t):
            nodes[py_nodes[0]].add(m.group(1), infer_py_type(m.group(2) or ""))

    def merge(dst: Table, src_t: Table) -> None:
        for k, ts in src_t.params.items():
            dst.params[k] |= ts

    class_keys = set(class_params) | set(class_subs)
    by_name: dict[str, list[tuple]] = defaultdict(list)
    for ck in class_keys:
        by_name[ck[0]].append(ck)

    def scoped_by(cls: str) -> list[str]:
        return [sc for anchor, scs in CLASS_SCOPES.items() if cls == anchor or anchor in ancestors(cls) for sc in scs]

    for ck in class_keys:
        for sc in scoped_by(ck[0]):
            merge(sub_tables[sc], class_params.get(ck, Table()))
            merge(sub_tables[sc], class_subs.get(ck, Table()))

    # Classes outside every plugin hierarchy are helpers (kinematics, iterators, ...) of their package.
    in_hierarchy = set(plugin_classes)
    for c in plugin_classes:
        in_hierarchy |= ancestors(c)
    for ck in class_keys:
        if ck[0] not in in_hierarchy and not scoped_by(ck[0]):
            merge(helper_params[ck[1]], class_params.get(ck, Table()))
            merge(helper_subs[ck[1]], class_subs.get(ck, Table()))

    # Resolve plugins
    by_pkg: dict[Path, list[str]] = defaultdict(list)
    for key, info in plugins.items():
        by_pkg[info["pkg"]].append(key)

    for key, info in plugins.items():
        cls = info["type"].split("::")[-1]
        tbl = plugin_tables[key]
        tbl.add("plugin", "str")
        for c in {cls} | ancestors(cls):
            for ck in by_name.get(c, []):
                merge(tbl, class_params.get(ck, Table()))
                merge(sub_tables[f"plugin:{key}/*"], class_subs.get(ck, Table()))
        pkgs = [info["pkg"]] + [r for r in roots if r.name in PACKAGE_EXTRAS.get(info["pkg"].name, [])]
        for pk in pkgs:
            merge(tbl, helper_params.get(pk, Table()))
            merge(sub_tables[f"plugin:{key}/*"], helper_subs.get(pk, Table()))
        hosts = HOSTS.get(info["base"], [])
        for h in hosts:
            merge(nodes[h], pkg_literals.get(info["pkg"], Table()))

    # Packages that both host a node and plugins (docking, route, collision monitor): literals go to the node.
    for p, ns in file_nodes.items():
        pk = package_of(p, roots)
        for n in ns:
            merge(nodes[n], pkg_literals.get(pk, Table()))

    mppi_key = next((k for k in plugins if k.endswith("MPPIController")), None)
    if mppi_key:
        merge(sub_tables[f"plugin:{mppi_key}/critics"], mppi_critics)
        for g, tbl in mppi_groups.items():
            merge(group_tables[f"plugin:{mppi_key}/{g}"], tbl)

    # Rename child scopes to the schema keys nav2lint builds from YAML.
    for key in list(sub_tables):
        if not key.endswith("/*"):
            continue
        plugin = key[len("plugin:") : -2] if key.startswith("plugin:") else None
        tbl = sub_tables.pop(key)
        if plugin and plugin.startswith("nav2_costmap_2d::") and plugin.endswith(("ObstacleLayer", "VoxelLayer")):
            sub_tables[f"plugin:{plugin}/observation_sources"] = tbl
        elif plugin and plugin.startswith("dwb_critics::"):
            # "scale" etc. come from the TrajectoryCritic base class header in dwb_core
            name = plugin.split("::")[-1].removesuffix("Critic")
            dwb = next((k for k in plugins if k.endswith("DWBLocalPlanner")), None)
            if dwb:
                merge(tbl, helper_subs.get(plugins[dwb]["pkg"], Table()))
                sub_tables[f"plugin:{dwb}/{name}"] = tbl
        elif key.startswith("node:"):
            # prefixed names in a node's own files: polygons, sources, navigators, docks ...
            node_prefix = key[:-1]
            for other in [k for k in sub_tables if k.startswith(node_prefix)]:
                merge(sub_tables[other], tbl)
    # DWB reads trajectory generator and kinematics parameters in its own namespace.
    dwb = next((k for k in plugins if k.endswith("DWBLocalPlanner")), None)
    if dwb:
        for k in plugins:
            if k.startswith("dwb_plugins::"):
                merge(plugin_tables[dwb], plugin_tables[k])
    # Dotted names are nested groups: "controller.k_phi" in docking_server -> scope node:docking_server/controller.
    for kind, tbls in (("node", nodes), ("plugin", plugin_tables)):
        for name, tbl in tbls.items():
            for param in [p for p in tbl.params if "." in p]:
                group, leaf = param.rsplit(".", 1)
                merge_one = group_tables[f"{kind}:{name}/" + group.replace(".", "/")]
                merge_one.params[leaf] |= tbl.params.pop(param)

    def dump(tbls: dict[str, Table]) -> dict:
        return {k: {p: sorted(ts) for p, ts in sorted(v.params.items())} for k, v in sorted(tbls.items()) if v.params}

    out = {
        "distro": args.distro,
        "nav2_commit": args.commit,
        "global": {p: sorted(ts) for p, ts in sorted(global_params.params.items())},
        "nodes": dump(nodes),
        "plugins": dump(plugin_tables),
        "scopes": dump({**sub_tables, **group_tables}),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    n_params = sum(len(v) for v in out["nodes"].values()) + sum(len(v) for v in out["plugins"].values())
    print(f"{args.distro}: {len(out['nodes'])} nodes, {len(out['plugins'])} plugins, {n_params} params -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
