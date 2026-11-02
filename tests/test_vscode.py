import json
import re
import sys
from pathlib import Path

import pytest

from nav2lint.vscode import _parse_jsonc, init_vscode


CHECK = "nav2lint: check current file"
WATCH = "nav2lint: watch workspace"


def write_tasks(workspace, content):
    target = workspace / ".vscode" / "tasks.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    return target


def read_tasks(target):
    return _parse_jsonc(target.read_bytes().decode("utf-8-sig"))[0]


def by_label(data):
    return {task["label"]: task for task in data["tasks"]}


def test_new_workspace_defaults_and_never_executes(tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Initializing tasks must not execute commands")

    monkeypatch.setattr("subprocess.run", unexpected)
    monkeypatch.setattr("subprocess.Popen", unexpected)
    monkeypatch.setattr("os.system", unexpected)
    workspace = tmp_path / "new workspace"
    target = init_vscode(workspace)
    assert target == workspace / ".vscode" / "tasks.json"
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["version"] == "2.0.0"
    tasks = by_label(data)
    assert set(tasks) == {CHECK, WATCH}
    for task in tasks.values():
        assert task["type"] == "process"
        assert task["command"] == sys.executable
        assert task["args"][:2] == ["-m", "nav2lint"]
        assert task["options"] == {"cwd": "${workspaceFolder}"}
        assert "runOptions" not in task
        assert "windows" not in task and "linux" not in task
        assert task["problemMatcher"]["fileLocation"] == ["autoDetect", "${workspaceFolder}"]
    assert tasks[CHECK]["args"] == ["-m", "nav2lint", "--format", "line", "${file}"]
    assert tasks[WATCH]["args"] == [
        "-m", "nav2lint", "--watch", "--format", "line", "${workspaceFolder}"
    ]
    assert tasks[WATCH]["isBackground"] is True
    assert "background" not in tasks[CHECK]["problemMatcher"]
    assert tasks[WATCH]["problemMatcher"]["background"] == {
        "activeBegin": True,
        "beginsPattern": "^nav2lint: checking",
        "endsPattern": "^nav2lint: done",
    }


@pytest.mark.parametrize("python", ["python3", "/opt/env with spaces/bin/python", r"X:\env with spaces\python.exe"])
def test_explicit_python_is_one_process_command(tmp_path, python):
    tasks = read_tasks(init_vscode(tmp_path, python=python))["tasks"]
    assert all(task["command"] == python for task in tasks)
    assert all(python not in task["args"] for task in tasks)


@pytest.mark.parametrize("python", ["", "   ", "python\0extra", 123])
def test_invalid_python_does_not_change_existing_file(tmp_path, python):
    target = write_tasks(tmp_path, b'{"tasks": []}')
    with pytest.raises(ValueError, match="Python executable"):
        init_vscode(tmp_path, python=python)
    assert target.read_bytes() == b'{"tasks": []}'


def test_merge_keeps_custom_task_and_top_level_settings(tmp_path):
    custom = {"label": CHECK, "type": "shell", "command": "custom-check", "custom": {"keep": True}}
    original = {
        "version": "2.0.0",
        "tasks": [custom, {"label": "build", "command": "build-tool"}],
        "inputs": [{"id": "mode", "type": "promptString", "description": "Mode"}],
        "presentation": {"reveal": "never"},
        "custom": {"nested": [1, False, None]},
    }
    target = write_tasks(tmp_path, json.dumps(original, indent=4))
    result = read_tasks(init_vscode(tmp_path, python="new-python"))
    assert result["tasks"][1:] == original["tasks"]
    assert by_label(result)[CHECK] == custom
    assert by_label(result)[WATCH]["command"] == "new-python"
    assert {key: value for key, value in result.items() if key != "tasks"} == {
        key: value for key, value in original.items() if key != "tasks"
    }
    assert target.read_text(encoding="utf-8").count('"custom-check"') == 1


@pytest.mark.parametrize("existing", ["check", "watch", "both"])
def test_existing_nav2lint_tasks_are_never_overwritten(tmp_path, existing):
    labels = [CHECK, WATCH] if existing == "both" else [CHECK if existing == "check" else WATCH]
    custom = [{"label": label, "command": "custom", "runOptions": {"runOn": "folderOpen"}} for label in labels]
    target = write_tasks(tmp_path, json.dumps({"tasks": custom}))
    original = target.read_bytes()
    result = read_tasks(init_vscode(tmp_path, python="python-new"))
    for task in custom:
        assert by_label(result)[task["label"]] == task
    assert len(result["tasks"]) == 2
    if existing == "both":
        assert target.read_bytes() == original


def test_idempotent_does_not_even_replace_file(tmp_path, monkeypatch):
    target = init_vscode(tmp_path)
    original = target.read_bytes()

    def unexpected(*args, **kwargs):
        pytest.fail("An unchanged tasks file must not be rewritten")

    monkeypatch.setattr("nav2lint.vscode.os.replace", unexpected)
    assert init_vscode(tmp_path, python="different-python") == target
    assert target.read_bytes() == original


@pytest.mark.parametrize("content", [
    '{}',
    '{ /* empty */ }',
    '{"tasks": []}',
    '{"tasks": [ /* tasks go here */ ]}',
    '{"inputs": [],}',
    '{"version": "2.0.0", "tasks": [],}',
    '{"tasks": [{"label": "build",},], "inputs": [1, 2,],}',
    '{"other": {"tasks": ["nested"],}, "tasks": []}',
    '{"version": "2.0.0", "note": "tasks", "tasks": [], "tail": true}',
    '// leading comment\n{"tasks": []} /* final comment */',
    '{"inputs": [{"id": "a", "default": "tasks: ["}], "tasks": []}',
    '{"tasks": [{"label": "build"}, /* comment after trailing comma */ ],}',
])
def test_jsonc_merge_shapes(tmp_path, content):
    write_tasks(tmp_path, content)
    original = _parse_jsonc(content)[0]
    target = init_vscode(tmp_path)
    result = read_tasks(target)
    assert {CHECK, WATCH} <= set(by_label(result))
    for key, value in original.items():
        if key != "tasks":
            assert result[key] == value
    assert result["tasks"][2:] == original.get("tasks", [])
    merged = target.read_bytes()
    init_vscode(tmp_path)
    assert target.read_bytes() == merged


def test_jsonc_keeps_comments_strings_bom_and_crlf(tmp_path):
    special = 'https://example.test/a//b/*not a comment*/,] } \\" // still a string\n\u6c49\u5b57'
    content = (
        '{\r\n'
        '  // keep this URL: https://example.test\r\n'
        '  "note": ' + json.dumps(special, ensure_ascii=False) + ',\r\n'
        '  "tasks": [\r\n'
        '    /* keep this task */\r\n'
        '    {"label": "build", "args": ["//", "/*", ",]", "\\\\", "\\\""],}, // keep tail\r\n'
        '  ],\r\n'
        '  "custom": {"tasks": [],}, /* keep nested */\r\n'
        '} // final comment\r\n'
    )
    original_data = _parse_jsonc(content)[0]
    target = write_tasks(tmp_path, b"\xef\xbb\xbf" + content.encode("utf-8"))
    init_vscode(tmp_path)
    output = target.read_bytes()
    assert output.startswith(b"\xef\xbb\xbf")
    assert b"\n" not in output.replace(b"\r\n", b"")
    result = read_tasks(target)
    assert result["note"] == special
    assert result["tasks"][2:] == original_data["tasks"]
    assert result["custom"] == original_data["custom"]
    for fragment in [
        '// keep this URL: https://example.test',
        '/* keep this task */', '// keep tail', '/* keep nested */', '// final comment',
        '{"label": "build", "args": ["//", "/*", ",]", "\\\\", "\\\""],},',
    ]:
        assert fragment.encode("utf-8") in output


@pytest.mark.parametrize("content", [
    b'', b'   ', b'[]', b'null', b'{broken}', b'{"tasks": []} extra',
    b'{"tasks": {}}', b'{"tasks": null}', b'{"tasks": [1]}',
    b'{"tasks": [{"label": []}]}', b'{"tasks": [{"label": null}]}',
    b'{"version": "0.1.0", "tasks": []}',
    b'{"tasks": [], "tasks": []}', b'{"custom": {"same": 1, "same": 2}}',
    b'{"custom": NaN}', b'{"custom": Infinity}', b'{"custom": -Infinity}',
    b'{"tasks": [], /* never closed}', b'{"tasks": [/*]*/}',
    b'{"tasks": ["unterminated]}', b'{"tasks": [,]}',
    b'{"tasks": [],,}', b'{"tasks": [1,,]}', b'{,}',
    b'{"tasks": [], "custom": {,}}', b'{"tasks": [], "custom": [/* comment */,]}',
    b'{"tasks": [], "custom": "bad\\escape"}', b'{"tasks": [], "custom": "bad\nstring"}',
    b'{"tasks": []}\xff',
    b'{"tasks": [{"label": "nav2lint: check current file"}, {"label": "nav2lint: watch workspace"}], "bad": NaN}',
])
def test_unsafe_files_rejected_without_changing_any_bytes(tmp_path, content):
    target = write_tasks(tmp_path, content)
    before = target.stat().st_mtime_ns
    with pytest.raises(ValueError, match="Cannot safely initialize VS Code tasks") as error:
        init_vscode(tmp_path)
    assert str(target) in str(error.value)
    assert target.read_bytes() == content
    assert target.stat().st_mtime_ns == before
    assert list(target.parent.iterdir()) == [target]


def test_atomic_write_failure_keeps_original(tmp_path, monkeypatch):
    target = write_tasks(tmp_path, b'{"tasks": []}')

    def fail_replace(*args, **kwargs):
        raise OSError("Simulated write failure")

    monkeypatch.setattr("nav2lint.vscode.os.replace", fail_replace)
    with pytest.raises(ValueError, match="Simulated write failure"):
        init_vscode(tmp_path)
    assert target.read_bytes() == b'{"tasks": []}'
    assert list(target.parent.iterdir()) == [target]


def test_missing_tasks_member_preserves_existing_text(tmp_path):
    content = '{\n  // Keep input settings exactly.\n  "inputs": [{"id":"url","default":"https://example.test//a"}],\n}\n'
    target = write_tasks(tmp_path, content)
    init_vscode(tmp_path)
    output = target.read_text(encoding="utf-8")
    assert output.endswith(content[1:])
    assert read_tasks(target)["inputs"] == _parse_jsonc(content)[0]["inputs"]


def test_workspace_file_is_reported_clearly(tmp_path):
    workspace = tmp_path / "not-a-folder"
    workspace.write_bytes(b"keep")
    with pytest.raises(ValueError, match="Cannot safely initialize VS Code tasks"):
        init_vscode(workspace)
    assert workspace.read_bytes() == b"keep"


def test_line_matcher_handles_windows_paths(tmp_path):
    task = read_tasks(init_vscode(tmp_path))["tasks"][0]
    pattern = task["problemMatcher"]["pattern"]
    for severity in ["error", "warning", "info"]:
        match = re.match(pattern["regexp"], rf"X:\robot workspace\nav.yaml:42: {severity}[T404] Unknown parameter")
        assert match is not None
        assert match.group(pattern["file"]) == r"X:\robot workspace\nav.yaml"
        assert match.group(pattern["line"]) == "42"
        assert match.group(pattern["severity"]) == severity
        assert match.group(pattern["code"]) == "T404"
        assert match.group(pattern["message"]) == "Unknown parameter"


def test_template_matches_generated_tasks_without_machine_paths(tmp_path):
    template = Path(__file__).resolve().parents[1] / "editors" / "vscode" / "tasks.json"
    text = template.read_text(encoding="utf-8")
    expected = _parse_jsonc(text)[0]
    generated = read_tasks(init_vscode(tmp_path, python="python"))
    assert generated == expected
    assert "D:/" not in text and "/mnt/d/" not in text and "PYTHONPATH" not in text
    assert "python.defaultInterpreterPath" in text
    assert all("runOptions" not in task for task in expected["tasks"])
