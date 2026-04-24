---
description: YOLO Economy Workflow
---

# YOLO Economy Workflow

## Workflow

1. **Context Initialization**
   - Before start working on task, scan `.agents/reports/` and read the 3 most recent `.md` files, plus any whose filename shares keywords with the current task.

2. **Working on Task**
   - On error: retry up to **3** times using a different approach each time. If still unresolved — stop and write report.
   - No explanatory prose in tool calls or intermediate steps. Act, don't narrate.

3. **Report Writing**
   - Save to `.agents/reports/<YYYYMMDD_HHMMSS>_<task_name>.md` using this template:

```
---
title: <Task Name>
timestamp: <YYYYMMDD_HHMMSS>
---

## Done <--- [Required] Bullet points describing what was accomplished.>
## Found <--- [Optional] Key findings, insights, or discoveries.>
## Status <-- [Optional] Explicitly list what is broken, unfinished, or requires user input.>
## Next Steps <-- [Optional]Recommended actions or future work.>
```

4. **Git Commit**
   - Format: `<task_name>: <short_description>`
   - Author: use your model name with version and mode, i.e. Claude Opus 4.6 (Thinking), Gemini 3.1 Pro (Low)
   - Never commit: credentials, `.env` files or untracked large files.

## Restrictions

  
1. **SEARCH & BROWSER POLICY**
   - NO: Do not use the browser for UI testing or verifying code output.
   - YES: Use targeted search ONLY if:
     1. A library API/documentation is unknown or from 2025/2026.
     2. An error persists after the first local fix attempt.
     3. Explicitly asked for real-time data.


2. **Tool Economy**   
   - Strictly avoid generating screenshots, video recordings, or UI diff maps unless explicitly requested by user.
   - 
3. **Scope**
   - Do not install packages, modify global configs, or touch files outside the project root without explicit permission.