# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OSS SMU Tier A: inbound allow_ns admit/block via JTAG2AXI + s_axi.

Honest SEP=1 scope (no sep_in_master, no Force):
  S1  allow_ns=0  — secure prot OKAY, nonsecure DECERR on VERSION_LO window
  S2  dual-slot   — inst0 secure + inst1 NS overlap admits both prot[1]
  S3  clear       — BlockByDefault DECERR for both

The FAB_SMC_026 outbound/S4/S5 matrix needs a peer master and is not covered.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, with_timeout
from ocah_axi_vip import PROT_NONSECURE, PROT_PRIVILEGED, RESP_DECERR, RESP_OKAY
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import (
    INBOUND_FILTER_INST_STRIDE,
    SMC_CHIP_CONFIG_VERSION_LO,
    filter_ctrl_bm,
    filter_ctrl_field_reset_encode,
    smc_indexed_addr,
)
from seq_lib.smu_axi_helpers import (
    make_smu_axi_master,
    resp_name,
)
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
from seq_lib.smu_tb_pins import smc_primary_reset, smu_scope

# FILTER_CONFIG packs from filter_ctrl.h *_bm (+ DATA_BUS_WIDTH encode 3).
_F_READ = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__READ_ALLOWED_bm")
_F_WRITE = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__WRITE_ALLOWED_bm")
_F_ENTRY = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm")
_F_ALLOW_NS = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ALLOW_NS_bm")
_F_ALLOW_BURST = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ALLOW_BURST_bm")
_F_BUS_WIDTH_64 = filter_ctrl_field_reset_encode("DATA_BUS_WIDTH")

CFG_SECURE_ONLY = _F_READ | _F_WRITE | _F_ENTRY | _F_BUS_WIDTH_64 | _F_ALLOW_BURST
CFG_NS_ONLY = CFG_SECURE_ONLY | _F_ALLOW_NS
_CFG_CMP_MASK = (
    _F_READ
    | _F_WRITE
    | _F_ENTRY
    | _F_ALLOW_NS
    | filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__DATA_BUS_WIDTH_bm")
    | _F_ALLOW_BURST
)

_IN_CFG = "SMC_TOP_SMC_INBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR"
_IN_START = "SMC_TOP_SMC_INBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR"
_IN_END = "SMC_TOP_SMC_INBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR"

AXI_TIMEOUT_NS = 200_000
FILTER_READY_POLLS = 64
FILTER_READY_STEP = 4
SECURE_PROT = PROT_PRIVILEGED  # prot[1]=0
NONSECURE_PROT = PROT_PRIVILEGED | PROT_NONSECURE  # 0x3


class smu_axi_filter_allow_ns_test_seq:
    """Inbound allow_ns S1/S2/S3 on VERSION_LO via J2A + s_axi."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.secure_ok = False
        self.ns_block_ok = False
        self.dual_ok = False
        self.clear_ok = False

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    async def _axi_rw(self, master, addr: int, *, prot, write: bool, wdata: int = 0):
        async def _do():
            if write:
                result = await master.write_bytes_result(
                    addr,
                    wdata.to_bytes(4, "little"),
                    prot=prot,
                    check_response=False,
                )
                return None, result.resp
            result = await master.read_bytes_result(addr, 4, prot=prot, check_response=False)
            return result.data, result.resp

        try:
            return await with_timeout(_do(), AXI_TIMEOUT_NS, "ns")
        except Exception as exc:
            raise AssertionError(
                f"TIMEOUT axi {'wr' if write else 'rd'} addr=0x{addr:08x} "
                f"prot={int(prot)} bound={AXI_TIMEOUT_NS}ns: {exc}"
            ) from exc

    async def _await_axi_resp(
        self,
        master,
        addr: int,
        *,
        prot,
        want,
        label: str,
        write: bool = False,
        wdata: int = 0,
    ):
        """Poll AXI until want resp (filter take-effect); fail with last state."""
        last = None
        last_data = None
        for poll in range(FILTER_READY_POLLS):
            val, resp = await self._axi_rw(master, addr, prot=prot, write=write, wdata=wdata)
            last, last_data = resp, val
            if resp == want:
                self._log(
                    f"FILTER_READY {label} want={resp_name(want)} "
                    f"poll={poll} last={resp_name(resp)}"
                )
                return val, resp
            await ClockCycles(self.dut.clk_smu_i, FILTER_READY_STEP)
        raise AssertionError(
            f"TIMEOUT FILTER_READY {label}: want={resp_name(want)} "
            f"last={resp_name(last) if last is not None else None} "
            f"data={last_data!r} polls={FILTER_READY_POLLS} "
            f"step={FILTER_READY_STEP}"
        )

    async def _j2a_wr(self, jtag, addr: int, data: int, name: str) -> None:
        st, _ = await jtag2axi_single_write(jtag, addr, data, require_complete=True)
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"J2A WR {name} @0x{addr:08x} status={st} want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        self._log(f"J2A WR {name} @0x{addr:08x} data=0x{data:x} status=SUCCESS")

    async def _j2a_rd(self, jtag, addr: int, name: str) -> int:
        st, rdata = await jtag2axi_single_read(jtag, addr, require_complete=True)
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"J2A RD {name} @0x{addr:08x} status={st} want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        self._log(f"J2A RD {name} @0x{addr:08x} data=0x{rdata:x} status=SUCCESS")
        return int(rdata)

    async def _program_inst(
        self, jtag, inst: int, start: int, end: int, config: int, tag: str
    ) -> None:
        base = smc_indexed_addr(_IN_CFG, inst)
        start_a = smc_indexed_addr(_IN_START, inst)
        end_a = smc_indexed_addr(_IN_END, inst)
        if smc_indexed_addr(_IN_CFG, 1) - smc_indexed_addr(_IN_CFG, 0) != (
            INBOUND_FILTER_INST_STRIDE
        ):
            raise AssertionError("inbound filter stride map inconsistency")
        await self._j2a_wr(jtag, start_a, start, f"{tag}_START")
        await self._j2a_wr(jtag, end_a, end, f"{tag}_END")
        await self._j2a_wr(jtag, base, config, f"{tag}_CONFIG")
        rb = await self._j2a_rd(jtag, base, f"{tag}_CONFIG_RB")
        if (rb & _CFG_CMP_MASK) != (config & _CFG_CMP_MASK):
            raise AssertionError(
                f"{tag} CONFIG readback mismatch want=0x{config:x} "
                f"got=0x{rb:x} (mask=0x{_CFG_CMP_MASK:x})"
            )

    async def _disable_inst(self, jtag, inst: int) -> None:
        base = smc_indexed_addr(_IN_CFG, inst)
        await self._j2a_wr(jtag, base, 0, f"DISABLE_I{inst}_CONFIG")

    async def run(self) -> None:
        dut = self.dut
        sb = self.test.env.scoreboard
        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        # feat_ctrl is 2-flop synced on TCK (ResetValue=0). Without TCK activity
        # smc_jtag2axi_security_disable stays 1 and SINGLE_OP silently no-ops
        # (capture stays SUCCESS/rdata=0).
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        # SEP=1 wrapper: route ext_in local addresses through the crossbar.
        await program_smc_aperture_local_alias(jtag, scoreboard=sb)

        try:
            sec = int(
                smu_scope(
                    dut
                ).u_dtp.u_jtag_intf_unit.u_jtag_ptap.smc_jtag2axi_security_disable.value
            )
            self._log(f"OBS smc_jtag2axi_security_disable={sec}")
            if sec != 0:
                raise AssertionError(f"J2A still gated after TCK sync: security_disable={sec}")
        except AttributeError as exc:
            self._log(f"OBS security_disable probe skipped: {exc}")

        idcode = await jtag.read_idcode()
        if idcode != 0x1:
            raise AssertionError(f"IDCODE want 0x1 got 0x{idcode:08x}")
        self._log(f"OBS IDCODE=0x{idcode:08x}")
        sb.expect_eq("CHK-SMU-ALLOW-NS-J2A-READY", idcode, 0x1)

        master = await make_smu_axi_master(dut, dut.clk_smu_i, smc_primary_reset(dut))

        probe = SMC_CHIP_CONFIG_VERSION_LO
        lo, hi = page_align_window(probe, probe)

        ver = await self._j2a_rd(jtag, probe, "VERSION_LO_SMOKE")
        self._log(f"J2A smoke VERSION_LO=0x{ver:08x}")

        # ---- S1: allow_ns=0 ----
        await self._disable_inst(jtag, 1)
        await self._program_inst(jtag, 0, lo, hi, CFG_SECURE_ONLY, "S1_SECURE")
        await self._await_axi_resp(
            master,
            probe,
            prot=SECURE_PROT,
            want=RESP_OKAY,
            label="S1_secure_wr_ready",
            write=True,
            wdata=0xA5A50001,
        )
        s_rd, s_rr = await self._axi_rw(master, probe, prot=SECURE_PROT, write=False)
        if s_rr != RESP_OKAY:
            raise AssertionError(
                f"S1 secure read expected OKAY got {resp_name(s_rr)} data=0x{s_rd:08x}"
            )
        self.secure_ok = True

        await self._await_axi_resp(
            master,
            probe,
            prot=NONSECURE_PROT,
            want=RESP_DECERR,
            label="S1_ns_wr_block",
            write=True,
            wdata=0xB5B50002,
        )
        ns_rd, ns_rr = await self._axi_rw(master, probe, prot=NONSECURE_PROT, write=False)
        if ns_rr != RESP_DECERR:
            raise AssertionError(
                f"S1 NS read expected DECERR got {resp_name(ns_rr)} data=0x{ns_rd:08x}"
            )
        self.ns_block_ok = True
        self._log("CHK-SMU-ALLOW-NS-S1: allow_ns=0 secure OKAY / NS DECERR on VERSION_LO")

        # ---- S2: dual-slot admit both ----
        await self._program_inst(jtag, 0, lo, hi, CFG_SECURE_ONLY, "S2_I0")
        await self._program_inst(jtag, 1, lo, hi, CFG_NS_ONLY, "S2_I1")
        for prot, label in (
            (SECURE_PROT, "secure"),
            (NONSECURE_PROT, "ns"),
        ):
            await self._await_axi_resp(
                master,
                probe,
                prot=prot,
                want=RESP_OKAY,
                label=f"S2_{label}_wr_ready",
                write=True,
                wdata=0xC5C50003,
            )
            rd, rr = await self._axi_rw(master, probe, prot=prot, write=False)
            if rr != RESP_OKAY:
                raise AssertionError(
                    f"S2 {label} read expected OKAY got {resp_name(rr)} data=0x{rd:08x}"
                )
        self.dual_ok = True
        self._log("CHK-SMU-ALLOW-NS-S2: dual-slot admits secure and NS prot on VERSION_LO")

        # ---- S3: clear → BlockByDefault ----
        await self._disable_inst(jtag, 1)
        await self._disable_inst(jtag, 0)
        for prot, label in (
            (SECURE_PROT, "secure"),
            (NONSECURE_PROT, "ns"),
        ):
            rd, rr = await self._await_axi_resp(
                master,
                probe,
                prot=prot,
                want=RESP_DECERR,
                label=f"S3_{label}_block",
                write=False,
            )
            self._log(f"S3 {label} DECERR data=0x{rd & 0xFFFF_FFFF:08x}")
        self.clear_ok = True
        self._log("CHK-SMU-ALLOW-NS-S3: clear → DECERR for secure and NS")
        sb.expect_eq("CHK-SMU-ALLOW-NS-S1", self.secure_ok and self.ns_block_ok, True)
        sb.expect_eq("CHK-SMU-ALLOW-NS-S2", self.dual_ok, True)
        sb.expect_eq("CHK-SMU-ALLOW-NS-S3", self.clear_ok, True)
        sb.expect_eq(
            "CHK-SMU-ALLOW-NS-BASIC",
            self.secure_ok and self.ns_block_ok and self.dual_ok and self.clear_ok,
            True,
        )
        self._log(
            "CHK-SMU-ALLOW-NS-BASIC: s1=%s s2=%s s3=%s (inbound only; no Force)"
            % (
                self.secure_ok and self.ns_block_ok,
                self.dual_ok,
                self.clear_ok,
            )
        )
