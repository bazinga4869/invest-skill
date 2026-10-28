# INV-SMOKE-01-RUN-02-V5-RECOVERY-PLAN-01

- **Status:** DRAFT FOR INDEPENDENT REVIEW; not PM-accepted. This is a plan only: no file in the failed `fixture-v5` root is modified, no new output root is created, and no builder/preflight/prepare is run.
- **Parent / authority:** `INV-SMOKE-01-RUN-02`. Chief's 2026-10-26 ruling allows a reversible local synthetic-fixture repair/retry after a written execution plan, same-plan independent PASS from `投研复核`, and PM acceptance; no additional user approval or duplicate ACK→START gate for that same accepted plan. Existing STOPs and restricted-operation approvals remain in force.
- **Failure evidence:** The sole V5 builder invocation at 2026-10-26 11:58:27.630013–11:58:27.631099 +08 exited 1 before `execute_build()` with `prebuild-state command binding mismatch`. Result SHA-256 `2c17d6ab08723eb62f671c973e284913c2efd21236c6623b979db0a37a2977b0`; failed root `.smoke-tmp/runtime/fixture-v5/` is immutable evidence and must be preserved.
- **Static root cause:** The failed builder script checks `state.get("exact_builder_command") != state.get("command_template")` at lines 122–123, but the frozen prebuild-state JSON includes `exact_builder_command` without a `command_template` field. The mismatch is therefore deterministic before `execute_build()`. This is a read-only diagnosis; no change to product source, schema, checklist, validator, V3, V4, or the failed V5 artifacts is proposed.

## Recovery proposal (not yet authorized to execute)

1. **Repair the state/command binding in the new attempt only.** Use one canonical frozen command string and serialize both `command_template` and `exact_builder_command` with byte-identical values into the new prebuild-state JSON before computing its SHA sidecar. The generated new-root builder must fail closed if either field is absent, unequal, or differs from the exact command and sanitized environment it is about to execute. It must also bind the canonical retry root `.smoke-tmp/runtime/fixture-v5-retry-01/` consistently in root guards, prebuild state, command, output inventory, and results; the old hard-coded `fixture-v5` root assertion must not survive into the new builder. Read back the JSON and verify the sidecar before the one builder invocation.
2. **Use a separate, non-overwriting output root:** `.smoke-tmp/runtime/fixture-v5-retry-01/`. It must not exist before the new attempt. Never write to, rename, or clean `.smoke-tmp/runtime/fixture-v5/`; preserve its prebuild state, script, logs, result and sidecars byte-for-byte.
3. **Bind the same reviewed V5 design:** same accepted addendum SHA `0b13a571a27146dadd78a5cbbfb4a4ae8f2aa4c095fc6939f05dd31079d94e8e`, crosswalk SHA `f639c6b131f02062749d2c6f9157ec65b6c8a525bc89155692cdd5a6d229e356`, candidate HEAD `5172550191ac55fd62990917aa49abb5c5c8fa2a`, same sandbox and hash-listed static/V3 inputs. No product-code or contract changes; if these inputs or the approved scope drift, stop and return to review.
4. **Build-only scope:** exactly one new local synthetic build attempt in the new root. Before any write, capture and classify full status, reverify HEAD/sandbox/all input hashes and directory absence, then freeze command, environment allowlist and exact write set. Add only the canonical top-level `公司治理` annual-report section and its rendered text/bundle under the new root; no JSON data leaves, no SQLite rows/database, no V3/V4/RUN-01 writes, real data, Provider, network, credentials, external CLI, cleanup, or retry. Do not run preflight or prepare in this task.

## Frozen candidate, dependencies, command, and write set

- **Recovery task ID:** `INV-SMOKE-01-RUN-02-FIXTURE-V5-RECOVERY-01`. **Candidate HEAD:** `5172550191ac55fd62990917aa49abb5c5c8fa2a`. **Status checkpoint captured 2026-10-26 17:17:12 +08:** tracked-status SHA-256 `9cd37aa1a6c6c1651ae554d06c9d0bad7e5cdd8d81b63ced70dc6294f508ec9a`; full-status SHA-256 `b462cc3b2ffb0596216ac7c758de831b1de6e62ae6cb92d038ff468ab5c3d29c` (197 entries); target retry root was absent. This checkpoint is bound for planning/review only; recapture and classify full status immediately before any recovery-root write.
- **Complete immutable input set:**

| Key | Path | SHA-256 |
|---|---|---|
| addendum | `INV-SMOKE-01-RUN-02-V5.md` | `0b13a571a27146dadd78a5cbbfb4a4ae8f2aa4c095fc6939f05dd31079d94e8` |
| crosswalk | `.smoke-tmp/INV-SMOKE-01-RUN-02-CROSSWALK-SYNTHETIC-v5.md` | `f639c6b131f02062749d2c6f9157ec65b6c8a525bc89155692cdd5a6d229e356` |
| rules | `data/checklist_evidence_rules.json` | `b1b4cc1251911e6562348d11702857c9f127fa2b451b46dee84aa0619d5b4a2c` |
| checklist | `data/expert_checklist.json` | `73288005b2b752ed1aaa6f176a735d6d1b94b2adebf3d8c93d326ff950c4b80b` |
| prepare | `scripts/prepare_prompts.py` | `9dbc6c23fcb838499b57750455b61da66d71fc300a68b6af6e4fb7f55ad5d554` |
| checker | `shared/checklist_verify.py` | `3ba605bcc7a687b0878a38aaa5e9ab28ea46dcdf02f4f77384b666b6c0c79157` |
| report-wiki | `shared/report_wiki.py` | `016dc9bd03221b4f114577deeced60fddfa5f331f2f994733e36cf1701a10088` |
| schema | `schema.sql` | `0d8b615a6e9e3bb2869b94cac85463198d2e82826771d841c5448fc95d52f0e9` |
| sandbox | `INV-SMOKE-01.sandbox.sb` | `912687fcb781218e620ccb9b297e5b331b3a9f03687a89740db294b0e37ab5c9` |
| V3 DB | `.smoke-tmp/runtime/fixture-v3/fixture-SYNTHETIC.sqlite` | `1377e9e2dd5f2c7adabd987ef2c8a86a16fdfbf8b884968aac0ff3f0798df00b` |
| V3 bundle | `.smoke-tmp/runtime/fixture-v3/report-bundle-SYNTHETIC.json` | `ea5e12b894ba0b8df01d418e22f023250fbbdbf55786e148b9f95fbfe8b1cd0b` |
| V3 manifest | `.smoke-tmp/runtime/fixture-v3/prepare-execution-manifest-SYNTHETIC-v3.json` | `2eea9b78466a767bc29aedb2447ec685da512d5eef640f72b0d482847aad41c4` |
| V3 builder | `.smoke-tmp/runtime/fixture-v3/fixture-builder-SYNTHETIC.py` | `f52e903bdc94e1ee0846b54cacdce4493128acc8873677ad865cb970410c1eae` |
| contracts | `shared/contracts.py` | `001b1a30e4424c0a8f704be2cd19c549a4edd7dc56c39fb49792fbcfb5dcb0f1` |
| project config | `shared/project_config.py` | `38af85e2180ae5a091db3d4bb86a559525d801364ece26703775b02d8a1ac16a` |

- **Frozen one-line command and environment:** the prebuild-state `command_template` and `exact_builder_command` MUST both equal this exact string, byte-for-byte; it uses no secrets:

```sh
/usr/bin/env -i PATH=/Users/bazinga/.dsh/bot/workspace/invest/invest-skill/.venv-macos/bin:/usr/bin:/bin HOME=/Users/bazinga/.dsh/bot/workspace/invest/invest-skill/.smoke-tmp/runtime/fixture-v5-retry-01 XDG_CONFIG_HOME=/Users/bazinga/.dsh/bot/workspace/invest/invest-skill/.smoke-tmp/runtime/fixture-v5-retry-01 XDG_CACHE_HOME=/Users/bazinga/.dsh/bot/workspace/invest/invest-skill/.smoke-tmp/runtime/fixture-v5-retry-01 XDG_DATA_HOME=/Users/bazinga/.dsh/bot/workspace/invest/invest-skill/.smoke-tmp/runtime/fixture-v5-retry-01 PYTHONPATH=/Users/bazinga/.dsh/bot/workspace/invest/invest-skill PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHON_DOTENV_DISABLED=1 INVEST_TEST_MODE=1 INVEST_SKIP_SYNC=1 INVEST_ANALYSIS_DATE=2026-08-01 INVEST_SKILL_HOME=/Users/bazinga/.dsh/bot/workspace/invest/invest-skill/.smoke-tmp/runtime/fixture-v5-retry-01 INVEST_RUNTIME_DIR=/Users/bazinga/.dsh/bot/workspace/invest/invest-skill/.smoke-tmp/runtime/fixture-v5-retry-01 INVEST_DB_PATH=/Users/bazinga/.dsh/bot/workspace/invest/invest-skill/.smoke-tmp/runtime/fixture-v3/fixture-SYNTHETIC.sqlite INVEST_REPORTS_DIR=/Users/bazinga/.dsh/bot/workspace/invest/invest-skill/.smoke-tmp/runtime/fixture-v5-retry-01/reports INVEST_LOG_DIR=/Users/bazinga/.dsh/bot/workspace/invest/invest-skill/.smoke-tmp/runtime/fixture-v5-retry-01/logs TMPDIR=/Users/bazinga/.dsh/bot/workspace/invest/invest-skill/.smoke-tmp/runtime/fixture-v5-retry-01/tmp INVEST_REPORT_WIKI_FIXTURE=/Users/bazinga/.dsh/bot/workspace/invest/invest-skill/.smoke-tmp/runtime/fixture-v3/report-bundle-SYNTHETIC.json /usr/bin/sandbox-exec -f /Users/bazinga/.dsh/bot/workspace/invest/invest-skill/INV-SMOKE-01.sandbox.sb /Users/bazinga/.dsh/bot/workspace/invest/invest-skill/.venv-macos/bin/python /Users/bazinga/.dsh/bot/workspace/invest/invest-skill/.smoke-tmp/runtime/fixture-v5-retry-01/fixture-builder-v5-SYNTHETIC.py
```

- **Complete allowed write set—nothing else may be created or overwritten:**
  - `.smoke-tmp/runtime/fixture-v5-retry-01/prebuild-state-SYNTHETIC-v5.json` and `.sha256`
  - `.smoke-tmp/runtime/fixture-v5-retry-01/fixture-builder-v5-SYNTHETIC.py`
  - `.smoke-tmp/runtime/fixture-v5-retry-01/builder.stdout` and `builder.stderr`
  - `.smoke-tmp/runtime/fixture-v5-retry-01/annual-report-SYNTHETIC-2025-v5.md`
  - `.smoke-tmp/runtime/fixture-v5-retry-01/report-bundle-SYNTHETIC-v5.json`
  - `.smoke-tmp/runtime/fixture-v5-retry-01/builder-result-SYNTHETIC-v5.json` and `.sha256`
  - `.smoke-tmp/runtime/fixture-v5-retry-01/postbuild-state-SYNTHETIC-v5.json`
  - Forbidden: any SQLite/JSON data leaf, any file under failed `fixture-v5`, or any path outside the retry root.

- **Independent verification methods authorized for the reviewer only:** read the exact plan, listed failure evidence and the 15 listed input files; compute SHA-256 only for those named paths with `shasum -a 256`; verify HEAD with `git rev-parse HEAD` and status with `git status --porcelain=v1 --untracked-files=all | shasum -a 256`. No other shell commands, scripts, network, writes, or build/preflight/prepare.

## Acceptance and stop conditions

- The reviewer must return same-plan PASS on the exact SHA-256 of this plan and confirm the binding correction, independent output root, scope, AC and failure boundary. PM must then accept/freeze that plan hash before the owner executes; reviewer PASS alone is not execution authority.
- On execution, require the result record and sidecar; exact command/environment; pre/post status and write set; artifact/input hashes; bundle validation; exactly one `公司治理` section and locator `年报:2025/annual/公司治理`; read-only V3 SQLite integrity and unchanged row counts; explicitly record zero new DB rows and `NOT_APPLICABLE_ZERO_INSERTS` (not a passed insert test).
- One attempt only. Any failed binding check, unexpected path/status, hash drift, failed gate or unclear side effect stops before/after the relevant first side effect, preserves evidence, and ends this recovery attempt; no second retry under this plan. Preflight remains a separate, later task with its own scope/authorization confirmation and ACK; prepare remains STOP.
- **Rollback:** no rollback or cleanup is authorized. Preserve the entire failed V5 root and any new recovery-root evidence. A further attempt or scope expansion requires a newly reviewed plan; external, real-data, credential, paid, destructive or irreversible actions still require the relevant explicit authorization.

## Ownership and handoff

- Plan owner: `investPM`.
- Independent plan reviewer: `投研复核` (read-only; no build or execution).
- Potential execution owner after exact-plan PASS and PM acceptance: `投研流程`.
- Candidate next task ID: `INV-SMOKE-01-RUN-02-FIXTURE-V5-RECOVERY-01`.
