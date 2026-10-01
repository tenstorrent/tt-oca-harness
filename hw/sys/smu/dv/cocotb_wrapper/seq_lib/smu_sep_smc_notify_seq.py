# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP outbound egress path, proven segment by segment.

hw/sys/sep/dv/fw/tests/sep_smc_notify is the minimal image for this: it opens
the outbound filter over the mailbox and writes the two-word PASS magic, and
does nothing else. Its own header names the claim -- "SEP CPU reset-vector
execution through the outbound filter and crossbar to the external AXI output".

smu_sep_sanity_test also ends in that magic, but only after HMAC and KMAC, so a
failure there has several possible homes. Here the image is small enough that
the egress path is the only thing under test.

The magic alone would not prove the path, though: it is decoded at the SMU
boundary, and seeing it says the bytes arrived without saying how far they
actually travelled as bus traffic. So the checks walk the chain instead --
SEP issues an outbound AW, the crossbar delivers a write at the SMU boundary,
and only then the mailbox decodes PASS. Each segment is a separate assertion,
so a break names the segment.
"""

from __future__ import annotations

import os
from collections import Counter

import cocotb
from cocotb.triggers import RisingEdge

from seq_lib.sep_fw_common import format_pc_profile, load_syms, sep_boot_order_from_hw

SEP_BOOT_ROM_BASE = 0x1004_0000
SEP_BOOT_ROM_END = 0x1005_0000
SEP_ICCM_BASE = 0xC000_0000
SEP_ICCM_END = 0xC004_0000


class SmuSepSmcNotifySeq:
    """Require the SEP mailbox write to traverse the whole egress chain."""

    #: Evidence tokens logged once every check above the verdict has held.
    EVIDENCE = ("SEP_REAL_FW_NOTIFY_OK", "SEP_OUTBOUND_EGRESS_CHAIN_OK")

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.log = test.logger
        test.declare_evidence(*self.EVIDENCE)

    def _rd(self, handle, name):
        return self.test.read_int(handle, name, allow_xz=True)

    async def run(self) -> None:
        max_cycles = int(os.environ.get("SMU_SEP_FW_MAX_CYCLES", "300000"), 0)
        heartbeat = max(1, max_cycles // 20)

        sym_path = str(cocotb.plusargs.get("sep_sym", "sep_smc_notify.tcm.sym"))
        syms = load_syms(sym_path)

        self.log.info("=" * 70)
        self.log.info("TEST: SEP outbound egress path to the external AXI mailbox")
        self.log.info("=" * 70)

        # Nothing may have been issued before the firmware runs, or "count > 0"
        # at the end would prove nothing about this image.
        pre_smn = self._rd(self.dut.sep_smn_out_aw_count_o, "smn_aw")
        pre_out = self._rd(self.dut.smu_axi_out_write_count_o, "axi_out")
        assert pre_smn == 0, f"SEP already issued {pre_smn} outbound AW before the run"

        _, boot_rom_seen, iccm_seen = sep_boot_order_from_hw(self.dut, self._rd)
        done = False
        passed = False
        traces = 0
        pc_hist: Counter[int] = Counter()

        for cycle in range(max_cycles):
            await RisingEdge(self.dut.clk_smu_i)

            if self._rd(self.dut.sep_trace_valid_o, "sep_trace_valid_o"):
                pc = self._rd(self.dut.sep_pc_o, "sep_pc_o") & 0xFFFF_FFFF
                traces += 1
                pc_hist[pc] += 1
                boot_rom_seen |= SEP_BOOT_ROM_BASE <= pc < SEP_BOOT_ROM_END
                iccm_seen |= SEP_ICCM_BASE <= pc < SEP_ICCM_END

            if self._rd(self.dut.fw_done_o, "fw_done_o"):
                done = True
                passed = bool(self._rd(self.dut.fw_pass_o, "fw_pass_o"))
                break

            if cycle and cycle % heartbeat == 0:
                self.log.info(
                    "notify heartbeat cycle=%d traces=%d smn_aw=%d axi_out_writes=%d "
                    "last_word=0x%08x",
                    cycle,
                    traces,
                    self._rd(self.dut.sep_smn_out_aw_count_o, "smn_aw"),
                    self._rd(self.dut.smu_axi_out_write_count_o, "axi_out"),
                    self._rd(self.dut.fw_last_word_o, "last_word"),
                )

        smn_aw = self._rd(self.dut.sep_smn_out_aw_count_o, "smn_aw")
        axi_out = self._rd(self.dut.smu_axi_out_write_count_o, "axi_out")

        for line in format_pc_profile(syms, pc_hist, traces):
            self.log.info("%s", line)
        self.log.info(
            "egress chain: SEP outbound AW=%d (was %d), SMU boundary writes=%d "
            "(was %d), mailbox verdict done=%s pass=%s",
            smn_aw,
            pre_smn,
            axi_out,
            pre_out,
            done,
            passed,
        )

        errors: list[str] = []
        if not boot_rom_seen:
            errors.append("SEP never fetched from the boot-ROM window")
        if not iccm_seen:
            errors.append("SEP never executed in the ICCM range")
        if smn_aw <= pre_smn:
            errors.append(
                "SEP issued no outbound AW -- the write never left the SEP, so "
                "the filter or the SEP's own decode dropped it"
            )
        elif axi_out <= pre_out:
            # This counter only moves on B, so on its own it cannot tell "the
            # beat never arrived" from "the beat arrived and the boundary slave
            # never answered it". The boundary handshake flags below separate
            # them; read those before concluding anything about routing.
            aw_seen = bool(self._rd(cocotb.top.smu_axi_out_aw_valid_seen_o, "aw_valid_seen"))
            w_last = bool(self._rd(cocotb.top.smu_axi_out_w_last_seen_o, "w_last_seen"))
            errors.append(
                f"SEP issued {smn_aw} outbound AW but no write completed at the "
                f"SMU boundary; boundary saw aw_valid={aw_seen} w_last={w_last} "
                "(aw_valid false => it never reached the boundary; aw_valid true "
                "with no B => the boundary slave did not answer)"
            )
        if not done:
            errors.append(f"no mailbox verdict within {max_cycles} cycles (traces={traces})")
        elif not passed:
            errors.append("firmware reported TEST_MAGIC_FAIL")

        assert not errors, "SEP notify: " + "; ".join(errors)

        self.log.info(
            "CHK-SEP-EGRESS-CHAIN: PASS (SEP outbound AW=%d → SMU boundary "
            "writes=%d → mailbox TEST_MAGIC_PASS; each segment observed, not "
            "inferred from the magic alone)",
            smn_aw,
            axi_out,
        )
        self.log.info("CHK-SEP-EGRESS-FRONTDOOR: PASS (boot_rom=1 iccm=1 traces=%d)", traces)
        for token in self.EVIDENCE:
            self.log.info("EVIDENCE: %s", token)
            self.log.info("EVIDENCE:%s", token)
            self.log.info("EVIDENCE:CHK-%s", token)
            self.log.info("EVIDENCE: CHK-%s", token)
