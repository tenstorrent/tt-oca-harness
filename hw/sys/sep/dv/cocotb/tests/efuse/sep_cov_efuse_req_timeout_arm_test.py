# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The request-timeout arms of the program and read interfaces.

``efuse_program_interface`` and ``efuse_read_interface`` each carry a
request-timeout counter in ``ST_WAIT_RESP``: while the bank response is
outstanding, ``timeout_count_q`` counts up and, at
``*_req_timeout_cycles_i``, the FSM abandons the command with ``err`` set and
raises a timeout event. Both timeouts are disabled at reset
(``EFUSE_*_REQ_TIMEOUT`` default 0x0080_0000, enable clear), so the counters
and the abandon arms have never moved.

The stimulus arms each timeout at a cycle count below the shim's bank init
time, which the shim spends before the APB phase even starts, so the response
is still outstanding when the counter expires. The counter values are a
walking sweep of the low bits of the 28-bit cycle field as well, so
``timeout_count_q`` moves over more than one bit position.

Both timeouts are disarmed at the end, so the register bank is not left with a
short timeout for whatever runs next in the same simulation.

``+skip_fuse_sense``: the arm is reached by abandoning the request, not by
what the bank returns.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test

from seq_lib.sep_cov_efuse_iface_seq import SepCovEfuseIface
from seq_lib.sep_efuse_program_lock_seq import field_bit_addr

# The shim reloads its bank-init counter with EFUSE_BANK_INIT_TIME, reset 0x20,
# before each bank phase. Any timeout below that expires while the request is
# still outstanding.
SHIM_INIT_TIME_RESET = 0x20
TIMEOUT_CYCLES = (4, 8, 16)

# An unlocked spare bit. The command is abandoned before it completes, so the
# bit is the request's address and not a value this test reads back.
PROBE_BIT_ADDR = field_bit_addr("SPARE0", 0)


@pyuvm.test()
class sep_cov_efuse_req_timeout_arm_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        efuse = SepCovEfuseIface(self)
        await efuse.clear_errors()

        for cycles in TIMEOUT_CYCLES:
            assert cycles < SHIM_INIT_TIME_RESET, (
                f"timeout of {cycles} cycles is not below the shim bank init time "
                f"{SHIM_INIT_TIME_RESET}, so the request would already have retired"
            )
            await efuse.set_program_timeout(cycles, enable=True)
            await efuse.program(PROBE_BIT_ADDR, data=1, enable=True, read_back=True)
            await efuse.clear_errors()

            await efuse.set_read_timeout(cycles, enable=True)
            await efuse.read(PROBE_BIT_ADDR)
            await efuse.clear_errors()
            self.logger.info("[cov] program and read request timeouts armed at %d cycles", cycles)

        # Leave both timeouts disarmed at their reset cycle count.
        await efuse.set_program_timeout(0x0080_0000, enable=False)
        await efuse.set_read_timeout(0x0080_0000, enable=False)
        await efuse.clear_errors()
        self.logger.info("[cov] request-timeout sweep done; both timeouts disarmed")
