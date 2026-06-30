"""
QQ 邮箱通知模块
通过 QQ SMTP 发送成绩更新提醒邮件。
"""

import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

from config import (
    SENDER_EMAIL,
    SMTP_AUTH_CODE,
    RECIPIENT_EMAIL,
    SMTP_SERVER,
    SMTP_PORT,
)

logger = logging.getLogger(__name__)


def _build_email_html(grades: list[dict]) -> str:
    """构建通知邮件 HTML 内容"""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rows_html = ""
    for g in grades:
        rows_html += f"""
        <tr>
            <td style="padding:10px 14px;border:1px solid #e0e0e0;">{g.get('course_name', '-')}</td>
            <td style="padding:10px 14px;border:1px solid #e0e0e0;text-align:center;
                font-weight:bold;color:#d4380d;">{g.get('grade', '-')}</td>
            <td style="padding:10px 14px;border:1px solid #e0e0e0;text-align:center;">{g.get('credit', '-')}</td>
            <td style="padding:10px 14px;border:1px solid #e0e0e0;text-align:center;">{g.get('semester', '-')}</td>
            <td style="padding:10px 14px;border:1px solid #e0e0e0;text-align:center;">{g.get('course_type', '-')}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:'Microsoft YaHei','PingFang SC',sans-serif;background:#f5f5f5;padding:20px;">
<div style="max-width:650px;margin:0 auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">

    <!-- Header -->
    <div style="background:#1677ff;padding:24px 28px;text-align:center;">
        <h1 style="color:#fff;margin:0;font-size:22px;">
            📢 你有新成绩出来了！
        </h1>
        <p style="color:rgba(255,255,255,0.85);margin:8px 0 0;font-size:14px;">
            共 {len(grades)} 门课程更新
        </p>
    </div>

    <!-- Grade Table -->
    <div style="padding:24px 28px;">
        <table style="width:100%;border-collapse:collapse;font-size:14px;">
            <thead>
                <tr style="background:#fafafa;">
                    <th style="padding:12px 14px;border:1px solid #e0e0e0;text-align:left;">课程名称</th>
                    <th style="padding:12px 14px;border:1px solid #e0e0e0;text-align:center;">成绩</th>
                    <th style="padding:12px 14px;border:1px solid #e0e0e0;text-align:center;">学分</th>
                    <th style="padding:12px 14px;border:1px solid #e0e0e0;text-align:center;">学期</th>
                    <th style="padding:12px 14px;border:1px solid #e0e0e0;text-align:center;">类别</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
    </div>

    <!-- Footer -->
    <div style="padding:18px 28px;background:#fafafa;border-top:1px solid #f0f0f0;
        text-align:center;color:#999;font-size:12px;">
        <p style="margin:2px 0;">⏰ 检测时间: {now_str}</p>
        <p style="margin:2px 0;">📧 由成绩提醒系统自动发送 · 浙江大学本科生教学网</p>
    </div>

</div>
</body>
</html>"""
    return html


def send_grade_notification(grades: list[dict]) -> bool:
    """
    发送成绩通知邮件。
    返回 True 表示发送成功。
    """
    if not grades:
        logger.info("没有新成绩，跳过邮件发送")
        return True

    logger.info(f"准备发送通知邮件... 共 {len(grades)} 门新课")

    subject = f"📢 你有 {len(grades)} 门新成绩出来了！"

    # 构建纯文本版
    text_lines = ["你有新成绩更新了！\n"]
    for g in grades:
        text_lines.append(
            f"  · {g.get('course_name', '-')}  "
            f"成绩: {g.get('grade', '-')}  "
            f"学分: {g.get('credit', '-')}  "
            f"学期: {g.get('semester', '-')}"
        )
    text_body = "\n".join(text_lines)

    # 构建 HTML 邮件
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECIPIENT_EMAIL

    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(_build_email_html(grades), "html", "utf-8"))

    try:
        # SSL 直连方式
        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=30)
        server.login(SENDER_EMAIL, SMTP_AUTH_CODE)
        server.sendmail(SENDER_EMAIL, RECIPIENT_EMAIL, msg.as_string())
        server.quit()

        logger.info(f"[OK] 邮件发送成功 -> {RECIPIENT_EMAIL}")
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error(
            "❌ QQ邮箱 SMTP 认证失败！请检查:\n"
            "  1. QQ邮箱是否开启了 SMTP 服务（设置→账户→POP3/SMTP服务）\n"
            "  2. .env 中的 SMTP_AUTH_CODE 是否是授权码（非QQ密码）\n"
            "  3. SENDER_EMAIL 是否与开启SMTP的QQ号一致"
        )
        return False

    except smtplib.SMTPException as e:
        logger.error(f"[FAIL] 邮件发送失败: {e}")
        return False


def send_test_email() -> bool:
    """发送一封测试邮件，用于验证配置是否正确"""
    test_grades = [{
        "course_name": "这是一封测试邮件",
        "grade": "100",
        "credit": "4.0",
        "semester": "测试学期",
        "course_type": "测试"
    }]

    subject = "✅ 成绩提醒系统 - 测试邮件"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECIPIENT_EMAIL

    html = _build_email_html(test_grades)
    html = html.replace("你有新成绩出来了", "成绩提醒系统配置成功")
    msg.attach(MIMEText("这是一封测试邮件，表示邮件配置正确。", "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=30)
        server.login(SENDER_EMAIL, SMTP_AUTH_CODE)
        server.sendmail(SENDER_EMAIL, RECIPIENT_EMAIL, msg.as_string())
        server.quit()
        print(f"✅ 测试邮件发送成功！请检查收件箱: {RECIPIENT_EMAIL}")
        return True
    except Exception as e:
        print(f"❌ 测试邮件发送失败: {e}")
        return False
