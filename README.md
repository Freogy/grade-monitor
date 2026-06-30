# 🎓 成绩提醒系统

针对 **浙江大学本科生教学网** 的自动成绩监控系统。定时爬取教务系统成绩，发现新出成绩时自动发送 **QQ 邮箱通知**。

## ✨ 功能

- 🔍 自动登录浙大教务系统，抓取成绩列表
- 🆕 智能识别新出成绩（增量检测，不会重复通知）
- 📧 QQ 邮箱 HTML 通知（漂亮的成绩单邮件）
- ⏰ 可配置检查间隔
- 🐳 Docker 一键部署到云服务器
- 📝 本地 SQLite 存储，无需额外数据库

## 🚀 快速开始

### 1. 克隆/下载项目

```bash
cd 成绩提醒
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置 `.env`

```bash
cp .env.example .env
# 编辑 .env 填入你的信息
```

需要填写的配置：

| 配置项 | 说明 |
|--------|------|
| `PORTAL_URL` | 教务系统地址（默认浙大） |
| `STUDENT_ID` | 学号 |
| `PASSWORD` | 教务系统密码 |
| `SENDER_EMAIL` | 发件QQ邮箱（如 `123456@qq.com`） |
| `SMTP_AUTH_CODE` | QQ邮箱 SMTP 授权码 ⚠️ |
| `RECIPIENT_EMAIL` | 接收通知的邮箱 |
| `CHECK_INTERVAL` | 检查间隔（分钟），默认 60 |

> ⚠️ **SMTP 授权码获取方式**：登录 QQ 邮箱 → 设置 → 账户 → POP3/SMTP 服务 → 开启并获取授权码（不是 QQ 密码！）

### 4. 运行

```bash
# 持续监控模式（根据 CHECK_INTERVAL 定时检查）
python monitor.py

# 只执行一次检查
python monitor.py --once

# 发送测试邮件（验证邮箱配置）
python monitor.py --test
```

## 🐳 Docker 部署

```bash
# 构建并启动
docker compose up -d

# 查看日志
docker compose logs -f

# 停止
docker compose down
```

## 📁 目录结构

```
成绩提醒/
├── config.py          # 配置管理
├── database.py        # SQLite 数据库操作
├── scraper.py         # 教务系统爬虫
├── notifier.py        # QQ 邮件通知
├── monitor.py         # 主程序入口
├── requirements.txt   # Python 依赖
├── .env.example       # 配置模板
├── .env               # 实际配置（不提交）
├── Dockerfile         # Docker 镜像
├── docker-compose.yml # Docker Compose 编排
└── README.md          # 本文件
```

## 🔧 适配其他教务系统

如需适配其他学校的教务系统，主要修改 `scraper.py` 中的以下部分：

1. **登录逻辑**：修改 `login()` 方法中的表单字段名和验证逻辑
2. **成绩页面 URL**：修改 `GRADE_PAGE_PATHS` 列表
3. **表格解析**：修改 `_parse_grade_table()` 和 `_extract_grade_from_row()` 的解析规则

## 📝 License

MIT
