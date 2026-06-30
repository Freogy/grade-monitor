FROM python:3.11-slim

WORKDIR /app

# 创建数据目录（运行时通过 volume 挂载持久化）
RUN mkdir -p /app/data

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制源码
COPY *.py .

# 数据目录声明为 volume（存放 grades.db 和 monitor.log）
VOLUME ["/app/data"]

ENV TZ=Asia/Shanghai
ENV DATA_DIR=/app/data

# 使用 exec 形式确保信号传递
CMD ["python", "-u", "monitor.py"]
