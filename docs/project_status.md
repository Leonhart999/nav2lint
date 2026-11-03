[中文](project_status_zh.md) | [ENG](project_status.md)

# Phase 1 completion and maintenance plan

Date: 2026-11-03. Latest software release: [v0.3.1](https://github.com/Leonhart999/nav2lint/releases/tag/v0.3.1).

## Decision

Phase 1 is complete. nav2lint is moving from active feature development to maintenance mode. The repository remains available and is not archived. This is a milestone decision, not a claim of a complete Nav2 validator or a 1.0 stability guarantee.

Documentation on `main` includes onboarding and milestone updates made after v0.3.1; the existing release tag has not been moved. No runtime behavior changes are part of this closeout.

## Delivered scope

- A ROS-free checker for Nav2 parameter YAML, with bundled source snapshots and reference configurations for Humble, Jazzy, Kilted, and Rolling.
- Checks for YAML structure, parameter types, plugin registration, known distro migrations, cross-parameter inconsistencies, and possible spelling mistakes.
- File and line diagnostics; text, line-oriented, and JSON output; rule explanations and parameter-evidence queries.
- Preview and opt-in mechanical fixes, project configuration, severity overrides, and suppression comments.
- Directory discovery, watch mode, manually started VS Code tasks, and a pre-commit hook. This is a CLI with editor integration, not a Marketplace extension.
- Automated Windows/Linux tests, distribution builds, installed-wheel smoke tests, bilingual READMEs, beginner guides, a demo animation, and public versioned releases.

## Validation evidence and boundaries

| Check | Evidence | What it does not establish |
|---|---|---|
| Automated regression suite | 213 tests at closeout, including a new check/preview/fix regression for the quick-start example | Complete rule coverage or real-robot safety |
| Official reference YAML | All four bundled distro configurations are checked by the suite without error/warning findings; installed-wheel tests repeat these checks | Compatibility with every Nav2 commit or downstream patch |
| Packaging | The suite builds an sdist and wheel, installs the wheel into a clean environment, and checks packaged resources, CLI queries, and task initialization | Publication on PyPI; no PyPI release has been made |
| Cross-platform CI | Eight Windows/Linux jobs covering Python 3.9, 3.10, 3.12, and 3.13; [pre-closeout run](https://github.com/Leonhart999/nav2lint/actions/runs/41590922593) passed all eight jobs | Every operating system or future runner image |
| Public configuration corpus | 1,550 deduplicated configurations were linted without crashes; two false-positive classes were corrected in v0.3.1 | A manually labeled accuracy/false-positive rate or runtime verification of all findings |
| Beginner installation | The v0.3.1 GitHub ZIP was installed in a clean Windows virtual environment and the CLI exercised | End-to-end testing of the documented Ubuntu user-pip and pipx flows |

Corpus collection and analysis artifacts remain local and are not included in this repository. The corpus result records work performed, not a fully reproducible public benchmark. The demo is a rendered terminal animation using real CLI output, not a screen recording or a two-minute video.

For current build results, see [GitHub Actions](https://github.com/Leonhart999/nav2lint/actions). Test counts describe this milestone and may change during maintenance.

## Known limitations

- Bundled parameter tables are incomplete static approximations of the recorded source snapshots, not runtime introspection. T404 means absence from those tables, not proof that Nav2 ignores a parameter.
- A distro name does not guarantee an exact match to the installed Nav2 package revision. Verify evidence against the actual version, especially for Rolling or downstream patches.
- Launch-time parameter overrides, rewritten YAML, and behavior tree XML are not resolved or checked.
- Third-party plugins do not receive complete parameter schemas or type checking. Exported plugin names are controlled by their plugin XML.
- Distro guessing and spelling suggestions are heuristic. Set `--distro` explicitly when known.
- Automatic fixes cannot infer robot-specific intent. Preview with `--diff` and keep a backup before using `--fix`.
- A clean lint result does not validate TF, sensors, localization, motion safety, navigation performance, or successful Nav2 startup. Simulation and runtime validation remain necessary.

## Maintenance policy

Accepted maintenance work:

1. Reproducible crashes and incorrect diagnostics, especially unsafe fixes or high-impact false positives.
2. Verified parameter-table or migration corrections, with target-version evidence and a regression test.
3. Documentation and installation corrections, plus necessary packaging/CI repairs.

New features are deferred unless a concrete use case justifies their scope and maintenance cost. There is no promised response time, release schedule, or automatic support for future ROS 2/Nav2 versions. Releases continue to use version updates, a changelog entry, a tag, and a GitHub Release; documentation-only maintenance may update `main` without changing the software version.

Deferred, not committed: PyPI publication, broader legacy-parameter explanations, and additional editor/UI integrations. A GUI, web service, Marketplace extension, exhaustive schema, or larger corpus is not a requirement for this milestone.

## Reporting a problem

Open a [GitHub issue](https://github.com/Leonhart999/nav2lint/issues/new?template=bug_report.md) with:

- `nav2lint --version`, Python version, OS, and the target ROS 2/Nav2 version or source commit if known.
- The exact command, relevant output, and a minimal YAML file that reproduces it.
- Expected behavior and the documentation/source evidence for a false-positive report.
- For a fix problem, a sanitized before/after diff and whether `--diff` showed the change.

Remove tokens, credentials, private paths, network addresses, and confidential robot configuration. Reproduce `--fix` reports on a disposable copy, not a deployed robot's live file.

## Continuing later

Start with the [quick start](quickstart.md), [README](../README.md), and [changelog](../CHANGELOG.md). For development, install `.[dev]` and run `python -m pytest -q`; this includes packaging tests. Keep generated datasets and build caches outside the checkout. Add a focused regression test for a maintenance fix and verify CI before publishing a release.
