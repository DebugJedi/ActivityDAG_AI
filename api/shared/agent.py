from __future__ import  annotations

"""
agent.py - Two-turn agentic loop for CriticalPath AI. 

Architecture:
    Turn 1 (Plan):
        Send user query + tool menu to LLM.
        LLM responds with one or more tool_calls - which tools to call and with what arguments. No data is retrieved yet.

    Execution (Parallel):
        All requested tool calls are executed simultaneously using
        python's concurrent.futures. Each call hits our analytics functions
        directly - no extra LLM calls, no network round trips.
    
    Turn 2 (synthesize):
        All tool results are packaged and sent back to LLM along with 
        the original query. LLM systhesiszes a final, grounded answer.

"""
import json
import os
import concurrent.futures
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple
from dotenv import load_dotenv

from .tools import TOOL_DEFINITIONS, TOOL_NAMES
from .analytics import(
    list_all_activities,
    activities_in_window,
    float_risk_analysis,
    critical_path_summary,
    project_duration,
    project_total_float,
    float_by_phase,
    critical_and_near_critical
)
from .config import AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT
from .schedule_graph import ScheduleGraph

_PLAN_SYSTEM_PROMPT = """\
You are CriticalPath AI, an expert Primavera P6 schedule analyst.

You have access to a set of tools that query a live P6 schedule database.
Your job in this turn is to SELECT which tools to call to fully answer the user's question.

Rules:
1. Call ALL tools needed to answer the question completely — do not under-call.
2. For compound questions ("activities starting next month with low float"),
   call BOTH the date window tool AND the float risk tool.
3. You may call multiple tools in parallel — they execute simultaneously.
4. Do not guess or answer from memory — always use tools to get live data.
5. If the question is about a specific task code (e.g. CON2000), always call
   get_task_details for that task.
6. For broad "health" or "overview" questions, call get_schedule_health plus
   any other relevant tools.
7. Today's date is {today}. Use this when resolving relative date expressions
   like "next 3 months" or "this year".

Respond ONLY with tool calls. Do not write any text response in this turn.
"""

_SYNTHESIS_SYSTEM_PROMPT = """\
You are CriticalPath AI, an expert Primavera P6 schedule analyst helping a \
project manager understand their construction schedule.

You have just retrieved live schedule data using analysis tools. \
Your job now is to synthesize all the data into a clear, accurate, \
stakeholder-friendly answer.

Rules:
1. Base your answer ENTIRELY on the tool results provided. Do not invent data.
2. Always cite specific task codes and names when discussing activities.
3. Convert hours to days (divide by 8) when presenting float or duration to users.
4. If results are empty for a date window, explain what IS happening in the \
   schedule during that period (spanning activities, etc.).
5. Never summarize the reply if a user asked of list of item and there are 77 items, show all 77 items. If user wants a summary, they can ask for that in a follow-up question.
6.. For risk questions, clearly distinguish critical (float=0) from \
   near-critical tasks — they require different management responses.
7. Be concise but complete. Use plain language, not scheduling jargon, \
   unless the user is clearly technical.
8. If data is missing or a tool returned no results, say so clearly and \
   explain what that means.
9. Today's date is {today}.
"""


class ToolExecutor:
    """
    Executes tool calls against the live schedule data.
    All tool functions are called synchronously but dispatched in parallel.
    by the agent loop using ThreadPoolExecutor.
    """

    def __init__(self, data,  proj_id: str, today):
        self.data = data
        self.proj_id = str(proj_id)
        self.today = today
        self._tasks = None
        self._graph = None
        

    def _get_tasks(self):
        if self._tasks is None:
            tasks = self.data.tasks[
                self.data.tasks["proj_id"].astype(str) == self.proj_id
            ].copy()

            if (self.data.wbs is not None and 
                "wbs_id" in tasks.columns and 
                "wbs_id" in self.data.wbs.columns):
                w = self.data.wbs[["wbs_id", "wbs_name"]].drop_duplicates()
                tasks = tasks.merge(w, on="wbs_id", how="left")
            self._tasks = tasks

        return self._tasks
    
    def _get_graph(self):
        if self._graph is None:
            sg = ScheduleGraph(self.data.tasks, self.data.taskpred, self.data.wbs)
            self._graph = sg.build_for_project(self.proj_id)
        return self._graph
    
    def _find_task(self, task_code: str):
        tasks = self._get_tasks()
        if "task_code" in tasks.columns:
            m = tasks[tasks["task_code"].astype(str).str.upper() == task_code.upper()]
            if not m.empty:
                return m.iloc[0].to_dict()
        return None
    

    def list_all_activities(self, **kwargs)-> Dict[str, Any]:
        return list_all_activities(self._get_tasks())
        
    def get_activities_in_window(
            self, 
            window_start: Optional[str] = None,
            window_end: Optional[str] = None,
            date_field: str = "both",
            **kwargs,
    )-> Dict[str, Any]:
        def _parse(s: Optional[str])-> Optional[date]:
            if not s:
                return None
            try:
                return datetime.strptime(s[:10], "%Y-%m-%d").date()
            
            except Exception:
                return None
            
        return activities_in_window(
            self._get_tasks(),
            window_start=_parse(window_start),
            window_end=_parse(window_end),
            date_field=date_field,
        )
    
    def get_float_risk_analysis(
            self,
            near_ciritical_threshold_days: float = 30.0,
            top_n_non_critical: Optional[int] = None,
            **kwargs,
    ) -> Dict[str, Any]:
        return float_risk_analysis(
            self._get_tasks(),
            near_critical_threshold_days=float(near_ciritical_threshold_days),
            top_n=top_n_non_critical,
        )
    
    def get_critical_path(self, **kwargs) -> Dict[str, Any]:
        build = self._get_graph()
        return critical_path_summary(build.graph)
    
    def get_project_duration(self, **kwargs) -> Dict[str, Any]:
        return project_duration(self._get_tasks())
    
    def get_project_total_float(self, **kwargs) -> Dict[str, Any]:
        return project_total_float(self._get_tasks())
    
    def get_task_details(self, task_code: str, **kwargs) -> Dict[str, Any]:
        task = self._find_task(task_code)
        if not task:
            return {"error": f"Task '{task_code}' not found in project {self.proj_id}."}
        
        build = self._get_graph()
        G = build.graph
        node_id = str(task.get("task_id", ""))

        preds, succs = [], []
        if node_id in G:
            preds = [
                {
                    "task_id": p,
                    "task_code": G.nodes[p].get("task_code", ""),
                    "task_name": G.nodes[p].get("task_name", ""),
                }
                for p in G.predecessors(node_id)
            ]

            succs = [
                {
                    "task_id": p,
                    "task_code": G.nodes[p].get("task_code", ""),
                    "task_name": G.nodes[p].get("task_name", ""),
                }
                for p in G.successors(node_id)
            ]
        
        return {
            "task": task,
            "predecessors": preds[:100],
            "successors": succs[:100],
        }
    
    def get_predecessors(self, task_code: str, **kwargs) -> Dict[str, Any]:
        task = self._find_task(task_code)
        if not task:
            return {"error": f"Task '{task_code}' not found."}
        build   = self._get_graph()
        G       = build.graph
        node_id = str(task.get("task_id", ""))
        preds   = []
        if node_id in G:
            preds = [
                {
                    "task_id":   p,
                    "task_code": G.nodes[p].get("task_code", ""),
                    "task_name": G.nodes[p].get("task_name", ""),
                }
                for p in G.predecessors(node_id)
            ]
        return {"task": task, "predecessors": preds[:100]}

    def get_successors(self, task_code: str, **kwargs) -> Dict[str, Any]:
        task = self._find_task(task_code)
        if not task:
            return {"error": f"Task '{task_code}' not found."}
        build   = self._get_graph()
        G       = build.graph
        node_id = str(task.get("task_id", ""))
        succs   = []
        if node_id in G:
            succs = [
                {
                    "task_id":   s,
                    "task_code": G.nodes[s].get("task_code", ""),
                    "task_name": G.nodes[s].get("task_name", ""),
                }
                for s in G.successors(node_id)
            ]
        return {"task": task, "successors": succs[:100]}
    
    def get_float_by_phase(
            self, 
            phase_filter: Optional[str] = None,
            near_ciritical_threshold_days: float = 30.0,
            **kwargs,
    ) -> Dict[str, Any]:
        
        
        return float_risk_analysis(
            self._get_tasks(),
            phase_filter=phase_filter,
            near_critical_threshold_days=float(near_ciritical_threshold_days),
            
    )

    def get_schedule_health(self, **kwargs) -> Dict[str, Any]:
        tasks = self._get_tasks()
        build = self._get_graph()
        G     = build.graph
        return {
            "project_duration":    project_duration(tasks),
            "project_total_float": project_total_float(tasks),
            "float_risk":          float_risk_analysis(tasks, near_critical_threshold_days=30.0),
            "critical_path":       critical_path_summary(G),
            "graph_metrics": {
                "total_tasks":    G.number_of_nodes(),
                "total_links":    G.number_of_edges(),
                "has_cycles":     build.has_cycles,
            },
        }
    
    def execute(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a single named tool call with given arguments."""
        fn = getattr(self, tool_name, None)
        if fn is None:
            return {"error": f"Unknown tool: {tool_name}"}
        try:
            return fn(**arguments)
        except Exception as e:
            return {"error": f"Tool '{tool_name}' failed: {type(e).__name__}: {e}"}

# load_dotenv()

# AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
# AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")

def run_agent(
    data,
    proj_id:  str,
    message:  str,
    history:  List[Dict[str, str]],
    today:    Optional[date] = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    Two-turn agentic loop.

    Returns:
        (final_answer: str, debug_info: dict)
        debug_info contains the tool calls made and their raw results,
        useful for logging and the app's "show reasoning" feature.
    """
    today = today or date.today()

    try:
        # Backup option
        # from openai import OpenAI  
        # client = OpenAI(api_key=OPENAI_API_KEY)

        from openai import AzureOpenAI
        client = AzureOpenAI(
            api_key=AZURE_OPENAI_API_KEY,
            api_version="2024-10-21",
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
        )
    except Exception as e:
        return f"Could not connect to Azure OpenAI: {e}", {}

    executor = ToolExecutor(data, proj_id, today)

    # ------------------------------------------------------------------
    # Turn 1: Planning — which tools to call?
    # ------------------------------------------------------------------
    plan_system = _PLAN_SYSTEM_PROMPT.format(today=str(today))

    plan_messages = [{"role": "system", "content": plan_system}]
    # Include recent history for conversational context (last 6 turns)
    for m in history[-6:]:
        if m.get("role") in ("user", "assistant"):
            plan_messages.append({"role": m["role"], "content": m["content"]})
    plan_messages.append({"role": "user", "content": message})

    try:
        plan_response = client.chat.completions.create(
            model="gpt-4o",
            messages=plan_messages,
            tools=TOOL_DEFINITIONS,
            tool_choice="required",   # must call at least one tool
            temperature=0,
        )
    except Exception as e:
        return f"Planning step failed: {e}", {}

    plan_msg = plan_response.choices[0].message

    # Extract tool calls from the response
    tool_calls = plan_msg.tool_calls or []
    if not tool_calls:
        # GPT didn't call any tools — fall back to direct answer
        return plan_msg.content or "I could not determine which tools to use for this query.", {}

    # ------------------------------------------------------------------
    # Execution: run all tool calls in parallel
    # ------------------------------------------------------------------
    tool_results: List[Dict[str, Any]] = []

    def _run_one(tc):
        name = tc.function.name
        try:
            args = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        result = executor.execute(name, args)
        return {
            "tool_call_id": tc.id,
            "tool_name":    name,
            "arguments":    args,
            "result":       result,
        }

    # Use ThreadPoolExecutor so IO-bound tools don't block each other
    # (for CPU-bound pandas operations this still helps with readability)
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(tool_calls), 4)) as pool:
        futures = [pool.submit(_run_one, tc) for tc in tool_calls]
        for f in concurrent.futures.as_completed(futures):
            tool_results.append(f.result())

    # Sort results back into original call order for consistent LLM context
    call_order = {tc.id: i for i, tc in enumerate(tool_calls)}
    tool_results.sort(key=lambda r: call_order.get(r["tool_call_id"], 999))

    # ------------------------------------------------------------------
    # Turn 2: Synthesis — produce the final answer
    # ------------------------------------------------------------------
    synthesis_system = _SYNTHESIS_SYSTEM_PROMPT.format(today=str(today))

    # Build the full message sequence: system + history + user + tool calls + results
    synthesis_messages = [{"role": "system", "content": synthesis_system}]
    for m in history[-6:]:
        if m.get("role") in ("user", "assistant"):
            synthesis_messages.append({"role": m["role"], "content": m["content"]})

    # Add the original user message
    synthesis_messages.append({"role": "user", "content": message})

    # Add the assistant's tool-call turn (required by OpenAI protocol)
    synthesis_messages.append({
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in tool_calls
        ],
    })

    # Add each tool result as a tool message
    for tr in tool_results:
        synthesis_messages.append({
            "role":         "tool",
            "tool_call_id": tr["tool_call_id"],
            "content":      json.dumps(tr["result"], default=str),
        })

    try:
        synthesis_response = client.chat.completions.create(
            model="gpt-4o",
            messages=synthesis_messages,
            temperature=0.2,   # slight creativity for natural language, but grounded
        )
        final_answer = synthesis_response.choices[0].message.content or ""
    except Exception as e:
        print(f"Synthesis step failed: {type(e).__name__}: {e}")
        # Fallback: render tool results directly
        final_answer = _fallback_render(message, tool_results)

    debug_info = {
        "tools_called": [
            {"name": tr["tool_name"], "arguments": tr["arguments"]}
            for tr in tool_results
        ],
        "tool_result_summary": {
            tr["tool_name"]: _summarize_result(tr["result"])
            for tr in tool_results
        },
    }

    return final_answer, debug_info


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fallback_render(message: str, tool_results: List[Dict]) -> str:
    """Plain text fallback if synthesis LLM call fails."""
    lines = [f"Results for: {message}\n"]
    for tr in tool_results:
        lines.append(f"[{tr['tool_name']}]")
        lines.append(json.dumps(tr["result"], indent=2, default=str))
        lines.append("")
    return "\n".join(lines)


def _summarize_result(result: Dict) -> str:
    """One-line summary of a tool result for debug logging."""
    if "error" in result:
        return f"ERROR: {result['error']}"
    if "count" in result:
        return f"{result['count']} items"
    if "activities" in result:
        return f"{len(result.get('activities', []))} activities"
    if "counts" in result:
        return str(result["counts"])
    if "path" in result:
        return f"critical path: {result.get('count', 0)} tasks"
    keys = list(result.keys())[:3]
    return f"keys: {keys}"