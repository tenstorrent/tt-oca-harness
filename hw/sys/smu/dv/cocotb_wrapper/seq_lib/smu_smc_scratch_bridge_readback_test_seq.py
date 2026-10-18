# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SCRATCH[0..15] reset value and write-readback through the SMC fabric JTAG2AXI bridge.

Spec: cpu_ctrl.rdl (reg SCRATCH: data[31:0] sw=rw reset 0; SCRATCH[16] @0x80, stride 8);
smc.rdl (smc_cpu_ctrl placement at SMC base + 0x3_9000); memmap.adoc.

Each SCRATCH[n] is read, written with a distinct pattern and read back, all over the bridge.
"""

from __future__ import annotations

import cocotb
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import smc_indexed_addr, smc_indexed_stride
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)

_SYMBOL = "SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR"
SCRATCH_COUNT = 16
SCRATCH_STRIDE = smc_indexed_stride(_SYMBOL)
SCRATCH_RESET = 0x0
PATTERN_FORMULA = "(0xA5A50000 ^ (n * 0x01010101)) & 0xFFFFFFFF"

J2A_POLL_LIMIT = 128


def scratch_addr(n: int) -> int:
    return smc_indexed_addr(_SYMBOL, n)


def pattern(n: int) -> int:
    return (0xA5A50000 ^ (n * 0x01010101)) & 0xFFFFFFFF


class smu_smc_scratch_bridge_readback_test_seq:
    """SCRATCH[n] reset read, pattern write and read-back over the JTAG2AXI bridge."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.done = False
        self.jtag = None
        self.j2a = 0
        self.sites = {
            "j2a": {"bound": f"{J2A_POLL_LIMIT} polls", "count": 0, "last": "none", "expired": 0},
        }

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _mark(self, step: str, text: str) -> None:
        self._log(f"STEP {step}: {text}")

    def _count(self, label: str, status: int, addr: int, kind: str) -> None:
        rec = self.sites["j2a"]
        self.j2a += 1
        rec["count"] = self.j2a
        rec["last"] = f"{kind} {label} status={status}"
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A {kind} {label} @0x{addr:08x} status={status}")

    def _expire(self, kind: str, label: str, exc: Exception) -> None:
        rec = self.sites["j2a"]
        rec["expired"] += 1
        rec["last"] = f"EXPIRED {kind} {label} {exc}"
        self._log(f"TIMEOUT-PATH j2a: bound={rec['bound']} EXPIRED last={exc}")

    async def _j2a_rd32(self, addr: int, label: str) -> int:
        try:
            status, rdata = await jtag2axi_single_read(
                self.jtag,
                addr,
                size=SMC_DBG_AXSIZE_4B,
                poll_limit=J2A_POLL_LIMIT,
                require_complete=True,
            )
        except TimeoutError as exc:
            self._expire("RD", label, exc)
            raise
        require_jtag_tdo_resolved(f"J2A RD {label} @0x{addr:08x}")
        self._count(label, status, addr, "RD")
        raw = int(rdata)
        return ((raw >> 32) if addr & 0x4 else raw) & 0xFFFFFFFF

    async def _j2a_wr32(self, addr: int, data: int, label: str) -> None:
        word = int(data) & 0xFFFFFFFF
        packed, wstrb = (word << 32, 0xF0) if addr & 0x4 else (word, 0x0F)
        try:
            status, _ = await jtag2axi_single_write(
                self.jtag,
                addr,
                packed,
                wstrb=wstrb,
                size=SMC_DBG_AXSIZE_4B,
                poll_limit=J2A_POLL_LIMIT,
                require_complete=True,
            )
        except TimeoutError as exc:
            self._expire("WR", label, exc)
            raise
        require_jtag_tdo_resolved(f"J2A WR {label} @0x{addr:08x}")
        self._count(label, status, addr, "WR")

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        dut = self.dut

        self._mark("S1", "SETUP: bring-up, IDCODE, J2A gate open")
        self.jtag = jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        gate = dut.tb_smc_jtag2axi_security_disable.value
        lc = dut.lc_state_o.value
        if not gate.is_resolvable or not lc.is_resolvable:
            raise AssertionError(f"X/Z on gate={gate} lc_state_o={lc}")
        if int(gate) & 1:
            raise AssertionError(f"SMC J2A gated: security_disable={gate}")
        self._log(f"CHK-COMP-SCRATCH-READBACK: lc_state_o=0x{int(lc):x} j2a_gate={int(gate)}")
        self._log(f"CELL setup idcode=0x{idcode:08x} security_disable={int(gate)}")

        self._mark("S2", "SCRATCH reset read, pattern write, read-back")
        self._log(f"CHK-COMP-SCRATCH-READBACK: pattern P_n = {PATTERN_FORMULA}")
        resets = []
        for n in range(SCRATCH_COUNT):
            resets.append(await self._j2a_rd32(scratch_addr(n), f"scratch_{n}"))
        for n in range(SCRATCH_COUNT):
            await self._j2a_wr32(scratch_addr(n), pattern(n), f"scratch_{n}")
        reads = []
        for n in range(SCRATCH_COUNT):
            reads.append(await self._j2a_rd32(scratch_addr(n), f"scratch_{n}"))
        for n in range(SCRATCH_COUNT):
            addr = scratch_addr(n)
            self._log(
                f"CELL scratch_{n} addr=0x{addr:08x} reset=0x{resets[n]:08x} "
                f"wrote=0x{pattern(n):08x} read=0x{reads[n]:08x}"
            )
            sb.expect_eq(
                f"CHK-COMP-SCRATCH-READBACK scratch_{n} reset",
                resets[n],
                SCRATCH_RESET,
                evidence="COMP_SCRATCH_READBACK",
            )
            sb.expect_eq(
                f"CHK-COMP-SCRATCH-READBACK scratch_{n} readback",
                reads[n],
                pattern(n),
                evidence="COMP_SCRATCH_READBACK",
            )

        self._mark("S3", "TIMEOUT: bounded waits and last state")
        lines = []
        for site, rec in self.sites.items():
            state = "EXPIRED" if rec["expired"] else "ok"
            lines.append(
                f"{site}: bound={rec['bound']} {state} count={rec['count']} last={rec['last']}"
            )
        for line in lines:
            self._log(f"TIMEOUT-PATH {line}")
        expired = sum(rec["expired"] for rec in self.sites.values())
        self._log(
            f"CHK-TIMEOUT-PATHS: sites={len(lines)} expired={expired} "
            f"j2a_accesses_counted={self.j2a} (counted at the call sites of this seq)"
        )
        sb.expect_eq("expired TIMEOUT-PATH records", expired, 0, evidence="CHK_TIMEOUT_PATHS")
        self.done = True
