import json
import urllib.error
import urllib.request

from app.config import get_settings


class OllamaError(RuntimeError):
    pass


def check_ollama() -> tuple[bool, str]:
    settings = get_settings()
    url = settings.ollama_base_url.rstrip("/") + "/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        models = [m.get("name", "") for m in payload.get("models", [])]
        configured = settings.ollama_model
        available = any(
            name == configured or (":" not in configured and name.split(":")[0] == configured)
            for name in models
        )
        if available:
            return True, f"Ollama is reachable and model '{configured}' appears installed."
        return False, f"Ollama is reachable, but '{configured}' was not found. Run: ollama pull {configured}"
    except Exception as exc:
        return False, f"Cannot reach Ollama at {url}. Start Ollama and check the URL. Details: {exc}"


def chat_json(system_prompt: str, user_prompt: str) -> dict:
    settings = get_settings()
    url = settings.ollama_base_url.rstrip("/") + "/api/chat"
    payload = {
        "model": settings.ollama_model,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "options": {"temperature": 0.1},
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.ollama_timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
        content = data.get("message", {}).get("content", "")
        result = json.loads(content)
        if not isinstance(result, dict):
            raise ValueError("Model output must be a JSON object")
        return result
    except urllib.error.URLError as exc:
        raise OllamaError(f"Could not connect to Ollama. Is it running? {exc}") from exc
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        raise OllamaError(f"Ollama returned invalid JSON. Try another model or simplify the task. {exc}") from exc
    except TimeoutError as exc:
        raise OllamaError("Ollama request timed out. Try a smaller model or increase the timeout.") from exc
