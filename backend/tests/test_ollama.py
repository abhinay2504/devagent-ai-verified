from app.services.ollama import check_ollama


def test_model_status_returns_tuple():
    available, message = check_ollama()
    assert isinstance(available, bool)
    assert isinstance(message, str)


def test_model_status_does_not_accept_wrong_variant(monkeypatch):
    import json
    from app.config import get_settings
    import app.services.ollama as ollama

    class FakeResponse:
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def read(self):
            return json.dumps({"models": [{"name": "qwen2.5-coder:7b"}]}).encode()

    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5-coder:3b")
    get_settings.cache_clear()
    monkeypatch.setattr(ollama.urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse())
    available, message = ollama.check_ollama()
    assert available is False
    assert "not found" in message
    get_settings.cache_clear()
