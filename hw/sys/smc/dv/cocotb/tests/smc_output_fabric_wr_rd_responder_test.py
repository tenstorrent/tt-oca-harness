# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_B4_001 ANCHOR: smc_output_fabric_wr_rd_responder_test
# DV-TESTCASE-CONTRACT-REVISION: 1 RECORD-SHA256: 1f097722d433b77c42d8cb41b777b906ec1eade0d8da9284d3b28f9b3703a07a
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/docs/SMC_VPLAN.adoc section 33 `smc_output_fabric_wr_rd_responder_test` ENV: cocotb
"""SMC OSS output-fabric responder-backed protocol test."""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.utils import get_sim_time
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_output_fabric_vip_utils import (
    OUTPUT_FABRIC_ADDR,
    OUTPUT_FABRIC_DATA,
    OUTPUT_FABRIC_MODEL_REGION,
    RESP_OKAY,
    RESPONDER_OBS_TIMEOUT_CYCLES,
    check_output_responder_delta,
    jtag_axi_read,
    jtag_axi_write,
    output_fabric_model,
    output_fabric_pass_all_cfg_seq,
    output_responder_counts,
)
from seq_lib.smc_output_fabric_wr_rd_responder_test_seq import (
    RESP_USER_SEED,
    SAMPLER_CATCH_UP_CYCLES,
    USER_MASK,
    SmcRspUserSampler,
)
from smc_base_test import smc_base_test

REQUIRED = (
    "CHK-NONVAC",
    "CHK-OUTPUT-FABRIC-WR-RD-GOLDEN",
    "CHK-RSP-USER-DBG-READ",
    "CHK-RSP-USER-DBG-WRITE",
    "CHK-TIMEOUT-PATHS",
)

_FENCE = ("USER-SEEDED", "JTAG-WRITE", "JTAG-READ", "GOLDEN")


def _now_ps() -> int:
    return int(get_sim_time("ps"))


def _hex(value: int | None) -> str:
    return "X/Z" if value is None else f"0x{value:x}"


@pyuvm.test()
class smc_output_fabric_wr_rd_responder_test(smc_base_test):
    """Drive JTAG AXI through output fabric; scoreboard checks memory golden."""

    required_evidence = REQUIRED
    min_evidence = len(REQUIRED)

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        dut = cocotb.top
        start_writes = int(dut.tb_output_axi_write_count.value)
        start_reads = int(dut.tb_output_axi_read_count.value)
        output_fabric_model(self)
        sampler = SmcRspUserSampler()
        sampler_task = cocotb.start_soon(sampler.run())
        fence: list[tuple[str, int, int]] = []

        cfg_seq = output_fabric_pass_all_cfg_seq()
        await self.start_seq(cfg_seq, self.env.sys_axi_agent.sequencer)

        responder = self.env.cfg.sys_out_mem
        assert responder is not None, "SYS_OUT responder not bound"
        responder.randomize_resp_user(RESP_USER_SEED)
        cocotb.log.info(
            "STEP S1: pass-all filters programmed; SYS_OUT responder BUSER/RUSER seeded "
            "with seed=0x%x; responder write_count=%d read_count=%d",
            RESP_USER_SEED,
            start_writes,
            start_reads,
        )
        fence.append(("USER-SEEDED", _now_ps(), 1))

        cocotb.log.info(
            "STEP S2: JTAG-AXI write 0x%016x @ 0x%x", OUTPUT_FABRIC_DATA, OUTPUT_FABRIC_ADDR
        )
        wmark = sampler.mark()
        w_item = await jtag_axi_write(
            self,
            OUTPUT_FABRIC_ADDR,
            OUTPUT_FABRIC_DATA,
            update_golden=True,
            memory_region=OUTPUT_FABRIC_MODEL_REGION,
        )
        jtag_b = await sampler.wait_jtag_beat(wmark, "b", "S2 write")
        await check_output_responder_delta(
            start_writes=start_writes,
            start_reads=start_reads,
            write_delta=1,
            read_delta=0,
            last_addr=OUTPUT_FABRIC_ADDR,
            last_wdata=OUTPUT_FABRIC_DATA,
        )
        write_obs_writes, write_obs_reads = output_responder_counts(dut)
        resp_b = sampler.responder_beats(wmark, "b", jtag_b.time_ps)
        assert len(resp_b) == 1, f"S2: expected one SYS_OUT B beat for the write, saw {resp_b}"
        drv_b = resp_b[0].user
        assert drv_b is not None, "S2: SYS_OUT responder BUSER is X/Z on its B beat"
        drv_b &= USER_MASK
        assert w_item.resp_code == RESP_OKAY, f"S2: JTAG write BRESP {w_item.resp_code}"
        assert jtag_b.resp == RESP_OKAY, f"S2: JTAG port BRESP {_hex(jtag_b.resp)}"
        assert drv_b != 0, "S2: responder drew BUSER 0; the seeded stimulus left BUSER idle"
        assert jtag_b.user is not None, "S2: BUSER at the JTAG manager is X/Z"
        obs_b = jtag_b.user & USER_MASK
        cocotb.log.info(
            "CHK-RSP-USER-DBG-WRITE: seed=0x%x responder BUSER=0x%03x jtag BUSER=0x%03x "
            "equal=%s BRESP=OKAY (measured, LINKED-ISSUE SF-001; responder write_count "
            "%d -> %d, B at %d ps)",
            RESP_USER_SEED,
            drv_b,
            obs_b,
            "y" if obs_b == drv_b else "n",
            start_writes,
            write_obs_writes,
            jtag_b.time_ps,
        )
        fence.append(("JTAG-WRITE", jtag_b.time_ps, 1))

        cocotb.log.info("STEP S3: JTAG-AXI read @ 0x%x", OUTPUT_FABRIC_ADDR)
        rmark = sampler.mark()
        r_item = await jtag_axi_read(
            self,
            OUTPUT_FABRIC_ADDR,
            check_golden=True,
            memory_region=OUTPUT_FABRIC_MODEL_REGION,
        )
        jtag_r = await sampler.wait_jtag_beat(rmark, "r", "S3 read")
        resp_r = [
            b
            for b in sampler.responder_beats(rmark, "r", jtag_r.time_ps)
            if b.data == OUTPUT_FABRIC_DATA
        ]
        assert len(resp_r) == 1, (
            f"S3: expected one SYS_OUT R beat carrying 0x{OUTPUT_FABRIC_DATA:x}, saw {resp_r}"
        )
        drv_r = resp_r[0].user
        assert drv_r is not None, "S3: SYS_OUT responder RUSER is X/Z on its R beat"
        drv_r &= USER_MASK
        assert r_item.resp_code == RESP_OKAY, f"S3: JTAG read RRESP {r_item.resp_code}"
        assert jtag_r.resp == RESP_OKAY, f"S3: JTAG port RRESP {_hex(jtag_r.resp)}"
        assert r_item.rdata == OUTPUT_FABRIC_DATA, f"S3: RDATA 0x{r_item.rdata:x}"
        assert jtag_r.data == OUTPUT_FABRIC_DATA, f"S3: JTAG port RDATA {_hex(jtag_r.data)}"
        assert drv_r != 0, "S3: responder drew RUSER 0; the seeded stimulus left RUSER idle"
        assert jtag_r.user is not None, "S3: RUSER at the JTAG manager is X/Z"
        obs_r = jtag_r.user & USER_MASK
        cocotb.log.info(
            "CHK-RSP-USER-DBG-READ: seed=0x%x responder RUSER=0x%03x jtag RUSER=0x%03x "
            "equal=%s RRESP=OKAY RDATA=0x%016x (measured, LINKED-ISSUE SF-001; R at %d ps)",
            RESP_USER_SEED,
            drv_r,
            obs_r,
            "y" if obs_r == drv_r else "n",
            r_item.rdata,
            jtag_r.time_ps,
        )
        fence.append(("JTAG-READ", jtag_r.time_ps, 1))

        await check_output_responder_delta(
            start_writes=start_writes,
            start_reads=start_reads,
            write_delta=1,
            read_delta=1,
            last_addr=OUTPUT_FABRIC_ADDR,
            last_wdata=OUTPUT_FABRIC_DATA,
        )
        assert self.env.scoreboard.memory_model_updates_seen >= 1
        assert self.env.scoreboard.memory_model_checks_seen >= 1
        end_writes, end_reads = output_responder_counts(dut)
        cocotb.log.info(
            "CHK-OUTPUT-FABRIC-WR-RD-GOLDEN: JTAG AXI write 0x%016x @ 0x%x then read "
            "back through the output fabric; SYS_OUT responder write_count %d -> %d "
            "(exactly +1), read_count %d -> %d (>= +1), last_addr/last_wdata matched "
            "the write; scoreboard memory-model updates=%d, golden read checks=%d",
            OUTPUT_FABRIC_DATA,
            OUTPUT_FABRIC_ADDR,
            start_writes,
            end_writes,
            start_reads,
            end_reads,
            self.env.scoreboard.memory_model_updates_seen,
            self.env.scoreboard.memory_model_checks_seen,
        )
        fence.append(("GOLDEN", _now_ps(), self.env.scoreboard.memory_model_checks_seen))

        sampler.stop = True
        await sampler_task

        cocotb.log.info("STEP S4: every bounded wait of S2-S3 completed inside its bound")
        axi_timeout_ns = self.env.cfg.axi_timeout_ns
        waits = (
            ("jtag_b_response", f"{axi_timeout_ns}ns", f"BRESP=OKAY at {jtag_b.time_ps}ps"),
            ("jtag_b_sampler", f"{SAMPLER_CATCH_UP_CYCLES}clk_smc_i", "1 JTAG B beat"),
            (
                "responder_write_obs",
                f"{RESPONDER_OBS_TIMEOUT_CYCLES}clk_smc_i",
                f"write_count={write_obs_writes} read_count={write_obs_reads}",
            ),
            ("jtag_r_response", f"{axi_timeout_ns}ns", f"RRESP=OKAY at {jtag_r.time_ps}ps"),
            ("jtag_r_sampler", f"{SAMPLER_CATCH_UP_CYCLES}clk_smc_i", "1 JTAG R beat"),
            (
                "responder_wr_rd_obs",
                f"{RESPONDER_OBS_TIMEOUT_CYCLES}clk_smc_i",
                f"write_count={end_writes} read_count={end_reads}",
            ),
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits, %s; expiry raises AssertionError with the "
            "last observed state; 0 expired",
            len(waits),
            " ".join(f"{name}=bound:{bound} last:{last}" for name, bound, last in waits),
        )

        assert tuple(term for term, _, _ in fence) == _FENCE, f"fence terms {fence}"
        assert all(count > 0 for _, _, count in fence), f"zero-count fence term {fence}"
        times = [t for _, t, _ in fence]
        assert times[0] < times[1] < times[2] <= times[3], f"fence out of order {fence}"
        cocotb.log.info(
            "CHK-NONVAC: %s (%s)",
            " < ".join(_FENCE),
            " ".join(f"{term}=count:{count}@{t}ps" for term, t, count in fence),
        )

        await self.record_protocol_vip(
            SmcProtocolVipKind.OUTPUT_FABRIC,
            type(self).__name__,
            csr_accesses=cfg_seq.accesses,
            # Directed stimulus floor: 3 inbound + 3 outbound pass-all filter
            # CSR writes (output_fabric_pass_all_cfg_seq); a floor taken from
            # `cfg_seq.accesses` would shrink with a sequence that stopped
            # issuing them.
            min_csr_accesses=6,
            # The two JTAG-AXI accesses are fabric traffic and are reported in
            # their own field; csr_accesses counts CSR traffic only.
            fabric_accesses=2,
            min_fabric_accesses=2,
            fabric_access_label="jtag_axi_accesses",
            proxy=False,
            details=(
                "JTAG AXI WR/RD + U1-3 scoreboard SmcMemoryModel golden "
                f"(updates={self.env.scoreboard.memory_model_updates_seen} "
                f"checks={self.env.scoreboard.memory_model_checks_seen})"
            ),
        )
