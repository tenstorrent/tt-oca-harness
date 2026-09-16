# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
cocotb 2.x adapter for the vendored cocotbext-i3c.

cocotbext-i3c 1.1.0 targets cocotb 1.x and imports names that cocotb 2.0 moved or
dropped, so importing it directly fails. This module restores them on the modules
it reads them from, then re-exports the classes the TB uses, so import order is not
something every consumer has to get right.

  cocotb.utils._get_log_time_scale      moved to cocotb.simtime
  cocotb.utils._get_simulator_precision replaced by the cocotb.simtime.time_precision
                                        module attribute, which the simulator sets
                                        during startup and so must be read lazily
  cocotb.handle.ModifiableObject        replaced by ValueObjectBase; used only as a
                                        type annotation here
"""

import cocotb.handle
import cocotb.simtime
import cocotb.utils

if not hasattr(cocotb.utils, "_get_log_time_scale"):
    cocotb.utils._get_log_time_scale = cocotb.simtime._get_log_time_scale

if not hasattr(cocotb.utils, "_get_simulator_precision"):
    cocotb.utils._get_simulator_precision = lambda: cocotb.simtime.time_precision

if not hasattr(cocotb.handle, "ModifiableObject"):
    cocotb.handle.ModifiableObject = cocotb.handle.ValueObjectBase

from cocotbext_i3c.common import I3C_RSVD_BYTE, I3cState  # noqa: E402
from cocotbext_i3c.i3c_target import I3cHeader, I3CTarget  # noqa: E402

__all__ = ["I3CTarget", "I3cHeader", "I3cState", "I3C_RSVD_BYTE"]
