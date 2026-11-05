FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY afya_api ./afya_api
RUN pip install --no-cache-dir .
USER 1000
EXPOSE 8080
CMD ["uvicorn", "afya_api.main:app", "--host", "0.0.0.0", "--port", "8080"]
