from typing import List, Dict, Optional

# Optional dependencies
try:
    from duckduckgo_search import DDGS  # type: ignore
except Exception:  # pragma: no cover - optional
    DDGS = None  # type: ignore

try:
    import requests  # type: ignore
except Exception:  # pragma: no cover - optional
    requests = None  # type: ignore


def search_duckduckgo(query: str, max_results: int = 5) -> List[Dict]:
    results: List[Dict] = []
    if DDGS is not None:
        try:
            with DDGS() as ddgs:  # type: ignore
                for r in ddgs.text(query, max_results=max_results):  # type: ignore
                    results.append({
                        "title": r.get("title"),
                        "href": r.get("href") or r.get("url"),
                        "body": r.get("body") or r.get("snippet"),
                    })
        except Exception:
            pass
    # Fallback: return empty list if library not available or failed
    return results


def fetch_url_title(url: str, timeout: float = 8.0) -> Optional[str]:
    if not requests:
        return None
    try:
        resp = requests.get(url, timeout=timeout, headers={
            "User-Agent": "Mozilla/5.0 (compatible; Search4People/1.0)"
        })
        if not resp.ok:
            return None
        text = resp.text or ""
        # crude title extraction
        start = text.lower().find("<title")
        if start == -1:
            return None
        start = text.find('>', start)
        if start == -1:
            return None
        end = text.lower().find("</title>", start)
        if end == -1:
            return None
        return text[start + 1:end].strip()
    except Exception:
        return None