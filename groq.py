"""Groq client kept behind a small provider boundary."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = Path(os.getenv("PROMPTS_DIR", str(PROJECT_ROOT / "prompts")))
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# Free-tier model; override with GROQ_MODEL if needed (e.g. llama-3.1-8b-instant).
DEFAULT_MODEL = "llama-3.3-70b-versatile"
_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)

# Loads local development secrets from the project root when present. In a
# container or hosted deployment, environment variables injected by Docker or
# the platform take precedence and no .env file is required.
load_dotenv(PROJECT_ROOT / ".env")


class GroqError(RuntimeError):
    """An upstream Groq request failed."""


def _prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def _strip_json_fence(text: str) -> str:
    cleaned = _JSON_FENCE.sub("", text.strip()).strip()
    if cleaned.startswith("{") or cleaned.startswith("["):
        return cleaned
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        return cleaned[start : end + 1]
    return cleaned


def _request(payload: dict[str, Any]) -> str:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise GroqError("GROQ_API_KEY is not configured")

    request = urllib.request.Request(
        GROQ_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # Groq is behind Cloudflare; urllib's default UA triggers 403/1010.
            "User-Agent": "Essay-Learner/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            body: dict[str, Any] = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise GroqError(f"Groq returned {error.code}: {detail[:500]}") from error
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise GroqError(f"Groq request failed: {error}") from error

    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise GroqError("Groq returned an unexpected response") from error
    if not isinstance(content, str) or not content.strip():
        raise GroqError("Groq returned an empty response")
    return content.strip()


def complete(prompt_name: str, variables: dict[str, str]) -> str:
    prompt = _prompt(prompt_name).format(**variables)
    payload = {
        "model": os.getenv("GROQ_MODEL", DEFAULT_MODEL),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
    }
    return _request(payload)


def complete_json(prompt_name: str, variables: dict[str, str]) -> str:
    prompt = _prompt(prompt_name).format(**variables)
    payload = {
        "model": os.getenv("GROQ_MODEL", DEFAULT_MODEL),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    return _strip_json_fence(_request(payload))
