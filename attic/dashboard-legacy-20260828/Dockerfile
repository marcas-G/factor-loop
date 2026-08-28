FROM python:3.13-slim

WORKDIR /app

# 只复制生成器需要的最小集合:config.py 是零依赖叶子模块
COPY core/config.py /app/core/config.py
COPY core/tools/generate_factor_dashboard.py /app/core/tools/generate_factor_dashboard.py
COPY core/tools/dashboard_template /app/core/tools/dashboard_template
RUN touch /app/core/__init__.py /app/core/tools/__init__.py

# data/ 由运行时挂载(factors.db 只读);HTML 生成到容器内 /app/data
COPY dashboard-server/serve.py /app/serve.py
COPY dashboard-server/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENV DASHBOARD_REFRESH_SECONDS=600 \
    DASHBOARD_PORT=8765 \
    PYTHONUNBUFFERED=1

EXPOSE 8765

ENTRYPOINT ["/app/entrypoint.sh"]
