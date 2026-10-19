# INV-DES-03 Formal Task Ledger

- **Ledger status:** Formal project task record in the invest-skill workspace; task assignments remain subject to group-visible ACK. This file is the single ledger for these three tasks; do not create a parallel task board.
- **Project status:** INV-DES-03 remains IN_PROGRESS / BLOCKED, not READY_FOR_CODE. Supervised resumption permits governance coordination, design/task breakdown, repository read-only inspection, and local governance-document edits only.
- **Global prohibited scope:** No source/code implementation or modification, tests/scripts/CLI/SQLite execution, dynamic validation, candidate SHA freeze, runtime artifacts or real external data, providers, credentials, expert-panel/wiki edits, release/publishing, push/merge/PR, or out-of-workspace access. Any newly restricted action requires separate user approval. Do not alter unrelated dirty/untracked files.
- **Record location:** `INV-DES-03-TASKS.md` (workspace-relative path).

## INV-DES-03-B1B6-READONLY-01 — Map identity evidence

- **Status:** DONE — PM self-owned bounded static evidence-map deliverable recorded in `INV-DES-03-MATRIX-INDEX.md:23-33`; identity gate remains BLOCKED and independent review is not yet done. This is not code/QA/dynamic validation approval.
- **Owner:** investPM.
- **Permission:** Read-only inspection of repository source and governance contracts; local governance-document edits limited to this ledger and named INV-DES-03 governance records. No source modification or runtime/data access.
- **Dependencies:** Current INV-DES-03 contract v4.75 and identity criteria B1–B6 in `INV-DES-03-MATRIX-INDEX.md`.
- **Acceptance criteria:**
  1. Map each of B1–B6 individually to exact repository path and line(s), or mark `UNKNOWN / NOT EVIDENCED`.
  2. Classify each statement as verified repository fact, assumption, or unknown; do not infer absence beyond the inspected repository.
  3. Distinguish hash/recomputation integrity or content consistency from source authenticity and authorization.
  4. Identify attacker capabilities, authoritative identity inputs, and write/replace boundaries only where supported by evidence.
  5. If no independently protected trust/authorization boundary is evidenced, state bounded current-model infeasibility and keep the gate fail-closed; do not claim identity design passes.
- **Deliverable:** B1–B6 evidence map and bounded decision recorded in `INV-DES-03.md` and/or `INV-DES-03-MATRIX-INDEX.md`, with precise citations.
- **Status detail:** B1–B6 evidence map and bounded infeasibility decision are recorded in `INV-DES-03-MATRIX-INDEX.md:23-33`; reviewer acceptance is separate and still pending. TASK-1 deliverable is complete at its bounded static/governance-document scope; no identity gate PASS is implied.
- **Evidence snapshot:** A bounded B1–B6 table was drafted in the formal matrix index based on repository paths/lines inspected. B1: report-gates lists sequence only; direct in-repo calls to checklist_audit were not located by bounded shell/Python searches, which does not establish absence of external/dynamic callers. B2: the repository text describes the required threat model but does not evidence a distinct protected identity authority. B3: snapshot/meta.batch_id and native plan fields exist, but a unique authorized claim/owner/attempt binding independent of the same writable runtime is not evidenced. B4: the checklist reader globs/concatenates matching files and the validator sections by expert_id without batch/hash checks; a trusted authoritative seven-result SHA inventory is not evidenced. B5: prepare writes staged files then performs multiple os.replace calls; interruption/retry/repair invalidation across all paths is not established as an atomic identity protocol; repair baseline is local integrity/structure control only. B6: checklist_audit read errors return nonzero, but report_path is explicitly read and --code has no identity gate; coverage failure propagation to all production consumers is not established. This is repository-bounded evidence; no inference about out-of-repo controls.
- **Bounded decision:** No independently protected, authoritative identity source binding the frozen batch/claim/attempt and seven result digests is evidenced in the reviewed repository. Under the current evidenced permission model, a trustworthy checklist identity gate is not demonstrable; current model is bounded-infeasible absent such authority. Keep stage-A fail-closed; do not calculate coverage from any --code glob hit. This is a design conclusion, not implementation or dynamic PASS.
- **Escalation classification:** YES — a user-level decision is required before any proposal to introduce/procure an independent authoritative identity source or signing/approval mechanism; this ledger records the need only and does not itself request authorization or initiate such work.
- **Checkpoint:** 2026-10-19 14:00 +08, a progress checkpoint only, not a completion promise.
- **Rollback:** If the document edit creates inconsistency, revert only that exact authored edit; preserve all pre-existing workspace changes.

## INV-DES-03-REM-MAP-READONLY-01 — Deduplicate REM coverage

- **Status:** IN_PROGRESS — PM self-owned bounded static mapping; partial evidence added for selected REM-01 and REM-03 rows, but not the complete REM-01..09 mapping. No acceptance by another member is implied.
- **Owner:** investPM.
- **Permission:** Read-only repository source inspection and local governance-document edits limited to this ledger and the matrix records. No source modification, runtime/data access, or execution.
- **Dependencies:** Existing REM-01..09 group scopes in `INV-DES-03-MATRIX-REMAINING.md` and current v4.75 contract baseline.
- **Acceptance criteria:**
  1. Record only production modules/call-sites actually inspected, with path/line references, callers/arguments where evidenced, and read/write/delete classification.
  2. Separate production, test-only, and out-of-repository/unknown boundaries; record roots/path parameters, failure behavior, and explicit exclusions where inspected.
  3. Distinguish `VERIFIED_STATIC`, `CORROBORATED`, `NOT_CHECKED`, `OUT_OF_SCOPE/UNKNOWN`, and `DYNAMIC_PENDING_AUTH`; do not use grep/AST counts as completion evidence.
  4. Do not invent a denominator, coverage percentage, or overall ETA. Keep cron `rm -f` exit-propagation gap as a confirmed existing gap; do not recount confirmed cleanup/cron coverage.
- **Deliverable:** Deduplicated REM-01..09 mapping and exclusion ledger in `INV-DES-03-MATRIX-REMAINING.md`, with aligned index pointers as needed.
- **Partial evidence delivered (bounded, not full task completion):** REM-01 `VERIFIED_STATIC` for the inspected checklist reader/validator, collect_results check path and report-gates contract; direct production caller graph and denominator remain unknown. REM-03 `VERIFIED_STATIC` for the cited cleanup candidate enumeration/deletion and assemble/cron call sequences; exact production call-site denominator, effective roots/permissions and runtime lease overlap remain unknown or dynamic-pending-auth. These are details of existing modules/call paths, not additional modules; no incident is claimed. REM-02/04–09 retain their existing statuses and are not claimed complete. Evidence is in `INV-DES-03-MATRIX-REMAINING.md:15,17`; TASK-2 remains IN_PROGRESS, not a signed-off full matrix.
- **Checkpoint:** 2026-10-20 12:00 +08, a progress checkpoint only, not a completion promise.
- **Rollback:** If the document edit creates inconsistency, revert only that exact authored edit; preserve all pre-existing workspace changes.

## INV-DES-03-REVIEW-75-READONLY-01 — Independent bounded document review

- **Status:** COMPLETED — bounded stage review returned `FAIL` for the submitted partial package; TASK-3 ledger status is corrected from WAIT_ACK to completed-for-bounded-verdict only. This is not full REM sign-off, overall design approval, or engineering QA.
- **Owner:** 投研复核 (ACKed and performed the bounded review).
- **Permission:** Read-only review of the stable B1–B6 evidence map and REM matrix documents only. No code/source execution, tests, runtime/data, provider, credentials, or engineering-QA claims.
- **Dependencies:** Stable, readable B1–B6 mapping and bounded REM-01/03 excerpts were available at the cited matrix paths; REM-02/04–09 remain incomplete and outside this stage verdict. Reviewer ACKed the bounded stage review in the group and stated ETA within 2 hours after complete package.
- **Acceptance criteria:** Check version/time consistency, evidence classifications and exclusions, duplicate counting, integrity-versus-authenticity/authorization threat-model distinction, and whether any unknown/unverified item was promoted to PASS. Return `PASS / FAIL / BLOCKED` with cited lines and precise corrections. This is not engineering QA.
- **Deliverable/result:** 投研复核 reported `FAIL` for ledger consistency: B1–B6 mapping and REM-01/03 bounded evidence passed locally, but this ledger incorrectly remained WAIT_ACK and said review could only start after all tasks completed. Update this TASK-3 record to capture the bounded review while retaining all residual blocks. Evidence: group verdict and `INV-DES-03-MATRIX-INDEX.md:23-33`, `INV-DES-03-MATRIX-REMAINING.md:15,17`.
- **Residual scope:** REM-02/04–09 are not reviewed or passed; overall identity gate remains BLOCKED / not READY_FOR_CODE. Any broader review requires a new/renewed group-visible scope and ACK.
- **Next action:** PM records this bounded verdict and maintains TASK-1/2 incomplete status; do not promote partial review to full completion.

## Group-visible assignment / acceptance log

- `2026-10-19 13:13 +08`: Ledger path `invest-skill/INV-DES-03-TASKS.md` posted in `invest-skill开发群`; Chief and 投研复核 confirmed the shared task board is empty, and Chief designated this workspace ledger plus the group assignment as the mutually readable record mechanism.
- `2026-10-19 13:13 +08`: TASK-1 and TASK-2 are PM self-owned, supervised-scope, read-only/governance work; marked IN_PROGRESS by PM only. This is not another member ACK.
- `2026-10-19 13:14 +08`: Unique ledger was re-read and status aligned: TASK-1/2 are PM self-owned IN_PROGRESS under supervised read-only/governance-document scope; shared task board remains empty and is not used as proof. In the group, investPM posted all three TASK-IDs, fields, permissions, relative path and prohibited scope.
- `INV-DES-03-REVIEW-75-READONLY-01`: 投研复核 initially kept WAIT_ACK while artifacts were missing; after the B1–B6 index and REM-01/03 excerpts were made readable, 投研复核 explicitly ACKed a bounded stage review and stated ETA within 2 hours after complete package. Scope excludes REM-02/04–09 sign-off and overall design/engineering QA.

