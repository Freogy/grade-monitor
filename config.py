"""
配置管理模块
读取 .env 文件中的配置项，提供统一的配置访问接口。
"""

import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))


def get_env(key: str, default=None) -> str:
    """获取环境变量，不存在时抛出异常或返回默认值"""
    value = os.getenv(key, default)
    if value is None:
        raise ValueError(f"缺少必要的配置项: {key}，请在 .env 文件中设置")
    return value


# --- 数据目录 ---
# 所有持久化文件（数据库、日志）存放在此目录下
# Docker 部署时设为 /app/data 配合 volume 挂载
DATA_DIR = os.getenv("DATA_DIR", os.path.join(BASE_DIR, "data"))
os.makedirs(DATA_DIR, exist_ok=True)

# --- 教务系统配置 ---
PORTAL_URL = get_env("PORTAL_URL")
STUDENT_ID = get_env("STUDENT_ID")
PASSWORD = get_env("PASSWORD")

# --- QQ 邮箱配置 ---
SENDER_EMAIL = get_env("SENDER_EMAIL")
SMTP_AUTH_CODE = get_env("SMTP_AUTH_CODE")
RECIPIENT_EMAIL = get_env("RECIPIENT_EMAIL")

# --- 运行配置 ---
CHECK_INTERVAL = int(get_env("CHECK_INTERVAL", "60"))

# --- 数据库路径 ---
DB_PATH = os.getenv("DB_PATH", os.path.join(DATA_DIR, "grades.db"))

# --- 日志路径 ---
LOG_PATH = os.path.join(DATA_DIR, "monitor.log")

# --- SMTP 配置 ---
SMTP_SERVER = "smtp.qq.com"
SMTP_PORT = 465
