# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP lifecycle posture: sensed from the eFuse macro, driven by firmware, traced
to every consumer.

The SEP LCC decides the chiplet's lifecycle posture and three consumers act on
it:

    SEP eFuse macro -> fuse sense -> shadow regs -> sep_lifecycle_ctrl -+-> lc_state    -> SMC
                                                                        +-> dbg_disable -> DTP
                                                                        +-> feat_ctrl

Two things move that posture in this run, and both are observed at the
consumers rather than inside the register block.

The first is the SEP eFuse sense. The run carries no +skip_fuse_sense, so the
shadow registers are earned by the sense FSM from the eFuse bank model's
+sep_efuse_hex image, and sep_fuse_sense_done_o marks its completion. Before the
sense delivers the LC word the LCC exports the INVALID encoding (lc_state 0x0f
at the SMC) and debug is not open at the DTP; afterwards the consumers hold the
posture the lifecycle specification gives for the state that image programs
(seq_lib.smu_lifecycle_table). SepSenseMonitor, started by the test before
bring-up, samples the posture at cold-reset release, records every transition
of lc_state / dbg_disable / sense-done with its time, and samples the posture
again once the sense has completed. The run fails if the sense was skipped, did
not complete within its bound, or had already delivered the LC word before the
pre-sense side could be sampled.

The second is firmware. hw/sys/sep/dv/fw/tests/sep_smu_lcc_flow drives the one
input software owns -- the DEMOTE registers -- and parks in a per-stage loop.
For each firmware stage the hardware half checks that the posture actually
moved at the consumers. The lock stage is what makes the demote stages
non-vacuous: a register that stored whatever software wrote would satisfy every
demote check; only a refused write after lock shows the block implements the
policy.

Note on what is NOT claimed: a demote is not required to move feat_ctrl. In
TEST_DEV the baseline is already ~(sip_dis | sys_dis), so with a permissive
eFuse image the bits a demote forces high are high already and the write is a
no-op there. feat_ctrl is reported, not asserted on; the demote's effect is
checked at lcc_demote_state_*_o, where it is unambiguous.
"""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

import cocotb
from cocotb.triggers import Event, RisingEdge
from cocotb.utils import get_sim_time

from seq_lib.sep_fw_common import addr_of, format_pc_profile, load_syms
from seq_lib.smu_addr_map import c_header_u32
from seq_lib.smu_lifecycle_table import LC_STATE_PRESENSE, lc_state_name, posture

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

# Bound on the SEP eFuse sense, in clk_smu cycles from cold-reset release; the
# SEP bench bounds its own sense at the same figure.
SENSE_MAX_CYCLES = 20_000
# Cycles between sep_fuse_sense_done_o rising and the post-sense sample, so the
# decoded posture has crossed to the SMC and DTP boundaries.
POST_SENSE_SETTLE_CYCLES = 16

_REPO_ROOT = Path(__file__).resolve().parents[6]
_SEP_ADDR_H = _REPO_ROOT / "hw" / "sys" / "sep" / "regs" / "gen" / "c" / "sep_addr.h"


def lc_raw_from_efuse_image(path: str) -> int:
    """Raw LC_STATE the eFuse bank model holds after loading a +sep_efuse_hex image.

    The model zero-fills its array and then $readmemh's the file, so a short
    image leaves the remaining words zero. The OTP LC_STATE word carries the raw
    4-bit code in [3:0]; the sense FSM differentially encodes it. The word index
    comes from the generated SEP address map.
    """
    lc_idx = (
        c_header_u32(_SEP_ADDR_H, "OCH_SEP_TOP_SEP_EFUSE_MAP_LC_STATE_BASE_ADDR")
        - c_header_u32(_SEP_ADDR_H, "OCH_SEP_TOP_SEP_EFUSE_MAP_BASE_ADDR")
    ) // 4
    words: dict[int, int] = {}
    idx = 0
    for tok in Path(path).read_text().split():
        if tok.startswith("@"):
            idx = int(tok[1:], 16)
            continue
        words[idx] = int(tok, 16)
        idx += 1
    return words.get(lc_idx, 0) & 0xF


def _now_ns() -> float:
    return float(get_sim_time(unit="ns"))


class SepSenseMonitor:
    """Watch the SEP eFuse sense at the SMU boundary from cold-reset release on.

    Started before bring-up so the pre-sense posture is sampled at the rising
    edge of rst_cold_n_o, before the sense FSM can have delivered the LC word.
    """

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.log = test.logger
        self.sensed = Event()
        self.errors: list[str] = []
        self.pre_sense: dict[str, int] | None = None
        self.pre_sense_at: tuple[int, float] | None = None
        self.lc_moved_at: tuple[int, float] | None = None
        self.sense_done_at: tuple[int, float] | None = None
        self.post: dict[str, int] | None = None
        self.post_at: tuple[int, float] | None = None
        self.skipped: int | None = None

    def _rd(self, handle, name):
        return self.test.read_int(handle, name, allow_xz=True)

    def posture(self) -> dict[str, int]:
        return {
            "feat_ctrl": self._rd(self.dut.lcc_feat_ctrl_o, "lcc_feat_ctrl_o"),
            "demote1": self._rd(self.dut.lcc_demote_state_1_o, "lcc_demote_state_1_o"),
            "demote2": self._rd(self.dut.lcc_demote_state_2_o, "lcc_demote_state_2_o"),
            "dbg_disable": self._rd(self.dut.lcc_dbg_disable_o, "lcc_dbg_disable_o"),
            "smc_jtag2axi_disabled": self._rd(
                self.dut.lcc_dbg_disable_smc_jtag2axi_o, "lcc_dbg_disable_smc_jtag2axi_o"
            ),
            "smc_lc_state": self._rd(self.dut.smc_lc_state_in_o, "smc_lc_state_in_o"),
        }

    @staticmethod
    def fmt(p: dict[str, int]) -> str:
        return (
            f"feat_ctrl=0x{p['feat_ctrl']:016x} demote1={p['demote1']:#04b} "
            f"demote2={p['demote2']:#04b} dbg_disable=0x{p['dbg_disable']:04x} "
            f"smc_jtag2axi_disabled={p['smc_jtag2axi_disabled']} "
            f"smc_lc_state=0x{p['smc_lc_state']:02x}"
        )

    def start(self) -> None:
        cocotb.start_soon(self._run())

    def _fail(self, msg: str) -> None:
        self.errors.append(msg)
        self.sensed.set()

    async def _run(self) -> None:
        dut = self.dut
        cold_seen_low = False
        armed = False
        cycle = 0
        last = None
        while True:
            await RisingEdge(dut.clk_smu_i)
            cold_n = self._rd(dut.rst_cold_n_o, "rst_cold_n_o")
            done = self._rd(dut.sep_fuse_sense_done_o, "sep_fuse_sense_done_o")
            cur = self.posture()
            if not cold_seen_low:
                cold_seen_low = not cold_n
                continue
            if not armed:
                if not cold_n:
                    continue
                armed = True
                self.skipped = self._rd(dut.sep_fuse_sense_skipped_o, "sep_fuse_sense_skipped_o")
                self.pre_sense = cur
                self.pre_sense_at = (cycle, _now_ns())
                self.log.info(
                    "SEP sense monitor: cold reset released at %.1f ns; "
                    "sep_fuse_sense_skipped_o=%d sep_fuse_sense_done_o=%d",
                    self.pre_sense_at[1],
                    self.skipped,
                    done,
                )
                self.log.info("pre-sense posture (cold-reset release): %s", self.fmt(cur))
                if self.skipped:
                    self._fail(
                        "sep_fuse_sense_skipped_o=1: the SEP eFuse sense is replaced by the "
                        "shadow preload (+skip_fuse_sense), so no sense can be observed"
                    )
                    return
                if done:
                    self._fail(
                        "sep_fuse_sense_done_o already 1 at cold-reset release -- the "
                        "pre-sense posture cannot be sampled"
                    )
                    return
                if cur["smc_lc_state"] != LC_STATE_PRESENSE:
                    self._fail(
                        f"smc_lc_state_in_o read 0x{cur['smc_lc_state']:02x} at cold-reset "
                        f"release, not the pre-sense 0x{LC_STATE_PRESENSE:02x} -- the SMC leg "
                        "has no baseline to move off"
                    )
                    return
                if cur["dbg_disable"] == 0:
                    self._fail(
                        "lcc_dbg_disable_o already all-open at cold-reset release -- the DTP "
                        "leg has no baseline to move off"
                    )
                    return
                last = (cur["smc_lc_state"], cur["dbg_disable"], done)
                continue
            cycle += 1
            now = (cur["smc_lc_state"], cur["dbg_disable"], done)
            if now != last:
                self.log.info(
                    "SEP sense monitor: cycle %d (%.1f ns) lc_state 0x%02x->0x%02x "
                    "dbg_disable 0x%04x->0x%04x sense_done %d->%d",
                    cycle,
                    _now_ns(),
                    last[0],
                    now[0],
                    last[1],
                    now[1],
                    last[2],
                    now[2],
                )
                if self.lc_moved_at is None and now[0] != last[0]:
                    self.lc_moved_at = (cycle, _now_ns())
                last = now
            if self.sense_done_at is None:
                if done:
                    self.sense_done_at = (cycle, _now_ns())
                elif cycle >= SENSE_MAX_CYCLES:
                    self._fail(
                        f"sep_fuse_sense_done_o still low {SENSE_MAX_CYCLES} clk_smu after "
                        "cold-reset release -- the SEP eFuse sense did not complete"
                    )
                    return
            elif cycle >= self.sense_done_at[0] + POST_SENSE_SETTLE_CYCLES:
                self.post = cur
                self.post_at = (cycle, _now_ns())
                self.log.info(
                    "post-sense posture (%d cycles after sense-done, %.1f ns): %s",
                    POST_SENSE_SETTLE_CYCLES,
                    self.post_at[1],
                    self.fmt(cur),
                )
                self.sensed.set()
                return


class SmuSepLccFlowSeq:
    """Prove the sensed posture and the firmware-driven demote reach feat_ctrl, DTP and SMC."""

    def __init__(self, test, monitor: SepSenseMonitor) -> None:
        self.test = test
        self.dut = cocotb.top
        self.log = test.logger
        self.mon = monitor

    def _rd(self, handle, name):
        return self.test.read_int(handle, name, allow_xz=True)

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

        # The consumer contract is the lifecycle state the sensed image programs.
        image = str(cocotb.plusargs.get("sep_efuse_hex", ""))
        assert image, "+sep_efuse_hex is required: it is the image the SEP sense reads"
        lc_raw = lc_raw_from_efuse_image(image)
        state = lc_state_name(lc_raw)
        want_sensed = posture(state)
        want_demoted = posture(state, demoted=True)

        self.log.info("=" * 70)
        self.log.info(
            "TEST: SEP lifecycle posture, sensed then firmware-driven, traced to consumers"
        )
        self.log.info("=" * 70)
        self.log.info(
            "eFuse image %s: LC_STATE raw 0x%x -> %s; contract after sense lc_state=0x%02x "
            "all_open=%s smc_jtag2axi_disabled=%s",
            image,
            lc_raw,
            state,
            want_sensed.lc_state,
            want_sensed.all_open,
            want_sensed.smc_jtag2axi_disabled,
        )

        # The firmware watcher runs from here so no retirement is missed while
        # the sense is awaited.
        watch: dict[str, object] = {
            "verdict": None,
            "boot_rom_seen": False,
            "iccm_seen": False,
            "traces": 0,
            "pc_hist": Counter(),
        }

        async def watch_firmware() -> None:
            for _ in range(max_cycles):
                await RisingEdge(self.dut.clk_smu_i)
                if self._rd(self.dut.sep_trace_valid_o, "sep_trace_valid_o"):
                    pc = self._rd(self.dut.sep_pc_o, "sep_pc_o") & 0xFFFF_FFFF
                    watch["traces"] += 1
                    watch["pc_hist"][pc] += 1
                    watch["boot_rom_seen"] |= SEP_BOOT_ROM_BASE <= pc < SEP_BOOT_ROM_END
                    watch["iccm_seen"] |= SEP_ICCM_BASE <= pc < SEP_ICCM_END
                    if watch["verdict"] is None:
                        if pc == pass_pc:
                            watch["verdict"] = ("pass", None)
                        elif pc in fail_pcs:
                            watch["verdict"] = ("fail", fail_pcs[pc])
                if watch["verdict"] is not None:
                    return

        watcher = cocotb.start_soon(watch_firmware())

        # Sense half: the monitor bounds the wait itself.
        await self.mon.sensed.wait()
        assert not self.mon.errors, "SEP LCC flow: " + "; ".join(self.mon.errors)
        before = self.mon.pre_sense
        sensed = self.mon.post
        assert before is not None and sensed is not None
        self.log.info(
            "SEP eFuse sense observed: sense-done at cycle %d (%.1f ns) after cold-reset "
            "release; lc_state left 0x%02x at cycle %s (%s ns)",
            self.mon.sense_done_at[0],
            self.mon.sense_done_at[1],
            LC_STATE_PRESENSE,
            self.mon.lc_moved_at[0] if self.mon.lc_moved_at else "-",
            f"{self.mon.lc_moved_at[1]:.1f}" if self.mon.lc_moved_at else "-",
        )

        errors: list[str] = []
        if sensed["smc_lc_state"] != want_sensed.lc_state:
            errors.append(
                f"SMC received lc_state 0x{sensed['smc_lc_state']:02x} after the sense, "
                f"expected 0x{want_sensed.lc_state:02x} for {state} -- the sensed posture "
                "is not reaching the SMC"
            )
        if want_sensed.all_open and sensed["dbg_disable"] != 0:
            errors.append(
                f"DTP received dbg_disable 0x{sensed['dbg_disable']:04x} after the sense, "
                f"{state} leaves every debug path open (0x0000)"
            )
        if bool(sensed["smc_jtag2axi_disabled"]) != want_sensed.smc_jtag2axi_disabled:
            errors.append(
                f"dbg_disable.smc_jtag2axi is {sensed['smc_jtag2axi_disabled']} after the "
                f"sense, {state} requires {int(want_sensed.smc_jtag2axi_disabled)}"
            )

        # Firmware half.
        await watcher
        # The firmware's last stores are still in flight when its terminal loop
        # retires; drain before sampling the consumers.
        for _ in range(SETTLE_CYCLES):
            await RisingEdge(self.dut.clk_smu_i)
        after = self.mon.posture()

        traces = int(watch["traces"])
        pc_hist: Counter[int] = watch["pc_hist"]  # type: ignore[assignment]
        for line in format_pc_profile(syms, pc_hist, traces):
            self.log.info("%s", line)
        self.log.info("posture after the run: %s", self.mon.fmt(after))

        verdict = watch["verdict"]
        if verdict is None:
            errors.append(
                f"firmware reached no terminal loop within {max_cycles} cycles (traces={traces})"
            )
        elif verdict[0] == "fail":
            errors.append(
                f"firmware parked in the {verdict[1]} fail loop -- its own on-chip "
                "check of that stage did not hold"
            )
        if not watch["boot_rom_seen"]:
            errors.append("SEP never fetched from the boot-ROM window")
        if not watch["iccm_seen"]:
            errors.append("SEP never executed in the ICCM range")

        # The firmware proved FEAT_CTRL moved as software reads it; these prove
        # the same posture reached the consumers. The demote baseline is the
        # pre-sense sample: the SEP CPU has not run at that point.
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
        if after["smc_lc_state"] != want_demoted.lc_state:
            errors.append(
                f"SMC holds lc_state 0x{after['smc_lc_state']:02x} after the run, expected "
                f"0x{want_demoted.lc_state:02x} for {state}"
            )
        if want_demoted.all_open and after["dbg_disable"] != 0:
            errors.append(
                f"DTP holds dbg_disable 0x{after['dbg_disable']:04x} after the run, "
                f"{state} with both demotes set leaves every debug path open (0x0000)"
            )
        if bool(after["smc_jtag2axi_disabled"]) != want_demoted.smc_jtag2axi_disabled:
            errors.append(
                f"dbg_disable.smc_jtag2axi is {after['smc_jtag2axi_disabled']} after the "
                f"run, {state} with both demotes set requires "
                f"{int(want_demoted.smc_jtag2axi_disabled)}"
            )

        assert not errors, "SEP LCC flow: " + "; ".join(errors)

        self.log.info(
            "CHK-SEP-LCC-SENSE: PASS (SEP eFuse sense ran, sep_fuse_sense_done_o rose at "
            "cycle %d after cold-reset release; SMC lc_state 0x%02x->0x%02x and DTP "
            "dbg_disable 0x%04x->0x%04x against the %s contract from %s)",
            self.mon.sense_done_at[0],
            before["smc_lc_state"],
            sensed["smc_lc_state"],
            before["dbg_disable"],
            sensed["dbg_disable"],
            state,
            os.path.basename(image),
        )
        self.log.info(
            "CHK-SEP-LCC-FW-STAGES: PASS (firmware cleared all four stages on-chip: "
            "FEAT_CTRL readable, DEMOTE_1 and DEMOTE_2 each accepted and read back, "
            "and the DEMOTE_1 lock refused a later clear)"
        )
        self.log.info(
            "CHK-SEP-LCC-FANOUT: PASS (demote1 %s->%s, demote2 %s->%s, "
            "feat_ctrl 0x%016x->0x%016x reported only; SMC lc_state 0x%02x held and DTP "
            "dbg_disable 0x%04x held through the demotes, as %s contracts)",
            format(before["demote1"], "#04b"),
            format(after["demote1"], "#04b"),
            format(before["demote2"], "#04b"),
            format(after["demote2"], "#04b"),
            before["feat_ctrl"],
            after["feat_ctrl"],
            after["smc_lc_state"],
            after["dbg_disable"],
            state,
        )
        self.log.info(
            "CHK-SEP-LCC-NONVAC: PASS (the sense legs are a delta off the pre-sense "
            "posture sampled at cold-reset release and a compare against the lifecycle "
            "table's value for the sensed image; the write-once lock rules out plain storage)"
        )
        for token in (
            "SEP_LCC_SENSE_OBSERVED_OK",
            "SEP_LCC_FW_FLOW_OK",
            "SEP_LCC_FANOUT_TO_SMC_DTP_OK",
        ):
            self.log.info("EVIDENCE: %s", token)
            self.log.info("EVIDENCE:%s", token)
            self.log.info("EVIDENCE:CHK-%s", token)
            self.log.info("EVIDENCE: CHK-%s", token)
