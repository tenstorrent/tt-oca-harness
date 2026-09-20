# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Non-grading frontdoor driver for the eFuse interface-controller CSRs.

The eFuse sequences already in ``seq_lib`` grade what they drive:
``sep_efuse_otp_program_seq`` requires a program to succeed (or to fail with
``PROGRAM_ERR``), and ``sep_efuse_direct_read_seq`` asserts ``read_status`` is
clear. The ``sep_cov_efuse_*`` stimulus leaves reach arms whose outcome is an
error by construction -- a go with the enable clear, a request timeout, a
read-locked field -- so they need the same register discipline without the
expectation attached.

This driver keeps the discipline and drops the grading:

* ``program_enable`` / ``read_enable`` are cleared after every command, because
  an enable left asserted starves the shared eFuse command channel and the next
  command never completes.
* every poll is bounded, so a command that never signals done reports and
  returns instead of hanging the leaf.
* the AXI response is still required to be OKAY. A CSR access that does not
  retire is a bus error, which is the one failure a stimulus-only leaf keeps.

Nothing here compares a read value against an expectation.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from sep_reg_meta import EFUSE_INTERFACE_CTRL

from seq_lib.sep_axi_reg_driver import SepAxiRegDriver

EFUSE_PROGRAM_CTRL = EFUSE_INTERFACE_CTRL.addr("EFUSE_PROGRAM_CTRL")
EFUSE_READ_CTRL = EFUSE_INTERFACE_CTRL.addr("EFUSE_READ_CTRL")
EFUSE_READ_DATA = EFUSE_INTERFACE_CTRL.addr("EFUSE_READ_INTERFACE_READ_DATA")
EFUSE_PROGRAM_READ_DATA = EFUSE_INTERFACE_CTRL.addr("EFUSE_PROGRAM_INTERFACE_READ_DATA")
EFUSE_IFACE_STATUS = EFUSE_INTERFACE_CTRL.addr("EFUSE_INTERFACE_CTRL_STATUS")
EFUSE_PROGRAM_REQ_TIMEOUT = EFUSE_INTERFACE_CTRL.addr("EFUSE_PROGRAM_REQ_TIMEOUT")
EFUSE_READ_REQ_TIMEOUT = EFUSE_INTERFACE_CTRL.addr("EFUSE_READ_REQ_TIMEOUT")

_F = EFUSE_INTERFACE_CTRL.field_mask
PROGRAM_DATA_BIT = _F("EFUSE_PROGRAM_CTRL", "efuse_data")
PROGRAM_GO_BIT = _F("EFUSE_PROGRAM_CTRL", "efuse_program_go")
PROGRAM_READ_BACK_BIT = _F("EFUSE_PROGRAM_CTRL", "efuse_program_read_back")
PROGRAM_ENABLE_BIT = _F("EFUSE_PROGRAM_CTRL", "program_enable")
PROGRAM_DONE_BIT = _F("EFUSE_PROGRAM_CTRL", "program_done")
PROGRAM_STATUS_BIT = _F("EFUSE_PROGRAM_CTRL", "program_status")

READ_GO_BIT = _F("EFUSE_READ_CTRL", "efuse_read_go")
READ_ENABLE_BIT = _F("EFUSE_READ_CTRL", "read_enable")
READ_DONE_BIT = _F("EFUSE_READ_CTRL", "read_done")
READ_STATUS_BIT = _F("EFUSE_READ_CTRL", "read_status")

REQ_ERROR_CLEAR = _F("EFUSE_INTERFACE_CTRL_STATUS", "efuse_req_error_clear")
PROGRAM_ADDR_ERROR_CLEAR = _F("EFUSE_INTERFACE_CTRL_STATUS", "efuse_program_addr_error_clear")
READ_ADDR_ERROR_CLEAR = _F("EFUSE_INTERFACE_CTRL_STATUS", "efuse_read_addr_error_clear")

PROGRAM_TIMEOUT_ENABLE = _F("EFUSE_PROGRAM_REQ_TIMEOUT", "program_req_timeout_enable")
PROGRAM_TIMEOUT_CYCLES = _F("EFUSE_PROGRAM_REQ_TIMEOUT", "program_req_timeout_cycles")
READ_TIMEOUT_ENABLE = _F("EFUSE_READ_REQ_TIMEOUT", "read_req_timout_enable")
READ_TIMEOUT_CYCLES = _F("EFUSE_READ_REQ_TIMEOUT", "read_req_timeout_cycles")

ADDR_MASK = 0xFFFF

# Poll bound for one eFuse command. Generous against the bank init time (the
# shim reload default is 32 cycles) and finite, so a command that never
# completes reports rather than hanging the leaf.
_POLL_CYCLES = 400


def cov_master(test, prefix: str = "s_axi"):
    """The VIP master sequence behind one SEP AXI agent, or None.

    Two reasons a coverage leaf reaches for it instead of ``start_seq``:

    * the SEP AXI sequencer retires one item at a time, so nothing overlaps
      through it and a demux' outstanding counters never leave depth one;
    * items driven through the agent are broadcast to the value scoreboard,
      which grades the AXI response. A stimulus leaf that drives an aperture
      whose response is the adopter's business, or a window that closes while
      the access is in flight, has no expectation to declare either way.

    The passive pin monitor still watches the bus, so a DECERR on the CPU-LSU
    bus must still be armed.
    """
    agent = test.env.axi_agent if prefix == "s_axi" else test.env.ext_axi_agent
    return getattr(getattr(agent, "driver", None), "axi", None)


class SepCovEfuseIface(SepAxiRegDriver):
    """eFuse interface-controller CSR access without an expectation attached."""

    _DRIVER_TAG = "COV-EFUSE"

    async def wr(self, addr: int, data: int) -> None:
        """One 32-bit CSR write; the AXI response must be OKAY."""
        await self._wr(addr, data)

    async def rd(self, addr: int) -> int:
        """One 32-bit CSR read; the AXI response must be OKAY."""
        return await self._rd(addr)

    async def clear_errors(self) -> None:
        """W1C the three sticky error flags so the next command is not starved."""
        await self._wr(
            EFUSE_IFACE_STATUS,
            REQ_ERROR_CLEAR | PROGRAM_ADDR_ERROR_CLEAR | READ_ADDR_ERROR_CLEAR,
        )

    async def program(
        self,
        bit_addr: int,
        *,
        data: int = 1,
        enable: bool = True,
        read_back: bool = True,
        go: bool = True,
    ) -> int | None:
        """Drive one EFUSE_PROGRAM_CTRL command and wait for program_done.

        Returns the status word that carried ``program_done``, or None if the
        poll bound expired. Every field is a caller choice, because the arms
        this drives are selected by the illegal-looking combinations
        (``go`` with ``enable`` clear, ``data`` = 0) that the legal ones never
        present.
        """
        wdata = bit_addr & ADDR_MASK
        if data:
            wdata |= PROGRAM_DATA_BIT
        if go:
            wdata |= PROGRAM_GO_BIT
        if read_back:
            wdata |= PROGRAM_READ_BACK_BIT
        if enable:
            wdata |= PROGRAM_ENABLE_BIT
        await self._wr(EFUSE_PROGRAM_CTRL, wdata)
        status = await self._poll(EFUSE_PROGRAM_CTRL, PROGRAM_DONE_BIT, "program")
        # Clear program_enable before any later command, whatever the outcome.
        await self._wr(EFUSE_PROGRAM_CTRL, 0)
        return status

    async def read(self, bit_addr: int, *, enable: bool = True, go: bool = True) -> int | None:
        """Drive one EFUSE_READ_CTRL command and wait for read_done.

        Returns the status word that carried ``read_done``, or None if the poll
        bound expired. The read data register is read on the way out so the
        ``dout`` path is driven; the value is not compared.
        """
        wdata = bit_addr & ADDR_MASK
        if go:
            wdata |= READ_GO_BIT
        if enable:
            wdata |= READ_ENABLE_BIT
        await self._wr(EFUSE_READ_CTRL, wdata)
        status = await self._poll(EFUSE_READ_CTRL, READ_DONE_BIT, "read")
        if status is not None:
            await self._rd(EFUSE_READ_DATA)
        await self._wr(EFUSE_READ_CTRL, 0)
        return status

    async def set_program_timeout(self, cycles: int, *, enable: bool) -> None:
        """Arm or disarm the program request-timeout counter."""
        value = cycles & PROGRAM_TIMEOUT_CYCLES
        if enable:
            value |= PROGRAM_TIMEOUT_ENABLE
        await self._wr(EFUSE_PROGRAM_REQ_TIMEOUT, value)

    async def set_read_timeout(self, cycles: int, *, enable: bool) -> None:
        """Arm or disarm the read request-timeout counter."""
        value = cycles & READ_TIMEOUT_CYCLES
        if enable:
            value |= READ_TIMEOUT_ENABLE
        await self._wr(EFUSE_READ_REQ_TIMEOUT, value)

    async def _poll(self, addr: int, done_bit: int, label: str) -> int | None:
        for _ in range(_POLL_CYCLES):
            await ClockCycles(cocotb.top.clk_i, 1)
            status = await self._rd(addr)
            if status & done_bit:
                return status
        self.log.info(
            "[cov-efuse] %s command did not signal done within %d cycles; "
            "the stimulus moves on",
            label,
            _POLL_CYCLES,
        )
        return None
