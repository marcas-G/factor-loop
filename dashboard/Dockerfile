FROM python:3.13-slim
WORKDIR /app
COPY core/__init__.py /app/core/__init__.py
COPY core/config.py /app/core/config.py
COPY core/db/__init__.py /app/core/db/__init__.py
COPY core/db/db.py /app/core/db/db.py
COPY core/tools/__init__.py /app/core/tools/__init__.py
COPY core/tools/dashboard_snapshot.py /app/core/tools/dashboard_snapshot.py
COPY dashboard/__init__.py /app/dashboard/__init__.py
COPY dashboard/server.py /app/dashboard/server.py
COPY dashboard/frontend/dist /app/dashboard/frontend/dist
ENV PYTHONUNBUFFERED=1 DASHBOARD_PORT=8765 FACTORS_DB=/app/data/factors.db
EXPOSE 8765
CMD ["python3", "/app/dashboard/server.py"]
