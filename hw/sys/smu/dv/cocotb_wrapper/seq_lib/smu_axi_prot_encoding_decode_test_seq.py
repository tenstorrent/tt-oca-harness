# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OSS SMU Tier A: inbound AxPROT[1] decode via allow_ns=0 (FAB_SMC_029 S9 subset).

SEP=1 honest scope: JTAG2AXI filter program + s_axi stimulus only.
S1–S8 (GPIO AXI-Lite exact-match) need sep_in_master and are not covered.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, with_timeout
from ocah_axi_vip import RESP_DECERR, RESP_OKAY
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import (
    SMC_CHIP_CONFIG_VERSION_LO,
    filter_ctrl_bm,
    filter_ctrl_field_reset_encode,
    smc_indexed_addr,
)
from seq_lib.smu_axi_helpers import make_smu_axi_master, resp_name
from seq_lib.smu_filter_helpers import (
    page_align_window,
    program_smc_aperture_local_alias,
)
from seq_lib.smu_jtag_helpers import (
    J2A_STATUS_SUCCESS,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
)
from seq_lib.smu_tb_pins import smc_primary_reset

_F_READ = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__READ_ALLOWED_bm")
_F_WRITE = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__WRITE_ALLOWED_bm")
_F_ENTRY = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm")
_F_ALLOW_BURST = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ALLOW_BURST_bm")
_F_BUS_WIDTH_64 = filter_ctrl_field_reset_encode("DATA_BUS_WIDTH")
CFG_SECURE_ONLY = _F_READ | _F_WRITE | _F_ENTRY | _F_BUS_WIDTH_64 | _F_ALLOW_BURST
_CFG_CMP_MASK = (
    _F_READ
    | _F_WRITE
    | _F_ENTRY
    | filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ALLOW_NS_bm")
    | filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__DATA_BUS_WIDTH_bm")
    | _F_ALLOW_BURST
)

_IN_CFG = "SMC_TOP_SMC_INBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR"
_IN_START = "SMC_TOP_SMC_INBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR"
_IN_END = "SMC_TOP_SMC_INBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR"

AXI_TIMEOUT_NS = 200_000
FILTER_READY_POLLS = 64
FILTER_READY_STEP = 4

# prot[1]=0 admit; prot[1]=1 block when allow_ns=0 (traffic_filter pass_ns equality).
SECURE_ALLOWED = frozenset({0x0, 0x1, 0x4, 0x5})
NONSECURE_BLOCKED = frozenset({0x2, 0x3, 0x6, 0x7})
PROT_LABELS = {
    0x0: "Data,Secure,User",
    0x1: "Data,Secure,Privileged",
    0x2: "Data,NonSecure,User",
    0x3: "Data,NonSecure,Privileged",
    0x4: "Instruction,Secure,User",
    0x5: "Instruction,Secure,Privileged",
    0x6: "Instruction,NonSecure,User",
    0x7: "Instruction,NonSecure,Privileged",
}


class smu_axi_prot_encoding_decode_test_seq:
    """S9 inbound allow_ns=0 eight-way AxPROT matrix on VERSION_LO."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.matrix_ok = False

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    async def _axi_rd(self, master, addr: int, prot: int):
        async def _do():
            result = await master.read_bytes_result(addr, 4, prot=prot, check_response=False)
            return result.data, result.resp

        try:
            return await with_timeout(_do(), AXI_TIMEOUT_NS, "ns")
        except Exception as exc:
            raise AssertionError(
                f"TIMEOUT axi rd addr=0x{addr:08x} prot=0x{prot:x}: {exc}"
            ) from exc

    async def _await_resp(self, master, addr: int, prot: int, want, label: str):
        last = None
        for poll in range(FILTER_READY_POLLS):
            _val, resp = await self._axi_rd(master, addr, prot)
            last = resp
            if resp == want:
                self._log(
                    f"FILTER_READY {label} prot=0x{prot:x} want={resp_name(want)} poll={poll}"
                )
                return
            await ClockCycles(self.dut.clk_smu_i, FILTER_READY_STEP)
        raise AssertionError(
            f"TIMEOUT FILTER_READY {label} prot=0x{prot:x} "
            f"want={resp_name(want)} last={resp_name(last) if last is not None else None}"
        )

    async def _j2a_wr(self, jtag, addr: int, data: int, name: str) -> None:
        st, _ = await jtag2axi_single_write(jtag, addr, data, require_complete=True)
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A WR {name} status={st}")
        self._log(f"J2A WR {name} @0x{addr:08x} data=0x{data:x}")

    async def _j2a_rd(self, jtag, addr: int, name: str) -> int:
        st, rdata = await jtag2axi_single_read(jtag, addr, require_complete=True)
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A RD {name} status={st}")
        return int(rdata)

    async def _program_secure_window(self, jtag, lo: int, hi: int) -> None:
        await self._j2a_wr(jtag, smc_indexed_addr(_IN_CFG, 1), 0, "DIS_I1")
        await self._j2a_wr(jtag, smc_indexed_addr(_IN_START, 0), lo, "S9_START")
        await self._j2a_wr(jtag, smc_indexed_addr(_IN_END, 0), hi, "S9_END")
        await self._j2a_wr(jtag, smc_indexed_addr(_IN_CFG, 0), CFG_SECURE_ONLY, "S9_CONFIG")
        rb = await self._j2a_rd(jtag, smc_indexed_addr(_IN_CFG, 0), "S9_RB")
        if (rb & _CFG_CMP_MASK) != (CFG_SECURE_ONLY & _CFG_CMP_MASK):
            raise AssertionError(f"S9 CONFIG rb mismatch want=0x{CFG_SECURE_ONLY:x} got=0x{rb:x}")

    async def run(self) -> None:
        dut = self.dut
        sb = self.test.env.scoreboard
        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        # SEP=1 wrapper: route ext_in local addresses through the crossbar.
        await program_smc_aperture_local_alias(jtag, scoreboard=sb)

        idcode = await jtag.read_idcode()
        if idcode != 0x1:
            raise AssertionError(f"IDCODE want 0x1 got 0x{idcode:08x}")
        sb.expect_eq("CHK-SMU-PROT-J2A-READY", idcode, 0x1)

        master = await make_smu_axi_master(dut, dut.clk_smu_i, smc_primary_reset(dut))
        probe = SMC_CHIP_CONFIG_VERSION_LO
        lo, hi = page_align_window(probe, probe)
        await self._program_secure_window(jtag, lo, hi)

        # Warm filter path with one known-good secure encoding.
        await self._await_resp(master, probe, 0x1, RESP_OKAY, "S9_warm_secure")

        observed: list[tuple[int, str]] = []
        wanted: list[tuple[int, str]] = []
        for prot in range(8):
            label = PROT_LABELS[prot]
            want = RESP_OKAY if prot in SECURE_ALLOWED else RESP_DECERR
            _val, resp = await self._axi_rd(master, probe, prot)
            observed.append((prot, resp_name(resp)))
            wanted.append((prot, resp_name(want)))
            self._log(
                f"CHK-SMU-PROT-S9 cell prot=0x{prot:x} {label} "
                f"resp={resp_name(resp)} expect={resp_name(want)}"
            )

        # Positive control: every SECURE_ALLOWED and NONSECURE_BLOCKED cell hit.
        if set(range(8)) != (SECURE_ALLOWED | NONSECURE_BLOCKED):
            raise AssertionError("S9 prot partition incomplete")
        sb.expect_eq(
            "CHK-SMU-PROT-S9-MATRIX",
            tuple(observed),
            tuple(wanted),
            evidence="CHK-SMU-PROT-S9-MATRIX",
        )
        self.matrix_ok = True
        self._log(
            "CHK-SMU-PROT-S9-BASIC: allow_ns=0 eight-way AxPROT matrix on VERSION_LO "
            "(S1-S8 GPIO exact-match deferred — needs sep_in)"
        )
