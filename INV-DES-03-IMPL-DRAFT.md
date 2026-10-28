# INV-DES-03-IMPL-DRAFT — Invest-skill governed implementation planning

- **Status:** PROPOSED / BLOCKED. This is a planning handoff only; no implementation authorization, no `READY_FOR_CODE`, no runtime/data access.
- **Owner:** investPM (contract and governance only).
- **Objective:** Close static design evidence and coverage gaps in INV-DES-03, then request a separately scoped, user-approved engineering owner/QA before any code task.
- **Scope:** Read-only analysis and local governance documents within the invest-skill workspace. No source edits, scripts, tests, CLI, SQLite, provider, network, credentials, runtime artifacts, expert-panel/wiki, schedule, or release changes.
- **Non-goals:** No implementation, dynamic validation, candidate SHA freeze, READY_FOR_CODE, real external data, provider/credentials, publishing, or out-of-workspace access.
- **Dependencies:** User's 2026-10-19 supervised-resumption notice; current INV-DES-03 v4.75; read-only repo status.

## Three proposed leaf tasks

### INV-DES-03-B1B6-READONLY-01 — Evidence map / infeasibility decision
- **Owner:** investPM.
- **Permission:** Read-only source/design inspection and local governance note only.
- **Dependencies:** Existing B1–B6 candidate requirements in `INV-DES-03-MATRIX-INDEX.md`; no source or runtime access beyond repository text.
- **AC:** For each B1–B6, record evidence path/line and distinction among verified fact, assumption, unknown; explicitly distinguish integrity hashes from authenticity/authorization; if no independent trust boundary is evidenced, document current-model infeasibility and retain fail-closed. Do not infer absence outside repo.
- **Deliverable:** B1–B6 evidence table/update to contract with exact references and bounded conclusion.
- **ETA:** 2026-10-19 14:00 +08, subject to no new scope.

### INV-DES-03-REM-MAP-READONLY-01 — Deduplicated REM static mapping
- **Owner:** investPM.
- **Permission:** Read-only review of repository source; local matrix documentation only.
- **Dependencies:** Existing REM-01..09 grouping; re-use already confirmed cleanup/cron and verify_manifest entries without recounting.
- **AC:** Each REM group has unique module/call-site rows only where inspected, production/test/out-of-repo distinctions, evidence path/line, verified-static vs not-checked vs dynamic-pending-auth state, explicit exclusions; no totals, coverage percentages, or ETA unless denominator is demonstrably closed. Known cron rm exit-propagation issue stays confirmed, not “unknown”.
- **Deliverable:** Updated REM matrix with evidence and exclusion ledger.
- **ETA:** 2026-10-20 12:00 +08; scope is still large and ETA is a checkpoint, not completion promise.

### INV-DES-03-REVIEW-75-READONLY-01 — Independent bounded document review
- **Owner:** 投研复核 (proposed; WAIT_ACK until explicit response).
- **Permission:** Read-only review of the produced B1–B6/REM contract and evidence map only; no code/tests/runtime/data.
- **Dependencies:** Tasks B1B6 and REM-MAP deliver stable v4.76-or-later record plus exact paths/lines; reviewer must ACK scope and ETA first.
- **AC:** Check version/time consistency, evidence classifications and exclusions, duplicate counting, threat-model distinction, and whether no unverified item was promoted to PASS; return PASS/FAIL/BLOCKED with cited lines and precise corrections. This is not engineering QA.
- **Deliverable:** Written bounded review verdict in invest-skill group.
- **ETA:** Within 2 hours after ACK and receipt of complete package; no execution until ACK.

## Global controls / rollback
- Tasks 1–2 are the only PM-owned active prep; no source modifications. If scope changes or evidence conflicts, stop and return item to design review.
- After each local governance edit, read back and check consistency. Revert only the exact PM-authored document change if it introduces inconsistency; do not clean unrelated dirty/untracked worktree files.
- No code/tests or any external side effects; all permissions remain as above. Project remains BLOCKED / non-READY_FOR_CODE.
