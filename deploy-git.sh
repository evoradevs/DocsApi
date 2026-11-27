#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

branch="${1:-main}"
if [[ "$(git branch --show-current)" != "$branch" ]]; then
  echo "ERRO: selecione a branch $branch antes de executar o deploy." >&2
  exit 1
fi
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo 'ERRO: há alterações locais em arquivos rastreados.' >&2
  exit 1
fi

git pull --ff-only origin "$branch"
docker compose config --quiet
docker compose build
docker compose up -d --wait --wait-timeout 120
docker compose ps
