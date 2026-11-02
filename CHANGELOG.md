# Changelog

All notable changes to nav2lint are documented here.

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

[0.2.1]: https://github.com/Leonhart999/nav2lint/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/Leonhart999/nav2lint/tree/v0.2.0
