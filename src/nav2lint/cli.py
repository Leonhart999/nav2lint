"""Command line: nav2lint [--distro humble] [--format text|json|line] [--strict] [--watch] [--fix|--diff] PATH..."""
from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
import time
from pathlib import Path

from . import __version__
from .config import CONFIG_NAMES, Config, ConfigError, _config_in, find_config, load_config
from .lint import NotUtf8, Result, fix_text, lint_text, read_text
from .loader import load
from .rules import ERROR, INFO, WARNING
from .schema import DISTROS, find_nodes, nav2_nodes

_COLORS = {ERROR: "\033[31m", WARNING: "\033[33m", INFO: "\033[36m"}
_SKIP_DIRS = {"build", "install", "log", "node_modules", "__pycache__"}

# Markers for the VS Code background problem matcher (see editors/vscode/tasks.json).
WATCH_BEGIN = "nav2lint: checking"
WATCH_END = "nav2lint: done"


def looks_like_nav2(path: Path) -> bool:
    """True if the file has a ros__parameters section for a Nav2 node."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    if "ros__parameters" not in text:
        return False
    try:
        root, _ = load(text)
    except Exception:  # broken YAML still deserves a report if it mentions Nav2 nodes
        return any(f"{n}:" in text for n in nav2_nodes())
    return any(s.name in nav2_nodes() for s in find_nodes(root))


_nav2_cache: dict[Path, tuple[float, bool]] = {}


def _is_nav2_cached(path: Path) -> bool:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return False
    hit = _nav2_cache.get(path)
    if hit is None or hit[0] != mtime:
        hit = (mtime, looks_like_nav2(path))
        _nav2_cache[path] = hit
    return hit[1]


def collect(paths: list[str]) -> list[Path]:
    """Explicit files are always linted; directories contribute their Nav2 parameter files."""
    out: list[Path] = []
    for p in map(Path, paths):
        if not p.is_dir():
            out.append(p)
            continue
        for dirpath, dirnames, filenames in os.walk(p):
            # prune in place so colcon build/install trees are never walked
            dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in _SKIP_DIRS)
            for name in sorted(filenames):
                f = Path(dirpath) / name
                if f.suffix in (".yaml", ".yml") and _is_nav2_cached(f):
                    out.append(f)
    return out


def _print_text(results: list[Result], color: bool, show_info: bool) -> None:
    for r in results:
        if r.distro and r.distro_reason:
            print(f"{r.path}: checking as {r.distro} (detected from: {r.distro_reason})")
        elif r.distro is None and r.distro_reason:
            print(f"{r.path}: could not detect the distro ({r.distro_reason}); skipping migration checks, use --distro to set it")
        for f in r.findings:
            if f.severity == INFO and not show_info:
                continue
            sev = f"{_COLORS[f.severity]}{f.severity}\033[0m" if color else f.severity
            print(f"{r.path}:{f.line}: {sev}[{f.rule}] {f.message}")
            for h in f.hint.splitlines():
                print(f"    {h}")
    print(_summary(results, show_info))


def _print_line(results: list[Result], show_info: bool) -> None:
    """One finding per line with the hint inline, for editors and grep."""
    for r in results:
        for f in r.findings:
            if f.severity == INFO and not show_info:
                continue
            hint = " -- " + " | ".join(f.hint.splitlines()) if f.hint else ""
            print(f"{r.path}:{f.line}: {f.severity}[{f.rule}] {f.message}{hint}")


def _print_json(results: list[Result]) -> None:
    out = [
        {
            "path": r.path,
            "distro": r.distro,
            "distro_reason": r.distro_reason,
            "suppressed": r.suppressed,
            "findings": [
                {"rule": f.rule, "severity": f.severity, "line": f.line, "message": f.message, "hint": f.hint, "fixable": f.fix is not None}
                for f in r.findings
            ],
        }
        for r in results
    ]
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    print()


def _summary(results: list[Result], show_info: bool) -> str:
    counts = {s: sum(f.severity == s for r in results for f in r.findings) for s in (ERROR, WARNING, INFO)}
    hidden = "" if show_info or not counts[INFO] else " (hidden, use --info)"
    out = f"{counts[ERROR]} error, {counts[WARNING]} warning, {counts[INFO]} info{hidden}"
    suppressed = sum(r.suppressed for r in results)
    if suppressed:
        out += f", {suppressed} suppressed"
    fixable = sum(r.fixable for r in results)
    if fixable:
        out += f"; {fixable} fixable with --fix"
    return out


def _config_for(path: Path, args) -> Config | None:
    if args.no_config:
        return None
    if args.config:
        return load_config(Path(args.config))
    return find_config(path)


def _run(files: list[Path], args) -> tuple[list[Result], int]:
    results = []
    for path in files:
        try:
            cfg = _config_for(path, args)
            text = read_text(path)
        except ConfigError as e:
            print(f"config error: {e}", file=sys.stderr)
            return results, 2
        except NotUtf8 as e:
            results.append(e.result())  # reported like any other finding; never rewritten by --fix
            continue
        except OSError as e:
            print(f"{path}: cannot read: {e}", file=sys.stderr)
            return results, 2
        if args.fix or args.diff:
            new, n, res = fix_text(text, args.distro, str(path), cfg)
            if args.diff:
                sys.stdout.writelines(
                    difflib.unified_diff(text.splitlines(keepends=True), new.splitlines(keepends=True), str(path), str(path))
                )
                continue
            if new != text:
                with open(path, "w", encoding="utf-8", newline="") as fh:
                    fh.write(new)
                print(f"{path}: fixed {n} issue(s)", file=sys.stderr)
            results.append(res)
        else:
            results.append(lint_text(text, args.distro, str(path), cfg))
    if args.diff:
        return results, 0
    if args.format == "json":
        _print_json(results)
    elif args.format == "line":
        _print_line(results, args.info)
    else:
        _print_text(results, sys.stdout.isatty() and not args.no_color, args.info)
    bad = {ERROR, WARNING} if args.strict else {ERROR}
    return results, 1 if any(f.severity in bad for r in results for f in r.findings) else 0


def _watch(args) -> int:
    """Re-lint whenever a watched file changes. Each round is framed by WATCH_BEGIN / WATCH_END lines."""
    last: dict[Path, float] | None = None
    try:
        while True:
            _config_in.cache_clear()  # pick up edits to .nav2lint.yaml
            files = collect(args.paths)
            watched = set(files)
            if args.config:
                watched.add(Path(args.config))
            elif not args.no_config:
                for f in files:
                    for d in f.resolve().parents:
                        watched.update(c for c in (d / n for n in CONFIG_NAMES) if c.is_file())
            stamp = {}
            for f in watched:
                try:
                    stamp[f] = f.stat().st_mtime
                except OSError:
                    pass
            if stamp != last:
                last = stamp
                print(f"{WATCH_BEGIN} {len(files)} file(s)", flush=True)
                results, _ = _run(files, args)
                if args.format == "line":
                    print(_summary(results, args.info))
                print(f"{WATCH_END}", flush=True)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="nav2lint", description="Static checker for Nav2 parameter files")
    ap.add_argument("paths", nargs="+", metavar="PATH", help="Nav2 parameter YAML files, or directories to search for them")
    ap.add_argument("--distro", choices=["auto", *DISTROS], help="target ROS 2 distro (default: from .nav2lint.yaml, else auto-detect)")
    ap.add_argument("--format", default="text", choices=["text", "json", "line"], help="line: one finding per line, hint inline")
    ap.add_argument("--strict", action="store_true", help="exit non-zero on warnings too")
    ap.add_argument("--info", action="store_true", help="show info-level findings")
    ap.add_argument("--no-color", action="store_true")
    ap.add_argument("--watch", action="store_true", help="re-check whenever a file changes (Ctrl+C to stop)")
    ap.add_argument("--fix", action="store_true", help="apply safe automatic fixes in place, then report what is left")
    ap.add_argument("--diff", action="store_true", help="print the fixes as a unified diff without changing files")
    ap.add_argument("--config", metavar="FILE", help="use this config file instead of searching for .nav2lint.yaml")
    ap.add_argument("--no-config", action="store_true", help="ignore .nav2lint.yaml files")
    ap.add_argument("--interval", type=float, default=1.0, help=argparse.SUPPRESS)
    ap.add_argument("--version", action="version", version=f"nav2lint {__version__}")
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.watch and (args.fix or args.diff):
        ap.error("--watch cannot be combined with --fix or --diff")
    if args.watch:
        return _watch(args)
    files = collect(args.paths)
    if not files:
        print("no Nav2 parameter files found", file=sys.stderr)
        return 0
    return _run(files, args)[1]
