# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ocah_uart_vip — hierarchical VIP layout.

cocotb/     cocotb (Python) VIP; its stable public API is re-exported here,
            so ``from ocah_uart_vip import <Class>`` is the import every test uses
interface/  SV interfaces shared by the cocotb and UVM flows (where present)
uvm/        SV-UVM agent collateral (where present)
cov/        framework-neutral SV coverage models (where present)
"""

from .cocotb import *  # noqa: F401,F403
from .cocotb import __all__  # noqa: F401
