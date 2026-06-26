"""被测代码 Bug 诊断模块

当测试执行未达标时，由 iterative_runner 调用，让 LLM 做"第二意见"：
判断失败到底是【被测代码本身有 bug】还是【LLM 生成的测试断言写错】。

verdict 取 'source_bug' / 'test_wrong' / 'both' / 'ambiguous' 之一；
仅当 verdict == 'source_bug' 且 confidence >= MIN_CONFIDENCE 时，
上层应阻断迭代并把 source_issues 反馈给用户。
"""

import json
import re
from dataclasses import asdict

from llm_client import chat_raw


MIN_CONFIDENCE = 0.6  # 低于此置信度不阻断迭代（防止 LLM 过度自信地误报）

SYSTEM_PROMPT = (
    "你是一位资深 Python 工程师，擅长定位代码缺陷。\n"
    "你将看到一段被测代码、一段针对它的 pytest 测试用例，以及测试执行的失败详情。\n"
    "你的任务：判断失败的根因是【被测代码有 bug】，还是【测试代码自身写错】。\n"
    "输出严格遵循 JSON 格式（不要任何额外文字、注释或 markdown 围栏）。"
)


def _build_user_prompt(source_code: str, test_code: str, failed_details: list) -> str:
    # 只截取前几条失败详情，避免诊断 Prompt 过长。
    failures_text = []
    for d in failed_details[:8]:
        name = getattr(d, "name", "") or "（未命名）"
        status = getattr(d, "status", "")
        msg = (getattr(d, "message", "") or "").replace("\n", "  ")[:500]
        failures_text.append(f"- {name} [{status}]：{msg}")
    failures = "\n".join(failures_text) if failures_text else "（无失败详情）"
    return (
        "【被测代码】\n```python\n"
        f"{source_code}\n```\n\n"
        "【LLM 生成的测试代码】\n```python\n"
        f"{test_code}\n```\n\n"
        "【失败的测试用例（最多 8 条）】\n"
        f"{failures}\n\n"
        "请综合上面三块信息，判断失败的真实原因。判断时注意：\n"
        "1) 函数名、参数名、docstring、约定俗成的算法语义可作为\"应有行为\"的依据。\n"
        "2) 若被测代码的实现与上述\"应有行为\"明显不符，应判 source_bug。\n"
        "3) 若被测代码本身没问题、只是测试的预期值算错了，应判 test_wrong。\n"
        "4) 不确定就给 ambiguous，不要强行判 source_bug。\n\n"
        "输出格式（严格 JSON）：\n"
        "{\n"
        '  "verdict": "source_bug" | "test_wrong" | "both" | "ambiguous",\n'
        '  "confidence": 0.0 到 1.0 的浮点数,\n'
        '  "reasoning": "200 字内中文解释",\n'
        '  "source_issues": [\n'
        "    {\n"
        '      "line": 行号（整数，没有具体行就填 0）,\n'
        '      "severity": "high" | "medium" | "low",\n'
        '      "title": "20 字内中文标题",\n'
        '      "description": "详细描述被测代码哪里写错了",\n'
        '      "suggested_fix": "具体的修复建议，必要时附正确的代码片段"\n'
        "    }\n"
        "  ],\n"
        '  "test_issues": [\n'
        "    {\n"
        '      "test_name": "test_xxx",\n'
        '      "description": "测试代码本身的问题"\n'
        "    }\n"
        "  ]\n"
        "}\n"
    )


def _safe_parse_json(raw: str) -> dict:
    """从模型输出里抠出 JSON 对象。容忍 ```json``` 围栏、前后多余文字。"""
    raw = (raw or "").strip()
    if not raw:
        return {}
    # 抠 ```json ... ``` 或 ``` ... ``` 围栏
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if fence:
        raw = fence.group(1).strip()
    # 再尝试找最外层 { ... }
    if not raw.startswith("{"):
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            raw = m.group(0)
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _normalize_diagnosis(data: dict) -> dict:
    """规范化 LLM 输出，保证字段齐全、类型正确。"""
    verdict = (data.get("verdict") or "").strip()
    if verdict not in ("source_bug", "test_wrong", "both", "ambiguous"):
        verdict = "ambiguous"
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    reasoning = str(data.get("reasoning") or "").strip()[:600]

    def _norm_source(item):
        try:
            line = int(item.get("line", 0))
        except (TypeError, ValueError):
            line = 0
        return {
            "line": line,
            "severity": item.get("severity") if item.get("severity") in ("high", "medium", "low") else "medium",
            "title": str(item.get("title") or "")[:60],
            "description": str(item.get("description") or "")[:600],
            "suggested_fix": str(item.get("suggested_fix") or "")[:1200],
        }

    def _norm_test(item):
        return {
            "test_name": str(item.get("test_name") or "")[:120],
            "description": str(item.get("description") or "")[:400],
        }

    source_issues = [_norm_source(i) for i in (data.get("source_issues") or []) if isinstance(i, dict)]
    test_issues = [_norm_test(i) for i in (data.get("test_issues") or []) if isinstance(i, dict)]
    return {
        "verdict": verdict,
        "confidence": round(confidence, 2),
        "reasoning": reasoning,
        "source_issues": source_issues[:10],
        "test_issues": test_issues[:10],
    }


def diagnose_failures(source_code: str, test_code: str, failed_details: list,
                     model_id: str, model_config: dict = None) -> dict:
    """对一次失败的测试运行做 bug 诊断。
    返回 dict：{verdict, confidence, reasoning, source_issues, test_issues, raw, llm_ok}
    """
    user_prompt = _build_user_prompt(source_code, test_code, failed_details or [])
    # 复用通用聊天接口，让模型只返回结构化 JSON 诊断结果。
    llm_result = chat_raw(model_id, SYSTEM_PROMPT, user_prompt, model_config,
                          max_tokens=2048, temperature=0.1)
    if not llm_result.get("success"):
        return {
            "verdict": "ambiguous", "confidence": 0.0,
            "reasoning": f"诊断调用失败：{llm_result.get('error', '')}",
            "source_issues": [], "test_issues": [],
            "raw": "", "llm_ok": False,
            "tokens_used": 0, "latency_ms": llm_result.get("latency_ms", 0),
        }
    parsed = _safe_parse_json(llm_result.get("raw", ""))
    diag = _normalize_diagnosis(parsed)
    diag["raw"] = llm_result.get("raw", "")[:2000]
    diag["llm_ok"] = True
    diag["tokens_used"] = llm_result.get("tokens_used", 0)
    diag["latency_ms"] = llm_result.get("latency_ms", 0)
    return diag


def should_block_iteration(diagnosis: dict) -> bool:
    """判断诊断结果是否足以阻断迭代。"""
    if not diagnosis:
        return False
    return (
        diagnosis.get("verdict") == "source_bug"
        and float(diagnosis.get("confidence", 0)) >= MIN_CONFIDENCE
        and len(diagnosis.get("source_issues") or []) > 0
    )
