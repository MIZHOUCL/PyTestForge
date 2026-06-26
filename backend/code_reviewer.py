"""被测代码问题分析模块"""

import ast
import re
import textwrap
from typing import List, Optional

from coverage_runner import CoverageRunResult


def _issue(severity: str, title: str, message: str, suggestion: str,
           line: Optional[int] = None, category: str = "quality") -> dict:
    return {
        "severity": severity,
        "title": title,
        "message": message,
        "suggestion": suggestion,
        "line": line,
        "category": category,
    }


def analyze_code_review(
    source_code: str,
    run_result: Optional[CoverageRunResult] = None,
) -> List[dict]:
    """返回被测代码的问题和改进建议。"""
    code = textwrap.dedent(source_code)
    issues = []
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [_issue(
            "high",
            "被测代码存在语法错误",
            f"第 {e.lineno} 行无法解析：{e.msg}",
            "先修复语法错误，再生成和运行测试。",
            e.lineno,
            "correctness",
        )]
    attach_parents(tree)

    # 按运行结果、模块结构、函数质量、语句风险和覆盖率依次收集建议。
    issues.extend(_runtime_issues(run_result))
    issues.extend(_module_issues(tree))
    issues.extend(_function_issues(tree))
    issues.extend(_statement_issues(tree))
    issues.extend(_coverage_issues(run_result))
    return _dedupe(issues)


def _runtime_issues(run_result: Optional[CoverageRunResult]) -> List[dict]:
    if not run_result:
        return []
    issues = []
    if run_result.error_msg:
        issues.append(_issue(
            "high",
            "测试执行阶段出现错误",
            run_result.error_msg,
            "优先确认被测代码和测试代码能稳定导入、执行，再判断覆盖率。",
            category="test",
        ))
    elif run_result.total > 0 and run_result.pass_rate < 1:
        failed_count = run_result.failed + run_result.errors
        issues.append(_issue(
            "medium",
            "存在行为不一致风险",
            f"{failed_count} 个测试用例未通过，可能是实现逻辑与预期不一致，也可能是测试断言需要修正。",
            "查看失败用例的信息，确认真实需求后修复实现或调整测试预期。",
            category="correctness",
        ))
    return issues


def _module_issues(tree: ast.AST) -> List[dict]:
    issues = []
    has_callable = any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                       for n in tree.body)
    if not has_callable:
        issues.append(_issue(
            "low",
            "缺少清晰的函数或类边界",
            "被测代码没有定义函数或类，后续复用和单元测试会比较困难。",
            "把核心逻辑封装为职责明确的函数或类，再围绕这些接口编写测试。",
        ))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.names:
            if any(alias.name == "*" for alias in node.names):
                issues.append(_issue(
                    "low",
                    "使用了通配符导入",
                    "通配符导入会让依赖来源不清晰，也容易引入命名冲突。",
                    "改为显式导入需要使用的名称。",
                    node.lineno,
                    "maintainability",
                ))
    return issues


def _function_issues(tree: ast.AST) -> List[dict]:
    issues = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # 复杂度和函数长度用于提示可维护性风险。
        complexity = _complexity(node)
        if complexity >= 12:
            issues.append(_issue(
                "high",
                "函数圈复杂度过高",
                f"`{node.name}` 的圈复杂度约为 {complexity}，分支和路径较多，维护成本较高。",
                "拆分独立判断逻辑，减少嵌套分支，或抽取策略函数。",
                node.lineno,
                "maintainability",
            ))
        elif complexity >= 8:
            issues.append(_issue(
                "medium",
                "函数逻辑偏复杂",
                f"`{node.name}` 的圈复杂度约为 {complexity}，建议关注可读性和测试场景数量。",
                "考虑拆分长条件、提取辅助函数，并补足边界测试。",
                node.lineno,
                "maintainability",
            ))

        end_lineno = getattr(node, "end_lineno", node.lineno)
        if end_lineno - node.lineno + 1 > 60:
            issues.append(_issue(
                "medium",
                "函数过长",
                f"`{node.name}` 长度超过 60 行，阅读和定位问题会变慢。",
                "按职责拆成多个更小的函数，保留一个清晰的主流程。",
                node.lineno,
                "maintainability",
            ))

        if not ast.get_docstring(node) and complexity >= 3:
            issues.append(_issue(
                "low",
                "复杂函数缺少说明",
                f"`{node.name}` 含有多个逻辑路径，但没有 docstring 说明输入、输出或异常。",
                "补充简短 docstring，说明核心行为、边界条件和异常约定。",
                node.lineno,
                "readability",
            ))

        missing_args = [arg.arg for arg in node.args.args if arg.arg != "self" and arg.annotation is None]
        if missing_args:
            issues.append(_issue(
                "info",
                "参数缺少类型标注",
                f"`{node.name}` 的参数 {', '.join(missing_args[:5])} 缺少类型标注。",
                "为公开函数补充类型标注，便于 IDE、测试生成和静态检查理解输入范围。",
                node.lineno,
                "readability",
            ))
        if node.returns is None:
            issues.append(_issue(
                "info",
                "返回值缺少类型标注",
                f"`{node.name}` 没有返回类型标注。",
                "为返回值添加类型标注，尤其是可能返回多种类型或 None 的函数。",
                node.lineno,
                "readability",
            ))

        for default in list(node.args.defaults) + list(node.args.kw_defaults):
            if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                issues.append(_issue(
                    "high",
                    "使用了可变默认参数",
                    f"`{node.name}` 使用列表、字典或集合做默认参数，可能在多次调用间共享状态。",
                    "改用 None 作为默认值，并在函数内部创建新对象。",
                    getattr(default, "lineno", node.lineno),
                    "correctness",
                ))
    return issues


def _statement_issues(tree: ast.AST) -> List[dict]:
    issues = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            if node.type is None:
                issues.append(_issue(
                    "medium",
                    "捕获了所有异常",
                    "裸 `except` 会吞掉 KeyboardInterrupt、SystemExit 等信号，也会掩盖真实错误。",
                    "捕获具体异常类型，并在必要时记录或重新抛出。",
                    node.lineno,
                    "reliability",
                ))
            elif isinstance(node.type, ast.Name) and node.type.id in {"Exception", "BaseException"}:
                issues.append(_issue(
                    "low",
                    "异常捕获范围过宽",
                    f"`except {node.type.id}` 可能隐藏具体失败原因。",
                    "尽量捕获业务上可预期的具体异常类型。",
                    node.lineno,
                    "reliability",
                ))
            if any(isinstance(ch, ast.Pass) for ch in node.body):
                issues.append(_issue(
                    "medium",
                    "异常被静默忽略",
                    "异常处理块中使用 `pass`，可能导致错误发生后系统继续处于未知状态。",
                    "至少记录错误上下文，或返回明确的失败结果。",
                    node.lineno,
                    "reliability",
                ))

        if isinstance(node, ast.Call):
            func_name = _call_name(node.func)
            if func_name in {"eval", "exec"}:
                issues.append(_issue(
                    "high",
                    "使用了动态代码执行",
                    f"`{func_name}` 会带来明显安全风险，也很难测试。",
                    "改用安全的数据解析或显式映射表，避免执行用户输入。",
                    node.lineno,
                    "security",
                ))
            elif func_name == "print":
                issues.append(_issue(
                    "info",
                    "使用 print 输出运行信息",
                    "`print` 不利于生产环境控制日志级别和输出位置。",
                    "改用 logging，并设置合适的日志级别。",
                    node.lineno,
                    "maintainability",
                ))
            elif func_name == "open" and not _inside_with(node):
                issues.append(_issue(
                    "low",
                    "文件打开未使用上下文管理器",
                    "`open()` 没有放在 `with` 中，异常时可能无法及时关闭文件。",
                    "使用 `with open(...) as f:` 管理文件生命周期。",
                    node.lineno,
                    "reliability",
                ))

        if isinstance(node, ast.Global):
            issues.append(_issue(
                "low",
                "使用了全局变量修改",
                f"`global {', '.join(node.names)}` 会让状态变化分散，测试之间也更容易互相影响。",
                "优先把状态封装到对象实例或显式参数中。",
                node.lineno,
                "maintainability",
            ))
        if isinstance(node, ast.Assert):
            issues.append(_issue(
                "low",
                "业务代码中使用 assert",
                "`assert` 在 Python 优化模式下会被移除，不适合作为业务校验。",
                "改用显式条件判断并抛出合适的异常。",
                node.lineno,
                "correctness",
            ))
        if _looks_like_secret_assignment(node):
            issues.append(_issue(
                "high",
                "疑似硬编码密钥",
                "代码中出现疑似 API Key、密码或 Token 的硬编码字符串。",
                "改用环境变量或配置文件注入敏感信息，并避免提交到版本库。",
                node.lineno,
                "security",
            ))
    return issues


def _coverage_issues(run_result: Optional[CoverageRunResult]) -> List[dict]:
    if not run_result:
        return []
    issues = []
    if run_result.coverage_error:
        issues.append(_issue(
            "medium",
            "覆盖率数据未成功采集",
            run_result.coverage_error,
            "先解决导入、语法或执行阶段问题，再根据覆盖率补测。",
            category="test",
        ))
        return issues
    if run_result.total_lines and run_result.line_coverage < 0.8:
        missing = ", ".join(str(x) for x in run_result.missing_lines[:8])
        issues.append(_issue(
            "low",
            "测试覆盖仍有明显缺口",
            f"行覆盖率为 {round(run_result.line_coverage * 100, 1)}%。"
            + (f" 未覆盖行包括：{missing}。" if missing else ""),
            "为未覆盖的返回路径、异常路径和边界输入补充测试。",
            category="coverage",
        ))
    if run_result.total_branches and run_result.branch_coverage < 0.8:
        issues.append(_issue(
            "low",
            "分支覆盖不足",
            f"分支覆盖率为 {round(run_result.branch_coverage * 100, 1)}%，仍有条件路径没有被测试命中。",
            "为每个 if/elif/else、异常和循环边界分别补充测试用例。",
            category="coverage",
        ))
    return issues


def _complexity(fn: ast.AST) -> int:
    score = 1
    for node in ast.walk(fn):
        if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.With, ast.AsyncWith)):
            score += 1
        elif isinstance(node, ast.BoolOp):
            score += max(0, len(node.values) - 1)
        elif isinstance(node, ast.IfExp):
            score += 1
    return score


def _call_name(func: ast.AST) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _inside_with(node: ast.AST) -> bool:
    parent = getattr(node, "_parent", None)
    while parent is not None:
        if isinstance(parent, (ast.With, ast.AsyncWith)):
            return True
        parent = getattr(parent, "_parent", None)
    return False


def _looks_like_secret_assignment(node: ast.AST) -> bool:
    if not isinstance(node, ast.Assign):
        return False
    names = []
    for target in node.targets:
        if isinstance(target, ast.Name):
            names.append(target.id.lower())
        elif isinstance(target, ast.Attribute):
            names.append(target.attr.lower())
    if not names or not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
        return False
    name_hit = any(re.search(r"(api[_-]?key|secret|password|token)", name) for name in names)
    value = node.value.value
    return name_hit and len(value) >= 12


def _dedupe(issues: List[dict]) -> List[dict]:
    # 去重后按严重程度排序，避免前端展示重复或低优先级过多。
    seen = set()
    result = []
    for item in issues:
        key = (item["title"], item.get("line"), item.get("message"))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    result.sort(key=lambda x: (order.get(x["severity"], 9), x.get("line") or 10**9))
    return result[:30]


def attach_parents(tree: ast.AST):
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            child._parent = parent
