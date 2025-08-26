import os
from typing import Optional, Any

# LangChain chat models
from langchain_openai import ChatOpenAI  # type: ignore

from langchain_google_genai import ChatGoogleGenerativeAI  # type: ignore

from langchain_ollama import ChatOllama  # type: ignore

# DuckDuckGo tool from langchain_community
from langchain_community.tools import DuckDuckGoSearchRun  # type: ignore

# Messages for system/human prompting
from langchain_core.messages import SystemMessage, HumanMessage  # type: ignore


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

    base_llm: Any = None

    # OpenAI preferred if configured
    if ChatOpenAI is not None and os.getenv("OPENAI_API_KEY"):
        model = os.getenv("OPENAI_MODEL", "gpt-4.1")
        base_llm = ChatOpenAI(model=model, temperature=0)
    # Gemini
    elif ChatGoogleGenerativeAI is not None and os.getenv("GEMINI_API_KEY"):
        model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
        base_llm = ChatGoogleGenerativeAI(model=model)
    # Ollama
    elif ChatOllama is not None and os.getenv("OLLAMA_MODEL"):
        model = os.getenv("OLLAMA_MODEL")
        host = os.getenv("OLLAMA_HOST", None)
        try:
            if host:
                base_llm = ChatOllama(model=model, base_url=host)
            else:
                base_llm = ChatOllama(model=model)
        except TypeError:
            # Some versions may not accept base_url; fall back to defaults
            base_llm = ChatOllama(model=model)
    else:
        # Fallback deterministic LLM for tests / no-keys
        _llm_singleton = DummyLLM()
        return _llm_singleton

    # Attach search tool and inject system prompt
    _llm_singleton = _attach_search_tool_and_system_prompt(base_llm)
    return _llm_singleton

class _SystemPromptWrapper:
    """Wrap an LLM to inject a system instruction and (optionally) bind tools.

    Keeps compatibility with llm.invoke(str) usage by converting to messages
    and prepending a system prompt advising to use internet search when needed.
    """
    def __init__(self, llm: Any, system_text: str, tools: Optional[list] = None):
        self._system_text = system_text
        try:
            if tools:
                # Ensure tools are bound if the model supports it
                self._llm = llm.bind_tools(tools)
            else:
                self._llm = llm
        except Exception:
            # If bind_tools is not supported, proceed without binding
            self._llm = llm

    def __getattr__(self, item):
        # Forward any unknown attribute/method to the underlying LLM
        return getattr(self._llm, item)

    def invoke(self, message: Any, **kwargs: Any):
        if SystemMessage is None or HumanMessage is None:
            # Fall back to simple pass-through if message classes unavailable
            return self._llm.invoke(message, **kwargs)
        try:
            if isinstance(message, str):
                msgs = [
                    SystemMessage(content=self._system_text),
                    HumanMessage(content=message),
                ]
            elif isinstance(message, list):
                # If a list of messages, ensure a system prompt is present
                has_system = any(
                    getattr(m, "type", None) == "system" or (
                        SystemMessage is not None and isinstance(m, SystemMessage)
                    )
                    for m in message
                )
                msgs = message if has_system else [SystemMessage(content=self._system_text), *message]
            else:
                content = getattr(message, "content", None)
                if content is None:
                    content = str(message)
                msgs = [
                    SystemMessage(content=self._system_text),
                    HumanMessage(content=content),
                ]
        except Exception:
            msgs = message
        return self._llm.invoke(msgs, **kwargs)


def _attach_search_tool_and_system_prompt(base_llm: Any) -> Any:
    """Bind DuckDuckGoSearchRun tool and inject system prompt advising searches."""
    system_text = (
        "You are a helpful assistant. Use the internet search tool "
        "to find all available information. Prefer calling the DuckDuckGo "
        "search tool when the user's request requires current data, verification, "
        "or discovering external sources. Always summarize sources succinctly. "
        "Try to find person info at linkedin, github, twitter, facebook, collect all related info."
    )

    tools = []
    if DuckDuckGoSearchRun is not None:
        try:
            ddg = DuckDuckGoSearchRun()
            tools.append(ddg)
        except Exception:
            # Tool unavailable/misconfigured; proceed without it
            pass

    return _SystemPromptWrapper(base_llm, system_text, tools=tools)
