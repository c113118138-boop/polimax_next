"""Select the native existing-schema backend, or explicitly requested demo mode."""
from pathlib import Path
from database import configuration
ROOT = Path(__file__).resolve().parents[1]
DATA, url, NATIVE = configuration(ROOT)
if NATIVE:
    from legacy_api import create_app
    app = create_app(ROOT, DATA, url)
    engine = app.state.engine
else:
    from demo_app import *
