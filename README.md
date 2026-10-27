# DevAgent AI

DevAgent AI is a local-first AI software-engineering assistant. It inspects a Python repository, drafts a task plan, proposes a unified diff, pauses for human approval, applies validated changes in a dedicated workspace, and can run tests in a Docker container with network access disabled.

> **Safety note:** Treat generated code and repositories as untrusted. Keep DevAgent pointed at a disposable copy of a project. Docker test execution is the recommended mode. The local subprocess runner is disabled by default and should only be enabled for repositories you trust.

## Features

- Local Ollama model integration (no hosted model API required)
- FastAPI backend and React/Vite/TypeScript dashboard
- SQLite task, event, patch, and test history
- Repository file listing and bounded text-file reading, with common secret files, private keys, and credential directories excluded
- Structured plan and patch generation
- Human approval before changes are applied
- Path validation and patch scope checks; repository/file traversal and symlink-based access are refused
- Docker-based pytest runner with network disabled, a read-only container/workspace, resource limits, dropped capabilities, bounded output capture, and timeout cleanup
- Repair proposals are approval-gated and capped by `DEVAGENT_MAX_REPAIR_ATTEMPTS` (default: 3 per task); failed tests never trigger silent edits
- Task-relevant repository context selection that never creates a patch from a truncated file
- Startup recovery for tasks interrupted during planning, plus atomic status claims against duplicate start/repair requests
- Tests for core safety, database, API, and patch behavior

## Architecture

```text
React UI -> FastAPI -> SQLite task/event store
                  -> Ollama adapter
                  -> repository reader / diff validator
                  -> human approval gate
                  -> validated patch application
                  -> Docker test runner (network disabled)
```

The first release deliberately focuses on Python repositories and one proposed patch per approval cycle. It can modify existing files only; creating, deleting, or renaming files is not supported yet. It does not run arbitrary shell commands, install packages automatically, push to GitHub, or modify a repository without approval.

## Requirements

- Windows 10/11, macOS, or Linux
- Python 3.11+ (Python 3.12 recommended)
- Node.js 20+ and npm (for the dashboard)
- Ollama for local model inference
- Docker Desktop / Docker Engine for isolated test execution (recommended and required for the Docker runner)

Ollama models can require several GB of storage and RAM. Start by checking your available memory before pulling a model. A small model may run on modest hardware but code quality and speed vary. See https://ollama.com/library for current models and https://ollama.com/download for installation.

## Quick start (Windows PowerShell)

1. Install Python, Node.js, Ollama, and Docker Desktop if you want isolated test execution.
2. Install and start Ollama. In a new PowerShell terminal, check `ollama --version` and `ollama list`. If the Python virtual-environment activation is blocked by PowerShell policy, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that terminal and activate again.
3. Pull a small model only after checking your machine's memory. Example: `ollama pull qwen2.5-coder:3b`. This is an example, not a guarantee that it will fit or perform well on every PC.
4. From the project root:

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

5. In another terminal, start the frontend:

```powershell
cd frontend
npm ci
npm run dev
```

6. Open the Vite URL shown in the terminal (usually http://localhost:5173). API docs are at http://127.0.0.1:8000/docs.

The included demo repository lives at `workspace/sample-python-project`. Configure `DEVAGENT_WORKSPACE_ROOT` to the absolute path of the `workspace` directory. On Windows PowerShell, for the current terminal:

```powershell
$env:DEVAGENT_WORKSPACE_ROOT = (Resolve-Path ..\workspace).Path
```

Set the same variable before starting the backend. The default in `.env.example` is `../workspace` relative to the backend directory.

## First workflow

1. Open the dashboard and create a task. Use the demo repository path `sample-python-project` (relative to the workspace root).
2. Enter a focused task, e.g. `Add a function called is_even(number) with unit tests.`
3. Start the task. The agent inspects the repository and proposes a patch. Ollama must be running and the configured model must be installed.
4. Review the diff and approve or reject it.
5. If approved, the patch is applied to the workspace. Run tests from the task page. Docker must be available for the isolated runner. Build the runner image once from the project root with `docker build -t devagent-ai-test-runner:latest sandbox` before running tests. If tests fail, use **Propose repair** to ask the agent for a new patch; review and approve that patch separately.
6. Inspect the test output and Git diff. Revert the workspace with Git if needed.

## Configuration

Copy `backend/.env.example` to `backend/.env` and adjust:

- `DEVAGENT_WORKSPACE_ROOT`: only directory tree the agent may read/write
- `DEVAGENT_DATABASE_PATH`: SQLite database path
- `OLLAMA_BASE_URL`: default `http://localhost:11434`
- `OLLAMA_MODEL`: model tag available in `ollama list`
- `DEVAGENT_DOCKER_IMAGE`: default `devagent-ai-test-runner:latest`
- `DEVAGENT_MAX_PATCH_BYTES`: maximum patch size
- `DEVAGENT_MAX_TEST_SECONDS`: test timeout
- `DEVAGENT_MAX_REPAIR_ATTEMPTS`: maximum manual repair proposals per task (default: 3)
- `DEVAGENT_ENABLE_LOCAL_TEST_RUNNER`: defaults to `false`; do not enable for untrusted code

Never commit `.env`, credentials, private repositories, or generated test data. `.gitignore` excludes common secrets and local state.

## Development and tests

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
pytest -q
ruff check app tests
```

Frontend checks:

```powershell
cd frontend
npm ci
npm run build
```

Tests that contact Ollama or require Docker are not part of the default unit suite. Those services must be verified separately on your computer.

## Security limitations

- Docker improves isolation but is not a perfect security boundary. Keep Docker updated and do not mount sensitive directories. The included test-runner image must be built once with `docker build -t devagent-ai-test-runner:latest sandbox`. It contains pytest and the Python standard library only; projects requiring third-party runtime packages need a separately reviewed test image. Dependencies are not installed automatically.
- The patch validator restricts paths and patch/file size, validates unified-diff hunk counts, preserves line endings, and stages writes before replacement; it still cannot prove a code change is correct.
- Common credential directories including `.config`, `.terraform`, `credentials`, and `secrets`, along with common secret files such as `.envrc` and `.git-credentials`, are excluded from agent access. This is a denylist, not a guarantee that every secret format is detected.
- Files that do not fit completely within the model context budget are not supplied as editable context. Context selection prioritizes paths matching the task description and avoids generating full-file replacements from truncated source.
- The test runner disables pytest plugin autoload and includes only pytest plus the Python standard library. Projects needing additional packages or pytest plugins require a separately reviewed runner image; dependencies are never installed automatically.
- Test execution is only exposed as a fixed `python -m pytest -q` command, not arbitrary shell access. Docker startup/command failures are reported as runner errors rather than being sent to the code-repair flow.
- Do not point this application at your home directory, production systems, or repositories containing secrets.
- This is a portfolio-grade prototype, not a hardened multi-user production service. It has no authentication by default; bind it to localhost and do not expose it to the public internet.

## GitHub publishing

Review the repository for secrets, test it locally, then:

```bash
git init
git add .
git status
git commit -m "Initial DevAgent AI implementation"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/devagent-ai.git
git push -u origin main
```

Create the empty GitHub repository yourself first. Do not include `.env`, `.venv`, `node_modules`, SQLite databases, or private source code.
