import json

from app import agents


def test_propose_files_retries_when_model_returns_empty_files(monkeypatch):
    calls = []
    responses = [
        {"summary": "subtract.py already exists", "files": []},
        {"summary": "Add subtract to math_utils.py", "files": [{"path": "math_utils.py", "content": "def subtract(a, b):\n    return a - b\n"}]},
    ]

    def fake_chat_json(system_prompt, user_prompt):
        calls.append((system_prompt, json.loads(user_prompt)))
        return responses.pop(0)

    monkeypatch.setattr(agents, "chat_json", fake_chat_json)
    result = agents.propose_files(
        "Add subtract(a, b)",
        [{"step": "Inspect existing module", "validation": "Review diff"}],
        ["math_utils.py", "test_math_utils.py"],
        {"math_utils.py": "def add(a, b):\n    return a + b\n", "test_math_utils.py": ""},
    )

    assert len(calls) == 2
    assert "correcting a failed code-edit proposal" in calls[1][0]
    assert result["files"][0]["path"] == "math_utils.py"
    assert "subtract" in result["files"][0]["content"]


def test_propose_files_keeps_empty_result_if_corrective_retry_also_empty(monkeypatch):
    monkeypatch.setattr(
        agents,
        "chat_json",
        lambda *_args: {"summary": "No edit needed", "files": []},
    )
    result = agents.propose_files("Do a task", [], ["main.py"], {"main.py": ""})
    assert result["files"] == []
