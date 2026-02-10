from __future__ import annotations
from typing import List, Dict, Any, Optional
import os
import json

from .config import OPENAI_API_KEY, OPENAI_MODEL

def _fallback_template(user_message: str, result: Dict[str, Any]) -> str:
    # Minimal offline response
    if "answer" in result:
        return str(result["answer"])
    return "Here are the results:\n" + json.dumps(result, indent=2, default=str)

def render_with_llm(system_prompt: str, history: List[Dict[str, str]], user_message: str, tool_result: Dict[str, Any]) -> str:
    """If OPENAI_API_KEY is set, uses OpenAI Responses API; else uses a template."""
    if not OPENAI_API_KEY:
        return _fallback_template(user_message, tool_result)

    # OpenAI official Python SDK uses OpenAI() client
    # See official docs: https://platform.openai.com/docs
    from openai import OpenAI  # type: ignore
    client = OpenAI(api_key=OPENAI_API_KEY)

    # Keep the context small-ish: include history + tool_result JSON
    tool_blob = json.dumps(tool_result, indent=2, default=str)

    messages: List[Dict[str, str]] = []
    messages.append({"role": "system", "content": system_prompt})
    for m in history[-20:]:
        if m.get("role") in ("user", "assistant"):
            messages.append({"role": m["role"], "content": m["content"]})
    messages.append({
        "role": "user",
        "content": (
            f"User question: {user_message}\n\n"
            f"Computed schedule data (JSON):\n{tool_blob}\n\n"
            "Write a concise, stakeholder-friendly answer. "
            "If you list tasks, include task_code + task_name when available. "
            "If results are empty, explain what might be missing in the data."
        )
    })

    resp = client.responses.create(
        model=OPENAI_MODEL,
        input=messages,
    )

    # SDK returns output_text convenience
    return getattr(resp, "output_text", str(resp))
