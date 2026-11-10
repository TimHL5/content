# Data Model (Postgres)

All tables: `id uuid pk default gen_random_uuid()`, `created_at`, `updated_at`. Owned rows have `owner_id uuid not null references users`. JSONB columns hold the Pydantic contracts. Always validate on write.

| Table | Key columns | Notes |
|---|---|---|
| `users` | email, name, plan | Single dev user until Phase 7 |
| `assets` | owner_id, kind (`reference`\|`footage`\|`music`\|`sfx`\|`render`\|`image`), s3_key, proxy_key, content_hash, duration_s, width, height, fps, has_audio, status (`uploading`\|`ready`\|`failed`\|`expired`), expires_at, meta jsonb | Every media file. `ready` = the original is stored; the proxy exists once `proxy_key` is set. `expired` is applied on read when `expires_at` has passed. |
| `reference_videos` | owner_id, asset_id, source_url, platform, status (`queued`\|`ingesting`\|`ingested`\|`analyzing`\|`ready`\|`failed`), derived jsonb (S3 keys of scenes/audio/transcript/color/sheets), error jsonb (`{code, message, hint}`) | One per analyzed reference. Not named `references`: that is a reserved word in Postgres. The API path stays `/references`. |
| `style_profiles` | owner_id, name, schema_version, data jsonb, source_reference_ids uuid[], is_blend bool | Editable; `data.user_overrides` holds edits |
| `projects` | owner_id, style_profile_id, title, brief jsonb, status (`planning`\|`shooting`\|`editing`\|`done`), share_token text unique null | `share_token` backs the read-only plan link |
| `shoot_plans` | project_id, version, data jsonb, is_current bool | New version on regenerate |
| `footage_clips` | project_id, asset_id, transcript_key, faces_key, quality jsonb, matched_shot_ids text[], coverage jsonb | Per uploaded raw clip |
| `timelines` | project_id, version, parent_id, created_by, data jsonb, is_current bool | Immutable versions |
| `renders` | timeline_id, preset, asset_id, status, duration_ms | |
| `jobs` | owner_id, type, status (`queued`\|`running`\|`succeeded`\|`failed`), progress float, step text, input jsonb, output jsonb, error text, attempts int, idempotency_key text unique null, parent_id | `idempotency_key` = `{subject_id}:{step}:{step_version}` where subject is the asset, project, or timeline the job works on. Null for jobs that must always run. |
| `llm_calls` | job_id, prompt_id, prompt_version, model, input_tokens, output_tokens, latency_ms, cost_usd, cache_hit bool | Cost tracking |
| `llm_cache` | key text unique, output jsonb | hash(prompt_id, version, model, inputs) |

## Indexes
- `assets(owner_id, kind)`, `assets(expires_at) where status='ready'`
- `jobs(idempotency_key)` unique, `jobs(parent_id)`
- `timelines(project_id, version)` unique, `shoot_plans(project_id, version)` unique

## Migrations
Phase 0: users, assets, jobs · Phase 1: reference_videos · Phase 2: style_profiles, llm_calls, llm_cache · Phase 3: projects, shoot_plans · Phase 4: timelines, renders · Phase 5: footage_clips
