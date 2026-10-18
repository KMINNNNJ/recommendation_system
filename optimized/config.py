"""Shared resource locations; credentials and models are not copied."""

import os
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parent
RESOURCE_ROOT = Path(
    os.getenv("RECOMMEND_RESOURCE_ROOT", str(CODE_ROOT.parent))
).expanduser().resolve()
