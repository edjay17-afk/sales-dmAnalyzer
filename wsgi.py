"""WSGI entrypoint for PythonAnywhere, Gunicorn, or uWSGI."""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app as application  # noqa: E402,F401
