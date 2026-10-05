# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Load the DV OCA helper modules without running env/__init__, which imports cocotb.

The stand-in package must be named `env` in `sys.modules`, because the helpers import
each other with `from env import ...`. It replaces any other `env` package for the rest
of the session.
"""

import importlib
import sys
import types

from sepvp import paths

DV_ENV_DIR = paths.OCAH_ROOT / "hw" / "sys" / "sep" / "dv" / "cocotb" / "env"


def load(name: str) -> types.ModuleType:
    package = sys.modules.get("env")
    if package is None or list(getattr(package, "__path__", [])) != [str(DV_ENV_DIR)]:
        package = types.ModuleType("env")
        package.__path__ = [str(DV_ENV_DIR)]
        sys.modules["env"] = package
    return importlib.import_module(f"env.{name}")
