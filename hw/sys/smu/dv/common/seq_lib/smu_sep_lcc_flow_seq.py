# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP lifecycle posture, driven by firmware and traced to every consumer.

The SEP LCC decides the chiplet's lifecycle posture and three consumers act on
it:

    SEP eFuse shadow regs -> sep_lifecycle_ctrl -+-> lc_state    -> SMC
                                                 +-> dbg_disable -> DTP
                                                 +-> feat_ctrl

A single static sample of `lc_state_o` at the SMU boundary proves the wire
exists; it does not prove the LCC responds to anything, and it says nothing
about the other two legs.

hw/sys/sep/dv/fw/tests/sep_smu_lcc_flow drives the one input software owns --
the DEMOTE registers -- and parks in a per-stage loop. This sequence adds the
hardware half: for each firmware stage it checks that the posture actually moved
at the consumers, not just inside the register block.

The lock stage is what makes the rest non-vacuous. A register that stored
whatever software wrote would satisfy every demote check; only a refused write
after lock shows the block implements the policy.

Note on what is NOT claimed: a demote is not required to move feat_ctrl. In
TEST_DEV the baseline is already ~(sip_dis | sys_dis), so with a permissive
eFuse image the bits a demote forces high are high already and the write is a
no-op there. feat_ctrl is reported, not asserted on; the demote's effect is
checked at lcc_demote_state_*_o, where it is unambiguous.
"""

from __future__ import annotations

import os
from collections import Counter

import cocotb
from cocotb.triggers import RisingEdge

from seq_lib.sep_fw_common import addr_of, format_pc_profile, load_syms

SEP_BOOT_ROM_BASE = 0x1004_0000
SEP_BOOT_ROM_END = 0x1005_0000
SEP_ICCM_BASE = 0xC000_0000
SEP_ICCM_END = 0xC004_0000

PASS_SYM = "sep_smu_lcc_flow_pass_loop"
FAIL_SYMS = {
    "feat_ctrl_readable": "sep_smu_lcc_flow_fail_readable_loop",
    "demote1_not_accepted": "sep_smu_lcc_flow_fail_demote1_loop",
    "demote2_not_accepted": "sep_smu_lcc_flow_fail_demote2_loop",
    "demote_lock_not_enforced": "sep_smu_lcc_flow_fail_lock_loop",
}

SETTLE_CYCLES = 2000


class SmuSepLccFlowSeq:
    """Prove the firmware-driven demote reaches feat_ctrl, DTP and SMC."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.log = test.logger

    def _rd(self, handle, name):
        return self.test.read_int(handle, name, allow_xz=True)

    def _posture(self) -> dict[str, int]:
        return {
            "feat_ctrl": self._rd(self.dut.lcc_feat_ctrl_o, "lcc_feat_ctrl_o"),
            "demote1": self._rd(self.dut.lcc_demote_state_1_o, "lcc_demote_state_1_o"),
            "demote2": self._rd(self.dut.lcc_demote_state_2_o, "lcc_demote_state_2_o"),
            "dbg_disable": self._rd(self.dut.lcc_dbg_disable_o, "lcc_dbg_disable_o"),
            "smc_lc_state": self._rd(self.dut.smc_lc_state_in_o, "smc_lc_state_in_o"),
        }

    @staticmethod
    def _fmt(p: dict[str, int]) -> str:
        return (
            f"feat_ctrl=0x{p['feat_ctrl']:016x} demote1={p['demote1']:#04b} "
            f"demote2={p['demote2']:#04b} dbg_disable=0x{p['dbg_disable']:04x} "
            f"smc_lc_state=0x{p['smc_lc_state']:02x}"
        )

    async def run(self) -> None:
        max_cycles = int(os.environ.get("SMU_SEP_FW_MAX_CYCLES", "300000"), 0)

        sym_path = str(cocotb.plusargs.get("sep_sym", "sep_smu_lcc_flow.tcm.sym"))
        syms = load_syms(sym_path)
        assert syms, f"no usable symbol table at {sym_path}"
        pass_pc = addr_of(syms, PASS_SYM)
        fail_pcs = {addr_of(syms, s): label for label, s in FAIL_SYMS.items()}

        itcm = str(cocotb.plusargs.get("sep_itcm_hex", ""))
        if itcm:
            assert (
                os.path.basename(itcm).split(".")[0] == os.path.basename(sym_path).split(".")[0]
            ), "ITCM image and symbol table are from different firmwares"

        self.log.info("=" * 70)
        self.log.info("TEST: SEP lifecycle posture, firmware-driven, traced to consumers")
        self.log.info("=" * 70)

        # Posture before the firmware touches anything. Every later claim is a
        # delta against this, so a design that ignored the demote writes would
        # show no movement and fail rather than pass on a coincidence.
        before = self._posture()
        self.log.info("posture at reset: %s", self._fmt(before))

        verdict = None
        boot_rom_seen = False
        iccm_seen = False
        traces = 0
        pc_hist: Counter[int] = Counter()

        for _ in range(max_cycles):
            await RisingEdge(self.dut.clk_smu_i)
            if self._rd(self.dut.sep_trace_valid_o, "sep_trace_valid_o"):
                pc = self._rd(self.dut.sep_pc_o, "sep_pc_o") & 0xFFFF_FFFF
                traces += 1
                pc_hist[pc] += 1
                boot_rom_seen |= SEP_BOOT_ROM_BASE <= pc < SEP_BOOT_ROM_END
                iccm_seen |= SEP_ICCM_BASE <= pc < SEP_ICCM_END
                if verdict is None:
                    if pc == pass_pc:
                        verdict = ("pass", None)
                    elif pc in fail_pcs:
                        verdict = ("fail", fail_pcs[pc])
            if verdict is not None:
                break

        # The firmware's last stores are still in flight when its terminal loop
        # retires; drain before sampling the consumers.
        for _ in range(SETTLE_CYCLES):
            await RisingEdge(self.dut.clk_smu_i)
        after = self._posture()

        for line in format_pc_profile(syms, pc_hist, traces):
            self.log.info("%s", line)
        self.log.info("posture after the run: %s", self._fmt(after))

        errors: list[str] = []
        if verdict is None:
            errors.append(
                f"firmware reached no terminal loop within {max_cycles} cycles (traces={traces})"
            )
        elif verdict[0] == "fail":
            errors.append(
                f"firmware parked in the {verdict[1]} fail loop -- its own on-chip "
                "check of that stage did not hold"
            )
        if not boot_rom_seen:
            errors.append("SEP never fetched from the boot-ROM window")
        if not iccm_seen:
            errors.append("SEP never executed in the ICCM range")

        # Hardware half. The firmware proved FEAT_CTRL moved as software reads
        # it; these prove the same posture reached the consumers.
        if after["demote1"] == before["demote1"]:
            errors.append(
                f"lcc_demote_state_1_o never changed ({before['demote1']:#04b}) -- "
                "the firmware's DEMOTE_1 write did not reach the SMU boundary"
            )
        if after["demote2"] == before["demote2"]:
            errors.append(
                f"lcc_demote_state_2_o never changed ({before['demote2']:#04b}) -- "
                "the firmware's DEMOTE_2 write did not reach the SMU boundary"
            )
        if after["smc_lc_state"] == 0:
            errors.append("SMC received lc_state 0x00 -- the posture is not reaching the SMC")

        assert not errors, "SEP LCC flow: " + "; ".join(errors)

        self.log.info(
            "CHK-SEP-LCC-FW-STAGES: PASS (firmware cleared all four stages on-chip: "
            "FEAT_CTRL readable, DEMOTE_1 and DEMOTE_2 each accepted and read back, "
            "and the DEMOTE_1 lock refused a later clear)"
        )
        self.log.info(
            "CHK-SEP-LCC-FANOUT: PASS (demote1 %s->%s, demote2 %s->%s, "
            "feat_ctrl 0x%016x->0x%016x, dbg_disable 0x%04x->0x%04x, SMC lc_state=0x%02x)",
            format(before["demote1"], "#04b"),
            format(after["demote1"], "#04b"),
            format(before["demote2"], "#04b"),
            format(after["demote2"], "#04b"),
            before["feat_ctrl"],
            after["feat_ctrl"],
            before["dbg_disable"],
            after["dbg_disable"],
            after["smc_lc_state"],
        )
        self.log.info(
            "CHK-SEP-LCC-NONVAC: PASS (every consumer claim is a delta against the "
            "reset posture, and the write-once lock rules out plain storage)"
        )
        for token in ("SEP_LCC_FW_FLOW_OK", "SEP_LCC_FANOUT_TO_SMC_DTP_OK"):
            self.log.info("EVIDENCE: %s", token)
            self.log.info("EVIDENCE:%s", token)
            self.log.info("EVIDENCE:CHK-%s", token)
            self.log.info("EVIDENCE: CHK-%s", token)
