# INV-SYNTHETIC-INPUT-DESIGN-01 — Synthetic data seam for bounded smoke

- **Status:** WITHDRAWN / SUPERSEDED by chief's 2026-10-20 group decision: use a schema.sql-based synthetic SQLite fixture through existing INVEST_DB_PATH; do not introduce a production fetch_data injection bypass. The remaining proposal text is retained as history, NOT an approved implementation plan. New leaf INV-SMOKE-01-SQLITE-FIXTURE-01 requires an explicit field/period/source contract before READY_FOR_CODE. Product source changes remain out of scope.
- **Owner:** investPM (design and task breakdown). Implementer and independent engineering QA: UNASSIGNED, requiring user-approved role designation after roster review. 投研流程 is an orchestration role, not automatically an implementer; 投研复核's read-only review is not engineering QA. No implementation may start before design acceptance and PM READY_FOR_CODE.
- **Dependency:** Failed `INV-SMOKE-01` evidence: `prepare_prompts.py` in `INVEST_TEST_MODE=1` still invokes `data_tools.py all`; isolated SQLite lacks the stock/market/financial fields required by the analysis path, and no documented synthetic fixture injection seam exists.

## Source-backed diagnosis (2026-10-20)

- `scripts/prepare_prompts.py:241-291`: test mode plus skip-sync suppresses only `sync` (244-257); `data_tools.py all` is still invoked unconditionally (258-261). Nonzero exits are propagated (262-271); returned JSON is checked by quality envelope, recomputed snapshot validation and requested-code equality (276-290). These checks must remain on any fixture seam.
- `.smoke-tmp/runtime/prepare.stderr:1`: missing stock identity, market date/close/market cap, annual/quarterly/balance/indicators/audit fields explain the observed exit 2. This demonstrates rejection of incomplete input, not a proven production data-path bug.
- `tests/test_runtime_contracts.py:199-230`: a prompt-construction test fixture exists, but it lacks the full acquisition-gate requirements (for example four quarters and all identity fields). It must not be reused as a passing end-to-end snapshot without schema validation.
- Corrective direction: explicit opt-in snapshot fixture at the fetch_data acquisition boundary, then the SAME envelope/snapshot/code checks. No silent test-mode relaxation, no fabricated PASS, no replacement of the validator. Exact fixture schema and remaining I/O call graph are still design prerequisites.

## Goal

Allow a bounded, deterministic prepare-path smoke to consume explicitly synthetic, task-local data without touching real data providers, pre-existing SQLite databases, Sage/wiki knowledge, report-wiki bundles, or any path outside an isolated runtime root. The feature must be opt-in and fail closed; production/default behavior must remain unchanged.

## Non-goals

- No production data collection, provider access, real company records, credentials, network, or external CLI/service.
- No change to investment conclusions, report schemas, expert prompts, knowledge base, expert panel, release configuration, or cron behavior.
- No broad mock framework or permanent test-data database.
- No bypass of identity Gate, checklist audit, report gates, or output containment.

## Proposed interface (for review, not implementation)

1. Add an explicit test-only injection switch (candidate name: `INVEST_SYNTHETIC_INPUT_DIR`) accepted only when `INVEST_TEST_MODE=1` and a dedicated synthetic-fixture schema/version marker is present.
2. Resolve the fixture root and every referenced file canonically; require all paths to remain below the task runtime root. Reject symlinks, traversal, missing files, unknown fields, invalid types, and unexpected schema versions.
3. Route the prepare data acquisition call through one narrow provider interface. In synthetic mode it reads only the declared fixture bundle; it must not import/call provider clients, `data_tools.py all`, local default database paths, Sage/wikis, or report-wiki materialization. If any forbidden path is reached, exit nonzero before writing final batch artifacts.
4. Normal mode remains byte-for-byte behaviorally unchanged: no env var means existing production data path; synthetic mode is rejected unless both test mode and schema marker are valid. Never infer synthetic mode from fixture file presence alone.
5. Keep all generated prompts, staged results, logs, reports and temporary files under a dedicated runtime root. Record resolved roots and fail if any configured data/log/temp/report destination escapes.

## Fixture contract to define before coding

- Versioned manifest with exact schema version and fixture file inventory plus hashes.
- Minimal required stock identity/meta, quote/market series, financial statements and any derived inputs actually consumed by `data_tools.py all`/prepare; each record explicitly labeled synthetic, with deterministic values and dates.
- No real ticker/company names, real market values, copied database rows, real reports, credential-like fields, or knowledge-cache content.
- Unknown or extra fields rejected; missing required fields fail with a field-specific diagnostic. Do not auto-fill plausible production values.
- Fixture builders, if needed, must be deterministic pure functions and must write only under the task runtime root.

## Design tasks (proposed IDs)

### INV-SYNTHETIC-INPUT-DESIGN-01A — Call-path and schema inventory (design/read-only)
- Map exactly which data functions/fields prepare consumes, from `prepare_prompts.py` through the data acquisition and report/batch creation path.
- Identify all possible provider, SQLite, wiki, report-wiki, cache, temp, log and output accesses; label verified vs unknown.
- Deliver call graph, required-field table, proposed fixture manifest/schema, and explicit unknowns.
- AC: every required input field has source/type/consumer; every I/O path is classified; no unsupported claim of exhaustive whole-repo coverage; no commands or dynamic execution.

### INV-SYNTHETIC-INPUT-DESIGN-01B — Injection seam and test plan (design only)
- Specify exact function boundary, opt-in guards, canonical path checks, fixture validation, failure semantics, and production-mode invariants.
- Define positive and negative tests: valid fixture works; missing/invalid schema rejected; path traversal/symlink rejected; test mode off rejects fixture override; synthetic mode cannot reach provider/SQLite/wikis/external CLIs; output escape rejected; failure leaves no successful batch/coverage artifact.
- Define independent engineering QA against one immutable candidate SHA and required raw evidence.
- AC: complete test matrix includes failure/repair/retry and no-state-leak cases; no gate weakening; no implementation commands in this design task.

## Risks / mitigations

- **Risk:** “synthetic” path accidentally falls through to real providers/SQLite. **Mitigation:** one explicit provider seam, hard fail on any undeclared access, negative tests that assert forbidden clients are never invoked.
- **Risk:** Partial batch artifacts appear successful after missing fixture. **Mitigation:** validate entire manifest before writes; atomic staging; failure must yield nonzero and no success marker/coverage.
- **Risk:** Environment variables redirect only some outputs. **Mitigation:** canonicalize and assert every read/write root at entry and before finalization.
- **Risk:** State leaks between attempts. **Mitigation:** per-run isolated runtime; no reuse of failed staging; retries require new run ID and fresh fixture hashes.
- **Risk:** Identity Gate gets bypassed because inputs are synthetic. **Mitigation:** all identity/checklist/report gates remain enabled and fail closed; synthetic status does not imply authenticity or coverage.

## Authorization and handoff

This is for user review only. If approved, investPM will split implementation into unique TASK-ID leaf tasks, confirm permissions, dependencies, ACs, negatives/failure testing, verification commands and rollback, obtain the implementer's ACK, and only then mark READY_FOR_CODE. No READY_FOR_CODE or implementation work exists as of this draft. Any material scope change returns to design and requires re-review/authorization.
