# Data Model (Postgres)

All tables: `id uuid pk default gen_random_uuid()`, `created_at`, `updated_at`. Owned rows have `owner_id uuid not null references users`. JSONB columns hold the Pydantic contracts. Always validate on write.

| Table | Key columns | Notes |
|---|---|---|
| `users` | email, name, plan | Single dev user until Phase 7 |
| `assets` | owner_id, kind (`reference`\|`footage`\|`music`\|`sfx`\|`render`\|`image`), s3_key, proxy_key, content_hash, duration_s, width, height, fps, has_audio, status (`uploading`\|`ready`\|`failed`\|`expired`), expires_at, meta jsonb | Every media file |
| `references` | owner_id, asset_id, source_url, platform, status, derived jsonb (S3 keys of scenes/audio/transcript/color/sheets), error | One per analyzed reference |
| `style_profiles` | owner_id, name, schema_version, data jsonb, source_reference_ids uuid[], is_blend bool | Editable; `data.user_overrides` holds edits |
| `projects` | owner_id, style_profile_id, title, brief jsonb, status (`planning`\|`shooting`\|`editing`\|`done`) | |
| `shoot_plans` | project_id, version, data jsonb, is_current bool | New version on regenerate |
| `footage_clips` | project_id, asset_id, transcript_key, faces_key, quality jsonb, matched_shot_ids text[], coverage jsonb | Per uploaded raw clip |
| `timelines` | project_id, version, parent_id, created_by, data jsonb, is_current bool | Immutable versions |
| `renders` | timeline_id, preset, asset_id, status, duration_ms | |
| `jobs` | owner_id, type, status (`queued`\|`running`\|`succeeded`\|`failed`), progress float, step text, input jsonb, output jsonb, error text, attempts int, idempotency_key text unique, parent_id | |
| `llm_calls` | job_id, prompt_id, prompt_version, model, input_tokens, output_tokens, latency_ms, cost_usd, cache_hit bool | Cost tracking |
| `llm_cache` | key text unique, output jsonb | hash(prompt_id, version, model, inputs) |

## Indexes
- `assets(owner_id, kind)`, `assets(expires_at) where status='ready'`
- `jobs(idempotency_key)` unique, `jobs(parent_id)`
- `timelines(project_id, version)` unique, `shoot_plans(project_id, version)` unique

## Migrations
Phase 0: users, assets, jobs · Phase 1: references · Phase 2: style_profiles, llm_calls, llm_cache · Phase 3: projects, shoot_plans · Phase 4: timelines, renders · Phase 5: footage_clips
