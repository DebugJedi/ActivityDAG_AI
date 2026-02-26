RESPONSE_STRATEGIES = {
    "LIST_ACTIVITIES": {
        "mandatory_prefix": (
            "MANDATORY RULE: The dataset contains {count} activities. "
            "You MUST list ALL {count} individually - every single one on its own numbered line. "
            "Format: '{n}. {task_code}: {task_name} ({duration_days} days, float: {float_days} days)'. "
            "Never show a sample or representative subset. "
            "Never say 'let me know if you want the full list' - the user already asked for it. "
            "Do not group multiple activities into one line."
        ),
        "format_hint": "numbered_list",
    },
    "FLOAT": {
    "mandatory_prefix": (
        "MANDATORY RULE: Structure the answer based on what the user asked: "
        "- If asking about RISK or DELAYS: lead with critical tasks (float=0), then near-critical. "
        "- If asking about BUFFER or SLIPPAGE: lead with near-critical count and minimum float. "
        "- If asking about DRIVING activities: lead with critical tasks — these drive the finish date. "
        "Always present critical (float=0) and near-critical as SEPARATE labeled groups. "
        "Never merge them. State the threshold used. "
        "List every task in each group with task_code, task_name, and float_days. "
        "Convert all float values from hours to days (divide by 8)."
    ),
    "format_hint": "grouped_list",
},

"HIGH_FLOAT": {
    "mandatory_prefix": (
        "MANDATORY RULE: The user wants to know which tasks can be safely delayed or "
        "which have scheduling flexibility for resource reallocation. "
        "Focus on the non_critical group — these are the tasks with buffer. "
        "Lead with: total count of tasks with float, and the range (min to max days). "
        "Then list the top candidates sorted by highest float first, showing "
        "task_code, task_name, and float_days for each. "
        "Do NOT focus on critical tasks for this query — the user wants flexibility, not risk."
    ),
    "format_hint": "grouped_list",
},

# Add PHASE_FLOAT strategy:
"PHASE_FLOAT": {
    "mandatory_prefix": (
        "MANDATORY RULE: The user is asking about a SPECIFIC phase or work type. "
        "State which phase was searched and how many tasks matched. "
        "Then present results in two labeled groups: "
        "CRITICAL (float=0) — list all with task_code, task_name. "
        "NEAR-CRITICAL (float > 0 but low) — list all with task_code, task_name, float_days. "
        "If no tasks are critical or near-critical in this phase, say so explicitly — "
        "that is good news and worth stating clearly. "
        "Do not include non-critical tasks unless the user asked for them."
    ),
    "format_hint": "grouped_list",
},
    "CRITICAL_PATH": {
        "mandatory_prefix": (
            "MANDATORY RULE: List every task on the critical path in sequence order. "
            "Show task_code, task_name, and duration in days for each. "
            "State the total path duration at the end. "
            "All tasks on the critical path have zero float - confirm this explicitly."
        ),
        "format_hint": "numbered_list",
    },
    "DATE_WINDOW": {
        "mandatory_prefix": (
            "MANDATORY RULE: State the exact date window you are analyzing at the top of your response. "
            "List activities starting/finishing in the window separately from activities spanning it. "
            "If no activities fall in the window, explain what IS underway during that period."
        ),
        "format_hint": "grouped_list",
    },
    "PREDECESSORS": {
        "mandatory_prefix": (
            "MANDATORY RULE: Show the specific task that was asked about first, then list "
            "all its predecessors. Include task_code, task_name, and relationship type for each."
        ),
        "format_hint": "structured",
    },
    "SUCCESSORS": {
        "mandatory_prefix": (
            "MANDATORY RULE: Show the specific task that was asked about first, then list "
            "all its successors. Include task_code, task_name, and relationship type for each."
        ),
        "format_hint": "structured",
    },
    "DURATION": {
        "mandatory_prefix": (
            "MANDATORY RULE: State the project start date, finish date, and total duration in days "
            "clearly at the top. Convert all durations from hours to days."
        ),
        "format_hint": "summary",
    },
    "PROJECT_TOTAL_FLOAT": {
    "mandatory_prefix": (
        "MANDATORY RULE: In P6 scheduling, 'project total float' has no single aggregate number. "
        "Structure your answer in this exact order: "
        "1. FIRST: Clarify this directly — 'There is no single total float value for a project. "
        "   Float is measured per activity. Here is the float picture for this project:' "
        "2. SECOND: Key float numbers — critical tasks (0 days), max float (X days on task Y), median float (X days). "
        "3. THIRD: Float distribution — near-critical (1-30 days), low (30-100 days), high (>100 days) counts. "
        "4. FOURTH: One sentence on schedule risk implication. "
        "DO NOT invent a single total float number by summing or averaging. "
        "DO NOT say 'total float is 0' — that is only the milestone value. "
        "DO NOT mention the finish milestone at all."
    ),
    "format_hint": "summary",
},
    "HEALTH": {
        "mandatory_prefix": (
            "MANDATORY RULE: Structure the health summary into sections: "
            "Critical Path Risk, Float Risk, Schedule Status, Key Concerns. "
            "Give a plain-language overall health rating at the top."
        ),
        "format_hint": "structured",
    },

    "SLIPPAGE": {
    "mandatory_prefix": (
        "MANDATORY RULE: Structure the answer in two clearly labeled groups: "
        "BEHIND BASELINE (finish_variance_days > 0) and AHEAD OF BASELINE (finish_variance_days < 0). "
        "Lead with the total count of slipped tasks and the worst single slippage in days. "
        "For each slipped task show: task_code, task_name, and finish_variance_days. "
        "Sort slipped tasks worst-first. "
        "If no tasks have slipped, state that clearly — it is good news. "
        "Do not confuse slippage with float — they are completely different concepts. "
        "finish_variance_days > 0 = behind baseline. finish_variance_days < 0 = ahead of baseline."
    ),
    "format_hint": "grouped_list",
},

    "PROJECT_VARIANCE": {
        "mandatory_prefix": (
            "MANDATORY RULE: State these three dates clearly at the top: "
            "1. Baseline finish (max target_end_date across all tasks) "
            "2. Current forecast finish (max early_end_date across all tasks) "
            "3. Scheduled completion date (scd_end_date from PROJECT table if available) "
            "Then state the variance in calendar days. "
            "Positive variance = behind baseline. Negative = ahead. Zero = on baseline. "
            "If variance is 0, state the project is currently tracking to its baseline."
        ),
        "format_hint": "summary",
},

    "BUDGET_TOTAL": {
        "mandatory_prefix": (
            "MANDATORY RULE: State the total project budget in dollars first. "
            "Then show the three-way split: Labor, Equipment, and Material "
            "with dollar amount AND percentage of total for each. "
            "If actual costs are available show percent spent. "
            "Format all dollar amounts with $ sign and comma separators (e.g. $292,540,611). "
            "Do not use technical field names like target_cost — say 'budget' instead."
        ),
       "format_hint": "summary",
},

    "BUDGET_BY_PHASE": {
        "mandatory_prefix": (
            "MANDATORY RULE: State the total budget at the top. "
            "Then list every phase with its budget sorted largest first. "
            "Show dollar amount and percentage of total for each phase. "
            "If a phase filter was applied, confirm which phase was searched. "
            "Format all dollar amounts with $ and commas."
        ),
        "format_hint": "numbered_list",
},

    "BUDGET_TOP_TASKS": {
        "mandatory_prefix": (
            "MANDATORY RULE: List each activity with its task_code, task_name, WBS phase, "
            "and budget in dollars. Sort highest cost first. "
            "State how many activities are shown and the combined budget they represent. "
            "Format all dollar amounts with $ and commas."
        ),
        "format_hint": "numbered_list",
},

    "RESOURCE_SPLIT": {
        "mandatory_prefix": (
            "MANDATORY RULE: Show Labor, Equipment, and Material as three separate labeled sections. "
            "For each show: dollar amount and percentage of total budget. "
            "State the total project budget at the top before breaking it down. "
            "Use plain language — say Labor, Equipment, Material not RT_Labor, RT_Equip, RT_Mat."
        ),
        "format_hint": "grouped_list",
},

    "RESOURCE_COST": {
        "mandatory_prefix": (
            "MANDATORY RULE: List each resource with its name, type (Labor / Equipment / Material), "
            "and total budget. Sort highest budget first. "
            "State how many resources are shown. "
            "Format all dollar amounts with $ and commas."
        ),
        "format_hint": "numbered_list",
},

    "RESOURCE_TASKS": {
        "mandatory_prefix": (
            "MANDATORY RULE: State the resource name and type at the top. "
            "Then list every task assigned to them with: task_code, task_name, "
            "planned hours, budget, and scheduled start and finish dates. "
            "State total task count and total planned hours at the end."
        ),
        "format_hint": "structured",
},
}