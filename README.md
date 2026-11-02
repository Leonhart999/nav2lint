# nav2lint

Static checker for ROS 2 Nav2 parameter files (`nav2_params.yaml`). It needs no ROS install and does not start Nav2; it points at the offending line in milliseconds.

A wrong Nav2 parameter usually shows up only after launch, as a cryptic type error in the log, or not at all because the value is silently ignored. nav2lint catches these before you launch.

## Install

```bash
pip install -e .        # from this repository
```

The only dependency is PyYAML. Python 3.9+, works on Windows, Linux and WSL.

Inside a ROS 2 environment (PyYAML is already installed) you can also run it without installing:

```bash
PYTHONPATH=/path/to/nav2lint/src python3 -m nav2lint nav2_params.yaml
```

## Usage

```bash
nav2lint nav2_params.yaml                 # auto-detect the distro
nav2lint --distro humble nav2_params.yaml # humble / jazzy / kilted / rolling
nav2lint --distro jazzy old_humble.yaml   # pre-migration check: what breaks when a Humble config runs on Jazzy
nav2lint --format json *.yaml             # JSON output for CI
nav2lint --strict --info params.yaml      # non-zero exit on warnings too; show info findings
nav2lint --distro humble ~/ros2_ws/src    # a directory: every Nav2 params file under it
nav2lint --watch --distro humble ~/ros2_ws/src   # re-check on every save, Ctrl+C to stop
nav2lint --format line params.yaml        # one finding per line, hint inline (editors, grep)
nav2lint --diff --distro jazzy old.yaml   # show the automatic fixes as a diff, change nothing
nav2lint --fix --distro jazzy old.yaml    # apply them in place, then report what is left
```

For a directory, nav2lint picks the YAML files that have a `ros__parameters` section for a Nav2 node, and skips hidden directories and colcon's `build/`, `install/` and `log/`. Files named explicitly are always checked.

Exit codes: 0 when there are no errors, 1 when there are errors (or warnings with `--strict`), 2 when a file cannot be read or a config file is invalid.

## Explain rules and parameter evidence

```bash
nav2lint --explain T404
nav2lint --describe controller_server.controller_frequency --distro humble
nav2lint --describe plugin:nav2_costmap_2d::InflationLayer.inflation_radius --distro jazzy
nav2lint --describe plugin:dwb_core::DWBLocalPlanner/PathAlign.scale --distro humble
nav2lint --describe amcl.initial_pose.x --distro humble --format json
```

Queries require no input files and support text or JSON output. `--describe` requires an explicit supported `--distro`; it does not infer the target from the current directory's configuration. Plugin queries use `::` for the class separator and `/` for child groups. Querying a plugin instance such as `controller_server.FollowPath.max_vel_x` cannot infer its class without a file; use the explicit plugin class instead.

Evidence distinguishes extracted source tables, official reference YAML, and built-in rclcpp conventions. Extracted entries identify the bundled Nav2 commit and data artifact; per-parameter C++ source locations are not currently recorded. A known parameter with an unknown type is different from one absent from the tables. No bundled scope is claimed to be complete, and absence does **not** prove that Nav2 ignores a parameter.

E102 and T404 findings include an additive `evidence` array in JSON output. Other rules currently leave it empty; their rationale is available through `--explain`. A successful query exits 0 even for `not_in_tables` or `unknown_scope`; malformed queries and unknown rule IDs exit 2.

## Automatic fixes

`--fix` applies the fixes whose correct form is unambiguous and leaves the rest for you. It edits only the affected lines, so comments, ordering and line endings stay as they were. Run `--diff` first to review.

| Rule | What `--fix` does |
|---|---|
| N003 | `ros_parameters` -> `ros__parameters` |
| E101 | integers in a mixed inline array -> floats; inline nested `footprint` -> quoted string |
| E102 | `1` -> `1.0` for double parameters, `2000.0` -> `2000` for integer ones, inline integer arrays -> float arrays |
| D201 | plugin separator `/` <-> `::` for the target distro (Nav2's own plugins only) |
| D202 | `progress_checker_plugin: "x"` <-> `progress_checker_plugins: ["x"]` |
| D203 | behavior_server topic key renames |
| D204 | deletes the built-in BT nodes from `plugin_lib_names` (and the key if nothing is left) |
| D207 | `viz_expansions` -> `debug_visualizations` |
| D209 | `global_frame: odom` -> `local_frame: odom` + `global_frame: map` |
| D210 | collision polygon `points` between flat array and string form |
| S304 | sign of `max_accel` / `max_decel` |

Spelling findings (T401–T404) are never fixed automatically because the suggestion may be wrong. Fixes run on inline values only; block-style lists are left alone.

Migrating the official Humble config with `--fix --distro jazzy` applies 11 fixes and leaves no errors or warnings.

## Configuration and suppressions

A `.nav2lint.yaml` in the file's directory or any parent applies to every file below it:

```yaml
distro: humble          # used when --distro is not given
disable: [S301]         # rules to turn off
severity:               # change a rule's severity
  T404: info
```

`--config FILE` uses a specific file and `--no-config` ignores them. `--distro` on the command line overrides the config.

To silence a single finding, add a comment in the params file:

```yaml
use_sim_time: False  # nav2lint: disable=S301            this line
# nav2lint: disable-next-line=T404                        the next line
# nav2lint: disable-file=S305                             the whole file
# nav2lint: disable                                       all rules on this line
```

Rule IDs are separated by commas; text after them is ignored, so you can give a reason. An unknown rule ID in a comment is reported as N005. Suppressed findings are counted in the summary and are never auto-fixed.

## VS Code

Generate tasks using the Python environment that has nav2lint installed:

```bash
# Run from the root of the workspace you want VS Code to open.
nav2lint --init-vscode .
# On Linux/WSL, optionally select a Python command explicitly.
nav2lint --init-vscode . --python python3
```

The default uses the current interpreter. `--python` selects a command explicitly; it does not install nav2lint or validate that environment. For Remote-WSL, initialize from WSL using a WSL Python with nav2lint installed. For a Windows VS Code window, use a Windows interpreter. Generated absolute interpreter paths are environment-specific; regenerate for a new machine, or choose a portable command available on its PATH.

Initialization merges missing nav2lint tasks into `.vscode/tasks.json`, preserves existing tasks (including custom tasks with the same labels), and refuses unsafe or malformed input without changing the file. Supported JSONC comments and trailing commas are accepted; insertion preserves the existing text, comments, BOM, and line endings. Both tasks start manually from *Tasks: Run Task*; initialization never runs a task or opts into folder-open execution.

- **nav2lint: watch workspace** re-checks Nav2 parameter files while the task runs.
- **nav2lint: check current file** checks the open file once.

The problem matcher routes findings to VS Code's Problems panel. Set `distro: <your distro>` in a workspace `.nav2lint.yaml`. [editors/vscode/tasks.json](editors/vscode/tasks.json) is a portable manual-copy alternative; adjust its Python command for the environment.

### Tasks missing from the task picker

1. Open the **workspace root folder** in VS Code, not just a YAML file or a subfolder. Run *Tasks: Run Task*, then *Show All Tasks* if needed. Task labels are not standalone Command Palette commands.
2. Trust the workspace only if you recognize its contents. If the task file changed externally, reload the VS Code window after saving your work.
3. Existing same-label tasks are intentionally not upgraded. Review their `command` and platform overrides; new generated tasks always have a top-level `command`.
4. Windows VS Code accessing a WSL folder via a UNC share may report file-watcher errors. This does not prove the cause of every missing task. Prefer Remote-WSL, or use a local `.code-workspace` file containing the WSL folder URI and a workspace-level `tasks` object copied from the template. Open that workspace file and select a Windows interpreter when using Windows VS Code.
5. Use `python3`, not `python`, on systems where only Python 3 is available. If you ran the CLI with a temporary `PYTHONPATH`, install nav2lint in the task's environment first, or explicitly configure its environment. Do not use `sudo` just to initialize editor tasks.

For example, in a WSL terminal with an existing `~/ros2_ws` workspace and nav2lint installed in that interpreter:

```bash
cd ~/ros2_ws
python3 -m nav2lint --init-vscode .
```

Paths such as `/path/to/nav2lint` in generic examples must be replaced with the actual checkout path; they are not literal installation locations.

## Example

Output for [examples/broken_humble.yaml](examples/broken_humble.yaml):

```
examples/broken_humble.yaml:4: warning[S307] amcl.min_particles=500 is greater than max_particles=200
examples/broken_humble.yaml:7: warning[T401] unknown node name `controler_server`
    did you mean `controller_server`?
examples/broken_humble.yaml:14: warning[T404] `FollowPath.angular_dist_threshold` is not in the bundled parameter tables for this scope (humble)
    tables may be incomplete; verify the target distro and plugin documentation
examples/broken_humble.yaml:15: warning[N002] duplicate key `plugin` (first defined on line 13); the later value silently wins
examples/broken_humble.yaml:21: warning[S301] `local_costmap` use_sim_time differs from the other 3 nodes
examples/broken_humble.yaml:22: error[E101] `footprint` is a nested list; ROS 2 parameters do not support nested arrays
    Nav2 expects footprint as a string: footprint: "[[0.2, 0.2], [0.2, -0.2], ...]"
examples/broken_humble.yaml:26: error[E102] `inflation_layer.inflation_radius` should be float but is int; Nav2 will fail with a parameter type mismatch
    write 1.0
examples/broken_humble.yaml:33: warning[S303] `voxel_layer.scan` raytrace_max_range=2.0 is less than obstacle_max_range=3.0; obstacles marked between 2.0 and 3.0 m are never cleared
examples/broken_humble.yaml:37: error[N004] the global_costmap node's full name is /global_costmap/global_costmap, so its parameters need two levels of nesting
examples/broken_humble.yaml:43: error[E101] `max_velocity` mixes float / int; ROS 2 arrays must have a single element type
    write integers as floats, e.g. 0 -> 0.0
examples/broken_humble.yaml:46: error[S304] velocity_smoother.max_decel must be non-positive (deceleration is negative); Nav2 throws during configure
5 error, 6 warning, 0 info; 4 fixable with --fix
```

## Rules

| ID | Severity | What it checks |
|---|---|---|
| N001 | error | YAML syntax error (with line number), or a file that is not UTF-8 |
| N002 | warning | Duplicate key (both PyYAML and ROS 2 silently keep the last value) |
| N003 | error | Top-level node without `ros__parameters`, or misspelled as `ros_parameters` |
| N004 | error | Costmap nested only one level (should be `local_costmap: local_costmap: ros__parameters`) |
| N005 | warning | Unknown rule ID in a `# nav2lint:` comment |
| N006 | error/warning | Parameters indented next to `ros__parameters` instead of under it (error); empty `ros__parameters` (warning) |
| E101 | error | Array mixing int/float, or nested array (typically footprint written as a list) |
| E102 | error | Type differs from what Nav2 declares, e.g. a double parameter written as integer `1` |
| P101 | error/warning | Name listed in a plugin list but never defined |
| P102 | error | Plugin instance without a `plugin` field (Nav2 default ids excepted) |
| P103 | info | Costmap layer defined but not in `plugins`/`filters`, so never loaded |
| D201 | error/warning/info | Plugin separator: Jazzy+ Nav2 plugins use `pkg::Class`; some Humble packages use `pkg/Class`. A third-party `pkg/Class` on Jazzy+ is only info, because its own plugin XML decides the name |
| D202 | warning | `progress_checker_plugin` (Humble) vs `progress_checker_plugins` (Jazzy+) |
| D203 | warning | behavior_server renames such as `costmap_topic` -> `local_costmap_topic` |
| D204 | warning | Since Jazzy `plugin_lib_names` lists only custom BT nodes; built-ins load automatically |
| D205 | error/warning | Since Kilted `error_code_names` must be replaced by `error_code_name_prefixes` |
| D206 | warning | Since Kilted `dock_backwards` became the dock plugin's `dock_direction` |
| D207 | warning | Since Jazzy Smac Hybrid `viz_expansions` -> `debug_visualizations` |
| D208 | warning | Since Jazzy RPP `use_interpolation` is deprecated |
| D209 | warning | Since Jazzy behavior_server has separate `local_frame` / `global_frame` |
| D210 | error | collision_monitor polygon `points`: flat array in Humble, string since Jazzy |
| D211 | warning | Since Humble `recoveries_server` is renamed to `behavior_server` |
| S301 | warning | Inconsistent `use_sim_time` across nodes |
| S302 | warning | `inflation_radius` smaller than the robot radius (from robot_radius or footprint) |
| S303 | warning | `raytrace_max_range` < `obstacle_max_range`, so distant obstacles are never cleared |
| S304 | error | velocity_smoother arrays not of length 3, negative accel, positive decel, min > max |
| S305 | warning | Controller max speed above the velocity_smoother limit (DWB / MPPI / RPP / Graceful) |
| S306 | warning | MPPI `model_dt` != 1/controller_frequency; horizon longer than the local costmap |
| S307 | warning | AMCL `min_particles` > `max_particles` |
| T401–T403 | warning | Likely misspelled node, plugin or parameter name, with a "did you mean" hint |
| T404 | warning | Parameter absent from the bundled tables for this scope and distro; tables may be incomplete, and other recorded distros are suggested |

### How it works

- Parameter names and types come from two sources per distro:
  - tables extracted from the Nav2 sources by [tools/extract_params.py](tools/extract_params.py) (see [src/nav2lint/data/](src/nav2lint/data/)): every `declare_parameter`, `declare_parameter_if_not_declared`, costmap `declareParameter`, MPPI `getParam`, DWB `searchAndGetParam` and `declare_or_get_parameter` call, plus `self.declare_parameter` in Python nodes (the Jazzy/Kilted loopback simulator), with the type taken from the default value. About 1,000–1,700 parameters per distro across all nodes and built-in plugins;
  - the official `nav2_bringup/params/nav2_params.yaml` of each distro (see [src/nav2lint/refs/](src/nav2lint/refs/)), which covers the few parameters the extractor misses.
- T404 runs only for nodes and plugins found in those tables. Third-party plugins and nodes get structural checks and the conservative T403 spell check: a key is reported only if one of its words is unknown, e.g. `inflation_raduis`.
- Migration rules (D2xx) come from the official Nav2 migration guides, cross-checked against the navigation2 source on each branch.
- Distro auto-detection looks for syntax that only some distros use (e.g. `nav2_behaviors/Spin`, `error_code_name_prefixes`). When it cannot decide, D2xx rules are skipped and you are asked to pass `--distro`. Auto-detection can be wrong for a file that already uses newer syntax than its distro supports, so pass `--distro` when you know it.

### Known limitations

- Parameter overrides from launch files (`RewrittenYaml`, `use_sim_time` passed by launch) are not resolved.
- Behavior tree XML files are not checked.
- Third-party plugin parameters get structural checks only, no type checks.
- The source tables are a static reading of C++ code. Parameters declared through unusual helpers may be missing, which shows up as a T404 false positive; please report them.

## pre-commit

After v0.3.0 is published, add this to the consuming repository's `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/Leonhart999/nav2lint
    rev: v0.3.0
    hooks:
      - id: nav2lint
```

The hook does not auto-fix. On relevant YAML changes it scans `.` using Nav2 discovery, rather than treating every YAML file (such as a map description) as a parameter file. The scan checks the working tree, not only staged files, and can include pre-existing problems. Put the target distro in `.nav2lint.yaml`; add `args: [., --strict]` to fail on warnings too. The v0.3.0 tag must exist before a remote hook can use it.

## Development

```bash
pip install -e '.[dev]'
pytest
```

### Regenerating the parameter tables

The tables in `src/nav2lint/data/` record the navigation2 commit they were built from. To rebuild one, download and unpack that branch, then run the extractor:

```bash
curl -L -o nav2_humble.tar.gz https://api.github.com/repos/ros-navigation/navigation2/tarball/humble
mkdir src_humble && tar -xzf nav2_humble.tar.gz -C src_humble --strip-components=1
python tools/extract_params.py src_humble humble src/nav2lint/data/humble.json --commit <sha>
```

Use `main` for `rolling`. After regenerating, run `pytest`: the tests lint the official config of every distro and must report no errors or warnings.

## License

Copyright 2026 Leonhart999. Licensed under the [Apache License 2.0](LICENSE).

The reference configs under `src/nav2lint/refs/` and the tables under `src/nav2lint/data/` are derived from [ros-navigation/navigation2](https://github.com/ros-navigation/navigation2) (Apache-2.0); see [NOTICE](NOTICE).
