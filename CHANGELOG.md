# ModAgent 改进日志

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
