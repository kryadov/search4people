from typing import Dict, Any, List, Optional, Tuple, TypedDict
import os

from langgraph.graph import StateGraph, END

from .tools import search_duckduckgo, fetch_url_title
from .llm import get_llm


class FlowState(TypedDict, total=False):
    inputs: Dict[str, Any]
    plan: List[str]
    candidates: List[Dict[str, Any]]
    current_index: int
    selected: Dict[str, Any]
    details: Dict[str, Any]
    summary: str
    queries: List[str]
    report: str
    awaiting_user: bool


def _make_queries(inputs: Dict[str, Any]) -> List[str]:
    parts = []
    for k in ["first_name", "last_name", "surname", "phone"]:
        v = (inputs or {}).get(k) or ""
        if v:
            parts.append(str(v).strip())
    base = " ".join(parts).strip()
    queries = []
    if base:
        queries.append(base)
        queries.append(f"{base} linkedin")
        queries.append(f"{base} github")
        queries.append(f"{base} twitter")
        queries.append(f"{base} facebook")
        if (inputs or {}).get("phone"):
            queries.append(f"{base} phone {inputs['phone']}")
    return queries[:5]


def _search_candidates(queries: List[str], max_results: int = 5) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    seen = set()
    for q in queries:
        res = search_duckduckgo(q, max_results=max_results)
        for r in res:
            href = (r.get("href") or "").strip()
            if not href or href in seen:
                continue
            seen.add(href)
            candidates.append({
                "title": r.get("title"),
                "url": href,
                "snippet": r.get("body"),
                "source_query": q,
            })
    return candidates


def _collect_details(candidate: Dict[str, Any]) -> Dict[str, Any]:
    details = dict(candidate)
    # Try fetching page title for enrichment
    title = fetch_url_title(candidate.get("url") or "")
    if title and not details.get("title"):
        details["title"] = title
    return details


def _make_report(state: Dict[str, Any]) -> str:
    llm = get_llm()
    selected = state.get("selected") or {}
    inputs = state.get("inputs") or {}
    details = state.get("details") or {}
    prompt = (
        "Create a concise, structured portfolio/report about the person based on inputs and collected details.\n"
        "Include: Basic info (name, phone), links, inferred roles, and any notable summaries from sources.\n"
        "If data is sparse, state limitations.\n\n"
        f"Inputs: {inputs}\n\n"
        f"Selected candidate: {selected}\n\n"
        f"Collected details: {details}\n\n"
        "Return a markdown-like text."
    )
    return llm.generate_text(prompt, max_tokens=900)


# Public API

def run_flow(inputs: Optional[Dict[str, Any]], prior_state: Optional[Dict[str, Any]], user_decision: Optional[str]) -> Tuple[Dict[str, Any], Optional[str]]:
    """
    Drive the multi-agent flow with simple state transitions. If langgraph is available, the state machine is compatible
    with a StateGraph, but to keep minimal footprint we execute steps procedurally while preserving the same state keys.

    Returns new_state, report_text (if any newly generated)
    """
    state: Dict[str, Any] = dict(prior_state or {})
    report_text: Optional[str] = None

    if inputs is not None:
        state["inputs"] = inputs

    # Initialize planning if not present
    if not state.get("plan") and state.get("inputs"):
        state["plan"] = [
            "Create person search plan",
            "Execute search and prepare candidates",
            "Request user confirmation on best candidate",
            "Collect details on confirmed candidate",
            "Prepare report and store in DB",
        ]

    # If we don't have candidates yet, perform search
    if not state.get("candidates") and state.get("inputs"):
        queries = _make_queries(state["inputs"]) or []
        state["queries"] = queries
        state["candidates"] = _search_candidates(queries, max_results=5)
        state["current_index"] = 0

    # Decide whether we need user input
    candidates = state.get("candidates") or []
    idx = int(state.get("current_index") or 0)

    # If a selected candidate exists and decision instructs to collect/report, continue
    if user_decision in ("collect", "report") and state.get("selected"):
        if user_decision == "collect":
            # Re-collect to try to enrich
            state["details"] = _collect_details(state["selected"])
            state["summary"] = state.get("summary") or (state["selected"].get("title") or "")
        else:  # report
            if not state.get("details") and state.get("selected"):
                state["details"] = _collect_details(state["selected"])
            report_text = _make_report(state)
            state["report"] = report_text
            state["awaiting_user"] = False
        return state, report_text

    # If no candidate selected yet, process user decision or ask for it
    if not state.get("selected"):
        if not candidates:
            state["awaiting_user"] = False
            state["summary"] = "No candidates found. Adjust search terms and try again."
            return state, None
        # If we don't have a decision yet, pause and ask user to confirm current candidate
        if not user_decision:
            state["awaiting_user"] = True
            return state, None
        # Process decision
        decision = (user_decision or "").strip().lower()
        if decision in ("yes", "y", "match", "true"):  # Confirm
            state["selected"] = candidates[idx]
            state["awaiting_user"] = False
            # proceed to collect and report in same call
            state["details"] = _collect_details(state["selected"])
            state["summary"] = state["selected"].get("title") or state["selected"].get("url")
            report_text = _make_report(state)
            state["report"] = report_text
            return state, report_text
        elif decision in ("no", "n", "next", "false"):
            idx += 1
            if idx < len(candidates):
                state["current_index"] = idx
                state["awaiting_user"] = True
                return state, None
            else:
                # Try another round of search with broader queries
                broadened = (state.get("queries") or []) + [
                    f"{(state.get('inputs') or {}).get('first_name','')} {(state.get('inputs') or {}).get('last_name','')} profile",
                    f"{(state.get('inputs') or {}).get('first_name','')} {(state.get('inputs') or {}).get('last_name','')} resume",
                ]
                new_candidates = _search_candidates(broadened, max_results=3)
                if new_candidates:
                    state["candidates"] = new_candidates
                    state["current_index"] = 0
                    state["awaiting_user"] = True
                    return state, None
                state["awaiting_user"] = False
                state["summary"] = "Exhausted candidates without a match."
                return state, None
        else:
            # Unknown input, ask again
            state["awaiting_user"] = True
            return state, None

    # If selected exists but no explicit collect/report requested, keep state
    state["awaiting_user"] = False
    return state, report_text


# Expose a minimal StateGraph for visualization or tooling
_state_graph = StateGraph(FlowState)
# We won't wire full async execution here to keep footprint minimal; run_flow manages procedural steps.
_state_graph.add_node("planner", lambda s: s)
_state_graph.add_node("searcher", lambda s: s)
_state_graph.add_node("decider", lambda s: s)
_state_graph.add_node("collector", lambda s: s)
_state_graph.add_node("reporter", lambda s: s)
_state_graph.add_node("coordinator", lambda s: s)
_state_graph.set_entry_point("planner")
_state_graph.add_edge("planner", "searcher")
_state_graph.add_edge("searcher", "decider")
_state_graph.add_edge("decider", "collector")
_state_graph.add_edge("collector", "reporter")
_state_graph.add_edge("reporter", END)
GRAPH = _state_graph