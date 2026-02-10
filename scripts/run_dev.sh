#!/usr/bin/env bash
set -e
uvicorn backend.app:app --reload --port 8000
