from __future__ import annotations
from typing import List, Dict, Any, Optional
import os
import json
from rich.console import Console
console = Console()
from dotenv import load_dotenv
import re
load_dotenv()

AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
OPENAI_MODEL = os.getenv("OPENAI_MODEL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

def clean_llm_text(text: str) -> str:
    if not text:
        return ""

    t = text

    # Normalize newlines
    t = t.replace("\r\n", "\n").replace("\r", "\n")

    # Remove markdown headings like "#", "##", etc.
    t = re.sub(r'^\s{0,3}#{1,6}\s*', '', t, flags=re.MULTILINE)

    # Remove bold/italic markers ** **, * *, __ __, _ _
    t = re.sub(r'\*\*(.*?)\*\*', r'\1', t)
    t = re.sub(r'__(.*?)__', r'\1', t)
    t = re.sub(r'\*(.*?)\*', r'\1', t)
    t = re.sub(r'_(.*?)_', r'\1', t)

    # Remove inline code ticks
    t = re.sub(r'`([^`]+)`', r'\1', t)

    # Convert bullet lines "- " or "* " to "• "
    t = re.sub(r'^\s*[-*]\s+', '• ', t, flags=re.MULTILINE)

    # Remove extra spaces
    t = re.sub(r'[ \t]+', ' ', t)

    # Clean excessive blank lines
    t = re.sub(r'\n{3,}', '\n\n', t).strip()

    return t

def _fallback_template(user_message: str, result: Dict[str, Any]) -> str:
    # Minimal offline response
    if "answer" in result:
        return str(result["answer"])
    return "Here are the results:\n" + json.dumps(result, indent=2, default=str)

def render_with_llm(system_prompt: str, history: List[Dict[str, str]], user_message: str, tool_result: Dict[str, Any]) -> str:
    """If OPENAI_API_KEY is set, uses OpenAI Responses API; else uses a template."""
    print("OpenAI KEY: ", OPENAI_API_KEY)
    if not AZURE_OPENAI_API_KEY:
        # console.print("The API is not working:......")
        print("The API Key is not working.......")
        return _fallback_template(user_message, tool_result)

    # OpenAI official Python SDK uses OpenAI() client
    # See official docs: https://platform.openai.com/docs

    ## Need to update azurebased OpenAI
    
    try:
        # from openai import OpenAI  
        # client = OpenAI(api_key=OPENAI_API_KEY)

        from openai import AzureOpenAI
        client = AzureOpenAI(
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            api_version="2024-02-01",
            azure_endpoint=AZURE_OPENAI_ENDPOINT)
        

        # Keep the context small-ish: include history + tool_result JSON
        tool_blob = json.dumps(tool_result, indent=2, default=str)

        messages: List[Dict[str, str]] = []
        messages.append({"role": "system", "content": system_prompt})
        for m in history[-20:]:
            if m.get("role") in ("user", "assistant"):
                messages.append({"role": m["role"], "content": m["content"]})

        # intent = tool_result.get("intent", "UNKNOWN")
        # meta = tool_result.get("meta", {})
        # f"Intent: {intent}\n"
        # f"Meta: {json.dumps(meta, indent=2, default=str)}\n\n"
        messages.append({
            "role": "user",
            "content": (
                f"User question: {user_message}\n"
                
                f"Computed schedule data (JSON):\n{tool_blob}\n\n"
                "Write a concise, stakeholder-friendly answer. "
                "If you list tasks, include task_code + task_name when available. "
                "If results are empty, explain what might be missing in the data."
            )
        })
        
        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL"),
            messages=messages
        )
        reply = resp.choices[0].message.content
    
        # This need to update to how azure response are called.
        # resp = client.responses.create(
        #     model=OPENAI_MODEL,
        #     input=messages,
        # )
        # reply = resp.output_text

    
        reply = clean_llm_text(reply)    
        
        return reply
    
    except Exception as e:
        print(f"LLM call failed: {type(e).__name__}: {e}")
        reply = _fallback_template(user_message, tool_result)

