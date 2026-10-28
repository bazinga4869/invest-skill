# INV-DES-03 10:19 静态核验附录

- 时点：2026-10-19 10:19 Asia/Shanghai；schedule occurrence `2026-10-19T02:19:29.700Z`。本附录只记录源码静态核验，不是动态验证、工程QA或实现授权。
- 新静态证据：`native_agent_tasks.py:617-650` 的 `_freeze_decision_baseline()`仅当baseline不存在时，从runtime已有result或rejected文件候选中按decision可解析性优先选择源，随后保存source path/SHA与decision/structure；`_repair_prompt()`读取runtime baseline并把decision规则注入修复任务（`:262-303`）；commit比较repair decision/structure，不匹配时写rejected/error并拒绝提交（`:775-851`）。
- 证据边界：这证明局部的修复语义/结构一致性控制，可减少repair改变已冻结决策的漂移；baseline来源仍是普通runtime中已有结果，材料未证明其与结果由独立权限主体保护或不可替换。因此不能作为可信原始来源、授权身份锚或独立保护信任根；同一可写主体可能替换baseline及结果。未访问runtime文件，未执行这些路径。
- 状态：B1–B6未闭合；identity gate继续BLOCKED。补充对照源码：baseline存在时直接复用；不存在时仅从普通runtime的当前result/rejected文件选取并重算局部decision/structure签名，不含独立来源授权证明。该控制只在读取到的baseline未被同权限主体替换这一前提下限制repair语义漂移，不建立可信原始来源或独立信任根。该切片不改变REM分母，不是完整矩阵签出或新review verdict。项目保持`IN_PROGRESS/BLOCKED`、非`READY_FOR_CODE`；未授权实现/动态验证。
- 下一责任：@investPM继续逐项完成B1–B6有来源证据映射，或明确当前权限模型无可行可信身份路径裁决；继续REM-01..09静态签出。其后以新TASK-ID真实@投研复核限定只读审查，明确输入、范围、AC、交付、期限和禁项；ACK前`WAIT_ACK`。
