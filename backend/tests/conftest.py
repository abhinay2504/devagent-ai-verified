import pytest


@pytest.fixture
def test_environment(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    repo = workspace / "demo"
    repo.mkdir(parents=True)
    (repo / "example.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (repo / "test_example.py").write_text("from example import add\n\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8")
    monkeypatch.setenv("DEVAGENT_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("DEVAGENT_DATABASE_PATH", str(tmp_path / "test.sqlite3"))
    monkeypatch.setenv("OLLAMA_MODEL", "test-model")
    from app.config import get_settings
    get_settings.cache_clear()
    from app import db
    db.init_db()
    yield workspace, repo
    get_settings.cache_clear()
