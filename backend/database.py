"""历史记录存储模块（含迭代记录表）"""

import json
import sqlite3
from datetime import datetime
from contextlib import contextmanager
from config import DATABASE_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT,
    source_code TEXT,
    model_id    TEXT,
    model_name  TEXT,
    strategy    TEXT,
    strategy_desc TEXT,
    test_code   TEXT,
    total       INTEGER DEFAULT 0,
    passed      INTEGER DEFAULT 0,
    failed      INTEGER DEFAULT 0,
    errors      INTEGER DEFAULT 0,
    pass_rate   REAL    DEFAULT 0.0,
    latency_ms  INTEGER DEFAULT 0,
    tokens_used INTEGER DEFAULT 0,
    run_output  TEXT    DEFAULT '',
    details     TEXT    DEFAULT '[]',
    code_review TEXT    DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS iteration_history (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at            TEXT,
    source_code           TEXT,
    model_id              TEXT,
    model_name            TEXT,
    strategy              TEXT,
    strategy_desc         TEXT,
    final_test_code       TEXT,
    iteration_count       INTEGER DEFAULT 0,
    final_status          TEXT,
    final_pass_rate       REAL    DEFAULT 0.0,
    final_line_coverage   REAL    DEFAULT 0.0,
    final_branch_coverage REAL    DEFAULT 0.0,
    final_path_coverage   REAL    DEFAULT 0.0,
    final_code_coverage   REAL    DEFAULT 0.0,
    coverage_threshold    REAL    DEFAULT 0.7,
    coverage_thresholds   TEXT    DEFAULT '{}',
    rounds_detail         TEXT    DEFAULT '[]',
    total_tokens          INTEGER DEFAULT 0,
    total_latency_ms      INTEGER DEFAULT 0,
    code_review           TEXT    DEFAULT '[]'
);
"""

HISTORY_COLUMNS = {
    "code_review": "TEXT DEFAULT '[]'",
}

ITERATION_HISTORY_COLUMNS = {
    "final_line_coverage": "REAL DEFAULT 0.0",
    "final_path_coverage": "REAL DEFAULT 0.0",
    "final_code_coverage": "REAL DEFAULT 0.0",
    "coverage_thresholds": "TEXT DEFAULT '{}'",
    "total_latency_ms": "INTEGER DEFAULT 0",
    "code_review": "TEXT DEFAULT '[]'",
}


@contextmanager
def get_conn():
    # 用上下文管理器统一提交/回滚，减少各处重复处理连接生命周期。
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _ensure_columns(conn, "history", HISTORY_COLUMNS)
        _ensure_columns(conn, "iteration_history", ITERATION_HISTORY_COLUMNS)


def _ensure_columns(conn, table: str, columns: dict):
    # 兼容旧数据库文件：缺少的新字段会在启动时自动补齐。
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _review_count(value) -> int:
    try:
        return len(json.loads(value or "[]"))
    except Exception:
        return 0


def _attach_iteration_coverage_counts(record: dict, rounds_detail: str):
    try:
        rounds = json.loads(rounds_detail or "[]")
    except Exception:
        rounds = []
    if not rounds:
        return
    final_round = rounds[-1]
    for key in (
        "covered_lines", "total_lines",
        "covered_branches", "total_branches",
        "covered_paths", "total_paths",
    ):
        if key in final_round:
            record[key] = final_round.get(key, 0)


# ──────────── 普通历史 ────────────

def save_record(record: dict) -> int:
    # 普通生成模式的一次执行结果写入 history 表。
    sql = """
    INSERT INTO history
        (created_at,source_code,model_id,model_name,strategy,strategy_desc,
         test_code,total,passed,failed,errors,pass_rate,
         latency_ms,tokens_used,run_output,details,code_review)
    VALUES
        (:created_at,:source_code,:model_id,:model_name,:strategy,:strategy_desc,
         :test_code,:total,:passed,:failed,:errors,:pass_rate,
         :latency_ms,:tokens_used,:run_output,:details,:code_review)
    """
    record.setdefault("created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    if isinstance(record.get("details"), list):
        record["details"] = json.dumps(record["details"], ensure_ascii=False)
    if isinstance(record.get("code_review"), list):
        record["code_review"] = json.dumps(record["code_review"], ensure_ascii=False)
    record.setdefault("code_review", "[]")
    with get_conn() as conn:
        return conn.execute(sql, record).lastrowid


def list_records(page=1, page_size=20, model_id="") -> dict:
    # 列表页只查询摘要字段，详情页再按 id 拉完整代码和结果。
    offset = (page - 1) * page_size
    where  = "WHERE model_id=:model_id" if model_id else ""
    params = {"limit": page_size, "offset": offset}
    if model_id:
        params["model_id"] = model_id
    with get_conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM history {where}", params).fetchone()[0]
        rows  = conn.execute(
            f"SELECT id,created_at,model_name,strategy,strategy_desc,"
            f"total,passed,failed,pass_rate,latency_ms,tokens_used,code_review "
            f"FROM history {where} ORDER BY id DESC LIMIT :limit OFFSET :offset", params
        ).fetchall()
    records = [dict(r) for r in rows]
    for r in records:
        r["review_count"] = _review_count(r.pop("code_review", "[]"))
    return {"total": total, "page": page, "page_size": page_size,
            "records": records}


def get_record(record_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM history WHERE id=?", (record_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["details"] = json.loads(d.get("details", "[]"))
    except Exception:
        d["details"] = []
    try:
        d["code_review"] = json.loads(d.get("code_review", "[]"))
    except Exception:
        d["code_review"] = []
    return d


def delete_record(record_id: int) -> bool:
    with get_conn() as conn:
        return conn.execute("DELETE FROM history WHERE id=?", (record_id,)).rowcount > 0


# ──────────── 迭代历史 ────────────

def save_iteration_record(record: dict) -> int:
    # 迭代模式保存最终结果和每轮明细，便于回放整个优化过程。
    sql = """
    INSERT INTO iteration_history
        (created_at,source_code,model_id,model_name,strategy,strategy_desc,
         final_test_code,iteration_count,final_status,final_pass_rate,
         final_line_coverage,final_branch_coverage,final_path_coverage,
         final_code_coverage,coverage_threshold,coverage_thresholds,
         rounds_detail,total_tokens,total_latency_ms,code_review)
    VALUES
        (:created_at,:source_code,:model_id,:model_name,:strategy,:strategy_desc,
         :final_test_code,:iteration_count,:final_status,:final_pass_rate,
         :final_line_coverage,:final_branch_coverage,:final_path_coverage,
         :final_code_coverage,:coverage_threshold,:coverage_thresholds,
         :rounds_detail,:total_tokens,:total_latency_ms,:code_review)
    """
    record.setdefault("created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    record.setdefault("final_line_coverage", 0.0)
    record.setdefault("final_path_coverage", 0.0)
    record.setdefault("final_code_coverage", record.get("final_branch_coverage", 0.0))
    if isinstance(record.get("coverage_thresholds"), dict):
        record["coverage_thresholds"] = json.dumps(
            record["coverage_thresholds"], ensure_ascii=False
        )
    record.setdefault("coverage_thresholds", "{}")
    record.setdefault("total_latency_ms", 0)
    if isinstance(record.get("code_review"), list):
        record["code_review"] = json.dumps(record["code_review"], ensure_ascii=False)
    record.setdefault("code_review", "[]")
    with get_conn() as conn:
        return conn.execute(sql, record).lastrowid


def list_iteration_records(page=1, page_size=20, model_id="") -> dict:
    offset = (page - 1) * page_size
    where  = "WHERE model_id=:model_id" if model_id else ""
    params = {"limit": page_size, "offset": offset}
    if model_id:
        params["model_id"] = model_id
    with get_conn() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM iteration_history {where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT id,created_at,model_name,strategy,iteration_count,"
            f"final_status,final_pass_rate,"
            f"CASE WHEN coverage_thresholds='{{}}' AND final_line_coverage=0 "
            f"THEN final_branch_coverage ELSE final_line_coverage END AS final_line_coverage,"
            f"final_branch_coverage,"
            f"CASE WHEN coverage_thresholds='{{}}' AND final_path_coverage=0 "
            f"THEN final_branch_coverage ELSE final_path_coverage END AS final_path_coverage,"
            f"CASE WHEN coverage_thresholds='{{}}' AND final_code_coverage=0 "
            f"THEN final_branch_coverage ELSE final_code_coverage END AS final_code_coverage,"
            f"coverage_threshold,coverage_thresholds,total_tokens,total_latency_ms,"
            f"code_review,rounds_detail "
            f"FROM iteration_history {where} ORDER BY id DESC "
            f"LIMIT :limit OFFSET :offset", params
        ).fetchall()
    records = [dict(r) for r in rows]
    for r in records:
        r["review_count"] = _review_count(r.pop("code_review", "[]"))
        _attach_iteration_coverage_counts(r, r.pop("rounds_detail", "[]"))
    return {"total": total, "page": page, "page_size": page_size,
            "records": records}


def get_iteration_record(record_id: int):
    # 详情读取时把 JSON 字段还原成前端可直接渲染的对象。
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM iteration_history WHERE id=?", (record_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["rounds_detail"] = json.loads(d.get("rounds_detail", "[]"))
    except Exception:
        d["rounds_detail"] = []
    try:
        d["coverage_thresholds"] = json.loads(d.get("coverage_thresholds", "{}"))
    except Exception:
        d["coverage_thresholds"] = {}
    try:
        d["code_review"] = json.loads(d.get("code_review", "[]"))
    except Exception:
        d["code_review"] = []
    if not d["coverage_thresholds"]:
        for key in ("final_line_coverage", "final_path_coverage", "final_code_coverage"):
            if not d.get(key):
                d[key] = d.get("final_branch_coverage", 0.0)
    return d


def delete_iteration_record(record_id: int) -> bool:
    with get_conn() as conn:
        return conn.execute(
            "DELETE FROM iteration_history WHERE id=?", (record_id,)).rowcount > 0


# ──────────── 统计对比 ────────────

def get_comparison_stats() -> list:
    """普通生成模式统计"""
    sql = """
    SELECT model_id, model_name, strategy,
           COUNT(*) AS run_count,
           ROUND(AVG(pass_rate)*100, 1) AS avg_pass_rate,
           ROUND(AVG(latency_ms), 0)    AS avg_latency_ms,
           ROUND(AVG(tokens_used), 0)   AS avg_tokens_used,
           SUM(passed) AS total_passed,
           SUM(total)  AS total_cases
    FROM history GROUP BY model_id, strategy ORDER BY model_id, strategy
    """
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql).fetchall()]


def get_iteration_comparison_stats() -> list:
    """迭代模式统计（含成功率、平均迭代轮次、平均覆盖率）"""
    sql = """
    SELECT model_id, model_name, strategy,
           COUNT(*) AS run_count,
           SUM(CASE WHEN final_status='success' THEN 1 ELSE 0 END) AS success_count,
           ROUND(100.0*SUM(CASE WHEN final_status='success' THEN 1 ELSE 0 END)/COUNT(*),1)
               AS success_rate,
           ROUND(AVG(iteration_count), 2)          AS avg_iterations,
           ROUND(AVG(CASE WHEN coverage_thresholds='{}' AND final_line_coverage=0
                THEN final_branch_coverage ELSE final_line_coverage END)*100, 1)
                AS avg_line_coverage,
           ROUND(AVG(final_branch_coverage)*100, 1) AS avg_branch_coverage,
           ROUND(AVG(CASE WHEN coverage_thresholds='{}' AND final_path_coverage=0
                THEN final_branch_coverage ELSE final_path_coverage END)*100, 1)
                AS avg_path_coverage,
           ROUND(AVG(CASE WHEN coverage_thresholds='{}' AND final_code_coverage=0
                THEN final_branch_coverage ELSE final_code_coverage END)*100, 1)
                AS avg_code_coverage,
           ROUND(AVG(final_pass_rate)*100, 1)       AS avg_pass_rate,
           ROUND(AVG(total_latency_ms), 0)          AS avg_latency_ms,
           ROUND(AVG(total_tokens), 0)              AS avg_tokens_used
    FROM iteration_history
    GROUP BY model_id, strategy ORDER BY model_id, strategy
    """
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql).fetchall()]
