---
name: Bug or false-positive report
about: Report a reproducible crash, incorrect diagnostic, unsafe fix, or documentation problem
---

## Summary

What happened, and what did you expect? Reports in English or Chinese are welcome.

## Environment

- nav2lint version (`nav2lint --version`):
- Python version:
- Operating system:
- Target ROS 2 distro:
- Nav2 package version or source commit, if known:
- Installation method (pip, pipx, editable source, other):

## Reproduction

Exact command:

```text

```

Minimal YAML (remove secrets, private paths, network addresses, and confidential configuration):

```yaml

```

Relevant output:

```text

```

## Evidence or fix details

For a false positive, link the target version's documentation/source or include relevant `--describe` output. T404 alone does not prove that Nav2 ignores a parameter.

For an automatic-fix issue, include a sanitized before/after diff and say whether `--diff` showed it. Reproduce on a disposable copy, not a deployed robot's live configuration.

For a documentation issue, link the page and describe the step that failed.
