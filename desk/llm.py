"""Cliente LLM. Cualquier endpoint compatible con OpenAI (DashScope/Qwen, Moonshot/Kimi, OpenAI)."""
import json
import re
import time
from .config import CFG

_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(base_url=CFG.llm_base_url, api_key=CFG.llm_api_key)
    return _client


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if not m:
            raise
        return json.loads(m.group(0))


def ask_json(role: str, system: str, user_payload: dict, model: str, retries: int = 2) -> dict:
    """Llama al modelo y devuelve el JSON parseado. Reintenta si la respuesta no es JSON."""
    if CFG.llm_provider == "mock":
        from .mock import mock_answer
        return mock_answer(role, user_payload)

    client = _get_client()
    messages = [
        {"role": "system", "content": system + "\n\nRESPONDE ÚNICAMENTE con un objeto JSON válido. Sin texto antes ni después, sin markdown."},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]
    last_err = None
    for attempt in range(retries + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=CFG.llm_temperature,
            )
            content = resp.choices[0].message.content or ""
            return _extract_json(content)
        except Exception as e:  # JSON inválido, rate limit, red...
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"[{role}] fallo LLM tras {retries + 1} intentos: {last_err}")
