# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared bench helpers for the Cross Trigger Matrix IP-level cocotb tests.

The bench drives two surfaces of ``cross_trigger_matrix_tb_top``:

* the AXI4-Lite CSR port through the shared AXI VIP's AXI4-Lite master
  (``OcahAxiLiteMasterAgent`` on the flattened ``axil_*`` pins, consumed
  through ``agent.sequence`` only);
* the ``ct_dst`` input vector, with the ``ct_src`` output vector as the
  observable.

The matrix contract (architecture spec): each CT_Src output selects any set
of CT_Dst inputs through its per-port CONFIG_0.CT_DST_SELECT mask and ORs
them together; the output is registered, so a driven input vector appears on
the outputs one clock later. Geometry (port count, select-field width),
register addresses, and reset values all come from the generated RDL header,
so a matrix resize regenerates this bench's expectations.
"""

from __future__ import annotations

import logging
import os

import cocotb
import cross_trigger_matrix_reg as _reg
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge
from ocah_axi_vip import OcahAxiLiteMasterAgent

CLK_PERIOD_NS = 10

# Geometry from the generated register header: one CONFIG_0 register per
# CT_Src port, one select bit per CT_Dst port.
CT_SRC_CONFIG_ADDRS: list[int] = []
while hasattr(_reg, f"CT_SRC_{len(CT_SRC_CONFIG_ADDRS)}__CONFIG_0_REG_ADDR"):
    CT_SRC_CONFIG_ADDRS.append(
        getattr(_reg, f"CT_SRC_{len(CT_SRC_CONFIG_ADDRS)}__CONFIG_0_REG_ADDR")
    )
NUM_CT_SRC = len(CT_SRC_CONFIG_ADDRS)
NUM_CT_DST = next(
    field[2] for field in _reg.CT_SRC_CONFIG_0_reg_t._fields_ if field[0] == "ct_dst_select"
)
SELECT_MASK = (1 << NUM_CT_DST) - 1
CONFIG_DEFAULT = _reg.CT_SRC_CONFIG_0_REG_DEFAULT

# The selector output is registered once; a driven ct_dst vector is visible
# on ct_src one clock later. The observation window adds slack for the
# falling-edge sampling alignment.
PULSE_OBSERVE_WINDOW = 4


def random_seed() -> int:
    """Runner-provided seed (run_dv.py --seed -> RANDOM_SEED); default 1."""
    return int(os.environ.get("RANDOM_SEED", "1"), 0)


def expected_src_vector(masks: list[int], dst_vector: int) -> int:
    """Reference model: bit i of ct_src = OR of the dst bits port i selects."""
    vector = 0
    for port, mask in enumerate(masks):
        if mask & dst_vector:
            vector |= 1 << port
    return vector


class CtmTb:
    """Clock/reset bring-up, register access, and vector-level helpers."""

    def __init__(self, dut, name: str = "ctm_tb") -> None:
        self.dut = dut
        self.log = logging.getLogger(f"cocotb.tb.{name}")
        self.agent = None
        self.seq = None

    async def start(self) -> None:
        """Init inputs, start the clock, run reset, and bring up the VIP."""
        dut = self.dut
        dut.ct_dst.value = 0
        dut.rst_n.value = 0

        cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, "ns").start())

        self.agent = OcahAxiLiteMasterAgent.from_prefix(
            dut,
            "axil",
            dut.clk,
            dut.rst_n,
            name="ctm_axil_host",
            timeout_cycles=1000,
        )
        self.seq = self.agent.sequence
        await self.agent.start()

        await ClockCycles(dut.clk, 5)
        dut.rst_n.value = 1
        await ClockCycles(dut.clk, 5)
        self.log.info(
            "bring-up complete: %dx%d matrix (dst x src), reset released",
            NUM_CT_DST,
            NUM_CT_SRC,
        )

    # ------------------------------------------------------------------
    # Register access
    # ------------------------------------------------------------------

    async def write_select(self, port: int, mask: int) -> None:
        await self.seq.write(CT_SRC_CONFIG_ADDRS[port], mask)

    async def read_select(self, port: int) -> int:
        return await self.seq.read(CT_SRC_CONFIG_ADDRS[port])

    async def clear_all_selects(self) -> None:
        for port in range(NUM_CT_SRC):
            await self.write_select(port, 0)

    async def program_masks(self, masks: list[int], what: str) -> None:
        """Write one select mask per port and log the routing table."""
        for port, mask in enumerate(masks):
            await self.write_select(port, mask)
        self.log.info(
            "%s: programmed %d port masks: %s",
            what,
            len(masks),
            " ".join(f"{mask:07x}" for mask in masks),
        )

    # ------------------------------------------------------------------
    # Vector-level stimulus and observation
    # ------------------------------------------------------------------

    async def drive_dst_steady(self, vector: int, settle_cycles: int = 3) -> None:
        """Drive a ct_dst level and wait for the registered output to settle."""
        await RisingEdge(self.dut.clk)
        self.dut.ct_dst.value = vector
        await ClockCycles(self.dut.clk, settle_cycles)

    def check_src(self, expected: int, what: str) -> None:
        """Compare the current ct_src vector against the reference model."""
        observed = int(self.dut.ct_src.value)
        assert observed == expected, (
            f"{what}: ct_src expected 0x{expected:07x}, observed 0x{observed:07x} "
            f"(diff 0x{(observed ^ expected):07x})"
        )

    async def pulse_and_observe(self, vector: int, what: str) -> tuple[int, int]:
        """Drive a single-cycle ct_dst pulse and watch the output window.

        Returns ``(observed_vector, nonzero_samples)`` where observed_vector
        is the OR of all non-zero falling-edge samples in the window. A clean
        single-cycle input pulse must yield exactly one non-zero sample.
        """
        dut = self.dut
        await RisingEdge(dut.clk)
        dut.ct_dst.value = vector
        await RisingEdge(dut.clk)
        dut.ct_dst.value = 0

        observed = 0
        nonzero_samples = 0
        for _ in range(PULSE_OBSERVE_WINDOW):
            await FallingEdge(dut.clk)
            sample = int(dut.ct_src.value)
            if sample != 0:
                observed |= sample
                nonzero_samples += 1
        self.log.debug(
            "%s: pulse dst=0x%07x -> src=0x%07x (%d non-zero samples)",
            what,
            vector,
            observed,
            nonzero_samples,
        )
        return observed, nonzero_samples

    async def pulse_and_expect(self, vector: int, expected: int, what: str) -> None:
        """Pulse ct_dst and require the modeled one-cycle ct_src response."""
        observed, nonzero_samples = await self.pulse_and_observe(vector, what)
        assert observed == expected, (
            f"{what}: pulse dst=0x{vector:07x}: ct_src expected 0x{expected:07x}, "
            f"observed 0x{observed:07x} (diff 0x{(observed ^ expected):07x})"
        )
        expected_samples = 1 if expected else 0
        assert nonzero_samples == expected_samples, (
            f"{what}: pulse dst=0x{vector:07x}: expected {expected_samples} non-zero "
            f"output sample(s) for a 1-cycle input pulse, observed {nonzero_samples}"
        )


__all__ = [
    "CLK_PERIOD_NS",
    "CONFIG_DEFAULT",
    "CT_SRC_CONFIG_ADDRS",
    "NUM_CT_DST",
    "NUM_CT_SRC",
    "PULSE_OBSERVE_WINDOW",
    "SELECT_MASK",
    "CtmTb",
    "expected_src_vector",
    "random_seed",
]
