# StyleCut: spec pack for Claude Code

An automated viral short-form clip creator. Paste a link to a viral video, get its style as a reusable profile, get a shot-by-shot filming plan, then have your footage auto-edited in that style.

## What's in here

```
CLAUDE.md                      # Claude Code reads this automatically: context, stack, rules
PLAN.md                        # Phased build plan with checkboxes and acceptance criteria
docs/
  PRD.md                       # Product requirements & user flows
  ARCHITECTURE.md              # System design, job DAG, storage
  STYLE_PROFILE_SPEC.md        # The "style DNA" schema + extraction methods
  PLAN_MODE_SPEC.md            # Shoot plan schema, generation, coverage check
  EDIT_ENGINE_SPEC.md          # Timeline schema, auto-assembly, FFmpeg renderer
  DATA_MODEL.md                # Postgres tables
  API.md                       # Endpoints
  PROMPTS.md                   # LLM prompt templates
  OPEN_QUESTIONS.md            # Claude logs ambiguities here
.claude/commands/
  next-task.md                 # /next-task: pick up the next unchecked task
  phase-review.md              # /phase-review: verify a phase against its criteria
```

## How to use it

1. These files live at the repo root (CLAUDE.md, PLAN.md, docs/, .claude/commands/).
2. Open Claude Code in the repo root.
3. First prompt:
   > Read CLAUDE.md, PLAN.md and everything in docs/. Summarize the architecture back to me in 10 bullets and list anything that seems contradictory. Then propose how you'll do Phase 0.
4. After that, just run `/next-task` each session. Run `/phase-review` before moving to the next phase.
5. Put 10 real reference clips you have the right to use into `eval/` before Phase 2. That's your quality benchmark.

## Run it

The host only needs Docker. Everything else (Python 3.12, ffmpeg 7, Node, pnpm) runs in containers.

```bash
make dev        # creates .env from .env.example on first run, then starts every service
```

- Web: http://localhost:3000 (System page: http://localhost:3000/health)
- API: http://localhost:8000/api/v1/health, docs at http://localhost:8000/docs
- MinIO console: http://localhost:9001 (credentials from `.env`)

```bash
make test       # pytest (real Postgres/Redis/MinIO, separate test database) + vitest
make lint       # ruff, mypy, eslint, tsc
make types      # Pydantic -> JSON Schema -> packages/schemas/generated/index.ts
make fixtures   # synthetic clips in apps/api/tests/fixtures/
make lock       # refresh uv.lock and pnpm-lock.yaml after changing dependencies
```

## Prerequisites
Docker, an Anthropic API key, and ideally a machine with an NVIDIA GPU for Whisper. CPU works with `WHISPER_MODEL=small`, just slower.
