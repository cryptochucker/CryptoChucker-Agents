#!/usr/bin/env bash
# setup.sh - bootstrap the CryptoChucker Agents project (Linux/macOS/WSL)
set -euo pipefail

echo "[setup] Creating virtual environment..."
python3 -m venv .venv

echo "[setup] Installing dependencies..."
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -r requirements-dev.txt

if [ ! -f .env ]; then
    echo "[setup] Copying .env.example -> .env (fill in your secrets)"
    cp .env.example .env
else
    echo "[setup] .env already exists, skipping copy"
fi

echo "[setup] Done. Activate with: source .venv/bin/activate"
