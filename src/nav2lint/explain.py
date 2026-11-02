"""Human-readable rule guidance and parameter-table queries."""
from __future__ import annotations

from .rules import RULE_IDS
from .schema import DISTROS, normalize_plugin, parameter_info

# Guidance describes static checks, not a guarantee about a running robot.
_RULES = {
    "N001": ("Invalid input", "The file is empty, malformed YAML, not a parameter mapping, or not UTF-8.", "Correct the syntax or encoding before checking parameter values.", "No automatic fix: reconstructing invalid input requires intent."),
    "N002": ("Duplicate key", "A mapping contains the same key more than once; the later value wins.", "Remove the unintended definition after reviewing both locations.", "No automatic fix: either value may be the intended one."),
    "N003": ("Missing parameter section", "A node is missing ros__parameters or uses the common ros_parameters typo.", "Place node parameters beneath ros__parameters.", "Only the unambiguous ros_parameters key spelling is auto-fixed."),
    "N004": ("Costmap nesting", "A costmap configuration lacks the nested costmap node name.", "Use local_costmap.local_costmap.ros__parameters or its global equivalent.", "No automatic fix: namespaces must be reviewed."),
    "N005": ("Unknown suppression rule", "A nav2lint suppression comment names an unknown rule ID.", "Correct the ID or remove the stale suppression.", "No automatic fix: the intended rule is unknown."),
    "N006": ("Misplaced or empty parameters", "Parameters sit beside ros__parameters, or that section is empty.", "Indent parameters beneath ros__parameters; remove an intentionally empty section if appropriate.", "No automatic fix: moving keys may change the intended hierarchy."),
    "E101": ("Unsupported parameter array", "An array mixes element types or contains nested arrays.", "Use one element type; encode Nav2 footprint coordinates as a string.", "Recognizable inline numeric arrays and nested footprints can be auto-fixed; ambiguous layouts are left alone."),
    "E102": ("Parameter type mismatch", "The YAML type differs from the types recorded in the selected parameter tables.", "Check the parameter evidence and use the declared type. Tables are static approximations, not runtime introspection.", "Unambiguous inline integer/double conversions can be auto-fixed; other conversions need review."),
    "P101": ("Undefined registered instance", "A registry references a plugin, source, or polygon with no matching definition.", "Define the referenced instance or remove it from the registry; built-in default IDs are exempt where known.", "No automatic fix: creating a definition requires intent."),
    "P102": ("Missing plugin type", "A plugin instance lacks its plugin class field.", "Set plugin to the intended class; known default instances are exempt.", "No automatic fix: the plugin class cannot be inferred safely."),
    "P103": ("Inactive costmap plugin", "A defined costmap plugin is absent from plugins and filters.", "Register it if intended, or leave it as an inactive example.", "No automatic fix: inactive definitions may be intentional."),
    "D201": ("Plugin class separator", "The plugin separator differs from the known convention for the target distro and package.", "Use the target distro's plugin spelling.", "Known separator migrations can be auto-fixed."),
    "D202": ("Progress checker registry migration", "Humble uses progress_checker_plugin; newer distros use progress_checker_plugins.", "Use the singular string or plural array required by the target distro.", "Recognizable inline registry values can be auto-fixed."),
    "D203": ("Behavior topic migration", "Behavior server costmap and footprint topic parameter names changed.", "Use the target distro's local topic parameter names.", "Known key renames can be auto-fixed."),
    "D204": ("Built-in BT library migration", "Since Jazzy, built-in BT libraries need not be listed in plugin_lib_names.", "Keep only custom BT libraries in that list.", "Known built-in entries can be removed automatically while retaining custom entries."),
    "D205": ("Error code parameter migration", "Since Kilted, error_code_names is replaced by error_code_name_prefixes.", "Review the target distro's error-code prefix configuration.", "No automatic fix: the new values require review."),
    "D206": ("Dock direction migration", "Since Kilted, dock_backwards moved to the dock plugin's dock_direction setting.", "Configure dock_direction in the intended dock plugin.", "No automatic fix: the destination and direction need review."),
    "D207": ("Planner visualization migration", "Since Jazzy, viz_expansions is replaced by debug_visualizations.", "Use the target distro's visualization parameter name.", "The known key rename can be auto-fixed."),
    "D208": ("Deprecated interpolation parameter", "RPP use_interpolation is deprecated in newer distros.", "Review and remove the obsolete override when migrating.", "No automatic fix: verify controller behavior first."),
    "D209": ("Behavior frame migration", "Newer behavior servers distinguish local_frame from global_frame.", "Review local and global frame semantics for the target distro.", "The recognized global_frame: odom migration can be auto-fixed."),
    "D210": ("Collision polygon representation", "Collision polygon points use a flat float array in Humble and a string in newer distros.", "Use the representation required by the target distro.", "Recognizable inline polygon representations can be auto-fixed."),
    "D211": ("Legacy recovery node name", "recoveries_server was renamed to behavior_server.", "Review the node name and its launch configuration together.", "No automatic fix: launch files may also require changes."),
    "S301": ("Inconsistent simulation clock", "Nodes in the file disagree about use_sim_time.", "Use a consistent clock, or suppress this if launch overrides make the effective values consistent.", "No automatic fix: the intended clock is unknown."),
    "S302": ("Small inflation radius", "Inflation radius is below the configured robot radius or footprint circumradius.", "Review robot geometry and the intended costmap inflation behavior.", "No automatic fix: this is a tuning decision."),
    "S303": ("Short clearing range", "raytrace_max_range is below obstacle_max_range.", "Review clearing and marking ranges together.", "No automatic fix: sensor and environment constraints are unknown."),
    "S304": ("Velocity smoother limits", "Velocity smoother arrays have invalid lengths, signs, or min/max ordering.", "Use three-axis arrays, non-negative acceleration, non-positive deceleration, and ordered bounds.", "Recognizable inline acceleration/deceleration signs can be auto-fixed; bounds and lengths need review."),
    "S305": ("Controller exceeds smoother", "A known controller's speed limit exceeds the configured velocity smoother limit.", "Review which limit should constrain the robot; launch overrides are not resolved.", "No automatic fix: safe speed limits depend on the robot."),
    "S306": ("MPPI timing or horizon", "MPPI model_dt differs from the controller period, or its horizon exceeds the local costmap extent.", "Review controller frequency, model timestep, horizon, and costmap dimensions together.", "No automatic fix: this is a tuning decision."),
    "S307": ("AMCL particle bounds", "min_particles exceeds max_particles.", "Set ordered particle bounds appropriate for localization.", "No automatic fix: either bound could be intended."),
    "T401": ("Possible node typo", "A node name closely resembles a known name.", "Verify the spelling against launch files; custom node names may be intentional.", "No automatic fix: similarity does not establish intent."),
    "T402": ("Possible plugin typo", "A plugin class closely resembles a known class.", "Verify the installed plugin's exported class name.", "No automatic fix: third-party classes may have similar names."),
    "T403": ("Possible parameter typo", "A parameter in a scope without a known table resembles a known spelling.", "Verify the plugin documentation before renaming it.", "No automatic fix: spelling suggestions are heuristic."),
    "T404": ("Parameter absent from tables", "A parameter is absent from the selected scope's bundled tables, which may be incomplete.", "Check the target distro, plugin type, source snapshot, and spelling. Absence is not proof that Nav2 ignores the parameter.", "No automatic fix: the parameter may be valid but missing from the tables."),
}


def explain_rule(rule: str) -> dict:
    rule = rule.upper()
    if rule not in RULE_IDS:
        raise ValueError(f"Unknown rule ID: {rule}")
    title, check, action, fix = _RULES[rule]
    return {"rule": rule, "title": title, "check": check, "action": action, "automatic_fix": fix}


def describe_parameter(target: str, distro: str) -> dict:
    """Resolve node.param or plugin:package::Class/group.param without loading user code."""
    if distro not in DISTROS:
        raise ValueError("Parameter queries require an explicit supported --distro")
    if "." not in target:
        raise ValueError("Use NODE.PARAMETER or plugin:PACKAGE::CLASS/GROUP.PARAMETER")
    owner, key = target.rsplit(".", 1)
    if not owner or not key or any(not part for part in owner.split(".")):
        raise ValueError("Parameter queries cannot contain empty path components")
    if owner.startswith("plugin:"):
        plugin_path = owner[len("plugin:"):]
        plugin, sep, groups = plugin_path.partition("/")
        if not plugin or "::" not in plugin:
            raise ValueError("Use a normalized plugin class: plugin:PACKAGE::CLASS.PARAMETER")
        schema = f"plugin:{normalize_plugin(plugin)}" + (f"/{groups.replace('.', '/')}" if sep else "")
    else:
        owner = owner.removeprefix("node:")
        parts = owner.split(".")
        if not all(parts):
            raise ValueError("Parameter queries cannot contain empty path components")
        schema = "node:" + parts[0] + "".join("/" + p for p in parts[1:])
    if schema.endswith("/") or "//" in schema:
        raise ValueError("Parameter queries cannot contain empty path components")
    return {"query": target, **parameter_info(distro, schema, key)}
