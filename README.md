# agent-auto

Multi-agent coding orchestrator with **local RAG** (ChromaDB + MiniLM) and an autonomous **open-source contribute** mode.

**Single task:** classify -> intake (.env) -> index -> Planner -> Retriever -> Coder -> Tester -> Reviewer -> PR

**Contribute:** fetch open issues -> rank easiest-first -> fork/solve -> real-user UX verify -> claim (>50%) -> structured PR -> CI fix loop

## Complexity tiers

| Tier | Behavior |
|---|---|
| `docs` | Fast path: 1 LLM rewrite, skip index/browser/tests |
| `simple` | Lite orchestrator, skip heavy tests/browser |
| `standard` | Full role chain + RAG |
| `complex` | Full chain, mandatory env gate, stricter reviewer |

## Setup

Python 3.11+.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
playwright install chromium
copy .env.example .env
gh auth login
```

Set `GROQ_API_KEY` (and `GH_TOKEN` if not using `gh` keyring). First RAG run downloads `all-MiniLM-L6-v2` locally.

## CLI

### Single instructed task

```bash
agent doctor

agent run \
  --repo https://github.com/org/app.git \
  --task "Add JWT refresh tokens." \
  --base-branch main \
  --env-file .\secrets.env \
  --yes
```

### Autonomous open-source contribute

```bash
agent contribute \
  --repo owner/name \
  --limit 10 \
  --labels "good first issue,bug" \
  --env-file .\secrets.env \
  --yes \
  --max-ci-retries 3
```

Behavior highlights:

- Fork-first when you lack write access; same-repo PR when you have push
- Skips issues where an assignee already has an open PR for that issue
- Solves easiest issues first (`docs` → `simple` → `standard` → `complex`)
- Comments “Working on this” only after >50% progress, then opens a PR with a structured body (`Fixes #N`, summary, checklist)
- Real-user Playwright/API smoke (not lint-only); blocks PR if UX fails (unless `--allow-unverified`)
- Watches CI, comments on failures, iterates fixes up to `--max-ci-retries`

State: `runs/contribute/<owner>__<repo>/state.json`

## Roles

- **Orchestrator** — sequences roles (no LLM)
- **Planner** — structured plan only (never edits)
- **Retriever** — top-k chunks from Chroma (local embeddings)
- **Coder** — implements one subtask with tools
- **Tester** — tests/browser per plan verify flags
- **Reviewer** — approve or request rework

## Docker

```bash
docker build -t agent-auto .
docker run --rm -it -e GROQ_API_KEY -e GH_TOKEN -v %CD%/runs:/runs agent-auto contribute --repo owner/name --limit 5 --yes
```
