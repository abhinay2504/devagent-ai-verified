import uuid

from app import db
from app.workflow import agent_graph


def prepare_task(task: dict, repair_feedback: str = "") -> dict:
    task_id = task["id"]
    # A failed earlier run may have left an unreviewed proposal. It must not remain approvable
    # after a new planning attempt begins.
    db.stale_pending_patches(task_id)
    db.set_task_status(task_id, "planning")
    db.add_event(task_id, "repository_inspection", "Inspecting repository files and bounded text context.")
    try:
        db.add_event(task_id, "agent_workflow", "Running LangGraph inspect → plan → propose workflow." if not repair_feedback else "Running a repair workflow using the latest failed-test output.")
        state = agent_graph.invoke({"task": task, "repair_feedback": repair_feedback})
        plan = state["plan"]
        proposal = state["proposal"]
        diff_text = state["diff_text"]
        db.save_plan(task_id, plan)
        db.add_event(task_id, "plan_created", f"Created a plan with {len(plan)} steps.")
        patch_id = str(uuid.uuid4())
        db.create_patch(patch_id, task_id, diff_text)
        db.set_task_status(task_id, "awaiting_approval")
        db.add_event(task_id, "patch_proposed", f"Patch {patch_id} is ready for human review. Summary: {proposal['summary']}")
        return {"patch_id": patch_id, "summary": proposal["summary"], "diff": diff_text, "plan": plan}
    except Exception as exc:
        db.set_task_status(task_id, "failed", str(exc)[:2000])
        db.add_event(task_id, "error", str(exc)[:2000])
        raise
