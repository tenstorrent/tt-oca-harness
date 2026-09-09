# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""sepvp — a Python runner + harness for the SEP virtual platform (sep-vp).

Launches a compiled SEP firmware ELF on the ``sep-vp`` SystemC virtual platform with
friendly control over boot straps, OTP fuses, and the SPI flash image, and exposes a
pexpect-style ``expect()`` API over the platform's decoded stdout streams
(``[SEP_STATUS]`` production status, ``[SIM_OUT]`` debug console, firmware ``printf``).

See ``virtual_platform/sepvp/README.md`` for the design.
"""

from sepvp.config import SimConfig
from sepvp.harness import Harness, HarnessError
from sepvp.sepvp_harness import SepVpHarness

__all__ = ["SimConfig", "Harness", "HarnessError", "SepVpHarness"]
