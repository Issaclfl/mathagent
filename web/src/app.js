// ============================================================
// 模块1：背景粒子系统（1000+ 粒子，连线，鼠标斥力）
// ============================================================
const bgCanvas = document.getElementById('bg-canvas');
const bgCtx = bgCanvas.getContext('2d');
let bgW, bgH, mouseX = -999, mouseY = -999;

function resizeBg() {
  bgW = bgCanvas.width = window.innerWidth;
  bgH = bgCanvas.height = window.innerHeight * 4;
}
resizeBg();
window.addEventListener('resize', resizeBg);
document.addEventListener('mousemove', e => { mouseX = e.clientX; mouseY = e.clientY; });

// 根据设备性能自适应粒子数（默认 2400，差则降）
let PARTICLE_COUNT = 2400;
const particles = [];
for (let i = 0; i < PARTICLE_COUNT; i++) {
  const hx = Math.random() * bgW, hy = Math.random() * bgH;
  particles.push({
    x: hx, y: hy,
    homeX: hx, homeY: hy, // 原始位置，鼠标离开后恢复用
    vx: (Math.random() - 0.5) * 0.3, vy: (Math.random() - 0.5) * 0.3,
    r: Math.random() * 2.5 + 1, o: Math.random() * 0.15 + 0.04,
    displaced: false // 是否被鼠标推开
  });
}

let lastFrame = 0, fps = 60;
function drawBg(ts) {
  requestAnimationFrame(drawBg);
  // 帧率检测：若低于 30fps 自动减粒子
  if (ts - lastFrame > 0) {
    fps = fps * 0.95 + (1000 / (ts - lastFrame)) * 0.05;
    if (fps < 30 && particles.length > 100) particles.length = Math.floor(particles.length * 0.8);
  }
  lastFrame = ts;

  bgCtx.clearRect(0, 0, bgW, bgH);
  for (let i = 0; i < particles.length; i++) {
    const p = particles[i];
    // 布朗运动漂移
    p.vx += (Math.random() - 0.5) * 0.02;
    p.vy += (Math.random() - 0.5) * 0.02;
    p.vx *= 0.99; p.vy *= 0.99;
    // 鼠标斥力 + 恢复逻辑
    const absMouseY = mouseY + window.scrollY;
    const dx = p.x - mouseX, dy = p.y - absMouseY;
    const dist = Math.sqrt(dx * dx + dy * dy);
    if (dist < 180 && dist > 0) {
      // 鼠标靠近：快速散开
      const force = (180 - dist) / 180 * 0.8;
      p.vx += (dx / dist) * force;
      p.vy += (dy / dist) * force;
      p.displaced = true;
    } else if (p.displaced) {
      // 鼠标离开：极慢恢复，不弹（加阻尼）
      const hx = p.homeX - p.x, hy = p.homeY - p.y;
      p.vx += hx * 0.002;
      p.vy += hy * 0.002;
      p.vx *= 0.95; p.vy *= 0.95; // 阻尼，防止弹
      if (Math.abs(hx) < 0.3 && Math.abs(hy) < 0.3) p.displaced = false;
    }
    p.x += p.vx; p.y += p.vy;
    // 边界包裹
    if (p.x < -10) p.x = bgW + 10;
    if (p.x > bgW + 10) p.x = -10;
    if (p.y < -10) p.y = bgH + 10;
    if (p.y > bgH + 10) p.y = -10;
    // 绘制粒子
    bgCtx.beginPath();
    bgCtx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
    bgCtx.fillStyle = `rgba(100,130,180,${p.o + 0.05})`;
    bgCtx.fill();
  }
  // 连线（距离 < 200px）
  bgCtx.lineWidth = 0.6;
  for (let i = 0; i < particles.length; i++) {
    for (let j = i + 1; j < Math.min(i + 60, particles.length); j++) {
      const a = particles[i], b = particles[j];
      const dx = a.x - b.x, dy = a.y - b.y;
      const d2 = dx * dx + dy * dy;
      if (d2 < 40000) { // 200^2
        const alpha = (1 - Math.sqrt(d2) / 200) * 0.1;
        bgCtx.beginPath();
        bgCtx.moveTo(a.x, a.y);
        bgCtx.lineTo(b.x, b.y);
        bgCtx.strokeStyle = `rgba(100,130,180,${alpha})`;
        bgCtx.stroke();
      }
    }
  }
}
requestAnimationFrame(drawBg);

// ============================================================
// 模块3：进度指示器（已移至工作台页面，不在首页展示）
// ============================================================

// ============================================================
// 模块4：PDF 预览（PDF.js CDN）
// ============================================================
let pdfDoc = null, pdfPage = 1, pdfScale = 1.5;

function openPDF() {
  document.getElementById('pdf-modal').classList.add('show');
  if (!pdfDoc) loadPDF();
}
function closePDF() {
  document.getElementById('pdf-modal').classList.remove('show');
}
document.getElementById('pdf-modal').addEventListener('click', e => {
  if (e.target === e.currentTarget) closePDF();
});

async function loadPDF() {
  // 动态加载 PDF.js
  if (!window.pdfjsLib) {
    const s = document.createElement('script');
    s.src = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.9.155/pdf.min.mjs';
    s.type = 'module';
    document.head.appendChild(s);
    await new Promise(r => s.onload = r);
    window.pdfjsLib = window['pdfjs-dist/build/pdf'];
    pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.9.155/pdf.worker.min.mjs';
  }
  const url = 'https://raw.githubusercontent.com/nicolo-ribaudo/pdf.js-test-files/main/docs/tracemonkey-pldi-09.pdf';
  try {
    pdfDoc = await pdfjsLib.getDocument(url).promise;
    renderPDFPage();
  } catch (e) {
    document.getElementById('pdf-viewer').innerHTML = '<p style="padding:40px;text-align:center;color:#999">PDF 加载失败，请检查网络</p>';
  }
}

async function renderPDFPage() {
  if (!pdfDoc) return;
  const page = await pdfDoc.getPage(pdfPage);
  const viewport = page.getViewport({ scale: pdfScale });
  const canvas = document.createElement('canvas');
  canvas.width = viewport.width; canvas.height = viewport.height;
  const ctx = canvas.getContext('2d');
  await page.render({ canvasContext: ctx, viewport }).promise;
  const viewer = document.getElementById('pdf-viewer');
  viewer.innerHTML = '';
  viewer.appendChild(canvas);
  document.getElementById('pdf-zoom-label').textContent = Math.round(pdfScale * 100) + '%';
}

function pdfZoom(dir) {
  if (dir === 0) pdfScale = 1.5;
  else pdfScale = Math.max(0.5, Math.min(3, pdfScale + dir * 0.25));
  renderPDFPage();
}

// ============================================================
// 导航滚动 + 滚动时背景效果
// ============================================================
function scrollTo(sel) {
  document.querySelector(sel)?.scrollIntoView({ behavior: 'smooth' });
}
window.addEventListener('scroll', () => {
  document.getElementById('nav').classList.toggle('scrolled', window.scrollY > 20);
});

// ============================================================
// 工作台：切换视图 + 运行任务
// ============================================================
function showWorkspace() {
  document.querySelector('.page').style.display = 'none';
  document.getElementById('workspace').classList.add('show');
  document.getElementById('nav').style.display = 'none';
  document.getElementById('pdf-fab').style.display = 'none';
  window.scrollTo(0, 0);
}
function showLanding() {
  document.getElementById('workspace').classList.remove('show');
  document.querySelector('.page').style.display = '';
  document.getElementById('nav').style.display = '';
  document.getElementById('pdf-fab').style.display = '';
}

// 字数计数
document.getElementById('ws-problem').addEventListener('input', e => {
  document.getElementById('ws-count').textContent = e.target.value.length + ' 字';
});

// 运行任务
let wsStage = 'idle', wsLogs = [], wsResult = null;
function handleRun() {
  const problem = document.getElementById('ws-problem').value.trim();
  if (!problem || wsStage === 'running') return;
  wsStage = 'running';
  wsLogs = [];
  document.getElementById('ws-status').textContent = '运行中';
  document.getElementById('ws-status').style.background = '#fff3e0';
  document.getElementById('ws-status').style.color = '#e65100';
  document.getElementById('ws-log-card').style.display = '';
  document.getElementById('ws-run').disabled = true;
  document.getElementById('ws-run').textContent = '⏳ 运行中...';
  addLog('提交任务...');
  fetch('http://localhost:8000/api/modeling', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      problem,
      skip_data_check: document.getElementById('ws-skip-data').checked,
      skip_solve: document.getElementById('ws-skip-solve').checked,
      skip_write: document.getElementById('ws-skip-write').checked
    })
  }).then(r => r.json()).then(data => {
    const taskId = data.task_id;
    addLog('任务已创建: ' + taskId);
    const poll = setInterval(() => {
      fetch('http://localhost:8000/api/status/' + taskId).then(r => r.json()).then(s => {
        addLog('[' + (s.stage || '...') + '] ' + (s.message || ''));
        if (s.status === 'done') {
          clearInterval(poll);
          wsResult = s;
          wsStage = 'done';
          showResult(s);
        } else if (s.status === 'error') {
          clearInterval(poll);
          addLog('❌ ' + s.error);
          wsStage = 'error';
          resetBtn();
        }
      }).catch(() => {});
    }, 5000);
  }).catch(e => {
    addLog('❌ 连接失败: ' + e);
    wsStage = 'error';
    resetBtn();
  });
}

// HIL 策略门控对话框
function showHILDialog(question, options, callback) {
  const modal = document.getElementById('hil-modal');
  document.getElementById('hil-question').textContent = question;
  const optDiv = document.getElementById('hil-options');
  optDiv.innerHTML = '';
  options.forEach((opt, i) => {
    const btn = document.createElement('button');
    btn.className = 'hil-option';
    btn.textContent = opt;
    btn.onclick = () => {
      modal.classList.remove('show');
      callback(opt, i);
    };
    optDiv.appendChild(btn);
  });
  modal.classList.add('show');
}
function addLog(msg) {
  const now = new Date().toLocaleTimeString();
  wsLogs.push({ t: now, msg: msg });
  const el = document.getElementById('ws-log');
  el.innerHTML = wsLogs.map(l => `<div><span class="log-time">${l.t}</span>${l.msg}</div>`).join('');
  el.scrollTop = el.scrollHeight;
  document.getElementById('ws-log-count').textContent = wsLogs.length + ' 条';
}
function showResult(s) {
  document.getElementById('ws-result-card').style.display = '';
  document.getElementById('ws-sp').textContent = s.sub_problems || 0;
  document.getElementById('ws-pages').textContent = s.pages || '—';
  document.getElementById('ws-pass').textContent = s.passed ? '✓' : '✗';
  document.getElementById('ws-pass').style.color = s.passed ? '#16a34a' : '#dc2626';
  document.getElementById('ws-result-badge').textContent = s.passed ? '质量通过' : '需复核';
  document.getElementById('ws-download').href = 'http://localhost:8000/api/download/' + s.task_id;
  document.getElementById('ws-status').textContent = '完成';
  document.getElementById('ws-status').style.background = '#f0fdf4';
  document.getElementById('ws-status').style.color = '#16a34a';
  resetBtn();
}
function resetBtn() {
  document.getElementById('ws-run').disabled = false;
  document.getElementById('ws-run').textContent = '🚀 开始建模';
}

// ============================================================
// 按钮涟漪效果
// ============================================================
document.addEventListener('click', e => {
  const btn = e.target.closest('button');
  if (!btn) return;
  const ripple = document.createElement('span');
  ripple.className = 'ripple';
  const rect = btn.getBoundingClientRect();
  const size = Math.max(rect.width, rect.height);
  ripple.style.width = ripple.style.height = size + 'px';
  ripple.style.left = (e.clientX - rect.left - size / 2) + 'px';
  ripple.style.top = (e.clientY - rect.top - size / 2) + 'px';
  btn.style.position = 'relative';
  btn.style.overflow = 'hidden';
  btn.appendChild(ripple);
  setTimeout(() => ripple.remove(), 600);
});

// 挂载到 window 供 HTML onclick 调用
window.showWorkspace = showWorkspace;
window.showLanding = showLanding;
window.handleRun = handleRun;
window.openPDF = openPDF;
window.closePDF = closePDF;
window.pdfZoom = pdfZoom;
window.showHILDialog = showHILDialog;
