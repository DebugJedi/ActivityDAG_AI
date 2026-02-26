"""
llm.py — Rendering layer for CriticalPath AI.

Handles two response shapes from router.py:
  1. Agent path  (routed_via="agent"):
     The answer is already a rendered string from the two-turn agent.
     Just clean and return it — no second LLM call needed.

  2. Direct path (routed_via="direct"):
     The data dict needs to be narrated into plain language.
     Calls Azure OpenAI once with the tool result as context.
"""

from __future__ import annotations
from typing import List, Dict, Any, Optional
import os
import json
import re
from dotenv import load_dotenv
from .response_strategies import RESPONSE_STRATEGIES

load_dotenv()

AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")

# ---------------------------------------------------------------------------
# Text cleaning
# ---------------------------------------------------------------------------

def clean_llm_text(text: str) -> str:
    if not text:
        return ""
    t = text

    mojibake = {
    "\xe2\x80\x94": "\u2014",  # em dash —
    "\xe2\x80\x99": "\u2019",  # right single quote '
    "\xe2\x80\x9c": "\u201c",  # left double quote "
    "\xe2\x80\x9d": "\u201d",  # right double quote "
    "\xe2\x80\x98": "\u2018",  # left single quote '
    "\xe2\x80\xa2": "\u2022",  # bullet •
    "\xe2\x80\xa6": "\u2026",  # ellipsis …
    "\xc2\xb7":     "\u00b7",  # middle dot ·
    "\xc2":         "",        # stray Â
}
    for bad, good in mojibake.items():
        t = t.replace(bad, good)
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r'^\s{0,3}#{1,6}\s*', '', t, flags=re.MULTILINE)
    t = re.sub(r'\*\*(.*?)\*\*', r'\1', t)
    t = re.sub(r'__(.*?)__', r'\1', t)
    t = re.sub(r'\*(.*?)\*', r'\1', t)
    t = re.sub(r'_(.*?)_', r'\1', t)
    t = re.sub(r'`([^`]+)`', r'\1', t)
    t = re.sub(r'^\s*[-*]\s+', '• ', t, flags=re.MULTILINE)
    t = re.sub(r'[ \t]+', ' ', t)
    t = re.sub(r'\n{3,}', '\n\n', t).strip()
    return t


def _fallback_template(user_message: str, result: Dict[str, Any]) -> str:
    if "answer" in result:
        return str(result["answer"])
    return "Here are the results:\n" + json.dumps(result, indent=2, default=str, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Main render function
# ---------------------------------------------------------------------------

def render_response(
    system_prompt: str,
    history: List[Dict[str, str]],
    user_message: str,
    route_result: Dict[str, Any],
) -> str:
    """
    Render a route_query() result into a user-facing string.

    Dispatches based on routed_via:
      "agent" or "agent_fallback" → answer already rendered, clean and return
      "direct" or anything else   → call LLM to narrate the data dict
    """
    routed_via = route_result.get("routed_via", "direct")

    # --- Agent path: answer is pre-rendered ---
    if routed_via in ("agent", "agent_fallback"):
        answer = route_result.get("answer", "")
        return clean_llm_text(answer) if answer else _fallback_template(user_message, route_result)

    # --- Direct path: narrate the data dict ---
    tool_result = route_result.get("data", route_result)
    return render_with_llm(system_prompt, history, user_message, tool_result)


def render_with_llm(
    system_prompt: str,
    history: List[Dict[str, str]],
    user_message: str,
    tool_result: Dict[str, Any],
    intent: Optional[str] = None,
) -> str:
    """Narrate a data dict into a stakeholder-friendly answer via Azure OpenAI."""
    data_str = json.dumps(tool_result, default=str, ensure_ascii=False)

    strategy = RESPONSE_STRATEGIES.get(intent, {})
    prefix = strategy.get("mandatory_prefix", "")

    if prefix and tool_result:
        count = tool_result.get("count", tool_result.get("total", "" ))
        prefix = prefix.replace("{count}", str(count)) if "{count}" in prefix else prefix

    if prefix:
        user_content = (f"{prefix}\n\n"
        f"USer asked: {user_message}\n\n"
        f"Data: {data_str}\n\n")
    else:
        user_content = f"User asked: {user_message}\n\nData: {data_str}" 

    
    if not AZURE_OPENAI_API_KEY:
        return _fallback_template(user_message, tool_result)

    try:
        from openai import AzureOpenAI
        client = AzureOpenAI(
            api_key=AZURE_OPENAI_API_KEY,
            api_version="2024-10-21",
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
        )


        tool_blob = json.dumps(tool_result, indent=2, default=str, ensure_ascii=False)
        
        strategy = RESPONSE_STRATEGIES.get(intent, {})
        prefix = strategy.get("mandatory_prefix", "")

        if "{count}" in prefix:
            count = tool_result.get("count", tool_result.get("total", "" ))
            prefix = prefix.replace("{count}", str(count))

        base_instructions = (
            "Write a concise, stakeholder-friendly answer."
            "Include task_code + task_name when listing activities."
            "Convert hours to days (÷8) for readability."
            "If results are empty, explain what that means in context."
        )

        instructions = f"{prefix}\n\n{base_instructions}" if prefix else base_instructions
        messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]

        for m in history[-20:]:
            if m.get("role") in ("user", "assistant"):
                messages.append({"role": m["role"], "content": m["content"]})

        messages.append({
            "role": "user",
            "content": (
                f"User question: {user_message}\n\n"
                f"Computed schedule data (JSON):\n{tool_blob}\n\n"
                f"{instructions}"
            ),
        })

        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
        )
        reply = resp.choices[0].message.content
        return clean_llm_text(reply)

    except Exception as e:
        print(f"LLM render failed: {type(e).__name__}: {e}")
        return _fallback_template(user_message, tool_result)


