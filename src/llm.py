import os
from typing import Optional

# Optional deps
try:
    import openai  # type: ignore
except Exception:
    openai = None  # type: ignore

try:
    import requests  # type: ignore
except Exception:
    requests = None  # type: ignore

try:
    import google.generativeai as genai  # type: ignore
except Exception:
    genai = None  # type: ignore


class LLMClient:
    def __init__(self):
        self.provider = None
        self.model = None
        # OpenAI
        if openai and os.getenv("OPENAI_API_KEY"):
            self.provider = "openai"
            self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            if hasattr(openai, "OpenAI"):
                self._client = openai.OpenAI()
            else:
                # legacy
                openai.api_key = os.getenv("OPENAI_API_KEY")
                self._client = openai
        # Gemini
        elif genai and os.getenv("GEMINI_API_KEY"):
            self.provider = "gemini"
            genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
            self.model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
            self._client = genai.GenerativeModel(self.model)
        # Ollama
        elif requests and os.getenv("OLLAMA_MODEL"):
            self.provider = "ollama"
            self.model = os.getenv("OLLAMA_MODEL")
            self._client = None  # REST via requests
        else:
            self.provider = "fallback"
            self.model = "fallback"
            self._client = None

    def generate_text(self, prompt: str, max_tokens: int = 800) -> str:
        try:
            if self.provider == "openai":
                # Support both SDK styles
                if hasattr(self._client, "chat") and hasattr(self._client.chat, "completions"):
                    resp = self._client.chat.completions.create(
                        model=self.model,
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=max_tokens,
                    )
                    return resp.choices[0].message.content.strip()
                else:
                    resp = self._client.chat.completions.create(
                        model=self.model,
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=max_tokens,
                    )
                    return resp.choices[0].message.content.strip()
            elif self.provider == "gemini":
                resp = self._client.generate_content(prompt)
                return (resp.text or "").strip()
            elif self.provider == "ollama":
                host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
                r = requests.post(f"{host}/api/generate", json={"model": self.model, "prompt": prompt, "stream": False}, timeout=60)
                if r.ok:
                    data = r.json()
                    return (data.get("response") or "").strip()
        except Exception:
            pass
        # Fallback deterministic summarization
        return (
            "[FALLBACK REPORT]\n" +
            prompt[:4000] +
            "\n-- End of fallback. Provide API keys for better results."
        )


_llm_singleton: Optional[LLMClient] = None


def get_llm() -> LLMClient:
    global _llm_singleton
    if _llm_singleton is None:
        _llm_singleton = LLMClient()
    return _llm_singleton