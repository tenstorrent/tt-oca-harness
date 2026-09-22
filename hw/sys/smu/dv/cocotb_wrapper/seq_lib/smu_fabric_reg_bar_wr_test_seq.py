# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OSS SMU Tier A: local fabric config-register delivery (FAB_SMC_032).

SEP=1 honest scope (no sep_in / no Force):
  S1  J2A ones/zeros RW-mask discovery + pattern write/readback at each
      fabric configuration-register destination (delivery-only; no field
      semantics).

Delivery goes over the JTAG2AXI frontdoor to the authoritative PeakRDL
destinations.
"""

from __future__ import annotations

import cocotb
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import (
    INBOUND_FILTER_START_SYM,
    OUTBOUND_FILTER_START_SYM,
    smc_addr,
    smc_indexed_addr,
)
from seq_lib.smu_jtag_helpers import (
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    SMC_DBG_AXSIZE_8B,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
)

FABCFG_DESTS = (
    (
        "cpu_ctrl",
        smc_addr("SMC_TOP_SMC_BASE_CONFIG_HANG_DET_DATA_ACCEL_TIMEOUT_THRESHOLD_BASE_ADDR"),
        4,
    ),
    (
        "alias_remap",
        smc_indexed_addr("SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_START_BASE_ADDR", 0),
        8,
    ),
    (
        "mmode_remap",
        smc_indexed_addr("SMC_TOP_SMC_MMODE_REMAP_REGION_REGION_ATTRS_BASE_ADDR", 0),
        8,
    ),
    (
        "xvisor_remap",
        smc_indexed_addr("SMC_TOP_SMC_XVISOR_REMAP_REGION_REGION_ATTRS_BASE_ADDR", 0),
        8,
    ),
    (
        "inbound_filter",
        smc_indexed_addr(INBOUND_FILTER_START_SYM, 0),
        8,
    ),
    (
        "outbound_filter",
        smc_indexed_addr(OUTBOUND_FILTER_START_SYM, 0),
        8,
    ),
)


# JTAG2AXI operations _wr_rd_prove issues per destination: the original read,
# the ones and zeros write/readback pairs, the pattern write/readback, and the
# restoring write. Each must answer SUCCESS at the consumer.
J2A_OPS_PER_DEST = 8


def _width_mask(width: int) -> int:
    if width not in (4, 8):
        raise AssertionError(f"unsupported width={width}")
    return (1 << (width * 8)) - 1


def _j2a_size_wstrb(width: int) -> tuple[int, int]:
    if width == 4:
        return SMC_DBG_AXSIZE_4B, 0x0F
    return SMC_DBG_AXSIZE_8B, 0xFF


class smu_fabric_reg_bar_wr_test_seq:
    """Prove J2A delivery to fabric config CSR destinations."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.s1_ok = False
        self.observed: list[str] = []
        self.okay_ops = 0

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    async def _j2a_wr(self, jtag, addr: int, data: int, width: int, name: str) -> None:
        size, wstrb = _j2a_size_wstrb(width)
        st, _ = await jtag2axi_single_write(
            jtag,
            addr,
            data & _width_mask(width),
            wstrb=wstrb,
            size=size,
            require_complete=True,
        )
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A WR {name} @0x{addr:08x} status={st}")
        self.okay_ops += 1

    async def _j2a_rd(self, jtag, addr: int, width: int, name: str) -> int:
        size, _ = _j2a_size_wstrb(width)
        st, rdata = await jtag2axi_single_read(jtag, addr, size=size, require_complete=True)
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A RD {name} @0x{addr:08x} status={st}")
        self.okay_ops += 1
        return int(rdata) & _width_mask(width)

    async def _wr_rd_prove(self, jtag, dest: str, addr: int, width: int) -> None:
        """Prove CSR delivery without claiming field semantics."""
        mask = _width_mask(width)
        all_ones = mask

        orig = await self._j2a_rd(jtag, addr, width, f"{dest}_orig")

        await self._j2a_wr(jtag, addr, all_ones, width, f"{dest}_ones")
        ones = await self._j2a_rd(jtag, addr, width, f"{dest}_ones_rb")

        await self._j2a_wr(jtag, addr, 0, width, f"{dest}_zeros")
        zeros = await self._j2a_rd(jtag, addr, width, f"{dest}_zeros_rb")

        rw_mask = ones & ~zeros & all_ones
        if rw_mask == 0:
            raise AssertionError(
                f"S1 dest={dest} @0x{addr:08x} no RW bits (ones=0x{ones:x} zeros=0x{zeros:x})"
            )

        pattern = (orig ^ 0xA5A5A5A5) & rw_mask
        if pattern == (orig & rw_mask):
            pattern = (orig + 1) & rw_mask
        write_val = (orig & ~rw_mask) | pattern

        await self._j2a_wr(jtag, addr, write_val, width, f"{dest}_pat")
        got = await self._j2a_rd(jtag, addr, width, f"{dest}_pat_rb")
        if (got & rw_mask) != pattern:
            raise AssertionError(
                f"S1 dest={dest} @0x{addr:08x} readback 0x{got:x} & "
                f"mask 0x{rw_mask:x} != pattern 0x{pattern:x}"
            )

        await self._j2a_wr(jtag, addr, orig, width, f"{dest}_restore")
        self._log(
            f"dest={dest} addr=0x{addr:08x} delivery wr+rd status=SUCCESS "
            f"rw_mask=0x{rw_mask:x} readback=match"
        )

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

        for dest, addr, width in FABCFG_DESTS:
            await self._wr_rd_prove(jtag, dest, addr, width)
            self.observed.append(dest)

        dests = [dest for dest, _, _ in FABCFG_DESTS]
        want_ops = J2A_OPS_PER_DEST * len(FABCFG_DESTS)
        cells = ",".join(f"dest={d}" for d in self.observed)
        self._log(
            f"CHK-SUB-AXIL-LOCAL-S2: {cells} write/readback held; "
            f"SUCCESS responses at the consumer={self.okay_ops} (expect {want_ops})"
        )
        sb.expect_eq(
            "CHK-SUB-AXIL-LOCAL-S2 destinations with write/readback held",
            self.observed,
            dests,
            evidence="CHK-SUB-AXIL-LOCAL-S2",
        )
        sb.expect_eq(
            "CHK-SUB-AXIL-LOCAL-S2 SUCCESS responses at the consumer",
            self.okay_ops,
            want_ops,
            evidence="CHK-SUB-AXIL-LOCAL-S2",
        )
        self.s1_ok = True
