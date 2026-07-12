# agent-auto

Multi-agent coding orchestrator with **local RAG** (ChromaDB + MiniLM):

**classify -> intake (.env) -> index -> Planner -> Retriever -> Coder -> Tester -> Reviewer -> PR**

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
```

Set `GROQ_API_KEY` (and `GH_TOKEN` for PRs). First RAG run downloads `all-MiniLM-L6-v2` locally.

## CLI

```bash
agent doctor

agent run \
  --repo https://github.com/org/app.git \
  --task "Add JWT refresh tokens." \
  --base-branch main \
  --env-file .\secrets.env \
  --yes
```

- Missing keys from the target `.env.example` are **prompted interactively**
- Non-TTY without `--env-file` fails with a clear error
- Clones land in `runs/<run_id>/repo/`; Chroma index in `runs/<run_id>/chroma/`

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
docker run --rm -it -e GROQ_API_KEY -e GH_TOKEN -v %CD%/runs:/runs agent-auto run --repo <url> --task "..." --env-file /runs/secrets.env --yes
```
