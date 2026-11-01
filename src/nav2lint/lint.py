"""Public API: lint_text / lint_file / fix_text."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from . import rules
from .config import Config, parse_suppressions
from .loader import load
from .rules import ERROR, Context, Finding
from .schema import DISTROS, find_nodes

_NEWLINE = re.compile(r"\r\n|\r|\n")


@dataclass
class Result:
    path: str
    distro: str | None
    distro_reason: str  # why the distro was guessed; empty when given explicitly
    findings: list[Finding]
    suppressed: int = 0

    @property
    def errors(self) -> int:
        return sum(f.severity == ERROR for f in self.findings)

    @property
    def fixable(self) -> int:
        return sum(f.fix is not None for f in self.findings)


def _resolve_distro(distro: str | None, config: Config | None) -> str:
    """--distro wins, then the config file, then auto-detection."""
    d = distro or (config.distro if config else None) or "auto"
    if d != "auto" and d not in DISTROS:
        raise ValueError(f"unknown distro {d!r}, expected one of {DISTROS} or 'auto'")
    return d


def lint_text(text: str, distro: str | None = None, path: str = "<string>", config: Config | None = None) -> Result:
    distro = _resolve_distro(distro, config)
    lines = _NEWLINE.split(text)
    try:
        root, dups = load(text)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        line = mark.line + 1 if mark else 1
        problem = getattr(e, "problem", None) or str(e)
        return Result(path, None, "", [Finding("N001", ERROR, line, f"YAML syntax error: {problem}")])

    sections = find_nodes(root)
    reason = ""
    if distro == "auto":
        resolved, reason = rules.guess_distro(sections)
    else:
        resolved = distro
    ctx = Context(root, dups, sections, resolved, lines)
    for check in rules.ALL_CHECKS:
        check(ctx)

    sup = parse_suppressions(lines)
    kept: list[Finding] = []
    hidden = 0
    for f in ctx.findings:
        if (config and f.rule in config.disable) or sup.hides(f):
            hidden += 1
            continue
        if config and f.rule in config.severity:
            f.severity = config.severity[f.rule]
        kept.append(f)
    kept += sup.problems
    kept.sort(key=lambda f: (f.line, f.rule))
    return Result(path, resolved, reason, kept, hidden)


def read_text(path: str | Path) -> str:
    """Read a file keeping its original line endings, so fixes can write it back unchanged elsewhere."""
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def lint_file(path: str | Path, distro: str | None = None, config: Config | None = None) -> Result:
    return lint_text(read_text(path), distro, str(path), config)


def apply_fixes(text: str, findings: list[Finding]) -> tuple[str, int]:
    """Apply every fix whose lines do not overlap an earlier fix. Returns (new_text, fixes_applied)."""
    parts = _NEWLINE.split(text)
    endings = _NEWLINE.findall(text) + [""]
    default_nl = endings[0] if endings[0] else "\n"
    edits: dict[int, list[str]] = {}
    applied = 0
    for f in sorted(findings, key=lambda f: f.line):
        if not f.fix:
            continue
        touched = {ln for ln, _ in f.fix}
        if touched & edits.keys() or any(not 1 <= ln <= len(parts) for ln in touched):
            continue
        edits.update(dict(f.fix))
        applied += 1
    if not applied:
        return text, 0
    out = []
    for i, (line, nl) in enumerate(zip(parts, endings), 1):
        if i in edits:
            new = edits[i]
            for j, s in enumerate(new):
                out.append(s + (nl if j == len(new) - 1 else (nl or default_nl)))
        else:
            out.append(line + nl)
    return "".join(out), applied


def fix_text(text: str, distro: str | None = None, path: str = "<string>", config: Config | None = None) -> tuple[str, int, Result]:
    """Apply fixes until none are left (overlapping fixes need another pass). Returns (text, fixes, final result)."""
    total = 0
    for _ in range(10):
        res = lint_text(text, distro, path, config)
        text, n = apply_fixes(text, res.findings)
        total += n
        if n == 0:
            return text, total, res
    return text, total, lint_text(text, distro, path, config)
