# 数值可靠性改造设计（HIL 闸门 + 验证状态 + 可审代码）

> 目标：把"算错但合理"的静默数值错误挡在论文外，并让人对无 ground truth 的物理核心拥有最终裁决权。
> 参照 jihe520/MathModelAgent 值得吸收的两点：HIL 人机协作、可再审代码。不采用其"LLM 自评完成"。

---

## 一、验证状态模型（核心）

每个子问题的执行结果携带 `verification_status`，四档：

| 状态 | 含义 | 谁给 | 能否进论文 |
|---|---|---|---|
| `verified_human` | 人工确认/人工填写的真值 | HIL 闸门 / verified_results CSV | ✅ 最高优先 |
| `verified_crosscheck` | 两种独立方法结果一致 | 自动（可选，先不做） | ✅ |
| `verified_metrics` | 代码真实运行回读（metrics.json），但无 ground truth 对照 | Solver | ✅（默认） |
| `unverified` | 未跑通 / LLM 估计 / 被人工拒绝 | 兜底 | ❌ 一律占位符 |

**铁律：Writer / 评审 / 数据审核只引用 `verified_*` 数值，`unverified` 写占位符 `[未验证]`。**

现有基础：`metrics.json` 回读已保证"数字来自真实运行"（=verified_metrics），缺的是把它显式化 + 加 human 真值层。

## 二、HIL 闸门（人机协作）

### 位置
`main.py` 第 4 步（求解）之后、第 5 步（评审）之前。

### 触发条件（满足其一则暂停）
- `config.hil.enabled = true` 且该子问题**无 ground truth**（物理/新颖算法/无数据留出集）
- 或 `hil.require_all = true` 强制全部暂停（调试用）

### 流程（batch 模式，复用现有 `--resume` 断点机制）
```
[4/7] Solver 求解完所有子问题
   ↓
HIL 闸门判断：有需要人工验证的子问题？
   ├─ 无 → 正常继续
   └─ 有 →
        ① 每个 execution 落盘：代码(.py/.txt) + 输出 + metrics
        ② 生成 data/hil/pending_<ts>.json（每个子问题待填：confirm/edit值/reject）
        ③ 打 checkpoint（已有机制）→ 打印提示 → 正常退出（状态=hil_awaiting）
   ↓
人审：可看落盘的 .ipynb/.py/.txt，打开 pending json 逐题填写
   ↓
python hil_resume.py data/hil/pending_<ts>.json
        ① 校验人工填写（类型/数值范围/必填）
        ② confirm → verified_human；edit(填了值) → 覆盖为人工值 + verified_human；
           reject → unverified（不进论文）；abort → 终止
        ③ 注入 summary["_verified_results"]（复用现有字段，人工值最高优先）
        ④ 从断点 resume → 继续评审/论文/门控
```

### 决策动作（4 种，够用）
`confirm` / `edit(给正确值)` / `reject` / `abort`（regenerate 需要回 stage3，v1 不做，人工可手动改后重跑）

## 三、可审代码落盘（Jupyter 化）

- Solver 不再用临时文件即抛即弃：最终执行代码写 `data/results/<task>/subX_*.py` + `subX_output.txt`
- 用 `nbformat` 生成同内容 `.ipynb`（未安装 nbformat 则降级 .py+.txt，不报错）
- 目的：人审时能逐行看"算这个数的代码"，而不是只看一个数字

## 四、Writer / 审核强制

- `writer._build_exec_summary`：只引用 `verified_*` 的数值；`unverified` → 占位符
- `audit.DataAuditor`：数据审核优先级 = 人工值 > verified_metrics > 缺省跳过（现状已优先人工，需补状态判断）

## 五、改动清单

| 文件 | 改动 | 风险 |
|---|---|---|
| `config.yaml` | 新增 `hil:` / `verification:` 段 | 低 |
| `main.py` | stage4 后插 HIL 闸门；组装 verification_status | 中（复用 checkpoint，可控） |
| `agents/solver.py` | 落盘代码/输出；execution 加 `verification_status="verified_metrics"` | 低 |
| `agents/writer.py` | 只引用 verified；unverified→占位符 | 低 |
| `agents/audit.py` | 数据审核状态判断 | 低 |
| `utils/verification.py` | **新增**：状态判定/强制校验/占位符规则 | 新 |
| `hil_resume.py` | **新增**：读决策→校验→注入→resume | 新 |
| `utils/notebook_utils.py` | **新增**：生成 .ipynb | 新 |
| `tests/test_verification.py` `test_hil.py` | **新增**：状态传播 / HIL 决策注入 | 新 |

## 六、不改的东西（保底）
- 7-agent 主流程、断点续跑、经验库、逻辑剪刀、铁律锁、manual_solutions 全部不动
- `hil.enabled=false` 时行为与现在完全一致（可随时整体回退）
- 每个改动点独立可启停

## 七、风险与边界（诚实）
1. HIL 会打断全自动 → 默认只在"无 ground truth"子问题触发，且可用配置整体关闭
2. 该方案**仍不解决**"代码算错但人工也信了"的情况——它把裁决权交给"人"，假设人比 LLM 可靠（竞赛场景成立）
3. 真正消灭静默错误仍需 ground truth 校验（留出集/独立方法），HIL 是当前数据条件下最现实的兜底

---

## 待你审核的关键决策点
1. HIL 触发范围：仅"无 ground truth"子问题，还是默认全部暂停？（建议：仅无真值）
2. 人工值注入是否覆盖代码输出（影响论文/评审引用）？（建议：是，人工为最高真值）
3. Jupyter 落盘是否必要？（建议：要，便于逐行审）
4. 改动是否分批做：先 verification 状态 + Writer 强制（1 天），再 HIL（1-2 天），再 notebook 落盘（半天）？

---

## ✅ 实施状态（2026-08-09 已全部落地并验证）

| 项 | 状态 | 验证 |
|---|---|---|
| 阶段1 verification 状态 + Writer/审核强制 | ✅ | `tests/test_verification.py` 5 项 PASS |
| 阶段1 顺带修复：Writer 原始输出泄漏（已验证值下仍混入旧错误值） | ✅ | 回归用例 PASS |
| 阶段2 HIL 闸门 + hil_resume.py | ✅ | `tests/test_hil.py` 4 项 PASS + 全链路集成验证（人工值 10.47 覆盖 4.72） |
| 阶段3 代码落盘 .py/.ipynb/.txt | ✅ | `utils/notebook_utils.py` 功能验证 PASS |
| 全量回归（10 个测试文件） | ✅ | 全绿 |

**新增/改动文件**：`utils/verification.py`、`utils/hil.py`、`utils/notebook_utils.py`、`hil_resume.py`、
`tests/test_verification.py`、`tests/test_hil.py`、`config.yaml`（verification/hil 段）、
`agents/solver.py`、`agents/writer.py`、`agents/audit.py`、`main.py`。

**使用**：`config.yaml` 设 `hil.enabled: true` → 无真值子问题求解后暂停，
编辑 `data/hil/pending_*.json` 填 decision → 运行 `python hil_resume.py data/hil/pending_*.json` 续跑。

---

# 审核层设计原则（Audit Layer）

> 本次重构将审核层从"LLM 主观打分"切换为"确定性校验 + 异常清单"。后续维护审核逻辑时必须遵守以下原则，**不要加回 LLM 调用**。

## 核心原则
- **确定性优先**：所有审核结果必须可复现，同一篇论文多次审核输出一致（无 LLM、无随机）。
- **零 LLM 评分**：审核器不调用任何大模型主观打分，只执行规则检查与数值比对。
- **输出为"证据"而非"判决"**：最终输出为异常项清单，通过/不通过由规则阈值决定，不由模型判断。

## 三个审核器的职责边界

| 审核器 | 检查方式 | 输出 |
|---|---|---|
| 逻辑审核 LogicAuditor | 7 项结构化清单（FFT/判据/不确定度/拟合优度/模型对比/自洽/灵敏度） | 缺失项列表 |
| 数据审核 DataAuditor | 论文数值 vs 参考真值比对（容差 2%） | 偏差项列表 |
| 排版审核 FormatAuditor | 规则引擎（公式编号/文献/图表/单位/层级/代码块） | 格式违规列表 |

## 与旧版的核心区别
- 旧版：LLM 读论文 → 三个百分制分数（非确定性、不可复现）
- 新版：规则/比对 → 通过/不通过 + 异常清单（确定性、可复现）

## 配置说明（当前可调项）
- `config.yaml → auditor.data_tolerance`：数据审核相对容差（默认 0.02）
- `config.yaml → auditor.score_threshold`：单项合规分通过线（默认 8.0）
- `config.yaml → auditor.overall_threshold`：综合合规分通过线（默认 9.0）
- 逻辑检查清单项、排版检查族目前为**代码内定义**（`LogicAuditor.CHECKS` / `FormatAuditor`），如需按数量/严重度配置化，可后续外移到 YAML。

## 待完善：基准校准机制
当前阈值（数据容差 2%、单项 >8、综合 >9）为经验值，**尚未经金标准数据集校准**。
后续需收集 10–20 篇人工审核通过的论文（附已知真值），跑门控统计误报/漏报率后调参。

---

# 补充：评审发现的盲区澄清

## 盲区2 已澄清：HIL 真值与门控的优先级链（代码已实现）
```
人工真值 verified_human > 代码输出 verified_metrics > 未验证 unverified
```
- HIL 注入的人工值写入 `summary["_verified_results"]`（`utils/hil.apply_decisions`）；
- 数据审核 `DataAuditor._extract_refs` **优先解析 `_verified_results`**，非空即返回，代码输出仅作回退；
- 即：只要有人工真值，门控数据比对**只比人工真值**，代码输出不参与。

## 盲区3 已澄清 + 已修复：门控终止状态的落盘行为
两种终止状态（`main.py` 审计循环）：
- **通过**：论文正常落盘，pipeline JSON 标记 `audit.passed=true`；
- **未通过（停滞2轮或达上限被强制接受）**：最后一次论文**仍落盘**，且：
  1. pipeline JSON 标记 `audit.force_accepted=true` + `accept_note`（含最终评分与异常说明）；
  2. **（2026-08 修复）** `accept_note` 会**追加到论文文件末尾**，用户打开论文即可见"⚠ 未通过门控，需人工复核"，不隐藏失败。

## 盲区1/4/5 状态（暂不实现，留待实测）
- **经验库写入规则**：当前 `record_from_summary` 对成功/失败的执行都记录（供先验），"好坏"由执行成功与否粗判；精细化规则（门控+人工确认才写、失败案例单独存 failures/）待实测 3-5 篇后定。
- **多子问题依赖**：暂不自动化；Builder 代码中由 LLM 依赛题背景处理，必要时人工在 manual_solutions 注入依赖。
- **错误模式库**：暂不建；自修复目前基于报错上下文（非历史模式），积累足够失败案例后再建。
