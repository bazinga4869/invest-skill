# 2026-10-25 原生专家原始产出（不可再生成证据包）

## 这是什么

603605.SH 批次 `d4450143cd0858a8260f0bd4`（分析日 2026-10-25，交易日 2026-10-23，native plan
transaction `2e3c97d7805891517d1515eb`）七位原生专家的**原始产出与输入 prompt**，从运行时目录
`invest-skill-runtime/` 固化为仓库内证据，供批次收口、复算与审计使用。

## 为什么必须保留

这些是 LLM 推理产物：同样的 prompt 重跑**不保证**得到同一份文本，也无法由代码或数据重算出等价文件。
在本次固化前，它们只以未提交的 `.next` staging 形式存在于运行时目录，属于单副本、不可复现状态。
本文证据包是它们的**持久副本**；`SHA256SUMS` 记录每个文件的 SHA-256，可与运行时侧逐字节比对。

## 目录

- `staging-next/`：24 份专家输出 staging 文件（`.next`），覆盖 7 位专家在 4 个运行轮次下的全部尝试
  （financial-auditor 6、value-valuator 7、management-auditor 4、growth-assessor 3、
  cognitive-controller 2、macro-cyclist 1、moat-analyst 1）。原文件名为隐藏文件
  `.invest_native_output_*.next`，此处**去点重命名**以便普通 tar/rsync 备份能带走；文件名其余部分未改。
- `prompts/`：14 份 prompt——7 份 `invest_native_original_prompt_*`（当次实际投喂的原始 prompt）与
  7 份 `invest_native_prompt_*`。
- `archive/`：原 `invest_native_archive_603605.SH_experts_d4450143cd0858a8260f0bd4_2e3c97d7805891517d1515eb/`
  内容（7 份原始 prompt + `plan_begin_20261025T134936048192Z.json`）。
- `invest_expert_run_603605.SH.json`、`invest_native_run_603605.SH.json`、`invest_execution_603605.SH.json`：
  当次运行台账与执行记录。
- `SHA256SUMS`：49 个文件的 SHA-256（固化时生成，逐项与运行时原件比对一致，0 处不一致）。

## 来源与状态边界

- 来源目录：`invest-skill-runtime/`（运行时数据，不属于本仓库工作树）。
- 本次为**复制**而非移动：原件仍留在运行时 staging 原位，以免改动批次 -08 的运行态。
  两端一致性由 `SHA256SUMS` 保证；若要清理运行时副本，应在批次正式收口后按证据包逐项核对再删。
- 这是**证据固化**，不构成批次通过：该批次七位专家的 compile / gate_precheck / commit 状态仍以其
  运行时台账为准，本包不改变任何门禁结论。

## 校验方法

```bash
cd evidence/native-experts-20261025
shasum -a 256 -c SHA256SUMS
```

与运行时原件比对：

```bash
RT=../../../invest-skill-runtime
for f in staging-next/*.next; do cmp -s "$f" "$RT/.$(basename "$f")" || echo "MISMATCH $f"; done
```
