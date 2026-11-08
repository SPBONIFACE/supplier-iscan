# Dev container image for GitHub Codespaces (#57). Python and uv only; Node, Docker and the
# non-root user come from the pinned features in devcontainer.json. No secret and no data file
# is copied in.
FROM ghcr.io/astral-sh/uv:0.12.24@sha256:3af4716e991d6956a41e573eab705d0ee08500cd829ed30293eb8472f372c65a AS uv

# Python 3.13.16, the version pinned in backend/.python-version.
FROM python:3.13.16-trixie@sha256:5b16f8c3c772f377a8a0133ee26cfe1d5b8359c88d408836281adb99fc6219d6

COPY --from=uv /uv /usr/local/bin/uv

# uv uses this image's Python and never downloads another one, so a version drift fails loudly.
ENV UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy
