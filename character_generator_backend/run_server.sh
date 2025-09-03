#!/usr/bin/env bash
# Simple runner for local development
set -euo pipefail
export PYTHONPATH=./
exec uvicorn src.api.main:app --host 0.0.0.0 --port 3001 --reload
