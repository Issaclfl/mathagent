# ModAgent 改进日志

---

## 2026-08-17 论文格式规范化（国赛标准）

> 按国赛格式规范完善论文生成链路：摘要关键词、问题分析四要素、公式统一编号、
> 假设边界、符号排列规则、语言规范。验证：37/37 单测 + 真实论文 25 个公式连续编号 1-25。

### ✨ 格式规范化

#### 1. 摘要：关键词 + 字数 + 禁式号引用
- **文件**: `agents/paper_guide.py` / `agents/writer.py`
- 摘要要求 300-500 字；末尾单独一行输出关键词（3-5 个，重要性降序）；
  摘要内禁止公式编号引用（如"式(5)"）

#### 2. 问题分析：总述→难点→技术路线→递进
- **文件**: `agents/paper_guide.py` 新增 `ANALYSIS_GUIDE` / `agents/writer.py`
- 问题分析要求：先总述学科分类与数学本质 → 列 3-5 个核心难点（难点|原因|思路）→
  一段总体技术路线 → 逐题递进分析

#### 3. 公式统一连续编号（确定性后处理）
- **文件**: `agents/writer.py` 新增 `_number_formulas()`
- **根因**: LLM 各章节独立生成公式，编号各自从 1 开始（实测灵敏度章节手写
  tag{1..5} 与模型章节 tag{1..10} 并存冲突）；正文"式(3)"引用也是编的
- **修复**: 后处理清除所有 LLM 手写 `\tag{n}`，按出现顺序统一重编号 (1),(2),...
  全局连续；代码围栏内 $$ 保护；格式 `\tag{n}` 兼容 Typst 转换器自动编号
- **配套**: prompt 要求正文不手写式号（用"上式""前述公式"），避免与系统编号错位

#### 4. 模型假设：已知条件不入假设
- **文件**: `agents/writer.py` PROMPT_ASSUMPTIONS
- 明确"题目给出的已知量（速度/半径/持续时间等）不属于假设；假设只含主动简化部分"

#### 5. 符号说明：逻辑顺序 + 斜体规范
- **文件**: `agents/writer.py` PROMPT_SYMBOLS
- 符号按"全局常量→决策变量→中间变量→结果量"排列；变量斜体 $t_d$、常量正体 $g$；
  单位缺失标"—"或"无量纲"

#### 6. 结果呈现：汇总表 + 对比分析
- **文件**: `agents/paper_guide.py` STRUCTURE_GUIDE
- 每个子问题末尾给"决策变量|最优值"汇总表；多子问题做对比分析
  （"相比问题1提升约X倍"）；多弹/多机协同说明机制（首尾衔接/分时段接力）

#### 7. 语言与排版规范
- **文件**: `agents/paper_guide.py` STRUCTURE_GUIDE
- 第三人称表述；术语首次出现附英文全称；数值精度（长度 0.1、时间 0.01）；
  避免口语化（"大概"→"约"）

#### 8. 参考文献：中文在前英文在后
- **文件**: `agents/writer.py` PROMPT_REFERENCES

### 验证
- `tests/test_fix_20260817.py`: 37/37 通过（新增公式编号 5 项）
- 真实论文（50 个公式块）：25 个独立公式连续编号 1-25，LLM 手写 tag 全部清除；
  Typst 转换兼容（19 个自动编号 label）

---

## 2026-08-17 修复共享单车论文六大硬伤（流水线级根因）

> 背景：审阅 `paper_20260817_001512.md` 发现标题脑补"动态定价"、Q2 方法描述矛盾、
> Q4 求解失败、章节编号混乱、符号不统一、参考文献编号冲突六大硬伤，
> 逐一定位到流水线代码根因并修复。验证：29/29 单测通过 + 真实断点重生成论文，
> 六项硬伤全部消除。

### 🔴 严重问题修复

#### 1. Q4 求解失败：fake_error 无错误上下文导致整条修复链盲修
- **文件**: `agents/solver.py`
- **根因**: returncode=0 但 stdout 含错误模式时，注入的 fake_error 只有一句
  "无有效产出"，不含 stdout 中实际出错的行——fix_code/Agent Loop/Builder
  重建模拿到的是无线索信息，3 轮修复全部空转（Q4 实证：last_stderr 只有笼统描述）
- **修复**: fake_error 附带 stdout 中含错误关键词的具体行（最多5行）+ 空跑原因说明
- **附带**: `_empty_success` 死变量激活（无 metrics/无图/无数值输出的空跑成功
  现在会被拦截，与日志描述一致）；错误消息从"经过N次修复"改为准确的
  "已尝试N次执行、自动修复N-1轮"

#### 2. 修复链无算法降级：失败后 Builder 仍用同一算法重建模
- **文件**: `main.py`
- **根因**: solver 失败 → Agent Loop → Builder 重建模时 `algorithm_map` 未变，
  MILP 修不好 MILP，最终整章留白
- **修复**: 新增 `_rebuild_with_fallback()`——重建模 feedback 前置降级指令
  （"放弃原算法，改用贪心/启发式等简单可靠方法，必须产出数值"），
  注意放在 feedback 前 2000 字内（Builder 会截断 feedback）
- **实证效果**: 重生成论文 Q4 问题分析如实写明"降级处理，后文如实说明"

#### 3. 章节编号混乱：`_normalize_headings` 无法识别伪造系统标题
- **文件**: `agents/writer.py`
- **根因（三个独立漏洞）**:
  - LLM 自带 `## 七、模型评价与推广`（中文序号格式）被当成新系统章节保留
    → 实证论文连续出现两个 `## 七、`
  - `####`/`#####` 层完全不处理 → 系统 `### 五.4` 与 LLM 自带 `#### 5.4`/`##### 5.4.1` 并存
  - 系统标题后 LLM 残留的无 # 标题行（"六、模型灵敏度分析与讨论"）形成视觉重复
- **修复**: 系统章节序号单调递增校验 + 章节名判重（伪造的降级为三级或删除）；
  4+ 级标题剥离 LLM 自带编号；系统标题后 40 字内中文序号开头的残留短行删除
- **配套 prompt**: 模型章节小节标题固定为 `#### 问题分析/模型建立/模型求解与结果`（无编号）；
  灵敏度/评价章节禁止自带章节大标题

#### 4. 标题脑补：`PROMPT_TITLE` 只给赛题文本无算法上下文
- **文件**: `agents/writer.py`
- **根因**: 标题 LLM 只见 problem_text，"动态定价"是自由发挥
- **修复**: 注入 `sub_algorithms`（各子问题实际算法）+ 一致性铁律
  （标题任务/方法必须来自实际求解方法）
- **实证效果**: 重生成标题从"…动态定价模型研究"变为
  "自行车需求时间序列预测与神经网络分类优化模型"（只含实际方法）

#### 5. Q2 方法矛盾：问题分析与实际模型是两个无锚点的 LLM 调用
- **文件**: `agents/writer.py`
- **根因**: 问题分析只拿粗粒度算法名（"聚类分析"），看不到 builder 实际
  math_model → LLM 脑补"自编码器/无监督聚类"，而实现是 MLP 监督分类
- **修复**: 新增 `_build_model_digests()`（各子问题实际模型摘要）注入
  问题分析 prompt + 一致性铁律；同时注入 `_build_exec_status()`
  （执行状态，失败子问题的分析措辞与后文对齐）
- **实证效果**: 重生成 Q2 问题分析写"监督学习下的分类…MLP"，与模型章节一致

#### 6. 质量门控不检查子问题成败
- **文件**: `agents/audit.py`
- **根因**: `LogicAuditor.run(paper, summary)` 收了 summary 但从未使用，
  9 项存在性正则全命中即高分——Q4 失败论文逻辑 8.89 分照常通过
- **修复**: 检查 `summary["executions"]` 中 status=error 的子问题，
  列为高严重度 issue（分数被拉低触发重写/停滞保护），反馈中明确
  "此问题无法通过论文重写修复，需人工重跑求解"

### 🟡 功能增强

#### 7. 符号表先行生成并注入模型章节（符号统一）
- **文件**: `agents/writer.py`
- **根因**: 符号表只拿赛题文本+算法名生成，与模型章节并行无共享约定，
  各章各用一套符号（Y_t / x^(0)(k) / D_{i,t}）
- **修复**: 符号表改为串行先行生成（基于 model_digests），全文注入各
  PROMPT_MODEL_SECTION 强制沿用

#### 8. 参考文献稳定键引用 [[键]] + 章节内引用块清理
- **文件**: `agents/writer.py`
- **根因**: 正文 LLM 自标 [N] 与文末列表两次独立生成，编号互相冲突；
  模型章节内 LLM 自带的参考文献块无人清理
- **修复**: 正文标注改为 `[[ARIMA]]` 稳定键 → `_link_citations()` 按文末
  列表实际内容解析键→编号映射后统一替换（未匹配键安全移除）；
  `_strip_inline_references()` 删除正文游离引文行与"参考文献"块标题

#### 9. `_insert_figures` 重写（防串图 + 按章节插图）
- **文件**: `agents/writer.py`
- **根因**: 扫描 figures 目录取"最新目录"——Web 多任务并发时 A 任务论文
  插入 B 任务的图；固定 [:5] 静默丢弃超出的图；相对路径依赖 cwd
- **修复**: 基于 `summary["executions"][i]["figures"]`（本次任务真实产物）
  收集图片 → 复制到 `figures/paper/sub{i}_{name}` 扁平目录 → 重写论文中
  LLM 保留的图片引用路径 → 未引用的图插入对应子问题章节（### 五.i）末尾

#### 10. `_build_model_exec_summary` 图片只传文件名
- **文件**: `agents/writer.py`
- **根因**: 2026-08-16 修了 `_build_exec_summary` 的路径泄漏但漏了此处，
  带时间戳子目录的完整路径仍会进模型章节 prompt 被 LLM 抄进论文
- **修复**: 只传 `figures/{文件名}`，实际路径由 `_insert_figures` 统一重写

### 🟢 小 Bug 修复

#### 11. solver `task_dir` 空值导致 rglob 整个项目根（执行卡死）
- **文件**: `agents/solver.py`
- **根因**: CLI 模式 task_dir=None 且环境变量未设时，`Path("")` 等价
  `Path('.')`，`exists()` 恒真 → rglob 递归整个项目（含前端 node_modules
  数万文件）并逐个复制，实测把单测直接卡死
- **修复**: task_dir 为空字符串时跳过数据上下文复制

#### 12. modeler `ptype` 变量覆盖
- **文件**: `agents/modeler.py`
- **修复**: 经验库循环内改用局部变量 `sp_type`，不再覆盖题型判定

#### 13. main.py solver 并行度误读 writer 配置
- **修复**: `get("writer.max_workers")` → `get("solver.max_workers")`

### 验证
- `tests/test_fix_20260817.py`: 29/29 通过（normalize/citations/inline-refs/
  fake_error/LogicAuditor/digests 全覆盖）
- 真实断点（Q4 失败场景）重生成论文：六项硬伤全部消除，结构干净

---

## 2026-08-16 修复 NIPT v3 论文硬伤

### 🔴 严重问题修复

#### 1. Solver "假装成功" 导致表1全空
- **文件**: `agents/solver.py`
- **根因**: `run_code()` 仅以 `returncode == 0` 判断成功，代码打印"文件不存在"但 returncode=0 时仍被视为成功
- **修复**: 增加 stdout 内容检查，识别"假装成功"模式（returncode=0 但 stdout 含错误关键词或 metrics.json 为空）
- **新增字段**: `fake_success` 标记，便于前端识别

#### 2. Builder 语法错误导致问题2被跳过
- **文件**: `agents/builder.py`
- **根因**: Builder 生成代码有缩进语法错误，`validate_code()` 拦截后返回 warning，Solver 端也无法修复
- **修复**: 语法验证失败时自动重试（最多2次），让 LLM 修正缩进/括号错误

#### 3. Writer insert_marker 不匹配导致图标题插入失败
- **文件**: `agents/writer.py`
- **根因**: 硬编码 `insert_marker = "## 灵敏度分析"` 无法匹配实际的 `"## 六、灵敏度分析"`
- **修复**: 改用正则匹配 `r"^##\s*(?:[一二三四五六七八九十]+[、.]?\s*)?灵敏度分析"`

### 🟡 功能增强

#### 4. API status 端点返回执行详情
- **文件**: `api.py`
- **新增字段**:
  - `execution_details`: 每个子问题的状态、验证状态、metrics 摘要
  - `execution_summary`: 成功/失败/跳过/已验证的统计
  - `paper_ready`: 论文是否已生成

### 📊 Web 端缺失功能分析

| 缺失功能 | 导致的问题 | 建议实现 |
|----------|-----------|----------|
| 中间结果确认 | 错误累积到论文 | 求解完成后暂停，展示 metrics + 图表供用户确认 |
| 子问题级别状态 | 看不到哪个子问题失败 | 展示每个子问题的执行状态、验证状态 |
| 论文预览 | 只有下载按钮 | 内嵌 Markdown 编辑器 + 实时预览 |
| 质量门控确认 | 自动跳过 HIL | 审核完成后暂停，展示评分供用户确认 |
| 重试/重跑 | 只能全部重跑 | 支持单独重跑某个子问题 |
| 心跳检测 | LLM 调用期间心跳停更 | 在 Solver 的 LLM 调用间歇刷新心跳 |

---

## 2026-08-16 之前的历史修复

（见对话总结中的完整列表）

### 核心 Bug 修复
1. 表格渲染为 `============== table(` - typst 转换器黑名单改正则白名单
2. `time.strftime("%f")` Windows 不兼容 - 改用毫秒拼接
3. 质量门控 100 轮失控 - 硬顶 8 轮
4. `os.environ["MATHAGENT_TASK_DIR"]` 多任务覆盖 - task_dir 参数贯穿

### GLM-5.1 审查修复
- 第一轮：质量门控轮数、子问题并行、全局变量、转换器、上传限制
- 第二轮：依赖检测、正则误伤、fig_base 冲突、无代码子问题、并发回调
- 第三轮：路径正则、归一化顺序、新检测模式、多层 task 段

### 新功能
- Web 端三选一输入、停止按钮、论文编辑面板、PDF 上传+AI 修改、心跳机制、数据路径归一化、matplotlib 线程安全、数据文件名别名、质量门控硬性红线

---

*本文件记录 ModAgent 项目的每次改进，便于追溯和复盘。*

## 2026-08-16 任务卡死问题调查

### 现象
- 任务 0545143e 卡在"求解"阶段 10+ 分钟
- API 进程 (PID 28824) 只有一个，无子进程
- 停止命令无效（任务在 LLM 调用中不检查 stop_event）

### 根因分析
1. **LLM 调用无超时保护**: `base.py` 的 `think()` 方法调用 `call_llm()`，虽有 60s 超时，但如果 LLM 服务端挂起，requests 可能不触发超时
2. **stop_event 只在 progress_callback 检查**: 如果任务卡在 LLM 调用中，不会触发 progress_callback，stop_event 永远不会被检查
3. **subprocess 超时可能失效**: Windows 上 `subprocess.run(timeout=30)` 对某些挂起的进程可能不生效

### 修复建议
1. 在 `base.py` 的 `think()` 中增加调用计时，超时主动中断
2. 在 Solver 的 LLM 调用间歇检查 stop_event
3. 考虑使用 `subprocess.Popen` + 手动超时控制

### 临时解决方案
- 重启 API 进程清除卡死任务

### 修复：任务卡死问题

**问题**: 任务卡在 LLM 调用中无法停止（stop_event 只在 progress_callback 检查）

**修复**:
1. `agents/base.py`: 新增 `set_stop_event()` / `get_stop_event()` 全局函数
2. `BaseAgent._check_stop()`: 每次 LLM 调用前后检查 stop_event
3. `api.py`: 任务启动时调用 `set_stop_event(stop_event)`，结束时清除

**效果**: 用户点击停止按钮后，LLM 调用在下一次重试时会检查并中断

## 2026-08-16 Writer 三个 prompt 级问题修复

### 1. 占位符问题（表1全空）
- **文件**: `agents/writer.py` (PROMPT_ABSTRACT, PROMPT_MODEL_SECTION)
- **根因**: Prompt 要求"若指标不存在，必须写[请填入Solver运行metrics.json中的对应值]"
- **修复**: 改为"若指标不存在或为空，写"—"或省略表格，严禁写占位符"

### 2. LLM 思考泄露
- **文件**: `agents/paper_guide.py` (STRUCTURE_GUIDE)
- **根因**: SYSTEM_PROMPT 未禁止元评论
- **修复**: 新增【输出纪律】条款，禁止"设计说明"、"我将..."、"反思"等自我指涉内容

### 3. 本地路径泄露
- **文件**: `agents/writer.py` (_build_exec_summary, _insert_figures, PROMPT_MODEL_SECTION)
- **根因**: 
  - `_build_exec_summary` 把 Solver 的绝对路径传给 LLM
  - `_insert_figures` 引用 `figures/时间戳/subN/xxx.png` 深层路径
- **修复**:
  - LLM 只看到文件名（`figures/fig_name.png`），不暴露时间戳目录
  - 图片复制到扁平目录 `figures/paper/figN.ext`，论文引用干净相对路径
  - Prompt 增加【路径规范】：禁止时间戳/子目录路径
