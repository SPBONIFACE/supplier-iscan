# Dev container (GitHub Codespaces)

How to use it: `README.md`, "Running it", "In a browser (GitHub Codespaces)". What is pinned
(`_docs/process/approved-dependencies.md`, "Dev container"):

| Item | Version | Pinned by |
| :--- | :--- | :--- |
| Base image `python:3.13.16-trixie` | Python 3.13.16 | digest, `Dockerfile` |
| `ghcr.io/astral-sh/uv` | 0.12.24 | digest (same as `backend/Dockerfile`), `Dockerfile` |
| `ghcr.io/devcontainers/features/common-utils` | 2.7.1 | digest, `devcontainer.json` |
| `ghcr.io/devcontainers/features/node` | 2.1.1, Node.js 24.22.1 | digest, `devcontainer.json` |
| `ghcr.io/devcontainers/features/docker-in-docker` | 4.1.3, Docker CE (`moby: false`) | digest, `devcontainer.json` |
| pnpm | `packageManager` in `frontend/package.json` | Corepack, `on-create.sh` |

Docker CE rather than Moby: the feature does not support Moby on Debian trixie.

Database: `post-start.sh` starts the `db` service of `docker-compose.yml` inside the codespace.
`devcontainer.json` maps the host name `db` to the container's loopback, so `DATABASE_URL` has the
same local-only value as in `docker-compose.yml` and serves both `make test` and `make run`.
