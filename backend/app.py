"""Flask 后端主服务"""

from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
from dataclasses import asdict

import database as db
from ast_parser import analyze_code
from prompt_builder import build_prompt
from llm_client import generate_test_cases
from coverage_runner import run_with_coverage
from code_reviewer import analyze_code_review
from iterative_runner import run_iteration, normalize_coverage_thresholds
from config import MODEL_MAP

app = Flask(__name__)
CORS(app)
db.init_db()


# 统一成功响应格式，方便前端按 code/msg/data 解析。
def ok(data=None, msg="success"):
    return jsonify({"code": 0, "msg": msg, "data": data})

# 统一错误响应格式，保留 HTTP 状态码给前端判断。
def err(msg, code=400):
    return jsonify({"code": 1, "msg": msg, "data": None}), code


def _normalize_model_config(raw_config):
    # 前端可能传入自定义模型配置，这里做字段清洗和必填校验。
    if not isinstance(raw_config, dict):
        return None
    cfg = {
        "id": str(raw_config.get("id", "")).strip(),
        "name": str(raw_config.get("name", "")).strip(),
        "api_key": str(raw_config.get("api_key", "")).strip(),
        "base_url": str(raw_config.get("base_url", "")).strip().rstrip("/"),
        "model": str(raw_config.get("model", "")).strip(),
        "temperature": raw_config.get("temperature", 0.2),
        "max_tokens": raw_config.get("max_tokens", 4096),
    }
    if not any(cfg.get(k) for k in ("api_key", "base_url", "model")):
        return None
    missing = [k for k in ("api_key", "base_url", "model") if not cfg[k]]
    if missing:
        raise ValueError(f"自定义模型配置缺少：{', '.join(missing)}")
    if not cfg["name"]:
        cfg["name"] = cfg["model"]
    if not cfg["id"]:
        cfg["id"] = f"custom:{cfg['name']}"
    return cfg


def _get_request_model(body):
    # 优先使用自定义模型；否则回退到后端预置模型表。
    model_config = _normalize_model_config(body.get("model_config"))
    if model_config:
        return model_config["id"], model_config["name"], model_config

    model_id = str(body.get("model_id", "deepseek")).strip()
    if model_id not in MODEL_MAP:
        raise ValueError(f"不支持的模型: {model_id}")
    return model_id, MODEL_MAP[model_id]["name"], None


# ── 代码分析 ──
@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    body = request.get_json(silent=True) or {}
    code = body.get("code", "").strip()
    if not code:
        return err("代码不能为空")
    # 只做静态语法和结构分析，不调用 LLM。
    result = analyze_code(code)
    if result.has_syntax_error:
        return err(result.syntax_error_msg)
    return ok({
        "summary": result.summary,
        "functions": [
            {"name": fn.name, "args": fn.args, "return_annotation": fn.return_annotation,
             "docstring": fn.docstring, "has_conditions": fn.has_conditions,
             "has_loops": fn.has_loops, "has_exceptions": fn.has_exceptions,
             "complexity": fn.complexity, "branches": fn.branches}
            for fn in result.functions
        ],
        "classes": result.classes, "imports": result.imports,
    })


# ── 迭代生成（SSE 流式）──
@app.route("/api/iterate", methods=["POST"])
def api_iterate():
    body = request.get_json(silent=True) or {}
    source_code        = body.get("code", "").strip()
    strategy           = body.get("strategy", "structured")
    # 兼容旧版单阈值和新版多覆盖率阈值。
    try:
        coverage_threshold = float(body.get("coverage_threshold", 0.7))
    except (TypeError, ValueError):
        coverage_threshold = 0.7
    coverage_thresholds = normalize_coverage_thresholds(
        body.get("coverage_thresholds"), coverage_threshold
    )

    if not source_code:
        return err("代码不能为空")
    if strategy not in ("zero_shot", "few_shot", "structured"):
        return err(f"不支持的策略: {strategy}")
    try:
        model_id, model_name, model_config = _get_request_model(body)
    except ValueError as e:
        return err(str(e))

    def generate():
        # run_iteration 逐步产出 SSE 字符串，前端据此刷新每轮状态。
        try:
            for event in run_iteration(
                source_code, model_id, strategy,
                coverage_thresholds, model_name, model_config
            ):
                yield event
        except Exception as e:
            import json
            yield f"data: {json.dumps({'type':'error','message':str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ── 普通生成并执行（保留原功能）──
@app.route("/api/generate_and_run", methods=["POST"])
def api_generate_and_run():
    body       = request.get_json(silent=True) or {}
    code       = body.get("code", "").strip()
    strategy   = body.get("strategy", "structured")
    if not code:
        return err("代码不能为空")
    try:
        model_id, model_name, model_config = _get_request_model(body)
    except ValueError as e:
        return err(str(e))

    analysis   = analyze_code(code)
    prompt     = build_prompt(strategy, code, analysis)
    # 普通模式只生成并执行一轮，不进入修复迭代。
    llm_result = generate_test_cases(model_id, prompt["system"], prompt["user"], model_config)
    if not llm_result["success"]:
        return jsonify({
            "code": 1,
            "msg": llm_result.get("error_message") or llm_result.get("error", "LLM 调用失败"),
            "data": {
                "error_type": llm_result.get("error_type", "unknown"),
                "suggestion": llm_result.get("suggestion", ""),
                "retryable": llm_result.get("retryable", False),
            }
        }), 400

    test_code  = llm_result["code"]
    run_result = run_with_coverage(code, test_code)
    details    = [asdict(d) for d in run_result.details]
    # 将执行结果再做一次代码质量分析，前端展示为改进建议。
    code_review = analyze_code_review(code, run_result)

    record_id = db.save_record({
        "source_code": code,
        "model_id": model_id, "model_name": model_name,
        "strategy": strategy, "strategy_desc": prompt["strategy_desc"],
        "test_code": test_code,
        "total": run_result.total, "passed": run_result.passed,
        "failed": run_result.failed, "errors": run_result.errors,
        "pass_rate": run_result.pass_rate,
        "latency_ms": llm_result["latency_ms"],
        "tokens_used": llm_result["tokens_used"],
        "run_output": run_result.raw_output[:3000],
        "details": details,
        "code_review": code_review,
    })
    return ok({
        "record_id": record_id, "test_code": test_code,
        "ast_summary": analysis.summary,
        "model_name": model_name,
        "strategy_desc": prompt["strategy_desc"],
        "tokens_used": llm_result["tokens_used"],
        "latency_ms": llm_result["latency_ms"],
        "code_review": code_review,
        "run": {
            "success": run_result.success,
            "total": run_result.total, "passed": run_result.passed,
            "failed": run_result.failed, "errors": run_result.errors,
            "pass_rate": run_result.pass_rate,
            "line_coverage": run_result.line_coverage,
            "branch_coverage": run_result.branch_coverage,
            "path_coverage": run_result.path_coverage,
            "code_coverage": run_result.code_coverage,
            "covered_lines": run_result.covered_lines,
            "total_lines": run_result.total_lines,
            "covered_branches": run_result.covered_branches,
            "total_branches": run_result.total_branches,
            "covered_paths": run_result.covered_paths,
            "total_paths": run_result.total_paths,
            "missing_lines": run_result.missing_lines[:20],
            "coverage_error": run_result.coverage_error,
            "error_msg": run_result.error_msg,
            "details": details,
        },
    })


# ── 历史记录（普通） ──
@app.route("/api/history", methods=["GET"])
def api_history():
    page      = int(request.args.get("page", 1))
    page_size = int(request.args.get("page_size", 20))
    model_id  = request.args.get("model_id", "")
    return ok(db.list_records(page, page_size, model_id))

@app.route("/api/history/<int:rid>", methods=["GET"])
def api_history_detail(rid):
    r = db.get_record(rid)
    return ok(r) if r else err("记录不存在", 404)

@app.route("/api/history/<int:rid>", methods=["DELETE"])
def api_history_delete(rid):
    return ok(msg="已删除") if db.delete_record(rid) else err("记录不存在", 404)


# ── 迭代历史 ──
@app.route("/api/iter_history", methods=["GET"])
def api_iter_history():
    page      = int(request.args.get("page", 1))
    page_size = int(request.args.get("page_size", 20))
    model_id  = request.args.get("model_id", "")
    return ok(db.list_iteration_records(page, page_size, model_id))

@app.route("/api/iter_history/<int:rid>", methods=["GET"])
def api_iter_history_detail(rid):
    r = db.get_iteration_record(rid)
    return ok(r) if r else err("记录不存在", 404)

@app.route("/api/iter_history/<int:rid>", methods=["DELETE"])
def api_iter_history_delete(rid):
    return ok(msg="已删除") if db.delete_iteration_record(rid) else err("记录不存在", 404)


# ── 统计对比 ──
@app.route("/api/stats", methods=["GET"])
def api_stats():
    return ok(db.get_comparison_stats())

@app.route("/api/iter_stats", methods=["GET"])
def api_iter_stats():
    return ok(db.get_iteration_comparison_stats())

@app.route("/api/models", methods=["GET"])
def api_models():
    return ok([{"id": k, "name": v["name"]} for k, v in MODEL_MAP.items()])


# ── 示例库 ──
@app.route("/api/examples", methods=["GET"])
def api_examples():
    """扫描 backend/examples/*.py，按文件名解析 metadata（docstring 前几行 key: value）。"""
    import os
    import re
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "examples")
    if not os.path.isdir(base):
        return ok([])
    out = []
    for fname in sorted(os.listdir(base)):
        if not fname.endswith(".py") or fname.startswith("_"):
            continue
        path = os.path.join(base, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError:
            continue
        meta = {"title": fname, "category": "", "difficulty": "", "tips": ""}
        m = re.match(r'\s*"""(.*?)"""', content, re.DOTALL)
        if m:
            # 示例文件顶部 docstring 中的 key:value 会展示在前端下拉列表。
            for raw in m.group(1).split("\n"):
                line = raw.strip()
                for key in meta:
                    prefix = f"{key}:"
                    if line.lower().startswith(prefix):
                        meta[key] = line[len(prefix):].strip()
                        break
        code = re.sub(r'^\s*"""(.*?)"""\s*\n', '', content, count=1, flags=re.DOTALL).rstrip()
        out.append({
            "id": fname[:-3],
            "filename": fname,
            "title": meta["title"] or fname[:-3],
            "category": meta["category"] or "other",
            "difficulty": meta["difficulty"] or "",
            "tips": meta["tips"] or "",
            "code": code,
        })
    return ok(out)


if __name__ == "__main__":
    from config import HOST, PORT, DEBUG
    print(f"启动服务：http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=DEBUG)
