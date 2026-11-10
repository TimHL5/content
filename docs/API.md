# API (FastAPI, `/api/v1`)

All long operations return `202 {job_id, resource_id}`. Track them with `GET /jobs/{id}` or SSE `GET /jobs/{id}/events`.
Errors: `{"error": {"code": "INGEST_PRIVATE_VIDEO", "message": "…", "hint": "Upload the file instead"}}`.

## Health
| Method | Path | Notes |
|---|---|---|
| GET | `/health` | `{status, checks:{db, redis, s3}}`; 200 when all pass, 503 otherwise |

## Uploads
| Method | Path | Body → Response |
|---|---|---|
| POST | `/uploads` | `{filename, size, content_type, kind}` → 201 `{asset_id, upload_id, part_size, parts:[{part_number, url}]}`. `kind`: `reference` \| `music` \| `sfx` (footage uploads arrive with projects in Phase 5). The browser PUTs each `part_size` slice to its URL and keeps the `ETag` response header. |
| POST | `/uploads/{asset_id}/complete` | `{upload_id, parts:[{part_number, etag}]}` → `{asset}` (status `ready`). Safe to retry. Processing starts when the asset is used: `POST /references` for references, `POST /projects/{id}/footage` for footage. |
| GET | `/assets/{asset_id}` | — → `{asset, url, proxy_url}` (presigned GETs, used by the players) |

## References & Styles
| Method | Path | Notes |
|---|---|---|
| POST | `/references` | `{url}` or `{asset_id}` (exactly one) → 202 `{job_id, resource_id}`; starts ingest (Phase 1) and the analysis DAG (Phase 2). Errors: `INGEST_DISABLED` (403), `INGEST_UNSUPPORTED_URL` (422). |
| GET | `/references` | list |
| GET | `/references/{id}` | `{id, status, platform, source_url, asset_id, job_id, error}`. `status`: `queued` → `ingesting` → `ingested` → `analyzing` → `ready`, or `failed` with `error: {code, message, hint}` (`INGEST_PRIVATE_VIDEO`, `INGEST_LOGIN_REQUIRED`, `INGEST_REMOVED`, `INGEST_REGION_LOCKED`, `INGEST_TOO_LONG`, `INGEST_TOO_LARGE`, `INGEST_NOT_A_VIDEO`, `INGEST_FAILED`). |
| GET | `/style-profiles` | list (library) |
| POST | `/style-profiles` | Not implemented yet: a profile is created automatically when analysis succeeds (`GET /references/{id}` → `style_profile_id`). `{blend:[{profile_id, weight}]}` arrives in Phase 7. |
| GET | `/style-profiles/{id}` | profile with overrides applied + contact-sheet URLs |
| PATCH | `/style-profiles/{id}` | `{name?, overrides?: {"/captions/highlight_color": "#00FF88"}}`. Overrides are JSON pointers to existing fields, merged with earlier ones and validated against the schema before saving; a `null` value removes that override. `/id`, `/schema_version`, `/source`, `/user_overrides` are protected. Errors: `OVERRIDE_INVALID_PATH`, `OVERRIDE_INVALID_VALUE`, `OVERRIDE_PROTECTED` (422). |
| DELETE | `/style-profiles/{id}` | |

## Projects & Plan Mode
| Method | Path | Notes |
|---|---|---|
| POST | `/projects` | `{style_profile_id, title, brief: ProjectBrief}` → 201 `ProjectOut` (`has_plan`, `plan_job_id`, `style_name`) |
| GET | `/projects` | list |
| GET/PATCH/DELETE | `/projects/{id}` | |
| POST | `/projects/{id}/shoot-plan` | generate → 202 |
| GET | `/projects/{id}/shoot-plan` | current version: `{version, plan: ShootPlan, word_count, style: {name, wpm, max_shot_s, beats}}`; 404 `PLAN_NOT_FOUND` |
| PATCH | `/projects/{id}/shoot-plan` | manual edits: `{lines?: [{id, text}], shots?: [{id, description?, direction?, duration_s?, priority?}], shot_order?: [ids]}`. Updates the current version in place; a broken rule becomes a `warnings` entry, not an error. |
| POST | `/projects/{id}/shoot-plan/regenerate` | `{scope, target_id?, instruction?}` → 202 |
| GET | `/projects/{id}/shoot-plan.pdf` | export |
| POST | `/projects/{id}/share` | creates `share_token` → `{url}` |
| GET | `/share/{token}` | public, read-only plan (no auth, no owner data) |
| GET | `/share/{token}/shoot-plan.pdf` | public PDF of the shared plan |
| DELETE | `/projects/{id}/share` | revoke the link |

## Footage & Assembly
| Method | Path | Notes |
|---|---|---|
| POST | `/projects/{id}/footage` | `{asset_ids:[…]}` → starts per-clip processing |
| GET | `/projects/{id}/footage` | clips + processing status |
| POST | `/projects/{id}/coverage-check` | → 202 → `{shots:[{shot_id, status, clip_ids, note}]}` |
| POST | `/projects/{id}/assemble` | `{options?:{music_asset_id?, skip_beat_sync?}}` → 202 → timeline id |

## Timelines & Renders
| Method | Path | Notes |
|---|---|---|
| GET | `/timelines/{id}` | |
| GET | `/projects/{id}/timelines` | version history |
| PATCH | `/timelines/{id}` | `{ops:[TimelineOp…]}` → new version |
| POST | `/timelines/{id}/render` | `{preset:"preview"\|"final"}` → 202 |
| GET | `/renders/{id}` | `{status, url}` (presigned) |

## Library
| Method | Path | Notes |
|---|---|---|
| GET | `/library/music?bpm_min&bpm_max&mood` | user + starter pack |
| GET | `/library/sfx?type=whoosh` | |

## Jobs
| Method | Path | Notes |
|---|---|---|
| GET | `/jobs/{id}` | |
| GET | `/jobs/{id}/events` | SSE: `progress`, `done`, `error` events |
| POST | `/jobs/{id}/retry` | failed jobs only |
