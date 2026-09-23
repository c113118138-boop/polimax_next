"""Project-local configuration; relative paths are rooted at the project."""
import os
from pathlib import Path
from dotenv import dotenv_values


def settings(root):
    root = Path(root)
    return {**dotenv_values(root / 'env'), **dotenv_values(root / '.env'), **os.environ}


def local_path(root, value):
    path = Path(value).expanduser()
    return path if path.is_absolute() else Path(root) / path


def data_path(root, config=None):
    config = settings(root) if config is None else config
    return local_path(root, config.get('AMS_DATA_DIR') or config.get('PREVIEW_DATA_DIR') or '.data')
