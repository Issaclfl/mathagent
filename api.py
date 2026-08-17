"""FastAPI 后端 —— 封装 mathagent 流水线为 Web API。"""
from __future__ import annotations

import time
import uuid
import threading
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

import sys
sys.path.insert(0, str(Path(__file__).parent))

from main import run_pipeline
from utils.auth import make_token, verify_token, check_password

app = FastAPI(title="MathModelAgent API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 鉴权中间件：除登录/健康检查外，所有 /api/* 需携带有效 token ──
# 公网部署必需（防白嫖 LLM API 额度）；本地开发未配 AUTH_PASSWORD 时
# 登录端点拒绝一切，但中间件仍放行（本地无鉴权，兼容现有用法）。
@app.middleware("http")
async def _auth_middleware(request: Request, call_next):
    path = request.url.path
    # 放行：登录/健康检查（无鉴权能力时本地照常使用）
    if path in ("/api/login", "/api/health") or not path.startswith("/api/"):
        return await call_next(request)
    # 有登录密码配置 → 强制鉴权；未配置 → 本地模式放行
    if not __import__("os").environ.get("AUTH_PASSWORD"):
        return await call_next(request)
    token = None
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
    if not token:
        token = request.query_params.get("token")  # 下载链接等 <a href> 场景
    if not token or not verify_token(token):
        return JSONResponse({"error": "未授权，请先登录"}, status_code=401)
    return await call_next(request)

DATA_DIR = Path(__file__).parent / "data"
RESULTS_DIR = DATA_DIR / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# 任务存储
tasks: dict[str, dict] = {}
stop_events: dict[str, threading.Event] = {}


def _cleanup_stale_tasks() -> None:
    """服务启动时清理上次运行遗留的 task_* 目录和运行产物。

    用户痛点：历史任务目录/结果不及时清除会堆积磁盘。
    只清理 task_*（Web 任务临时目录），保留 data 下的正式数据
    （problems/、b2025/、bike_data/、manual_solutions/、experience.json）。
    """
    try:
        for d in DATA_DIR.glob("task_*"):
            if d.is_dir():
                import shutil
                shutil.rmtree(d, ignore_errors=True)
        # 清理 results 下的历史运行产物
        from main import cleanup_old_artifacts
        cleanup_old_artifacts()
    except Exception:
        pass


_cleanup_stale_tasks()


# ── 请求模型 ──────────────────────────────────────────────

class LoginRequest(BaseModel):
    password: str


@app.post("/api/login")
def login(req: LoginRequest):
    """密码登录，签发 7 天有效 token。"""
    if not check_password(req.password):
        return JSONResponse({"error": "密码错误"}, status_code=401)
    return {"status": "ok", "token": make_token()}


class ModelingRequest(BaseModel):
    problem: str
    skip_data_check: bool = False
    skip_solve: bool = False
    skip_write: bool = False


class PaperEditRequest(BaseModel):
    markdown: str


class ReviseRequest(BaseModel):
    suggestion: str


class ModelingFilesRequest(BaseModel):
    """文件上传建模请求：赛题文档 + 数据文件（multipart/form-data）。"""
    skip_data_check: bool = False
    skip_solve: bool = False
    skip_write: bool = False


# ── 任务管理 ──────────────────────────────────────────────

@app.post("/api/modeling")
def start_modeling(req: ModelingRequest):
    """提交建模任务（异步执行）。"""
    task_id = str(uuid.uuid4())[:8]
    task_dir = DATA_DIR / f"task_{task_id}"
    task_dir.mkdir(exist_ok=True)

    problem_path = task_dir / "problem.txt"
    problem_path.write_text(req.problem, encoding="utf-8")

    stop_event = threading.Event()
    stop_events[task_id] = stop_event

    tasks[task_id] = {
        "status": "running",
        "stage": "初始化",
        "task_dir": str(task_dir),
        "last_active_at": time.time(),  # 心跳：每个阶段刷新，前端据此检测卡死
    }

    # 注意：不再设置全局环境变量 MATHAGENT_TASK_DIR（多任务并发会互相覆盖），
    # 任务目录通过 run_pipeline(task_dir=...) 参数传给各阶段（线程安全）

    def _run():
        # 设置全局 stop_event，供 BaseAgent 在 LLM 调用间隙检查
        from agents.base import set_stop_event
        set_stop_event(stop_event)
        try:
            ckpt = RESULTS_DIR / "pipeline_checkpoint.json"
            if ckpt.exists():
                ckpt.unlink()

            def _progress(stage, msg):
                if stop_event.is_set():
                    raise InterruptedError("用户取消任务")
                # 心跳：每个阶段回调时刷新最后活跃时间
                tasks[task_id].update(stage=stage, message=msg, last_active_at=time.time())

            summary = run_pipeline(
                str(problem_path),
                skip_solve=req.skip_solve,
                skip_write=req.skip_write,
                skip_data_check=req.skip_data_check,
                skip_hil=True,
                progress_callback=_progress,
                task_dir=str(task_dir),
            )
            tasks[task_id].update(
                status="done",
                result=summary,
                sub_problems=len(summary.get("sub_problems", [])),
                passed=summary.get("audit", {}).get("passed", False),
                paper_path=summary.get("paper", {}).get("paper_path"),
                last_active_at=time.time(),
            )
        except InterruptedError:
            tasks[task_id].update(status="stopped", message="用户取消", last_active_at=time.time())
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            print(f"[API ERROR] {task_id}: {e}\n{tb}", flush=True)
            tasks[task_id].update(status="error", error=str(e), last_active_at=time.time())
        finally:
            set_stop_event(None)  # 清除全局 stop_event
            stop_events.pop(task_id, None)
            _cleanup_old_tasks()

    threading.Thread(target=_run, daemon=True).start()
    return {"task_id": task_id, "status": "pending"}


@app.post("/api/modeling-files")
async def start_modeling_files(
    problem_file: UploadFile | None = File(default=None),
    data_files: list[UploadFile] = File(default=[]),
    skip_data_check: bool = Form(False),
    skip_solve: bool = Form(False),
    skip_write: bool = Form(False),
    extra_problem_text: str = Form(""),
):
    """文件上传建模：赛题文档 + 数据文件（multipart/form-data）。

    - problem_file: 赛题文档（.txt/.docx/.pdf），与文本输入二选一
    - data_files: 数据文件（.csv/.xlsx/.txt/.json 等），保存到任务目录，
      Solver 执行时通过 task_dir 复制到子问题运行环境
    - extra_problem_text: 可选，用户在文本框补充的赛题说明（追加到文档文本之后）
    """
    task_id = str(uuid.uuid4())[:8]
    task_dir = DATA_DIR / f"task_{task_id}"
    task_dir.mkdir(exist_ok=True)

    # 1. 解析赛题文档
    problem_text = ""
    if problem_file is not None and problem_file.filename:
        raw = await problem_file.read()
        if len(raw) > 2 * 1024 * 1024:
            return JSONResponse({"error": "赛题文档超过 2MB 限制"}, status_code=413)
        fname = problem_file.filename.lower()
        if fname.endswith(".txt"):
            problem_text = raw.decode("utf-8", errors="replace")
        elif fname.endswith(".docx"):
            import io
            from docx import Document
            doc = Document(io.BytesIO(raw))
            problem_text = "\n".join(p.text for p in doc.paragraphs)
        elif fname.endswith(".pdf"):
            import fitz
            doc = fitz.open(stream=raw, filetype="pdf")
            problem_text = "\n".join(pg.get_text() for pg in doc)
            doc.close()
        else:
            return JSONResponse({"error": "赛题文档仅支持 .txt/.docx/.pdf"}, status_code=400)
        if not problem_text.strip():
            return JSONResponse({"error": "赛题文档无法提取文本（可能是扫描件）"}, status_code=400)
        # 保存文档副本供人工查看
        (task_dir / f"problem_uploaded{Path(problem_file.filename).suffix}").write_bytes(raw)

    # 用户补充的赛题说明追加到文档文本之后（两段用分隔线区分）
    if extra_problem_text.strip():
        problem_text = problem_text.rstrip() + "\n\n【用户补充说明】\n" + extra_problem_text.strip()

    problem_path = task_dir / "problem.txt"
    problem_path.write_text(problem_text, encoding="utf-8")

    # 2. 保存数据文件（到任务目录根，Solver 的 task_dir 逻辑会复制进执行环境）
    saved_data: list[str] = []
    for df in data_files:
        if not df.filename:
            continue
        if df.size > 50 * 1024 * 1024:
            return JSONResponse({"error": f"数据文件 {df.filename} 超过 50MB 限制"}, status_code=413)
        content = await df.read()
        # 防路径穿越：只取文件名，忽略用户提供的目录部分
        safe_name = Path(df.filename).name
        (task_dir / safe_name).write_bytes(content)
        saved_data.append(safe_name)

    # 3. 启动流水线（复用文本建模的 _run 逻辑）
    stop_event = threading.Event()
    stop_events[task_id] = stop_event
    tasks[task_id] = {
        "status": "running",
        "stage": "初始化",
        "task_dir": str(task_dir),
        "data_files": saved_data,
        "last_active_at": time.time(),  # 心跳
    }

    def _run():
        # 设置全局 stop_event，供 BaseAgent 在 LLM 调用间隙检查
        from agents.base import set_stop_event
        set_stop_event(stop_event)
        try:
            ckpt = RESULTS_DIR / "pipeline_checkpoint.json"
            if ckpt.exists():
                ckpt.unlink()

            def _progress(stage, msg):
                if stop_event.is_set():
                    raise InterruptedError("用户取消任务")
                # 心跳：每个阶段回调时刷新最后活跃时间
                tasks[task_id].update(stage=stage, message=msg, last_active_at=time.time())

            summary = run_pipeline(
                str(problem_path),
                skip_solve=skip_solve,
                skip_write=skip_write,
                skip_data_check=skip_data_check,
                skip_hil=True,
                progress_callback=_progress,
                task_dir=str(task_dir),
            )
            tasks[task_id].update(
                status="done",
                result=summary,
                sub_problems=len(summary.get("sub_problems", [])),
                passed=summary.get("audit", {}).get("passed", False),
                paper_path=summary.get("paper", {}).get("paper_path"),
                last_active_at=time.time(),
            )
        except InterruptedError:
            tasks[task_id].update(status="stopped", message="用户取消", last_active_at=time.time())
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            print(f"[API ERROR] {task_id}: {e}\n{tb}", flush=True)
            tasks[task_id].update(status="error", error=str(e), last_active_at=time.time())
        finally:
            set_stop_event(None)  # 清除全局 stop_event
            stop_events.pop(task_id, None)
            _cleanup_old_tasks()

    threading.Thread(target=_run, daemon=True).start()
    return {
        "task_id": task_id,
        "status": "pending",
        "problem_len": len(problem_text),
        "data_files": saved_data,
    }


def _cleanup_old_tasks(keep: int = 10):
    """清理旧任务目录，防止磁盘无限增长（保留最近 keep 个）。"""
    try:
        dirs = sorted(
            (d for d in DATA_DIR.glob("task_*") if d.is_dir()),
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )
        for d in dirs[keep:]:
            import shutil
            shutil.rmtree(d, ignore_errors=True)
    except Exception:
        pass


@app.post("/api/stop/{task_id}")
def stop_task(task_id: str):
    """停止正在运行的任务。"""
    stop_event = stop_events.get(task_id)
    if stop_event:
        stop_event.set()
        return {"status": "stopping"}
    return {"status": "not_found"}


@app.get("/api/status/{task_id}")
def get_status(task_id: str):
    """查询任务状态（增强版：返回执行详情供前端展示）。"""
    task = tasks.get(task_id)
    if not task:
        return {"status": "not_found"}

    # 基础状态
    resp = {
        "status": task["status"],
        "stage": task.get("stage"),
        "message": task.get("message"),
        "sub_problems": task.get("sub_problems"),
        "passed": task.get("passed"),
        "task_id": task_id,
        "error": task.get("error"),
        "last_active_at": task.get("last_active_at"),
    }

    # 增强：返回执行详情（子问题级别）
    result = task.get("result") or {}
    executions = result.get("executions") or []
    sub_problems = result.get("sub_problems") or []

    if executions and sub_problems:
        # 组装每个子问题的执行摘要
        exec_details = []
        for i, (sp, exec_data) in enumerate(zip(sub_problems, executions)):
            if not isinstance(exec_data, dict):
                exec_data = {}
            detail = {
                "index": i + 1,
                "sub_problem": sp[:80],  # 截断过长的子问题描述
                "status": exec_data.get("status", "skipped"),
                "verification": exec_data.get("verification_status", "unknown"),
                "attempts": exec_data.get("attempts"),
                "has_metrics": bool(exec_data.get("metrics_json")),
                "has_figures": bool(exec_data.get("figures")),
                "error": exec_data.get("error", "")[:200] if exec_data.get("error") else None,
            }
            # 提取关键指标摘要（如有）
            metrics_json = exec_data.get("metrics_json") or {}
            if metrics_json:
                detail["metrics_summary"] = {
                    k: v for k, v in list(metrics_json.items())[:5]
                }
            exec_details.append(detail)

        resp["execution_details"] = exec_details
        resp["execution_summary"] = {
            "total": len(sub_problems),
            "succeeded": sum(1 for e in executions if isinstance(e, dict) and e.get("status") == "ok"),
            "failed": sum(1 for e in executions if isinstance(e, dict) and e.get("status") == "error"),
            "skipped": sum(1 for e in executions if isinstance(e, dict) and e.get("status") == "skipped"),
            "verified": sum(
                1 for e in executions
                if isinstance(e, dict) and e.get("verification_status", "").startswith("verified")
            ),
        }

    # 论文状态
    if task.get("paper_path"):
        resp["paper_path"] = task["paper_path"]
        resp["paper_ready"] = True

    return resp


# ── 论文编辑 ──────────────────────────────────────────────

@app.get("/api/paper/{task_id}")
def get_paper_markdown(task_id: str):
    """获取论文 markdown 内容（用于编辑）。"""
    task = tasks.get(task_id)
    if not task:
        return JSONResponse({"error": "task not found"}, status_code=404)

    paper_path = task.get("paper_path")
    if not paper_path:
        return JSONResponse({"error": "paper not generated yet"}, status_code=404)

    md_path = Path(paper_path)
    if md_path.suffix == ".md" and md_path.exists():
        content = md_path.read_text(encoding="utf-8")
        return {"markdown": content, "path": str(md_path)}

    if md_path.suffix == ".typ":
        md_candidate = md_path.with_suffix(".md")
        if md_candidate.exists():
            content = md_candidate.read_text(encoding="utf-8")
            return {"markdown": content, "path": str(md_candidate)}

    return JSONResponse({"error": "markdown file not found"}, status_code=404)


@app.post("/api/paper/{task_id}")
def save_paper_markdown(task_id: str, req: PaperEditRequest):
    """保存修改后的论文 markdown 并重新编译 PDF。"""
    task = tasks.get(task_id)
    if not task:
        return JSONResponse({"error": "task not found"}, status_code=404)

    paper_path = task.get("paper_path")
    if not paper_path:
        return JSONResponse({"error": "paper not generated yet"}, status_code=404)

    md_path = Path(paper_path)
    if md_path.suffix == ".md":
        md_file = md_path
    elif md_path.suffix == ".typ":
        md_file = md_path.with_suffix(".md")
    else:
        return JSONResponse({"error": "unsupported file type"}, status_code=400)

    md_file.write_text(req.markdown, encoding="utf-8")

    try:
        from utils.typst_export import md_to_typst

        typ_content = md_to_typst(req.markdown)
        typ_file = md_file.with_suffix(".typ")
        typ_file.write_text(typ_content, encoding="utf-8")

        import subprocess
        typst_bin = Path(__file__).parent / "tools" / "typst-x86_64-pc-windows-msvc" / "typst.exe"
        fonts_dir = Path(__file__).parent / "fonts"
        pdf_file = md_file.with_suffix(".pdf")

        result = subprocess.run(
            [str(typst_bin), "compile", "--font-path", str(fonts_dir), str(typ_file), str(pdf_file)],
            capture_output=True,
            timeout=60,
        )

        if result.returncode != 0:
            error_msg = result.stderr.decode("utf-8", errors="replace")
            return JSONResponse({"error": f"PDF compilation failed: {error_msg}"}, status_code=500)

        task["paper_path"] = str(pdf_file)
        return {"status": "ok", "pdf_path": str(pdf_file)}

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── PDF 上传 + AI 修改 ──────────────────────────────────────

@app.post("/api/upload")
async def upload_pdf(file: UploadFile = File(...)):
    """上传已有 PDF 论文，提取文本并返回 markdown。"""
    if not file.filename.endswith('.pdf'):
        return JSONResponse({"error": "只支持 PDF 文件"}, status_code=400)

    # 上传大小限制（10MB），防止内存耗尽
    MAX_UPLOAD = 10 * 1024 * 1024
    content = await file.read()
    if len(content) > MAX_UPLOAD:
        return JSONResponse({"error": "文件超过 10MB 限制"}, status_code=413)

    task_id = str(uuid.uuid4())[:8]
    task_dir = DATA_DIR / f"task_{task_id}"
    task_dir.mkdir(exist_ok=True)

    # 保存上传的 PDF
    pdf_path = task_dir / "uploaded.pdf"
    pdf_path.write_bytes(content)

    # 提取 PDF 文本
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(pdf_path))
        page_count = len(doc)
        full_text = []
        for page_num in range(page_count):
            page = doc[page_num]
            text = page.get_text()
            full_text.append(text)
        doc.close()

        extracted = "\n".join(full_text)

        # 保存提取的文本
        md_path = task_dir / "paper.md"
        md_path.write_text(extracted, encoding="utf-8")

        tasks[task_id] = {
            "status": "uploaded",
            "task_dir": str(task_dir),
            "paper_path": str(md_path),
            "pdf_path": str(pdf_path),
            "filename": file.filename,
        }

        return {
            "task_id": task_id,
            "status": "uploaded",
            "filename": file.filename,
            "markdown": extracted,
            "pages": page_count,
        }

    except Exception as e:
        return JSONResponse({"error": f"PDF 解析失败: {str(e)}"}, status_code=500)


@app.post("/api/revise/{task_id}")
def revise_paper(task_id: str, req: ReviseRequest):
    """根据用户建议 AI 修改论文。"""
    task = tasks.get(task_id)
    if not task:
        return JSONResponse({"error": "task not found"}, status_code=404)

    md_path = Path(task.get("paper_path", ""))
    if not md_path.exists():
        return JSONResponse({"error": "论文文件不存在"}, status_code=404)

    current_md = md_path.read_text(encoding="utf-8")

    # 调用 LLM 修改论文
    try:
        from utils.llm_client import call_llm

        system_prompt = """你是一位专业的数学建模论文修改专家。
你的任务是根据用户的修改建议，对论文进行精确修改。

规则：
1. 只修改用户指定的部分，不要改动其他内容
2. 保持 Markdown 格式不变
3. 保持论文的学术性和专业性
4. 如果用户要求删除某段内容，直接删除
5. 如果用户要求添加内容，添加到合适的位置
6. 如果用户要求修改某段文字，按要求修改
7. 返回完整的修改后论文（不要省略任何部分）"""

        prompt = f"""请根据以下修改建议，对论文进行修改。

【修改建议】
{req.suggestion}

【当前论文内容】
{current_md}

请返回修改后的完整论文（Markdown 格式）："""

        revised = call_llm(prompt, system_prompt=system_prompt, temperature=0.3)

        if not revised:
            return JSONResponse({"error": "AI 修改失败，未返回结果"}, status_code=500)

        # 清理 LLM 输出中可能的前后缀
        # 有时 LLM 会加上 "以下是修改后的论文：" 等前缀
        import re
        cleaned = re.sub(r'^.*?(#{1,2}\s)', r'\1', revised, count=1, flags=re.DOTALL)

        # 保存修改后的 markdown
        md_path.write_text(cleaned, encoding="utf-8")

        # 编译 PDF
        from utils.typst_export import md_to_typst
        typ_content = md_to_typst(cleaned)
        typ_file = md_path.with_suffix(".typ")
        typ_file.write_text(typ_content, encoding="utf-8")

        import subprocess
        typst_bin = Path(__file__).parent / "tools" / "typst-x86_64-pc-windows-msvc" / "typst.exe"
        fonts_dir = Path(__file__).parent / "fonts"
        pdf_file = md_path.with_suffix(".pdf")

        result = subprocess.run(
            [str(typst_bin), "compile", "--font-path", str(fonts_dir), str(typ_file), str(pdf_file)],
            capture_output=True,
            timeout=60,
        )

        if result.returncode != 0:
            error_msg = result.stderr.decode("utf-8", errors="replace")
            return JSONResponse({"error": f"PDF 编译失败: {error_msg}"}, status_code=500)

        task["paper_path"] = str(md_path)
        task["pdf_path"] = str(pdf_file)

        return {
            "status": "ok",
            "markdown": cleaned,
            "pdf_path": str(pdf_file),
            "message": f"已根据建议修改论文并重新编译 PDF",
        }

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f"[REVISE ERROR] {task_id}: {e}\n{tb}", flush=True)
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/download/{task_id}")
def download_paper(task_id: str):
    """下载生成的论文 PDF。"""
    task = tasks.get(task_id)
    if not task:
        return JSONResponse({"error": "task not found"}, status_code=404)

    # 优先返回 pdf_path（上传的或生成的）
    pdf_path = task.get("pdf_path") or task.get("paper_path")
    if not pdf_path or not Path(pdf_path).exists():
        return JSONResponse({"error": "paper not found"}, status_code=404)

    p = Path(pdf_path)
    if p.suffix == ".md":
        return FileResponse(p, media_type="text/markdown", filename=p.name)
    return FileResponse(p, media_type="application/pdf", filename=p.name)


@app.get("/api/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    # 端口 8000：与前端 workspace 页面的 API 地址保持一致
    # （改前端或改后端都行，这里统一到 8000，用户访问习惯）
    uvicorn.run(app, host="0.0.0.0", port=8000)
