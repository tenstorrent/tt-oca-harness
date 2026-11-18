# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Each I3C instance's interrupt reaches its own peripheral-interrupt bit.

`hw/ip/i3ccore_wrap/doc/index.adoc` states that the six instances' interrupts
reach peripheral interrupts 12 to 17, and `smc_peripherals.sv` places
`i3c_irqs_smc_clk` on `peripheral_interrupts_o[17:12]`. The bench lifts that
slice as `tb_i3c_irq`.

The core's controller interrupt is the PIO interrupt: each `PIO_INTR_STATUS`
bit takes its next value while its `PIO_INTR_STATUS_ENABLE` bit is set and
raises the line while its `PIO_INTR_SIGNAL_ENABLE` bit is set, and the
matching `PIO_INTR_FORCE` bit forces that interrupt (`pio_registers.rdl`), so
a force raises the status and the line without bus traffic. On each instance
in turn the leaf enables the response-ready status
and signal, writes `RESP_READY_FORCE`, requires `RESP_READY_STAT` to read 1 and
`tb_i3c_irq` to read exactly the instance's own bit within the poll bound, then
clears the force and requires the status and every bit low again. The response
queue is empty throughout, so nothing but the force sets the bit. The other
five instances stay at reset while one is driven, so a line that follows the
wrong instance, or two lines that move together, fails the one-hot compare.
"""

from __future__ import annotations

import re

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i3c_to_fabric_test_seq import _I3C_BASE_RDL, _RDL_FIELD_RE

_I3C_RDL_DIR = _I3C_BASE_RDL.parent
#: A register's closing brace and name, with or without an address.
_RDL_REG_END_ANY_RE = re.compile(r"\}\s*(\w+)\s*(?:@\s*0x[0-9A-Fa-f]+\s*)?;")


def i3c_field_masks(rdl_name: str, reg_name: str) -> dict[str, int]:
    """Return ``{field: bitmask}`` of ``reg_name`` from the vendor RDL file ``rdl_name``."""
    path = _I3C_RDL_DIR / rdl_name
    text = path.read_text(encoding="utf-8")
    for match in _RDL_REG_END_ANY_RE.finditer(text):
        if match.group(1) != reg_name:
            continue
        body_start = text.rfind("reg {", 0, match.start())
        assert body_start >= 0, f"{reg_name} in {path} has no reg body"
        masks = {
            field.group("name"): ((1 << (int(field.group("hi")) - int(field.group("lo")) + 1)) - 1)
            << int(field.group("lo"))
            for field in _RDL_FIELD_RE.finditer(text[body_start : match.start()])
        }
        assert masks, f"no fields parsed for {reg_name} in {path}"
        return masks
    raise RuntimeError(f"register {reg_name} not found in {path}")


#: The response-ready interrupt in each of the four PIO interrupt registers
#: (pio_registers.rdl).
RESP_READY_STAT = i3c_field_masks("pio_registers.rdl", "PIO_INTR_STATUS")["RESP_READY_STAT"]
RESP_READY_STAT_EN = i3c_field_masks("pio_registers.rdl", "PIO_INTR_STATUS_ENABLE")[
    "RESP_READY_STAT_EN"
]
RESP_READY_SIGNAL_EN = i3c_field_masks("pio_registers.rdl", "PIO_INTR_SIGNAL_ENABLE")[
    "RESP_READY_SIGNAL_EN"
]
RESP_READY_FORCE = i3c_field_masks("pio_registers.rdl", "PIO_INTR_FORCE")["RESP_READY_FORCE"]
NUM_I3C = smc_addr("SMC_TOP_OCA_I3C_WRAP_I3C_CSR_NUM")
POLL_LIMIT = 50
POLL_CYCLES = 20


def _pio(name: str, inst: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_OCA_I3C_WRAP_I3C_CSR_PIOCONTROL_{name}_BASE_ADDR", inst)


class smc_i3c_irq_route_test_seq(SmcCsrSeq):
    """Force the PIO response-ready interrupt on each instance and watch the PLIC lines."""

    def __init__(self, name: str = "smc_i3c_irq_route_test_seq") -> None:
        super().__init__(name)
        self.routed: list[int] = []

    @staticmethod
    def _lines() -> int:
        value = cocotb.top.tb_i3c_irq.value
        assert value.is_resolvable, f"tb_i3c_irq is not resolvable: {value}"
        return int(value)

    async def _wait_lines(self, label: str, want: int) -> int:
        lines = -1
        for _ in range(POLL_LIMIT):
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
            lines = self._lines()
            if lines == want:
                return lines
        raise AssertionError(
            f"{label}: tb_i3c_irq reads 0b{lines:06b} after {POLL_LIMIT * POLL_CYCLES} clk_smc_i "
            f"cycles, expected 0b{want:06b}"
        )

    async def _leg(self, inst: int) -> None:
        label = f"I3C{inst}"
        quiet = self._lines()
        assert quiet == 0, f"{label}: tb_i3c_irq reads 0b{quiet:06b} before any force"
        status = await self.csr_read(f"{label}_PIO_INTR_IDLE", _pio("PIO_INTR_STATUS", inst))
        assert status & RESP_READY_STAT == 0, (
            f"{label}: PIO_INTR_STATUS=0x{status:08x} reports a response before any force"
        )
        await self.csr_write(
            f"{label}_PIO_SE", _pio("PIO_INTR_STATUS_ENABLE", inst), RESP_READY_STAT_EN
        )
        await self.csr_write(
            f"{label}_PIO_SIG", _pio("PIO_INTR_SIGNAL_ENABLE", inst), RESP_READY_SIGNAL_EN
        )
        await self.csr_write(f"{label}_PIO_FORCE", _pio("PIO_INTR_FORCE", inst), RESP_READY_FORCE)
        status = await self.csr_read(f"{label}_PIO_INTR_FORCED", _pio("PIO_INTR_STATUS", inst))
        assert status & RESP_READY_STAT, (
            f"{label}: PIO_INTR_STATUS=0x{status:08x} after RESP_READY_FORCE with the status "
            f"enable set; the force is ORed into the status"
        )
        await self._wait_lines(f"{label}_FORCED", 1 << inst)
        await self.csr_write(f"{label}_PIO_RELEASE", _pio("PIO_INTR_FORCE", inst), 0)
        status = await self.csr_read(f"{label}_PIO_INTR_RELEASED", _pio("PIO_INTR_STATUS", inst))
        assert status & RESP_READY_STAT == 0, (
            f"{label}: PIO_INTR_STATUS=0x{status:08x} keeps the response-ready bit after the "
            f"force is cleared with the response queue empty"
        )
        await self._wait_lines(f"{label}_RELEASED", 0)
        await self.csr_write(f"{label}_PIO_SIG_OFF", _pio("PIO_INTR_SIGNAL_ENABLE", inst), 0)
        await self.csr_write(f"{label}_PIO_SE_OFF", _pio("PIO_INTR_STATUS_ENABLE", inst), 0)
        self.routed.append(inst)
        cocotb.log.info(
            "CHK-I3C-IRQ-ROUTE: I3C%d PIO_INTR_FORCE.RESP_READY_FORCE with the status and signal "
            "enables set raised PIO_INTR_STATUS.RESP_READY_STAT and tb_i3c_irq read exactly "
            "0b%s (peripheral interrupt %d) within %d clk_smc_i cycles, and clearing the force "
            "dropped the status and every line",
            inst,
            f"{1 << inst:06b}",
            12 + inst,
            POLL_LIMIT * POLL_CYCLES,
        )

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        for inst in range(NUM_I3C):
            await self._leg(inst)
