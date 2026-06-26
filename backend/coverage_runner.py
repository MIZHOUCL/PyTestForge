"""
覆盖率执行模块
在独立子进程中运行 pytest + coverage.py，采集测试结果和多维覆盖率
"""

import ast
import os
import re
import sys
import json
import tempfile
import subprocess
from dataclasses import dataclass
from typing import List
from config import TEST_TIMEOUT


@dataclass
class TestDetail:
    name: str
    status: str       # passed / failed / error
    message: str
    duration_ms: float


@dataclass
class CoverageRunResult:
    success: bool
    total: int
    passed: int
    failed: int
    errors: int
    pass_rate: float
    branch_coverage: float        # 分支覆盖率 0.0 ~ 1.0
    covered_branches: int
    total_branches: int
    missing_lines: List[int]      # 未覆盖的代码行
    details: List[TestDetail]
    raw_output: str
    error_msg: str
    line_coverage: float = 0.0    # 行覆盖率 0.0 ~ 1.0
    covered_lines: int = 0
    total_lines: int = 0
    path_coverage: float = 0.0    # 路径覆盖率（基于 coverage.py 分支路径）0.0 ~ 1.0
    covered_paths: int = 0
    total_paths: int = 0
    code_coverage: float = 0.0    # coverage.py 综合代码覆盖率 0.0 ~ 1.0
    coverage_error: str = ""


# 标准库 + 测试框架 + 常用第三方库的根模块名。
# 这些模块的 import 会被保留，其他全部改写为 from target import ...
_SAFE_IMPORT_ROOTS = {
    # 测试框架
    "pytest", "unittest", "mock", "hypothesis", "doctest",
    # 标准库（覆盖测试用例中常用）
    "math", "re", "json", "sys", "os", "io", "time", "datetime", "calendar",
    "random", "string", "decimal", "fractions", "statistics", "numbers",
    "collections", "itertools", "functools", "operator", "copy", "bisect",
    "heapq", "queue", "weakref",
    "typing", "enum", "dataclasses", "abc", "contextlib", "types",
    "pathlib", "tempfile", "shutil", "glob", "csv", "configparser",
    "argparse", "warnings", "logging", "traceback",
    "threading", "multiprocessing", "subprocess", "asyncio", "concurrent",
    "urllib", "http", "socket", "email", "html", "xml", "ssl",
    "hashlib", "hmac", "secrets", "uuid", "base64", "binascii", "struct",
    "ast", "inspect", "textwrap", "pprint", "reprlib",
    "pickle", "shelve", "marshal", "sqlite3",
    "__future__", "builtins",
    # 常用第三方
    "numpy", "pandas", "scipy",
}

# 旧版本中识别的占位符模块名，在 AST 解析失败时由 fallback 使用
_LEGACY_PLACEHOLDERS = (
    "your_module", "module", "solution", "src", "main", "code", "target_module",
)


def _is_safe_import(module: str) -> bool:
    """判断 import 的模块是否属于标准库/测试库/常用第三方库白名单。"""
    if not module:
        return False
    root = module.split(".")[0]
    return root in _SAFE_IMPORT_ROOTS


def _rebuild_import_from(node: ast.ImportFrom) -> str:
    """将 from X import a, b as c 改写为 from target import a, b as c。"""
    names_part = ", ".join(
        f"{alias.name} as {alias.asname}" if alias.asname else alias.name
        for alias in node.names
    )
    if not names_part:
        return "from target import *"
    return f"from target import {names_part}"


def _split_import(node: ast.Import) -> tuple:
    """把 import a, b, c 拆成 (保留的别名列表, 是否需要补 target 通配)。"""
    safe = [a for a in node.names if _is_safe_import(a.name)]
    unsafe_count = len(node.names) - len(safe)
    return safe, unsafe_count > 0


def _ast_inject_import(test_code: str) -> str:
    """基于 AST 的 import 改写：所有非白名单模块统一指向 target。"""
    tree = ast.parse(test_code)
    lines = test_code.splitlines()

    edits = []  # (start_lineno, end_lineno, replacement_lines)
    has_target_import = False

    for node in tree.body:
        # LLM 常会猜模块名，这里把非白名单导入统一修正为 target。
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level and node.level > 0:
                edits.append((node.lineno, node.end_lineno, [_rebuild_import_from(node)]))
                has_target_import = True
                continue
            if module == "target":
                has_target_import = True
                continue
            if _is_safe_import(module):
                continue
            edits.append((node.lineno, node.end_lineno, [_rebuild_import_from(node)]))
            has_target_import = True
        elif isinstance(node, ast.Import):
            safe_aliases, has_unsafe = _split_import(node)
            if not has_unsafe:
                if any(a.name == "target" for a in node.names):
                    has_target_import = True
                continue
            replacement = []
            if safe_aliases:
                replacement.append(
                    "import " + ", ".join(
                        f"{a.name} as {a.asname}" if a.asname else a.name
                        for a in safe_aliases
                    )
                )
            replacement.append("from target import *")
            edits.append((node.lineno, node.end_lineno, replacement))
            has_target_import = True

    for start, end, replacement in sorted(edits, key=lambda x: -x[0]):
        del lines[start - 1:end]
        for offset, line in enumerate(replacement):
            lines.insert(start - 1 + offset, line)

    new_code = "\n".join(lines)
    if not has_target_import:
        new_code = "from target import *\n\n" + new_code
    return new_code


def _legacy_inject_import(test_code: str) -> str:
    """AST 解析失败时的兜底：保留旧的占位符替换 + 顶部追加 target 通配导入。"""
    placeholder_group = "|".join(_LEGACY_PLACEHOLDERS)
    test_code = re.sub(
        rf'from\s+(?:{placeholder_group})\s+import',
        'from target import',
        test_code,
    )
    test_code = re.sub(
        rf'import\s+(?:{placeholder_group})\b',
        'import target',
        test_code,
    )
    if "from target import" not in test_code and "import target" not in test_code:
        test_code = "from target import *\n\n" + test_code
    return test_code


def _inject_import(test_code: str) -> str:
    """改写 LLM 生成的 import：标准库/pytest 等保留，其他全部指向 target。"""
    try:
        return _ast_inject_import(test_code)
    except SyntaxError:
        return _legacy_inject_import(test_code)


def run_with_coverage(source_code: str, test_code: str) -> CoverageRunResult:
    """
    执行测试并采集行、分支、路径、综合代码覆盖率。
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # 在临时目录中隔离被测代码和测试代码，避免污染项目文件。
        src_path  = os.path.join(tmpdir, "target.py")
        test_path = os.path.join(tmpdir, "test_target.py")
        cov_path  = os.path.join(tmpdir, "coverage.json")
        rep_path  = os.path.join(tmpdir, "report.json")
        cov_data  = os.path.join(tmpdir, ".coverage")

        with open(src_path,  "w", encoding="utf-8") as f:
            f.write(source_code)
        with open(test_path, "w", encoding="utf-8") as f:
            f.write(_inject_import(test_code))

        # Step1: coverage run + pytest
        cmd_run = [
            sys.executable, "-m", "coverage", "run",
            f"--data-file={cov_data}",
            "--branch",
            f"--source=target",
            "-m", "pytest", test_path,
            "-v", "--tb=short", "--no-header",
            "-p", "no:cacheprovider",
            "--json-report",
            f"--json-report-file={rep_path}",
        ]
        try:
            proc = subprocess.run(
                cmd_run, cwd=tmpdir,
                capture_output=True, text=True,
                timeout=TEST_TIMEOUT,
            )
            raw_output = proc.stdout + proc.stderr
        except subprocess.TimeoutExpired:
            return CoverageRunResult(
                success=False, total=0, passed=0, failed=0, errors=0,
                pass_rate=0.0, branch_coverage=0.0,
                covered_branches=0, total_branches=0,
                missing_lines=[], details=[], raw_output="",
                error_msg=f"执行超时（>{TEST_TIMEOUT}秒），请检查代码是否含有死循环。",
                coverage_error="执行超时，未生成覆盖率数据。",
            )
        except Exception as e:
            return CoverageRunResult(
                success=False, total=0, passed=0, failed=0, errors=0,
                pass_rate=0.0, branch_coverage=0.0,
                covered_branches=0, total_branches=0,
                missing_lines=[], details=[], raw_output="",
                error_msg=f"执行异常：{e}",
                coverage_error="执行异常，未生成覆盖率数据。",
            )

        # Step2: coverage json
        cmd_json = [
            sys.executable, "-m", "coverage", "json",
            f"--data-file={cov_data}",
            "-o", cov_path,
        ]
        try:
            json_proc = subprocess.run(
                cmd_json, cwd=tmpdir,
                capture_output=True, text=True, timeout=10
            )
            coverage_output = (json_proc.stdout or "") + (json_proc.stderr or "")
        except subprocess.TimeoutExpired:
            coverage_output = "coverage json 生成超时"
        except Exception as e:
            coverage_output = f"coverage json 生成失败：{e}"

        # Step3: 解析 pytest JSON
        pytest_result = _parse_pytest_json(rep_path, raw_output)

        # Step4: 解析 coverage JSON
        coverage_data = _parse_coverage_json(cov_path, coverage_output)
        for key, value in coverage_data.items():
            setattr(pytest_result, key, value)
        return pytest_result


def _parse_pytest_json(rep_path: str, raw_output: str) -> CoverageRunResult:
    try:
        # 优先解析 pytest-json-report 产物，能拿到更准确的用例状态。
        with open(rep_path, encoding="utf-8") as f:
            report = json.load(f)
        summary = report.get("summary", {})
        total   = summary.get("total", 0)
        passed  = summary.get("passed", 0)
        failed  = summary.get("failed", 0)
        errors  = summary.get("error", 0)
        pass_rate = passed / total if total > 0 else 0.0

        details = []
        for test in report.get("tests", []):
            outcome = test.get("outcome", "error")
            node_id = test.get("nodeid", "")
            name    = node_id.split("::")[-1] if "::" in node_id else node_id
            msg     = ""
            if outcome != "passed":
                call = test.get("call", {})
                msg  = call.get("longrepr", "") or call.get("crash", {}).get("message", "")
            dur = test.get("call", {}).get("duration", 0) * 1000
            details.append(TestDetail(
                name=name, status=outcome,
                message=str(msg)[:400], duration_ms=round(dur, 2)
            ))

        error_msg = ""
        if total == 0:
            if "SyntaxError" in raw_output:
                error_msg = "测试代码存在语法错误，无法执行。"
            elif "ImportError" in raw_output or "ModuleNotFoundError" in raw_output:
                error_msg = "测试代码存在导入错误，请检查模块名。"

        return CoverageRunResult(
            success=True, total=total, passed=passed,
            failed=failed, errors=errors,
            pass_rate=round(pass_rate, 4),
            branch_coverage=0.0, covered_branches=0, total_branches=0,
            missing_lines=[], details=details,
            raw_output=raw_output[:3000], error_msg=error_msg,
        )
    except Exception:
        return _parse_text_output(raw_output)


def _parse_text_output(output: str) -> CoverageRunResult:
    # JSON 报告不可用时，从 pytest 文本输出里兜底提取结果。
    passed = failed = errors = 0
    details = []
    for line in output.splitlines():
        line = line.strip()
        if " PASSED" in line:
            name = re.split(r"\s+PASSED", line)[0].split("::")[-1]
            details.append(TestDetail(name=name, status="passed", message="", duration_ms=0))
            passed += 1
        elif " FAILED" in line:
            name = re.split(r"\s+FAILED", line)[0].split("::")[-1]
            details.append(TestDetail(name=name, status="failed", message="", duration_ms=0))
            failed += 1
        elif " ERROR" in line and "::test_" in line:
            name = re.split(r"\s+ERROR", line)[0].split("::")[-1]
            details.append(TestDetail(name=name, status="error", message="", duration_ms=0))
            errors += 1
    total = passed + failed + errors
    error_msg = ""
    if total == 0 and ("SyntaxError" in output or "ImportError" in output):
        error_msg = "测试代码存在语法/导入错误，无法执行。"
    return CoverageRunResult(
        success=total > 0, total=total, passed=passed,
        failed=failed, errors=errors,
        pass_rate=round(passed / total, 4) if total else 0.0,
        branch_coverage=0.0, covered_branches=0, total_branches=0,
        missing_lines=[], details=details,
        raw_output=output[:3000], error_msg=error_msg,
    )


def _empty_coverage(error_msg: str = "") -> dict:
    return {
        "branch_coverage": 0.0,
        "covered_branches": 0,
        "total_branches": 0,
        "missing_lines": [],
        "line_coverage": 0.0,
        "covered_lines": 0,
        "total_lines": 0,
        "path_coverage": 0.0,
        "covered_paths": 0,
        "total_paths": 0,
        "code_coverage": 0.0,
        "coverage_error": error_msg,
    }


def _parse_coverage_json(cov_path: str, coverage_output: str = "") -> dict:
    """解析 coverage JSON，返回多维覆盖率数据。"""
    try:
        with open(cov_path, encoding="utf-8") as f:
            data = json.load(f)
        files = data.get("files", {})
        # 只看 target.py
        for fname, fdata in files.items():
            if "target" in fname:
                # coverage.py 的 summary 同时提供行覆盖和分支覆盖基础数据。
                summary = fdata.get("summary", {})
                total_lines = summary.get("num_statements", 0) or 0
                covered_lines = summary.get("covered_lines", 0) or 0
                line_cov = (covered_lines / total_lines) if total_lines > 0 else 1.0

                total_br = summary.get("num_branches", 0) or 0
                covered_br = summary.get("covered_branches", 0) or 0
                branch_cov = (covered_br / total_br) if total_br > 0 else 1.0

                executed_paths = fdata.get("executed_branches", []) or []
                missing_paths = fdata.get("missing_branches", []) or []
                covered_paths = len(executed_paths)
                total_paths = covered_paths + len(missing_paths)
                if total_paths == 0 and total_br > 0:
                    covered_paths = covered_br
                    total_paths = total_br
                path_cov = (covered_paths / total_paths) if total_paths > 0 else 1.0

                percent_covered = summary.get("percent_covered")
                if percent_covered is None:
                    code_cov = line_cov
                else:
                    code_cov = float(percent_covered) / 100

                return {
                    "branch_coverage": round(branch_cov, 4),
                    "covered_branches": covered_br,
                    "total_branches": total_br,
                    "missing_lines": fdata.get("missing_lines", []) or [],
                    "line_coverage": round(line_cov, 4),
                    "covered_lines": covered_lines,
                    "total_lines": total_lines,
                    "path_coverage": round(path_cov, 4),
                    "covered_paths": covered_paths,
                    "total_paths": total_paths,
                    "code_coverage": round(code_cov, 4),
                    "coverage_error": "",
                }
        return _empty_coverage("覆盖率数据未包含被测模块 target.py，可能测试没有执行到被测代码。")
    except Exception:
        msg = (coverage_output or "").strip().splitlines()
        detail = msg[-1] if msg else "coverage.json 未生成"
        if "No data to report" in detail:
            detail = "没有可报告的覆盖率数据，测试可能在收集阶段已经失败。"
        return _empty_coverage(f"覆盖率数据不可用：{detail}")
