from ast_parser import CodeAnalysisResult

FEW_SHOT = '''示例：
def divide(a,b):
    if b==0: raise ValueError("除数不能为零")
    return a/b

from target import *
import pytest
def test_divide_normal(): assert divide(10,2)==5.0
def test_divide_zero():
    with pytest.raises(ValueError): divide(10,0)
def test_divide_neg(): assert divide(-6,2)==-3.0
---
'''
SYS = ("你是专业Python测试工程师，精通pytest。生成的测试用例须：\n"
       "1.使用pytest风格(test_开头)\n2.覆盖正常/边界/异常路径\n"
       "3.每个函数只测一个场景\n4.包含必要import\n5.只输出可执行Python代码\n"
       "6.被测代码已保存为 target.py，导入被测函数必须使用 "
       "`from target import *` 或 `from target import 函数名`，"
       "禁止使用源码中的函数名/文件名作为模块名（例如禁止 `from add_numbers import ...`）")

IMPORT_RULE = (
    "导入规则：被测代码保存在 target.py 中，"
    "请使用 `from target import *` 或 `from target import 函数名` 导入，"
    "切勿凭函数名或文件名猜测模块名。"
)


class PromptBuilder:
    def build(self, strategy, code, analysis):
        # 根据用户选择的策略切换不同 Prompt 模板。
        if strategy=="zero_shot": return self._zs(code)
        if strategy=="few_shot":  return self._fs(code)
        return self._st(code, analysis)

    def _zs(self, code):
        return {"system":SYS,"user":f"为以下Python函数编写完整pytest测试用例：\n```python\n{code}\n```\n{IMPORT_RULE}\n覆盖正常、边界、异常情况，直接输出可执行测试代码。","strategy_desc":"Zero-shot"}

    def _fs(self, code):
        return {"system":SYS,"user":f"{FEW_SHOT}\n按上面风格为以下函数编写测试：\n```python\n{code}\n```\n{IMPORT_RULE}","strategy_desc":"Few-shot"}

    def _st(self, code, analysis):
        pts = []
        for fn in analysis.functions:
            # 结构化模式会把 AST 中识别到的分支、循环、异常转成测试点。
            p = [f"函数{fn.name}：正常输入验证返回值"]
            if fn.has_conditions: p.append(f"每个条件分支各一用例({fn.complexity-1}个分支)")
            if fn.has_loops: p.append("空/单/多元素三种循环边界")
            if fn.has_exceptions: p.append("触发异常的非法输入(pytest.raises)")
            pts.append("\n".join(p))
        hint = "\n".join(pts) or "覆盖所有可能路径"
        user = (f"待测代码：\n```python\n{code}\n```\n\n{analysis.summary}\n\n"
                f"必须覆盖的测试点：\n{hint}\n\n{IMPORT_RULE}\n\n请生成完整pytest测试代码。")
        return {"system":SYS,"user":user,"strategy_desc":"Structured(AST增强)"}

builder = PromptBuilder()
def build_prompt(strategy, code, analysis): return builder.build(strategy, code, analysis)
