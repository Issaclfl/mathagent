"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

type Stage = "idle" | "running" | "done" | "error";

const API_BASE = "http://localhost:8000";

// ── 示例赛题 ──────────────────────────────────────────────
const EXAMPLES: { name: string; text: string }[] = [
  {
    name: "🚲 共享单车调度优化",
    text: `共享单车动态调度与精准投放优化

一、问题背景
某城市共享单车运营公司拥有 10000 辆共享单车，分布在城市 200 个租赁站点。公司提供了过去一年逐小时的站点租还车数据（时间、温度、湿度、风速、天气、小时、是否周末、是否节假日、租还数量等字段）。

运营中发现以下问题：
1. 高峰期站点"潮汐现象"严重：早高峰住宅区车辆被骑走，办公区无车可用；晚高峰相反。
2. 部分站点长期车辆堆积（超过站点容量），部分站点长期空置。
3. 调度车队的调度成本高，调度时机和调度量缺乏科学依据。

二、需要解决的数学问题

问题1：共享单车需求时空预测模型
基于历史数据，建立各站点逐小时借还车需求量的预测模型。要求对预测精度进行量化评估（如 MAE/RMSE），分析各特征对需求的影响程度。

问题2：站点潮汐失衡量化与调度需求识别
定义站点"失衡程度"指标，识别哪些站点在什么时段需要调度，以及需要调度多少辆车。

问题3：调度路径与运力优化模型
给定调度车（每辆可装载 50 辆车，从调度中心出发），在满足各站点调度需求的前提下，最小化总调度成本。

问题4：投放量优化建议
基于以上分析，向运营公司提出科学的单车投放量建议，使得整体满足率最高、调度成本最低。`,
  },
  {
    name: "🌊 洪涝应急物资调度",
    text: `城市洪涝灾害下"生命线"应急物资动态调度与路径规划

一、问题背景
受极端暴雨影响，某沿海城市的内河水位急剧上升，导致市区出现严重内涝。道路积水深度随时间动态变化，且部分路段因积水过深导致交通中断。应急指挥中心需要在 72小时黄金救援期内，从城郊的 3个物资储备仓库向城市内 50个受灾居民点配送应急物资（水、食品、药品）。

存在以下复杂现实约束：
- 路网动态失效：路段通行状态取决于实时积水深度
- 需求不确定：受灾点的实际人口转移情况未知
- 多模式运输：卡车（载重5吨，涉水深度<30cm）和皮划艇/冲锋舟（载重1吨）
- 层级分配：物资先运至"街道临时中转站"（5个），再由中转站分拨至各受灾点

二、需要解决的数学问题

问题1：内涝积水动态预测与路网脆弱性评估（机理+数据驱动建模）
根据简化的水量平衡方程，结合城市数字高程（DEM）数据，建立各路段积水深度随时间变化的物理方程，并构建不确定性传播模型，定量给出未来T时刻各路段积水深度超过30cm（中断阈值）的概率分布。

问题2：动态需求预测模型（逆向建模）
历史数据显示，某受灾点需求 Di(t) 与该点水位 Hi(t) 强相关，但具体表达式未知。设计一种在线学习/参数辨识方法，实时修正需求预测函数中的参数。

问题3：考虑路径中断概率的多目标动态调度优化（核心优化模型）
构建一个多周期、多物资、多模式的联合调度模型。优化目标：总配送时间最短、总运输成本最小、各受灾点物资满足率的方差最小（公平性）。约束条件中需引入机会约束。

问题4：模型失效的应急预案（鲁棒性测试）
假设在调度进行到第24小时时，突发地震导致通讯中断，失去所有实时水位数据，且一个储备仓库损毁。设计应急方案。`,
  },
];

// ── 本地历史记录 ─────────────────────────────────────────
type HistoryItem = {
  task_id: string;
  created_at: string;
  problem_preview: string;
  status: string;
  stage?: string;
};

function loadHistory(): HistoryItem[] {
  try {
    const raw = localStorage.getItem("modagent_history");
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveHistory(items: HistoryItem[]) {
  try {
    localStorage.setItem("modagent_history", JSON.stringify(items.slice(0, 20)));
  } catch {
    /* localStorage 不可用时静默忽略 */
  }
}

export default function Workspace() {
  const [problem, setProblem] = useState("");
  const [stage, setStage] = useState<Stage>("idle");
  const [logs, setLogs] = useState<string[]>([]);
  const [result, setResult] = useState<any>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [problemFile, setProblemFile] = useState<File | null>(null);
  const [dataFiles, setDataFiles] = useState<File[]>([]);

  useEffect(() => {
    setHistory(loadHistory());
  }, []);

  // ── 轮询任务状态 ────────────────────────────────────────
  const pollStatus = useCallback(async (id: string) => {
    const poll = setInterval(async () => {
      try {
        const r = await fetch(`${API_BASE}/api/status/${id}`);
        const s = await r.json();
        if (s.status === "done") {
          clearInterval(poll);
          setResult(s);
          setStage("done");
          setLogs(p => [...p, "✅ 全部流程完成"]);
          // 更新历史记录状态
          setHistory(h => {
            const next = h.map(item =>
              item.task_id === id ? { ...item, status: "done" } : item
            );
            saveHistory(next);
            return next;
          });
        } else if (s.status === "error" || s.status === "stopped") {
          clearInterval(poll);
          setLogs(p => [...p, `❌ ${s.error || "任务已停止"}`]);
          setStage("error");
        } else if (s.message) {
          setLogs(p => {
            const last = p[p.length - 1] || "";
            return last.includes(s.message) ? p : [...p, `[${s.stage || "..."}] ${s.message}`];
          });
        }
      } catch (e) {
        clearInterval(poll);
        setLogs(p => [...p, `连接失败: ${e}`]);
        setStage("error");
      }
    }, 3000);
  }, []);

  const handleRun = async () => {
    if (stage === "running") return;

    // 收集赛题文本（文件或文本域）
    let text = problem.trim();
    if (problemFile && !text) {
      text = await problemFile.text();
    }
    if (!text) {
      alert("请粘贴赛题文本或上传赛题文件");
      return;
    }

    setStage("running");
    setLogs(["提交任务..."]);

    try {
      let res: Response;
      let data: any;

      // 有数据文件 → multipart 上传；否则走文本接口
      if (dataFiles.length > 0 || problemFile) {
        const fd = new FormData();
        if (problemFile) fd.append("problem_file", problemFile);
        if (!problemFile) fd.append("extra_problem_text", text);
        dataFiles.forEach(f => fd.append("data_files", f));
        res = await fetch(`${API_BASE}/api/modeling-files`, { method: "POST", body: fd });
      } else {
        res = await fetch(`${API_BASE}/api/modeling`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ problem: text }),
        });
      }
      data = await res.json();
      if (!res.ok) throw new Error(data.error || "提交失败");

      const id = data.task_id;
      setTaskId(id);
      setLogs(p => [...p, `任务已创建: ${id}`]);

      // 写入历史
      const item: HistoryItem = {
        task_id: id,
        created_at: new Date().toLocaleString(),
        problem_preview: text.slice(0, 40) + (text.length > 40 ? "..." : ""),
        status: "running",
      };
      setHistory(h => {
        const next = [item, ...h];
        saveHistory(next);
        return next;
      });

      pollStatus(id);
    } catch (e) {
      setLogs(p => [...p, `连接失败: ${e}`]);
      setStage("error");
    }
  };

  const handleStop = async () => {
    if (taskId) {
      try {
        await fetch(`${API_BASE}/api/stop/${taskId}`, { method: "POST" });
        setLogs(p => [...p, "⏹ 已发送停止请求"]);
      } catch { /* ignore */ }
    }
  };

  const clearAll = () => {
    setProblem("");
    setProblemFile(null);
    setDataFiles([]);
    setResult(null);
    setLogs([]);
    setTaskId(null);
    setStage("idle");
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-white border-b border-gray-100 px-6 h-14 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2"><span className="text-xl">🧮</span><span className="font-bold text-gray-900">ModAgent</span></Link>
        <span className="text-sm text-gray-500">工作台</span>
      </nav>

      <div className="max-w-5xl mx-auto px-6 py-10">
        <h1 className="text-2xl font-bold text-gray-900 mb-6">📝 输入赛题</h1>

        {/* ── 输入区 ── */}
        <div className="bg-white rounded-2xl border border-gray-200 p-6 shadow-sm mb-6">
          <textarea
            value={problem}
            onChange={e => setProblem(e.target.value)}
            placeholder="将赛题文字粘贴到这里…"
            className="w-full h-48 p-4 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-gray-900/10 resize-none"
          />
          <div className="mt-3 flex flex-wrap gap-3 text-xs text-gray-500">
            {/* 示例赛题 */}
            {EXAMPLES.map(ex => (
              <button
                key={ex.name}
                onClick={() => { setProblem(ex.text); setProblemFile(null); }}
                className="px-3 py-1.5 rounded-full border border-gray-200 hover:border-gray-400 hover:text-gray-800 transition"
              >
                {ex.name}
              </button>
            ))}
          </div>

          {/* 文件上传 */}
          <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3">
            <label className="flex items-center gap-3 px-4 py-3 rounded-xl border border-dashed border-gray-300 hover:border-gray-400 cursor-pointer transition">
              <span className="text-lg">📄</span>
              <div className="flex-1 min-w-0">
                <div className="text-sm text-gray-700">赛题文件（PDF / Word / TXT）</div>
                <div className="text-xs text-gray-400 truncate">{problemFile ? problemFile.name : "上传后自动读取文本"}</div>
              </div>
              <input type="file" accept=".pdf,.docx,.txt" className="hidden"
                onChange={e => setProblemFile(e.target.files?.[0] || null)} />
            </label>
            <label className="flex items-center gap-3 px-4 py-3 rounded-xl border border-dashed border-gray-300 hover:border-gray-400 cursor-pointer transition">
              <span className="text-lg">📊</span>
              <div className="flex-1 min-w-0">
                <div className="text-sm text-gray-700">数据文件（Excel / CSV，可多选）</div>
                <div className="text-xs text-gray-400 truncate">{dataFiles.length ? `${dataFiles.length} 个文件` : "供求解代码读取"}</div>
              </div>
              <input type="file" accept=".csv,.xlsx,.xls,.txt,.json" multiple className="hidden"
                onChange={e => setDataFiles(Array.from(e.target.files || []))} />
            </label>
          </div>

          <div className="mt-4 flex items-center justify-between">
            <span className="text-xs text-gray-400">{problem.length} 字</span>
            <div className="flex gap-2">
              <button onClick={clearAll} className="px-4 py-2.5 rounded-full border border-gray-200 text-sm text-gray-600 hover:bg-gray-50 transition">
                清空
              </button>
              {stage === "running" ? (
                <button onClick={handleStop}
                  className="px-6 py-2.5 rounded-full bg-red-500 text-white text-sm font-medium hover:bg-red-600 transition">
                  ⏹ 停止
                </button>
              ) : (
                <button onClick={handleRun} disabled={!problem.trim() && !problemFile}
                  className="px-6 py-2.5 rounded-full bg-gray-900 text-white text-sm font-medium hover:bg-gray-800 disabled:opacity-50 transition">
                  🚀 开始建模
                </button>
              )}
            </div>
          </div>
        </div>

        {/* ── 运行日志 ── */}
        {logs.length > 0 && (
          <div className="bg-white rounded-2xl border border-gray-200 p-6 shadow-sm mb-6">
            <h2 className="text-sm font-semibold text-gray-700 mb-3">📋 运行日志</h2>
            <div className="bg-gray-50 rounded-xl p-4 h-48 overflow-y-auto font-mono text-xs text-gray-600 space-y-1">
              {logs.map((l, i) => <div key={i}>{l}</div>)}
              {stage === "running" && <div className="text-gray-400 animate-pulse">⏳ 运行中…</div>}
            </div>
          </div>
        )}

        {/* ── 结果 ── */}
        {result && (
          <div className="bg-white rounded-2xl border border-gray-200 p-6 shadow-sm mb-6">
            <h2 className="text-sm font-semibold text-gray-700 mb-4">📄 结果</h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="text-center p-3 bg-gray-50 rounded-xl">
                <div className="text-2xl font-bold">{result.sub_problems || 0}</div>
                <div className="text-xs text-gray-500">子问题</div>
              </div>
              <div className="text-center p-3 bg-gray-50 rounded-xl">
                <div className="text-2xl font-bold text-green-600">{result.passed ? "✓" : "✗"}</div>
                <div className="text-xs text-gray-500">质量门控</div>
              </div>
              <div className="text-center p-3 bg-gray-50 rounded-xl">
                <div className="text-2xl font-bold">{result.execution_summary?.succeeded ?? "—"}</div>
                <div className="text-xs text-gray-500">成功执行</div>
              </div>
              <div className="text-center p-3 bg-gray-50 rounded-xl flex items-center justify-center">
                <a href={`${API_BASE}/api/download/${result.task_id}`}
                  className="text-sm font-medium text-blue-600 hover:underline">⬇️ 下载论文</a>
              </div>
            </div>

            {result.execution_details && result.execution_details.length > 0 && (
              <div className="mt-5">
                <h3 className="text-xs font-semibold text-gray-500 mb-2">子问题执行详情</h3>
                <div className="space-y-2">
                  {result.execution_details.map((d: any, i: number) => (
                    <div key={i} className="flex items-center gap-3 px-3 py-2 bg-gray-50 rounded-lg text-sm">
                      <span className="text-base">{d.status === "ok" ? "✅" : d.status === "error" ? "❌" : "⏭️"}</span>
                      <span className="flex-1 text-gray-700 truncate">{i + 1}. {d.sub_problem}</span>
                      <span className="text-xs text-gray-400">{d.verification === "unverified" ? "未验证" : d.verification}</span>
                      {d.error && <span className="text-xs text-red-500 truncate max-w-[200px]">{d.error}</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── 历史记录 ── */}
        {history.length > 0 && (
          <div className="bg-white rounded-2xl border border-gray-200 p-6 shadow-sm">
            <h2 className="text-sm font-semibold text-gray-700 mb-3">🕘 历史任务</h2>
            <div className="space-y-2">
              {history.map((item, i) => (
                <div key={i} className="flex items-center gap-3 px-3 py-2 bg-gray-50 rounded-lg text-sm">
                  <span className="text-base">
                    {item.status === "done" ? "✅" : item.status === "running" ? "⏳" : "❌"}
                  </span>
                  <span className="flex-1 text-gray-700 truncate">{item.problem_preview}</span>
                  <span className="text-xs text-gray-400">{item.created_at}</span>
                  <button
                    onClick={() => {
                      setTaskId(item.task_id);
                      setStage("running");
                      setLogs([`恢复历史任务: ${item.task_id}`]);
                      pollStatus(item.task_id);
                    }}
                    className="px-2.5 py-1 rounded-full border border-gray-200 text-xs text-gray-600 hover:border-gray-400 transition"
                  >
                    查看
                  </button>
                  {item.status === "done" && (
                    <a href={`${API_BASE}/api/download/${item.task_id}`}
                      className="px-2.5 py-1 rounded-full border border-gray-200 text-xs text-blue-600 hover:border-blue-400 transition">
                      下载
                    </a>
                  )}
                </div>
              ))}
            </div>
            <p className="mt-3 text-xs text-gray-400">历史记录保存在本浏览器（localStorage），仅你自己可见。</p>
          </div>
        )}
      </div>
    </div>
  );
}
