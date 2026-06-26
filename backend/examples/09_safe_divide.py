"""title: 安全除法
category: exception
difficulty: easy
tips: 最基础异常示例；考察 ZeroDivisionError + TypeError + 正常路径
"""


def safe_divide(a: float, b: float) -> float:
    """安全除法：除数为 0 抛 ZeroDivisionError，非数字抛 TypeError。"""
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise TypeError("被除数和除数都必须是数字")
    if isinstance(a, bool) or isinstance(b, bool):
        raise TypeError("布尔值不被允许")
    if b == 0:
        raise ZeroDivisionError("除数不能为零")
    return a / b
