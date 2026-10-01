# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG2AXI vs SMN concurrent write on the same CSR; no tear. SEP=1, no Force.

Concurrency is established, not assumed. The SMN writer is released only once
the JTAG2AXI write's AW handshake has been seen on the DTP -> SMC debug port,
and the four handshakes -- J2A AW and B at that port, SMN AW and B at the SMU
boundary -- are timestamped. The race holds when the SMN write was accepted
before the J2A write's response came back, so both writes were outstanding in
the SMC at the same time.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, Event, First, RisingEdge, Timer
from cocotb.utils import get_sim_time
from ocah_axi_vip import RESP_OKAY
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import (
    SMC_CHIP_CONFIG_CHIP_ID,
    SMC_CHIP_CONFIG_VERSION_LO,
    SMC_CHIP_CONFIG_VERSION_LO_RESET,
)
from seq_lib.smu_axi_helpers import (
    axi_read32_resp_bounded,
    axi_write32_resp_bounded,
    make_smu_axi_master,
)
from seq_lib.smu_filter_helpers import (
    SCRATCH_COLD_ADDR,
    await_smn_resp,
    program_inbound0_window,
    program_smc_aperture_local_alias,
)
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)
from seq_lib.smu_tb_pins import smc_primary_reset, smu_axi_in_prefix

VERSION_LO = SMC_CHIP_CONFIG_VERSION_LO
VERSION_LO_RESET = SMC_CHIP_CONFIG_VERSION_LO_RESET
PAT_J = 0x17A6_0001
PAT_S = 0x5A11_0002
WINDOW_START = SCRATCH_COLD_ADDR
WINDOW_END = SMC_CHIP_CONFIG_CHIP_ID
# The J2A AW handshake must show up within one DR shift plus fabric latency;
# a bridge that never launches is a failure here, not a hang.
J2A_AW_TIMEOUT_NS = 200_000


class smu_jtag2axi_vs_smn_same_csr_race_test_seq:
    """Race J2A vs SMN on SCRATCH_COLD; coherent winner, no tear."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.s1_ok = False
        self.s2_ok = False
        self.s3_ok = False
        self.s4_ok = False
        self.winner = 0

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _sample_int(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on OSS tb_top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val)

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        dut = self.dut

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        # SEP=1 wrapper: route ext_in local addresses through the crossbar.
        await program_smc_aperture_local_alias(jtag, scoreboard=sb)

        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        gate = self._sample_int("tb_smc_jtag2axi_security_disable") & 1
        if gate != 0:
            raise AssertionError(f"SMC J2A still gated after TCK sync: security_disable={gate}")
        self.s1_ok = True
        sb.expect_eq("CHK-J2ASMN-GATE-OPEN", gate, 0)

        master = await make_smu_axi_master(dut, dut.clk_smu_i, smc_primary_reset(dut))
        await program_inbound0_window(jtag, WINDOW_START, WINDOW_END, scoreboard=sb, tag="RACE")
        await await_smn_resp(
            master,
            SCRATCH_COLD_ADDR,
            RESP_OKAY,
            clk=dut.clk_smu_i,
            label="pre-race SCRATCH SMN ready",
        )

        st0, _ = await jtag2axi_single_write(
            jtag,
            SCRATCH_COLD_ADDR,
            0,
            wstrb=0xF,
            size=SMC_DBG_AXSIZE_4B,
            require_complete=True,
        )
        require_jtag_tdo_resolved("pre-race scratch clear")
        if st0 != J2A_STATUS_SUCCESS:
            raise AssertionError(f"pre-race scratch clear status={st0}")
        sb.expect_eq("CHK-J2ASMN-CLEAR", st0, J2A_STATUS_SUCCESS)

        j_result: dict = {}
        s_result: dict = {}
        ts: dict[str, float] = {}
        period_ns = float(self.cfg.smu_clk_period_ns)
        aw0 = self._sample_int("dtp_smc_dbg_aw_count_o")
        b0 = self._sample_int("dtp_smc_dbg_b_count_o")
        j_aw_seen = Event()
        prefix = smu_axi_in_prefix(dut)
        smn_awvalid = getattr(dut, f"{prefix}_awvalid")
        smn_awready = getattr(dut, f"{prefix}_awready")
        smn_bvalid = getattr(dut, f"{prefix}_bvalid")
        smn_bready = getattr(dut, f"{prefix}_bready")

        async def _watch_j2a_port():
            # The TB counters register one cycle after the handshake they
            # count, so each stamp is pulled back by one period.
            while "j_b" not in ts:
                await RisingEdge(dut.clk_smu_i)
                now = float(get_sim_time(unit="ns")) - period_ns
                if "j_aw" not in ts and self._sample_int("dtp_smc_dbg_aw_count_o") > aw0:
                    ts["j_aw"] = now
                    j_aw_seen.set()
                if "j_b" not in ts and self._sample_int("dtp_smc_dbg_b_count_o") > b0:
                    ts["j_b"] = now

        async def _watch_smn_port():
            while "s_b" not in ts:
                await RisingEdge(dut.clk_smu_i)
                now = float(get_sim_time(unit="ns"))
                if "s_aw" not in ts and int(smn_awvalid.value) and int(smn_awready.value):
                    ts["s_aw"] = now
                if "s_b" not in ts and int(smn_bvalid.value) and int(smn_bready.value):
                    ts["s_b"] = now

        async def _jtag_writer():
            st, _ = await jtag2axi_single_write(
                jtag,
                SCRATCH_COLD_ADDR,
                PAT_J,
                wstrb=0xF,
                size=SMC_DBG_AXSIZE_4B,
                require_complete=True,
            )
            require_jtag_tdo_resolved("race J2A write")
            j_result["st"] = st

        async def _smn_writer():
            resp = await axi_write32_resp_bounded(
                master, SCRATCH_COLD_ADDR, PAT_S, label="race SMN write"
            )
            s_result["resp"] = resp

        t_j = cocotb.start_soon(_jtag_writer())
        t_watch_j = cocotb.start_soon(_watch_j2a_port())
        # Gate the second writer on the first writer's issue.
        await First(j_aw_seen.wait(), Timer(J2A_AW_TIMEOUT_NS, unit="ns"))
        if "j_aw" not in ts:
            raise AssertionError(
                f"race J2A write: no AW handshake on the DTP->SMC debug port within "
                f"{J2A_AW_TIMEOUT_NS} ns; nothing to race against"
            )
        t_watch_s = cocotb.start_soon(_watch_smn_port())
        t_s = cocotb.start_soon(_smn_writer())
        await t_j
        await t_s
        await First(t_watch_j.join(), Timer(J2A_AW_TIMEOUT_NS, unit="ns"))
        await First(t_watch_s.join(), Timer(J2A_AW_TIMEOUT_NS, unit="ns"))
        if j_result.get("st") != J2A_STATUS_SUCCESS:
            raise AssertionError(f"race J2A write status={j_result.get('st')}")
        if s_result.get("resp") != RESP_OKAY:
            raise AssertionError(f"race SMN write resp={s_result.get('resp')}")
        for stamp in ("j_aw", "j_b", "s_aw", "s_b"):
            if stamp not in ts:
                raise AssertionError(f"race: handshake {stamp} was never observed; stamps={ts}")
        self._log(
            "RACE_J2A_SMN handshakes ns: J2A aw=%.1f b=%.1f  SMN aw=%.1f b=%.1f  "
            "(SMN aw - J2A aw = %.1f, J2A b - SMN aw = %.1f)"
            % (
                ts["j_aw"],
                ts["j_b"],
                ts["s_aw"],
                ts["s_b"],
                ts["s_aw"] - ts["j_aw"],
                ts["j_b"] - ts["s_aw"],
            )
        )
        overlapped = ts["j_aw"] <= ts["s_aw"] < ts["j_b"]
        if not overlapped:
            raise AssertionError(
                "race: the SMN write was not accepted while the J2A write was outstanding "
                f"(J2A aw={ts['j_aw']:.1f} b={ts['j_b']:.1f}, SMN aw={ts['s_aw']:.1f} ns); "
                "the two writes did not overlap"
            )
        self.s2_ok = True
        sb.expect_eq("CHK-J2ASMN-WR-J", j_result["st"], J2A_STATUS_SUCCESS)
        sb.expect_eq("CHK-J2ASMN-WR-S", s_result["resp"], RESP_OKAY)
        sb.expect_eq(
            "CHK-J2ASMN-OVERLAP SMN accepted inside the J2A AW..B window", overlapped, True
        )

        await ClockCycles(dut.clk_smu_i, 64)
        st_r, jdata = await jtag2axi_single_read(
            jtag,
            SCRATCH_COLD_ADDR,
            size=SMC_DBG_AXSIZE_4B,
            require_complete=True,
        )
        require_jtag_tdo_resolved("post-race J2A read")
        if st_r != J2A_STATUS_SUCCESS:
            raise AssertionError(f"post-race J2A read status={st_r}")
        j_val = int(jdata) & 0xFFFF_FFFF
        s_val, s_resp = await axi_read32_resp_bounded(
            master, SCRATCH_COLD_ADDR, label="post-race SMN read"
        )
        if s_resp != RESP_OKAY:
            raise AssertionError(f"post-race SMN read resp={s_resp}")
        s_val = int(s_val) & 0xFFFF_FFFF
        if j_val != s_val:
            raise AssertionError(f"post-race J2A=0x{j_val:08x} SMN=0x{s_val:08x} disagree")
        if j_val not in (PAT_J, PAT_S):
            raise AssertionError(
                f"post-race tear: got 0x{j_val:08x} not in (0x{PAT_J:08x}, 0x{PAT_S:08x})"
            )
        self.winner = j_val
        self.s3_ok = True
        self._log(f"RACE_J2A_SMN winner=0x{j_val:08x} agents agree")
        sb.expect_eq(
            "CHK-RACE-J2A-SMN agents agree",
            j_val,
            s_val,
            evidence="RACE_J2A_SMN",
        )

        st_v, r_v = await jtag2axi_single_read(jtag, VERSION_LO, require_complete=True)
        require_jtag_tdo_resolved("post-race VERSION_LO")
        if st_v != J2A_STATUS_SUCCESS or (int(r_v) & 0xFFFF_FFFF) != VERSION_LO_RESET:
            raise AssertionError(f"post-race J2A VERSION_LO status={st_v} data=0x{int(r_v):08x}")
        v_smn, v_resp = await axi_read32_resp_bounded(
            master, VERSION_LO, label="post-race SMN VERSION"
        )
        if v_resp != RESP_OKAY or (int(v_smn) & 0xFFFF_FFFF) != VERSION_LO_RESET:
            raise AssertionError(f"post-race SMN VERSION resp={v_resp} data=0x{int(v_smn):08x}")
        self.s4_ok = True
        sb.expect_eq("CHK-J2ASMN-VERSION", int(r_v) & 0xFFFF_FFFF, VERSION_LO_RESET)
