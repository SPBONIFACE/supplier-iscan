#!/bin/sh
# Runs at every start of the codespace: starts the PostgreSQL 16 service of docker-compose.yml
# (same image, same local-only defaults), so that `make test` has a database. `make run` reuses
# it. The database port is published on the container's loopback only and is not forwarded.
set -eu

# The Docker daemon of the docker-in-docker feature starts in the background.
tries=0
until docker info >/dev/null 2>&1; do
  tries=$((tries + 1))
  if [ "$tries" -ge 60 ]; then
    echo "Docker did not start within 60 seconds; start the database with: docker compose up -d --wait db" >&2
    exit 1
  fi
  sleep 1
done

docker compose up --detach --wait db
