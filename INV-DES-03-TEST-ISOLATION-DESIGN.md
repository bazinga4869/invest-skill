# pytest 导入前隔离设计（提案）

- **关联任务：** `INV-DES-03-TEST-ISOLATION-CONFTEST-DESIGN-01`
- **日期：** 2026-10-29
- **状态：** 已按 lead 的 BLOCKED 复核意见修订，待再次复核；实现与测试仍 BLOCKED。`tests/conftest.py` 仍未创建。
- **边界：** 本文不授权实现、代码修改、pytest 收集/运行、CLI、runtime/DB/data 访问或 READY_FOR_CODE。

## 1. 目标与当前证据

目标是在任何测试模块导入前，将测试运行约束到本次测试创建、唯一且可识别的临时 runtime 子树；覆盖模块导入副作用、测试子进程和失败留证，防止误读写正式 runtime、数据库、报告或其他外部路径。

主合同 `INV-DES-03.md:865` 要求在测试模块导入前注入 tempfile runtime root，覆盖裸 pytest 收集/运行、隔离子进程、`tests/stub_agent.py` 和模块级 `RUNTIME_ROOT` 导入者。现有矩阵 REM07-01、05–09 是有限静态记录：多个导入链会经 `shared.runtime` 设置进程 umask 并解析/创建当时的 runtime root；`tests/test_report_gates.py` 会读取 `WIKI_ROOT/index.md`；`shared.data_tools` 导入链会检查 `.env` 并可能加载。它们不是全仓导入清单，也没有动态证明隔离有效。**硬边界：**对 `WIKI_ROOT/index.md` 一律使用测试区合成 fixture/mock，或由 OS 隔离层拒绝访问真实 WIKI_ROOT；对 `.env` 一律使用测试区 fixture/预导入 mock，或由 OS 隔离层拒绝对真实 `.env` 的 metadata/read 访问。任何配置无法被重定向或 mock 时，必须 fail closed；不得读取外部 wiki 或真实 `.env`。

## 2. 建议的启动顺序

1. **强制外层 pytest worker。** 所有受支持的 pytest 入口——裸 `pytest`、`python -m pytest`、collection-only、IDE 与 CI——必须映射到唯一的项目测试 supervisor；supervisor 是唯一可启动 pytest interpreter 的授权父进程。它在创建 Python 进程之前净化环境、设置测试区 root 与 umask 077、设置 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，再显式加载审过的插件 allowlist，并在 Python/pytest 启动前对整个进程树施加 OS sandbox。sandbox 只读允许的仓库源码，拒绝对仓库写入、正式 runtime、真实 DB/data、真实报告、WIKI_ROOT、真实 `.env`、外部 repo/provider 与网络的访问。CI、IDE 与项目支持的本地入口只能调用 supervisor；OS/CI 执行策略必须拒绝绕过 supervisor 的直接 pytest/Python 启动，PATH shim 或事后 conftest 检查不算强制门禁。若平台不能在 Python/插件初始化前强制此父子关系和 sandbox，则本地 pytest/collection 一律不运行，设计状态保持 BLOCKED，不得声称 fail-closed 已实现。
2. **建立唯一运行根。** 在 worker 中、导入任何项目模块前，测试 bootstrap 通过标准库创建带随机运行标识的临时工作区，并在其下指定唯一 `runtime/` 子目录。临时根必须是绝对路径、归属于本次运行、权限受限，并且不能等于或位于项目仓库、已知正式 runtime、真实 DB、真实报告目录或它们的 symlink 目标。bootstrap 将 `INVEST_RUNTIME_DIR` 设置为该子目录，并从进程环境移除未获准的路径覆盖变量；若无法证明上述关系则 fail closed，中止收集。
3. **先初始化，再导入。** 拟议的根级 `tests/conftest.py` 只可先使用标准库校验 supervisor 写入的 run marker、临时 root 与隔离状态，不得在此之前导入 `shared.runtime`、脚本模块、测试模块或其他可能触发 runtime 的本项目代码。它只是第二道一致性检查，不是外层门禁：pytest 插件可能在 conftest 加载前运行，所以不能靠 conftest 拦截插件副作用。supervisor 必须在 Python 启动前完成环境净化、插件 autoload 禁用及 OS sandbox；缺失/错误 marker 时 conftest 中止收集。不能用 session fixture 代替这一步：fixture 执行时，测试模块的顶层 import 已经发生。若任何启动代码在 root 设置前导入项目模块，应在 OS 隔离内阻断并记录失败，而不是事后 patch 模块常量。
4. **处理 import-time 副作用。** 当前静态记录显示，导入 `shared.runtime` 会改变进程 umask 并解析/创建 runtime root，部分导入者会把 `RUNTIME_ROOT` 固定为模块级快照。因此须在专用 worker 中先设置 restrictive umask（设计目标 `077`），再导入项目模块；让任何 import-time mkdir 只能落在唯一临时根。导入后校验实际快照解析仍在该根内，并检查 umask 未意外放宽。不要在模块已导入后仅 patch 环境变量或 `RUNTIME_ROOT`，然后声称隔离成立。需要测试不同 umask 的场景时，应另用一次性子进程，避免同一 pytest worker 中共享、恢复全局 umask。
5. **收集与运行使用相同隔离。** 普通 pytest 收集、collection-only 流程及测试执行必须经过同一启动边界。收集也会 import 测试模块，不能视为无副作用。若直接启动路径不能保证先完成环境净化和插件控制，则该入口不受支持，应阻止而非降级为“只收集”。初版设计默认单 worker、串行运行；启用 xdist 或并行测试前，必须追加每 worker 唯一 runtime root 的设计与验证，不得共享本次 root。

## 3. 子进程隔离

- 测试仅可启动明确登记的 Python test worker 或受控 stub；使用参数数组而非 shell 字符串，设置明确的 cwd、超时和进程组监督。正常结束前须确认所有子进程已退出/回收。
- 子进程拿到最小环境白名单，不继承凭证、生产 root、DB/report/log 路径或外部 Provider 配置。`INVEST_RUNTIME_DIR` 必须指向测试运行区；`HOME`、`TMPDIR`、`STUB_STATE_DIR` 等临时状态路径须落在本次运行区。需要 DB 的独立测试只能使用明确创建于测试区的 disposable DB；其他测试应 mock/阻断 DB 入口。不能依赖“测试数据看起来像 fixture”来证明不会访问真实 DB。
- Provider、Sage/report-wiki 等外部 CLI、网络及未登记可执行程序默认禁止。PATH stub 仅作第二道提示/拦截；必须另有操作系统级隔离边界，拒绝对正式 runtime、真实 DB/data、报告和其他未授权路径的写入，并默认拒绝网络。若宿主平台无法提供可验证的拒绝边界，则不得运行这组测试。
- `tests/stub_agent.py` 的状态目录和调用方输出均须显式置于本次临时区；不得沿用 `/tmp` 共享同代码命名空间。integration legacy 分支的共享 `/tmp` 清理在未重新设计前不纳入可运行测试集。
- **WIKI_ROOT 硬隔离：**`tests/test_report_gates.py` 对 `WIKI_ROOT/index.md` 的输入只能来自本次测试区生成的合成 fixture，或由导入前安装的 mock/stub 提供。supervisor 在 Python 启动前将 `WIKI_ROOT` 指向该 fixture；OS sandbox 同时拒绝对真实/外部 WIKI_ROOT 的路径 metadata 与内容读取。无法确认读取被重定向或拒绝时，测试收集/运行失败关闭；不得访问、复制或“只读核验”外部 wiki。
- **`.env` 硬隔离：**`shared.data_tools` 导入链中 `.env` 检查/加载必须由导入前 mock 的 loader 与测试区合成配置替代，或由 OS sandbox 对真实 `.env` 的 metadata/read 访问拒绝。supervisor 不继承 host env/凭证；不得读取、复制或加载仓内、用户目录或其他真实 `.env`。若无法在模块 import 前确定并隔离其查找路径，则该测试不得导入 `shared.data_tools`，应中止并保留失败证据；不能把“环境变量看似干净”视作 `.env` 未被读取的证明。

## 4. 失败留证与清理

每次运行建立仅属于该 run ID 的证据清单，记录运行 ID、worker/测试标识、临时根、导入阶段、退出码、受控子进程状态、失败类型、临时区相对路径清单及清理结果；环境只记变量名或经审查的非敏感摘要，不记录凭证值。保留失败 traceback 和受控 stdout/stderr，先做敏感值过滤；不复制正式 runtime、DB 或报告内容作为测试证据。

导入/收集失败、越界探测、超时、子进程未回收、证据写入失败或清理失败都必须 fail closed：保留本次临时根和已生成证据，明确标记 `FAILED_RETAINED`，报告绝对证据路径与未完成清理项。不得在失败路径中递归清理共享 `/tmp`、仓库或推测出来的目录。只有所有子进程回收且运行通过后，才可清理本次登记的唯一临时根；删除前需再次确认规范化路径仍严格位于本次根中，目标非 symlink/非正式根，清理失败则保留并报告，不吞掉错误。

## 5. 正反例与失败边界

| 场景 | 预期结果 |
|---|---|
| 正例：顶层测试模块 import `shared.runtime`，快照 root 指向本次唯一临时 runtime；import 创建的目录只在该测试区 | 允许收集；记录 root 与 import-time umask 检查结果 |
| 正例：受控子进程收到净化环境、登记的临时状态目录和有限 executable，完成后可确认进程已退出 | 允许继续；父进程保留同一 run ID 下的子进程证据 |
| 正例：测试失败，但所有输出均在本次临时区 | 标记 `FAILED_RETAINED`；保留证据，禁止自动清空失败现场 |
| 正例：`test_report_gates.py` 只读取测试区合成 `WIKI_ROOT/index.md`；`data_tools` 导入在真实 `.env` 被 OS 拒绝的前提下使用预先安装的 mock loader/合成配置 | 允许进入对应隔离用例；证据只记录 fixture 身份，不读取或复制真实 wiki/`.env` |
| 反例：`INVEST_RUNTIME_DIR` 缺失、相对、指向正式根、解析后逃逸临时区，或与其他运行共享 | 收集前阻断；不 patch 后继续、不 mkdir 正式路径 |
| 反例：conftest/插件在环境设置前导入项目模块，或 pytest 插件未审查/意外 autoload | 外层 worker sandbox 阻止其越界；记录导入顺序并保留临时证据；不能由 conftest 事后补救 |
| 反例：从 supervisor 外执行裸 `pytest`、`python -m pytest`、collection-only 或 IDE/CI 直接 pytest 入口 | 执行策略在 Python/pytest/插件初始化前拒绝；若任何绕过路径可启动 interpreter，则门禁验收失败，所有 pytest/collection 保持 BLOCKED |
| 反例：`test_report_gates.py` 解析到真实 WIKI_ROOT，或 `data_tools` 检查/读取真实 `.env`，或 fixture/mock 未在 import 前生效 | OS sandbox 拒绝路径 metadata/read；记录违规并失败留证，不退回真实文件 |
| 反例：代码或子进程尝试写入仓库、正式 runtime、真实 DB/report/data、网络或未登记外部 CLI | OS 隔离拒绝；标记隔离失败并保留现场，不把一次拒绝当成完整安全证明 |
| 反例：两个 worker 共用 runtime、子进程超时后仍存活、stage/清理冲突或证据路径越界 | 阻断/失败并保留证据；不执行宽范围清理，不声称测试隔离 PASS |

## 6. 未决假设与进入实现前门槛

- 外层 supervisor、执行策略与 OS sandbox 尚未实现或验证。后续验收必须逐一证明所有支持入口（裸 `pytest`、`python -m pytest`、collection-only、IDE、CI）都经 supervisor，且绕过入口在 Python/plugin 初始化前被拒；conftest marker 只是第二道检查。未证明前所有 pytest/collection 保持 BLOCKED。
- 必须确认项目实际 pytest 版本、根目录选择、conftest 加载顺序、插件自动发现机制与启动器/IDE/CI 集成；本文未运行 pytest 或 collection，不能将顺序或门禁描述视为已验证事实。
- 当前 REM07 行只列有限 import/caller 样本；剩余模块是否有更早的 import-time filesystem、umask、DB、网络或子进程副作用尚未穷尽。不得据此宣布全套隔离完成。
- `WIKI_ROOT` 与 `data_tools` `.env` 的实际查找路径/解析时序尚未核定；必须在单独获准的源码设计审查中确认如何在 import 前替换为 fixture/mock，或证明 OS sandbox 对真实路径的 metadata/read 拒绝有效。本文和本任务均未访问 wiki 或 `.env`。
- 需由平台负责人确认 macOS/Linux 临时目录、symlink 解析、权限、全进程树 sandbox 和 pytest 执行策略的强制能力；不能只靠环境变量、PATH shim 或 pytest fixture 作为安全边界。若该能力不可用，不得运行本项目测试。
- DB 测试的 disposable DB 位置/生命周期、外部 CLI stub allowlist、失败证据保留期限/容量/脱敏责任尚待确认。
- xdist、任何 supervisor 外的 raw pytest、或测试真实 Provider/外部 repo 均不在授权范围；需要另行设计、审批和单独门禁验收。

**结论：**本稿已补入 lead 指定的真实 WIKI_ROOT/`.env` 隔离规则及所有入口强制 worker/绕过拒绝验收，但仍是纯文档修订；设计复核未通过前保持 BLOCKED。`tests/conftest.py`、supervisor、OS 沙箱、测试或动态验证均未创建/执行；实现还需明确责任人、独立工程 QA 任务，并由 PM 单独签发 `READY_FOR_CODE`。
