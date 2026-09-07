#!/bin/bash
set -a
source ../.env.local
export PROVIDER=groq+firecrawl
set +a
exec .venv/bin/uvicorn app.main:app --port 8000
