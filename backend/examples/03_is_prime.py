"""title: 判断素数
category: basic
difficulty: easy
tips: 循环 + 早返回，分支多；建议覆盖 n<2 / 偶数 / 6k±1 三种路径
"""


def is_prime(n: int) -> bool:
    """判断 n 是否为素数（n >= 2）。"""
    if n < 2:
        return False
    if n < 4:
        return True
    if n % 2 == 0:
        return False
    i = 3
    while i * i <= n:
        if n % i == 0:
            return False
        i += 2
    return True
