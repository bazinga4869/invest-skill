# INV-DES-03-STATIC-INVENTORY-PLAN-01 — Limited static inventory extension

- **Revision:** v1.1, plan only; supersedes the blocked embedded plan candidate whose `INV-DES-03-TASKS.md` SHA-256 was `0cf7e2e1f58b13432392b05163d3ff130adfc6823deb13935b0e33f35eec39b2`.
- **Status / owner / gate:** `PLAN_PROPOSED / WAITING_INDEPENDENT_PLAN_REVIEW_AND_LEAD_WRITTEN_RELEASE`; owner investPM (plan coordination only). The immutable SHA of this standalone plan is recorded in `INV-DES-03-TASKS.md`. This is not authorization to read source files, enumerate directories, create a manifest, or start inventory work. No `READY_FOR_CODE`.
- **Purpose:** Continue the already named REM-01..09 candidate mapping without claiming an exhaustive repository audit. Keep candidate IDs and the existing TASKS 35–42 evidence/dedup rules; report unknowns explicitly.

## 1. Boundary and proposed approved roots

The later inventory may use only repository-relative roots named here, and only after (a) independent PASS on this exact plan-file SHA and (b) a separate written Lead release naming this same SHA and the exact authorized roots/method. The expected repository root is `/Volumes/MacData/workspace/invest-skill`; the release must restate the resolved absolute root and STOP on mismatch.

Proposed root allowlist (Lead may narrow it; any expansion requires a revised plan and another independent review):

1. `scripts/` and its descendants;
2. `shared/` and its descendants;
3. `tests/` and its descendants;
4. the exact file `references/execution.md`;
5. the exact file `references/automation.md`.

No other `references/` contents, repository-root files, `config.yaml`, `.git/`, `data/`, runtime/state/report/cache paths, external repositories, database files, credentials, or provider state are in scope. The Lead release must list the selected root IDs and state whether metadata-only path enumeration is authorized. No directory listing or file read is authorized by this plan alone.

The following contract-named root-shell basenames remain unresolved path candidates, not approved roots or manifest paths: `daily_analysis.sh`, `cron_trigger.sh`, `run_experts.sh`, `run_challenges.sh`, `run_cross_reviews.sh`, `activity_log.sh`, `alert.sh`, `watchdog.sh`, `reports_today.sh`, `pending_stocks.sh`, `cron_hermes_daily.sh`, `cron_hermes_push.sh`, `agent_backend.sh`. Do not infer repository-root paths or search for them. They remain `PATH_UNRESOLVED` until an authorized Lead record supplies the exact repository-relative paths and a separate release explicitly includes those paths. Existing `scripts/` matrix paths remain the baseline where already recorded.

## 2. Path-only manifest, canonical identity, and symlinks

After both gates, and only for the released roots, produce a path-only manifest before reading source content. Each row records `root_id`, canonical repository-relative path, entry kind if available without dereferencing, existing candidate IDs or `UNMAPPED_PENDING_DESIGN`, and the provenance for how the path entered the manifest. The manifest is not a source-content hash list and does not define a repository-wide denominator.

Canonical path rules:

- A manifest path is relative to exactly one `root_id`, uses `/` separators, and has no leading slash, empty component, `.` component, or `..` component; reject invalid forms rather than silently rewriting them.
- Preserve path case and the exact Unicode sequence returned for the directory entry. Do not case-fold, Unicode-normalize, call `realpath`, resolve aliases, or use filesystem inode/content identity for deduplication. If a path cannot be represented losslessly, mark `PATH_IDENTITY_UNKNOWN` and STOP on that row.
- The duplicate key is `(root_id, canonical_relative_path)`. Exact duplicate keys merge into one manifest row while retaining all observation references. Equal path strings under different root IDs remain separate. Hardlinks and other physical aliases are not identified or merged; mark physical identity `NOT_CHECKED`.
- Never follow symlinks. If the released path-only method permits `lstat` metadata, record a symlink as `SYMLINK_NOT_FOLLOWED` and do not read its target. Do not `stat`, resolve, traverse, or read through a link. If entry kind cannot be established safely, or a link would cross an approved-root boundary, record `SYMLINK_STATUS_UNKNOWN`/`OUT_OF_SCOPE_SYMLINK` and STOP on that row. This is not dynamic symlink, redirect, or TOCTOU validation.

The manifest's own SHA-256, if required, is recorded separately from every source-file SHA and must cite the authorized generation/measurement record. Do not infer file count, candidate denominator, or percentage from grep/AST counts.

## 3. Known candidate names (not exhaustive)

The names below are only paths already present in current contract/matrix text; they do not establish that other paths do not exist. Newly enumerated entries under an approved root remain unknown until the authorized manifest is produced.

- `scripts/`: `activity_log.sh`; `agent_backend.sh`; `alert.sh`; `assemble_report.py`; `calibrate_scores.py`; `checklist_audit.py`; `cleanup_intermediates.py`; `collect_challenges.py`; `collect_cross_reviews.py`; `collect_results.py`; `corpus_ready.py`; `cron_hermes_daily.sh`; `cron_hermes_push.sh`; `cron_trigger.sh`; `daily_analysis.sh`; `execution_provenance.py`; `expert_result_v3.py`; `native_agent_tasks.py`; `normalize_challenge.py`; `pending_stocks.sh`; `pick_stocks.py`; `prewarm_corpus.py`; `prepare_challenges.py`; `prepare_cross_reviews.py`; `prepare_prompts.py`; `preserve_failure_evidence.py`; `reports_today.sh`; `run_challenges.sh`; `run_cross_reviews.sh`; `run_experts.sh`; `runtime_guard.py`; `trace_health.py`; `trace_wrapper.py`; `validate_prompt_bundle.py`; `verify_manifest.py`; `verify_report.py`; `watchdog.sh`.
- `shared/`: `checklist_verify.py`; `contracts.py`; `data_tools.py`; `project_config.py`; `report_wiki.py`; `runtime.py`; `sage_wiki.py`; `trace.py`.
- `tests/`: `integration_test.sh`; `stub_agent.py`; `test_data_contracts.py`; `test_native_agent_tasks.py`; `test_report_gates.py`; `test_report_wiki_contract.py`; `test_runtime_contracts.py`; `test_sage_wiki_contract.py`; `test_semiannual_extract.py`.
- Exact reference files: `references/execution.md`; `references/automation.md`.

## 4. Per-file questions and evidence record

For each authorized manifest row, ask only the released questions: (1) existing TASK-ID/candidate ID or explicit `NOT_CHECKED` reason; (2) static read/write/append/replace/delete/mkdir/rename/copy, database API, network/provider, or subprocess operations and exact source lines; (3) caller/argument/cwd/path-root provenance and whether the path stays in the released boundary; (4) permission source or `UNKNOWN` (no `stat` unless separately authorized); (5) error/timeout/partial-write/cleanup/retry/fail-closed branches; (6) production/test/docs/support classification and dedup reference; (7) residual unknowns and exact stop/authorization dependency.

Every evidence row records task/candidate ID, `root_id`, canonical relative path, exact line range if source reading is released, evidence type (`CONTRACT`, `MATRIX`, or authorized `STATIC_SOURCE`), operation/classification, caller/path evidence, permissions or `UNKNOWN`, failure behavior, dedup key/reference, disposition (`VERIFIED_STATIC`, `CORROBORATED`, `NOT_CHECKED`, `OUT_OF_SCOPE/UNKNOWN`, or `DYNAMIC_PENDING_AUTH`), residual risk, reviewer, immutable review-target SHA, and timestamp.

**Source SHA provenance:** A source-file SHA may be recorded only from an authorized Lead manifest/record that identifies the exact path and value, or when a separate written release expressly permits hashing that exact named file. In the latter case compute a content SHA-256 from the authorized file bytes and record exact command, path, time, and result. If neither provenance is available, set `source_sha256=UNKNOWN`. Never inspect `.git`, infer a SHA from a Git object/history, substitute a manifest SHA for a source-file SHA, or hash unnamed files.

## 5. NOT_CHECKED, reconciliation, and completion language

If a new candidate is encountered within an authorized root, add only a minimal row using its existing ID if available (otherwise `UNMAPPED_PENDING_DESIGN`), exact path/line or discovery reference, dedup/status fields, and `NOT_CHECKED`; then stop substantive classification for that candidate and request PM/Lead design disposition. This row is a recorded unresolved item, not PASS, not proof of coverage, and not a basis to declare the inventory complete.

`TASKS 35–42` permits explicit `NOT_CHECKED` and `DYNAMIC_PENDING_AUTH` carry-forward states. A bounded result may be called `BOUNDED_RECONCILED_WITH_UNRESOLVED_ITEMS` only after every path in the authorized manifest and every currently named candidate ID has a row/disposition, duplicates and cross-group dedup references are reconciled, and the applicable independent review is recorded. Carry-forward rows remain unresolved and must be listed. This status does not imply exhaustive repository coverage, a complete physical-file universe, dynamic validation, or TASK-2 acceptance. Any later candidate found in already scoped materials must be added and reconciliation reopened before the bounded result is re-presented.

## 6. Exclusions and stop conditions

No reads of runtime/data/config/secrets, `.git/`, databases, external repositories or providers; no database connection, test execution/import/collection, CLI, shell command, script, network or provider invocation; no source/config edits, cleanup, deletion, knowledge-base or expert-panel changes; no dynamic permission, symlink-target, redirect, concurrency, or TOCTOU validation; no repo-wide search or grep/AST denominator.

Test source may be read only after the separate release explicitly authorizes each test path; tests are never executed, imported, collected, or used to claim isolation/safety. An unapproved path, unresolved root/basename, path identity ambiguity, symlink ambiguity, candidate/SHA drift, missing required SHA provenance, excluded data/runtime need, dynamic-evidence need, or newly found candidate stops the affected branch and returns it to PM/Lead. Do not continue by broadening scope or assigning new TASK-IDs.

Before any source read, both gates must be documented: (1) independent plan review PASS on this exact standalone plan SHA; and (2) separate written Lead release naming the same plan SHA, absolute repository root, selected root IDs/exact paths, permitted path-manifest metadata method, exact source paths/lines allowed, any file-hash method, test-source-only permission if applicable, exclusions, stop conditions, and rollback. A plan review is not engineering QA; a Lead release is not implied by review PASS.

## 7. Rollback and current state

This plan has no source, runtime, or data effects. Revert only this plan/ledger text if it creates inconsistency. Until both gates are met, source reading, directory enumeration, manifest creation, and inventory execution remain STOP.
