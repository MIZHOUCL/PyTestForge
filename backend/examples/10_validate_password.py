"""title: 密码强度校验
category: exception
difficulty: medium
tips: 多重 ValueError 抛出；考察长度、大小写、数字、特殊字符 4 条规则
"""


def validate_password(password: str) -> bool:
    """校验密码强度。返回 True 表示通过；否则抛 ValueError 说明具体原因。
    规则：
      1. 长度 8-32 个字符
      2. 至少含一个大写字母
      3. 至少含一个小写字母
      4. 至少含一个数字
      5. 至少含一个特殊字符（!@#$%^&*）
    """
    if not isinstance(password, str):
        raise TypeError("password 必须是字符串")
    if len(password) < 8:
        raise ValueError("密码长度不能小于 8")
    if len(password) > 32:
        raise ValueError("密码长度不能大于 32")
    if not any(c.isupper() for c in password):
        raise ValueError("密码必须包含至少一个大写字母")
    if not any(c.islower() for c in password):
        raise ValueError("密码必须包含至少一个小写字母")
    if not any(c.isdigit() for c in password):
        raise ValueError("密码必须包含至少一个数字")
    if not any(c in "!@#$%^&*" for c in password):
        raise ValueError("密码必须包含至少一个特殊字符")
    return True
