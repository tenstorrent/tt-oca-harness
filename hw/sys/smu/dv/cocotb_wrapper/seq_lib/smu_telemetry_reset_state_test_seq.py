# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Telemetry receiver control, status, interrupt and message registers at reset.

Spec: telemetry_receiver.rdl (CTRL, STATUS, INTR_*, TELEMETRY_PROBE_ID, TELEMETRY_COUNTER_VLDS,
TELEMETRY_COUNTER reset values); telemetry_receiver_wrap.rdl and smc.rdl (three receivers at
SMC base + 0x9000 + 0x100 * k); doc/memmap.adoc "Reset Behavior".

The JTAG2AXI bridge reads every register before any ATB beat is driven; nothing is written.
"""

from __future__ import annotations

import cocotb
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import smc_addr, smc_indexed_addr
from seq_lib.smu_boundary_regs import smc_indexed2_addr, telemetry_receiver_u32
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    axi64_unpack32,
    jtag2axi_single_read,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)

_PFX = "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_"
CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

NUM_RECEIVERS = 3
NUM_COUNTERS = 32
STATUS_EMPTY_BM = telemetry_receiver_u32("TELEMETRY_RECEIVER__STATUS__BUFFER_EMPTY_bm")
STATUS_FULL_BM = telemetry_receiver_u32("TELEMETRY_RECEIVER__STATUS__BUFFER_FULL_bm")
STATUS_EMPTY_RESET = telemetry_receiver_u32("TELEMETRY_RECEIVER__STATUS__BUFFER_EMPTY_reset")
STATUS_FULL_RESET = telemetry_receiver_u32("TELEMETRY_RECEIVER__STATUS__BUFFER_FULL_reset")
STATUS_RESET = (STATUS_EMPTY_RESET * STATUS_EMPTY_BM) | (STATUS_FULL_RESET * STATUS_FULL_BM)
STATUS_FIELD_BM = STATUS_EMPTY_BM | STATUS_FULL_BM

J2A_POLL_LIMIT = 128


def _tel(name: str, receiver: int) -> int:
    return smc_indexed_addr(f"{_PFX}{name}_BASE_ADDR", receiver)


class smu_telemetry_reset_state_test_seq:
    """Reset-state reads of the three telemetry receivers over JTAG2AXI."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.done = False
        self.jtag = None
        self.j2a = 0
        self.sites: dict[str, dict] = {}

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _mark(self, step: str, text: str) -> None:
        self._log(f"STEP {step}: {text}")

    def _cell(self, name: str, addr: int, text: str) -> None:
        self._log(f"CELL {name} addr=0x{addr:08x} {text}")

    async def _j2a_rd(self, addr: int, label: str) -> int:
        """One counted JTAG2AXI read; an expiry is recorded and re-raised."""
        rec = self.sites.setdefault(
            "j2a", {"bound": f"{J2A_POLL_LIMIT} polls", "count": 0, "last": "none", "expired": 0}
        )
        try:
            status, rdata = await jtag2axi_single_read(
                self.jtag,
                addr,
                size=SMC_DBG_AXSIZE_4B,
                poll_limit=J2A_POLL_LIMIT,
                require_complete=True,
            )
        except TimeoutError as exc:
            rec["expired"] += 1
            rec["last"] = f"EXPIRED {label} {exc}"
            self._log(f"TIMEOUT-PATH j2a: bound={rec['bound']} EXPIRED last={exc}")
            raise
        require_jtag_tdo_resolved(f"J2A RD {label} @0x{addr:08x}")
        self.j2a += 1
        rec["count"] = self.j2a
        rec["last"] = f"{label} status={status}"
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A RD {label} @0x{addr:08x} status={status}")
        return axi64_unpack32(addr, rdata)

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        dut = self.dut

        self._mark("S1", "SETUP: bring-up, IDCODE, J2A gate open")
        await self.cfg.reset_done.wait()
        self.jtag = jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        gate = dut.tb_smc_jtag2axi_security_disable.value
        if not gate.is_resolvable or int(gate) & 1:
            raise AssertionError(f"SMC J2A gated: security_disable={gate}")
        self._log(f"CELL setup idcode=0x{idcode:08x} security_disable={int(gate)}")
        cg_word = await self._j2a_rd(CLOCK_GATE_CONTROL, "CLOCK_GATE_CONTROL")
        self._log(f"CHK-TELR-CTRL-STATUS: cg_word=0x{cg_word:08x}")

        self._mark("S2", "read STATUS, CTRL, INTR_STATUS, INTR_ENABLE, INTR_TEST on rx0..2")
        for rx in range(NUM_RECEIVERS):
            addr = _tel("STATUS", rx)
            value = await self._j2a_rd(addr, f"rx{rx} STATUS")
            self._cell(f"rx{rx} STATUS", addr, f"value=0x{value:08x}")
            sb.expect_eq(
                f"CHK-TELR-CTRL-STATUS rx{rx} STATUS.BUFFER_EMPTY/BUFFER_FULL reset",
                value & STATUS_FIELD_BM,
                STATUS_RESET,
                evidence="TELR_CTRL_STATUS",
            )
            for reg in ("CTRL", "INTR_STATUS", "INTR_ENABLE", "INTR_TEST"):
                addr = _tel(reg, rx)
                value = await self._j2a_rd(addr, f"rx{rx} {reg}")
                self._cell(f"rx{rx} {reg}", addr, f"value=0x{value:08x}")
                sb.expect_eq(
                    f"CHK-TELR-CTRL-STATUS rx{rx} {reg} reset",
                    value,
                    0,
                    evidence="TELR_CTRL_STATUS",
                )

        self._mark("S3", "read PROBE_ID, COUNTER_VLDS, COUNTER[n] on rx0..2")
        for rx in range(NUM_RECEIVERS):
            cells = [
                (f"rx{rx} TELEMETRY_PROBE_ID", _tel("TELEMETRY_PROBE_ID", rx)),
                (f"rx{rx} TELEMETRY_COUNTER_VLDS", _tel("TELEMETRY_COUNTER_VLDS", rx)),
            ]
            for n in range(NUM_COUNTERS if rx == 0 else 1):
                cells.append(
                    (
                        f"rx{rx} TELEMETRY_COUNTER[{n}]",
                        smc_indexed2_addr(f"{_PFX}TELEMETRY_COUNTER_BASE_ADDR", rx, n),
                    )
                )
            for name, addr in cells:
                value = await self._j2a_rd(addr, name)
                self._cell(name, addr, f"value=0x{value:08x}")
                sb.expect_eq(
                    f"CHK-TELR-MESSAGE-ZERO {name} reset",
                    value,
                    0,
                    evidence="TELR_MESSAGE_ZERO",
                )

        self._mark("S4", "TIMEOUT: bounded waits and last state")
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
