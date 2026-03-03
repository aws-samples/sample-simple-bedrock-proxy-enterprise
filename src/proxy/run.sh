#!/bin/bash
exec python -m uvicorn --port=$PORT main:app --no-server-header
