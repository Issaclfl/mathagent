import { useState, useRef } from "react";

/* ── 粒子背景（橙色系） ───────────────────── */
function ParticleBG() {
  const canvasRef = useRef(null);
  // eslint-disable-next-line
  const [dots] = useState(() =>
    Array.from({ length: 80 }, (_, i) => ({
      x: Math.random() * 1400,
      y: Math.random() * 700,
      r: Math.random() * 2.5 + 0.5,
      vx: (Math.random() - 0.5) * 0.4,
      vy: (Math.random() - 0.5) * 0.4,
      o: Math.random() * 0.15 + 0.04,
    }))
  );
  return (
    <canvas ref={canvasRef} className="absolute inset-0 pointer-events-none" style={{ width: "100%", height: "100%" }} />
  );
}

/* ── 导航栏 ──────────────────────────────── */
function Navbar({ onStart }) {
  const [scrolled, setScrolled] = useState(false);
  if (typeof window !== "undefined") {
    window.onscroll = () => setScrolled(window.scrollY > 20);
  }
  return (
    <nav className={`fixed top-0 w-full z-50 transition-all duration-300 ${scrolled ? "bg-white/90 backdrop-blur-md border-b border-gray-100 shadow-sm" : "bg-transparent"}`}>
      <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xl font-bold text-gray-900">ModAgent</span>
        </div>
        <div className="hidden md:flex items-center gap-8 text-[13px] text-gray-500 font-medium">
          <a href="#features" className="hover:text-gray-900 transition-colors">研究</a>
          <a href="#features" className="hover:text-gray-900 transition-colors">模型</a>
          <a href="#pricing" className="hover:text-gray-900 transition-colors">定价</a>
          <a href="#about" className="hover:text-gray-900 transition-colors">关于</a>
        </div>
        <div className="flex items-center gap-3">
          <button onClick={onStart} className="px-5 py-2 rounded-lg bg-gray-900 text-white text-[13px] font-semibold hover:bg-gray-800 transition-colors">
            立即体验
          </button>
        </div>
      </div>
    </nav>
  );
}

/* ── 功能数据 ───────────────────────────── */
const FEATURES = [
  { icon: "🔍", title: "智能拆题", desc: "自动分析赛题，拆解为子问题并推荐最优算法" },
  { icon: "⚙️", title: "模型建立", desc: "基于知识库生成数学模型，支持多种优化方法" },
  { icon: "💻", title: "代码执行", desc: "自动生成 Python 求解代码，独立环境执行并修复" },
  { icon: "📊", title: "图表生成", desc: "自动绘制热力图、曲线图等专业图表" },
  { icon: "📝", title: "论文撰写", desc: "生成国赛格式论文，三线表 + 公式编号 + 参考文献" },
  { icon: "✅", title: "质量门控", desc: "三重审核：逻辑 / 数据 / 排版，确保论文质量" },
];

const MODELS = [
  { name: "数学建模标准版", desc: "适用于 CUMCM/ICM 等数学建模竞赛，支持5个子问题并行求解", time: "15-25 分钟", price: "¥9.99/次", tag: null },
  { name: "数学建模专业版", desc: "在标准版基础上增加灵敏度分析、鲁棒性测试、多场景验证", time: "25-40 分钟", price: "¥19.99/次", tag: "推荐" },
  { name: "数学建模会员", desc: "无限次使用，优先队列，历史记录，专属客服支持", time: "不限", price: "¥49.99/月", tag: null },
];

/* ── Landing Page ────────────────────────── */
function Landing({ onStart }) {
  return (
    <div className="min-h-screen bg-white">
      <Navbar onStart={onStart} />

      {/* Hero */}
      <section className="relative min-h-[85vh] flex items-center justify-center bg-[#FAFAFA] overflow-hidden">
        <div className="absolute inset-0 opacity-30">
          {Array.from({ length: 120 }, (_, i) => (
            <div key={i} className="absolute rounded-full bg-gray-900" style={{
              left: `${Math.random() * 100}%`, top: `${Math.random() * 100}%`,
              width: Math.random() * 4 + 1, height: Math.random() * 4 + 1,
              opacity: Math.random() * 0.15 + 0.03,
              animation: `float ${5 + (i % 7)}s ease-in-out infinite alternate`,
              animationDelay: `${(i % 10) * 0.3}s`,
            }} />
          ))}
        </div>
        <style>{`@keyframes float { 0%{transform:translateY(0)} 100%{transform:translateY(-20px)} }`}</style>
        <div className="relative z-10 max-w-4xl mx-auto text-center px-6">
          <h1 className="text-5xl md:text-[64px] font-bold text-gray-900 leading-[1.15] tracking-tight mb-6">
            与你同行，探索
            <br />
            <span className="text-gray-900">智能建模的温度</span>
          </h1>
          <p className="text-gray-500 text-base md:text-lg max-w-xl mx-auto mb-10 leading-relaxed">
            ModAgent 是一款面向竞赛与训练场景的数学建模 AI 工具，<br className="hidden md:block" />
            可帮助你完成题目分析、模型建立、代码执行、图表生成与论文交付。
          </p>
          <div className="flex items-center justify-center gap-4">
            <button onClick={onStart} className="px-8 py-3 rounded-lg bg-gray-900 text-white font-semibold text-sm hover:bg-gray-800 transition-colors shadow-sm">
              立即体验
            </button>
            <button className="px-8 py-3 rounded-lg border border-gray-200 text-gray-700 font-semibold text-sm hover:bg-gray-50 transition-colors">
              API 接入
            </button>
          </div>
          <p className="mt-6 text-[13px] text-gray-400">
            查看 <a href="#pricing" className="text-gray-900 hover:underline font-medium">Token 套餐</a>
          </p>
        </div>
      </section>

      {/* 模型矩阵 */}
      <section id="features" className="py-24 bg-white">
        <div className="max-w-6xl mx-auto px-6">
          <div className="flex items-center gap-3 mb-4">
            <span className="w-1.5 h-6 bg-gray-900 rounded-full inline-block" />
            <h2 className="text-2xl md:text-3xl font-bold text-gray-900">模型列表</h2>
          </div>
          <p className="text-gray-400 text-sm mb-10">选择适合你的建模方案，快速上手</p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
            {MODELS.map((m) => (
              <div key={m.name} className="bg-[#F7F7F8] rounded-xl p-6 hover:shadow-md transition-shadow cursor-pointer group">
                <div className="flex items-center gap-2 mb-3">
                  <span className="text-[15px] font-bold text-gray-900">{m.name}</span>
                  {m.tag && (
                    <span className="text-[11px] font-semibold bg-gray-900 text-white px-2 py-0.5 rounded-full">{m.tag}</span>
                  )}
                </div>
                <p className="text-[13px] text-gray-500 leading-relaxed mb-4">{m.desc}</p>
                <div className="flex items-center justify-between pt-4 border-t border-gray-200/60">
                  <span className="text-[13px] text-gray-400">{m.time}</span>
                  <span className="text-sm font-bold text-gray-900">{m.price}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* 功能列表 */}
      <section className="py-24 bg-[#FAFAFA]">
        <div className="max-w-6xl mx-auto px-6">
          <div className="flex items-center gap-3 mb-4">
            <span className="w-1.5 h-6 bg-gray-900 rounded-full inline-block" />
            <h2 className="text-2xl md:text-3xl font-bold text-gray-900">核心能力</h2>
          </div>
          <p className="text-gray-400 text-sm mb-10">全流程自动化，从赛题到论文</p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {FEATURES.map((f) => (
              <div key={f.title} className="flex items-start gap-4 bg-white rounded-xl p-5 border border-gray-100 hover:border-gray-200 hover:shadow-sm transition-all">
                <div className="text-2xl mt-0.5 shrink-0">{f.icon}</div>
                <div>
                  <h3 className="text-[15px] font-bold text-gray-900 mb-1">{f.title}</h3>
                  <p className="text-[13px] text-gray-500 leading-relaxed">{f.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* 定价 */}
      <section id="pricing" className="py-24 bg-white">
        <div className="max-w-6xl mx-auto px-6">
          <div className="flex items-center gap-3 mb-4">
            <span className="w-1.5 h-6 bg-gray-900 rounded-full inline-block" />
            <h2 className="text-2xl md:text-3xl font-bold text-gray-900">定价方案</h2>
          </div>
          <p className="text-gray-400 text-sm mb-10">简单透明，按需付费</p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
            <div className="bg-[#F7F7F8] rounded-xl p-6">
              <h3 className="text-[15px] font-bold text-gray-900 mb-1">单次使用</h3>
              <div className="text-3xl font-bold text-gray-900 mb-1">¥9.99</div>
              <p className="text-[13px] text-gray-400 mb-5">一次完整建模流程</p>
              <button onClick={onStart} className="w-full py-2.5 rounded-lg border border-gray-200 text-[13px] font-semibold text-gray-700 hover:bg-gray-100 transition-colors">立即使用</button>
            </div>
            <div className="bg-gray-900 text-white rounded-xl p-6">
              <h3 className="text-[15px] font-bold mb-1">会员</h3>
              <div className="text-3xl font-bold mb-1">¥49.99<span className="text-base font-normal opacity-80">/月</span></div>
              <p className="text-[13px] opacity-70 mb-5">无限次使用</p>
              <button className="w-full py-2.5 rounded-lg bg-white text-gray-900 text-[13px] font-semibold hover:bg-gray-50 transition-colors">开通会员</button>
            </div>
            <div className="bg-[#F7F7F8] rounded-xl p-6">
              <h3 className="text-[15px] font-bold text-gray-900 mb-1">企业定制</h3>
              <div className="text-3xl font-bold text-gray-900 mb-1">联系我们</div>
              <p className="text-[13px] text-gray-400 mb-5">私有化部署/API 集成</p>
              <button className="w-full py-2.5 rounded-lg border border-gray-200 text-[13px] font-semibold text-gray-700 hover:bg-gray-100 transition-colors">联系销售</button>
            </div>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="py-10 border-t border-gray-100 bg-white">
        <div className="max-w-6xl mx-auto px-6 flex flex-col md:flex-row items-center justify-between gap-4">
          <span className="text-[13px] font-bold text-gray-900">ModAgent</span>
          <p className="text-[12px] text-gray-400">© 2026 ModAgent. All rights reserved.</p>
        </div>
      </footer>
    </div>
  );
}

/* ── Workspace ──────────────────────────── */
function Workspace({ onBack }) {
  const [problem, setProblem] = useState("");
  const [stage, setStage] = useState("idle");
  const [logs, setLogs] = useState([]);
  const [result, setResult] = useState(null);
  const logEndRef = useRef(null);

  const handleRun = async () => {
    if (!problem.trim()) return;
    setStage("running");
    setLogs([{ t: new Date().toLocaleTimeString(), msg: "提交任务..." }]);
    try {
      const res = await fetch("http://localhost:8000/api/modeling", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ problem }),
      });
      const data = await res.json();
      const taskId = data.task_id;
      setLogs(p => [...p, { t: new Date().toLocaleTimeString(), msg: `任务已创建: ${taskId}` }]);
      const poll = setInterval(async () => {
        try {
          const r = await fetch(`http://localhost:8000/api/status/${taskId}`);
          const s = await r.json();
          setLogs(p => [...p, { t: new Date().toLocaleTimeString(), msg: `[${s.stage || "..."}] ${s.message || ""}` }]);
          if (s.status === "done") { clearInterval(poll); setResult(s); setStage("done"); }
          else if (s.status === "error") { clearInterval(poll); setLogs(p => [...p, { t: new Date().toLocaleTimeString(), msg: `❌ ${s.error}` }]); setStage("error"); }
        } catch { /* poll */ }
      }, 5000);
    } catch (e) { setLogs(p => [...p, { t: new Date().toLocaleTimeString(), msg: `❌ ${e}` }]); setStage("error"); }
  };

  return (
    <div className="min-h-screen bg-[#FAFAFA]">
      <nav className="bg-white border-b border-gray-100 px-6 h-14 flex items-center justify-between">
        <button onClick={onBack} className="text-[15px] font-bold text-gray-900 hover:opacity-70 transition-opacity">
          ModAgent
        </button>
        <span className={`text-[12px] font-semibold px-3 py-1 rounded-full ${stage === "running" ? "bg-blue-50 text-gray-900" : stage === "done" ? "bg-green-50 text-green-600" : "bg-gray-100 text-gray-500"}`}>
          {stage === "running" ? "运行中" : stage === "done" ? "完成" : "就绪"}
        </span>
      </nav>
      <div className="max-w-4xl mx-auto px-6 py-8 space-y-5">
        {/* 输入 */}
        <div className="bg-white rounded-xl border border-gray-100 p-5">
          <h2 className="text-[15px] font-bold text-gray-900 mb-1">输入赛题</h2>
          <p className="text-[13px] text-gray-400 mb-4">将赛题文字粘贴到下方</p>
          <textarea value={problem} onChange={e => setProblem(e.target.value)}
            placeholder="粘贴赛题内容..."
            className="w-full h-40 p-4 bg-[#F7F7F8] rounded-lg text-[13px] text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-gray-900/20 resize-none transition-all"
          />
          <div className="flex items-center justify-between mt-3">
            <span className="text-[12px] text-gray-400">{problem.length} 字</span>
            <button onClick={handleRun} disabled={stage === "running" || !problem.trim()}
              className="px-5 py-2 rounded-lg bg-gray-900 text-white text-[13px] font-semibold hover:bg-gray-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
              {stage === "running" ? "运行中..." : "🚀 开始建模"}
            </button>
          </div>
        </div>

        {/* 日志 */}
        {logs.length > 0 && (
          <div className="bg-white rounded-xl border border-gray-100 p-5">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-[13px] font-bold text-gray-900">运行日志</h3>
              <span className="text-[11px] text-gray-400 bg-gray-50 px-2 py-0.5 rounded-full">{logs.length} 条</span>
            </div>
            <div className="bg-[#F7F7F8] rounded-lg p-3 max-h-56 overflow-y-auto">
              <div className="space-y-0.5 font-mono text-[11px]">
                {logs.map((l, i) => (
                  <div key={i} className="flex gap-2 text-gray-500">
                    <span className="text-gray-300 w-14 shrink-0">{l.t}</span>
                    <span>{l.msg}</span>
                  </div>
                ))}
                <div ref={logEndRef} />
              </div>
            </div>
          </div>
        )}

        {/* 结果 */}
        {result && (
          <div className="bg-white rounded-xl border border-gray-100 p-5">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-[15px] font-bold text-gray-900">建模结果</h3>
              <span className={`text-[12px] font-semibold px-3 py-1 rounded-full ${result.passed ? "bg-green-50 text-green-600" : "bg-red-50 text-red-500"}`}>
                {result.passed ? "质量通过" : "需复核"}
              </span>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <div className="bg-[#F7F7F8] rounded-lg p-4 text-center">
                <div className="text-2xl font-bold text-gray-900">{result.sub_problems || 0}</div>
                <div className="text-[11px] text-gray-400 mt-1">子问题</div>
              </div>
              <div className="bg-[#F7F7F8] rounded-lg p-4 text-center">
                <div className="text-2xl font-bold text-gray-900">{result.pages || "—"}</div>
                <div className="text-[11px] text-gray-400 mt-1">论文页数</div>
              </div>
              <div className="bg-[#F7F7F8] rounded-lg p-4 text-center">
                <div className="text-2xl font-bold text-green-600">{result.passed ? "✓" : "✗"}</div>
                <div className="text-[11px] text-gray-400 mt-1">质量门控</div>
              </div>
              <div className="bg-[#F7F7F8] rounded-lg p-4 flex flex-col items-center justify-center">
                <a href={`http://localhost:8000/api/download/${result.task_id}`}
                  className="text-[13px] font-semibold text-gray-900 hover:underline">⬇️ 下载论文</a>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── App ──────────────────────────────── */
export default function App() {
  const [page, setPage] = useState("landing");
  return page === "landing"
    ? <Landing onStart={() => setPage("workspace")} />
    : <Workspace onBack={() => setPage("landing")} />;
}
