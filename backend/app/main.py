import json
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.config import get_settings
from app.orchestrator import prepare_task
from app.schemas import ApprovalRequest, TaskCreate
from app.services.ollama import check_ollama
from app.services.patching import PatchError, apply_unified_patch
from app.services.repository import RepositoryError, resolve_repo
from app.services.test_runner import TestRunnerError, run_pytest


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    db.recover_interrupted_tasks()
    get_settings().workspace_root.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="DevAgent AI", version="0.1.0", description="Local-first AI software engineering agent", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "devagent-ai"}


@app.get("/api/model/status")
def model_status():
    available, message = check_ollama()
    return {"available": available, "model": get_settings().ollama_model, "message": message}


@app.get("/api/repositories")
def repositories():
    from app.services.repository import IGNORED_DIRS

    root = get_settings().workspace_root
    root.mkdir(parents=True, exist_ok=True)
    names = [
        path.name for path in root.iterdir()
        if path.is_dir() and not path.is_symlink() and not path.name.startswith(".") and path.name.lower() not in IGNORED_DIRS
    ]
    return {"workspace_root": str(root), "repositories": sorted(names)}


@app.get("/api/repositories/{repo_path:path}/files")
def repository_files(repo_path: str):
    from app.services.repository import list_files
    try:
        return {"files": list_files(repo_path)}
    except RepositoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/tasks", status_code=201)
def create_task(payload: TaskCreate):
    try:
        resolve_repo(payload.repo_path)
    except RepositoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    task = db.create_task_record(str(uuid.uuid4()), payload.description.strip(), payload.repo_path.replace("\\", "/"))
    return task


@app.get("/api/tasks")
def list_tasks():
    return {"tasks": db.list_tasks()}


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str):
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task["plan"] = json.loads(task["plan_json"]) if task.get("plan_json") else []
    task["patches"] = db.get_task_patches(task_id)
    task["test_results"] = db.get_test_results(task_id)
    return task


@app.post("/api/tasks/{task_id}/start")
def start_task(task_id: str):
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] not in {"queued", "failed"}:
        raise HTTPException(status_code=409, detail=f"Task cannot start from status '{task['status']}'.")
    if not db.claim_task_status(task_id, {"queued", "failed"}, "planning"):
        raise HTTPException(status_code=409, detail="Task is already being processed or has changed status.")
    try:
        return prepare_task(task)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/tasks/{task_id}/events")
def task_events(task_id: str):
    if not db.get_task(task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    return {"events": db.get_events(task_id)}


@app.get("/api/tasks/{task_id}/diff")
def task_diff(task_id: str):
    if not db.get_task(task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    return {"patches": db.get_task_patches(task_id)}


@app.post("/api/approvals/{patch_id}")
def decide_patch(patch_id: str, payload: ApprovalRequest):
    patch = db.get_patch(patch_id)
    if not patch:
        raise HTTPException(status_code=404, detail="Patch not found")
    if patch["status"] != "pending":
        raise HTTPException(status_code=409, detail="This patch has already been reviewed or is being processed.")
    task = db.get_task(patch["task_id"])
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] != "awaiting_approval":
        raise HTTPException(status_code=409, detail="This task is not waiting for patch approval.")
    if not payload.approve:
        if not db.claim_patch_status(patch_id, "pending", "rejected"):
            raise HTTPException(status_code=409, detail="This patch has already been reviewed or is being processed.")
        db.set_task_status(task["id"], "rejected")
        db.add_event(task["id"], "patch_rejected", payload.feedback or "Patch rejected by user.")
        return {"status": "rejected"}
    if not db.claim_patch_status(patch_id, "pending", "applying"):
        raise HTTPException(status_code=409, detail="This patch has already been reviewed or is being processed.")
    try:
        repo = resolve_repo(task["repo_path"])
        changed = apply_unified_patch(repo, patch["diff_text"])
    except (RepositoryError, PatchError, OSError) as exc:
        db.update_patch_status(patch_id, "failed")
        db.set_task_status(task["id"], "failed", str(exc)[:2000])
        db.add_event(task["id"], "patch_apply_error", str(exc))
        raise HTTPException(status_code=400, detail=f"Patch was not applied: {exc}") from exc
    db.update_patch_status(patch_id, "applied", applied=True)
    db.set_task_status(task["id"], "applied")
    db.add_event(task["id"], "patch_applied", "Approved patch applied to: " + ", ".join(changed))
    return {"status": "applied", "changed_files": changed}


@app.post("/api/tasks/{task_id}/repair")
def repair_task(task_id: str):
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] != "needs_review":
        raise HTTPException(status_code=409, detail="Repair is available after a failed test run.")
    results = db.get_test_results(task_id)
    if not results or results[0]["passed"]:
        raise HTTPException(status_code=409, detail="No failed test result is available to repair.")
    repair_events = [event for event in db.get_events(task_id) if event["event_type"] == "repair_started"]
    max_repairs = max(0, get_settings().devagent_max_repair_attempts)
    if len(repair_events) >= max_repairs:
        raise HTTPException(
            status_code=409,
            detail=f"Repair limit reached ({max_repairs}). Review the changes manually or create a new task.",
        )
    if not db.claim_task_status(task_id, {"needs_review"}, "planning"):
        raise HTTPException(status_code=409, detail="Task is already being processed or has changed status.")
    db.add_event(task_id, "repair_started", f"Starting repair attempt {len(repair_events) + 1} of {max_repairs}.")
    try:
        return prepare_task(task, repair_feedback=results[0]["output"])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/tasks/{task_id}/tests")
def run_task_tests(task_id: str):
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] != "applied":
        raise HTTPException(status_code=409, detail="Approve and apply a patch before running tests.")
    if not db.claim_task_status(task_id, {"applied"}, "testing"):
        raise HTTPException(status_code=409, detail="Tests are already running or the task status has changed.")
    try:
        result = run_pytest(task["repo_path"])
    except (RepositoryError, TestRunnerError) as exc:
        db.set_task_status(task_id, "applied")
        db.add_event(task_id, "test_runner_unavailable", str(exc))
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    db.save_test_result(task_id, result["runner"], result["passed"], result["exit_code"], result["output"])
    status = "completed" if result["passed"] else "needs_review"
    db.set_task_status(task_id, status)
    db.add_event(task_id, "tests_passed" if result["passed"] else "tests_failed", result["output"][:1000] or "No test output.")
    return result
