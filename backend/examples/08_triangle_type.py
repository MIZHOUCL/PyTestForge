"""title: 三角形类型判定
category: branch
difficulty: medium
tips: 多重复合条件；考察等边/等腰/直角/普通/非三角形 5 类
"""


def triangle_type(a: float, b: float, c: float) -> str:
    """根据三条边长判断三角形类型：
    invalid    任一边 <= 0 或不满足三角形不等式
    equilateral 三边相等
    isosceles  两边相等
    right      直角（勾股）
    scalene    不等边
    """
    if a <= 0 or b <= 0 or c <= 0:
        return "invalid"
    if a + b <= c or a + c <= b or b + c <= a:
        return "invalid"
    if a == b == c:
        return "equilateral"
    sides = sorted([a, b, c])
    if abs(sides[0] ** 2 + sides[1] ** 2 - sides[2] ** 2) < 1e-9:
        return "right"
    if a == b or b == c or a == c:
        return "isosceles"
    return "scalene"
