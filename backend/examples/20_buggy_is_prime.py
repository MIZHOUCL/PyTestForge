"""title: 素数判定漏掉 n=2
category: buggy
difficulty: medium
tips: 2 是最小的素数，但这里 if n <= 2 直接返回 False；诊断应能定位边界判断
"""


def is_prime(n: int) -> bool:
    """判断 n 是否为素数。"""
    if n <= 2:  # ← bug：应该 n < 2 返回 False，n == 2 返回 True
        return False
    if n % 2 == 0:
        return False
    i = 3
    while i * i <= n:
        if n % i == 0:
            return False
        i += 2
    return True
