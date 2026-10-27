# DevAgent AI

DevAgent AI is a local-first AI software-engineering assistant. It inspects a Python repository, drafts a task plan, proposes a unified diff, pauses for human approval, applies validated changes in a dedicated workspace, and can run tests in a Docker container with network access disabled.

> **Safety note:** Treat generated code and repositories as untrusted. Keep DevAgent pointed at a disposable copy of a project. Docker test execution is the recommended mode. The local subprocess runner is disabled by default and should only be enabled for repositories you trust.

## Features

- Local Ollama model integration
- FastAPI backend and React/Vite/TypeScript dashboard
- SQLite task, event, patch, and test history
- Repository inspection and bounded text-file reading
- Structured plan and patch generation with human approval
- Validated patch application and Docker-based pytest runner

## Requirements

- Python 3.11+
- Node.js 20+ and npm
- Ollama with a compatible local model
- Docker Desktop / Docker Engine for isolated test execution

## Quick start (Windows PowerShell)

Backend:

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

Frontend (another terminal):

```powershell
cd frontend
npm ci
npm run dev
```

Open the Vite URL shown in the terminal (usually http://localhost:5173). API docs are at http://127.0.0.1:8000/docs.

## Demo workflow

The included demo repository lives at `workspace/sample-python-project`. Configure `DEVAGENT_WORKSPACE_ROOT` to the absolute path of the `workspace` directory. Build the Docker test runner from the repository root:

```powershell
docker build -t devagent-ai-test-runner:latest sandbox
```

Create a task, review the plan and diff, approve the patch, and run the tests.

## Security

Do not commit `.env`, credentials, virtual environments, `node_modules`, SQLite databases, or generated test data. Docker improves isolation but is not a perfect security boundary. Keep the application bound to localhost and do not expose this prototype to the public internet.
