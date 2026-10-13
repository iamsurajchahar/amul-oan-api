# CLAUDE.md

Project memory for Claude Code sessions on this repo. Loaded automatically at session start.

## Telemetry layer plan (saved 2026-10-13 at the user's request)

Source: GitHub issue #3 "Telemetry layer: one uniform, reliable store" in the telemetry
repo (the new home for telemetry code; exact repo name not confirmed). Opened by
KDwevedi on 2026-10-12, assigned to iamsurajchahar (the user), project AMUL.
KDwevedi commented: "@iamsurajchahar Taking a crack at 2a and 2b" (read as: the two
"Move everything here and clean out amul-oan-api" items below).

## What this is for
One store for all chat and voice telemetry, in a single format, converted losslessly
from every era of the Langfuse traces. Everything downstream (exports, APIs, dashboards,
reports) reads from it, and it must not break when the apps change what they send.

## Where the current work falls short
- The current adapters throw data away: question and answer text and user ids are hashed;
  tool results, model, tokens, cost, score values and most of each turn's steps are
  never stored.
- eras.yaml is wrong in places: it marks voice text as unrecoverable, but the text is
  there in every era.

## The APIs are premature
- The ~10 query endpoints sit on that lossy table, so they cannot replace the exports or
  produce Amul's report. Each becomes a contract that cannot change once Amul depends on it.
- They are too specific; no consumer benefits from separate APIs over functionally the
  same queries. They can exist later, purposefully, not as the first draft.

## Tasks (0 of 6 sub-issues done as of 2026-10-13)
1. Clean up first (the one-time transform depends on it):
   - #4 Importer misses turns with no traces row (before 2026-06-09)
   - #5 Correct the voice eras in eras.yaml
   - #6 Correct the chat eras in eras.yaml
   - #7 Cut-off turns are recorded as delivered
   - #8 Chat traces carry Langfuse release voice-oan-api
   - #9 Docs, comments and Langfuse MCP notes repeat the wrong era claims
2. Move everything to the telemetry repo and clean out amul-oan-api:
   - (2a) Move the telemetry code there: import, adapters, eras, mappings, API (#11
     "Move the telemetry import, adapters and query API here from amul-oan-api").
   - (2b) Remove it from amul-oan-api, including the telemetry router the chat app
     mounts (issue cites main.py:111; on main today it is main.py:108
     `app.include_router(telemetry.router)`). The apps keep only what they send.
3. One shape (turn shape v1, below). Keep it in the telemetry repo as one registry:
   each field declared once, everything else generated from it or checked against it
   in CI. No duplicated mapping code.
4. Both apps emit it in prod.
5. Transform history into it once, into a new Langfuse ClickHouse database. Verify
   against the original, then point Langfuse at it. The original stays as the backup
   until verified.
6. One simple API for raw queries: cursor pagination that stays stable while new data
   lands; date filters and field filters. Done when the exports UI and Amul's monthly
   report can run off it.
7. Dashboards: an alerts dashboard (freshness, traces that don't match the shape),
   checked daily. Agree the rest of the list this week, implement after.

## Open decisions
- Import chat's first era (02-02 to 03-10, 8,063 turns)?
- The 02-10 voice spike (22,898 agent runs against about 600 a day): real traffic or a test?
- Drop stt_signal_auto_hangup? Keep voice v1 marked as never in prod, or remove it?
  Add the chat backend roots to the non-turn list?
- How long raw text and phone numbers are kept.
- Default count: what the farmer said (utterances) or every request?

## Turn shape v1 (draft 2026-10-12)
The one shape every turn is sent to Langfuse in, for every pipeline (webapp, whatsapp,
telephony). History is transformed into it once.

### Root trace (one per turn)
| Field | Type | Required | Values |
|---|---|---|---|
| name | string | yes | `turn` (same for every pipeline) |
| input | string | yes | Original question, as typed or as STT text for this request |
| output | string | yes | Answer as delivered, in the target language (telephony: the chunks actually spoken) |
| sessionId | string | yes | Source session id |
| userId | string | when known | Raw phone or id, unhashed |
| level, statusMessage | | on error | `ERROR` and the reason when amul.outcome = error |
| amul.schema_version | string | yes | `turn.v1` |
| amul.kind | string | yes | `turn` (`background_job`, `frontend_event` for non-turn traces) |
| amul.pipeline | string | yes | `webapp`, `whatsapp`, `telephony` |
| amul.direction | string | yes | `inbound`, `outbound` |
| amul.provider | string | telephony | `raya` |
| amul.service | string | yes | `amul-oan-api`, `voice-oan-api` |
| amul.release | string | yes | Git commit of the running code |
| amul.source_lang, amul.target_lang | string | yes | `gu`, `hi`, `en`, `mr`, `pa`, `bn` |
| amul.translation_mode | string | yes | `direct`, `translated` |
| amul.pipeline_profile | string | yes | `oss`, `legacy`, or another configured profile |
| amul.persona | string | no | `farmer`, `doctor` |
| amul.outcome | string | yes | `success`, `error`, `cancelled`, `moderation_rejected`, `stale_request`, plus telephony fast paths (`stt_signal`, `hold_message`, `greeting_fast_path`, `identity_fast_path`, `fragment_fast_path`, `non_meaningful_hangup`, `outbound_declined`, `outbound_no_data`, `pretranslation_empty`) |
| amul.farmer_id | string | when known | Phone as 10 digits; absent for anonymous users |
| amul.call_id | string | telephony | One id per call: the provider's, else generated at call start |
| amul.process_id | string | telephony | Provider's request id |
| amul.request_epoch | integer | telephony | Session ownership epoch this request held |
| amul.utterance_id | string | telephony | Trace id of the first request for this utterance (its own id if none was superseded) |
| amul.superseded_by | string | with stale_request | Trace id of the request that took over |
| amul.parent_turn_id | string | non-turn only | Trace id of the turn that caused it, when there is one |

Metadata values are flat strings or numbers. Only the turn runner writes trace-level
fields; no step may update the trace.

### Child steps (all nested under the root: one turn is one trace)
- `pre_translation` GENERATION: original text in, English out. Absent when direct.
- `moderation` GENERATION: text in, `{rejected, category, reason}` out.
- `agent` AGENT: English question in, English answer out.
  - `chat <model>` GENERATION (pydantic-ai's name): messages, model, usage, cost.
  - `<tool name>` TOOL: arguments in, result out, `amul.tool_status` (`success`, `empty`,
    `no_result`, `unavailable`, `error`), `amul.cache` (`hit`, `miss`); level = ERROR
    and statusMessage on failure.
  - API SPANs (current names, e.g. `fetch_farmer_amulpashudhan`): `{ok, status_code,
    fetch_reason}` out; level = ERROR on failure.
- `post_translation` SPAN: English answer in, delivered text out; one
  `stream_translation` GENERATION per chunk.
- `suggestions` GENERATION: may finish after the root.
- Telephony only, optional: `non_meaningful`, `outbound_consent`, `nudge`,
  `farmer_context`, `history_write`.

### Scores (all on the turn trace)
- `turn_outcome` (CATEGORICAL, equals amul.outcome)
- `served_tier` (CATEGORICAL, per-step tier string)
- `user_feedback` (NUMERIC rating, comment = text; the frontend gets the trace id in the
  chat response)

### Non-turn traces
Root `background_job` (`amul.job`: `farmer_background_refresh`, `cache_fill`, ...) or
`frontend_event` (`amul.event`: `question`, `question_response`, `error`, `feedback`,
`anonymous_token_issued`), with the same base amul.* keys and `amul.parent_turn_id`
when a turn caused it.

### Follow-ups listed under the shape
- Transform history once into a new Langfuse ClickHouse database, per era, using the
  corrected eras (#5, #6).
- Build the trace rows Langfuse never wrote (#4) during that transform.
- Before switching, confirm CLICKHOUSE_DB works on our Langfuse (3.225.4), and how
  Langfuse merges a late event into a transformed row.
- Make amul-oan-api's app/turn runner the single emitter; voice-oan-api emits the same
  shape until voice cuts over.
- Voice stops sanitising root text (voice_trace_text_mode).
- Stamps ship to prod; none has ever reached it.
- Cut-off turns recorded as delivered (#7).
- Chat's Langfuse release says voice-oan-api (#8).
- Keep this contract in the amul-telemetry registry; each app's CI checks traces from
  its test turns against it.

## Related references mentioned on the issue
- #10 Correct eras.yaml from the 10-12 prod validation
- amul-oan-api#365 Telemetry: versioned contract, export and dashboards
- memory_backend#2 Add scheduled text-chat memory worker
- amul-oan-api#367 Add canonical farmer identity to memory traces
- amul-oan-api#362 Enable farmer memory in Amul AI chat (merge feat/memory_v0, deploy
  the memory writer)

## Where the code sits in amul-oan-api (checked 2026-10-13, main at 4d2bb31)
- Frontend telemetry ingest (what the chat app sends): `app/routers/telemetry.py`
  (`POST /observability-service/action/data/v3/telemetry`), mounted in `main.py:108`;
  worker in `app/tasks/telemetry_queue.py`; `app/services/telemetry_mapper.py`,
  `app/services/telemetry_normalizer.py`, `app/services/langfuse_telemetry_writer.py`,
  `app/models/telemetry.py`.
- The importer, adapters, eras.yaml, mappings and query API are NOT on main. They live
  under `telemetry/` on branches such as `feat/chat-telemetry-import`,
  `feat/voice-telemetry-import`, `feat/telemetry-query-api`,
  `feat/telemetry-api-standalone`, `feat/telemetry-dashboard-queries`,
  `fix/eras-registry-gaps` (files: `telemetry/eras.yaml`, `telemetry/mappings/{chat,voice}.yaml`,
  `telemetry/contracts/{chat,voice}.turn.v1.json`, `telemetry/clickhouse/*.sql`,
  `telemetry/consumers.yaml`, `telemetry/non_turn_traces.yaml`).
- Related branches: `chore/remove-telemetry-reading`, `refactor/run-turn-surface-telemetry`.
