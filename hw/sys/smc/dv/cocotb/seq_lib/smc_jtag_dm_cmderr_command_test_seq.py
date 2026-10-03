# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CPU Debug Module: command writes while abstractcs.cmderr is nonzero.

Hard gates, each read back over the DMI:
  * An Access Register command to a running hart ends with busy=0 and
    cmderr=4 (halt/resume), and command reads back the written value.
  * A Quick Access write while cmderr=4 replaces cmderr with 2 (not
    supported) and replaces the stored command.
  * An Access Register write while cmderr=2 leaves cmderr at 2 and busy=0
    (nothing executes) and still replaces the stored command.
  * Writing 1s to abstractcs.cmderr clears it to 0.

The RISC-V debug specification ignores command writes while cmderr is
nonzero; hw/sys/smc/doc/cpu.adoc documents this Debug Module's behaviour.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_cpu_vip_utils import (
    CPU_CTRL_RESET_CTRL,
    CPU_RESET_CTRL_DEBUG_RELEASE,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_jtag_protocol_vip import SmcJtagTap

DMI_DMSTATUS = 0x11
DMI_ABSTRACTCS = 0x16
DMI_COMMAND = 0x17

ABSTRACTCS_CMDERR_SHIFT = 8
ABSTRACTCS_CMDERR_MASK = 0x7
ABSTRACTCS_BUSY = 1 << 12
ABSTRACTCS_CMDERR_W1C = ABSTRACTCS_CMDERR_MASK << ABSTRACTCS_CMDERR_SHIFT

CMDERR_NONE = 0
CMDERR_NOT_SUPPORTED = 2
CMDERR_HALT_RESUME = 4

# Access Register: cmdtype=0, aarsize=3 (64-bit), transfer=1, regno=x0 / x1.
CMD_ACCESS_REG_X0 = 0x0032_1000
CMD_ACCESS_REG_X1 = 0x0032_1001
# Quick Access: cmdtype=1.
CMD_QUICK_ACCESS = 0x0100_0000

_BUSY_POLLS = 16


class smc_jtag_dm_cmderr_command_test_seq(SmcCsrSeq):
    """Drive command writes over the DMI with cmderr clear, 4 and 2."""

    def __init__(self, name: str = "smc_jtag_dm_cmderr_command_test_seq") -> None:
        super().__init__(name)
        self.cmderr_trace: list[int] = []
        self.dm_ok: bool = False
        self._tap: SmcJtagTap | None = None
        self._abits: int = 7
        self._idle: int = 5

    async def _dmi_read(self, addr: int) -> int:
        assert self._tap is not None
        return await self._tap.dmi_read(addr, abits=self._abits, idle=self._idle)

    async def _dmi_write(self, addr: int, data: int) -> None:
        assert self._tap is not None
        await self._tap.dmi_write(addr, data, abits=self._abits, idle=self._idle)

    async def _abstractcs_idle(self) -> int:
        """Return abstractcs once busy reads 0; fail if it never does."""
        abstractcs = 0
        for _ in range(_BUSY_POLLS):
            abstractcs = await self._dmi_read(DMI_ABSTRACTCS)
            if not abstractcs & ABSTRACTCS_BUSY:
                return abstractcs
        raise AssertionError(
            f"abstractcs.busy still set after {_BUSY_POLLS} DMI reads (last 0x{abstractcs:08X})"
        )

    @staticmethod
    def _cmderr(abstractcs: int) -> int:
        return (abstractcs >> ABSTRACTCS_CMDERR_SHIFT) & ABSTRACTCS_CMDERR_MASK

    async def _write_command(self, command: int) -> tuple[int, int]:
        """Write command, wait for idle; return (cmderr, command readback)."""
        await self._dmi_write(DMI_COMMAND, command)
        cmderr = self._cmderr(await self._abstractcs_idle())
        readback = await self._dmi_read(DMI_COMMAND)
        self.cmderr_trace.append(cmderr)
        return cmderr, readback

    async def body(self) -> None:
        await self.csr_write(
            "CPU_CTRL_DEBUG_RESET_RELEASE",
            CPU_CTRL_RESET_CTRL,
            CPU_RESET_CTRL_DEBUG_RELEASE,
            length=8,
        )
        await ClockCycles(cocotb.top.clk_smc_i, 64)
        reset_ctrl = await self.csr_read("CPU_CTRL_RESET_CTRL_RB", CPU_CTRL_RESET_CTRL, length=8)
        assert reset_ctrl & (1 << 24), f"debug_reset_n not set in RESET_CTRL (got 0x{reset_ctrl:X})"

        self._tap = SmcJtagTap(name="smc_jtag_dm_cmderr")
        self._tap.init_signals()
        await self._tap.reset_tap()
        await self._tap.read_idcode(check=True)
        await self._tap.read_dmstatus()
        dtmcs = await self._tap.read_dtmcs()
        self._abits = ((dtmcs >> 4) & 0x3F) or 7
        self._idle = max((dtmcs >> 12) & 0x7, 5)

        await self._dmi_write(DMI_ABSTRACTCS, ABSTRACTCS_CMDERR_W1C)
        start = self._cmderr(await self._abstractcs_idle())
        assert start == CMDERR_NONE, f"cmderr={start} before the first command, expected 0"
        dmstatus = await self._dmi_read(DMI_DMSTATUS)
        assert not dmstatus & (1 << 9), (
            f"dmstatus.anyhalted set (0x{dmstatus:08X}); the halt/resume error needs a running hart"
        )

        cmderr, readback = await self._write_command(CMD_ACCESS_REG_X0)
        assert cmderr == CMDERR_HALT_RESUME, (
            f"Access Register to a running hart left cmderr={cmderr}, expected 4"
        )
        assert readback == CMD_ACCESS_REG_X0, (
            f"command read back 0x{readback:08X}, expected 0x{CMD_ACCESS_REG_X0:08X}"
        )
        cocotb.log.info("CHK-JTAG-DM-CMDERR-HALTRESUME: command=0x%08X cmderr=%d", readback, cmderr)

        cmderr, readback = await self._write_command(CMD_QUICK_ACCESS)
        assert cmderr == CMDERR_NOT_SUPPORTED, (
            f"Quick Access while cmderr=4 left cmderr={cmderr}, expected 2"
        )
        assert readback == CMD_QUICK_ACCESS, (
            f"command read back 0x{readback:08X} after a write while cmderr=4, "
            f"expected 0x{CMD_QUICK_ACCESS:08X}"
        )
        cocotb.log.info("CHK-JTAG-DM-CMDERR-OVERWRITE: command=0x%08X cmderr=%d", readback, cmderr)

        cmderr, readback = await self._write_command(CMD_ACCESS_REG_X1)
        assert cmderr == CMDERR_NOT_SUPPORTED, (
            f"Access Register while cmderr=2 left cmderr={cmderr}, expected 2"
        )
        assert readback == CMD_ACCESS_REG_X1, (
            f"command read back 0x{readback:08X} after a write while cmderr=2, "
            f"expected 0x{CMD_ACCESS_REG_X1:08X}"
        )
        cocotb.log.info("CHK-JTAG-DM-CMDERR-STORE: command=0x%08X cmderr=%d", readback, cmderr)

        await self._dmi_write(DMI_ABSTRACTCS, ABSTRACTCS_CMDERR_W1C)
        cmderr = self._cmderr(await self._abstractcs_idle())
        self.cmderr_trace.append(cmderr)
        assert cmderr == CMDERR_NONE, f"cmderr={cmderr} after writing 1s to it, expected 0"
        cocotb.log.info("CHK-JTAG-DM-CMDERR-CLEAR: cmderr=%d", cmderr)

        self.dm_ok = True
