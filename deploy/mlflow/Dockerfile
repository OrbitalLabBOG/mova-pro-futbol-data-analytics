FROM python:3.13.5-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MLFLOW_DISABLE_AGENT_HINT=1 PYTHONPATH=/app
ARG MOVA_MLFLOW_REVISION=unknown
LABEL org.opencontainers.image.revision=$MOVA_MLFLOW_REVISION
WORKDIR /app
COPY deploy/mlflow/requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r requirements.lock && useradd --uid 10002 --create-home mlflow
COPY experiments /app/experiments
COPY deploy/mlflow /app/deploy/mlflow
USER 10002:10002
EXPOSE 5000
ENTRYPOINT ["python", "/app/deploy/mlflow/server.py"]
