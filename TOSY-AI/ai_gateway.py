"""Plan-aware Gemini routing with automatic, server-side fallback."""
import os
import logging
import requests

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are TOSY AI, a helpful, honest, age-appropriate assistant. "
    "Be clear, practical, and admit uncertainty."
)


def _configured_compatible_providers():
    order = os.getenv("AI_PROVIDER_ORDER", "openai,openrouter")
    keys = {
        "openai": os.getenv("OPENAI_API_KEY", "").strip(),
        "openrouter": os.getenv("OPENROUTER_API_KEY", "").strip(),
    }
    return [
        name for name in (x.strip().lower() for x in order.split(","))
        if name in keys and keys[name] and name not in []
    ]


def _call_gemini(prompt, history, model):
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Gemini API key is not configured")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    contents = []
    for item in history[-12:]:
        contents.append({
            "role": "user" if item["role"] == "user" else "model",
            "parts": [{"text": item["content"]}],
        })
    contents.append({"role": "user", "parts": [{"text": prompt}]})
    response = requests.post(
        url,
        params={"key": key},
        json={
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": contents,
        },
        timeout=(10, 60),
    )
    response.raise_for_status()
    data = response.json()
    parts = data["candidates"][0]["content"]["parts"]
    return "".join(part.get("text", "") for part in parts if part.get("text"))


def _call_compatible(provider, prompt, history):
    if provider == "openai":
        key = os.environ["OPENAI_API_KEY"].strip()
        url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1/chat/completions")
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    else:
        key = os.environ["OPENROUTER_API_KEY"].strip()
        url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1/chat/completions")
        model = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend({"role": x["role"], "content": x["content"]} for x in history[-12:])
    messages.append({"role": "user", "content": prompt})
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if provider == "openrouter":
        headers["HTTP-Referer"] = os.getenv("APP_BASE_URL", "http://localhost:5000")
        headers["X-Title"] = "TOSY Intel"
    response = requests.post(
        url, headers=headers, json={"model": model, "messages": messages}, timeout=(10, 60)
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]



def ai_analyze_image(image_bytes, mime_type, prompt, plan="free"):
    """Analyze an uploaded image with Gemini vision; try Pro first for Pro users."""
    import base64
    if mime_type not in {"image/png", "image/jpeg", "image/webp"}:
        raise ValueError("Unsupported image format")
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Gemini API key is not configured")

    is_pro = str(plan).lower() == "pro"
    flash_model = os.getenv("GEMINI_FREE_MODEL", "gemini-3.8-flash").strip()
    pro_model = os.getenv("GEMINI_PRO_MODEL", "gemini-3.1-pro-preview").strip()
    models = ([pro_model, flash_model] if is_pro else [flash_model])
    encoded = base64.b64encode(image_bytes).decode("ascii")
    question = (prompt or "Describe this image and help me understand it.").strip()[:4000]
    contents = [{"role": "user", "parts": [
        {"text": question},
        {"inline_data": {"mime_type": mime_type, "data": encoded}},
    ]}]
    last_error = None
    for model in dict.fromkeys(models):
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            response = requests.post(
                url, params={"key": key},
                json={
                    "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                    "contents": contents,
                    "generationConfig": {"temperature": 0.4},
                }, timeout=(10, 90),
            )
            response.raise_for_status()
            data = response.json()
            parts = data["candidates"][0]["content"]["parts"]
            answer = "".join(part.get("text", "") for part in parts if part.get("text")).strip()
            if not answer:
                raise ValueError("Gemini returned an empty image response")
            log.info("Image analysis completed using Gemini model=%s", model)
            return answer
        except Exception as exc:
            last_error = exc
            log.warning("Image analysis failed model=%s error=%s", model, type(exc).__name__)
    raise RuntimeError("Image analysis is temporarily unavailable") from last_error


def ai_reply(prompt, history, plan="free"):
    """Free: Flash. Pro: Pro model, then Flash, then configured compatible providers."""
    is_pro = str(plan).lower() == "pro"
    flash_model = os.getenv("GEMINI_FREE_MODEL", "gemini-3.8-flash").strip()
    pro_model = os.getenv("GEMINI_PRO_MODEL", "gemini-3.1-pro-preview").strip()

    attempts = []
    if os.getenv("GEMINI_API_KEY", "").strip():
        if is_pro:
            attempts.append(("gemini", pro_model))
        attempts.append(("gemini", flash_model))

    attempts.extend((provider, None) for provider in _configured_compatible_providers())
    if not attempts:
        raise RuntimeError("No AI provider API key is configured")

    failures = []
    for provider, model in attempts:
        try:
            if provider == "gemini":
                answer = _call_gemini(prompt, history, model)
            else:
                answer = _call_compatible(provider, prompt, history)
            if not isinstance(answer, str) or not answer.strip():
                raise ValueError("Provider returned an empty response")
            log.info("AI response completed using provider=%s model=%s", provider, model or "configured")
            return answer.strip()
        except Exception as exc:
            # Do not log API keys, prompts, or raw provider response bodies.
            log.warning(
                "AI attempt failed provider=%s model=%s error=%s",
                provider, model or "configured", type(exc).__name__
            )
            failures.append(f"{provider}:{model or 'configured'}")

    raise RuntimeError("All configured AI attempts failed: " + ",".join(failures))
