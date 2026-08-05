#!/bin/sh
set -eu
python -m pip install -r requirements.txt
exec python -m uvicorn main:app --host 0.0.0.0 --port 10000
