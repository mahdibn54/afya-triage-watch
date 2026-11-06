FROM ghcr.io/wso2/fhir-mcp-server@sha256:52443bfe53dda032ceab5232163570976887d00bce2c635c3875c29d988ff2c1
USER root
RUN /opt/venv/bin/python -m ensurepip && /opt/venv/bin/python -m pip install --no-cache-dir pytest
COPY evals/stack/test_isolation.py /checks/test_isolation.py
USER 10001
