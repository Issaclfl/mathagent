# 🧮 ModAgent — 数学建模智能体

面向数学建模竞赛（CUMCM / MCM / ICM）的 AI 论文生成工具。输入赛题，自动完成 **拆题 → 算法推荐 → 建模代码 → 求解修复 → 评审 → 论文生成 → 三重质量门控** 全流程，输出国赛格式论文（Markdown / Typst / PDF）。

## ✨ 核心能力

| 能力 | 说明 |
|------|------|
| 7-Agent 流水线 | 协调者→建模者→构建者→求解者→评审者→写作者→质量门控 |
| 数值验证状态 | verified_human > crosscheck > metrics > unverified 四档 |
| 确定性审核 | 逻辑/数据/排版三重审核，规则引擎，可复现 |
| 数据契约链 | 前序子问题结果通过 result_N.json 传递给后续子问题 |
| HIL 人机协作 | 数值确认 + 3 个策略门控（可 --skip-hil 全自动） |
| 自动清理 | 运行产物按保留策略自动清理，不堆积磁盘 |

## 🚀 快速开始

### 1. 环境准备

```bash
# Python 3.10+；前端需要 Node.js 18+
pip install -r requirements.txt
cd frontend && npm install && cd ..
```

### 2. 配置密钥

```bash
cp .env.example .env
# 编辑 .env，填入 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL
```

### 3. 一键启动（Windows）

```bash
start.bat
```

启动两个服务：
- **后端 API**: http://localhost:8000 （FastAPI，含健康检查 `/api/health`）
- **前端网站**: http://localhost:3000 （Next.js）

浏览器打开 **http://localhost:3000** 即可使用。

### 4. 命令行模式（调试）

```bash
python main.py                          # 跑示例赛题（data/problems/bike_shared.txt）
python main.py data/problems/xxx.txt    # 指定赛题
python main.py --until 求解             # 渐进式：跑完求解停止，人工确认后续跑
python main.py --skip-hil               # 全自动模式（跳过人工闸门）
python main.py --resume data/results/pipeline_checkpoint.json  # 断点续跑
```

## 📁 目录结构

```
mathagent/
├── main.py               # 主流水线（7-Agent 串联）
├── api.py                # FastAPI 后端（端口 8000）
├── config.yaml           # 全局配置
├── requirements.txt      # Python 依赖
├── agents/               # 7 个 Agent + 质量门控
│   ├── coordinator.py    # 拆题
│   ├── modeler.py        # 算法推荐
│   ├── builder.py        # 建模 + 代码生成
│   ├── solver.py         # 代码执行 + 修复
│   ├── reviewer.py       # 结果评审
│   ├── writer.py         # 论文生成
│   └── audit.py          # 逻辑/数据/排版三重审核
├── utils/                # 工具库（LLM/验证/HIL/经验库等）
├── scripts/              # 辅助脚本（HIL 续跑、论文修订、独立审核）
├── frontend/             # Next.js 前端（品牌名 ModAgent）
├── data/
│   ├── problems/         # 赛题文件（bike_shared.txt 等示例）
│   ├── b2025/            # 2025 B 题数据（附件）
│   ├── bike_data/        # 共享单车数据
│   ├── manual_solutions/ # 人工求解方案（manifest.json）
│   └── experience.json   # 经验库（自动积累，不入库）
└── tools/                # typst 编译工具
```

## 🧹 自动清理机制（防产物堆积）

- 每次运行 `run_pipeline` 前清理历史产物：论文保留最新 20 份、代码/图片目录各保留 30 个
- `api.py` 启动时清理残留的 `data/task_*/` 任务目录
- Web 模式下每个任务完成后清理旧任务目录（保留最近 10 个）
- `data/results/`、`data/task_*/`、`data/hil/` 均在 `.gitignore` 中，不入库

## 🧪 测试

```bash
python tests/test_run.py            # 端到端冒烟（拆题+算法）
python tests/test_full_pipeline.py  # 全流程测试
```

## 📌 已知边界

- 物理仿真/规则清晰类题目效果最佳（如 2025 国赛 A 题烟幕干扰弹）
- 依赖数据质量；无真值子问题建议开启 HIL 人工确认
- 论文质量门控不通过时最多重写 8 轮，仍不通过会标注失败状态供人工复核

## 🛠 技术栈

Python · FastAPI · Next.js · Streamlit（已移除） · MiMo LLM API · Typst
