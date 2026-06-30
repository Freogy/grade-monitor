"""
数据库操作模块
使用 SQLite 存储已抓取的成绩记录，防止重复通知。
"""

import sqlite3
import hashlib
from datetime import datetime
from contextlib import contextmanager
from config import DB_PATH


def _make_raw_id(course_name: str, semester: str, grade: str) -> str:
    """根据课程名+学期+成绩生成唯一标识"""
    raw = f"{course_name}|{semester}|{grade}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


class GradeDB:
    """成绩数据库操作类"""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_table()

    @contextmanager
    def _conn(self):
        """获取数据库连接（上下文管理器，自动提交和关闭）"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_table(self):
        """初始化数据库表"""
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS grades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    course_name TEXT NOT NULL,
                    grade TEXT NOT NULL,
                    credit TEXT,
                    semester TEXT,
                    course_type TEXT,
                    raw_id TEXT UNIQUE,
                    notified_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def exists(self, raw_id: str) -> bool:
        """检查某条成绩是否已存在"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM grades WHERE raw_id = ?", (raw_id,)
            ).fetchone()
            return row is not None

    def insert_grade(self, course_name: str, grade: str, credit: str = "",
                     semester: str = "", course_type: str = "") -> bool:
        """
        插入一条新成绩记录。
        返回 True 表示是新成绩，False 表示已存在。
        """
        raw_id = _make_raw_id(course_name, semester, grade)
        if self.exists(raw_id):
            return False

        with self._conn() as conn:
            conn.execute(
                """INSERT INTO grades
                   (course_name, grade, credit, semester, course_type, raw_id, notified_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (course_name, grade, credit, semester, course_type,
                 raw_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )
        return True

    def find_new_grades(self, grades: list[dict]) -> list[dict]:
        """
        从成绩列表中筛选出新增的成绩。
        grades: [{"course_name": str, "grade": str, "credit": str, ...}, ...]
        返回: 新成绩列表
        """
        new_grades = []
        for g in grades:
            raw_id = _make_raw_id(
                g.get("course_name", ""),
                g.get("semester", ""),
                g.get("grade", "")
            )
            if not self.exists(raw_id):
                new_grades.append(g)
                self.insert_grade(
                    course_name=g.get("course_name", ""),
                    grade=g.get("grade", ""),
                    credit=g.get("credit", ""),
                    semester=g.get("semester", ""),
                    course_type=g.get("course_type", "")
                )
        return new_grades

    def get_all_grades(self) -> list[dict]:
        """获取所有已记录的成绩"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM grades ORDER BY created_at DESC"
            ).fetchall()
            return [dict(row) for row in rows]

    def get_recent_notifications(self, limit: int = 10) -> list[dict]:
        """获取最近的通知记录"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM grades WHERE notified_at IS NOT NULL "
                "ORDER BY notified_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(row) for row in rows]
