# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Load the DV OCA helper modules without running env/__init__, which imports cocotb.

The stand-in package must be named `env` in `sys.modules`, because the helpers import
each other with `from env import ...`. It replaces any other `env` package for the rest
of the session. Some helpers also import their siblings as top-level modules, so the
directory is put on `sys.path` too.
"""

import importlib
import sys
import types

from sepvp import paths

DV_ENV_DIR = paths.OCAH_ROOT / "hw" / "sys" / "sep" / "dv" / "cocotb" / "env"


def load(name: str) -> types.ModuleType:
    if str(DV_ENV_DIR) not in sys.path:
        sys.path.append(str(DV_ENV_DIR))
    package = sys.modules.get("env")
    if package is None or list(getattr(package, "__path__", [])) != [str(DV_ENV_DIR)]:
        package = types.ModuleType("env")
        package.__path__ = [str(DV_ENV_DIR)]
        sys.modules["env"] = package
    return importlib.import_module(f"env.{name}")
