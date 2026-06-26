"""title: 阶乘漏掉 n=0 边界
category: buggy
difficulty: easy
tips: factorial(0) 数学上是 1，但这里返回 0。诊断应指出边界处理错误
"""


def factorial(n: int) -> int:
    """计算非负整数 n 的阶乘。"""
    if n < 0:
        raise ValueError("n 不能为负数")
    if n == 0:
        return 0  # ← bug：应为 1
    result = 1
    for i in range(1, n + 1):
        result *= i
    return result
