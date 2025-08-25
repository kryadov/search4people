import json
from src.langgraph_flow import GRAPH


def test_graph_confirm_yes_finishes_and_reports():
    # Pre-populated state simulating the DB prior to confirmation
    candidate = {
        "title": "Test Candidate",
        "url": "https://example.com/profile",
        "snippet": "Profile snippet",
        "source_query": "John Doe linkedin",
    }
    state = {
        "inputs": {"first_name": "John", "last_name": "Doe"},
        "candidates": [candidate],
        "current_index": 0,
        # critical: decision should be preserved and cause selection -> collect -> reporter
        "user_decision": "yes",
    }

    out = GRAPH.invoke(state)

    assert out.get("selected"), "Candidate should be selected after 'yes' decision"
    assert out.get("awaiting_user") is False, "Flow should not be awaiting user after 'yes'"
    assert out.get("summary"), "Summary should be set after selection"
    # a report should be generated because route after collect with 'yes' goes to reporter
    assert isinstance(out.get("report"), str) and len(out.get("report")) > 0
