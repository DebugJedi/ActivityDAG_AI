from __future__ import annotations


"""
tools.py - Tool definition for the CriticalPath AI agentic layer.

Each tool here corresponds to an analytics function. The JSON schema
is what Azure OpenAI's funciton-calling API sees - it tells the LLM
what each tool does, what parameters it accepts, and what it returns.

Desing rules:
    - Descriptions must be specific enough that the LLM picks the RIGHT tool,
    not just any tool. Vagure description cause wrong tool selection.
    - Parameters must match EXACTLY what the executor in agent.py expects.
    - Every tool should independently callable - no hidden dependencies.
    - Tools are designed to be called in PARALLEL when possible.
"""

from typing import Any, Dict, List

TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_all_activities",
            "description": (
                "Returns the complete list of ALL activities (tasks) in the project. "
                "Use this when the user asks to see all tasks, list activities, or needs "
                "a full schedule overview. Returns task codes, names, WBS phase, dates, "
                "status, float, and duration for every activity."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "get_activities_in_window",
            "description": (
                "Returns activities that start or finish within a specified date range, "
                "plus activities already underway (spanning) during that period. "
                "Use this when the user asks about activities in a time window: "
                "'next 3 months', 'in April 2024', 'between March and June', "
                "'starting before July', 'what's happening in Q2'. "
                "The date window should already be resolved to actual calendar dates."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "window_start": {
                        "type": "string",
                        "description": "Start of date window in YYYY-MM-DD format. Can be null if open-ended.",
                    },
                    "window_end": {
                        "type": "string",
                        "description": "End of date window in YYYY-MM-DD format. Can be null if open-ended.",
                    },
                    "date_field": {
                        "type": "string",
                        "enum": ["both", "start", "end"],
                        "description": (
                            "'both' = activities starting OR finishing in window (default). "
                            "'start' = only activities starting in window. "
                            "'end' = only activities finishing in window."
                        ),
                    },
                },
                "required": [],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "get_float_risk_analysis",
            "description": (
                "Returns a complete float risk breakdown: critical tasks (float = 0), "
                "near-critical tasks (float between 0 and threshold), and non-critical tasks "
                "sorted by lowest float first. Use this for: 'top float risks', "
                "'near critical activities', 'what tasks are at risk', 'schedule risk', "
                "'which tasks could delay the project'. "
                "Critical and near-critical are returned as SEPARATE groups."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "near_critical_threshold_days": {
                        "type": "number",
                        "description": (
                            "Tasks with float <= this many days are considered near-critical. "
                            "Default is 30 days. Use a larger value (e.g. 60) for more conservative analysis."
                        ),
                    },
                    "top_n_non_critical": {
                        "type": "integer",
                        "description": "Limit the non-critical list to this many items (sorted by lowest float). Default: no limit.",
                    },
                },
                "required": [],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "get_critical_path",
            "description": (
                "Computes and returns the critical path through the project network — "
                "the longest chain of dependent activities that determines the project "
                "finish date. Use this when the user asks: 'what is the critical path', "
                "'driving path', 'what controls the project finish date', "
                "'which tasks can't slip'. Returns the ordered sequence of activities."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "get_project_duration",
            "description": (
                "Returns the overall project start date, finish date, and total duration in days. "
                "Use for: 'how long is the project', 'when does the project start/finish', "
                "'total project duration', 'project timeline'."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "get_project_total_float",
            "description": (
                "Returns the project-level total float — the amount of schedule buffer "
                "before the project finish date would slip. Based on the finish milestone. "
                "Use for: 'what is the project total float', 'how much buffer does the project have', "
                "'project float'. Different from task-level float."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "get_task_details",
            "description": (
                "Returns full details for a specific task including its dates, duration, float, "
                "status, and its direct predecessors and successors in the schedule network. "
                "Use when the user asks about a SPECIFIC named task: "
                "'tell me about CON2000', 'what is PER1000', 'details on DES1060'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_code": {
                        "type": "string",
                        "description": "The P6 activity code (e.g. 'CON2000', 'PER1000', 'DES1060').",
                    },
                },
                "required": ["task_code"],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "get_predecessors",
            "description": (
                "Returns all predecessor activities for a specific task — "
                "the activities that must finish before this one can start. "
                "Use for: 'what comes before X', 'predecessors of X', 'what does X depend on', "
                "'what is blocking X'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_code": {
                        "type": "string",
                        "description": "The P6 activity code to look up predecessors for.",
                    },
                },
                "required": ["task_code"],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "get_successors",
            "description": (
                "Returns all successor activities for a specific task — "
                "the activities that can only start after this one finishes. "
                "Use for: 'what comes after X', 'successors of X', 'downstream of X', "
                "'what does X drive'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_code": {
                        "type": "string",
                        "description": "The P6 activity code to look up successors for.",
                    },
                },
                "required": ["task_code"],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "get_schedule_health",
            "description": (
                "Returns a comprehensive schedule health snapshot: project duration, "
                "total float, float risk distribution, critical path summary, and graph metrics. "
                "Use for broad diagnostic questions: 'how is the schedule looking', "
                "'schedule health', 'what are the biggest risks', 'give me an overview', "
                "'open ends', 'schedule quality'."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },

{
    "type": "function",
    "function": {
        "name": "get_float_by_phase",
        "description": (
            "Returns float risk analysis filtered to a specific WBS phase or work type. "
            "Use when the user asks about float or risk for a specific phase: "
            "'which design tasks are at risk', 'construction near-critical activities', "
            "'permits with no float', 'electrical tasks at risk'. "
            "Matches against WBS phase name and task code prefix."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "phase_filter": {
                    "type": "string",
                    "description": "Phase keyword to filter by, e.g. 'design', 'construction', 'permit', 'civil'.",
                },
                "near_critical_threshold_days": {
                    "type": "number",
                    "description": "Float threshold in days for near-critical. Default 30.",
                },
            },
            "required": ["phase_filter"],
        },
    },
},
]


TOOL_NAMES = {t["function"]["name"] for t in TOOL_DEFINITIONS}