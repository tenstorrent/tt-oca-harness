# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_B1_008 ANCHOR: smc_cpuif_handshake_instances_test
# DV-TESTCASE-CONTRACT-REVISION: 5 RECORD-SHA256: 4d68d1879a666d752f86205bbe7816fd6beb72a0287f15da626741cf702c43c4
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_COV_B1_VPLAN_DETAIL.md @ artifact_revision 8 ENV: cocotb
"""Every register-block instance: pipelined, back to back, W ahead of AW and held.

Every instance of the multi-instance families (GPIO interfaces 0..64, inbound and
outbound filter entries 0..15, M-mode, Xvisor and alias remaps 0..7, I2C 0..2,
the UART/log wraps 0..3, telemetry receivers 0..2, the cold and warm scratch
banks) and instance 0 of every single-instance family (reset unit, cpu_ctrl, the
64 mailbox apertures, AVSBus, I2C control, OCTS, DFX, base configuration, eFuse
interface control and shadow, zeroer and iDMA control, I3C 0, DFD/CLA,
chip_config, ndm_reset, straps) take, through SEP_IN: pipelined reads (and on
the pinned-map families pipelined interleaved writes and reads), back-to-back
reads, writes with W ahead of AW, a read and a write against a held RREADY /
BREADY, and sixteen-deep groups queued behind a held response. One instance of
each family the contract lists takes the held groups again behind a 512-cycle
hold.

Run:
    python3 tools/dv/run_dv.py --dut smc --items smc_cpuif_handshake_instances_test --tool vcs
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_cpuif_handshake_instances_test_seq import (
    smc_cpuif_handshake_instances_test_seq,
)
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from the
# sequence. 187 pinned-map instances (65 GPIO interfaces, 32 filter entries,
# 8 M-mode, 8 Xvisor and 8 alias remaps, 64 mailbox apertures, reset unit,
# cpu_ctrl) at 188 SEP_IN accesses each: the reference read; 8 pipelined
# accesses and a restore (10); 4 pipelined reads; 2 back-to-back reads; the
# second register's reference, two writes, two back-to-back reads and two
# restores (9); three W-ahead writes with readbacks and a restore (8); the
# write-back leg (3) and its 12-offset sweep of write-write-read and write-read
# groups (60); the RREADY-held read; the BREADY-held write, its readback and a
# restore (4); and 16 held reads, 16 held mixed accesses, a restore, 16 held
# writes, a readback and a restore, then 16 distinct-ID held reads, 16
# distinct-ID held write-backs and a readback (86). Plus the precondition reads: 32
# FILTER_CONFIG, 8 region_attrs and 2 IRQS per mailbox aperture (128). 38 plain
# instances at 153 each (reference, 4 pipelined reads, 2 back-to-back reads,
# write-back leg and sweep (63), RREADY-held read, 82 in the held groups), 4 LCR
# accesses around each of the 4 divisor latches, and 5 CLOCK_GATE_CONTROL
# accesses for the mailbox clock. The long-hold instances (6 pinned-map, 10
# plain) repeat the held groups: 86 accesses each on a pinned-map instance and
# 82 on a plain one.
PINNED = 187
PLAIN = 38
LONG_PINNED = 6
LONG_PLAIN = 10
CPUIF_INSTANCES_MIN_CSR_ACCESSES = (
    PINNED * 188 + (32 + 8 + 128) + PLAIN * 153 + 4 * 4 + 5 + LONG_PINNED * 86 + LONG_PLAIN * 82
)


@pyuvm.test()
class smc_cpuif_handshake_instances_test(smc_base_test):
    """Pipeline, skew and hold the front end of every register-block instance."""

    required_evidence = (
        "CHK-CPUIF-B2B-DIFF",
        "CHK-CPUIF-B2B-SAME",
        "CHK-CPUIF-BREADY-HOLD",
        "CHK-CPUIF-HELD-GROUP",
        "CHK-CPUIF-LONG-HOLD",
        "CHK-CPUIF-PIPELINED-READ",
        "CHK-CPUIF-PIPELINED-RW",
        "CHK-CPUIF-RREADY-HOLD",
        "CHK-CPUIF-W-AHEAD",
        "CHK-CPUIF-W-AHEAD-WRITEBACK",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 12

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cpuif_handshake_instances_test_seq("smc_cpuif_handshake_instances_test_seq")
        pinned = sum(1 for x in seq.instances if x.pinned)
        assert (pinned, len(seq.instances) - pinned) == (PINNED, PLAIN), (
            f"the instance set holds {pinned} pinned-map and "
            f"{len(seq.instances) - pinned} plain instances, expected {PINNED} and {PLAIN}"
        )
        by_name = {x.name: x for x in seq.instances}
        long_pinned = sum(1 for name in seq.long_hold if by_name[name].pinned)
        assert (long_pinned, len(seq.long_hold) - long_pinned) == (LONG_PINNED, LONG_PLAIN), (
            f"the long-hold set holds {long_pinned} pinned-map and "
            f"{len(seq.long_hold) - long_pinned} plain instances, expected {LONG_PINNED} and "
            f"{LONG_PLAIN}"
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.DIAGNOSTIC,
            type(self).__name__,
            min_csr_accesses=CPUIF_INSTANCES_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=f"{len(seq.instances)} register-block instances, {seq.waits} bounded waits",
        )
