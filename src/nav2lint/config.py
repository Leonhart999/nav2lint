"""Project configuration (.nav2lint.yaml) and inline suppression comments.

.nav2lint.yaml, found by walking up from each linted file:

    distro: humble          # used when --distro is not given
    disable: [S301, T404]   # rules to turn off
    severity:               # change the severity of a rule
      P103: warning

Inline comments in a params file:

    use_sim_time: True  # nav2lint: disable=S301         this line
    # nav2lint: disable-next-line=T404                   the next line
    # nav2lint: disable-file=S305                        the whole file
    # nav2lint: disable                                  without "=": all rules
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from .rules import RULE_IDS, SEVERITIES, WARNING, Finding
from .schema import DISTROS

CONFIG_NAMES = (".nav2lint.yaml", ".nav2lint.yml")
ALL = "*"


class ConfigError(Exception):
    pass


@dataclass
class Config:
    path: Path | None = None
    distro: str | None = None
    disable: set[str] = field(default_factory=set)
    severity: dict[str, str] = field(default_factory=dict)


def _rule_list(value, where: str) -> set[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{where}: expected a list of rule IDs")
    bad = [v for v in value if v not in RULE_IDS]
    if bad:
        raise ConfigError(f"{where}: unknown rule ID(s) {', '.join(bad)}")
    return set(value)


def load_config(path: Path) -> Config:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as e:
        raise ConfigError(f"{path}: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: expected a mapping")
    unknown = set(raw) - {"distro", "disable", "severity"}
    if unknown:
        raise ConfigError(f"{path}: unknown key(s) {', '.join(sorted(unknown))}; expected distro, disable, severity")
    cfg = Config(path=path)
    if "distro" in raw:
        if raw["distro"] not in (*DISTROS, "auto"):
            raise ConfigError(f"{path}: distro must be one of {', '.join(DISTROS)} or auto")
        cfg.distro = raw["distro"]
    if "disable" in raw:
        cfg.disable = _rule_list(raw["disable"], f"{path}: disable")
    sev = raw.get("severity") or {}
    if not isinstance(sev, dict):
        raise ConfigError(f"{path}: severity must map rule IDs to error/warning/info")
    for rule, level in sev.items():
        _rule_list([rule], f"{path}: severity")
        if level not in SEVERITIES:
            raise ConfigError(f"{path}: severity of {rule} must be error, warning or info")
        cfg.severity[rule] = level
    return cfg


@lru_cache(maxsize=None)
def _config_in(directory: Path) -> Config | None:
    for name in CONFIG_NAMES:
        p = directory / name
        if p.is_file():
            return load_config(p)
    parent = directory.parent
    return None if parent == directory else _config_in(parent)


def find_config(file: Path) -> Config | None:
    """Nearest .nav2lint.yaml in the file's directory or any parent."""
    return _config_in(file.resolve().parent)


# ---------- inline suppression ----------

_DIRECTIVE = re.compile(
    r"#\s*nav2lint:\s*(disable-file|disable-next-line|disable)\b(?:\s*=\s*([A-Za-z]\d{3}(?:\s*,\s*[A-Za-z]\d{3})*))?"
)


@dataclass
class Suppressions:
    file: set[str] = field(default_factory=set)
    lines: dict[int, set[str]] = field(default_factory=dict)
    problems: list[Finding] = field(default_factory=list)  # malformed directives

    def hides(self, f: Finding) -> bool:
        rules = self.file | self.lines.get(f.line, set())
        return ALL in rules or f.rule in rules


def parse_suppressions(lines: list[str]) -> Suppressions:
    out = Suppressions()
    for i, text in enumerate(lines, 1):
        m = _DIRECTIVE.search(text)
        if not m:
            continue
        kind, ids = m.group(1), m.group(2)
        rules = {ALL} if ids is None else {r.upper() for r in re.split(r"[\s,]+", ids) if r}
        bad = sorted(r for r in rules - {ALL} if r not in RULE_IDS)
        if bad:
            out.problems.append(Finding("N005", WARNING, i, f"unknown rule ID(s) in nav2lint comment: {', '.join(bad)}"))
            rules -= set(bad)
        if kind == "disable-file":
            out.file |= rules
        else:
            target = i + 1 if kind == "disable-next-line" else i
            out.lines.setdefault(target, set()).update(rules)
    return out
