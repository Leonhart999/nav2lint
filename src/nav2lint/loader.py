"""YAML loader that keeps line numbers.

PyYAML's safe_load drops line numbers and silently overwrites duplicate keys.
This walks the composed node tree directly, keeping a line number for every value and recording duplicates.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import yaml


class _Loader(yaml.SafeLoader):
    """SafeLoader subclass that only changes float resolution."""


# YAML 1.1 requires a dot in floats, so PyYAML reads 1e-10 as a string.
# ROS 2's rcl_yaml_param_parser reads it as a double; match ROS 2 here.
_FLOAT_RE = re.compile(
    r"""^(?:[-+]?(?:[0-9][0-9_]*)\.[0-9_]*(?:[eE][-+]?[0-9]+)?
    |[-+]?(?:[0-9][0-9_]*)(?:[eE][-+]?[0-9]+)
    |\.[0-9_]+(?:[eE][-+][0-9]+)?
    |[-+]?\.(?:inf|Inf|INF)
    |\.(?:nan|NaN|NAN))$""",
    re.X,
)
_Loader.yaml_implicit_resolvers = {
    k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:float"]
    for k, v in _Loader.yaml_implicit_resolvers.items()
}
_Loader.add_implicit_resolver("tag:yaml.org,2002:float", _FLOAT_RE, list("-+0123456789."))


@dataclass
class Node:
    """A YAML value and its 1-based line number.

    For mappings `value` is dict[str, Node], for sequences list[Node],
    for scalars the plain Python value.
    """

    value: Any
    line: int
    kind: str  # "map" | "seq" | "scalar"
    key_lines: dict[str, int] = field(default_factory=dict)

    def get(self, key: str) -> "Node | None":
        if self.kind != "map":
            return None
        return self.value.get(key)

    def plain(self) -> Any:
        """Strip line numbers and return plain Python objects."""
        if self.kind == "map":
            return {k: v.plain() for k, v in self.value.items()}
        if self.kind == "seq":
            return [v.plain() for v in self.value]
        return self.value


@dataclass
class Duplicate:
    key: str
    line: int
    first_line: int


def load(text: str) -> tuple[Node | None, list[Duplicate]]:
    """Parse YAML text and return (root, duplicates). Raises yaml.YAMLError on syntax errors."""
    loader = _Loader(text)
    try:
        root = loader.get_single_node()
        dups: list[Duplicate] = []
        if root is None:
            return None, dups
        return _convert(root, loader, dups), dups
    finally:
        loader.dispose()


def _convert(n: yaml.Node, loader: _Loader, dups: list[Duplicate]) -> Node:
    line = n.start_mark.line + 1
    if isinstance(n, yaml.MappingNode):
        out: dict[str, Node] = {}
        key_lines: dict[str, int] = {}
        for k, v in n.value:
            key = str(loader.construct_object(k, deep=True))
            kline = k.start_mark.line + 1
            if key in out:
                dups.append(Duplicate(key, kline, key_lines[key]))
            out[key] = _convert(v, loader, dups)
            key_lines[key] = kline
        return Node(out, line, "map", key_lines)
    if isinstance(n, yaml.SequenceNode):
        return Node([_convert(v, loader, dups) for v in n.value], line, "seq")
    return Node(loader.construct_object(n, deep=True), line, "scalar")
