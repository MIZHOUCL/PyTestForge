import ast
import re, time
from openai import OpenAI
import openai
from config import MODEL_MAP

DEFAULT_MAX_TOKENS = 8000


def _missing_config_fields(cfg):
    return [k for k in ("api_key", "base_url", "model") if not str(cfg.get(k, "")).strip()]


def _error_result(error_type, error_message, suggestion, retryable, latency_ms=0):
    # 所有 LLM 错误都整理成统一结构，前后端都能复用。
    return {
        "success": False,
        "code": "",
        "raw": "",
        "tokens_used": 0,
        "latency_ms": latency_ms,
        "error": error_message,
        "error_type": error_type,
        "error_message": error_message,
        "suggestion": suggestion,
        "retryable": retryable,
    }


def _truncate_to_last_parseable(code: str) -> str:
    """从尾部逐行去掉，直到剩余前缀能通过 ast.parse；若整段不能解析则返回空串。"""
    try:
        ast.parse(code)
        return code
    except SyntaxError:
        pass
    lines = code.splitlines()
    for end in range(len(lines) - 1, 0, -1):
        candidate = "\n".join(lines[:end])
        try:
            ast.parse(candidate)
            return candidate
        except SyntaxError:
            continue
    return ""


def _has_test_function(code: str) -> bool:
    """检查代码里是否至少有一个 def test_* 或 async def test_*。"""
    if not code.strip():
        return False
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            return True
    return False


class LLMClient:
    def __init__(self):
        # 按 base_url + api_key 缓存客户端，避免每次请求都重新创建连接对象。
        self._clients = {}

    def _resolve_config(self, model_id, model_config=None):
        # 自定义模型和预置模型最终都规范成 OpenAI 兼容配置。
        if model_config:
            cfg = {
                "name": model_config.get("name") or model_config.get("model") or model_id,
                "api_key": model_config.get("api_key", ""),
                "base_url": model_config.get("base_url", ""),
                "model": model_config.get("model", ""),
                "temperature": model_config.get("temperature", 0.2),
                "max_tokens": model_config.get("max_tokens", DEFAULT_MAX_TOKENS),
            }
            missing = _missing_config_fields(cfg)
            if missing:
                return None, f"自定义模型配置缺少：{', '.join(missing)}"
            return cfg, ""
        if model_id not in MODEL_MAP:
            return None, f"未知模型:{model_id}"
        cfg = dict(MODEL_MAP[model_id])
        missing = _missing_config_fields(cfg)
        if missing:
            return None, (
                f"预置模型 {cfg.get('name', model_id)} 配置缺少：{', '.join(missing)}。"
                "请设置 APIY_API_KEY 环境变量，或在前端添加自定义模型配置。"
            )
        return cfg, ""

    def _get_client(self, cfg):
        cache_key = (cfg["base_url"].rstrip("/"), cfg["api_key"])
        if cache_key not in self._clients:
            self._clients[cache_key] = OpenAI(
                api_key=cfg["api_key"],
                base_url=cfg["base_url"].rstrip("/")
            )
        return self._clients[cache_key]

    def generate(self, model_id, system_prompt, user_prompt, model_config=None):
        cfg, error = self._resolve_config(model_id, model_config)
        if error:
            return _error_result("config_error", error, "请检查模型配置是否完整", False)
        start = time.time()
        try:
            # 调用 OpenAI 兼容接口生成 pytest 代码。
            max_tokens = int(cfg.get("max_tokens", DEFAULT_MAX_TOKENS) or DEFAULT_MAX_TOKENS)
            temperature = float(cfg.get("temperature", 0.2) or 0.2)
            r = self._get_client(cfg).chat.completions.create(
                model=cfg["model"],
                messages=[{"role": "system", "content": system_prompt},
                          {"role": "user", "content": user_prompt}],
                temperature=temperature, max_tokens=max_tokens)
            ms = int((time.time() - start) * 1000)
            choice = r.choices[0]
            raw = choice.message.content or ""
            finish_reason = (getattr(choice, "finish_reason", "") or "").lower()
            if not raw.strip():
                return _error_result(
                    "empty_response",
                    "模型返回了空内容",
                    "请尝试更换 Prompt 策略或切换其他模型",
                    True, ms
                )
            code = self._extract(raw)
            truncated = finish_reason == "length"
            warning = ""
            if truncated:
                # 输出被截断时，尽量保留前面仍可解析且包含测试函数的代码。
                recovered = _truncate_to_last_parseable(code)
                if recovered and _has_test_function(recovered):
                    code = recovered
                    warning = (
                        f"模型输出在 max_tokens={max_tokens} 处被截断，"
                        "已自动保留前面可解析、含测试函数的部分。"
                        "建议在模型配置中将 max_tokens 调到更大（例如 6144 或 8192）后重试。"
                    )
                else:
                    return _error_result(
                        "truncated",
                        f"模型输出被截断（max_tokens={max_tokens} 不足），无法恢复出可执行的测试代码",
                        "请在模型配置中将 max_tokens 增大到 4096+，或缩短被测代码后重试",
                        True, ms
                    )
            return {
                "success": True, "code": code, "raw": raw,
                "tokens_used": r.usage.total_tokens if r.usage else 0,
                "latency_ms": ms, "error": "",
                "error_type": "truncated_recovered" if truncated else "",
                "error_message": warning,
                "suggestion": "" if not truncated else "增大 max_tokens 配置（建议 6144+）",
                "retryable": False,
                "truncated": truncated,
            }
        except openai.AuthenticationError as e:
            return _error_result(
                "auth_error",
                f"API 认证失败：{self._short_msg(e)}",
                "请检查 API Key 是否正确、是否已过期或余额不足",
                False, int((time.time() - start) * 1000)
            )
        except openai.RateLimitError as e:
            return _error_result(
                "rate_limit",
                f"请求频率超限：{self._short_msg(e)}",
                "请等待 30 秒后重试，或升级 API 套餐",
                True, int((time.time() - start) * 1000)
            )
        except openai.NotFoundError as e:
            return _error_result(
                "model_not_found",
                f"模型不存在：{self._short_msg(e)}",
                "请检查模型 ID 是否正确，或该模型是否已下线",
                False, int((time.time() - start) * 1000)
            )
        except openai.APITimeoutError as e:
            return _error_result(
                "timeout",
                f"请求超时：{self._short_msg(e)}",
                "模型响应过慢，请稍后重试或切换更快的模型",
                True, int((time.time() - start) * 1000)
            )
        except openai.APIConnectionError as e:
            return _error_result(
                "network_error",
                f"网络连接失败：{self._short_msg(e)}",
                "请检查网络连接和 Base URL 是否正确",
                True, int((time.time() - start) * 1000)
            )
        except openai.InternalServerError as e:
            return _error_result(
                "server_error",
                f"服务端错误：{self._short_msg(e)}",
                "API 服务端异常，请稍后重试",
                True, int((time.time() - start) * 1000)
            )
        except openai.BadRequestError as e:
            return _error_result(
                "bad_request",
                f"请求参数错误：{self._short_msg(e)}",
                "请检查输入代码是否过长或包含不支持的内容",
                False, int((time.time() - start) * 1000)
            )
        except Exception as e:
            return _error_result(
                "unknown",
                f"未知错误：{str(e)[:200]}",
                "请检查配置后重试，如持续出现请联系管理员",
                False, int((time.time() - start) * 1000)
            )

    def _short_msg(self, e):
        msg = str(e)
        return msg[:150] if len(msg) > 150 else msg

    def _extract(self, text):
        # 优先提取 markdown 代码块；没有代码块时把整段文本当作代码。
        m = re.findall(r"```(?:python)?\n?([\s\S]*?)```", text, re.I)
        if m:
            return max(m, key=len).strip()
        # 无闭合 ``` 时（典型于被截断的输出）：剥掉开头的 ```python / ```
        stripped = text.strip()
        unclosed = re.match(r"^```(?:python)?\s*\n([\s\S]*)$", stripped, re.I)
        if unclosed:
            return unclosed.group(1).rstrip("`").strip()
        return stripped


client = LLMClient()


def generate_test_cases(model_id, sys_p, user_p, model_config=None):
    return client.generate(model_id, sys_p, user_p, model_config)


def chat_raw(model_id, sys_p, user_p, model_config=None, max_tokens=2048, temperature=0.1):
    """通用 LLM 文本回答接口（不剥码、不做截断回收），供 bug_detector 等模块使用。
    返回 {success, raw, tokens_used, latency_ms, error, error_type}。
    """
    cfg, err = client._resolve_config(model_id, model_config)
    if err:
        return {"success": False, "raw": "", "tokens_used": 0, "latency_ms": 0,
                "error": err, "error_type": "config_error"}
    try:
        import time as _t
        start = _t.time()
        r = client._get_client(cfg).chat.completions.create(
            model=cfg["model"],
            messages=[{"role": "system", "content": sys_p},
                      {"role": "user", "content": user_p}],
            temperature=temperature, max_tokens=max_tokens)
        ms = int((_t.time() - start) * 1000)
        raw = (r.choices[0].message.content or "").strip()
        return {"success": True, "raw": raw,
                "tokens_used": r.usage.total_tokens if r.usage else 0,
                "latency_ms": ms, "error": "", "error_type": ""}
    except Exception as e:
        return {"success": False, "raw": "", "tokens_used": 0, "latency_ms": 0,
                "error": str(e)[:200], "error_type": "exception"}
