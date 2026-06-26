"""
迭代优化模块
最多运行 MAX_ROUNDS 轮，每轮结束后判断是否达标，未达标则构造修复 Prompt 继续迭代
通过 Generator 产出 SSE 事件字符串，供 Flask 流式响应使用
"""

import json
from dataclasses import asdict

from ast_parser import analyze_code
from prompt_builder import build_prompt
from llm_client import generate_test_cases
from coverage_runner import run_with_coverage, CoverageRunResult
from code_reviewer import analyze_code_review
from repair_prompt import build_repair_prompt
from bug_detector import diagnose_failures, should_block_iteration

MAX_ROUNDS = 3

COVERAGE_METRICS = {
    "line": {
        "label": "行覆盖率",
        "coverage_attr": "line_coverage",
        "covered_attr": "covered_lines",
        "total_attr": "total_lines",
    },
    "branch": {
        "label": "分支覆盖率",
        "coverage_attr": "branch_coverage",
        "covered_attr": "covered_branches",
        "total_attr": "total_branches",
    },
    "path": {
        "label": "路径覆盖率",
        "coverage_attr": "path_coverage",
        "covered_attr": "covered_paths",
        "total_attr": "total_paths",
    },
    "code": {
        "label": "代码覆盖率",
        "coverage_attr": "code_coverage",
        "covered_attr": "covered_lines",
        "total_attr": "total_lines",
    },
}


def _sse(data: dict) -> str:
    """格式化 SSE 事件"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _coerce_threshold(value, default: float) -> float:
    # 支持 0.7 和 70 两种输入形式，最终统一成 0~1。
    try:
        threshold = float(value)
    except (TypeError, ValueError):
        threshold = default
    if threshold > 1:
        threshold = threshold / 100
    return max(0.0, min(1.0, threshold))


def normalize_coverage_thresholds(raw_thresholds=None, legacy_threshold=0.7) -> dict:
    """兼容旧的单分支阈值，同时支持多覆盖率阈值。"""
    base = _coerce_threshold(legacy_threshold, 0.7)
    thresholds = {key: base for key in COVERAGE_METRICS}
    if isinstance(raw_thresholds, dict):
        for key in thresholds:
            thresholds[key] = _coerce_threshold(raw_thresholds.get(key), thresholds[key])
    return thresholds


def _metric_is_applicable(result: CoverageRunResult, metric_key: str) -> bool:
    meta = COVERAGE_METRICS[metric_key]
    total = getattr(result, meta["total_attr"], 0)
    if metric_key == "code":
        return result.total_lines > 0 or result.total_branches > 0
    return total > 0


def _coverage_failures(result: CoverageRunResult, thresholds: dict) -> list:
    failures = []
    if result.coverage_error:
        return failures
    # 逐项检查行、分支、路径、综合覆盖率是否达标。
    for key, threshold in thresholds.items():
        if key not in COVERAGE_METRICS or not _metric_is_applicable(result, key):
            continue
        meta = COVERAGE_METRICS[key]
        coverage_value = getattr(result, meta["coverage_attr"], 0.0)
        if coverage_value < threshold:
            cov_pct = round(coverage_value * 100, 1)
            thr_pct = round(threshold * 100, 1)
            failures.append(f"{meta['label']} {cov_pct}% 未达目标 {thr_pct}%")
    return failures


def _meets_threshold(result: CoverageRunResult, coverage_thresholds: dict) -> bool:
    """判断本轮是否达标：无执行错误 + 通过率100% + 各启用覆盖率达阈值"""
    if result.error_msg:
        return False
    if result.total == 0:
        return False
    if result.pass_rate < 1.0:
        return False
    if result.coverage_error:
        return False
    return not _coverage_failures(result, coverage_thresholds)


def _failure_summary(result: CoverageRunResult, coverage_thresholds: dict) -> str:
    """生成本轮失败原因的简短描述"""
    reasons = []
    if result.error_msg:
        reasons.append(result.error_msg)
    if result.total == 0:
        reasons.append("未收集到任何测试用例（可能存在语法或导入错误）")
    elif result.pass_rate < 1.0:
        failed_count = result.failed + result.errors
        reasons.append(f"{failed_count} 个测试用例未通过")
    if result.coverage_error:
        reasons.append(result.coverage_error)
    reasons.extend(_coverage_failures(result, coverage_thresholds))
    return "；".join(reasons) if reasons else "未知原因"


def run_iteration(
    source_code: str,
    model_id: str,
    strategy: str,
    coverage_thresholds: dict,
    model_name: str,
    model_config: dict = None,
):
    """
    迭代生成生成器，产出 SSE 事件字符串。
    外部通过 for event in run_iteration(...): 使用。
    """
    import database as db
    coverage_thresholds = normalize_coverage_thresholds(coverage_thresholds)
    branch_threshold = coverage_thresholds["branch"]

    # ── 初始解析 ──
    analysis = analyze_code(source_code)
    if analysis.has_syntax_error:
        yield _sse({"type": "error", "message": analysis.syntax_error_msg})
        return

    rounds_data = []
    prev_test_code = None
    prev_result = None
    first_prompt = build_prompt(strategy, source_code, analysis)

    yield _sse({"type": "start", "total_rounds": MAX_ROUNDS, "model": model_name,
                "strategy": strategy, "coverage_threshold": branch_threshold,
                "coverage_thresholds": coverage_thresholds})

    for round_num in range(1, MAX_ROUNDS + 1):

        # ── 构造 Prompt ──
        if round_num == 1:
            # 第一轮使用用户选择的生成策略。
            prompt = first_prompt
        else:
            # 后续轮次基于上一轮失败原因生成修复 Prompt。
            prompt = build_repair_prompt(
                source_code, prev_test_code, prev_result,
                coverage_thresholds, round_num
            )

        yield _sse({"type": "generating", "round": round_num})

        # ── 调用 LLM ──
        llm_result = generate_test_cases(
            model_id, prompt["system"], prompt["user"], model_config
        )
        if not llm_result["success"]:
            yield _sse({
                "type": "round_result", "round": round_num,
                "status": "error",
                "failure_reason": llm_result.get("error_message") or f"LLM 调用失败：{llm_result['error']}",
                "error_type": llm_result.get("error_type", "unknown"),
                "suggestion": llm_result.get("suggestion", ""),
                "retryable": llm_result.get("retryable", False),
                "test_code": "", "pass_rate": 0,
                "line_coverage": 0, "branch_coverage": 0,
                "path_coverage": 0, "code_coverage": 0,
                "passed": 0, "total": 0,
                "covered_lines": 0, "total_lines": 0,
                "covered_branches": 0, "total_branches": 0,
                "covered_paths": 0, "total_paths": 0,
                "details": [], "tokens_used": 0, "latency_ms": llm_result["latency_ms"],
                "coverage_error": "",
            })
            # LLM 失败直接结束
            break

        test_code = llm_result["code"]
        tokens_used = llm_result["tokens_used"]
        latency_ms = llm_result["latency_ms"]
        truncation_notice = (
            llm_result.get("error_message", "") if llm_result.get("truncated") else ""
        )

        yield _sse({"type": "executing", "round": round_num})

        # ── 执行测试 + 覆盖率 ──
        result = run_with_coverage(source_code, test_code)
        prev_test_code = test_code
        prev_result = result

        # 每轮都按通过率、执行错误和多维覆盖率判断是否达标。
        passed_round = _meets_threshold(result, coverage_thresholds)
        failure_reason = "" if passed_round else _failure_summary(result, coverage_thresholds)
        if truncation_notice:
            failure_reason = (
                f"⚠️ {truncation_notice}\n{failure_reason}"
                if failure_reason
                else f"⚠️ {truncation_notice}"
            )

        round_info = {
            "round": round_num,
            "test_code": test_code,
            "pass_rate": result.pass_rate,
            "line_coverage": result.line_coverage,
            "branch_coverage": result.branch_coverage,
            "path_coverage": result.path_coverage,
            "code_coverage": result.code_coverage,
            "covered_lines": result.covered_lines,
            "total_lines": result.total_lines,
            "covered_branches": result.covered_branches,
            "total_branches": result.total_branches,
            "covered_paths": result.covered_paths,
            "total_paths": result.total_paths,
            "passed": result.passed,
            "total": result.total,
            "failed": result.failed,
            "status": "pass" if passed_round else "fail",
            "failure_reason": failure_reason,
            "details": [asdict(d) for d in result.details],
            "tokens_used": tokens_used,
            "latency_ms": latency_ms,
            "missing_lines": result.missing_lines[:20],
            "coverage_error": result.coverage_error,
            "truncated": bool(llm_result.get("truncated")),
            "truncation_notice": truncation_notice,
            "bug_diagnosis": None,
        }

        # ── 第 1 轮失败时跑 Bug 诊断（"第二意见"） ──
        # 用 LLM 判断失败是源代码 bug 还是测试断言写错。
        # 仅当 verdict=source_bug 且高置信度时阻断后续迭代。
        bug_diagnosis = None
        if (not passed_round) and round_num == 1 and result.total > 0:
            failed_details = [d for d in result.details if d.status in ("failed", "error")]
            if failed_details:
                yield _sse({"type": "diagnosing", "round": round_num})
                bug_diagnosis = diagnose_failures(
                    source_code, test_code, failed_details, model_id, model_config
                )
                round_info["bug_diagnosis"] = bug_diagnosis
        rounds_data.append(round_info)

        yield _sse({"type": "round_result", **round_info})

        # ── Bug 诊断命中：阻断迭代，存库并结束 ──
        if bug_diagnosis and should_block_iteration(bug_diagnosis):
            code_review = analyze_code_review(source_code, result)
            yield _sse({
                "type": "source_bug_detected",
                "round": round_num,
                "diagnosis": bug_diagnosis,
            })
            record_id = db.save_iteration_record({
                "source_code": source_code,
                "model_id": model_id,
                "model_name": model_name,
                "strategy": strategy,
                "strategy_desc": first_prompt["strategy_desc"],
                "final_test_code": test_code,
                "iteration_count": round_num,
                "final_status": "source_bug",
                "final_pass_rate": result.pass_rate,
                "final_line_coverage": result.line_coverage,
                "final_branch_coverage": result.branch_coverage,
                "final_path_coverage": result.path_coverage,
                "final_code_coverage": result.code_coverage,
                "coverage_threshold": branch_threshold,
                "coverage_thresholds": coverage_thresholds,
                "rounds_detail": json.dumps(rounds_data, ensure_ascii=False),
                "total_tokens": sum(r.get("tokens_used", 0) for r in rounds_data)
                                + bug_diagnosis.get("tokens_used", 0),
                "total_latency_ms": sum(r.get("latency_ms", 0) for r in rounds_data)
                                    + bug_diagnosis.get("latency_ms", 0),
                "code_review": code_review,
            })
            yield _sse({
                "type": "done", "status": "source_bug",
                "record_id": record_id, "rounds": round_num,
                "code_review": code_review,
                "diagnosis": bug_diagnosis,
            })
            return

        if passed_round:
            code_review = analyze_code_review(source_code, result)
            # ── 达标，存库，结束 ──
            record_id = db.save_iteration_record({
                "source_code": source_code,
                "model_id": model_id,
                "model_name": model_name,
                "strategy": strategy,
                "strategy_desc": first_prompt["strategy_desc"],
                "final_test_code": test_code,
                "iteration_count": round_num,
                "final_status": "success",
                "final_pass_rate": result.pass_rate,
                "final_line_coverage": result.line_coverage,
                "final_branch_coverage": result.branch_coverage,
                "final_path_coverage": result.path_coverage,
                "final_code_coverage": result.code_coverage,
                "coverage_threshold": branch_threshold,
                "coverage_thresholds": coverage_thresholds,
                "rounds_detail": json.dumps(rounds_data, ensure_ascii=False),
                "total_tokens": sum(r.get("tokens_used", 0) for r in rounds_data),
                "total_latency_ms": sum(r.get("latency_ms", 0) for r in rounds_data),
                "code_review": code_review,
            })
            yield _sse({"type": "done", "status": "success", "record_id": record_id,
                        "rounds": round_num, "code_review": code_review})
            return

    # ── 全部轮次失败 ──
    code_review = analyze_code_review(source_code, prev_result)
    # 失败时保留各轮中的最佳指标，便于历史记录对比。
    best_branch_cov = max((r["branch_coverage"] for r in rounds_data), default=0.0)
    best_line_cov = max((r["line_coverage"] for r in rounds_data), default=0.0)
    best_path_cov = max((r["path_coverage"] for r in rounds_data), default=0.0)
    best_code_cov = max((r["code_coverage"] for r in rounds_data), default=0.0)
    best_pass = max((r["pass_rate"] for r in rounds_data), default=0.0)
    record_id = db.save_iteration_record({
        "source_code": source_code,
        "model_id": model_id,
        "model_name": model_name,
        "strategy": strategy,
        "strategy_desc": first_prompt["strategy_desc"],
        "final_test_code": prev_test_code or "",
        "iteration_count": MAX_ROUNDS,
        "final_status": "failed",
        "final_pass_rate": best_pass,
        "final_line_coverage": best_line_cov,
        "final_branch_coverage": best_branch_cov,
        "final_path_coverage": best_path_cov,
        "final_code_coverage": best_code_cov,
        "coverage_threshold": branch_threshold,
        "coverage_thresholds": coverage_thresholds,
        "rounds_detail": json.dumps(rounds_data, ensure_ascii=False),
        "total_tokens": sum(r.get("tokens_used", 0) for r in rounds_data),
        "total_latency_ms": sum(r.get("latency_ms", 0) for r in rounds_data),
        "code_review": code_review,
    })
    yield _sse({"type": "done", "status": "failed", "record_id": record_id,
                "rounds": MAX_ROUNDS, "code_review": code_review})
