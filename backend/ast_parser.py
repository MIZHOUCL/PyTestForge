import ast, textwrap
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class FunctionInfo:
    name: str; args: List[dict]; return_annotation: str
    docstring: Optional[str]; has_conditions: bool; has_loops: bool
    has_exceptions: bool; branches: List[str]; complexity: int

@dataclass
class CodeAnalysisResult:
    functions: List[FunctionInfo] = field(default_factory=list)
    classes: List[str] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    has_syntax_error: bool = False
    syntax_error_msg: str = ""
    summary: str = ""

class ASTParser:
    def parse(self, code: str) -> CodeAnalysisResult:
        result = CodeAnalysisResult()
        try:
            # dedent 让用户从网页粘贴的缩进代码也能正常解析。
            tree = ast.parse(textwrap.dedent(code))
        except SyntaxError as e:
            result.has_syntax_error = True
            result.syntax_error_msg = f"语法错误：第{e.lineno}行 - {e.msg}"
            return result
        # 遍历 AST，收集后续 Prompt 生成会用到的函数、类、导入信息。
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                result.imports.append(ast.unparse(node))
            if isinstance(node, ast.ClassDef):
                result.classes.append(node.name)
            if isinstance(node, ast.FunctionDef):
                result.functions.append(self._parse_fn(node))
        result.summary = self._summary(result)
        return result

    def _parse_fn(self, node):
        args = []
        for a in node.args.args:
            # 参数和返回值注解用于辅助 LLM 理解输入输出范围。
            ann = ""
            if a.annotation:
                try: ann = ast.unparse(a.annotation)
                except: ann = "unknown"
            args.append({"name": a.arg, "annotation": ann})
        ret = ""
        if node.returns:
            try: ret = ast.unparse(node.returns)
            except: ret = "unknown"
        doc = ast.get_docstring(node)
        has_cond = has_loop = has_exc = False
        branches = []; cx = 1
        for ch in ast.walk(node):
            # 用简单规则估算圈复杂度，并记录主要分支提示。
            if isinstance(ch, ast.If):
                has_cond = True; cx += 1
                try: branches.append(f"if {ast.unparse(ch.test)}")
                except: branches.append("if <cond>")
            elif isinstance(ch, (ast.For, ast.While)):
                has_loop = True; cx += 1
            elif isinstance(ch, (ast.ExceptHandler, ast.Raise)):
                has_exc = True; cx += 1
        return FunctionInfo(name=node.name, args=args, return_annotation=ret,
            docstring=doc, has_conditions=has_cond, has_loops=has_loop,
            has_exceptions=has_exc, branches=branches[:5], complexity=cx)

    def _summary(self, r: CodeAnalysisResult) -> str:
        # 汇总成中文结构说明，直接拼进结构化 Prompt。
        lines = ["【代码结构分析】"]
        if r.imports: lines.append(f"依赖：{', '.join(r.imports[:5])}")
        if r.classes: lines.append(f"类：{', '.join(r.classes)}")
        for fn in r.functions:
            lines.append(f"\n函数名：{fn.name}")
            if fn.args:
                a = [f"{a['name']}:{a['annotation']}" if a['annotation'] else a['name'] for a in fn.args]
                lines.append(f"  参数：{', '.join(a)}")
            if fn.return_annotation: lines.append(f"  返回类型：{fn.return_annotation}")
            if fn.docstring: lines.append(f"  说明：{fn.docstring.split(chr(10))[0][:80]}")
            feats = []
            if fn.has_conditions: feats.append("含条件分支")
            if fn.has_loops: feats.append("含循环")
            if fn.has_exceptions: feats.append("含异常处理")
            if feats: lines.append(f"  特征：{', '.join(feats)}")
            if fn.branches: lines.append(f"  分支：{'; '.join(fn.branches[:3])}")
            lines.append(f"  圈复杂度：{fn.complexity}")
            tips = ["正常输入"]
            if fn.has_conditions: tips.append("每个分支边界条件")
            if fn.has_loops: tips.append("空集合/单元素/多元素")
            if fn.has_exceptions: tips.append("触发异常的非法输入")
            lines.append(f"  建议覆盖：{'; '.join(tips)}")
        return "\n".join(lines)

parser = ASTParser()
def analyze_code(code: str) -> CodeAnalysisResult:
    return parser.parse(code)
