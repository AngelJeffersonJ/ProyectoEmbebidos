from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / '.env'
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)


class Config:
    """Centralized configuration loaded from environment variables."""

    FLASK_ENV = os.getenv('FLASK_ENV', 'development')
    DEBUG = FLASK_ENV == 'development'
    TESTING = os.getenv('TESTING', 'false').lower() == 'true'
    SECRET_KEY = os.getenv('SECRET_KEY', 'change-me')

    AIO_USERNAME = os.getenv('AIO_USERNAME', '')
    AIO_KEY = os.getenv('AIO_KEY', '')
    AIO_FEED_KEY = os.getenv('AIO_FEED_KEY', 'wardrive')

    STORAGE_PATH = os.getenv('STORAGE_PATH', str(BASE_DIR / 'storage' / 'data.jsonl'))
    OFFLINE_BUFFER_PATH = os.getenv('OFFLINE_BUFFER_PATH', str(BASE_DIR / 'storage' / 'offline_buffer.jsonl'))
    REQUEST_TIMEOUT = float(os.getenv('REQUEST_TIMEOUT', '10'))
