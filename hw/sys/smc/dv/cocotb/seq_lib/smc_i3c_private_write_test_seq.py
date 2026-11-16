# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A private write queued on I3C0 and I3C1 with no target to answer it.

An I3C controller with `HC_CONTROL.BUS_ENABLE` set but no command queued never
drives its bus. This leaf brings I3C0 and I3C1 up as the active controller the
way the OCCP controller firmware does -- bus enabled in PIO mode,
`STBY_CR_CONTROL.STBY_CR_ENABLE_INIT` at the active-controller value, open-drain
bus timing, queue thresholds and the PIO queues enabled -- with `T_IDLE`
shortened so the bus is available within the leg, programs DAT entry 0 with
address 0x50 (`DAT_structure.rdl`: `STATIC_ADDRESS`, `DYNAMIC_ADDRESS`) and
queues one Immediate Data Transfer of one byte to that entry.

The command descriptor the PIO `COMMAND_PORT` takes is the HCI one, carried
here as the sequence's own field table (`CMD_ATTR`, `TID`, `DEV_INDEX`,
`DTT`, `WROC`, `TOC`); the DV OCCP controller driver
`hw/sys/smc/dv/fw/common/occp/i3c_controller_driver.c` carries the same bit
layout in its own descriptor macros.

Nothing on the single build answers that address, so the header is not
acknowledged. The response descriptor's `ERR_STATUS` reports an address NACK
as 0x5 and its `TID` echoes the command's. On I3C0 the bench also sees the
pad: the controller has to drive SDA low at least once during the transfer.

The I3C0 leg also samples the wrapper's pad-enable gates on every peripheral
clock. `hw/ip/i3ccore_wrap/doc/index.adoc` states that the wrapper turns the
core's bus levels into open-drain pad enables: SCL is driven only low (`scl_o`
tied low, `scl_oe_o` the inverse of the core's SCL level) and SDA is driven in
both directions while push-pull mode is selected (`sda_oe_o` is `sel_od_pp_o`
OR the inverse of `sda_o`). The SCL output enable must never be seen with the
SCL output level high while the controller pulls SCL low at least once, and
the SDA output enable must equal that OR on every sample.
"""

from __future__ import annotations

import re

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from .smc_addr_map import _REPO, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i3c_irq_route_test_seq import i3c_field_masks
from .smc_i3c_to_fabric_test_seq import (
    HC_CONTROL_OFFSET,
    I3C_HC_CONTROL_ENABLED,
    I3C_HC_CONTROL_RESET,
)

_PIO_INTR_STATUS = i3c_field_masks("pio_registers.rdl", "PIO_INTR_STATUS")
_PIO_INTR_STATUS_ENABLE = i3c_field_masks("pio_registers.rdl", "PIO_INTR_STATUS_ENABLE")
_PIO_CONTROL = i3c_field_masks("pio_registers.rdl", "PIO_CONTROL")
_QUEUE_THLD_CTRL = i3c_field_masks("pio_registers.rdl", "QUEUE_THLD_CTRL")
_STBY_CR_CONTROL = i3c_field_masks("standby_controller_mode.rdl", "STBY_CR_CONTROL")


def _lsb(mask: int) -> int:
    return mask & -mask


#: PIO_INTR_STATUS.RESP_READY_STAT (pio_registers.rdl).
RESP_READY = _PIO_INTR_STATUS["RESP_READY_STAT"]
#: PIO_INTR_STATUS_ENABLE: TX/RX threshold, command queue ready, response ready.
PIO_STATUS_ENABLE = (
    _PIO_INTR_STATUS_ENABLE["TX_THLD_STAT_EN"]
    | _PIO_INTR_STATUS_ENABLE["RX_THLD_STAT_EN"]
    | _PIO_INTR_STATUS_ENABLE["CMD_QUEUE_READY_STAT_EN"]
    | _PIO_INTR_STATUS_ENABLE["RESP_READY_STAT_EN"]
)
#: PIO_CONTROL: ENABLE and RS.
PIO_RUN = _PIO_CONTROL["ENABLE"] | _PIO_CONTROL["RS"]
#: QUEUE_THLD_CTRL: command-empty threshold 1, response-buffer threshold 1.
QUEUE_THRESHOLDS = _lsb(_QUEUE_THLD_CTRL["CMD_EMPTY_BUF_THLD"]) | _lsb(
    _QUEUE_THLD_CTRL["RESP_BUF_THLD"]
)
#: STBY_CR_CONTROL.STBY_CR_ENABLE_INIT: ACM_INIT (2'b01) initializes in Active
#: Controller mode (standby_controller_mode.rdl).
STBY_ENABLE_INIT_MASK = _STBY_CR_CONTROL["STBY_CR_ENABLE_INIT"]
STBY_ACM_INIT = 1
STBY_ACTIVE_CONTROLLER = STBY_ACM_INIT * _lsb(STBY_ENABLE_INIT_MASK)
#: HCI command descriptor, DWORD0: CMD_ATTR[2:0], TID[6:3], DEV_INDEX[20:16],
#: DTT[25:23] (immediate byte count), WROC[30], TOC[31]; DWORD1 carries the
#: immediate data bytes.
CMD_ATTR_IMMEDIATE = 0x1
CMD_TID_SHIFT = 3
CMD_DEV_INDEX_SHIFT = 16
CMD_DTT_SHIFT = 23
CMD_WROC = 1 << 30
CMD_TOC = 1 << 31
#: HCI response descriptor: ERR_STATUS[31:28], TID[27:24]; 0x5 is an address NACK.
RESP_ERR_SHIFT = 28
RESP_TID_SHIFT = 24
ERR_NACK = 0x5
#: The DAT entry the write addresses; its field positions come from the I3C
#: core's DAT_structure.rdl.
DAT_ENTRY = 0
_DAT_RDL = (
    _REPO
    / "vendor"
    / "chipsalliance"
    / "i3c-core"
    / "upstream"
    / "src"
    / "rdl"
    / "DAT_structure.rdl"
)
_DAT_FIELD_RE = re.compile(r"\}\s*(\w+)\s*\[(\d+):(\d+)\]\s*;")
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


def _dat_lsb(field: str) -> int:
    for name, _msb, lsb in _DAT_FIELD_RE.findall(_DAT_RDL.read_text(encoding="utf-8")):
        if name == field:
            return int(lsb)
    raise KeyError(f"{field} is not a field of {_DAT_RDL}")


DAT_STATIC_ADDRESS_SHIFT = _dat_lsb("STATIC_ADDRESS")
DAT_DYNAMIC_ADDRESS_SHIFT = _dat_lsb("DYNAMIC_ADDRESS")
DAT_ENTRY_LO = (TARGET_ADDR << DAT_STATIC_ADDRESS_SHIFT) | (
    TARGET_ADDR << DAT_DYNAMIC_ADDRESS_SHIFT
)


def _dat(inst: int, word: int) -> int:
    """Address of 32-bit ``word`` of DAT entry ``DAT_ENTRY`` on instance ``inst``."""
    return (
        smc_indexed_addr("SMC_TOP_OCA_I3C_WRAP_I3C_CSR_DAT_BASE_ADDR", inst)
        + 8 * DAT_ENTRY
        + 4 * word
    )


def _pio(name: str, inst: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_OCA_I3C_WRAP_I3C_CSR_PIOCONTROL_{name}_BASE_ADDR", inst)


def _ec(name: str, inst: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_OCA_I3C_WRAP_I3C_CSR_I3C_EC_{name}_BASE_ADDR", inst)


def _hc_control(inst: int) -> int:
    return smc_indexed_addr("SMC_TOP_OCA_I3C_WRAP_I3C_CSR_BASE_ADDR", inst) + HC_CONTROL_OFFSET


def _immediate_write(dev_index: int, tid: int, data: int) -> tuple[int, int]:
    """HCI Immediate Data Transfer of one byte to the target DAT entry ``dev_index`` names."""
    dword0 = (
        CMD_ATTR_IMMEDIATE
        | (tid << CMD_TID_SHIFT)
        | (dev_index << CMD_DEV_INDEX_SHIFT)
        | (1 << CMD_DTT_SHIFT)
        | CMD_WROC
        | CMD_TOC
    )
    return dword0, data & 0xFF


class smc_i3c_private_write_test_seq(SmcCsrSeq):
    """Queue one private write on I3C0 and I3C1 and read back its response."""

    def __init__(self, name: str = "smc_i3c_private_write_test_seq") -> None:
        super().__init__(name)
        self.responses: dict[int, int] = {}
        self.sda_low_cycles = 0
        self.scl_low_cycles = 0
        self.scl_high_drive_cycles = 0
        self.sda_gate_mismatches = 0
        self.pp_cycles = 0
        self.samples = 0

    @staticmethod
    def _bit(handle) -> int:
        value = handle.value
        assert value.is_resolvable, f"{handle._name} is not resolvable: {value}"
        return int(value)

    async def _sample_pads(self, stop: list[bool]) -> None:
        dut = cocotb.top
        while not stop[0]:
            await RisingEdge(dut.clk_periph_i)
            self.samples += 1
            self.sda_low_cycles += self._bit(dut.tb_i3c0_sda_dut_low)
            self.scl_low_cycles += self._bit(dut.tb_i3c0_scl_dut_low)
            self.scl_high_drive_cycles += self._bit(dut.tb_i3c0_scl_drive_high)
            pp = self._bit(dut.tb_i3c0_sda_pp_sel)
            self.pp_cycles += pp
            if self._bit(dut.tb_i3c0_sda_oe) != (pp | (1 - self._bit(dut.tb_i3c0_sda_out))):
                self.sda_gate_mismatches += 1

    async def _leg(self, inst: int) -> int:
        label = f"I3C{inst}"
        await self.csr_read(f"{label}_HC", _hc_control(inst), expected=I3C_HC_CONTROL_RESET)
        stby_reg = _ec("STDBYCTRLMODE_STBY_CR_CONTROL", inst)
        stby = await self.csr_read(f"{label}_STBY", stby_reg)
        pio_ctrl = await self.csr_read(f"{label}_PIO_CTRL_IDLE", _pio("PIO_CONTROL", inst))
        await self.csr_write(f"{label}_BUS_EN", _hc_control(inst), I3C_HC_CONTROL_ENABLED)
        stby_acm = (stby & ~STBY_ENABLE_INIT_MASK) | STBY_ACTIVE_CONTROLLER
        await self.csr_write(f"{label}_STBY_ACM", stby_reg, stby_acm)
        stby_rb = await self.csr_read(f"{label}_STBY_ACM_RB", stby_reg)
        assert stby_rb & STBY_ENABLE_INIT_MASK == STBY_ACTIVE_CONTROLLER, (
            f"{label}: STBY_CR_CONTROL reads 0x{stby_rb:08x} after STBY_CR_ENABLE_INIT was "
            f"written ACM_INIT (0x{stby_acm:08x}); the register's hardware-written fields are "
            f"not compared"
        )
        for name, value in TIMING:
            await self.csr_write(f"{label}_{name}", _ec(f"SOCMGMTIF_{name}", inst), value)
        await self.csr_write(f"{label}_QTC", _pio("QUEUE_THLD_CTRL", inst), QUEUE_THRESHOLDS)
        await self.csr_write(
            f"{label}_PIO_SE", _pio("PIO_INTR_STATUS_ENABLE", inst), PIO_STATUS_ENABLE
        )
        await self.csr_write(f"{label}_PIO_RUN", _pio("PIO_CONTROL", inst), PIO_RUN)
        await self.csr_write(f"{label}_DAT0_LO", _dat(inst, 0), DAT_ENTRY_LO)
        await self.csr_write(f"{label}_DAT0_HI", _dat(inst, 1), 0)
        await self.csr_read(f"{label}_DAT0_LO_RB", _dat(inst, 0), expected=DAT_ENTRY_LO)

        tid = inst + 1
        dword0, dword1 = _immediate_write(DAT_ENTRY, tid, DATA_BYTE)
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
        err, resp_tid = (resp >> RESP_ERR_SHIFT) & 0xF, (resp >> RESP_TID_SHIFT) & 0xF
        assert (err, resp_tid) == (ERR_NACK, tid), (
            f"{label}: response 0x{resp:08x} carries error status 0x{err:x} and TID {resp_tid}; "
            f"a write to an unanswered address reports NACK (0x{ERR_NACK:x}) with TID {tid}"
        )
        await self.csr_write(f"{label}_DAT0_LO_CLR", _dat(inst, 0), 0)
        await self.csr_read(f"{label}_DAT0_LO_CLR_RB", _dat(inst, 0), expected=0)
        await self.csr_write(f"{label}_PIO_RESTORE", _pio("PIO_CONTROL", inst), pio_ctrl)
        await self.csr_write(f"{label}_BUS_OFF", _hc_control(inst), I3C_HC_CONTROL_RESET)
        await self.csr_write(f"{label}_STBY_RESTORE", stby_reg, stby)
        return resp

    async def body(self) -> None:
        stop = [False]
        sampler = cocotb.start_soon(self._sample_pads(stop))
        self.responses[0] = await self._leg(0)
        stop[0] = True
        await sampler
        assert self.sda_low_cycles > 0, (
            "I3C0 answered a queued private write without its controller ever driving SDA low"
        )
        assert self.scl_low_cycles > 0, (
            "I3C0 answered a queued private write without its controller ever driving SCL low"
        )
        assert self.scl_high_drive_cycles == 0, (
            f"I3C0 asserted its SCL output enable with the SCL output level high on "
            f"{self.scl_high_drive_cycles} of {self.samples} peripheral clocks; the wrapper ties "
            f"scl_o low and drives SCL only low"
        )
        assert self.sda_gate_mismatches == 0, (
            f"I3C0's SDA output enable differed from (push-pull select OR NOT sda_o) on "
            f"{self.sda_gate_mismatches} of {self.samples} peripheral clocks"
        )
        cocotb.log.info(
            "CHK-I3C-SCL-OD-ONLY: over %d peripheral clocks of the I3C0 private write the "
            "controller pulled SCL low on %d and SDA low on %d, the SCL output enable was never "
            "asserted with the SCL output level high (%d samples), and the SDA output enable "
            "equalled push-pull-select OR NOT sda_o on every sample (push-pull selected on %d "
            "samples)",
            self.samples,
            self.scl_low_cycles,
            self.sda_low_cycles,
            self.scl_high_drive_cycles,
            self.pp_cycles,
        )
        self.responses[1] = await self._leg(1)
        cocotb.log.info(
            "CHK-I3C-PRIVATE-WRITE: a one-byte immediate private write to unanswered address "
            "0x%02x (DAT entry 0), "
            "queued on I3C0 and I3C1 as the active controller, came back as NACK with its own "
            "TID on both (responses 0x%08x, 0x%08x); the I3C0 controller drove SDA low on %d "
            "peripheral clocks",
            TARGET_ADDR,
            self.responses[0],
            self.responses[1],
            self.sda_low_cycles,
        )
