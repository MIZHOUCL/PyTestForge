# PyTestForge

PyTestForge 是一个基于 Flask + Vue 的 LLM 测试用例生成与评估工具。它可以分析 Python 代码结构，调用 OpenAI 兼容接口生成 `pytest` 测试，在隔离临时目录中执行测试，并展示通过率、行覆盖率、分支覆盖率、路径覆盖率和综合覆盖率。

## 功能特性

- 支持 zero-shot、few-shot、AST 增强三种测试生成策略。
- 自动运行 `pytest` 和 `coverage.py`，展示测试结果与覆盖率。
- 覆盖率不达标或测试失败时，可进行多轮迭代优化。
- 支持多模型对比，包括通过率、耗时、Token 用量和历史记录。
- 可辅助判断失败原因更像是源代码 bug，还是生成测试断言有误。
- 内置 Python 示例库，也支持在前端配置自定义 OpenAI 兼容模型。

## 项目结构

```text
backend/
  app.py              Flask API 服务
  llm_client.py       OpenAI 兼容模型客户端
  coverage_runner.py  pytest + coverage 执行器
  iterative_runner.py 多轮迭代生成流程
  database.py         SQLite 历史记录
  examples/           示例 Python 代码
frontend/
  index.html          Vue 3 单页前端
uml_usecases/         架构与设计图
```

## 环境要求

- Python 3.10+
- 一个 OpenAI 兼容 API Key。可以配置后端预置模型，也可以直接在前端自定义模型面板填写。

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

cp .env.example .env
# 如果使用内置模型预设，请编辑 .env 并填写 APIY_API_KEY。

python backend/app.py
```

另开一个终端启动前端静态服务：

```bash
cd frontend
python3 -m http.server 8080
```

浏览器打开 <http://127.0.0.1:8080>，并保持后端运行在 <http://127.0.0.1:5050>。

## 配置说明

后端会从环境变量或项目根目录的 `.env` 读取配置。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APIY_API_KEY` | 空 | 内置模型预设使用的 API Key。 |
| `APIY_BASE_URL` | `https://api.apiyi.com/v1` | 内置模型预设的 OpenAI 兼容接口地址。 |
| `HOST` | `0.0.0.0` | Flask 监听地址。 |
| `PORT` | `5050` | Flask 端口。 |
| `DEBUG` | `true` | 是否开启 Flask 调试模式。 |
| `TEST_TIMEOUT` | `15` | 单次测试执行超时时间，单位秒。 |
| `DATABASE_PATH` | 项目根目录 `history.db` | 可选，覆盖 SQLite 历史库路径。 |

如果没有设置 `APIY_API_KEY`，内置模型预设会返回配置错误。你仍然可以在前端自定义模型面板填写 Provider、Base URL、模型 ID 和 Key。

## 安全提醒

- 不要提交 `.env`、SQLite 历史库、API Key、生成报告或个人文档。
- 前端自定义模型配置会保存在浏览器 `localStorage`，请避免在共享电脑上保存真实 Key。
- 如果某个 Key 曾经被写入代码、截图或分享过，即使现在已删除，也建议立刻轮换。
- 发布到公开仓库前，建议再做一次 secret scan，并检查 `.gitignore` 是否生效。

## 开发检查

```bash
python -m compileall backend
python - <<'PY'
import sys
sys.path.insert(0, "backend")
import app
print("backend import ok")
PY
```

## License

当前还没有包含许可证文件。正式开源前请先选择并添加许可证；这类工具常用 MIT 或 Apache-2.0。
