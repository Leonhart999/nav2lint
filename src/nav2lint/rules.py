"""Lint rules. Each check takes a Context and appends Findings.

Rule ID prefixes:
  N0xx file structure       E1xx parameter types      P1xx plugin lists
  D2xx distro migration     S3xx cross-param sanity   T4xx spelling
"""
from __future__ import annotations

import ast
import difflib
import math
import re
from dataclasses import dataclass, field

from .loader import Duplicate, Node
from .schema import (
    DISTROS,
    PLUGIN_REGISTRIES,
    NodeSection,
    Reference,
    Scope,
    declared,
    declared_union,
    is_placeholder,
    nav2_plugin_packages,
    normalize_plugin,
    parameter_info,
    reference,
    registry_names,
    ros_type,
    union_reference,
    walk,
)

ERROR, WARNING, INFO = "error", "warning", "info"
SEVERITIES = (ERROR, WARNING, INFO)

RULE_IDS = frozenset(
    ["N001", "N002", "N003", "N004", "N005", "N006", "E101", "E102", "P101", "P102", "P103"]
    + [f"D2{i:02d}" for i in range(1, 12)]
    + [f"S30{i}" for i in range(1, 8)]
    + ["T401", "T402", "T403", "T404"]
)

# A fix replaces whole source lines: [(line_number, replacement_lines)]; an empty list deletes the line.
Fix = list[tuple[int, list[str]]]


@dataclass
class Finding:
    rule: str
    severity: str
    line: int
    message: str
    hint: str = ""
    fix: Fix | None = None
    evidence: list[dict] = field(default_factory=list)


@dataclass
class Context:
    root: Node | None
    dups: list[Duplicate]
    sections: list[NodeSection]
    distro: str | None  # None means unknown; D2xx rules are skipped
    lines: list[str] = field(default_factory=list)  # source lines without line endings
    findings: list[Finding] = field(default_factory=list)

    def add(self, rule: str, severity: str, line: int, message: str, hint: str = "", fix: Fix | None = None,
            evidence: list[dict] | None = None) -> None:
        self.findings.append(Finding(rule, severity, line, message, hint, fix, evidence or []))

    def at_least(self, distro: str) -> bool:
        return self.distro is not None and DISTROS.index(self.distro) >= DISTROS.index(distro)

    def section(self, name: str) -> NodeSection | None:
        for s in self.sections:
            if s.name == name:
                return s
        return None


# ---------- helpers ----------

def num(n: Node | None) -> float | None:
    if n is None or n.kind != "scalar" or isinstance(n.value, bool):
        return None
    return float(n.value) if isinstance(n.value, (int, float)) else None


def num_list(n: Node | None) -> list[float] | None:
    if n is None or n.kind != "seq":
        return None
    vals = [num(e) for e in n.value]
    return None if any(v is None for v in vals) else vals  # type: ignore[return-value]


def key_line(scope: Scope, key: str) -> int:
    return scope.params.key_lines.get(key, scope.params.line)


def plugin_is(scope: Scope, *suffixes: str) -> bool:
    """True if the scope's plugin, or the controller a RotationShim wraps, ends with one of `suffixes`."""
    return any(p is not None and normalize_plugin(p).endswith(suffixes) for p in (scope.plugin, scope.primary))


def all_scopes(ctx: Context):
    for sec in ctx.sections:
        yield from walk(sec.root)


def close(word: str, candidates, cutoff: float = 0.8) -> str | None:
    m = difflib.get_close_matches(word, list(candidates), n=1, cutoff=cutoff)
    return m[0] if m and m[0] != word else None


def fmt_types(ts: set[str]) -> str:
    return " / ".join(sorted(ts))


# ---------- fix helpers (line-based, so comments and layout survive) ----------

_NUM = r"(?<![\w.+-])([-+]?)(\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)(?![\w.])"


def _src(ctx: Context, line: int) -> str | None:
    return ctx.lines[line - 1] if 1 <= line <= len(ctx.lines) else None


def fix_sub(ctx: Context, line: int, pattern: str, repl) -> Fix | None:
    old = _src(ctx, line)
    if old is None:
        return None
    new, n = re.subn(pattern, repl, old, count=1)
    return [(line, [new])] if n and new != old else None


def fix_value(ctx: Context, line: int, key: str, transform) -> Fix | None:
    """Rewrite the inline value of `key:` on `line` with transform(value_text)."""
    old = _src(ctx, line)
    if old is None:
        return None
    m = re.match(rf"^(\s*(?:-\s+)?[\"']?{re.escape(key)}[\"']?\s*:\s*)(.*?)(\s*(?:#.*)?)$", old)
    if not m or not m.group(2):
        return None
    new_val = transform(m.group(2))
    if new_val is None or new_val == m.group(2):
        return None
    return [(line, [m.group(1) + new_val + m.group(3)])]


def fix_rename(ctx: Context, line: int, old_key: str, new_key: str) -> Fix | None:
    return fix_sub(ctx, line, rf"^(\s*)({re.escape(old_key)})(\s*:)", lambda m: m.group(1) + new_key + m.group(3))


def int_to_float(v: str) -> str | None:
    return v + ".0" if re.fullmatch(r"[-+]?\d+", v) else None


def float_to_int(v: str) -> str | None:
    m = re.fullmatch(r"([-+]?\d+)\.0*", v)
    return m.group(1) if m else None


def _flow(v: str) -> bool:
    return v.startswith("[") and v.endswith("]") and "[" not in v[1:-1]


def ints_to_floats(v: str) -> str | None:
    if not _flow(v):
        return None
    return re.sub(_NUM, lambda m: m.group(0) if re.search(r"[.eE]", m.group(2)) else m.group(0) + ".0", v)


def make_sign(v: str, negative: bool) -> str | None:
    if not _flow(v):
        return None

    def one(m: re.Match) -> str:
        val = float(m.group(2))
        if val == 0:
            return m.group(0)
        return ("-" if negative else "") + m.group(2)

    return re.sub(_NUM, one, v)


# Nav2 fills in a default plugin type for these ids when `plugin` is omitted.
DEFAULT_IDS = {
    "GridBased",
    "FollowPath",
    "progress_checker",
    "goal_checker",
    "simple_smoother",
    "spin",
    "backup",
    "drive_on_heading",
    "wait",
    "assisted_teleop",
    "static_layer",
    "obstacle_layer",
    "inflation_layer",
    "wait_at_waypoint",
    "navigate_to_pose",
    "navigate_through_poses",
}

# Packages whose plugins were registered as pkg/Class in Humble; Jazzy+ uses pkg::Class.
SLASH_PACKAGES = {"nav2_navfn_planner", "nav2_behaviors", "nav2_smac_planner", "nav2_theta_star_planner"}

COSTMAPS = {"local_costmap", "global_costmap"}


# ---------- N0xx file structure ----------

def check_structure(ctx: Context) -> None:
    for d in ctx.dups:
        ctx.add("N002", WARNING, d.line, f"duplicate key `{d.key}` (first defined on line {d.first_line}); the later value silently wins")

    root = ctx.root
    if root is None or root.kind != "map":
        ctx.add("N001", ERROR, 1, "file is empty or its top level is not a mapping")
        return

    def contains_rp(n: Node) -> bool:
        if n.kind != "map":
            return False
        if "ros__parameters" in n.value:
            return True
        return any(contains_rp(v) for v in n.value.values())

    def find_near_rp(n: Node) -> tuple[str, int] | None:
        if n.kind != "map":
            return None
        for k, v in n.value.items():
            if close(k, ["ros__parameters"], 0.75):
                return k, n.key_lines[k]
            r = find_near_rp(v)
            if r:
                return r
        return None

    for k, v in root.value.items():
        if v.kind == "map" and not contains_rp(v):
            near = find_near_rp(v)
            hint = f"`{near[0]}` on line {near[1]} should be `ros__parameters` (two underscores)" if near else ""
            fix = fix_rename(ctx, near[1], near[0], "ros__parameters") if near else None
            ctx.add("N003", ERROR, root.key_lines[k], f"no `ros__parameters` under `{k}`; ROS 2 will not load these parameters", hint, fix)

    for s in ctx.sections:
        if s.name in COSTMAPS and (len(s.yaml_path) < 2 or s.yaml_path[-2] != s.name):
            ctx.add(
                "N004",
                ERROR,
                s.line,
                f"the {s.name} node's full name is /{s.name}/{s.name}, so its parameters need two levels of nesting",
                f"use:\n{s.name}:\n  {s.name}:\n    ros__parameters:",
            )

    # N006: parameters indented at the level of ros__parameters instead of under it
    def misplaced(n: Node, name: str) -> None:
        if n.kind != "map":
            return
        if "ros__parameters" not in n.value:
            for k, v in n.value.items():
                misplaced(v, k)
            return
        rp = n.value["ros__parameters"]
        others = [k for k in n.value if k != "ros__parameters"]
        for k in others:
            ctx.add(
                "N006",
                ERROR,
                n.key_lines[k],
                f"`{k}` is next to `ros__parameters`, not under it, so ROS 2 does not load it as a parameter of `{name}`",
                "indent it under ros__parameters",
            )
        if rp.kind == "scalar" and not others:
            ctx.add("N006", WARNING, n.key_lines["ros__parameters"], f"`ros__parameters` of `{name}` is empty")

    for k, v in root.value.items():
        misplaced(v, k)

# ---------- E1xx parameter types ----------

def split_key(scope: Scope, key: str) -> tuple[str, str]:
    """`BaseObstacle.scale` inside a plugin is the same parameter as a nested `BaseObstacle: {scale: ..}`."""
    if "." not in key:
        return scope.schema, key
    group, leaf = key.rsplit(".", 1)
    return f"{scope.schema}/{group.replace('.', '/')}", leaf


def known_params(ctx: Context, schema: str) -> dict[str, set[str]] | None:
    """Parameters Nav2 declares for a scope (sources plus official config), or None if Nav2 does not know the scope."""
    if ctx.distro:
        src = declared(ctx.distro).tables.get(schema)
        ref = reference(ctx.distro).types.get(schema)
    else:
        src = declared_union().get(schema)
        ref = union_reference().types.get(schema)
    if src is None and ref is None:
        return None
    out: dict[str, set[str]] = {k: set(v) for k, v in (src or {}).items()}
    for k, ts in (ref or {}).items():
        out.setdefault(k, set()).update(ts)
    return out


def lookup(ctx: Context, scope: Scope, key: str) -> tuple[dict[str, set[str]] | None, str]:
    """(known parameters for `key`'s scope, leaf name). A RotationShim scope also accepts the shim's own params."""
    schema, leaf = split_key(scope, key)
    table = known_params(ctx, schema)
    if scope.extra_schema and "." not in key:
        extra = known_params(ctx, scope.extra_schema)
        if extra is not None:
            merged = {k: set(v) for k, v in (table or {}).items()}
            for k, ts in extra.items():
                merged.setdefault(k, set()).update(ts)
            table = merged
    return table, leaf


def parameter_evidence(ctx: Context, scope: Scope, key: str) -> list[dict]:
    schema, leaf = split_key(scope, key)
    schemas = [schema]
    if scope.extra_schema and "." not in key:
        schemas.append(scope.extra_schema)
    evidence = [parameter_info(d, sch, leaf) for d in ([ctx.distro] if ctx.distro else DISTROS) for sch in schemas]
    return [e for e in evidence if e["status"] != "unknown_scope"]


def _expected(ctx: Context, scope: Scope, key: str) -> set[str] | None:
    if scope.node in COSTMAPS and scope.path == "" and key == "footprint":
        return {"str"}  # Nav2 footprint is a string "[[x, y], ...]"
    if scope.registered_by == "polygons" and key == "points":
        return None  # distro dependent, handled by D210
    table, leaf = lookup(ctx, scope, key)
    return (table or {}).get(leaf) or None


def check_types(ctx: Context) -> None:
    for sc in all_scopes(ctx):
        for k, v in sc.params.value.items():
            if v.kind == "map" or is_placeholder(v):
                continue
            line = key_line(sc, k)
            t = ros_type(v)
            if t == "nested":
                hint = 'Nav2 expects footprint as a string: footprint: "[[0.2, 0.2], [0.2, -0.2], ...]"' if k == "footprint" else ""
                fix = fix_value(ctx, line, k, lambda s: f'"{s}"' if s.startswith("[[") and s.endswith("]]") else None) if k == "footprint" else None
                ctx.add("E101", ERROR, line, f"`{sc.full(k)}` is a nested list; ROS 2 parameters do not support nested arrays", hint, fix)
                continue
            if t == "mixed":
                kinds = {ros_type(e) for e in v.value}
                numeric = kinds == {"int", "float"}
                hint = "write integers as floats, e.g. 0 -> 0.0" if numeric else ""
                fix = fix_value(ctx, line, k, ints_to_floats) if numeric else None
                ctx.add("E101", ERROR, line, f"`{sc.full(k)}` mixes {fmt_types(kinds)}; ROS 2 arrays must have a single element type", hint, fix)
                continue
            exp = _expected(ctx, sc, k)
            if not exp or t in exp or t == "null":
                continue
            if t == "list" and any(e.startswith("list") for e in exp):
                continue
            hint, fix = "", None
            if t == "int" and "float" in exp:
                hint, fix = f"write {v.value}.0", fix_value(ctx, line, k, int_to_float)
            elif t == "list[int]" and "list[float]" in exp:
                hint, fix = "write the elements as floats, e.g. [0.5, 0.0, 2.0]", fix_value(ctx, line, k, ints_to_floats)
            elif t == "float" and "int" in exp:
                hint = "this parameter is an integer; drop the fractional part"
                fix = fix_value(ctx, line, k, float_to_int)
            ctx.add(
                "E102",
                ERROR,
                line,
                f"`{sc.full(k)}` should be {fmt_types(exp)} but is {t}; Nav2 will fail with a parameter type mismatch",
                hint,
                fix,
                parameter_evidence(ctx, sc, k),
            )


# ---------- P1xx plugin lists ----------

def check_registries(ctx: Context) -> None:
    for sc in all_scopes(ctx):
        defined = {c.path.rsplit(".", 1)[-1]: c for c in sc.children}
        listed: set[str] = set()
        for k, v in sc.params.value.items():
            if k not in PLUGIN_REGISTRIES and k not in ("polygons", "observation_sources"):
                continue
            names = registry_names(v)
            listed.update(names)
            for name in names:
                child = defined.get(name)
                if child is None:
                    if k == "observation_sources" and sc.node not in COSTMAPS:
                        sev = ERROR  # collision_monitor sources have no defaults
                    elif k == "polygons":
                        sev = ERROR
                    elif k == "observation_sources":
                        sev = WARNING
                    elif name in DEFAULT_IDS:
                        continue
                    else:
                        sev = ERROR
                    ctx.add("P101", sev, key_line(sc, k), f"`{sc.full(k)}` lists `{name}` but there is no `{name}:` section")
                elif k in PLUGIN_REGISTRIES and child.plugin is None and name not in DEFAULT_IDS:
                    ctx.add("P102", ERROR, child.line, f"`{child.path}` has no `plugin` field")

        # A costmap layer that is defined but not listed is a classic "my change has no effect".
        if sc.node in COSTMAPS and sc.path == "" and ("plugins" in sc.params.value or "filters" in sc.params.value):
            for name, child in defined.items():
                if child.plugin and name not in listed:
                    ctx.add(
                        "P103",
                        INFO,
                        sc.params.key_lines[name],
                        f"`{name}` defines plugin {child.plugin} but is not in plugins/filters, so it is never loaded",
                    )


# ---------- D2xx distro migration ----------

def guess_distro(sections: list[NodeSection]) -> tuple[str | None, str]:
    """Guess the distro from syntax that only some distros use. Returns (distro, reason)."""
    old: list[str] = []
    new: list[str] = []
    kilted = False
    for sec in sections:
        for sc in walk(sec.root):
            if sc.plugin and "/" in sc.plugin and sc.plugin.split("/")[0] in SLASH_PACKAGES:
                old.append(f"plugin name {sc.plugin}")
            if sc.plugin and "::" in sc.plugin and sc.plugin.split("::")[0] in SLASH_PACKAGES:
                new.append(f"plugin name {sc.plugin}")
        p = sec.params.value
        if sec.name == "controller_server":
            if "progress_checker_plugin" in p:
                old.append("progress_checker_plugin")
            if "progress_checker_plugins" in p:
                new.append("progress_checker_plugins")
        if sec.name == "behavior_server":
            if "costmap_topic" in p:
                old.append("behavior_server.costmap_topic")
            if "local_costmap_topic" in p or "local_frame" in p:
                new.append("behavior_server.local_costmap_topic/local_frame")
        if sec.name == "bt_navigator":
            if "error_code_name_prefixes" in p:
                kilted = True
                new.append("error_code_name_prefixes")
            if "navigators" in p or "error_code_names" in p:
                new.append("bt_navigator.navigators/error_code_names")
    if old and new:
        return None, f"found both old-style ({old[0]}) and new-style ({new[0]}) syntax"
    if old:
        return "humble", old[0]
    if kilted:
        return "kilted", "error_code_name_prefixes"
    if new:
        return "jazzy", new[0]
    return None, "no distro-specific syntax found"


def _points_to_string(v: str) -> str | None:
    try:
        vals = [float(x) for x in ast.literal_eval(v)]
    except (ValueError, SyntaxError, TypeError):
        return None
    if not vals or len(vals) % 2:
        return None
    return '"[' + ", ".join(f"[{vals[i]:g}, {vals[i + 1]:g}]" for i in range(0, len(vals), 2)) + ']"'


def _points_to_flat(v: str) -> str | None:
    try:
        pts = ast.literal_eval(ast.literal_eval(v))
        vals = [float(c) for p in pts for c in p]
    except (ValueError, SyntaxError, TypeError):
        return None
    return "[" + ", ".join(f"{x:g}" if "." in f"{x:g}" else f"{x:g}.0" for x in vals) + "]"


def check_migration(ctx: Context) -> None:
    if ctx.distro is None:
        return
    d = ctx.distro
    jazzy_plus = ctx.at_least("jazzy")

    for sc in all_scopes(ctx):
        if sc.plugin:
            line = key_line(sc, "plugin")
            if jazzy_plus and "/" in sc.plugin:
                new = normalize_plugin(sc.plugin)
                if sc.plugin.split("/")[0] in nav2_plugin_packages():
                    ctx.add("D201", ERROR, line, f"{d} plugin names use `::`; `{sc.plugin}` will fail to load", f"use {new}", fix_sub(ctx, line, re.escape(sc.plugin), new))
                else:
                    # A third-party plugin is looked up by the name its own plugin XML registers.
                    ctx.add("D201", INFO, line, f"`{sc.plugin}` uses `/`; Nav2's own plugins use `::` since Jazzy",
                            f"keep it if the plugin's XML registers this name, otherwise use {new}")
            if d == "humble" and "::" in sc.plugin and sc.plugin.split("::")[0] in SLASH_PACKAGES:
                new = sc.plugin.replace("::", "/")
                ctx.add("D201", WARNING, line, f"in Humble, {sc.plugin.split('::')[0]} plugins are registered as `pkg/Class`", f"use {new}", fix_sub(ctx, line, re.escape(sc.plugin), new))
        p = sc.params.value
        if jazzy_plus and plugin_is(sc, "SmacPlannerHybrid") and "viz_expansions" in p:
            line = key_line(sc, "viz_expansions")
            ctx.add("D207", WARNING, line, "since Jazzy, `viz_expansions` is renamed to `debug_visualizations`", "", fix_rename(ctx, line, "viz_expansions", "debug_visualizations"))
        if jazzy_plus and plugin_is(sc, "RegulatedPurePursuitController") and "use_interpolation" in p:
            ctx.add("D208", WARNING, key_line(sc, "use_interpolation"), "since Jazzy, RPP `use_interpolation` is deprecated")
        if sc.registered_by == "polygons" and "points" in p:
            t = ros_type(p["points"])
            line = key_line(sc, "points")
            if jazzy_plus and t != "str":
                ctx.add(
                    "D210", ERROR, line, f"in {d}, collision_monitor polygon `points` is a string",
                    'points: "[[0.3, 0.3], [0.3, -0.3], [-0.3, -0.3], [-0.3, 0.3]]"',
                    fix_value(ctx, line, "points", _points_to_string),
                )
            if d == "humble" and t != "list[float]":
                transform = _points_to_flat if t == "str" else ints_to_floats
                ctx.add(
                    "D210", ERROR, line, "in Humble, collision_monitor polygon `points` is a flat float array",
                    "points: [0.3, 0.3, 0.3, -0.3, -0.3, -0.3, -0.3, 0.3]",
                    fix_value(ctx, line, "points", transform),
                )

    cs = ctx.section("controller_server")
    if cs:
        p = cs.params.value
        if jazzy_plus and "progress_checker_plugin" in p:
            line = cs.params.key_lines["progress_checker_plugin"]
            fix = fix_sub(ctx, line, r"^(\s*)progress_checker_plugin(\s*:\s*)([\"']?)(\w+)\3", lambda m: f'{m.group(1)}progress_checker_plugins{m.group(2)}["{m.group(4)}"]')
            ctx.add("D202", WARNING, line, f"{d} uses the list parameter `progress_checker_plugins`", 'progress_checker_plugins: ["progress_checker"]', fix)
        if d == "humble" and "progress_checker_plugins" in p:
            line = cs.params.key_lines["progress_checker_plugins"]
            fix = fix_sub(ctx, line, r"^(\s*)progress_checker_plugins(\s*:\s*)\[\s*([\"']?)(\w+)\3\s*\]", lambda m: f'{m.group(1)}progress_checker_plugin{m.group(2)}"{m.group(4)}"')
            ctx.add("D202", WARNING, line, "Humble uses the string parameter `progress_checker_plugin`; this list is ignored", 'progress_checker_plugin: "progress_checker"', fix)

    bs = ctx.section("behavior_server")
    if bs:
        p = bs.params.value
        renames = {"costmap_topic": "local_costmap_topic", "footprint_topic": "local_footprint_topic"}
        for old, new in renames.items():
            if jazzy_plus and old in p:
                line = bs.params.key_lines[old]
                ctx.add("D203", WARNING, line, f"{d} behavior_server uses `{new}`; `{old}` is ignored", "", fix_rename(ctx, line, old, new))
            if d == "humble" and new in p:
                line = bs.params.key_lines[new]
                ctx.add("D203", WARNING, line, f"Humble behavior_server uses `{old}`; `{new}` is ignored", "", fix_rename(ctx, line, new, old))
        gf = p.get("global_frame")
        if jazzy_plus and gf is not None and gf.value == "odom" and "local_frame" not in p:
            line = bs.params.key_lines["global_frame"]
            src = _src(ctx, line) or ""
            m = re.match(r"^(\s*)global_frame\s*:\s*[\"']?odom[\"']?\s*$", src)
            fix = [(line, [f"{m.group(1)}local_frame: odom", f"{m.group(1)}global_frame: map"])] if m else None
            ctx.add(
                "D209",
                WARNING,
                line,
                "since Jazzy, behavior_server has separate `local_frame` (odom) and `global_frame` (map); "
                "this is Humble-style config and global_frame should not be odom",
                "local_frame: odom\nglobal_frame: map",
                fix,
            )

    bt = ctx.section("bt_navigator")
    if bt:
        p = bt.params.value
        libs = p.get("plugin_lib_names")
        if jazzy_plus and libs is not None:
            def builtin(n: str) -> bool:
                return n.startswith("nav2_") and (n.endswith("_bt_node") or n == "nav2_path_expiring_timer_condition")

            builtins = [n for n in registry_names(libs) if builtin(n)]
            if builtins:
                key_ln = bt.params.key_lines["plugin_lib_names"]
                fix: Fix | None = None
                if libs.kind == "seq" and libs.value and all(e.line != key_ln for e in libs.value):
                    fix = [(e.line, []) for e in libs.value if builtin(str(e.value))]
                    if len(fix) == len(libs.value):
                        fix.append((key_ln, []))
                elif len(builtins) == len(registry_names(libs)):
                    fix = [(key_ln, [])]
                ctx.add(
                    "D204",
                    WARNING,
                    key_ln,
                    f"{d} loads all built-in BT nodes automatically and plugin_lib_names should list only custom nodes; "
                    f"{len(builtins)} built-in nodes are listed here (e.g. {builtins[0]}), which usually causes duplicate-registration errors",
                    "remove the built-in nodes, or remove plugin_lib_names entirely",
                    fix,
                )
        if ctx.at_least("kilted") and "error_code_names" in p:
            ctx.add("D205", ERROR, bt.params.key_lines["error_code_names"], f"in {d}, `error_code_names` throws at startup and must be replaced by `error_code_name_prefixes`")
        if not ctx.at_least("kilted") and "error_code_name_prefixes" in p:
            ctx.add("D205", WARNING, bt.params.key_lines["error_code_name_prefixes"], f"`error_code_name_prefixes` was added in Kilted; {d} ignores it")

    rs = ctx.section("recoveries_server")
    if rs:
        ctx.add(
            "D211",
            WARNING,
            rs.key_line,
            "since Humble, recoveries_server is renamed to behavior_server; no node reads this section",
            "rename it to behavior_server and change nav2_recoveries/... plugins to nav2_behaviors/... (`::` since Jazzy)",
        )

    ds = ctx.section("docking_server")
    if ds and ctx.at_least("kilted") and "dock_backwards" in ds.params.value:
        ctx.add("D206", WARNING, ds.params.key_lines["dock_backwards"], "since Kilted, `dock_backwards` moved into the dock plugin as the string parameter `dock_direction`", 'dock_direction: "backward"')


# ---------- S3xx cross-parameter sanity ----------

def _robot_radius(costmap: Scope) -> float | None:
    r = num(costmap.params.get("robot_radius"))
    fp = costmap.params.get("footprint")
    if fp is not None and fp.kind == "scalar" and isinstance(fp.value, str) and fp.value.strip() not in ("", "[]"):
        try:
            pts = ast.literal_eval(fp.value)
            return max(math.hypot(float(x), float(y)) for x, y in pts)
        except (ValueError, SyntaxError, TypeError):
            return r
    return r


def check_sanity(ctx: Context) -> None:
    # Mixed use_sim_time: in simulation some nodes run on wall time and TF stamps stop matching.
    sim = {s.name: s for s in ctx.sections if isinstance(getattr(s.params.get("use_sim_time"), "value", None), bool)}
    vals = {s.params.value["use_sim_time"].value for s in sim.values()}
    if len(vals) == 2:
        falses = [n for n, s in sim.items() if s.params.value["use_sim_time"].value is False]
        trues = [n for n in sim if n not in falses]
        minority = falses if len(falses) <= len(trues) else trues
        for n in minority:
            s = sim[n]
            ctx.add("S301", WARNING, s.params.key_lines["use_sim_time"], f"`{n}` use_sim_time differs from the other {len(sim) - len(minority)} nodes")

    for name in COSTMAPS:
        cm = ctx.section(name)
        if not cm:
            continue
        radius = _robot_radius(cm.root)
        for sc in walk(cm.root):
            if plugin_is(sc, "InflationLayer") and radius is not None:
                ir = num(sc.params.get("inflation_radius"))
                if ir is not None and ir < radius:
                    ctx.add("S302", WARNING, key_line(sc, "inflation_radius"), f"{name} inflation_radius={ir} is smaller than the robot radius {radius:.3f}; plans will hug obstacles")
            if plugin_is(sc, "ObstacleLayer", "VoxelLayer"):
                for src in sc.children:
                    rt = num(src.params.get("raytrace_max_range"))
                    ob = num(src.params.get("obstacle_max_range"))
                    if rt is not None and ob is not None and rt < ob:
                        ctx.add(
                            "S303",
                            WARNING,
                            key_line(src, "raytrace_max_range"),
                            f"`{src.path}` raytrace_max_range={rt} is less than obstacle_max_range={ob}; "
                            f"obstacles marked between {rt} and {ob} m are never cleared",
                        )

    vs = ctx.section("velocity_smoother")
    vmax = None
    if vs:
        p = vs.params
        arrays = {k: num_list(p.get(k)) for k in ("max_velocity", "min_velocity", "max_accel", "max_decel")}
        for k, arr in arrays.items():
            if arr is not None and len(arr) != 3:
                ctx.add("S304", ERROR, p.key_lines[k], f"velocity_smoother.{k} needs 3 elements [x, y, theta], got {len(arr)}")
        acc, dec = arrays["max_accel"], arrays["max_decel"]
        if acc and any(a < 0 for a in acc):
            line = p.key_lines["max_accel"]
            ctx.add("S304", ERROR, line, "velocity_smoother.max_accel must be non-negative; Nav2 throws during configure", "", fix_value(ctx, line, "max_accel", lambda s: make_sign(s, False)))
        if dec and any(a > 0 for a in dec):
            line = p.key_lines["max_decel"]
            ctx.add("S304", ERROR, line, "velocity_smoother.max_decel must be non-positive (deceleration is negative); Nav2 throws during configure", "", fix_value(ctx, line, "max_decel", lambda s: make_sign(s, True)))
        mx, mn = arrays["max_velocity"], arrays["min_velocity"]
        if mx and mn and len(mx) == len(mn) and any(a < b for a, b in zip(mx, mn)):
            ctx.add("S304", ERROR, p.key_lines["min_velocity"], "velocity_smoother.min_velocity has a component greater than max_velocity")
        vmax = mx

    cs = ctx.section("controller_server")
    if cs:
        freq = num(cs.params.get("controller_frequency")) or 20.0
        lc = ctx.section("local_costmap")
        for sc in cs.root.children:
            p = sc.params
            lin = ang = None
            if plugin_is(sc, "DWBLocalPlanner"):
                lin, ang = num(p.get("max_vel_x")), num(p.get("max_vel_theta"))
            elif plugin_is(sc, "MPPIController"):
                lin, ang = num(p.get("vx_max")), num(p.get("wz_max"))
            elif plugin_is(sc, "RegulatedPurePursuitController"):
                lin = num(p.get("desired_linear_vel"))
            elif plugin_is(sc, "GracefulController"):
                lin, ang = num(p.get("v_linear_max")), num(p.get("v_angular_max"))
            if vmax and len(vmax) == 3:
                for val, idx, label in ((lin, 0, "linear"), (ang, 2, "angular")):
                    if val is not None and val > vmax[idx] + 1e-9:
                        ctx.add(
                            "S305",
                            WARNING,
                            sc.line,
                            f"`{sc.path}` max {label} velocity {val} exceeds velocity_smoother.max_velocity[{idx}]={vmax[idx]} and will be clipped",
                        )
            if plugin_is(sc, "MPPIController"):
                dt = num(p.get("model_dt")) or 0.05
                if abs(dt - 1.0 / freq) > 1e-6:
                    ctx.add(
                        "S306",
                        WARNING,
                        key_line(sc, "model_dt") if "model_dt" in p.value else sc.line,
                        f"MPPI model_dt={dt} does not match controller_frequency={freq} Hz; "
                        f"the docs recommend model_dt = 1/controller_frequency = {1.0 / freq:.4g}",
                    )
                steps = num(p.get("time_steps")) or 56
                vx = num(p.get("vx_max")) or 0.5
                if lc:
                    w, h = num(lc.params.get("width")), num(lc.params.get("height"))
                    if w and h:
                        horizon = steps * dt * vx
                        if horizon > min(w, h) / 2:
                            ctx.add(
                                "S306",
                                WARNING,
                                sc.line,
                                f"MPPI horizon time_steps*model_dt*vx_max = {horizon:.2f} m exceeds the local costmap half-size "
                                f"{min(w, h) / 2:.2f} m; trajectory ends cannot see obstacles",
                            )

    amcl = ctx.section("amcl")
    if amcl:
        lo, hi = num(amcl.params.get("min_particles")), num(amcl.params.get("max_particles"))
        if lo is not None and hi is not None and lo > hi:
            ctx.add("S307", WARNING, amcl.params.key_lines["min_particles"], f"amcl.min_particles={lo:g} is greater than max_particles={hi:g}")


# ---------- T4xx spelling ----------

def _vocab(ref: Reference) -> set[str]:
    words: set[str] = set()
    for table in ref.types.values():
        for k in table:
            words.update(re.split(r"[_.]", k))
    for n in ref.nodes:
        words.update(n.split("_"))
    return words


def _looks_misspelled(key: str, vocab: set[str]) -> bool:
    """A key is a typo candidate only if at least one of its words is unknown.

    This keeps valid params like min_vel_theta (absent from the reference files, but made of
    known words) from being reported as a misspelling of max_vel_theta.
    """
    return any(w and w not in vocab and not w.isdigit() for w in re.split(r"[_.]", key))


def check_spelling(ctx: Context) -> None:
    ref: Reference = union_reference()
    vocab = _vocab(ref)
    migrated = {f.line for f in ctx.findings if f.rule.startswith("D")}
    for sec in ctx.sections:
        if sec.name not in ref.nodes and not sec.name.startswith("/") and _looks_misspelled(sec.name, vocab):
            m = close(sec.name, ref.nodes)
            if m:
                ctx.add("T401", WARNING, sec.key_line, f"unknown node name `{sec.name}`", f"did you mean `{m}`?")
    for sc in all_scopes(ctx):
        if sc.plugin:
            norm = normalize_plugin(sc.plugin)
            if norm not in ref.plugins:
                m = close(norm, ref.plugins, 0.85)
                if m:
                    ctx.add("T402", WARNING, key_line(sc, "plugin"), f"unknown plugin `{sc.plugin}`", f"did you mean `{m}`?")
        for k, v in sc.params.value.items():
            if v.kind == "map":
                continue
            schema, _ = split_key(sc, k)
            table, leaf = lookup(ctx, sc, k)
            line = key_line(sc, k)
            if table is not None:
                if leaf in table or line in migrated:
                    continue
                m = close(leaf, table, 0.75)
                hint = f"did you mean `{m}`?" if m else ""
                where = ctx.distro or "any supported distro"
                others = [d for d in DISTROS if d != ctx.distro and leaf in (declared(d).tables.get(schema) or {})]
                if others:
                    hint = f"`{leaf}` exists in {', '.join(others)}" + (f"; {hint}" if hint else "")
                hint += ("; " if hint else "") + "tables may be incomplete; verify the target distro and plugin documentation"
                ctx.add("T404", WARNING, line, f"`{sc.full(k)}` is not in the bundled parameter tables for this scope ({where})",
                        hint, evidence=parameter_evidence(ctx, sc, k))
                continue
            # Scope unknown to the Nav2 tables (third-party plugin): only flag likely typos.
            known = set(ref.types.get(sc.schema, {}))
            if len(known) < 3 or k in known or not _looks_misspelled(k, vocab):
                continue
            m = close(k, known)
            if m:
                ctx.add("T403", WARNING, line, f"`{sc.full(k)}` may be misspelled; verify the plugin's parameter documentation", f"did you mean `{m}`?")


ALL_CHECKS = [check_structure, check_types, check_registries, check_migration, check_sanity, check_spelling]
