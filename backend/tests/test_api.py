from fastapi.testclient import TestClient

from app.main import app


def test_health(test_environment):
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_create_task_and_reject_invalid_repo(test_environment):
    with TestClient(app) as client:
        good = client.post("/api/tasks", json={"description": "Add a helper function", "repo_path": "demo"})
        bad = client.post("/api/tasks", json={"description": "Add a helper function", "repo_path": "../outside"})
    assert good.status_code == 201
    assert good.json()["status"] == "queued"
    assert bad.status_code == 400


def test_approved_patch_is_applied(test_environment):
    from app import db
    from app.services.patching import make_unified_diff

    _, repo = test_environment
    with TestClient(app) as client:
        created = client.post("/api/tasks", json={"description": "Add a helper function", "repo_path": "demo"})
        task_id = created.json()["id"]
        old = (repo / "example.py").read_text(encoding="utf-8")
        new = "def add(a, b):\n    return a + b + 10\n"
        patch_id = "test-patch-approval"
        db.create_patch(patch_id, task_id, make_unified_diff("example.py", old, new))
        db.set_task_status(task_id, "awaiting_approval")
        response = client.post(f"/api/approvals/{patch_id}", json={"approve": True})

    assert response.status_code == 200
    assert response.json()["status"] == "applied"
    assert (repo / "example.py").read_text(encoding="utf-8") == new


def test_agent_workflow_generates_reviewable_patch(test_environment, monkeypatch):
    from app.workflow import agent_graph
    import app.workflow as workflow

    _, _repo = test_environment
    monkeypatch.setattr(workflow, "create_plan", lambda task, names, context: [
        {"step": "Update helper", "validation": "Run unit tests"}
    ])
    monkeypatch.setattr(workflow, "propose_files", lambda task, plan, names, context: {
        "summary": "Improve add helper",
        "files": [{"path": "example.py", "content": "def add(a, b):\n    return a + b + 1\n"}],
    })
    result = agent_graph.invoke({"task": {"id": "workflow-test", "description": "Update the add helper", "repo_path": "demo"}})
    assert result["plan"][0]["step"] == "Update helper"
    assert "--- a/example.py" in result["diff_text"]
    assert "return a + b + 1" in result["diff_text"]


def test_start_task_persists_plan_and_creates_pending_patch(test_environment, monkeypatch):
    import app.orchestrator as orchestrator

    class FakeGraph:
        def invoke(self, state):
            return {
                "plan": [{"step": "Update helper", "validation": "Run tests"}],
                "proposal": {
                    "summary": "Update add helper",
                    "files": [{"path": "example.py", "content": "def add(a, b):\n    return a + b + 1\n"}],
                },
                "diff_text": (
                    "--- a/example.py\n+++ b/example.py\n@@ -1,2 +1,2 @@\n"
                    " def add(a, b):\n-    return a + b\n+    return a + b + 1\n"
                ),
            }

    monkeypatch.setattr(orchestrator, "agent_graph", FakeGraph())
    with TestClient(app) as client:
        created = client.post(
            "/api/tasks",
            json={"description": "Update the add helper", "repo_path": "demo"},
        )
        task_id = created.json()["id"]
        started = client.post(f"/api/tasks/{task_id}/start")
        details = client.get(f"/api/tasks/{task_id}")

    assert started.status_code == 200, started.text
    assert details.status_code == 200
    assert details.json()["status"] == "awaiting_approval"
    assert details.json()["plan"] == [{"step": "Update helper", "validation": "Run tests"}]
    assert len(details.json()["patches"]) == 1
    assert details.json()["patches"][0]["status"] == "pending"


def test_task_description_rejects_whitespace_only(test_environment):
    with TestClient(app) as client:
        response = client.post(
            "/api/tasks",
            json={"description": "        ", "repo_path": "demo"},
        )
    assert response.status_code == 422


def test_repair_attempt_limit_is_enforced(test_environment, monkeypatch):
    from app import db
    from app.config import get_settings

    monkeypatch.setenv("DEVAGENT_MAX_REPAIR_ATTEMPTS", "1")
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/tasks",
                json={"description": "Fix the failing unit test", "repo_path": "demo"},
            )
            task_id = created.json()["id"]
            db.set_task_status(task_id, "needs_review")
            db.save_test_result(task_id, "docker", False, 1, "AssertionError: expected 2")
            db.add_event(task_id, "repair_started", "Starting repair attempt 1 of 1.")
            response = client.post(f"/api/tasks/{task_id}/repair")
        assert response.status_code == 409
        assert "Repair limit reached" in response.json()["detail"]
    finally:
        get_settings.cache_clear()


def test_full_mocked_task_lifecycle(test_environment, monkeypatch):
    import app.orchestrator as orchestrator
    import app.main as main

    class FakeGraph:
        def invoke(self, state):
            return {
                "plan": [{"step": "Update helper", "validation": "Run tests"}],
                "proposal": {"summary": "Add a small helper change", "files": []},
                "diff_text": (
                    "--- a/example.py\n+++ b/example.py\n@@ -1,2 +1,2 @@\n"
                    " def add(a, b):\n-    return a + b\n+    return a + b + 1\n"
                ),
            }

    monkeypatch.setattr(orchestrator, "agent_graph", FakeGraph())
    monkeypatch.setattr(
        main,
        "run_pytest",
        lambda _repo: {"runner": "mock", "passed": True, "exit_code": 0, "output": "2 passed"},
    )
    with TestClient(app) as client:
        created = client.post(
            "/api/tasks",
            json={"description": "Change the add helper behavior", "repo_path": "demo"},
        )
        task_id = created.json()["id"]
        started = client.post(f"/api/tasks/{task_id}/start")
        patch_id = started.json()["patch_id"]
        approved = client.post(f"/api/approvals/{patch_id}", json={"approve": True})
        tests = client.post(f"/api/tasks/{task_id}/tests")
        details = client.get(f"/api/tasks/{task_id}")

    assert created.status_code == 201
    assert started.status_code == 200
    assert approved.status_code == 200
    assert tests.status_code == 200 and tests.json()["passed"] is True
    assert details.json()["status"] == "completed"
    assert details.json()["test_results"][0]["output"] == "2 passed"


def test_interrupted_planning_task_recovers_on_startup(test_environment):
    from app import db
    import uuid

    task_id = str(uuid.uuid4())
    db.create_task_record(task_id, "Recover an interrupted planning task", "demo")
    db.set_task_status(task_id, "planning")
    db.create_patch("orphaned-patch", task_id, "--- a/example.py\n+++ b/example.py\n@@ -1 +1 @@\n-x\n+y\n")

    with TestClient(app) as client:
        details = client.get(f"/api/tasks/{task_id}").json()

    assert details["status"] == "failed"
    assert "interrupted" in details["error"].lower()
    assert details["patches"][0]["status"] == "stale"


def test_task_status_claim_is_atomic_and_conditional(test_environment):
    from app import db
    import uuid

    task_id = str(uuid.uuid4())
    db.create_task_record(task_id, "Claim a queued task once", "demo")
    assert db.claim_task_status(task_id, {"queued", "failed"}, "planning") is True
    assert db.claim_task_status(task_id, {"queued", "failed"}, "planning") is False


def test_patch_cannot_be_approved_when_task_is_not_waiting(test_environment):
    from app import db
    from app.services.patching import make_unified_diff

    _, repo = test_environment
    with TestClient(app) as client:
        created = client.post(
            "/api/tasks",
            json={"description": "Change the add helper behavior", "repo_path": "demo"},
        )
        task_id = created.json()["id"]
        old = (repo / "example.py").read_text(encoding="utf-8")
        patch_id = "not-awaiting-approval"
        db.create_patch(patch_id, task_id, make_unified_diff("example.py", old, old + "\n# change\n"))
        response = client.post(f"/api/approvals/{patch_id}", json={"approve": True})
    assert response.status_code == 409
    assert (repo / "example.py").read_text(encoding="utf-8") == old


def test_patch_status_claim_prevents_approve_reject_race(test_environment):
    from app import db
    import uuid

    task_id = str(uuid.uuid4())
    db.create_task_record(task_id, "Protect patch status", "demo")
    patch_id = "single-claim-patch"
    db.create_patch(patch_id, task_id, "--- a/example.py\n+++ b/example.py\n@@ -1 +1 @@\n-x\n+y\n")
    assert db.claim_patch_status(patch_id, "pending", "applying") is True
    assert db.claim_patch_status(patch_id, "pending", "rejected") is False


def test_interrupted_test_run_recovers_to_applied(test_environment):
    from app import db
    import uuid

    task_id = str(uuid.uuid4())
    db.create_task_record(task_id, "Recover interrupted tests", "demo")
    db.set_task_status(task_id, "testing")
    with TestClient(app) as client:
        details = client.get(f"/api/tasks/{task_id}").json()
    assert details["status"] == "applied"
    assert "interrupted" in details["error"].lower()


def test_failed_patch_application_marks_task_and_patch_failed(test_environment):
    from app import db

    _, repo = test_environment
    with TestClient(app) as client:
        created = client.post(
            "/api/tasks",
            json={"description": "Change the add helper behavior", "repo_path": "demo"},
        )
        task_id = created.json()["id"]
        patch_id = "stale-context-patch"
        db.create_patch(
            patch_id,
            task_id,
            "--- a/example.py\n+++ b/example.py\n@@ -1,2 +1,2 @@\n"
            " def add(a, b):\n-    return a - b\n+    return a + b + 1\n",
        )
        db.set_task_status(task_id, "awaiting_approval")
        response = client.post(f"/api/approvals/{patch_id}", json={"approve": True})
        details = client.get(f"/api/tasks/{task_id}").json()

    assert response.status_code == 400
    assert details["status"] == "failed"
    assert details["patches"][0]["status"] == "failed"
    assert (repo / "example.py").read_text(encoding="utf-8") == "def add(a, b):\n    return a + b\n"


def test_interrupted_patch_application_recovers_as_failed(test_environment):
    from app import db
    import uuid

    task_id = str(uuid.uuid4())
    db.create_task_record(task_id, "Recover interrupted patch application", "demo")
    db.set_task_status(task_id, "awaiting_approval")
    db.create_patch("interrupted-applying-patch", task_id, "--- a/example.py\n+++ b/example.py\n@@ -1 +1 @@\n-x\n+y\n")
    assert db.claim_patch_status("interrupted-applying-patch", "pending", "applying") is True

    with TestClient(app) as client:
        details = client.get(f"/api/tasks/{task_id}").json()

    assert details["status"] == "failed"
    assert "inspect the repository diff" in details["error"].lower()
    assert details["patches"][0]["status"] == "failed"
