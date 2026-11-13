# Natural-Language Metrics Service: Standing Rules

These rules apply to every future task and every file in this repository. Create all project files within this Capstone project folder.

## Stack and code quality

- Use Python 3.11+, SQLite, Streamlit, the OpenAI API, Pydantic, and pytest.
- Read the OpenAI API key from the environment only.
- List new packages before installing them. Keep requirements pinned to exact versions.
- Write typed code in small modules and add docstrings to public functions.

## Governed query architecture

- The LLM must never write or execute SQL on the main path. It selects governed metrics through function calling; a deterministic compiler builds the SQL.
- Apply defence in depth in this exact order:
  1. Pydantic argument validation.
  2. Catalog metric-ID check.
  3. Dimension and filter allow-lists.
  4. Deterministic compiler.
  5. SQL AST validation.
  6. Read-only SQLite connection.
- Never guess on undefined or ambiguous metrics. Request clarification or refuse as appropriate.
- Numbers in the final answer must come from query results or deterministic application code, never from LLM arithmetic.

## Response contract

- Every service response must carry outcome, value, metric definition, SQL, and a trace ID.
- Outcomes are exactly: `answer`, `clarify`, `refuse`, `empty_result`.
- Keep all response fields present for every outcome; use null values where a value, metric definition, or SQL is unavailable. Never fabricate them.

## Secrets

- Never hardcode or log secrets.
- Use a git-ignored `.env` for local environment configuration and a committed `.env.example` containing placeholders only.
- Load local configuration into the environment; application code reads secrets from the environment only.

## Evaluation and task completion

- Do not tune on the locked test set. Tune on the dev set only.
- After each task, run the applicable tests and report their results. If tests cannot run or do not exist yet, state that explicitly.
- After each task, summarise changes and list assumptions and unknowns.
- Propose the repository structure and obtain user approval before creating the initial project scaffold.
