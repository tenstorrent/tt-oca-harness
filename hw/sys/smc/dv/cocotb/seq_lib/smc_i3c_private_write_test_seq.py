# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A private write queued on I3C0 and I3C1 with no target to answer it.

The other single-build I3C leaves read the CSR window and set
`HC_CONTROL.BUS_ENABLE`, but none queues a command, so the I3C0 and I3C1
controllers never drive their buses. This leaf brings each up as the active
controller the way the OCCP controller firmware does -- bus enabled in PIO
mode, `STBY_CR_CONTROL.STBY_CR_ENABLE_INIT` at the active-controller value,
open-drain bus timing, queue thresholds and the PIO queues enabled -- with
`T_IDLE` shortened so the bus is available within the leg, and queues one
immediate private write of one byte to static address 0x50.

Nothing on the single build answers that address, so the header is not
acknowledged. The TCRI response descriptor (6.4.1 Table 1) reports an address
NACK as error status 0x5, and the descriptor must echo the command's
transaction ID. On I3C0 the bench also sees the pad: the controller has to
drive SDA low at least once during the transfer.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from .smc_addr_map import smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i3c_to_fabric_test_seq import (
    HC_CONTROL_OFFSET,
    I3C_HC_CONTROL_ENABLED,
    I3C_HC_CONTROL_RESET,
)

#: PIO_INTR_STATUS.RESP_READY_STAT (pio_registers.rdl).
RESP_READY = 1 << 4
#: PIO_INTR_STATUS_ENABLE: TX/RX threshold, command queue ready, response ready.
PIO_STATUS_ENABLE = 0x1B
#: PIO_CONTROL: ENABLE and RS.
PIO_RUN = 0x3
#: QUEUE_THLD_CTRL: command-empty threshold 1, response-buffer threshold 1.
QUEUE_THRESHOLDS = (1 << 8) | 1
#: STBY_CR_CONTROL.STBY_CR_ENABLE_INIT[31:30]: 3 is the active controller.
STBY_ENABLE_INIT_MASK = 3 << 30
STBY_ACTIVE_CONTROLLER = 3 << 30
#: TCRI response error status for a NACKed address.
ERR_NACK = 0x5
TARGET_ADDR = 0x50
DATA_BYTE = 0xA5
POLL_LIMIT = 400
POLL_CYCLES = 50

#: Open-drain bus timing in core clocks, the set the OCCP controller firmware
#: programs, with T_IDLE shortened so the bus is available within the leg.
TIMING = (
    ("T_R_REG", 0),
    ("T_F_REG", 0),
    ("T_SU_DAT_REG", 2),
    ("T_HD_DAT_REG", 2),
    ("T_HIGH_REG", 14),
    ("T_HIGH_OD_REG", 8),
    ("T_HIGH_INIT_OD_REG", 8),
    ("T_LOW_REG", 14),
    ("T_LOW_OD_REG", 8),
    ("T_HD_STA_REG", 13),
    ("T_SU_STA_REG", 9),
    ("T_SU_STO_REG", 8),
    ("T_HD_RSTA_REG", 9),
    ("T_DS_OD_REG", 24),
    ("T_FREE_REG", 13),
    ("T_AVAL_REG", 40),
    ("T_IDLE_REG", 200),
)


def _pio(name: str, inst: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_OCA_I3C_WRAP_I3C_CSR_PIOCONTROL_{name}_BASE_ADDR", inst)


def _ec(name: str, inst: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_OCA_I3C_WRAP_I3C_CSR_I3C_EC_{name}_BASE_ADDR", inst)


def _hc_control(inst: int) -> int:
    return smc_indexed_addr("SMC_TOP_OCA_I3C_WRAP_I3C_CSR_BASE_ADDR", inst) + HC_CONTROL_OFFSET


def _immediate_write(addr: int, tid: int, data: int) -> tuple[int, int]:
    """Immediate Data Transfer, direct addressing (i3c_pkg.sv, TCRI 7.2.2.1)."""
    attr = 0x5
    dtt = 1
    wroc = 1 << 30
    toc = 1 << 31
    dword0 = attr | (tid << 3) | (addr << 16) | (dtt << 23) | wroc | toc
    return dword0, data & 0xFF


class smc_i3c_private_write_test_seq(SmcCsrSeq):
    """Queue one private write on I3C0 and I3C1 and read back its response."""

    def __init__(self, name: str = "smc_i3c_private_write_test_seq") -> None:
        super().__init__(name)
        self.responses: dict[int, int] = {}
        self.sda_low_cycles = 0

    async def _count_sda_low(self, stop: list[bool]) -> None:
        dut = cocotb.top
        while not stop[0]:
            await RisingEdge(dut.clk_periph_i)
            if dut.tb_i3c0_sda_dut_low.value.is_resolvable and int(dut.tb_i3c0_sda_dut_low.value):
                self.sda_low_cycles += 1

    async def _leg(self, inst: int) -> int:
        label = f"I3C{inst}"
        await self.csr_read(f"{label}_HC", _hc_control(inst), expected=I3C_HC_CONTROL_RESET)
        stby_reg = _ec("STDBYCTRLMODE_STBY_CR_CONTROL", inst)
        stby = await self.csr_read(f"{label}_STBY", stby_reg)
        pio_ctrl = await self.csr_read(f"{label}_PIO_CTRL_IDLE", _pio("PIO_CONTROL", inst))
        await self.csr_write(f"{label}_BUS_EN", _hc_control(inst), I3C_HC_CONTROL_ENABLED)
        await self.csr_write(
            f"{label}_STBY_ACM", stby_reg, (stby & ~STBY_ENABLE_INIT_MASK) | STBY_ACTIVE_CONTROLLER
        )
        for name, value in TIMING:
            await self.csr_write(f"{label}_{name}", _ec(f"SOCMGMTIF_{name}", inst), value)
        await self.csr_write(f"{label}_QTC", _pio("QUEUE_THLD_CTRL", inst), QUEUE_THRESHOLDS)
        await self.csr_write(
            f"{label}_PIO_SE", _pio("PIO_INTR_STATUS_ENABLE", inst), PIO_STATUS_ENABLE
        )
        await self.csr_write(f"{label}_PIO_RUN", _pio("PIO_CONTROL", inst), PIO_RUN)

        tid = inst + 1
        dword0, dword1 = _immediate_write(TARGET_ADDR, tid, DATA_BYTE)
        await self.csr_write(f"{label}_CMD0", _pio("COMMAND_PORT", inst), dword0)
        await self.csr_write(f"{label}_CMD1", _pio("COMMAND_PORT", inst), dword1)
        status = 0
        for _ in range(POLL_LIMIT):
            status = await self.csr_read(f"{label}_PIO_INTR", _pio("PIO_INTR_STATUS", inst))
            if status & RESP_READY:
                break
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        assert status & RESP_READY, (
            f"{label}: PIO_INTR_STATUS=0x{status:08x}; no response to a queued private write"
        )
        resp = await self.csr_read(f"{label}_RESP", _pio("RESPONSE_PORT", inst))
        err, resp_tid = (resp >> 28) & 0xF, (resp >> 24) & 0xF
        assert (err, resp_tid) == (ERR_NACK, tid), (
            f"{label}: response 0x{resp:08x} carries error status 0x{err:x} and TID {resp_tid}; "
            f"a write to an unanswered address reports NACK (0x{ERR_NACK:x}) with TID {tid}"
        )
        await self.csr_write(f"{label}_PIO_RESTORE", _pio("PIO_CONTROL", inst), pio_ctrl)
        await self.csr_write(f"{label}_BUS_OFF", _hc_control(inst), I3C_HC_CONTROL_RESET)
        await self.csr_write(f"{label}_STBY_RESTORE", stby_reg, stby)
        return resp

    async def body(self) -> None:
        stop = [False]
        counter = cocotb.start_soon(self._count_sda_low(stop))
        self.responses[0] = await self._leg(0)
        stop[0] = True
        await counter
        assert self.sda_low_cycles > 0, (
            "I3C0 answered a queued private write without its controller ever driving SDA low"
        )
        self.responses[1] = await self._leg(1)
        cocotb.log.info(
            "CHK-I3C-PRIVATE-WRITE: a one-byte private write to unanswered address 0x%02x, "
            "queued on I3C0 and I3C1 as the active controller, came back as NACK with its own "
            "TID on both (responses 0x%08x, 0x%08x); the I3C0 controller drove SDA low on %d "
            "peripheral clocks",
            TARGET_ADDR,
            self.responses[0],
            self.responses[1],
            self.sda_low_cycles,
        )
