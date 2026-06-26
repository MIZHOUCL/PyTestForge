"""Runtime configuration for PyTestForge.

Sensitive values are loaded from environment variables or a local .env file.
Do not hard-code API keys in this file before publishing the repository.
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - python-dotenv is optional at import time.
    load_dotenv = None

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

if load_dotenv:
    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv(BASE_DIR / ".env", override=False)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# ===================== API 统一配置 =====================
APIY_API_KEY = os.getenv("APIY_API_KEY", "").strip()
APIY_BASE_URL = os.getenv("APIY_BASE_URL", "https://api.apiyi.com/v1").strip().rstrip("/")

# ===================== 服务配置 =====================
HOST = os.getenv("HOST", "0.0.0.0")
PORT = _env_int("PORT", 5050)
DEBUG = _env_bool("DEBUG", True)

# ===================== 数据库配置 =====================
DATABASE_PATH = os.getenv("DATABASE_PATH", str(PROJECT_ROOT / "history.db"))

# ===================== 测试执行配置 =====================
# 单次测试执行超时时间（秒）
TEST_TIMEOUT = _env_int("TEST_TIMEOUT", 15)

# ===================== 模型映射 =====================
MODEL_MAP = {
    "deepseek": {
        "name": "deepseek-chat",
        "api_key": APIY_API_KEY,
        "base_url": APIY_BASE_URL,
        "model": "deepseek-chat",
    },
    "qwen": {
        "name": "qwen-turbo",
        "api_key": APIY_API_KEY,
        "base_url": APIY_BASE_URL,
        "model": "qwen-turbo",
    },
    "gpt4o": {
        "name": "gpt-4o-mini",
        "api_key": APIY_API_KEY,
        "base_url": APIY_BASE_URL,
        "model": "gpt-4o-mini",
    },
    "claude": {
        "name": "claude-haiku-4-5-20251001",
        "api_key": APIY_API_KEY,
        "base_url": APIY_BASE_URL,
        "model": "claude-haiku-4-5-20251001",
    },
    "gemini": {
        "name": "gemini-2.5-flash",
        "api_key": APIY_API_KEY,
        "base_url": APIY_BASE_URL,
        "model": "gemini-2.5-flash",
    },
}
