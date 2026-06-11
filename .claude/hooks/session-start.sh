#!/bin/bash
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

# Install web dependencies
cd "$CLAUDE_PROJECT_DIR/web"
npm install

# Upgrade setuptools so legacy packages (e.g. python-bitcoinrpc) build correctly
pip install -q --upgrade setuptools

# Install backend Python dependencies
pip install -q -r "$CLAUDE_PROJECT_DIR/backend/requirements.txt"

# Install collector Python dependencies
pip install -q -r "$CLAUDE_PROJECT_DIR/collector/requirements.txt"
