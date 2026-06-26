"""title: ISO 日期解析
category: exception
difficulty: medium
tips: TypeError + ValueError + 边界月份；建议 few-shot + 高路径阈值
"""


def parse_iso_date(text: str) -> tuple:
    """解析 'YYYY-MM-DD' 格式日期，返回 (year, month, day)。
    非法格式抛 ValueError；非字符串抛 TypeError。
    """
    if not isinstance(text, str):
        raise TypeError("text 必须是字符串")
    parts = text.split("-")
    if len(parts) != 3:
        raise ValueError("日期格式应为 YYYY-MM-DD")
    try:
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError as e:
        raise ValueError("日期各字段必须是整数") from e
    if year < 1 or year > 9999:
        raise ValueError("年份超出 1-9999 范围")
    if month < 1 or month > 12:
        raise ValueError("月份必须在 1-12 之间")
    days_in_month = [31, 29 if _is_leap(year) else 28, 31, 30, 31, 30,
                     31, 31, 30, 31, 30, 31]
    if day < 1 or day > days_in_month[month - 1]:
        raise ValueError(f"{year}-{month:02d} 没有第 {day} 天")
    return year, month, day


def _is_leap(year: int) -> bool:
    return (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
