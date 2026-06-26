"""title: 嵌套字典安全访问
category: exception
difficulty: medium
tips: KeyError + TypeError + 默认值；考察多层访问中途异常
"""


def fetch_nested(data: dict, path: str, default=None):
    """按点分隔的路径访问嵌套字典：fetch_nested({'a':{'b':1}}, 'a.b') -> 1。
    路径不存在或中间不是字典时返回 default；非字典/非字符串入参抛 TypeError。
    """
    if not isinstance(data, dict):
        raise TypeError("data 必须是字典")
    if not isinstance(path, str):
        raise TypeError("path 必须是字符串")
    if not path:
        return default
    keys = path.split(".")
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        if key not in current:
            return default
        current = current[key]
    return current
