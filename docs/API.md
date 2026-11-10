# API (FastAPI, `/api/v1`)

All long operations return `202 {job_id, resource_id}`. Track them with `GET /jobs/{id}` or SSE `GET /jobs/{id}/events`.
Errors: `{"error": {"code": "INGEST_PRIVATE_VIDEO", "message": "…", "hint": "Upload the file instead"}}`.

## Uploads
| Method | Path | Body → Response |
|---|---|---|
| POST | `/uploads` | `{filename, size, content_type, kind}` → `{asset_id, parts:[{part_number, url}], upload_id}` |
| POST | `/uploads/{asset_id}/complete` | `{upload_id, parts:[{part_number, etag}]}` → `{asset}` + enqueues proxy |

## References & Styles
| Method | Path | Notes |
|---|---|---|
| POST | `/references` | `{url}` or `{asset_id}` → 202, starts the analysis DAG |
| GET | `/references/{id}` | status + derived keys |
| GET | `/style-profiles` | list (library) |
| POST | `/style-profiles` | `{reference_id, name}` (auto-created on analysis success) or `{blend:[{profile_id, weight}]}` |
| GET | `/style-profiles/{id}` | profile with overrides applied + contact-sheet URLs |
| PATCH | `/style-profiles/{id}` | `{overrides: {"/captions/highlight_color": "#00FF88"}}` |
| DELETE | `/style-profiles/{id}` | |

## Projects & Plan Mode
| Method | Path | Notes |
|---|---|---|
| POST | `/projects` | `{style_profile_id, title, brief}` |
| GET/PATCH | `/projects/{id}` | |
| POST | `/projects/{id}/shoot-plan` | generate → 202 |
| GET | `/projects/{id}/shoot-plan` | current version |
| PATCH | `/projects/{id}/shoot-plan` | manual edits (re-validated) |
| POST | `/projects/{id}/shoot-plan/regenerate` | `{scope, target_id?, instruction?}` → 202 |
| GET | `/projects/{id}/shoot-plan.pdf` | export |
| POST | `/projects/{id}/share` | read-only plan link |

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
