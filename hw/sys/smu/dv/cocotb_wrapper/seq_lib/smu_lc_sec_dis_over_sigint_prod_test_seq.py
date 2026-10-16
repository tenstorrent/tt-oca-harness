# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A matched security-disable token in PROD opens every debug path, also under a sigint injection.

Spec: hw/sys/sep/doc/security_disable.adoc (a token match overrides the lifecycle control and
forces every feature-control bit on), hw/sys/sep/doc/lifecycle_controller.adoc (feature-control
profile, "DTP path feature gates", the override applies after the integrity fail-closed),
hw/sys/sep/doc/otp_fuse_controller.adoc (PROD admits only the eFuse MMR token block over JTAG),
hw/ip/efuse/regs/efuse_mmr.rdl (token words, TOKEN_EOP, match code),
hw/ip/jtag/jtag_stap/doc/architecture.adoc and hw/ip/jtag/jtag_intf_unit/doc/architecture.adoc
(STAP host TMS, iJTAG SIBs), hw/sys/dtp/doc/jtag.adoc (SMC fabric bridge).

The PROD eFuse shadow image is the only stimulus besides the JTAG accesses and
``lc_sigint_inject_i``. The steps run in this order:

S1, setup: ``+lc_sigint_inject`` armed, ``lc_sigint_inject_i`` low, ``sep_fuse_sense_done_o`` rises.
S2, closed posture: ``lcc_feat_ctrl_o``, the security-disable net at the SMU and at the SMC, the
    SEP STAP host TMS, the SMC fabric AW/AR/B counters over one SINGLE_OP read and write, and a
    SEC_DISABLE_TOKEN_MATCH read over the SEP OTP bridge as the positive control.
S3, token: eight all-zero token words, TOKEN_EOP with the go bit, a SEC_DISABLE_TOKEN_I[0] read
    and the match read, every access over the SEP OTP bridge.
S4, net: the security-disable net at the SMU and at the SMC.
S5, feature control: ``lcc_feat_ctrl_o``.
S6, SEP STAP: selected over the PTAP, its host TMS follows the PTAP TMS.
S7, other STAPs: the same for the I/O, SMC and extra STAPs.
S8, SIBs: under SELECT_IJTAG the three SIBs open, capture 1 and their bench cells join the loop.
S9, fabric: one SINGLE_OP read and write launch AR, AW and B.
S10, injection: ``lc_sigint_inject_i`` raised; feature control, the SEP STAP host TMS and the
    fabric launch hold; ``lc_sigint_err_o`` and the SMC OTP responses are measured and logged only.
S11, release: ``lc_sigint_inject_i`` lowered; feature control holds.
Every bounded wait reports its bound, the cycles it used and the last observed state.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_boundary_regs import (
    SMU_SEP_STAP_ORDER,
    ptap_prefixed,
    stap_3dcr_scan_word,
    stap_sib_pattern,
)
from seq_lib.smu_compose_helpers import hier, sample
from seq_lib.smu_dtp_scan_chain_boundary_seq import (
    DTP_IR_SELECT_IJTAG,
    ijtag_chain,
    ijtag_shift,
    ijtag_word,
)
from seq_lib.smu_dtp_sep_dm_dmi_test_seq import MIN_PTAP_TMS_EDGES, SEP_STAP_TMS
from seq_lib.smu_jtag_helpers import (
    DTP_IR_IDCODE,
    DTP_IR_TAP_3DCR,
    DTP_IR_WIDTH,
    J2A_OP_WRITE,
    J2A_STATUS_BUSY,
    J2A_STATUS_SUCCESS,
    PTAP_3DCR_WIDTH,
    SMC_OTP_AXSIZE_4B,
    otp_jtag2axi_single_read,
    otp_jtag2axi_single_write,
    pack_otp_single_op,
    ptap_3dcr_value,
    require_jtag_tdo_resolved,
    unpack_otp_single_op,
)
from seq_lib.smu_lc_export_seq import (
    FEAT_CTRL_ALL_ENABLED,
    FEAT_CTRL_FUNCTION_ONLY,
    IJTAG_DR_BIT,
    IJTAG_FLUSH_OPEN_REQUEST,
    LANE_DISABLED,
    LAUNCHED_AR_AW_B,
    NOT_LAUNCHED,
    OTP_POLL_BOUND,
    ExportSpec,
    _ReadCounter,
    smu_lc_export_seq,
)
from seq_lib.smu_lc_sigint_fail_closed_seq import INJECT_TAKE_CYCLES
from seq_lib.smu_lifecycle_table import LC_RAW, lc_state_word
from seq_lib.smu_otp_bridges_under_dbg_disable_seq import SMC_EFUSE_SPARE0, SMC_SPARE_PATTERN
from seq_lib.smu_sep_sba_peripheral_test_seq import (
    SECURITY_DISABLE_PATH,
    SECURITY_DISABLE_SMC_PATH,
    TOKEN_EOP,
    TOKEN_GO,
    TOKEN_MATCH,
    TOKEN_MATCH_CODE,
    TOKEN_STATUS_MASK,
    TOKEN_WORDS,
)
from seq_lib.smu_sep_stap_hold_reset_test_seq import TMS_WINDOW_CYCLES
from seq_lib.smu_tb_pins import smu_scope

SPEC = ExportSpec(
    state="PROD",
    tag="PROD",
    image="sep_efuse_shadow_lc_prod.preload",
    feat_ctrl=FEAT_CTRL_FUNCTION_ONLY,
    lane=LANE_DISABLED,
    inject=True,
)

#: hw/sys/sep/doc/security_disable.adoc: the security-disable net is low before a token match and
#: high after it.
SECURITY_DISABLE_LOW = 0
SECURITY_DISABLE_HIGH = 1
#: hw/ip/efuse/regs/efuse_mmr.rdl, SEC_DISABLE_TOKEN_I: the token words the bench binds as its
#: expected digest preimage are all zero (hw/sys/sep/doc/security_disable.adoc, token activation).
TOKEN_WORD_VALUE = 0
#: hw/sys/sep/doc/otp_fuse_controller.adoc: PROD admits the eFuse MMR token block, so each access
#: completes with the success response (J2A status 0).
TOKEN_OP_ADMITTED = J2A_STATUS_SUCCESS
#: Full-word byte strobes of a 32-bit eFuse MMR access (hw/ip/efuse/regs/efuse_mmr.rdl).
OTP_WRITE_WSTRB = 0xF
#: Polls of the match read before the wait expires.
MATCH_POLL_BOUND = 8

#: hw/sys/dtp/doc/jtag.adoc "STAP Secondary Scan Path", hw/sys/smu/doc/port_table.adoc: host TMS
#: and TDO-enable taps of each STAP.
STAP_TMS_PATH = {
    "sep": SEP_STAP_TMS,
    "io": "tb_stap_io_tms",
    "smc": "tb_stap_smc_tms",
    "extra0": "tb_stap_extra0_tms",
}
STAP_OEN_PATH = {
    "sep": "u_dut.u_smu.u_dtp.jtag_stap_sep_host_tdo_oen_o",
    "io": "tb_stap_io_tdo_oen",
    "smc": "tb_stap_smc_tdo_oen",
    "extra0": "tb_stap_extra0_tdo_oen",
}
#: Clock cycles of ``clk_ref_i`` the host TMS watch covers around one IDCODE IR and DR scan.
STAP_IDCODE_WINDOW_CYCLES = 2 * TMS_WINDOW_CYCLES
STAP_IDCODE_DR_BITS = 32
TLR_TMS_HIGHS = 5
IDLE_TCKS_AFTER_TLR = 8

#: hw/ip/jtag/jtag_intf_unit/doc/architecture.adoc "iJTAG Network": a scan wide enough for the
#: six-cell open chain and a nonzero payload behind it.
IJTAG_OPEN_SCAN_BITS = 12
IJTAG_FLUSH_OPEN_CHAIN = 0b101100

#: Bench fault-inject definition (tb/tb_wrapper_top.sv, LC_STATE pair fault inject): the n rail
#: of bit 0 is inverted while lc_sigint_inject_i is high.
LC_PAIR_FLIP = 0x10
LC_PROD_WORD = lc_state_word(LC_RAW["PROD"])
LC_PROD_BROKEN_WORD = LC_PROD_WORD ^ LC_PAIR_FLIP


class smu_lc_sec_dis_over_sigint_prod_test_seq(smu_lc_export_seq):
    """The PROD closed posture, a token match over the SEP OTP bridge, then every path open."""

    def __init__(self, test) -> None:
        super().__init__(test, SPEC)

    def _net(self) -> tuple[int, int]:
        scope = smu_scope(self.dut)
        return (
            sample(hier(scope, SECURITY_DISABLE_PATH), SECURITY_DISABLE_PATH),
            sample(hier(scope, SECURITY_DISABLE_SMC_PATH), SECURITY_DISABLE_SMC_PATH),
        )

    async def _feat(self) -> int:
        await RisingEdge(self.dut.clk_smu_i)
        return self._rd("lcc_feat_ctrl_o")

    async def _sep_otp_write(self, addr: int, data: int, name: str) -> int:
        """One SEP OTP SINGLE_OP write; returns the response status."""
        await self._ensure_tap()
        counter = _ReadCounter(self.tap)
        raw = pack_otp_single_op(
            J2A_OP_WRITE, addr, data, wstrb=OTP_WRITE_WSTRB, size=SMC_OTP_AXSIZE_4B
        )
        await self.tap.write("SEP_OTP_AXI_SINGLE_OP", raw)
        require_jtag_tdo_resolved(f"SEP OTP J2A WR issue {name}")
        await ClockCycles(self.dut.clk_smu_i, 32)
        status = J2A_STATUS_BUSY
        for _ in range(OTP_POLL_BOUND):
            capt = await counter.read("SEP_OTP_AXI_SINGLE_OP", shift_value=0)
            require_jtag_tdo_resolved(f"SEP OTP J2A WR poll {name}")
            status, _ = unpack_otp_single_op(capt)
            if status != J2A_STATUS_BUSY:
                break
            await ClockCycles(self.dut.clk_smu_i, 16)
        last = f"status={status}"
        self._record(
            "otp_write",
            OTP_POLL_BOUND,
            counter.reads,
            "polls",
            last,
            expired=(status == J2A_STATUS_BUSY),
        )
        self._log(f"CELL sep_otp_write {name} @0x{addr:08x} data=0x{data:08x} {last}")
        return status

    async def _tlr(self) -> None:
        """Return the TAP to Test-Logic-Reset on TMS alone, then to Run-Test/Idle."""
        await self._ensure_tap()
        for _ in range(TLR_TMS_HIGHS):
            await self.jtag.step_tms(1)
        self.jtag.sync_model(OcahJtagState.TEST_LOGIC_RESET)
        await self.jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(IDLE_TCKS_AFTER_TLR):
            await self.jtag.step_tms(0)

    async def _select_stap(self, name: str) -> None:
        """TAP_3DCR select of one STAP: PTAP select, its SIB, then its 3DCR with Select set."""
        await self._scan_ir(DTP_IR_TAP_3DCR, DTP_IR_WIDTH, "TAP_3DCR")
        await self._scan_dr(
            ptap_3dcr_value(config_hold=0, select=1), PTAP_3DCR_WIDTH, f"PTAP select {name}"
        )
        await self.jtag.step_tms(0)
        await self.jtag.step_tms(0)
        sib_word, sib_width = ptap_prefixed(
            stap_sib_pattern(name, 1), len(SMU_SEP_STAP_ORDER), config_hold=0
        )
        await self._scan_dr(sib_word, sib_width, f"open {name} SIB")
        stap_word, stap_width = stap_3dcr_scan_word(
            name, config_hold=0, stap_sel=1, tms_hold=1, sib_en=0
        )
        value, width = ptap_prefixed(stap_word, stap_width, config_hold=0)
        await self._scan_dr(value, width, f"write {name} 3DCR select")

    async def _stap_follow(self, name: str, tag: str = "") -> dict:
        """Select one STAP, then watch its host TMS and TDO enable over an IDCODE IR and DR scan."""
        await self._tlr()
        await self._select_stap(name)
        win = {"scan_done": False}
        monitor = cocotb.start_soon(
            self._tms_monitor(
                win,
                hier(self.dut, STAP_OEN_PATH[name]),
                STAP_TMS_PATH[name],
                STAP_IDCODE_WINDOW_CYCLES,
            )
        )
        await self._scan_ir(DTP_IR_IDCODE, DTP_IR_WIDTH, f"IDCODE {name}")
        await self._scan_dr(0, STAP_IDCODE_DR_BITS, f"IDCODE DR {name}")
        win["scan_done"] = True
        obs = await monitor
        done = obs["done"]
        self._record(
            f"stap_window_{name}{tag}",
            STAP_IDCODE_WINDOW_CYCLES,
            done if done is not None else STAP_IDCODE_WINDOW_CYCLES,
            "cycles",
            f"levels={sorted(obs['levels'])} ptap_edges={obs['ptap_edges']} "
            f"host_edges={obs['sep_edges']} oen_highs={obs['oen_highs']}",
            expired=done is None,
        )
        return obs

    @staticmethod
    def _follows(obs: dict) -> tuple[bool, bool, bool, bool]:
        """(host edges equal PTAP edges, PTAP edges at least the IR length, both levels, TDO
        enable)."""
        return (
            obs["sep_edges"] == obs["ptap_edges"],
            obs["ptap_edges"] >= MIN_PTAP_TMS_EDGES,
            sorted(obs["levels"]) == [0, 1],
            obs["oen_highs"] > 0,
        )

    async def _set_inject(self, value: int, want_lc: int) -> None:
        """Drive ``lc_sigint_inject_i``; return once ``lc_state_o`` carries the expected word."""
        self.dut.lc_sigint_inject_i.value = value
        for cycle in range(1, INJECT_TAKE_CYCLES + 1):
            await ClockCycles(self.dut.clk_smu_i, 1)
            word = self._rd("lc_state_o")
            if word == want_lc:
                self._record(
                    f"inject_{value}",
                    INJECT_TAKE_CYCLES,
                    cycle,
                    "cycles",
                    f"lc_state_o=0x{word:02x}",
                )
                return
        self._record(
            f"inject_{value}",
            INJECT_TAKE_CYCLES,
            INJECT_TAKE_CYCLES,
            "cycles",
            f"lc_state_o=0x{self._rd('lc_state_o'):02x} want=0x{want_lc:02x}",
            expired=True,
        )

    async def _smc_otp_logged(self) -> None:
        """An SMC OTP read and write whose responses are measured and logged only."""
        await self._ensure_tap()
        counter = _ReadCounter(self.tap)
        status, rdata = await otp_jtag2axi_single_read(
            counter, SMC_EFUSE_SPARE0, poll_limit=OTP_POLL_BOUND
        )
        self._record(
            "smc_otp_read_inject",
            OTP_POLL_BOUND,
            counter.reads,
            "polls",
            f"status={status}",
            expired=(status == J2A_STATUS_BUSY),
        )
        self._log(
            f"OBSERVATION CHK-LC-SECDIS-OVER-SIGINT-PROD: smc_otp_read status={status} "
            f"rdata=0x{int(rdata) & 0xFFFF_FFFF:08x} (measured and logged only)"
        )
        counter = _ReadCounter(self.tap)
        status, _ = await otp_jtag2axi_single_write(
            counter, SMC_EFUSE_SPARE0, SMC_SPARE_PATTERN, poll_limit=OTP_POLL_BOUND
        )
        self._record(
            "smc_otp_write_inject",
            OTP_POLL_BOUND,
            counter.reads,
            "polls",
            f"status={status}",
            expired=(status == J2A_STATUS_BUSY),
        )
        self._log(
            f"OBSERVATION CHK-LC-SECDIS-OVER-SIGINT-PROD: smc_otp_write status={status} "
            "(measured and logged only)"
        )

    def _log_sigint_err(self, where: str) -> None:
        self._log(
            f"OBSERVATION CHK-LC-SECDIS-OVER-SIGINT-PROD: "
            f"lc_sigint_err_o={self._rd('lc_sigint_err_o')} "
            f"{where} (measured and logged only)"
        )

    async def run(self) -> None:
        await self._mark(
            "SETUP: PROD shadow image, +lc_sigint_inject armed, wait for sep_fuse_sense_done_o"
        )
        await self._setup()
        assert self._rd("lc_sigint_inject_i") == 0, "lc_sigint_inject_i must start low"

        await self._mark("CLOSED POSTURE: feature control, net, SEP STAP, fabric, OTP control read")
        feat_before = await self._feat()
        net_before = self._net()
        stap_levels, stap_edges, stap_oen, stap_ptap, stap_select = await self._stap_parked_probe()
        start, end, delta_before = await self._fabric_deltas(launches=False)
        control_op, match_before = await self._sep_otp_read(
            TOKEN_MATCH, "SEC_DISABLE_TOKEN_MATCH before the token"
        )
        match_before &= TOKEN_STATUS_MASK
        self._log(
            f"CELL closed_posture feat=0x{feat_before:016x} net={net_before} "
            f"stap_levels={stap_levels} stap_edges={stap_edges} stap_oen={stap_oen} "
            f"stap_ptap_edges={stap_ptap} stap_select={stap_select} fabric {start}->{end} "
            f"match_before=0x{match_before:02x} control_op={control_op}"
        )

        await self._mark(
            "TOKEN: eight zero words, go bit, I[0] read, match read over the SEP OTP bridge"
        )
        write_ops = [
            await self._sep_otp_write(addr, TOKEN_WORD_VALUE, f"SEC_DISABLE_TOKEN_I[{i}]")
            for i, addr in enumerate(TOKEN_WORDS)
        ]
        eop_op = await self._sep_otp_write(TOKEN_EOP, TOKEN_GO, "TOKEN_EOP go")
        word0_op, word0 = await self._sep_otp_read(TOKEN_WORDS[0], "SEC_DISABLE_TOKEN_I[0]")
        self._log(
            f"OBSERVATION SEC_DISABLE_TOKEN_I[0] data=0x{word0:08x} (measured and logged only)"
        )
        match_reads = 0
        match_op, match_after = control_op, match_before
        for _ in range(MATCH_POLL_BOUND):
            match_op, raw = await self._sep_otp_read(TOKEN_MATCH, "SEC_DISABLE_TOKEN_MATCH")
            match_after = raw & TOKEN_STATUS_MASK
            match_reads += 1
            if match_after != match_before:
                break
        self._record(
            "token_match",
            MATCH_POLL_BOUND,
            match_reads,
            "polls",
            f"status=0x{match_after:02x} before=0x{match_before:02x}",
            expired=(match_after == match_before),
        )
        self._check(
            "CHK-LC-SECDIS-TOKEN-MATCH-JTAG-PROD",
            f"match status before=0x{match_before:02x} after=0x{match_after:02x} "
            f"want_after=0x{TOKEN_MATCH_CODE:02x} control_op={control_op}",
            (control_op, match_before != TOKEN_MATCH_CODE, match_after),
            (TOKEN_OP_ADMITTED, True, TOKEN_MATCH_CODE),
        )
        self._check(
            "CHK-LC-OTP-SEP-POLICY-PROD-MMR",
            f"ops writes={write_ops} eop={eop_op} read_i0={word0_op} read_match={match_op} "
            f"match=0x{match_after:02x}",
            (write_ops, eop_op, word0_op, match_op, match_after),
            (
                [TOKEN_OP_ADMITTED] * len(TOKEN_WORDS),
                TOKEN_OP_ADMITTED,
                TOKEN_OP_ADMITTED,
                TOKEN_OP_ADMITTED,
                TOKEN_MATCH_CODE,
            ),
        )

        await self._mark("NET: security-disable net at the SMU and at the SMC")
        await RisingEdge(self.dut.clk_smu_i)
        net_after = self._net()
        self._check(
            "CHK-LC-SECDIS-NET-PROD",
            f"net (SMU, SMC) before={net_before} after={net_after}",
            (net_before, net_after),
            (
                (SECURITY_DISABLE_LOW, SECURITY_DISABLE_LOW),
                (SECURITY_DISABLE_HIGH, SECURITY_DISABLE_HIGH),
            ),
        )

        await self._mark("FEATURE CONTROL: lcc_feat_ctrl_o after the match")
        feat_after = await self._feat()
        self._check(
            "CHK-LC-SECDIS-FEATCTRL-PROD",
            f"lcc_feat_ctrl_o before=0x{feat_before:016x} after=0x{feat_after:016x}",
            (feat_before, feat_after),
            (FEAT_CTRL_FUNCTION_ONLY, FEAT_CTRL_ALL_ENABLED),
        )

        await self._mark("SEP STAP selected over the PTAP while the PTAP TMS toggles")
        sep_obs = await self._stap_follow("sep")
        self._check(
            "CHK-LC-SECDIS-SEP-STAP-OPEN-PROD",
            f"closed levels={stap_levels} host_edges={stap_edges} oen_highs={stap_oen} "
            f"ptap_edges={stap_ptap}; open levels={sorted(sep_obs['levels'])} "
            f"host_edges={sep_obs['sep_edges']} ptap_edges={sep_obs['ptap_edges']} "
            f"oen_highs={sep_obs['oen_highs']}",
            (
                stap_levels,
                stap_edges,
                stap_oen,
                stap_ptap >= MIN_PTAP_TMS_EDGES,
                *self._follows(sep_obs),
                sep_obs["sep_edges"] > stap_edges,
            ),
            ([0], 0, 0, True, True, True, True, True, True),
        )

        await self._mark("I/O, SMC and extra STAPs selected over the PTAP")
        others = {name: await self._stap_follow(name) for name in ("io", "smc", "extra0")}
        self._check(
            "CHK-LC-SECDIS-OTHER-STAPS-OPEN-PROD",
            " ".join(
                f"{name}: host_edges={o['sep_edges']} ptap_edges={o['ptap_edges']} "
                f"oen_highs={o['oen_highs']}"
                for name, o in others.items()
            ),
            {name: self._follows(o) for name, o in others.items()},
            {name: (True, True, True, True) for name in others},
        )

        await self._mark("SELECT_IJTAG: shift 1 into the three SIBs, then capture")
        await self._tlr()
        await self.jtag.shift_ir(DTP_IR_SELECT_IJTAG, back_to_rti=True)
        closed = frozenset()
        everything = frozenset(IJTAG_DR_BIT)
        open_word = ijtag_word(closed, everything, IJTAG_FLUSH_OPEN_REQUEST, IJTAG_OPEN_SCAN_BITS)
        cap_word = ijtag_word(everything, everything, IJTAG_FLUSH_OPEN_CHAIN, IJTAG_OPEN_SCAN_BITS)
        want_open = ijtag_shift(closed, open_word, IJTAG_OPEN_SCAN_BITS)[0]
        want_cap = ijtag_shift(everything, cap_word, IJTAG_OPEN_SCAN_BITS)[0]
        got_open, _ = await self._ijtag_scan(open_word, 1, IJTAG_OPEN_SCAN_BITS)
        got_cap, counts = await self._ijtag_scan(cap_word, 2, IJTAG_OPEN_SCAN_BITS)
        chain = ijtag_chain(everything)
        capture_bits = {
            name: (got_cap >> (len(chain) - 1 - chain.index(("sib", name)))) & 1
            for name in IJTAG_DR_BIT
        }
        selects = {name: counts[name] for name in IJTAG_DR_BIT}
        self._check(
            "CHK-LC-SECDIS-SIBS-OPEN-PROD",
            f"SIB captures={capture_bits} open scan out=0x{got_open:x} want=0x{want_open:x} "
            f"open-chain scan out=0x{got_cap:x} want=0x{want_cap:x} host_selects={selects} "
            f"tck_seen={counts['tck']} chain_cells={len(chain)}",
            (
                capture_bits,
                got_open == want_open,
                got_cap == want_cap,
                {name: selects[name] >= IJTAG_OPEN_SCAN_BITS for name in selects},
            ),
            (
                dict.fromkeys(IJTAG_DR_BIT, 1),
                True,
                True,
                dict.fromkeys(IJTAG_DR_BIT, True),
            ),
        )

        await self._mark("SMC fabric SINGLE_OP read then write after the match")
        start, end, delta_after = await self._fabric_deltas(launches=True, tag="_open")
        self._check(
            "CHK-LC-SECDIS-FABRIC-LAUNCH-PROD",
            f"AR/AW/B deltas before={delta_before} after={delta_after} counts {start}->{end} "
            f"otp_control_op={control_op}",
            (delta_before, delta_after, control_op),
            (NOT_LAUNCHED, LAUNCHED_AR_AW_B, TOKEN_OP_ADMITTED),
        )

        await self._mark("INJECTION: lc_sigint_inject_i raised with the match held")
        await self._set_inject(1, LC_PROD_BROKEN_WORD)
        self._log_sigint_err("while injected")
        feat_inject = await self._feat()
        inject_obs = await self._stap_follow("sep", "_inject")
        _, _, delta_inject = await self._fabric_deltas(launches=True, tag="_inject")
        await self._smc_otp_logged()
        lc_injected = self._rd("lc_state_o")

        await self._mark("RELEASE: lc_sigint_inject_i lowered")
        await self._set_inject(0, LC_PROD_WORD)
        self._log_sigint_err("after release")
        feat_release = await self._feat()
        self._check(
            "CHK-LC-SECDIS-OVER-SIGINT-PROD",
            f"injected lc_state_o=0x{lc_injected:02x} feat=0x{feat_inject:016x} "
            f"sep_host_edges={inject_obs['sep_edges']} ptap_edges={inject_obs['ptap_edges']} "
            f"fabric deltas={delta_inject}; released feat=0x{feat_release:016x}",
            (
                feat_inject,
                *self._follows(inject_obs),
                delta_inject,
                feat_release,
            ),
            (
                FEAT_CTRL_ALL_ENABLED,
                True,
                True,
                True,
                True,
                LAUNCHED_AR_AW_B,
                FEAT_CTRL_ALL_ENABLED,
            ),
        )

        labels = [
            "sense_done",
            *[f"stap_window_{i}" for i in range(1, 7)],
            "fabric_window_read",
            "fabric_window_write",
            *["otp_read"] * (2 + match_reads),
            *["otp_write"] * (len(TOKEN_WORDS) + 1),
            "token_match",
            "stap_window_sep",
            *[f"stap_window_{name}" for name in ("io", "smc", "extra0")],
            "ijtag_window_1",
            "ijtag_window_2",
            "fabric_ar_open",
            "fabric_b_open",
            "inject_1",
            "stap_window_sep_inject",
            "fabric_ar_inject",
            "fabric_b_inject",
            "smc_otp_read_inject",
            "smc_otp_write_inject",
            "inject_0",
        ]
        await self._finish(sorted(labels))
