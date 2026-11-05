# Build context is the repo root (see docker-compose.yml): the api imports the shared SQL module afya_mcp.workflow.
FROM python:3.12-slim
WORKDIR /app
COPY mcp/pyproject.toml /src/mcp/pyproject.toml
COPY mcp/afya_mcp /src/mcp/afya_mcp
RUN pip install --no-cache-dir /src/mcp
COPY api/pyproject.toml ./
COPY api/afya_api ./afya_api
RUN pip install --no-cache-dir .
USER 1000
EXPOSE 8080
CMD ["uvicorn", "afya_api.main:app", "--host", "0.0.0.0", "--port", "8080"]
