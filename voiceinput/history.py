"""识别历史。SQLite 存在程序目录旁边(绿色软件,不写 AppData)。

存历史的理由很具体:识别错了、或者粘到了错的窗口,总得有地方找回原文,
不然一句话就白说了。不是为了做统计。
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .config import app_dir

DB_NAME = "history.db"


def default_path() -> Path:
    """历史库的默认位置:程序目录旁边(绿色软件)。

    **必须是函数,不能是导入时算好的常量。** 写成常量的话
    `History()` 的默认路径在 import 那一刻就钉死了 ——
    测试没法把它重定向到临时目录,于是任何忘了传 path 的测试
    都会**往真实的历史库里写**。实测就这么污染过一次。
    """
    return app_dir() / DB_NAME


_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  REAL NOT NULL,
    text        TEXT NOT NULL,
    raw_text    TEXT NOT NULL,
    audio_s     REAL NOT NULL,
    infer_s     REAL NOT NULL,
    engine      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_entries_created ON entries(created_at DESC);
"""


@dataclass(frozen=True)
class Entry:
    id: int
    created_at: float
    text: str
    raw_text: str
    audio_s: float
    infer_s: float
    engine: str

    @property
    def rtf(self) -> float:
        return self.infer_s / self.audio_s if self.audio_s else 0.0


class History:
    """线程安全的历史存储。

    热键线程和 UI 线程都会碰它,所以用一把锁 + `check_same_thread=False`,
    而不是每个线程各开一个连接——写入频率很低(一次说话一条),
    锁竞争不是问题,少一层复杂度更划算。
    """

    def __init__(self, path: Path | None = None, max_entries: int = 2000) -> None:
        self._path = path or default_path()
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def set_max_entries(self, limit: int) -> None:
        """改保留上限。**调小了要立刻裁剪**,不能等下次写入才生效 ——
        用户把上限从 2000 改成 100,是希望多余的马上就没了。"""
        self._max_entries = max(1, int(limit))
        with self._lock:
            self._trim_locked()

    def add(self, text: str, raw_text: str, audio_s: float, infer_s: float,
            engine: str = "") -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO entries (created_at, text, raw_text, audio_s, infer_s, engine)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (time.time(), text, raw_text, audio_s, infer_s, engine),
            )
            self._conn.commit()
            new_id = int(cur.lastrowid or 0)
            self._trim_locked()
        return new_id

    def _trim_locked(self) -> None:
        """超出上限删最旧的。历史是用来找回错漏的,不是档案库。"""
        self._conn.execute(
            "DELETE FROM entries WHERE id NOT IN ("
            "  SELECT id FROM entries ORDER BY created_at DESC LIMIT ?"
            ")",
            (self._max_entries,),
        )
        self._conn.commit()

    def recent(self, limit: int = 200, search: str = "") -> list[Entry]:
        sql = "SELECT * FROM entries"
        params: list[object] = []
        if search:
            sql += " WHERE text LIKE ?"
            params.append(f"%{search}%")
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [_to_entry(r) for r in rows]

    def delete(self, entry_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
            self._conn.commit()

    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM entries")
            self._conn.commit()

    def count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM entries").fetchone()
        return int(row["n"])

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def _to_entry(row: sqlite3.Row) -> Entry:
    return Entry(
        id=row["id"],
        created_at=row["created_at"],
        text=row["text"],
        raw_text=row["raw_text"],
        audio_s=row["audio_s"],
        infer_s=row["infer_s"],
        engine=row["engine"],
    )
