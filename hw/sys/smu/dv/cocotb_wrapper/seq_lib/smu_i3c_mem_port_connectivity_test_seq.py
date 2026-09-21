# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""FAB_SMC_031 — AXI4-Lite local peripheral delivery (UART/I2C/GPIO/I3C/AVSBus).

SEP=1 honest scope (no sep_in / no Force):
  S1  J2A read at each peripheral destination; status must not be DECERR.

Delivery goes over the JTAG2AXI frontdoor to the PeakRDL destinations
(delivery-only; no field semantics).
"""

from __future__ import annotations

import cocotb
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import smc_addr, smc_indexed_addr
from seq_lib.smu_jtag_helpers import (
    J2A_STATUS_DECERR,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    jtag2axi_single_read,
    make_smu_jtag_tap,
)

# FAB_SMC_031 dest cells; addresses from PeakRDL smc_addr.h.
PERIPH_DESTS = (
    (
        "UART",
        smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR", 0),
    ),
    (
        "I2C",
        smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR", 0),
    ),
    (
        "GPIO",
        smc_indexed_addr("SMC_TOP_GPIO_INTF_BASE_ADDR", 0),
    ),
    (
        "I3C",
        smc_indexed_addr("SMC_TOP_OCA_I3C_WRAP_I3C_CSR_BASE_ADDR", 0),
    ),
    (
        "AVSBus",
        smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_CFG_0_BASE_ADDR"),
    ),
)


class smu_i3c_mem_port_connectivity_test_seq:
    """Prove J2A delivery to local peripheral CSR windows."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.s1_ok = False
        self.observed: list[str] = []

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    async def _j2a_rd32(self, jtag, addr: int, label: str) -> tuple[int, int]:
        """Return (status, rdata32) with 64b-lane unpack for addr[2]=1."""
        st, rdata = await jtag2axi_single_read(
            jtag, addr, size=SMC_DBG_AXSIZE_4B, require_complete=True
        )
        raw = int(rdata)
        word = (raw >> 32) & 0xFFFFFFFF if (addr & 0x4) else raw & 0xFFFFFFFF
        return st, word

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        jtag = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)

        idcode = await jtag.read_idcode()
        if idcode != 0x1:
            raise AssertionError(f"IDCODE want 0x1 got 0x{idcode:08x}")
        sb.expect_eq("CHK-SUB-AXIL-LOCAL-J2A-READY", idcode, 0x1)

        for dest, addr in PERIPH_DESTS:
            st, rdata = await self._j2a_rd32(jtag, addr, dest)
            if st == J2A_STATUS_DECERR:
                raise AssertionError(f"S1 dest={dest} @0x{addr:08x} DECERR (not delivered)")
            if st != J2A_STATUS_SUCCESS:
                raise AssertionError(
                    f"S1 dest={dest} @0x{addr:08x} status={st} (want SUCCESS, not DECERR)"
                )
            self._log(f"dest={dest} addr=0x{addr:08x} delivery status=SUCCESS rdata=0x{rdata:08x}")
            self.observed.append(dest)

        if len(self.observed) != len(PERIPH_DESTS):
            raise AssertionError(
                f"S1 delivered to {len(self.observed)} of "
                f"{len(PERIPH_DESTS)} destinations ({self.observed})"
            )

        cells = ",".join(f"dest={d}" for d in self.observed)
        self._log(f"CHK-SUB-AXIL-LOCAL-S1: {cells} observed=OKAY at consumer")
        sb.expect_eq(
            "CHK-SUB-AXIL-LOCAL-S1",
            len(self.observed),
            len(PERIPH_DESTS),
            evidence="CHK-SUB-AXIL-LOCAL-S1",
        )
        self.s1_ok = True
        self._log(f"PASS FAB_SMC_031 smu_i3c_mem_port_connectivity_test observed={self.observed}")
