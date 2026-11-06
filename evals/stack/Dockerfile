FROM python:3.12-slim
WORKDIR /checks
COPY mcp/pyproject.toml /src/mcp/pyproject.toml
COPY mcp/afya_mcp /src/mcp/afya_mcp
COPY api/pyproject.toml /src/api/pyproject.toml
COPY api/afya_api /src/api/afya_api
RUN pip install --no-cache-dir /src/mcp /src/api pytest
COPY api/tests/fake_model.py /checks/fake_model.py
COPY evals/stack /checks
CMD ["python", "-m", "pytest", "/tests", "-q", "-p", "no:cacheprovider", "--ignore=/tests/test_isolation.py", "--junitxml=/artifacts/group-a.xml"]
