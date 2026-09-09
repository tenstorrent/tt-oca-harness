# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Bootstrap the sep-vp harness plugin for all VP pytest suites.

The ``sepvp`` package is deliberately not installed (no editable install); this
top-level conftest makes it importable and loads the shared plugin for every
suite under tests/.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
pytest_plugins = ["sepvp.pytest_plugin"]
