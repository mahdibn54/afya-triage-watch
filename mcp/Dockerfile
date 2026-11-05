FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY afya_mcp ./afya_mcp
RUN pip install --no-cache-dir .
USER 1000
EXPOSE 9000
CMD ["uvicorn", "afya_mcp.server:app", "--host", "0.0.0.0", "--port", "9000"]
