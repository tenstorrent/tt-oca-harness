# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Walking-one / walking-zero sweep of the eFuse shim bank-init-time field.

``EFUSE_BANK_INIT_TIME.init_time`` is the only register in the eFuse shim CSR
window (``hw/ip/efuse/dv/models/regs/gen/py/efuse_shim_ctrl_reg.py``), reached
through arm 1 of ``u_efuse_shim_demux``. Its 32-bit value is the load input of
both ``prim_count`` instances in ``efuse_interface_shim``
(``prim_count_r`` and ``prim_count_w``, ``set_cnt_i``), which reload it in
every idle cycle and count it down at the start of each bank access. The whole
suite leaves it at its 0x20 reset, so the field and both counters have only
ever held one value.

The sweep writes each walking-one and walking-zero pattern and reads it back,
which moves every bit of the CSR storage and of the counter load input. A
bank access is then issued for the small values only: ``init_time`` is the
number of cycles a read stalls before the APB phase, so a pattern with a high
bit set would hold the read FSM for longer than any run. The default is
restored at the end so the register is not left with a long init time.

``+skip_fuse_sense``: the sweep needs no sensed data.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from sep_reg_meta import sym

from seq_lib.sep_cov_efuse_iface_seq import SepCovEfuseIface, cov_master

EFUSE_BANK_INIT_TIME = sym("SEP_EXTERNAL_EFUSE_SHIM_CTRL_REG_MAP_BASE_ADDR")

# efuse_shim_ctrl.rdl reset for init_time, restored at the end of the sweep.
INIT_TIME_RESET = 0x20

# Above this an eFuse bank access stalls for more cycles than the leaf has, so
# the counter is loaded but not counted down for those patterns. 1024 cycles is
# a few microseconds at the system clock and still 32x the reset value.
MAX_COUNTDOWN_VALUE = 1024

# Bound on one shim CSR access, so a wedged window reports instead of hanging.
_ACCESS_TIMEOUT_NS = 20_000

# Word 0 of the OTP array. The read is there to make the counter load and
# count; which word it reads does not matter and its data is not compared.
PROBE_BIT_ADDR = 0


@pyuvm.test()
class sep_cov_efuse_shim_init_time_sweep_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more."""

    stimulus_only = True

    async def _shim_write(self, value: int) -> None:
        await self._master.write_bytes_result(
            EFUSE_BANK_INIT_TIME,
            value.to_bytes(4, "little"),
            size=2,
            check_response=False,
            timeout_ns=_ACCESS_TIMEOUT_NS,
            allow_timeout=True,
        )

    async def _shim_read(self) -> None:
        await self._master.read_bytes_result(
            EFUSE_BANK_INIT_TIME,
            4,
            size=2,
            check_response=False,
            timeout_ns=_ACCESS_TIMEOUT_NS,
            allow_timeout=True,
        )

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        # The shim window holds an adopter-owned register, so its response is
        # not the value scoreboard's to grade; the access goes to the VIP
        # master directly.
        self._master = cov_master(self, "s_axi")
        if self._master is None:
            raise AssertionError(
                "no VIP master behind env.axi_agent.driver; the shim CSR sweep "
                "cannot reach the init-time register"
            )
        efuse = SepCovEfuseIface(self)

        patterns = [1 << b for b in range(32)]
        patterns += [(~(1 << b)) & 0xFFFF_FFFF for b in range(32)]
        countdown = 0
        for value in patterns:
            await self._shim_write(value)
            await self._shim_read()
            if value <= MAX_COUNTDOWN_VALUE:
                # Small enough for the loaded counter to reach zero inside the
                # command poll, so the decrement path runs as well as the load.
                await efuse.read(PROBE_BIT_ADDR)
                countdown += 1

        await self._shim_write(INIT_TIME_RESET)
        await self._shim_read()
        await efuse.read(PROBE_BIT_ADDR)
        self.logger.info(
            "[cov] init_time sweep done: %d patterns written and read back, "
            "%d of them followed by a bank read, reset value 0x%x restored",
            len(patterns),
            countdown,
            INIT_TIME_RESET,
        )
