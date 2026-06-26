"""
修复型 Prompt 构建模块
根据上一轮执行结果，分析失败原因并构造针对性的修复 Prompt
"""

from coverage_runner import CoverageRunResult

SYSTEM_PROMPT = (
    "你是一位专业的 Python 软件测试工程师，精通 pytest 框架和单元测试最佳实践。"
    "你编写的测试用例应当：\n"
    "1. 使用 pytest 风格（函数名以 test_ 开头）\n"
    "2. 覆盖正常路径、边界条件和异常路径\n"
    "3. 每个测试函数只测试一个场景，函数名清晰描述测试目的\n"
    "4. 包含必要的 import 语句\n"
    "5. 只输出可直接执行的 Python 代码，不要有任何解释文字\n"
    "6. 被测代码已保存为 target.py，导入被测函数必须使用 "
    "`from target import *` 或 `from target import 函数名`，"
    "禁止凭函数名/文件名猜测模块名（例如禁止 `from add_numbers import add_numbers`）"
)


def build_repair_prompt(
    source_code: str,
    prev_test_code: str,
    result: CoverageRunResult,
    coverage_thresholds: dict,
    round_num: int,
) -> dict:
    """
    根据上一轮结果构造修复型 Prompt
    :param source_code: 被测源代码
    :param prev_test_code: 上一轮生成的测试代码
    :param result: 上一轮执行结果
    :param coverage_thresholds: 用户设定的多覆盖率阈值（0~1）
    :param round_num: 当前是第几轮迭代（从2开始）
    """
    thresholds = _normalize_thresholds(coverage_thresholds)
    problems = _analyze_problems(result, thresholds)
    instructions = _build_instructions(result, thresholds)

    user_prompt = (
        f"【第{round_num}轮迭代修复】\n\n"
        f"被测 Python 代码：\n```python\n{source_code}\n```\n\n"
        f"上一轮生成的测试代码（存在问题，需要修复）：\n```python\n{prev_test_code}\n```\n\n"
        f"上一轮执行结果：\n{problems}\n\n"
        f"修复要求：\n{instructions}\n\n"
        "导入约束（必须遵守）：被测代码保存在 target.py 中，"
        "请使用 `from target import *` 或 `from target import 函数名` 导入，"
        "切勿凭函数名/文件名猜测模块名。\n\n"
        "请在上一轮测试代码的基础上进行修改和补充，"
        "保留已通过的测试函数，修复失败的测试函数，补充缺失的覆盖场景。"
        "直接输出完整的、可执行的 pytest 测试代码。"
    )

    return {
        "system": SYSTEM_PROMPT,
        "user": user_prompt,
        "strategy_desc": f"迭代修复（第{round_num}轮）",
    }


COVERAGE_METRICS = {
    "line": ("行覆盖率", "line_coverage", "covered_lines", "total_lines", "行"),
    "branch": ("分支覆盖率", "branch_coverage", "covered_branches", "total_branches", "分支"),
    "path": ("路径覆盖率", "path_coverage", "covered_paths", "total_paths", "条路径"),
    "code": ("代码覆盖率", "code_coverage", "covered_lines", "total_lines", "行"),
}


def _normalize_thresholds(thresholds) -> dict:
    def coerce(value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = 0.7
        if number > 1:
            number = number / 100
        return max(0.0, min(1.0, number))

    if isinstance(thresholds, dict):
        return {key: coerce(thresholds.get(key, 0.7)) for key in COVERAGE_METRICS}
    value = coerce(thresholds)
    return {key: value for key in COVERAGE_METRICS}


def _metric_is_applicable(result: CoverageRunResult, key: str) -> bool:
    if key == "code":
        return result.total_lines > 0 or result.total_branches > 0
    total_attr = COVERAGE_METRICS[key][3]
    return getattr(result, total_attr, 0) > 0


def _coverage_gaps(result: CoverageRunResult, thresholds: dict) -> list:
    # 找出尚未达到用户目标的覆盖率维度，后面转成修复指令。
    gaps = []
    if result.coverage_error:
        return gaps
    for key, threshold in thresholds.items():
        if key not in COVERAGE_METRICS or not _metric_is_applicable(result, key):
            continue
        label, coverage_attr, _, _, _ = COVERAGE_METRICS[key]
        value = getattr(result, coverage_attr, 0.0)
        if value < threshold:
            gaps.append((label, round((threshold - value) * 100, 1)))
    return gaps


def _analyze_problems(result: CoverageRunResult, thresholds: dict) -> str:
    """生成问题描述文本"""
    lines = []

    # 语法/执行错误
    if result.error_msg:
        lines.append(f"❌ 执行错误：{result.error_msg}")
        return "\n".join(lines)

    # 通过率
    pass_pct = round(result.pass_rate * 100, 1)
    lines.append(f"• 测试通过率：{pass_pct}%（{result.passed}/{result.total} 通过）")

    # 失败的测试函数
    failed_tests = [d for d in result.details if d.status in ("failed", "error")]
    if failed_tests:
        lines.append(f"• 失败的测试函数（{len(failed_tests)} 个）：")
        for d in failed_tests[:5]:  # 最多列出5个，避免 Prompt 过长
            msg_short = d.message[:200].replace("\n", " ") if d.message else "（无详细信息）"
            lines.append(f"  - {d.name}：{msg_short}")

    if result.coverage_error:
        lines.append(f"• 覆盖率数据：{result.coverage_error}")
    else:
        for key, threshold in thresholds.items():
            if key not in COVERAGE_METRICS or not _metric_is_applicable(result, key):
                continue
            label, coverage_attr, covered_attr, total_attr, unit = COVERAGE_METRICS[key]
            cov_pct = round(getattr(result, coverage_attr, 0.0) * 100, 1)
            thr_pct = round(threshold * 100, 1)
            covered = getattr(result, covered_attr, 0)
            total = getattr(result, total_attr, 0)
            lines.append(
                f"• {label}：{cov_pct}%（目标 {thr_pct}%，已覆盖 {covered}/{total} {unit}）"
            )

    # 未覆盖的代码行
    if result.missing_lines:
        ml = result.missing_lines[:10]
        lines.append(f"• 未覆盖的代码行：第 {', '.join(str(l) for l in ml)} 行")

    return "\n".join(lines)


def _build_instructions(result: CoverageRunResult, thresholds: dict) -> str:
    """根据失败原因生成修复指令"""
    instructions = []

    if result.error_msg:
        # 执行失败时优先要求修复语法/导入，而不是盲目补覆盖率。
        if "语法" in result.error_msg:
            instructions.append("1. 修复测试代码中的语法错误，确保代码可以被 Python 解析。")
            instructions.append("2. 确保 import 语句正确，使用 `from target import *` 导入被测函数。")
        elif "导入" in result.error_msg:
            instructions.append("1. 修复导入语句，使用 `from target import *` 或 `from target import 函数名`。")
        else:
            instructions.append("1. 修复导致执行失败的问题，确保测试代码可以正常运行。")
        return "\n".join(instructions)

    idx = 1
    # 修复失败测试
    failed_tests = [d for d in result.details if d.status in ("failed", "error")]
    if failed_tests:
        instructions.append(f"{idx}. 修复以上 {len(failed_tests)} 个失败的测试函数：")
        instructions.append("   - 检查断言值是否与被测函数的实际返回值匹配。")
        instructions.append("   - 如果是异常测试，确保使用 `pytest.raises()` 捕获正确的异常类型。")
        idx += 1

    coverage_gaps = _coverage_gaps(result, thresholds)
    if result.coverage_error:
        instructions.append(f"{idx}. 调整测试代码，使测试能真正导入并执行被测函数，恢复覆盖率采集。")
        idx += 1
    elif coverage_gaps:
        # 覆盖率未达标时，把缺口和未覆盖行明确告诉模型。
        gap_text = "、".join(f"{label}差 {gap}%" for label, gap in coverage_gaps)
        instructions.append(f"{idx}. 补充测试用例以提升覆盖率（当前{gap_text}）：")
        if result.missing_lines:
            instructions.append(
                f"   - 重点覆盖第 {', '.join(str(l) for l in result.missing_lines[:8])} 行的代码路径。"
            )
        instructions.append("   - 为每个条件分支（if/elif/else）各添加至少一个专门的测试用例。")
        instructions.append("   - 对循环结构，添加空集合、单元素、多元素三种场景的测试用例。")
        instructions.append("   - 增加能穿过不同返回、异常、边界路径的用例，提升路径和综合代码覆盖。")
        idx += 1

    instructions.append(f"{idx}. 保留上一轮已通过的测试函数，不要删除或修改它们。")

    return "\n".join(instructions)
