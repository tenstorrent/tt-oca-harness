# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS U1-2/U1-3/U6-2: SYS_OUT error responses through the slave agent's one-shot faults.

The outbound fabric is a conduit: an error the SYS_OUT subordinate raises is
the subordinate's verdict, and the fabric's obligation is to hand the requesting
manager back the same encoding, not a downgraded, upgraded or swallowed one,
and to keep no error state afterwards. Each phase programs one response code on
the responder, observes it on the SYS_OUT wire through the passive monitor, and
requires the JTAG-AXI manager to receive that exact code
(``expected_resp``, which the scoreboard enforces exactly, so DECERR is not
satisfied by SLVERR). The final phase re-runs the plain OKAY write/read pair on
the same address, so a fabric that latched an error is caught.
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_output_fabric_vip_utils import (
    OUTPUT_FABRIC_ADDR,
    OUTPUT_FABRIC_ALT_ADDR,
    OUTPUT_FABRIC_ALT_DATA,
    OUTPUT_FABRIC_DATA,
    OUTPUT_FABRIC_MODEL_REGION,
    RESP_DECERR,
    RESP_OKAY,
    RESP_SLVERR,
    check_output_responder_delta,
    jtag_axi_read,
    jtag_axi_write,
    output_fabric_model,
    output_fabric_pass_all_cfg_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_output_fabric_slverr_inject_test(smc_base_test):
    """OKAY WR/RD, one-shot SLVERR and DECERR on both directions, OKAY recovery."""

    required_evidence = ("CHK-SYS-OUT-ERROR-CODES",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        dut = cocotb.top
        assert hasattr(dut, "tb_output_axi_bresp"), (
            "tb_output_axi_bresp missing from the smc_uvm_top port surface"
        )
        output_fabric_model(self)

        start_writes = int(dut.tb_output_axi_write_count.value)
        start_reads = int(dut.tb_output_axi_read_count.value)
        sb = self.env.scoreboard
        mon = self.env.output_axi_monitor
        mon.allow_slverr = True
        updates0 = sb.memory_model_updates_seen
        checks0 = sb.memory_model_checks_seen
        snap0 = mon.snapshot()

        cfg_seq = output_fabric_pass_all_cfg_seq("slverr_inject_pass_all_seq")
        await self.start_seq(cfg_seq, self.env.sys_axi_agent.sequencer)

        # Phase A: OKAY path.
        wr_ok = await jtag_axi_write(
            self,
            OUTPUT_FABRIC_ADDR,
            OUTPUT_FABRIC_DATA,
            expected_resp=RESP_OKAY,
            update_golden=True,
            memory_region=OUTPUT_FABRIC_MODEL_REGION,
        )
        assert wr_ok.resp_code == RESP_OKAY, wr_ok.resp_code
        rd_ok = await jtag_axi_read(
            self,
            OUTPUT_FABRIC_ADDR,
            expected_resp=RESP_OKAY,
            check_golden=True,
            memory_region=OUTPUT_FABRIC_MODEL_REGION,
        )
        assert rd_ok.resp_code == RESP_OKAY, rd_ok.resp_code
        snap_a = mon.snapshot()
        assert snap_a["b_okay"] >= snap0["b_okay"] + 1, snap_a
        assert snap_a["r_okay"] >= snap0["r_okay"] + 1, snap_a

        # Phase B: one-shot read fault programmed on the SYS_OUT responder. The
        # beat carries SLVERR and no data; the fault retires with the beat and
        # the stored word is untouched.
        sys_out_mem = self.cfg.sys_out_mem
        assert sys_out_mem is not None, "SYS_OUT responder not bound"
        sys_out_mem.inject_error(OUTPUT_FABRIC_ADDR, RESP_SLVERR, read=True, write=False)
        rd_err = await jtag_axi_read(
            self,
            OUTPUT_FABRIC_ADDR,
            allow_error=True,
            expected_resp=RESP_SLVERR,
        )
        assert rd_err.resp_code == RESP_SLVERR, (
            f"injected read resp={rd_err.resp_code}, expected SLVERR"
        )
        assert sys_out_mem.read_int(OUTPUT_FABRIC_ADDR, 8) == OUTPUT_FABRIC_DATA, (
            "SLVERR beat altered the stored word"
        )
        snap_b = mon.snapshot()
        assert snap_b["r_slverr"] >= snap_a["r_slverr"] + 1, snap_b

        # Phase C: the fault has retired; the readback matches the golden DATA.
        rd_again = await jtag_axi_read(
            self,
            OUTPUT_FABRIC_ADDR,
            expected_resp=RESP_OKAY,
            check_golden=True,
            memory_region=OUTPUT_FABRIC_MODEL_REGION,
        )
        assert rd_again.resp_code == RESP_OKAY, rd_again.resp_code

        await check_output_responder_delta(
            start_writes=start_writes,
            start_reads=start_reads,
            write_delta=1,
            read_delta=3,
            last_addr=OUTPUT_FABRIC_ADDR,
            last_wdata=OUTPUT_FABRIC_DATA,
        )
        assert sb.memory_model_updates_seen == updates0 + 1, (
            f"unexpected golden updates={sb.memory_model_updates_seen}"
        )
        assert sb.memory_model_checks_seen == checks0 + 2
        snap_c = mon.snapshot()
        assert snap_c["r_okay"] >= snap_b["r_okay"] + 1, snap_c
        assert snap_c["b_decerr"] == 0 and snap_c["r_decerr"] == 0, snap_c
        cocotb.log.info(
            "U6-2 SYS_OUT monitor PASS: snap=%s updates=%d checks=%d",
            snap_c,
            sb.memory_model_updates_seen,
            sb.memory_model_checks_seen,
        )

        # Phase D/E/F: the other three error encodings the outbound path has to
        # carry back unchanged -- SLVERR and DECERR on a write, DECERR on a
        # read. DECERR is a hard fail in the monitor until the scenario says it
        # is expected, so the opt-in is taken here and not at build time.
        mon.allow_decerr = True
        injected = (
            ("wr_slverr", RESP_SLVERR, False),
            ("wr_decerr", RESP_DECERR, False),
            ("rd_decerr", RESP_DECERR, True),
        )
        observed = []
        for label, resp, is_read in injected:
            before = mon.snapshot()
            sys_out_mem.inject_error(OUTPUT_FABRIC_ALT_ADDR, resp, read=is_read, write=not is_read)
            if is_read:
                access = await jtag_axi_read(
                    self, OUTPUT_FABRIC_ALT_ADDR, expect_error=True, expected_resp=resp
                )
                tally = "r_decerr" if resp == RESP_DECERR else "r_slverr"
            else:
                access = await jtag_axi_write(
                    self,
                    OUTPUT_FABRIC_ALT_ADDR,
                    OUTPUT_FABRIC_ALT_DATA,
                    expect_error=True,
                    expected_resp=resp,
                )
                tally = "b_decerr" if resp == RESP_DECERR else "b_slverr"
            after = mon.snapshot()
            assert access.resp_code == resp, (
                f"{label}: the manager received resp={access.resp_code} for an "
                f"injected resp={resp}; the outbound path must return the "
                f"subordinate's encoding unchanged"
            )
            assert after[tally] == before[tally] + 1, (
                f"{label}: the SYS_OUT monitor counted {after[tally] - before[tally]} "
                f"{tally} beat(s) on the wire, expected exactly 1 (snapshot {after})"
            )
            observed.append(f"{label}->{access.resp_code}")

        # Phase G: every injected fault was one-shot, so the same address must
        # now complete OKAY and hand back the word it was given.
        wr_ok2 = await jtag_axi_write(
            self,
            OUTPUT_FABRIC_ALT_ADDR,
            OUTPUT_FABRIC_ALT_DATA,
            expected_resp=RESP_OKAY,
            update_golden=True,
            memory_region=OUTPUT_FABRIC_MODEL_REGION,
        )
        assert wr_ok2.resp_code == RESP_OKAY, wr_ok2.resp_code
        rd_ok2 = await jtag_axi_read(
            self,
            OUTPUT_FABRIC_ALT_ADDR,
            expected_resp=RESP_OKAY,
            check_golden=True,
            memory_region=OUTPUT_FABRIC_MODEL_REGION,
        )
        assert rd_ok2.resp_code == RESP_OKAY, rd_ok2.resp_code

        await check_output_responder_delta(
            start_writes=start_writes,
            start_reads=start_reads,
            write_delta=4,
            read_delta=5,
            last_addr=OUTPUT_FABRIC_ALT_ADDR,
            last_wdata=OUTPUT_FABRIC_ALT_DATA,
        )
        assert sb.memory_model_updates_seen == updates0 + 2, (
            f"unexpected golden updates={sb.memory_model_updates_seen}"
        )
        assert sb.memory_model_checks_seen == checks0 + 3
        snap_g = mon.snapshot()
        cocotb.log.info(
            "CHK-SYS-OUT-ERROR-CODES: the manager received %s for the injected "
            "responses, each seen once on the SYS_OUT wire; the following OKAY "
            "write/read of 0x%016x at 0x%08x completed normally (snapshot %s)",
            ", ".join(observed),
            OUTPUT_FABRIC_ALT_DATA,
            OUTPUT_FABRIC_ALT_ADDR,
            snap_g,
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
            # The nine JTAG-AXI accesses are fabric traffic and are reported in
            # their own field; csr_accesses counts CSR traffic only.
            fabric_accesses=9,
            min_fabric_accesses=9,
            fabric_access_label="jtag_axi_accesses",
            proxy=False,
            details=(
                "SYS_OUT responder one-shot SLVERR/DECERR on both directions + "
                f"SmcMemoryModel + U6-2 output AXI monitor tallies {snap_g}"
            ),
        )
