# Changelog

All notable changes to nav2lint are documented here.

## [0.3.1] - 2026-11-03

### Fixed

- D201 no longer reports third-party `pkg/Class` plugin names on Jazzy+ as load errors, and `--fix` no longer rewrites them. Their own plugin XML decides the registered name; for example, STVL registers `spatio_temporal_voxel_layer/SpatioTemporalVoxelLayer`. They are now reported as info. Nav2's own plugins are still errors.
- Parameters of the Python loopback simulator on Jazzy and Kilted (such as `enable_stamped_cmd_vel` and `publish_clock`) are no longer reported as T404. The extractor now reads literal `self.declare_parameter` calls in Python nodes. Other table entries are unchanged.

### Tests

- Found by linting 1,550 deduplicated real-world Nav2 parameter files from public GitHub repositories, with no crashes. Frequent E102 findings, such as integer `save_map_timeout` and float costmap `width`/`height`, were checked against the Nav2 sources and confirmed.

## [0.3.0] - 2026-11-02

### Added

- `--explain RULE` with check descriptions, review guidance, and automatic-fix boundaries for every rule.
- `--describe NODE.PARAMETER --distro DISTRO` and explicit plugin/group parameter queries, with source-table, reference-YAML, and built-in convention evidence.
- Structured `evidence` for E102 and T404 JSON diagnostics, including source snapshot commits, known/unknown types, and explicit incomplete-table status.
- `--init-vscode [WORKSPACE]` with configurable Python commands and safe merging of existing VS Code tasks, without machine-specific repository paths or automatic task execution.
- A pre-commit hook for checking Nav2 configurations without passing unrelated YAML files as explicit inputs.
- Windows/Linux CI, isolated wheel smoke checks, and focused source-extractor regression fixtures.

### Changed

- T404 now reports absence from bundled tables rather than claiming that Nav2 necessarily ignores the parameter. T403 spelling advice is also explicitly tentative.
- Portable VS Code tasks start manually by default. Existing custom tasks are preserved by initialization.
- Initialization output now explains workspace selection, preserved interpreter/automatic-run settings, and Python installation requirements.
- Document missing-task troubleshooting, WSL UNC watcher limitations and a local workspace-file workaround; replace the editor quick-start placeholder with the current workspace directory.

## [0.2.1] - 2026-11-02

### Fixed

- Report non-UTF-8 parameter files as N001 with the line of the first invalid byte instead of crashing. Leave these files unchanged when using `--fix`.
- Detect parameters indented next to `ros__parameters` instead of beneath it (N006 error), and report an empty `ros__parameters` section as an N006 warning.
- Accept both RotationShimController parameters and parameters of its `primary_controller` in the same plugin scope. Apply type and speed checks to the wrapped controller as well.
- Report the correct node-name line for T401 and D211 when comments appear before `ros__parameters`.
- Correct the DWB regression test to distinguish the valid `min_speed_theta` parameter from the undeclared `min_vel_theta` parameter.
- Align the README's minimum Python version with the package metadata: Python 3.9 or later.

### Tests

- Add regression coverage for encoding errors, misplaced parameters, wrapped controller parameters, and diagnostic line numbers.
- Verify the release with 70 passing tests on Windows with Python 3.12.

## [0.2.0] - 2026-11-02

Initial tagged public release, based on commit `918bcdc`.

### Added

- Static checks for Nav2 parameter YAML without installing ROS or launching Nav2.
- Parameter names and types extracted from Nav2 C++ sources, supplemented by official reference configurations for Humble, Jazzy, Kilted, and Rolling.
- Checks for YAML structure, duplicate keys, parameter types, plugin configuration, distro migrations, cross-parameter consistency, and likely spelling mistakes.
- `--fix` and `--diff` for unambiguous mechanical fixes while preserving unaffected text, comments, and line endings.
- Project configuration through `.nav2lint.yaml`, severity overrides, and inline suppression comments.
- Text, line-oriented, and JSON output, strict mode, directory scanning, and watch mode.
- VS Code task examples with a problem matcher.
- A Python API, an English README, and a Chinese user guide.
- Apache-2.0 license, copyright notice, and author metadata for Leonhart999.

[0.3.1]: https://github.com/Leonhart999/nav2lint/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/Leonhart999/nav2lint/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/Leonhart999/nav2lint/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/Leonhart999/nav2lint/tree/v0.2.0
