"""
成绩提醒系统 - 主监控程序
定时爬取浙大教务系统成绩，发现新成绩时通过 QQ 邮箱发送通知。

用法:
    python monitor.py          # 正常监控模式（定时检查）
    python monitor.py --once   # 单次检查
    python monitor.py --test   # 发送测试邮件
"""

import argparse
import logging
import os
import signal
import sys
import time
from datetime import datetime

import schedule

from config import CHECK_INTERVAL, DATA_DIR, LOG_PATH
from database import GradeDB
from scraper import JwxtScraper, LoginError, ScrapeError
from notifier import send_grade_notification, send_test_email

# --- 日志配置 ---
os.makedirs(DATA_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# --- 优雅退出标志 ---
_shutdown_requested = False


def _on_shutdown(signum, frame):
    global _shutdown_requested
    logger.info(f"[信号] 收到 {signal.Signals(signum).name}，正在优雅退出...")
    _shutdown_requested = True


def check_once(scraper: JwxtScraper, db: GradeDB) -> list[dict]:
    """
    执行一次完整的检查流程：
    登录 -> 抓取成绩 -> 比对数据库 -> 发送通知
    返回新成绩列表。
    """
    logger.info("=" * 50)
    logger.info("[检查] 开始新一轮成绩检查")

    # 1. 抓取成绩
    try:
        grades = scraper.fetch_grades()
    except LoginError as e:
        logger.error(f"登录失败: {e}")
        return []
    except ScrapeError as e:
        logger.error(f"抓取失败: {e}")
        return []
    except Exception as e:
        logger.error(f"未知错误: {e}", exc_info=True)
        return []

    if not grades:
        logger.info("未抓取到任何成绩记录（可能暂无成绩或页面结构变更）")
        return []

    logger.info(f"抓取到 {len(grades)} 条成绩")

    # 2. 筛选新成绩
    new_grades = db.find_new_grades(grades)

    if not new_grades:
        logger.info("没有发现新成绩，无需通知")
        return []

    logger.info(f"[新成绩] 发现 {len(new_grades)} 门新成绩！")
    for g in new_grades:
        logger.info(
            f"  - {g.get('course_name', '-')} | "
            f"成绩: {g.get('grade', '-')} | "
            f"学分: {g.get('credit', '-')} | "
            f"学期: {g.get('semester', '-')}"
        )

    # 3. 发送通知
    success = send_grade_notification(new_grades)
    if not success:
        logger.warning("通知发送失败，但成绩已记录到数据库，下次不会重复通知")

    return new_grades


def run_monitor():
    """持续监控模式"""
    scraper = JwxtScraper()
    db = GradeDB()

    logger.info("=" * 50)
    logger.info("[启动] 成绩提醒系统启动")
    logger.info(f"   教务系统: {scraper.jwglxt_base}")
    logger.info(f"   检查间隔: {CHECK_INTERVAL} 分钟")
    logger.info(f"   通知邮箱: {RECIPIENT_EMAIL}")
    logger.info("=" * 50)

    # 启动后立即检查一次
    check_once(scraper, db)

    # 定时调度
    schedule.every(CHECK_INTERVAL).minutes.do(lambda: check_once(scraper, db))

    logger.info(f"[定时] 下次检查时间: {CHECK_INTERVAL} 分钟后")

    while not _shutdown_requested:
        schedule.run_pending()
        time.sleep(30)

    logger.info("[退出] 成绩提醒系统已停止")


if __name__ == "__main__":
    from config import RECIPIENT_EMAIL

    # 注册信号处理（Docker stop 时优雅退出）
    signal.signal(signal.SIGTERM, _on_shutdown)
    signal.signal(signal.SIGINT, _on_shutdown)

    parser = argparse.ArgumentParser(description="成绩提醒系统")
    parser.add_argument(
        "--once", action="store_true",
        help="只执行一次检查后退出"
    )
    parser.add_argument(
        "--test", action="store_true",
        help="发送测试邮件验证配置"
    )
    args = parser.parse_args()

    if args.test:
        print("[邮件] 正在发送测试邮件...")
        send_test_email()
        sys.exit(0)

    if args.once:
        scraper = JwxtScraper()
        db = GradeDB()
        new_grades = check_once(scraper, db)
        if new_grades:
            print(f"\n[完成] 发现 {len(new_grades)} 门新成绩，通知已发送")
        else:
            print("\n[完成] 检查完毕，没有新成绩")
        sys.exit(0)

    run_monitor()
