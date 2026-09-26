"""Test suite for the Baby AI laboratory (Milestone 001).

Importing this package puts the project root on ``sys.path`` so that
``import babylab`` works regardless of the working directory.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
