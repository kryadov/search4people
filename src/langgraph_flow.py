from typing import Dict, Any, List, Optional, Tuple, TypedDict
import os
import logging

from langgraph.graph import StateGraph, END

from .tools import search_duckduckgo, fetch_url_title
from .llm import get_llm

logger = logging.getLogger("search4people.flow")


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
    logger.debug("Built queries from inputs=%s -> %s", {k: (inputs or {}).get(k) for k in ["first_name","last_name","surname","phone"]}, queries[:5])
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
    logger.debug("Search produced %d candidates from %d queries", len(candidates), len(queries))
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
    return llm.generate_text(prompt, max_tokens=2048)


# Public API



# Define a proper StateGraph with standard nodes and transitions
_graph = StateGraph(FlowState)

# Node implementations

def _node_ingest(state: Dict[str, Any]) -> Dict[str, Any]:
    logger.debug("[ingest] prior_state_keys=%s inputs_provided=%s decision=%s", list((state.get("prior_state") or {}).keys()), state.get("inputs") is not None, state.get("user_decision"))
    # If a prior_state payload is explicitly provided, merge it; otherwise preserve the state as-is.
    if "prior_state" in state and isinstance(state.get("prior_state"), dict):
        prior = state.get("prior_state") or {}
        merged = dict(prior)
        # Overlay any explicitly provided fields from current call
        if state.get("inputs") is not None:
            merged["inputs"] = state.get("inputs")
        if state.get("user_decision") is not None:
            merged["user_decision"] = state.get("user_decision")
        return merged
    # No explicit prior_state: return the state unchanged
    return state


def _node_planner(state: Dict[str, Any]) -> Dict[str, Any]:
    if state.get("inputs") and not state.get("plan"):
        state["plan"] = [
            "Create person search plan",
            "Execute search and prepare candidates",
            "Request user confirmation on best candidate",
            "Collect details on confirmed candidate",
            "Prepare report and store in DB",
        ]
        logger.debug("[planner] plan initialized with %d steps", len(state["plan"]))
    else:
        logger.debug("[planner] plan exists=%s", bool(state.get("plan")))
    return state


def _node_searcher(state: Dict[str, Any]) -> Dict[str, Any]:
    if not state.get("candidates") and state.get("inputs"):
        queries = _make_queries(state["inputs"]) or []
        state["queries"] = queries
        state["candidates"] = _search_candidates(queries, max_results=5)
        state["current_index"] = 0
        logger.debug("[searcher] candidates=%d", len(state["candidates"]))
    else:
        logger.debug("[searcher] skipped: candidates_exist=%s inputs_exist=%s", bool(state.get("candidates")), bool(state.get("inputs")))
    return state


def _route_after_search(state: Dict[str, Any]) -> str:
    user_decision = (state.get("user_decision") or "").strip().lower()
    candidates = state.get("candidates") or []
    selected_exists = bool(state.get("selected"))
    if selected_exists and user_decision in ("collect", "report"):
        nxt = "collector" if user_decision == "collect" else "reporter"
        logger.debug("[route_after_search] selected exists and decision=%s -> %s", user_decision, nxt)
        return nxt
    if not selected_exists:
        if not candidates:
            logger.debug("[route_after_search] no candidates -> finish")
            return "finish"
        if not user_decision:
            logger.debug("[route_after_search] awaiting user decision -> ask")
            return "ask"
        logger.debug("[route_after_search] have decision -> decider")
        return "decider"
    # selected exists but no explicit collect/report requested
    logger.debug("[route_after_search] selected exists, no collect/report -> finalize")
    return "finalize"


def _node_ask(state: Dict[str, Any]) -> Dict[str, Any]:
    state["awaiting_user"] = True
    return state


def _node_decider(state: Dict[str, Any]) -> Dict[str, Any]:
    decision = (state.get("user_decision") or "").strip().lower()
    candidates = state.get("candidates") or []
    idx = int(state.get("current_index") or 0)
    logger.debug("[decider] decision=%s idx=%s candidates=%d", decision, idx, len(candidates))
    if decision in ("yes", "y", "match", "true"):
        if candidates:
            state["selected"] = candidates[idx]
            state["awaiting_user"] = False
            sel = state.get("selected") or {}
            state["summary"] = sel.get("title") or sel.get("url")
            logger.debug("[decider] selected=%s", sel.get("url") or sel.get("title"))
        return state
    elif decision in ("no", "n", "next", "false"):
        idx += 1
        if idx < len(candidates):
            state["current_index"] = idx
            state["awaiting_user"] = True
            logger.debug("[decider] moving to next idx=%d", idx)
            return state
        else:
            broadened = (state.get("queries") or []) + [
                f"{(state.get('inputs') or {}).get('first_name','')} {(state.get('inputs') or {}).get('last_name','')} profile",
                f"{(state.get('inputs') or {}).get('first_name','')} {(state.get('inputs') or {}).get('last_name','')} resume",
            ]
            new_candidates = _search_candidates(broadened, max_results=3)
            if new_candidates:
                state["candidates"] = new_candidates
                state["current_index"] = 0
                state["awaiting_user"] = True
                logger.debug("[decider] broadened search returned %d candidates", len(new_candidates))
                return state
            state["awaiting_user"] = False
            state["summary"] = "Exhausted candidates without a match."
            logger.debug("[decider] no more candidates")
            return state
    else:
        state["awaiting_user"] = True
        logger.debug("[decider] unknown decision -> awaiting user")
        return state


def _route_after_decider(state: Dict[str, Any]) -> str:
    if state.get("selected"):
        return "collector"
    return "ask" if state.get("awaiting_user") else "finish"


def _node_collector(state: Dict[str, Any]) -> Dict[str, Any]:
    if state.get("selected"):
        state["details"] = _collect_details(state["selected"])
        if not state.get("summary"):
            sel = state.get("selected") or {}
            state["summary"] = sel.get("title") or sel.get("url")
        logger.debug("[collector] collected details, summary=%s", state.get("summary"))
    else:
        logger.debug("[collector] no selected candidate")
    return state


def _route_after_collect(state: Dict[str, Any]) -> str:
    decision = (state.get("user_decision") or "").strip().lower()
    nxt = "reporter" if decision in ("yes", "y", "match", "true") else "finalize"
    logger.debug("[route_after_collect] decision=%s -> %s", decision, nxt)
    return nxt


def _node_reporter(state: Dict[str, Any]) -> Dict[str, Any]:
    if not state.get("details") and state.get("selected"):
        state["details"] = _collect_details(state["selected"])
    report_text = _make_report(state)
    state["report"] = report_text
    state["awaiting_user"] = False
    logger.debug("[reporter] report length=%d", len(state.get("report") or ""))
    return state


def _node_finalize(state: Dict[str, Any]) -> Dict[str, Any]:
    state["awaiting_user"] = False
    if state.get("selected") and not state.get("summary"):
        sel = state.get("selected") or {}
        state["summary"] = sel.get("title") or sel.get("url")
    logger.debug("[finalize] awaiting_user=%s summary=%s", state.get("awaiting_user"), state.get("summary"))
    return state

def _node_finish(state: Dict[str, Any]) -> Dict[str, Any]:
    state["awaiting_user"] = False
    if not state.get("summary"):
        if not state.get("selected") and not state.get("candidates"):
            state["summary"] = "No candidates found. Adjust search terms and try again."
    logger.debug("[finish] awaiting_user=%s selected=%s candidates=%d summary=%s", state.get("awaiting_user"), bool(state.get("selected")), len(state.get("candidates") or []), state.get("summary"))
    return state

# Wire the graph
_graph.add_node("ingest", _node_ingest)
_graph.add_node("planner", _node_planner)
_graph.add_node("searcher", _node_searcher)
_graph.add_node("ask", _node_ask)
_graph.add_node("decider", _node_decider)
_graph.add_node("collector", _node_collector)
_graph.add_node("reporter", _node_reporter)
_graph.add_node("finalize", _node_finalize)
_graph.add_node("finish", _node_finish)

_graph.set_entry_point("ingest")
_graph.add_edge("ingest", "planner")
_graph.add_edge("planner", "searcher")
_graph.add_conditional_edges("searcher", _route_after_search, {
    "collector": "collector",
    "reporter": "reporter",
    "decider": "decider",
    "ask": "ask",
    "finish": "finish",
    "finalize": "finalize",
})
_graph.add_conditional_edges("decider", _route_after_decider, {
    "collector": "collector",
    "ask": "ask",
    "finish": "finish",
})
_graph.add_conditional_edges("collector", _route_after_collect, {
    "reporter": "reporter",
    "finalize": "finalize",
})
_graph.add_edge("reporter", END)
_graph.add_edge("ask", END)
_graph.add_edge("finalize", END)
_graph.add_edge("finish", END)

# Expose the compiled graph as GRAPH (standard StateGraph usage)
GRAPH = _graph.compile()