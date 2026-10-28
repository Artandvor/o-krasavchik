"""Тонкая абстракция над LLM. Провайдер выбирается в .env:

    LLM_PROVIDER=anthropic | openai | none
    LLM_MODEL=...            (по умолчанию claude-sonnet-4-5 / gpt-4o-mini)
    LLM_API_KEY=...
    LLM_BASE_URL=...         (для openai-совместимых: OpenRouter, Ollama, vLLM, YandexGPT-шлюзы)

Если ключа нет, LLM недоступна, и каждая функция, которая её использует, обязана иметь
детерминированный fallback. Важно: LLM в системе НИКОГДА не «угадывает» характеристику —
она только разбирает текст (запрос пользователя, ответ отельера, описание новой
характеристики) в структуру, которую дальше проверяет код.
"""
import json
import os
import re

import httpx


class LLM:
    def __init__(self):
        self.provider = os.environ.get("LLM_PROVIDER", "none").lower()
        self.key = os.environ.get("LLM_API_KEY", "")
        self.base = os.environ.get("LLM_BASE_URL", "")
        default = {"anthropic": "claude-sonnet-4-5", "openai": "gpt-4o-mini"}.get(self.provider, "")
        self.model = os.environ.get("LLM_MODEL", default)
        if self.provider in ("anthropic", "openai") and not self.key and "localhost" not in self.base:
            self.provider = "none"

    @property
    def available(self) -> bool:
        return self.provider != "none"

    def complete(self, system: str, user: str, max_tokens: int = 1200, temperature: float = 0.0) -> str:
        if self.provider == "anthropic":
            r = httpx.post(
                (self.base or "https://api.anthropic.com") + "/v1/messages",
                headers={"x-api-key": self.key, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": self.model, "max_tokens": max_tokens, "temperature": temperature,
                      "system": system, "messages": [{"role": "user", "content": user}]},
                timeout=60,
            )
            r.raise_for_status()
            return "".join(b.get("text", "") for b in r.json()["content"])
        if self.provider == "openai":
            r = httpx.post(
                (self.base or "https://api.openai.com/v1").rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {self.key}"},
                json={"model": self.model, "max_tokens": max_tokens, "temperature": temperature,
                      "messages": [{"role": "system", "content": system},
                                   {"role": "user", "content": user}]},
                timeout=60,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        raise RuntimeError("LLM не настроена")

    def json(self, system: str, user: str, max_tokens: int = 1500):
        """Просит JSON и аккуратно его достаёт. Возвращает None при любой ошибке —
        вызывающий код переходит на fallback."""
        if not self.available:
            return None
        try:
            txt = self.complete(system + "\nОтвечай ТОЛЬКО валидным JSON без пояснений.", user, max_tokens)
            m = re.search(r"\{.*\}|\[.*\]", txt, re.S)
            return json.loads(m.group(0)) if m else None
        except Exception as e:  # noqa: BLE001
            print(f"[llm] ошибка: {e}")
            return None


_llm = None


def get_llm() -> LLM:
    global _llm
    if _llm is None:
        _llm = LLM()
    return _llm
