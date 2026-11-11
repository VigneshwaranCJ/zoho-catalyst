# syntax=docker/dockerfile:1
# One Dockerfile, two images (choose with `--target`):
#   api    : FastAPI server. Slim: no Docling / PyTorch.
#   worker : background jobs. Adds the `ingestion` dependency group (Docling,
#            CPU-only PyTorch) and Docling's models, downloaded at BUILD time so
#            the container never downloads anything at runtime.
# Both run as a non-root user.

# ---------------------------------------------------------------- dependencies
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Extra dependency groups, e.g. "--group ingestion" for the worker.
ARG UV_GROUPS=""
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-default-groups ${UV_GROUPS} --no-install-project
COPY . .

# ---------------------------------------------------------------- docling models
FROM builder AS models
ENV HF_HOME=/tmp/hf
# Layout + table-structure + OCR models only (what our PDF pipeline uses).
RUN /app/.venv/bin/python -c "from pathlib import Path; \
from docling.utils.model_downloader import download_models; \
download_models(output_dir=Path('/models'), with_code_formula=False, \
with_picture_classifier=False, progress=False)" \
 && du -sh /models

# ---------------------------------------------------------------- api runtime
FROM python:3.12-slim AS api
RUN useradd --create-home --uid 10001 app \
 && mkdir -p /data/storage && chown app:app /data/storage
WORKDIR /app
COPY --from=builder --chown=app:app /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 STORAGE_DIR=/data/storage
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ---------------------------------------------------------------- worker runtime
FROM api AS worker
USER root
# Shared libraries needed by the OCR/image stack (OpenCV, ONNX Runtime).
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*
COPY --from=models --chown=app:app /models /models
ENV DOCLING_ARTIFACTS_PATH=/models HF_HOME=/tmp/hf HF_HUB_OFFLINE=1 OMP_NUM_THREADS=4
USER app
HEALTHCHECK NONE
CMD ["python", "-m", "app.worker"]
