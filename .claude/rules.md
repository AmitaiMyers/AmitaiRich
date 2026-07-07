# Claude Rules

## Stage new files immediately (do NOT commit)

Whenever you create a new file (any extension), you must stage it right away:

```
git add <path-to-new-file>
```

Rules:
- Stage immediately after file creation, before continuing with additional edits or creating more files.
- If you create multiple files, stage each one (or stage the directory) before proceeding.
- `git add` respects `.gitignore`, so ignored files are skipped automatically — do not force-add ignored files with `-f`.
- DO NOT run `git commit` or `git push`. The user handles commits and pushes.

Follow these rules strictly:

1. Use Project Context and Documents
   - Always use the full context of ALL files and code snippets I give you now and that I gave you earlier in this project.
   - Implement features and changes according to the specific document/file I mention (e.g., SRS, SDD, design doc, PDF, etc.).
   - If there is a conflict between generic best practices and the project documents I specify, follow the project documents and call out the conflict.

2. RIPER
   - Code must be: Readable, Intentional, Predictable, Explicit, and Robust.
   - Prefer clear names, small focused functions, and obvious control flow.
   - Avoid “clever” tricks that hurt readability.

3. DRY Coding
   - Do not repeat logic or structures.
   - If you see similar code in 2+ places, extract a function, class, or helper.
   - Prefer reusable abstractions over copy–paste.

4. Fail Fast — No getters, No try/except
   - Let errors surface early with clear messages.
   - Do NOT use `.get()` on dicts; use direct access and validate inputs explicitly.
   - Avoid `try/except` for control flow. Let the program crash on invalid assumptions.

   Example (Python):
   # Good (fail fast)
   user_id = payload["user_id"]
   assert isinstance(user_id, int), "user_id must be int"

   # Bad (hides issues)
   user_id = payload.get("user_id", None)
   # or wrapping everything in try/except

5. Prefer Simple Solutions
   - Always choose the simplest design that fully solves the problem.
   - Avoid over-engineering, unnecessary patterns, or premature abstractions.
   - If there is a choice between a simple approach and a complex “enterprise” one, choose the simple one.

6. Bug Handling: Always Call Out and Fix
   - If you detect a bug, logical inconsistency, or risky edge case in my code or in code you generate:
     - Explicitly tell me what the bug is and why it’s a problem.
     - Immediately propose and show the corrected version of the code.
   - Never ignore or work around a bug silently.