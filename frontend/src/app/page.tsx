"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

function ParticleBG() {
  const [dots, setDots] = useState<{ x: number; y: number; r: number; o: number }[]>([]);
  useEffect(() => {
    setDots(Array.from({ length: 60 }, () => ({
      x: Math.random() * 100, y: Math.random() * 100,
      r: Math.random() * 3 + 1, o: Math.random() * 0.25 + 0.05,
    })));
  }, []);
  return (
    <div className="absolute inset-0 overflow-hidden pointer-events-none" aria-hidden>
      {dots.map((d, i) => (
        <div key={i} className="absolute rounded-full bg-gray-400" style={{
          left: `${d.x}%`, top: `${d.y}%`, width: d.r * 2, height: d.r * 2, opacity: d.o,
          animation: `float ${6 + Math.random() * 8}s ease-in-out infinite alternate`,
          animationDelay: `${Math.random() * 4}s`,
        }} />
      ))}
      <style jsx>{`@keyframes float { 0%{transform:translateY(0) translateX(0)} 100%{transform:translateY(-30px) translateX(15px)} }`}</style>
    </div>
  );
}

function Navbar() {
  return (
    <nav className="fixed top-0 w-full z-50 bg-white/80 backdrop-blur-md border-b border-gray-100">
      <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
        <div className="flex items-center gap-2"><span className="text-2xl">🧮</span><span className="text-lg font-bold text-gray-900">ModAgent</span></div>
        <div className="hidden md:flex items-center gap-8 text-sm text-gray-600">
          <a href="#features" className="hover:text-gray-900 transition">功能</a>
          <a href="#pricing" className="hover:text-gray-900 transition">价格</a>
        </div>
        <Link href="/workspace" className="px-5 py-2 rounded-full bg-gray-900 text-white text-sm font-medium hover:bg-gray-800 transition">开始使用 →</Link>
      </div>
    </nav>
  );
}

const FEATURES = [
  { icon: "🔍", title: "智能拆题", desc: "自动分析赛题，拆解为子问题并推荐最优算法" },
  { icon: "⚙️", title: "模型建立", desc: "基于知识库生成数学模型，支持多种优化方法" },
  { icon: "💻", title: "代码执行", desc: "自动生成 Python 求解代码，独立环境执行并修复" },
  { icon: "📊", title: "图表生成", desc: "自动绘制热力图、曲线图等专业图表" },
  { icon: "📝", title: "论文撰写", desc: "生成国赛格式论文，三线表+公式编号+参考文献" },
  { icon: "✅", title: "质量门控", desc: "三重审核：逻辑/数据/排版，确保论文质量" },
];

export default function Home() {
  return (
    <div className="min-h-screen">
      <Navbar />
      <section className="relative min-h-screen flex items-center justify-center bg-gradient-to-b from-gray-50 to-white overflow-hidden">
        <ParticleBG />
        <div className="relative z-10 max-w-4xl mx-auto text-center px-6 pt-24">
          <h1 className="text-5xl md:text-7xl font-bold text-gray-900 leading-tight tracking-tight">
            数学建模助手，<br />自动完成建模、<br />代码与论文生成
          </h1>
          <p className="mt-6 text-lg md:text-xl text-gray-500 max-w-2xl mx-auto">面向竞赛与训练场景的数学建模 AI 工具，完成题目分析、模型建立、代码执行、图表生成与论文交付。</p>          <div className="mt-10 flex items-center justify-center gap-4">
            <Link href="/workspace" className="px-8 py-3.5 rounded-full bg-gray-900 text-white font-medium hover:bg-gray-800 transition shadow-lg">开始使用</Link>
            <a href="#features" className="px-8 py-3.5 rounded-full border border-gray-300 text-gray-700 font-medium hover:bg-gray-50 transition">了解更多</a>
          </div>
        </div>
      </section>
      <section id="features" className="py-24 bg-white">
        <div className="max-w-6xl mx-auto px-6">
          <h2 className="text-3xl md:text-4xl font-bold text-center text-gray-900 mb-4">一站式建模工作流</h2>
          <p className="text-center text-gray-500 mb-16">从赛题输入到论文交付，全流程自动化</p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {FEATURES.map(f => (
              <div key={f.title} className="p-6 rounded-2xl border border-gray-100 hover:shadow-lg transition-all">
                <div className="text-4xl mb-4">{f.icon}</div>
                <h3 className="text-lg font-semibold text-gray-900 mb-2">{f.title}</h3>
                <p className="text-gray-500 text-sm">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>
      <section id="pricing" className="py-24 bg-gray-50">
        <div className="max-w-4xl mx-auto px-6 text-center">
          <h2 className="text-3xl font-bold text-gray-900 mb-12">简单透明的定价</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-8 max-w-3xl mx-auto">
            <div className="p-8 rounded-2xl bg-white border border-gray-200">
              <h3 className="text-xl font-bold mb-2">单次使用</h3>
              <div className="text-4xl font-bold mb-4">¥9.9<span className="text-lg font-normal text-gray-400">/次</span></div>
              <ul className="text-sm text-gray-600 space-y-2 text-left mb-8">
                <li>✓ 赛题分析 + 模型建立</li><li>✓ 代码执行 + 图表生成</li><li>✓ 国赛格式论文 PDF</li><li>✓ 质量门控审核</li>
              </ul>
              <Link href="/workspace" className="block w-full py-3 rounded-full border border-gray-300 text-center font-medium hover:bg-gray-50 transition">立即使用</Link>
            </div>
            <div className="p-8 rounded-2xl bg-gray-900 text-white">
              <h3 className="text-xl font-bold mb-2">会员</h3>
              <div className="text-4xl font-bold mb-4">¥49.9<span className="text-lg font-normal text-gray-400">/月</span></div>
              <ul className="text-sm text-gray-300 space-y-2 text-left mb-8">
                <li>✓ 无限次建模</li><li>✓ 优先队列</li><li>✓ 历史记录</li><li>✓ 专属客服</li>
              </ul>
              <button className="block w-full py-3 rounded-full bg-white text-gray-900 font-medium hover:bg-gray-100 transition" onClick={() => alert("支付功能即将上线，敬请期待 🚀")}>开通会员</button>
            </div>
          </div>
        </div>
      </section>
      <footer className="py-12 border-t border-gray-100 bg-white">
        <div className="max-w-6xl mx-auto px-6 flex items-center justify-between">
          <div className="flex items-center gap-2"><span className="text-xl">🧮</span><span className="font-bold">ModAgent</span></div>
          <p className="text-sm text-gray-400">© 2026 ModAgent · 数学建模智能体</p>
        </div>
      </footer>
    </div>
  );
}
