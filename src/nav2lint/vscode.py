"""Create opt-in VS Code tasks without running commands or changing user tasks."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


def _tasks(python: str) -> list[dict]:
    def matcher() -> dict:
        return {
            "owner": "nav2lint",
            "source": "nav2lint",
            "fileLocation": ["autoDetect", "${workspaceFolder}"],
            "pattern": {
                "regexp": r"^(.*):(\d+): (error|warning|info)\[(\w+)\] (.*)$",
                "file": 1,
                "line": 2,
                "severity": 3,
                "code": 4,
                "message": 5,
            },
        }

    check = {
        "label": "nav2lint: check current file",
        "type": "process",
        "command": python,
        "args": ["-m", "nav2lint", "--format", "line", "${file}"],
        "options": {"cwd": "${workspaceFolder}"},
        "presentation": {"reveal": "silent", "clear": True},
        "problemMatcher": matcher(),
    }
    watch = {
        "label": "nav2lint: watch workspace",
        "type": "process",
        "command": python,
        "args": ["-m", "nav2lint", "--watch", "--format", "line", "${workspaceFolder}"],
        "options": {"cwd": "${workspaceFolder}"},
        "isBackground": True,
        "presentation": {"reveal": "never"},
        "problemMatcher": matcher(),
    }
    watch["problemMatcher"]["background"] = {
        "activeBegin": True,
        "beginsPattern": "^nav2lint: checking",
        "endsPattern": "^nav2lint: done",
    }
    return [check, watch]


def _unique_object(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError(f"Non-JSON numeric constant: {value}")


def _parse_jsonc(text: str) -> tuple[dict, str]:
    """Mask comments/trailing commas, preserving offsets and string contents."""
    chars = list(text)
    i = 0
    tokens = []
    while i < len(text):
        char = text[i]
        if char == '"':
            tokens.append((char, i))
            i += 1
            while i < len(text):
                if text[i] == "\\":
                    i += 2
                elif text[i] == '"':
                    i += 1
                    break
                else:
                    i += 1
        elif text.startswith("//", i) or text.startswith("/*", i):
            start = i
            if text[i + 1] == "/":
                while i < len(text) and text[i] not in "\r\n":
                    i += 1
            else:
                end = text.find("*/", i + 2)
                if end == -1:
                    raise ValueError("Unterminated JSONC block comment")
                i = end + 2
            for pos in range(start, i):
                if chars[pos] not in "\r\n":
                    chars[pos] = " "
        else:
            if char not in " \t\r\n":
                tokens.append((char, i))
            i += 1

    for index, (char, pos) in enumerate(tokens[:-1]):
        if char == "," and tokens[index + 1][0] in "]}":
            # An empty array/object with a comma is not valid JSONC.
            if index == 0 or tokens[index - 1][0] in "[{,:":
                raise ValueError("Invalid JSONC trailing comma")
            chars[pos] = " "
    cleaned = "".join(chars)
    data = json.loads(
        cleaned, object_pairs_hook=_unique_object, parse_constant=_invalid_constant
    )
    if not isinstance(data, dict):
        raise ValueError("The tasks file must contain a JSON object")
    if "version" in data and data["version"] != "2.0.0":
        raise ValueError('The tasks file version must be "2.0.0"')
    tasks = data.get("tasks", [])
    if not isinstance(tasks, list) or any(not isinstance(task, dict) for task in tasks):
        raise ValueError('The "tasks" setting must be an array of objects')
    if any("label" in task and not isinstance(task["label"], str) for task in tasks):
        raise ValueError("Task labels must be strings")
    return data, cleaned


def _value_start(cleaned: str, key: str) -> int:
    """Locate a validated top-level member without matching strings or comments."""
    decoder = json.JSONDecoder()
    pos = cleaned.index("{") + 1
    while True:
        while cleaned[pos] in " \t\r\n,":
            pos += 1
        name, pos = decoder.raw_decode(cleaned, pos)
        while cleaned[pos] in " \t\r\n:":
            pos += 1
        if name == key:
            return pos
        _, pos = decoder.raw_decode(cleaned, pos)


def _merge(text: str, tasks: list[dict]) -> str:
    data, cleaned = _parse_jsonc(text)
    labels = {task.get("label") for task in data.get("tasks", [])}
    missing = [task for task in tasks if task["label"] not in labels]
    if not missing:
        return text
    newline = "\r\n" if "\r\n" in text else "\n"
    members = {}
    if "version" not in data:
        members["version"] = "2.0.0"
    if "tasks" in data:
        # Prepend only missing tasks: existing text, including comments, stays intact.
        pos = _value_start(cleaned, "tasks") + 1
        rendered = ",\n".join(
            "\n".join("    " + line for line in json.dumps(task, indent=2).splitlines())
            for task in missing
        )
        insertion = "\n" + rendered + ("," if data["tasks"] else "") + "\n"
        text = text[:pos] + insertion.replace("\n", newline) + text[pos:]
    else:
        members["tasks"] = missing
    if members:
        pos = cleaned.index("{") + 1
        insertion = json.dumps(members, indent=2)[1:-1].rstrip()
        insertion += ("," if data else "") + "\n"
        text = text[:pos] + insertion.replace("\n", newline) + text[pos:]
    # Validate the complete proposed document before any filesystem changes.
    _parse_jsonc(text)
    return text


def init_vscode(workspace: Path, python: str | None = None) -> Path:
    """Return workspace/.vscode/tasks.json after adding missing nav2lint tasks.

    The default executable is sys.executable; an explicit executable may be a
    path or a command on PATH. It must have nav2lint installed. Tasks use this
    command, not VS Code's selected Python interpreter; rerun with an explicit
    executable to select one when first creating tasks. Existing tasks with the
    same labels are never changed, even if a different executable is supplied.

    JSONC comments, trailing commas, BOM and existing text are retained. Invalid
    UTF-8, ambiguous duplicate keys, unsupported versions and invalid task-list
    structures raise ValueError without changing the original bytes. Writes are
    atomic. Tasks are never executed or configured to run on folder open.
    """
    executable = sys.executable if python is None else python
    if not isinstance(executable, str) or not executable.strip() or "\0" in executable:
        raise ValueError("The Python executable must be a non-empty string without NUL characters")
    target = Path(workspace) / ".vscode" / "tasks.json"
    temporary = None
    try:
        if target.is_symlink():
            raise ValueError(f"Refusing to replace a symbolic link: {target}")
        original = target.read_bytes() if target.exists() else None
        bom = b"\xef\xbb\xbf" if original is not None and original.startswith(b"\xef\xbb\xbf") else b""
        text = original.decode("utf-8-sig") if original is not None else "{}\n"
        merged = _merge(text, _tasks(executable))
        output = bom + merged.encode("utf-8")
        if output == original:
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".nav2lint-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(output)
        if original is not None:
            temporary.chmod(target.stat().st_mode)
        os.replace(temporary, target)
        return target
    except (OSError, ValueError, RecursionError) as exc:
        raise ValueError(f"Cannot safely initialize VS Code tasks at {target}: {exc}") from exc
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
