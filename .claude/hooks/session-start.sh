#!/bin/bash
#
# SessionStart hook for Claude Code on the web (cloud environments).
#
# Purpose: install project dependencies so tests and linters work in remote
# sessions. This repository is currently empty, so this scaffold auto-detects
# common dependency manifests and installs them when present, and is a safe
# no-op otherwise. Flesh out the relevant section once you add your project.
#
# Runs synchronously: the cloud session waits for this to finish before the
# agent starts, which avoids race conditions at the cost of slightly slower
# startup. Switch to async mode later if you prefer faster startup.
#
# Docs: https://code.claude.com/docs/en/claude-code-on-the-web
set -euo pipefail

# Only run in Claude Code on the web (remote) sessions. Remove this guard if
# you also want dependency installation to run for local sessions.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  echo "[session-start] Local session; skipping dependency install."
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"

echo "[session-start] Detecting project dependencies..."

ran_something=false

# --- Node.js (npm / pnpm / yarn) ---
if [ -f package.json ]; then
  ran_something=true
  if [ -f pnpm-lock.yaml ] && command -v pnpm >/dev/null 2>&1; then
    echo "[session-start] pnpm install"
    pnpm install
  elif [ -f yarn.lock ] && command -v yarn >/dev/null 2>&1; then
    echo "[session-start] yarn install"
    yarn install
  else
    # Prefer 'npm install' over 'npm ci' so the cached container benefits.
    echo "[session-start] npm install"
    npm install
  fi
fi

# --- Python (pip / Poetry / uv) ---
if [ -f pyproject.toml ] || [ -f requirements.txt ]; then
  ran_something=true
  if [ -f poetry.lock ] && command -v poetry >/dev/null 2>&1; then
    echo "[session-start] poetry install"
    poetry install
  elif [ -f uv.lock ] && command -v uv >/dev/null 2>&1; then
    echo "[session-start] uv sync"
    uv sync
  elif [ -f requirements.txt ]; then
    echo "[session-start] pip install -r requirements.txt"
    pip install -r requirements.txt
  fi
fi

# --- Rust (cargo) ---
if [ -f Cargo.toml ]; then
  ran_something=true
  echo "[session-start] cargo fetch"
  cargo fetch
fi

# --- Go ---
if [ -f go.mod ]; then
  ran_something=true
  echo "[session-start] go mod download"
  go mod download
fi

# --- Ruby (bundler) ---
if [ -f Gemfile ]; then
  ran_something=true
  echo "[session-start] bundle install"
  bundle install
fi

if [ "$ran_something" = false ]; then
  echo "[session-start] No dependency manifest found yet — nothing to install."
  echo "[session-start] Add your project, then customize this hook as needed."
fi

echo "[session-start] Done."
