# Backend API image. No secret and no data file is copied in: configuration is passed at run time
# through environment variables.
FROM ghcr.io/astral-sh/uv:0.12.24@sha256:3af4716e991d6956a41e573eab705d0ee08500cd829ed30293eb8472f372c65a AS uv

FROM python:3.13.16-slim-trixie@sha256:cf50a4f6ac4f026458b08d5222023d700ac806410dff5e9ca8728fa44f2b850f

COPY --from=uv /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PYTHONUNBUFFERED=1 \
    REDACTION_MODEL_DIR=/opt/model \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

WORKDIR /app

# Runtime dependencies only, installed from the committed lockfile without changing it.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev

# The name-detection model (#19): fetched here, at build time, from a pinned revision and checked
# against sha256 digests in scripts/fetch_model.py; the running application never downloads
# anything. No secret is involved (public files).
COPY scripts/fetch_model.py ./scripts/fetch_model.py
RUN /opt/venv/bin/python scripts/fetch_model.py /opt/model

COPY app ./app

RUN useradd --system --uid 10001 --no-create-home api
USER api

# API port, fixed (README "Running it"). Listens on all container interfaces; the host
# publishes it on 127.0.0.1 only (docker-compose.yml).
EXPOSE 8000
CMD ["/opt/venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
