import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Must be set before app.config.get_settings() is first called.
os.environ["STAFF_USERNAME"] = "staff"
os.environ["STAFF_PASSWORD"] = "s3cret-pass"
os.environ["SECRET_KEY"] = "test-secret-key"
