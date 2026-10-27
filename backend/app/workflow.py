from typing import Any, TypedDict

from app.agents import create_plan, propose_files
from app.config import get_settings
from app.services.patching import PatchError, make_unified_diff, validate_relative_path
from app.services.repository import collect_context, resolve_repo

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:  # Enables unit testing without LangGraph installed; production install includes it.
    END = "__end__"
    START = "__start__"
    StateGraph = None


class AgentState(TypedDict, total=False):
    task: dict[str, Any]
    file_names: list[str]
    context: dict[str, str]
    plan: list[dict[str, str]]
    proposal: dict[str, Any]
    diff_text: str
    repair_feedback: str


def inspect_repository(state: AgentState) -> dict[str, Any]:
    task = state["task"]
    resolve_repo(task["repo_path"])
    names, context = collect_context(task["repo_path"], query=task.get("description", ""))
    if not names:
        raise ValueError("No eligible text files were found in this repository.")
    if not context:
        raise ValueError(
            "No complete text files fit within the configured model context budget. "
            "Increase the context budget or use a smaller, focused repository."
        )
    return {"file_names": names, "context": context}


def plan_task(state: AgentState) -> dict[str, Any]:
    description = state["task"]["description"]
    if state.get("repair_feedback"):
        description += "\n\nREPAIR MODE: Previous tests failed. Diagnose and fix the failure while preserving existing behavior. Test output:\n" + state["repair_feedback"][:8000]
    plan = create_plan(description, state["file_names"], state["context"])
    return {"plan": plan}


def propose_patch(state: AgentState) -> dict[str, Any]:
    task = state["task"]
    description = task["description"]
    if state.get("repair_feedback"):
        description += "\n\nREPAIR MODE: Fix the reported test failure. Do not remove or weaken tests to make them pass. Test output:\n" + state["repair_feedback"][:8000]
    proposal = propose_files(description, state["plan"], state["file_names"], state["context"])
    if not proposal["files"]:
        summary = proposal.get("summary", "The model did not explain its result.")
        raise ValueError(
            "DevAgent could not propose a code change after one corrective retry. "
            "The requested behavior may already exist, or the model may not have understood the task. "
            f"Model summary: {summary[:500]} "
            "Check the current files and try a more specific task if a change is still needed."
        )
    diffs = []
    seen = set()
    for item in proposal["files"]:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("content"), str):
            raise ValueError("Each proposed file must have a path and complete content string.")
        path = validate_relative_path(item["path"])
        if path not in state["file_names"]:
            raise PatchError(f"The model attempted to modify a file not present in the repository: {path}")
        if path not in state["context"]:
            raise PatchError(f"The model attempted to modify a file outside the supplied context: {path}. Narrow the task or increase context coverage.")
        if path in seen:
            raise PatchError(f"The model proposed duplicate edits for {path}.")
        seen.add(path)
        old = state["context"][path]
        diffs.append(make_unified_diff(path, old, item["content"]))
    diff_text = "\n".join(diff for diff in diffs if diff)
    if not diff_text.strip():
        raise ValueError(
            "DevAgent generated no effective changes after one corrective retry. "
            "The requested behavior may already be implemented. Inspect the current files, "
            "or specify the exact missing behavior and expected tests."
        )
    if len(diff_text.encode("utf-8")) > get_settings().devagent_max_patch_bytes:
        raise PatchError("Proposed changes exceed the configured patch size limit.")
    return {"proposal": proposal, "diff_text": diff_text}


class SequentialGraphFallback:
    """Small deterministic fallback for test environments without optional LangGraph."""
    def invoke(self, state: AgentState) -> AgentState:
        state = {**state, **inspect_repository(state)}
        state = {**state, **plan_task(state)}
        state = {**state, **propose_patch(state)}
        return state


def build_agent_graph():
    if StateGraph is None:
        return SequentialGraphFallback()
    graph = StateGraph(AgentState)
    graph.add_node("inspect", inspect_repository)
    graph.add_node("plan", plan_task)
    graph.add_node("propose", propose_patch)
    graph.add_edge(START, "inspect")
    graph.add_edge("inspect", "plan")
    graph.add_edge("plan", "propose")
    graph.add_edge("propose", END)
    return graph.compile()


agent_graph = build_agent_graph()
