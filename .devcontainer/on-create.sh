#!/bin/sh
# Runs once, when the codespace is created. pnpm comes from Corepack at the exact version and hash
# of the packageManager field in frontend/package.json (never npm install). Creates no file in the
# repository and no .env file.
set -eu

corepack enable pnpm
cd frontend
# Also the default outside frontend/, so `pnpm --version` gives the pinned version everywhere.
corepack install --global "$(node -p 'require("./package.json").packageManager')"
