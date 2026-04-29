"""
Gunicorn config for Render.

This lets your Render start command stay simple, for example:
    gunicorn app:app

Gunicorn automatically reads gunicorn.conf.py from the project root.

Why this exists:
- Render provides PORT dynamically.
- Twilio /media is a long-lived websocket.
- The default Gunicorn sync worker timeout kills long websocket calls after ~30s.
"""

import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
worker_class = "gthread"
workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
threads = int(os.environ.get("GUNICORN_THREADS", "100"))
timeout = 0
graceful_timeout = 30
keepalive = 75
accesslog = "-"
errorlog = "-"
loglevel = "info"
