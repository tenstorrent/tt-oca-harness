# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ocah_lib — the shared DV framework library every OCAH bench class extends.

cocotb/     PyUVM realization; its public API is re-exported here, so
            ``from ocah_lib import OcahTest`` is the import every bench uses
uvm/        SV-UVM realization (``ocah_lib_pkg``, entered through
            ``uvm/sources.toml``), identical basenames
"""

from .cocotb import *  # noqa: F401,F403
from .cocotb import __all__  # noqa: F401
