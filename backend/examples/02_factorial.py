"""title: 阶乘（递归 + 边界）
category: basic
difficulty: easy
tips: 含负数异常分支；建议 structured 策略；阈值 90/90/80/90
"""


def factorial(n: int) -> int:
    """计算非负整数 n 的阶乘。负数抛 ValueError。"""
    if not isinstance(n, int):
        raise TypeError("n 必须是整数")
    if n < 0:
        raise ValueError("n 不能是负数")
    if n <= 1:
        return 1
    return n * factorial(n - 1)
