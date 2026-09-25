#!/bin/bash
PORT=${1:-8000}
echo "Starting Engine History API on port $PORT"
uvicorn main:app --host 0.0.0.0 --port $PORT --reload