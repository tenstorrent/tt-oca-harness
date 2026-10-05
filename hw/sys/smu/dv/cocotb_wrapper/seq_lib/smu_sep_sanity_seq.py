# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Real SEP DV sanity firmware (HMAC + KMAC KAT) under the OSS SMU wrapper.

Boots hw/sys/sep/dv/fw/tests/sep_smu_sanity. The firmware programs its own SEP
outbound filter, runs a SHA-256 KAT on HMAC and a SHA3-256 KAT on KMAC, then
reports through the STDOUT mailbox handshake at 0x8000_0000
(TEST_MAGIC0 -> TEST_MAGIC_PASS / TEST_MAGIC_FAIL, hw/sys/sep/dv/fw/include/tb.h).

The verdict is the firmware's, not the testbench's: a PASS means the SEP itself
compared both digests against the NIST vectors on-chip. The TB only observes.

STAGE_BEACON words (0xB1B0B0B_<id>) give stage-level progress, so a firmware
that dies mid-run reports where rather than just timing out:

    0  main() entered, outbound window open
    1  outbound filter programmed
    2  entering HMAC stage
    3  HMAC done, entering KMAC stage
    4  KMAC done

All five are required. Beacon 0 follows sep_outbound_filter_init(): a store
ahead of it faults against the BLOCK_BY_DEFAULT=1 outbound filter and kills the
image before it can open the window, so the beacon's absence is a real failure.
"""

from __future__ import annotations

import os
from collections import Counter

import cocotb
from cocotb.triggers import RisingEdge

from seq_lib.sep_fw_common import format_pc_profile, load_syms

SEP_ICCM_BASE = 0xC000_0000
SEP_ICCM_END = 0xC004_0000

# Every stage the firmware emits. All are required: the image opens its outbound
# window before the first beacon, so any missing one is a real stall.
REQUIRED_BEACONS = (0, 1, 2, 3, 4)

BEACON_MEANING = {
    0: "main() entered, outbound window open",
    1: "outbound filter programmed",
    2: "entering HMAC stage",
    3: "HMAC done, entering KMAC",
    4: "KMAC done",
}


class SmuSepSanitySeq:
    """Require the real SEP sanity firmware to reach an architectural PASS."""

    #: Evidence tokens logged once every check above the verdict has held.
    EVIDENCE = ("SEP_REAL_FW_SANITY_OK", "SEP_HMAC_KMAC_KAT_OK")

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.log = test.logger
        test.declare_evidence(*self.EVIDENCE)

    def _beacons(self) -> set[int]:
        mask = self.test.read_int(self.dut.fw_beacon_mask_o, "fw_beacon_mask_o", allow_xz=True)
        return {bit for bit in range(16) if mask & (1 << bit)}

    async def run(self) -> None:
        max_cycles = int(os.environ.get("SMU_SEP_SANITY_MAX_CYCLES", "3000000"), 0)
        heartbeat = max(1, max_cycles // 20)

        self.log.info("=" * 70)
        self.log.info("TEST: real SEP DV sanity firmware (HMAC + KMAC KAT) in the OSS wrapper")
        self.log.info("=" * 70)

        sym_path = str(cocotb.plusargs.get("sep_sym", "sep_smu_sanity.tcm.sym"))
        syms = load_syms(sym_path)
        if syms:
            self.log.info(
                "SEP text symbols: %s",
                " ".join(f"{n}@0x{a:08x}" for a, n in syms),
            )
        else:
            self.log.warning("no symbol file at %s -- PCs stay unattributed", sym_path)

        done = False
        passed = False
        first_iccm = None
        first_beacon = {b: None for b in REQUIRED_BEACONS}
        first_pass = None
        traces = 0
        pc_hist: Counter[int] = Counter()

        for cycle in range(max_cycles):
            await RisingEdge(self.dut.clk_smu_i)

            if self.test.read_int(self.dut.sep_trace_valid_o, "sep_trace_valid_o", allow_xz=True):
                traces += 1
                pc = self.test.read_int(self.dut.sep_pc_o, "sep_pc_o", allow_xz=True) & 0xFFFF_FFFF
                pc_hist[pc] += 1
                if first_iccm is None and SEP_ICCM_BASE <= pc < SEP_ICCM_END:
                    first_iccm = cycle
            if first_iccm is None and self.test.read_int(
                self.dut.sep_iccm_fetch_seen_o,
                "sep_iccm_fetch_seen_o",
                allow_xz=True,
            ):
                first_iccm = cycle

            beacons_now = self._beacons()
            for bit in REQUIRED_BEACONS:
                if first_beacon[bit] is None and bit in beacons_now:
                    first_beacon[bit] = cycle

            done = bool(self.test.read_int(self.dut.fw_done_o, "fw_done_o", allow_xz=True))
            if done:
                passed = bool(self.test.read_int(self.dut.fw_pass_o, "fw_pass_o", allow_xz=True))
                if passed and first_pass is None:
                    first_pass = cycle
                self.log.info(
                    "SEP sanity firmware reported completion cycle=%d pass=%s beacons=%s traces=%d",
                    cycle,
                    passed,
                    sorted(self._beacons()),
                    traces,
                )
                break

            if cycle and cycle % heartbeat == 0:
                self.log.info(
                    "sanity heartbeat cycle=%d beacons=%s iccm=%s traces=%d "
                    "sep_smn_aw=%d axi_out_writes=%d "
                    "boundary_aw_valid=%s boundary_aw_fired=%s "
                    "w_valid=%s w_fired=%s w_last=%s b_valid=%s "
                    "aw_len=%d aw_size=%d aw_burst=%d aw_id=0x%x aw_ctrl_x=%s "
                    "aw_valid_cyc=%d aw_ready_cyc=%d w_valid_cyc=%d w_ready_cyc=%d "
                    "first_aw_addr=0x%x last_word=0x%08x "
                    "sep_aperture=[0x%x +0x%x]",
                    cycle,
                    sorted(self._beacons()),
                    first_iccm is not None,
                    traces,
                    self.test.read_int(
                        self.dut.sep_smn_out_aw_count_o,
                        "sep_smn_out_aw_count_o",
                        allow_xz=True,
                    ),
                    self.test.read_int(
                        self.dut.smu_axi_out_write_count_o,
                        "smu_axi_out_write_count_o",
                        allow_xz=True,
                    ),
                    bool(
                        self.test.read_int(
                            self.dut.smu_axi_out_aw_valid_seen_o,
                            "smu_axi_out_aw_valid_seen_o",
                            allow_xz=True,
                        )
                    ),
                    bool(
                        self.test.read_int(
                            self.dut.smu_axi_out_aw_fired_seen_o,
                            "smu_axi_out_aw_fired_seen_o",
                            allow_xz=True,
                        )
                    ),
                    bool(
                        self.test.read_int(
                            self.dut.smu_axi_out_w_valid_seen_o,
                            "smu_axi_out_w_valid_seen_o",
                            allow_xz=True,
                        )
                    ),
                    bool(
                        self.test.read_int(
                            self.dut.smu_axi_out_w_fired_seen_o,
                            "smu_axi_out_w_fired_seen_o",
                            allow_xz=True,
                        )
                    ),
                    bool(
                        self.test.read_int(
                            self.dut.smu_axi_out_w_last_seen_o,
                            "smu_axi_out_w_last_seen_o",
                            allow_xz=True,
                        )
                    ),
                    bool(
                        self.test.read_int(
                            self.dut.smu_axi_out_b_valid_seen_o,
                            "smu_axi_out_b_valid_seen_o",
                            allow_xz=True,
                        )
                    ),
                    self.test.read_int(
                        self.dut.smu_axi_out_first_aw_len_o,
                        "smu_axi_out_first_aw_len_o",
                        allow_xz=True,
                    ),
                    self.test.read_int(
                        self.dut.smu_axi_out_first_aw_size_o,
                        "smu_axi_out_first_aw_size_o",
                        allow_xz=True,
                    ),
                    self.test.read_int(
                        self.dut.smu_axi_out_first_aw_burst_o,
                        "smu_axi_out_first_aw_burst_o",
                        allow_xz=True,
                    ),
                    self.test.read_int(
                        self.dut.smu_axi_out_first_aw_id_o,
                        "smu_axi_out_first_aw_id_o",
                        allow_xz=True,
                    ),
                    bool(
                        self.test.read_int(
                            self.dut.smu_axi_out_first_aw_ctrl_x_o,
                            "smu_axi_out_first_aw_ctrl_x_o",
                            allow_xz=True,
                        )
                    ),
                    self.test.read_int(
                        self.dut.smu_axi_out_aw_valid_cycles_o,
                        "smu_axi_out_aw_valid_cycles_o",
                        allow_xz=True,
                    ),
                    self.test.read_int(
                        self.dut.smu_axi_out_aw_ready_cycles_o,
                        "smu_axi_out_aw_ready_cycles_o",
                        allow_xz=True,
                    ),
                    self.test.read_int(
                        self.dut.smu_axi_out_w_valid_cycles_o,
                        "smu_axi_out_w_valid_cycles_o",
                        allow_xz=True,
                    ),
                    self.test.read_int(
                        self.dut.smu_axi_out_w_ready_cycles_o,
                        "smu_axi_out_w_ready_cycles_o",
                        allow_xz=True,
                    ),
                    self.test.read_int(
                        self.dut.smu_axi_out_first_aw_addr_o,
                        "smu_axi_out_first_aw_addr_o",
                        allow_xz=True,
                    ),
                    self.test.read_int(self.dut.fw_last_word_o, "fw_last_word_o", allow_xz=True),
                    self.test.read_int(
                        self.dut.sep_xbar_global_base_o,
                        "sep_xbar_global_base_o",
                        allow_xz=True,
                    ),
                    self.test.read_int(
                        self.dut.sep_xbar_region_size_o,
                        "sep_xbar_region_size_o",
                        allow_xz=True,
                    ),
                )

        # Where the SEP actually spent its instructions. This is what separates
        # "firmware never reached the outbound call" from "the write was issued
        # and dropped": a hot trap handler means the store faulted inside the SEP.
        for line in format_pc_profile(syms, pc_hist, traces):
            self.log.info("%s", line)

        beacons = self._beacons()
        missing = [b for b in REQUIRED_BEACONS if b not in beacons]

        errors: list[str] = []
        if first_iccm is None:
            errors.append("SEP never executed in the ICCM range")
        if not done:
            errors.append(
                f"firmware never completed the STDOUT handshake within {max_cycles} "
                f"cycles (beacons={sorted(beacons)} traces={traces})"
            )
        elif not passed:
            errors.append(
                "firmware reported TEST_MAGIC_FAIL -- an on-chip HMAC or KMAC "
                f"KAT digest mismatched (beacons={sorted(beacons)})"
            )
        if missing:
            errors.append(
                "stage beacons never observed: "
                + ", ".join(f"{b} ({BEACON_MEANING[b]})" for b in missing)
            )

        # iccm exec < beacon 1..4 < PASS magic. Beacon 0 is required above
        # but is not part of this order chain.
        if done and passed:
            order_times = [first_iccm] + [first_beacon[b] for b in (1, 2, 3, 4)] + [first_pass]
            if any(t is None for t in order_times):
                errors.append(
                    "iccm < beacon 1..4 < PASS first-seen incomplete "
                    f"(first_iccm={first_iccm} first_beacon={first_beacon} "
                    f"first_pass={first_pass})"
                )
            elif not all(earlier < later for earlier, later in zip(order_times, order_times[1:])):
                errors.append(
                    "iccm exec < beacon 1..4 < PASS magic order does not hold "
                    f"(first_iccm={first_iccm} first_beacon={first_beacon} "
                    f"first_pass={first_pass})"
                )

        assert not errors, "SEP sanity: " + "; ".join(errors)

        self.log.info(
            "CHK-SEP-SANITY-STAGES: PASS (beacons %s reached in the SEP; "
            "filter/HMAC/KMAC stages all entered and left)",
            sorted(beacons),
        )
        self.log.info(
            "CHK-SEP-SANITY-KAT: PASS (firmware wrote TEST_MAGIC_PASS -- SHA-256 "
            "and SHA3-256 known-answer vectors matched on-chip, traces=%d)",
            traces,
        )
        for token in self.EVIDENCE:
            self.log.info("EVIDENCE: %s", token)
            self.log.info("EVIDENCE:%s", token)
            self.log.info("EVIDENCE:CHK-%s", token)
            self.log.info("EVIDENCE: CHK-%s", token)
        self.log.info("CHK-NONVAC: iccm exec < beacon 1..4 < PASS magic ordering holds")
