"""Gunicorn settings for the container (see Dockerfile)."""

import os

bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:5006")
workers = int(os.environ.get("GUNICORN_WORKERS", "3"))
timeout = 30
# The worker heartbeat file goes to memory where there is a /dev/shm, so the
# container's filesystem can be read-only. Elsewhere, such as macOS, gunicorn's default applies.
worker_tmp_dir = "/dev/shm" if os.path.isdir("/dev/shm") else None
accesslog = "-"
# The path without its query string, so sign-up tokens never reach the logs.
# The client address is the one the reverse proxy forwarded.
access_log_format = '%({x-forwarded-for}i)s %(t)s "%(m)s %(U)s %(H)s" %(s)s %(b)s %(M)sms'
