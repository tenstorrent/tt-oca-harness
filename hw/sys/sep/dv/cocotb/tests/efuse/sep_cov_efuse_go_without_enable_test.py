# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The early-reject arms of the program and read interface idle states.

``efuse_program_interface`` leaves ``ST_PROGRAM_IDLE`` on ``program_go`` and,
before issuing anything to the bank, rejects two combinations outright: the
enable clear, and the program data zero (the array is write-one-to-set, so a
program of 0 is not a command). ``efuse_read_interface`` has the matching
enable-clear arm in ``ST_READ_IDLE``. Each sets ``done`` and ``err`` in the
same cycle and stays in idle. Every existing test presents the fully enabled
combination, so none of the three arms has run.

All three are legal register programming: the CSR fields exist and software
may write any combination of them. Nothing here is out of bounds, so no
address-validity assertion is in play.

Each sequence is followed by a write of the ``EFUSE_INTERFACE_CTRL_STATUS``
clear bits, because a sticky error left set starves the next command.

``+skip_fuse_sense``: no command reaches the fuse bank, so nothing depends on
sensed data.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test

from seq_lib.sep_cov_efuse_iface_seq import SepCovEfuseIface
from seq_lib.sep_efuse_program_lock_seq import field_bit_addr

# An unlocked spare bit. No command reaches the bank on any of these arms, so
# the address is only there to be a legal in-range value.
PROBE_BIT_ADDR = field_bit_addr("SPARE0", 0)


@pyuvm.test()
class sep_cov_efuse_go_without_enable_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        efuse = SepCovEfuseIface(self)
        await efuse.clear_errors()

        # (a) program_go with program_enable clear.
        await efuse.program(PROBE_BIT_ADDR, data=1, enable=False, read_back=False)
        await efuse.clear_errors()
        self.logger.info("[cov] program go with enable clear driven")

        # (b) program_go with program_enable set and efuse_data zero.
        await efuse.program(PROBE_BIT_ADDR, data=0, enable=True, read_back=False)
        await efuse.clear_errors()
        self.logger.info("[cov] program go with data zero driven")

        # (c) read_go with read_enable clear.
        await efuse.read(PROBE_BIT_ADDR, enable=False)
        await efuse.clear_errors()
        self.logger.info("[cov] read go with enable clear driven")
