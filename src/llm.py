import os
from typing import Optional, Any

# Optional LangChain chat models
try:
    from langchain_openai import ChatOpenAI  # type: ignore
except Exception:
    ChatOpenAI = None  # type: ignore

try:
    from langchain_google_genai import ChatGoogleGenerativeAI  # type: ignore
except Exception:
    ChatGoogleGenerativeAI = None  # type: ignore

try:
    from langchain_ollama import ChatOllama  # type: ignore
except Exception:
    ChatOllama = None  # type: ignore


class DummyLLM:
    def invoke(self, message: Any):
        try:
            if isinstance(message, str):
                text = message
            else:
                text = getattr(message, "content", "") or str(message)
        except Exception:
            text = str(message)
        return (
            "[FALLBACK REPORT]\n" +
            text[:4000] +
            "\n-- End of fallback. Provide API keys for better results."
        )


_llm_singleton: Optional[Any] = None


def get_llm() -> Any:
    global _llm_singleton
    if _llm_singleton is not None:
        return _llm_singleton

    # OpenAI preferred if configured
    if ChatOpenAI is not None and os.getenv("OPENAI_API_KEY"):
        model = os.getenv("OPENAI_MODEL", "gpt-4.1")
        _llm_singleton = ChatOpenAI(model=model, temperature=0)
        return _llm_singleton

    # Gemini
    if ChatGoogleGenerativeAI is not None and os.getenv("GEMINI_API_KEY"):
        model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
        _llm_singleton = ChatGoogleGenerativeAI(model=model)
        return _llm_singleton

    # Ollama
    if ChatOllama is not None and os.getenv("OLLAMA_MODEL"):
        model = os.getenv("OLLAMA_MODEL")
        host = os.getenv("OLLAMA_HOST", None)
        try:
            if host:
                _llm_singleton = ChatOllama(model=model, base_url=host)
            else:
                _llm_singleton = ChatOllama(model=model)
        except TypeError:
            # Some versions may not accept base_url; fall back to defaults
            _llm_singleton = ChatOllama(model=model)
        return _llm_singleton

    # Fallback deterministic LLM for tests / no-keys
    _llm_singleton = DummyLLM()
    return _llm_singleton