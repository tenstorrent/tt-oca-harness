# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP-IO-STAP: IO STAP host TCK edges during PTAP IDCODE / BYPASS scans.

S1: During IDCODE IR+DR, ``tb_stap_io_tck`` (product ``jtag_stap_io_host_tap_ctrl_o.tck``)
    shows >=2 edges.
S2: During BYPASS IR + non-zero DR payload, TCK shows >=2 edges again.

No Force. Not claimed:
adjacent-die STAP BFM IDCODE or extra-STAP matrix.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from ocah_jtag_vip import OcahJtagMasterSequence, OcahJtagState

from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    DTP_IR_WIDTH,
    make_smu_jtag_tap,
)

EDGE_SAMPLE_CYCLES = 1000
IDLE_SAMPLE_CYCLES = 200
# Lower bound: IR (6b) + DR (32b) each bit needs a TCK edge pair in practice;
# require at least one edge per DR bit so a 2-edge floor cannot false-pass.
MIN_TCK_EDGES = 32
BYPASS_IR = (1 << DTP_IR_WIDTH) - 1
PAYLOAD_BITS = [1, 0, 1, 0, 1, 1, 0, 0] * 4


class smu_dtp_io_stap_smoke_test_seq:
    """Prove IO STAP TCK fanout during PTAP scans via TB observe pin."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.s1_ok = False
        self.s2_ok = False

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _sample_tck(self) -> int:
        pin = getattr(self.dut, "tb_stap_io_tck", None)
        if pin is None:
            raise AssertionError("tb_stap_io_tck unobservable on OSS tb_top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on tb_stap_io_tck: {val}")
        return int(val) & 1

    async def _count_tck_edges(self, cycles: int = EDGE_SAMPLE_CYCLES) -> int:
        prev = self._sample_tck()
        edges = 0
        for _ in range(cycles):
            await RisingEdge(self.dut.clk_ref_i)
            cur = self._sample_tck()
            if cur != prev:
                edges += 1
                prev = cur
        return edges

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        raw = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        jtag = OcahJtagMasterSequence(raw)
        await jtag.reset_to_tlr()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)

        idcode = await raw.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        sb.expect_eq("CHK-DTP-IO-STAP-JTAG-READY", idcode, DTP_DEFAULT_IDCODE)

        # Idle contrast: RTI with no shift — TCK must stay near-quiet vs scan.
        for _ in range(16):
            await jtag.step_tms(0)
        idle_edges = await self._count_tck_edges(IDLE_SAMPLE_CYCLES)
        idle_max = 2  # allow residual settle edges after prior IDCODE
        if idle_edges > idle_max:
            raise AssertionError(
                f"IO STAP tck idle_edges={idle_edges} want <={idle_max} "
                f"(RTI, no scan; sensitivity baseline)"
            )
        self._log(f"CHK-DTP-IO-STAP-IDLE: tck_edges={idle_edges} (max={idle_max} RTI quiet)")
        sb.expect_true("CHK-DTP-IO-STAP-IDLE", idle_edges <= idle_max)

        # S1: IDCODE scan while counting IO STAP TCK edges
        mon = cocotb.start_soon(self._count_tck_edges())
        await jtag.shift_ir(0x01, width=DTP_IR_WIDTH, back_to_rti=True)
        await jtag.shift_dr(0, 32, back_to_rti=True)
        edges = await mon
        if edges < MIN_TCK_EDGES:
            raise AssertionError(
                f"IO STAP tck edges={edges} during IDCODE "
                f"(need >={MIN_TCK_EDGES}; idle was {idle_edges})"
            )
        self.s1_ok = True
        self._log(
            f"CHK-DTP-IO-STAP-SCAN: tck_edges={edges} "
            f"(min={MIN_TCK_EDGES} idle={idle_edges}) pin=tb_stap_io_tck"
        )
        sb.expect_true(
            "CHK-DTP-IO-STAP-SCAN",
            edges >= MIN_TCK_EDGES and edges > idle_edges,
            evidence="CHK-DTP-IO-STAP-SCAN",
        )

        # S2: BYPASS + non-zero DR payload
        payload = 0
        for i, bit in enumerate(PAYLOAD_BITS):
            payload |= (bit & 1) << i
        mon2 = cocotb.start_soon(self._count_tck_edges())
        await jtag.shift_ir(BYPASS_IR, width=DTP_IR_WIDTH, back_to_rti=True)
        await jtag.shift_dr(payload, 32, back_to_rti=True)
        edges2 = await mon2
        if edges2 < MIN_TCK_EDGES:
            raise AssertionError(
                f"IO STAP payload tck edges={edges2} "
                f"(need >={MIN_TCK_EDGES}; idle was {idle_edges})"
            )
        self.s2_ok = True
        self._log(
            f"CHK-DTP-IO-STAP-SCAN-PAYLOAD: tck_edges={edges2} "
            f"(min={MIN_TCK_EDGES} idle={idle_edges}) payload=0x{payload:08x}"
        )
        sb.expect_true(
            "CHK-DTP-IO-STAP-SCAN-PAYLOAD",
            edges2 >= MIN_TCK_EDGES and edges2 > idle_edges,
        )

        self._log(f"PASS DTP-IO-STAP s1={self.s1_ok} s2={self.s2_ok} edges={edges}/{edges2}")
