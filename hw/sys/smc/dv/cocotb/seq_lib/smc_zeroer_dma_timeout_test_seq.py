# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Zeroer datapath payload check through the output-fabric responder."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import cocotb
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot

# Shared output-fabric VIP layer: fabric window, filter pass-all programming and
# the X-aware responder sampling all live there (no local re-implementation).
from .smc_output_fabric_vip_utils import (
    OUTPUT_FABRIC_ADDR,
    check_output_responder_delta,
    output_fabric_pass_all_cfg_seq,
    output_responder_counts,
    reg_field_pack,
)

# Generated PeakRDL map (hw/sys/smc/regs/gen/py/smc_reg.py).
_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    ZEROER_CTRL_CTRL_STATUS_REG_ADDR,
    ZEROER_CTRL_DEST_ADDR_REG_ADDR,
    ZEROER_CTRL_SIZE_REG_ADDR,
)

ZEROER_DEST_ADDR = ZEROER_CTRL_DEST_ADDR_REG_ADDR
ZEROER_SIZE = ZEROER_CTRL_SIZE_REG_ADDR
ZEROER_CTRL_STATUS = ZEROER_CTRL_CTRL_STATUS_REG_ADDR
# CTRL_STATUS start value packed from the generated ZEROER_CTRL field layout
# (int_en at bit 0 — the write side effect that starts the FSM), not a literal.
ZEROER_CTRL_STATUS_START = reg_field_pack("ZEROER_CTRL_CTRL_STATUS_reg_t", int_en=1)
# --- CTRL_STATUS readback expectation (S4) ----------------------------------
# Packed from the same generated field layout, never a literal, and every bit of
# the 64-bit word is accounted for:
#
#   INT_EN[0]  = 1  -- ``hw/ip/zeroer/regs/zeroer_ctrl.rdl``: ``sw = rw; hw = r``.
#                     Software owns the field and hardware never writes it, so it
#                     holds the 1 that S3 wrote to arm the completion interrupt.
#   STATUS[32] = 0  -- the field carries BUSY (see the polarity note below) and
#                     by the time this read is issued the operation is
#                     independently proven finished -- the responder counted the
#                     zeroer's AXI write and the region reads back zeros -- so
#                     the field must be 0. This read is also the cleared leg of
#                     the 0 -> 1 -> 0 lifecycle proven in S5.
#   all other bits  = 0 -- the RDL declares no field there (``rsvd_0[31:1]`` and
#                     nothing above bit 32), so reserved-zero.
#
# STATUS POLARITY -- the RDL description and the RTL disagree, and this
# expectation rests on the observed lifecycle, not on the documentation:
#   * ``hw/ip/zeroer/regs/zeroer_ctrl.rdl:51`` describes STATUS as "Returns
#     status of whether zeroer has completed"; ``hw/sys/smc/doc/zeroer.adoc``
#     renders that same generated field text and assigns busy/completion to no
#     bit position of its own.
#   * ``hw/ip/zeroer/rtl/zeroer.sv:201`` drives
#     ``hwif_in.CTRL_STATUS.STATUS.next = zeroer_busy_o`` and ``:128`` defines
#     ``zeroer_busy_o = status_swacc[1] | (cur_state != ST_IDLE) |
#     (|outstanding_reqs)``. The implemented polarity is therefore BUSY.
# No field-level source states the implemented polarity, so this testcase
# transcribes none: S5 *observes* the lifecycle (0 before the trigger, 1 inside
# the trigger-to-idle window, 0 again after completion), which makes the S4 zero
# the closing half of a proven transition rather than an idle value a dead bit
# would also return. The CHK-ZEROER-CTRL-STATUS token cites ``zeroer.sv`` and
# the S5 observation for the polarity.
ZEROER_CTRL_STATUS_DONE = reg_field_pack("ZEROER_CTRL_CTRL_STATUS_reg_t", int_en=1, status=0)

OUTPUT_FABRIC_NEIGHBOUR_ADDR = OUTPUT_FABRIC_ADDR + 8
OUTPUT_FABRIC_MODEL_REGION = "zeroer_output_fabric"
OUTPUT_FABRIC_MODEL_SIZE = 0x1000
ZEROER_POISON = bytes.fromhex("a0a1a2a3a4a5a6a7")
ZEROER_NEIGHBOUR_POISON = bytes.fromhex("b0b1b2b3b4b5b6b7")
ZEROER_EXPECTED = bytes(len(ZEROER_POISON))
ZEROER_WAIT_CYCLES = 200

# --- S5 CTRL_STATUS busy-lifecycle positive control -------------------------
# The payload operation clears 8 bytes = one 64-bit AXI beat, which retires in
# far less time than one AXI-Lite CSR read takes to return, so polling
# CTRL_STATUS around it can never catch STATUS asserted. S5 therefore runs a
# SECOND, long zeroing purely as the positive control for the
# STATUS bit: BUSY_PROBE_SIZE bytes / 8 bytes per beat = BUSY_PROBE_BEATS beats,
# which holds `cur_state != ST_IDLE` (and `|outstanding_reqs`) across many CSR
# reads. It runs after every payload assertion, targets the same already-zeroed
# region, and stays inside OUTPUT_FABRIC_MODEL_SIZE so it cannot reach memory
# any other check depends on.
BUSY_PROBE_SIZE = 0x800
BUSY_PROBE_BEATS = BUSY_PROBE_SIZE // 8
# Bound is a liveness ceiling, not a checked quantity: expiry FAILS.
BUSY_PROBE_ASSERT_CYCLES = 400
BUSY_PROBE_CLEAR_CYCLES = 4000
# STATUS is bit 32 of the 64-bit CTRL_STATUS word, packed from the generated
# field layout rather than shifted by hand.
STATUS_BM = reg_field_pack("ZEROER_CTRL_CTRL_STATUS_reg_t", status=1)

# Coverage contract for SMC-ZEROER-WRITE-STREAM.S1. Kept as an independent
# literal: ``cells_hit`` is built from the individual observations in ``body``
# (one append per passing comparison), so ``satisfied`` compares two sets that
# can genuinely differ. Never assign ``cells_hit`` from this tuple.
REQUIRED_COVERAGE_CELLS = (
    "zeroer-region-zeroed",
    "zeroer-neighbours-untouched",
)


def _sample_output_write_count() -> int:
    """X-aware SYS_OUT write-counter sample (shared output-fabric VIP helper)."""
    writes, _reads = output_responder_counts()
    return writes


def _coverage_report_dirs() -> list[Path]:
    """Ordered candidate dirs for the artifact, most authoritative first.

    Only directories that belong to the run tree are offered, never the bare
    working directory: ``Path.cwd()`` is wherever the simulator was launched
    from (the repo root for a hand-run), so an artifact written there lands
    outside the run and a stale copy is indistinguishable from this run's. The
    caller writes exactly ONE copy -- the first candidate that accepts it -- so
    there is a single artifact per run to hash. ``<cwd>/coverage`` is the last
    resort for a bare ``pytest``-style invocation with neither harness variable
    set: a dedicated subdirectory, not the working directory itself.
    """
    candidates: list[Path] = []
    env_dir = os.environ.get("SMC_DV_RUN_LOGDIR")
    if env_dir:
        candidates.append(Path(env_dir))
    results = os.environ.get("COCOTB_RESULTS_FILE")
    if results:
        # .../<item>/results/results.xml → .../<item>/logs and .../<item>/coverage
        item_dir = Path(results).resolve().parent.parent
        candidates.append(item_dir / "logs")
        candidates.append(item_dir / "coverage")
    candidates.append(Path.cwd() / "coverage")
    # Deduplicate while preserving order.
    seen: set[Path] = set()
    out: list[Path] = []
    for path in candidates:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            out.append(resolved)
    return out


def _run_seed() -> int:
    """Seed actually applied to this run, from the harness variable the TB reads.

    ``smc_base_test.random_seed()`` reads ``RANDOM_SEED`` and the runner exports
    it (``tools/dv/runlib/stages.py``). ``SEED`` is never set by the harness, so
    an artifact stamped from it would carry the default ``1`` while the run used
    a different seed ([SEED-REPRODUCIBLE]). Absent is a failure, not a default:
    an artifact that names the wrong seed cannot be reproduced.
    """
    raw = os.environ.get("RANDOM_SEED")
    assert raw, (
        "RANDOM_SEED is not set: the functional-coverage-report must record the "
        "seed that produced it, and defaulting to 1 would publish an "
        "unreproducible claim"
    )
    return int(raw, 0)


def _emit_functional_coverage_report(cells_hit: list[str]) -> Path:
    """Write FL-required functional-coverage-report for WRITE-STREAM.S1 cells.

    ``cells_hit`` MUST come from the caller's per-cell observations; this
    function never derives it from ``REQUIRED_COVERAGE_CELLS``: deriving it there
    would make ``satisfied`` an ``expected >= expected`` tautology
    ([NO-FABRICATED-VERDICT]).
    """
    payload = {
        "artifact_type": "functional-coverage-report",
        "feature_key": "SMC-ZEROER-WRITE-STREAM.S1",
        "method": "DIRECTED",
        "seed": _run_seed(),
        "required_cells": list(REQUIRED_COVERAGE_CELLS),
        "cells_hit": cells_hit,
        "satisfied": set(cells_hit) >= set(REQUIRED_COVERAGE_CELLS),
    }
    text = json.dumps(payload, indent=2) + "\n"
    # Exactly one copy, in the most authoritative writable location.
    for out_dir in _coverage_report_dirs():
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / "functional-coverage-report.json"
            out_path.write_text(text, encoding="utf-8")
            return out_path
        except OSError:
            continue
    raise AssertionError("failed to write functional-coverage-report.json")


class smc_zeroer_dma_timeout_test_seq(output_fabric_pass_all_cfg_seq):
    """Program zeroer and verify that output-fabric bytes are actually cleared.

    Inherits the shared output-fabric filter programming
    (``program_inbound_pass_all`` / ``program_outbound_pass_all``) from
    ``output_fabric_pass_all_cfg_seq``.
    """

    def __init__(self, name: str = "smc_zeroer_dma_timeout_test_seq") -> None:
        super().__init__(name)
        self.checked_bytes = 0

    def _ensure_model_region(self) -> None:
        if OUTPUT_FABRIC_MODEL_REGION not in self.memory_model.regions:
            self.memory_model.add_region(
                OUTPUT_FABRIC_MODEL_REGION,
                OUTPUT_FABRIC_ADDR,
                OUTPUT_FABRIC_MODEL_SIZE,
            )

    async def _write_bytes(self, addr: int, data: bytes) -> None:
        assert self.env is not None, "sequence env is not initialized"
        item_name = f"jtag_output_preload_0x{addr:x}"
        item = SmcSysAxiItem(item_name)
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = len(data)
        item.wdata = int.from_bytes(data, "little")
        await _OneShot(item, f"{item_name}_os").start(self.env.jtag_axi_agent.sequencer)

    async def _read_bytes(self, addr: int, length: int) -> bytes:
        assert self.env is not None, "sequence env is not initialized"
        item_name = f"jtag_output_readback_0x{addr:x}"
        item = SmcSysAxiItem(item_name)
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = length
        await _OneShot(item, f"{item_name}_os").start(self.env.jtag_axi_agent.sequencer)
        return item.rdata.to_bytes(length, "little")

    async def _wait_for_zeroer_write(self, start_writes: int, start_reads: int) -> None:
        """Exact-count wait for the single zeroer beat on the SYS_OUT responder.

        ``ZEROER_SIZE`` is 8 bytes against a 64-bit data path, so the operation
        is EXACTLY one AXI write beat and the count is knowable, not merely
        bounded below: a second beat is the signature of a size/burst-length or
        strobe defect writing past the configured region, and a ``>=`` poll
        accepts it. ``check_output_responder_delta(exact_writes=True)`` fails
        the moment the counter passes the expected value, and additionally
        cross-checks the beat's address and data -- the zeroer must write
        ``0`` at ``OUTPUT_FABRIC_ADDR``. Expiry raises with the last observed
        state ([TIMEOUT-MUST-FAIL]).
        """
        await check_output_responder_delta(
            start_writes=start_writes,
            start_reads=start_reads,
            write_delta=1,
            read_delta=0,
            last_addr=OUTPUT_FABRIC_ADDR,
            last_wdata=0,
            exact_writes=True,
            timeout_cycles=ZEROER_WAIT_CYCLES,
        )

    async def body(self) -> None:
        cocotb.log.info(
            "STEP S1: SETUP pass-all filters; JTAG-preload poison "
            f"{ZEROER_POISON.hex()} at {OUTPUT_FABRIC_ADDR:#x} and neighbour "
            f"{ZEROER_NEIGHBOUR_POISON.hex()} at {OUTPUT_FABRIC_NEIGHBOUR_ADDR:#x}"
        )
        self._ensure_model_region()
        # Inherited from output_fabric_pass_all_cfg_seq.
        await self.program_inbound_pass_all()
        await self.program_outbound_pass_all()

        # Track poison in the VIP model for neighbour bookkeeping only; the
        # zeroed-region oracle is JTAG AXI readback vs ZEROER_EXPECTED, not
        # memory_model.expect after rewriting the model.
        self.memory_model.write(
            OUTPUT_FABRIC_ADDR, ZEROER_POISON, region=OUTPUT_FABRIC_MODEL_REGION
        )
        self.memory_model.write(
            OUTPUT_FABRIC_NEIGHBOUR_ADDR, ZEROER_NEIGHBOUR_POISON, region=OUTPUT_FABRIC_MODEL_REGION
        )
        await self._write_bytes(OUTPUT_FABRIC_ADDR, ZEROER_POISON)
        await self._write_bytes(OUTPUT_FABRIC_NEIGHBOUR_ADDR, ZEROER_NEIGHBOUR_POISON)
        preload_rb = await self._read_bytes(OUTPUT_FABRIC_ADDR, len(ZEROER_POISON))
        neighbour_preload = await self._read_bytes(
            OUTPUT_FABRIC_NEIGHBOUR_ADDR, len(ZEROER_NEIGHBOUR_POISON)
        )
        assert preload_rb == ZEROER_POISON
        assert neighbour_preload == ZEROER_NEIGHBOUR_POISON
        # Baseline AFTER JTAG preload so the +1 cannot be satisfied by preload writes.
        start_writes, start_reads = output_responder_counts()
        cocotb.log.info(
            "CHK-NONVAC: S1 JTAG preload readback confirms poison "
            f"{preload_rb.hex()} and neighbour {neighbour_preload.hex()} "
            f"were written and observed before trigger; "
            f"write-count baseline after preload={start_writes}"
        )

        cocotb.log.info(
            "STEP S2: program ZEROER_DEST_ADDR/SIZE from smc_reg map "
            f"(DEST@{ZEROER_DEST_ADDR:#x} SIZE@{ZEROER_SIZE:#x})"
        )
        await self.csr_write("ZEROER_DEST_ADDR", ZEROER_DEST_ADDR, OUTPUT_FABRIC_ADDR, length=8)
        await self.csr_write("ZEROER_SIZE", ZEROER_SIZE, len(ZEROER_POISON), length=8)
        # Read both command words back before the trigger. `expected=` is the
        # compare: the scoreboard applies an exact 64-bit equality and raises on
        # mismatch, so a command register that dropped the write, aliased onto
        # its sibling, or returned a reset value is caught here rather than
        # showing up later as an unexplained wrong-sized operation. Neither
        # register carries a write side effect (only CTRL_STATUS does --
        # zeroer_ctrl.rdl gives INT_EN wr_swacc), so the readbacks cannot start
        # the FSM early.
        dest_rb = await self.csr_read(
            "ZEROER_DEST_ADDR_RB", ZEROER_DEST_ADDR, expected=OUTPUT_FABRIC_ADDR, length=8
        )
        size_rb = await self.csr_read(
            "ZEROER_SIZE_RB", ZEROER_SIZE, expected=len(ZEROER_POISON), length=8
        )
        assert dest_rb == OUTPUT_FABRIC_ADDR and size_rb == len(ZEROER_POISON), (
            f"zeroer command registers did not hold the programmed values: "
            f"DEST_ADDR read {dest_rb:#x} (wrote {OUTPUT_FABRIC_ADDR:#x}), "
            f"SIZE read {size_rb:#x} (wrote {len(ZEROER_POISON):#x})"
        )
        cocotb.log.info(
            "CHK-ZEROER-CMD-READBACK: DEST_ADDR@"
            f"{ZEROER_DEST_ADDR:#x} reads {dest_rb:#x} and SIZE@{ZEROER_SIZE:#x} "
            f"reads {size_rb:#x}, both equal to what S2 wrote"
        )
        cocotb.log.info(
            "CHK-ZEROER-REGION-DECODE: csr_write ZEROER_DEST_ADDR@"
            f"{ZEROER_DEST_ADDR:#x}={OUTPUT_FABRIC_ADDR:#x} and ZEROER_SIZE@"
            f"{ZEROER_SIZE:#x}={len(ZEROER_POISON)} both OKAY "
            "(addresses from smc_reg ZEROER_CTRL_*_REG_ADDR)"
        )

        cocotb.log.info("STEP S3: trigger ZEROER_CTRL_STATUS.int_en=1; wait writes; readback zeros")
        # The zeroer FSM starts on the INT_EN field write side effect.
        await self.csr_write(
            "ZEROER_CTRL_STATUS_START", ZEROER_CTRL_STATUS, ZEROER_CTRL_STATUS_START, length=8
        )
        # Exactly one AXI write clears the 8-byte DEST region; neighbour is
        # untouched. `exact_writes=True` makes a second beat a failure.
        await self._wait_for_zeroer_write(start_writes, start_reads)
        write_count = _sample_output_write_count()
        cocotb.log.info(
            "CHK-ZEROER-TRIGGER-STARTS: after DEST/SIZE set, "
            f"ZEROER_CTRL_STATUS_START@{ZEROER_CTRL_STATUS:#x}="
            f"{ZEROER_CTRL_STATUS_START:#x} (int_en from the generated field layout) caused "
            f"tb_output_axi_write_count {start_writes}->{write_count} "
            f"(post-preload baseline+1 EXACTLY, last_addr={OUTPUT_FABRIC_ADDR:#x} "
            f"last_wdata=0) within bound={ZEROER_WAIT_CYCLES} clk_smc_i"
        )

        actual = await self._read_bytes(OUTPUT_FABRIC_ADDR, len(ZEROER_EXPECTED))
        neighbour_after = await self._read_bytes(
            OUTPUT_FABRIC_NEIGHBOUR_ADDR, len(ZEROER_NEIGHBOUR_POISON)
        )
        # Independent oracles: AXI readback vs ZEROER_EXPECTED / neighbour poison.
        # Do not rewrite memory_model then expect — that is a self-compare.
        #
        # Each coverage cell is credited from its OWN comparison result, and the
        # artifact is written before the asserts fire, so a run in which either
        # comparison failed publishes `cells_hit` without that cell and
        # `satisfied: false` — the verdict is measured, not declared.
        region_zeroed = actual == ZEROER_EXPECTED
        neighbours_untouched = neighbour_after == ZEROER_NEIGHBOUR_POISON
        cells_hit: list[str] = []
        if region_zeroed:
            cells_hit.append("zeroer-region-zeroed")
        if neighbours_untouched:
            cells_hit.append("zeroer-neighbours-untouched")
        report_path = _emit_functional_coverage_report(cells_hit)

        assert region_zeroed, (
            f"zeroer did not clear payload: got {actual.hex()}, expected {ZEROER_EXPECTED.hex()}"
        )
        assert neighbours_untouched, (
            "zeroer modified neighbour bytes outside configured region: "
            f"got {neighbour_after.hex()}, expected {ZEROER_NEIGHBOUR_POISON.hex()}"
        )
        assert write_count == start_writes + 1, (
            f"zeroer output-fabric write count is {write_count}, expected "
            f"exactly {start_writes + 1}: ZEROER_SIZE={len(ZEROER_POISON)} "
            f"bytes on a 64-bit data path is exactly one AXI beat, so any "
            f"other count is a size/burst-length defect"
        )
        assert set(cells_hit) >= set(REQUIRED_COVERAGE_CELLS), (
            f"required coverage cells not hit: missing "
            f"{sorted(set(REQUIRED_COVERAGE_CELLS) - set(cells_hit))}"
        )
        self.checked_bytes = len(ZEROER_EXPECTED)

        cocotb.log.info(
            "STEP S4: read ZEROER_CTRL_STATUS back and check the armed INT_EN "
            "plus the deasserted busy status (see ZEROER_CTRL_STATUS_DONE)"
        )
        ctrl_status = await self.csr_read(
            "ZEROER_CTRL_STATUS_DONE",
            ZEROER_CTRL_STATUS,
            expected=ZEROER_CTRL_STATUS_DONE,
            length=8,
        )
        cocotb.log.info(
            "CHK-ZEROER-CTRL-STATUS: CTRL_STATUS@"
            f"{ZEROER_CTRL_STATUS:#x} reads {ctrl_status:#018x} == "
            f"{ZEROER_CTRL_STATUS_DONE:#018x} -- INT_EN[0]=1 (the completion "
            "interrupt this test armed at S3 is latched in the register, rdl "
            "sw=rw/hw=r), STATUS[32]=0 (polarity is BUSY per zeroer.sv:201 / "
            ":128 and is OBSERVED in S5's 0->1->0 lifecycle, NOT transcribed "
            "from documentation: zeroer_ctrl.rdl:51 and the generated "
            "zeroer_ctrl.adoc that zeroer.adoc includes describe the field as "
            "'completed'; the operation is independently proven complete "
            "above), reserved bits 0. SCOPE: the INT_EN write is load-bearing "
            "(zeroer_ctrl.rdl:43 gives it wr_swacc and zeroer.sv:207/:260 make "
            "that strobe the FSM trigger), so it cannot be written as 0; the "
            "resulting completion IRQ OUTPUT is UNOBSERVED here and by every "
            "SMC cocotb testcase -- hw/sys/smc/dv/tb/tb_top.sv exposes no "
            "tb_zeroer_*_irq observability port. This token claims the latched "
            "enable only, never the interrupt firing."
        )

        cocotb.log.info(
            "CHK-ZEROER-REGION-ZEROED: JTAG readback at OUTPUT_FABRIC_ADDR "
            f"returns {actual.hex()} (8 zero bytes), replacing poison; "
            f"neighbour@{OUTPUT_FABRIC_NEIGHBOUR_ADDR:#x} still "
            f"{neighbour_after.hex()}; "
            f"tb_output_axi_write_count={write_count} >= post-preload baseline+1 "
            f"(baseline={start_writes}); "
            f"COV cells={cells_hit}; functional-coverage-report={report_path}"
        )
        await self._prove_status_busy_lifecycle()

        cocotb.log.info("SMC_006 scenario PASS")

    async def _prove_status_busy_lifecycle(self) -> None:
        """Observe CTRL_STATUS.STATUS 0 -> 1 -> 0 on a long zeroing.

        Without this, every STATUS compare in the testcase is against 0, and a
        STATUS bit tied low, undriven, or never connected through the hwif path
        passes identically to a working busy flag -- 0 is simultaneously "not
        busy", "not completed" and "field absent"
        ([NEGATIVE-NEEDS-POSITIVE-CONTROL]). The asserted state is the only
        observation that separates those.
        """
        # Sampled here rather than inherited from the caller's earlier read, so
        # the cleared leg is observed at the point the lifecycle claims it.
        cleared_before = await self.csr_read("ZEROER_STATUS_CLEARED", ZEROER_CTRL_STATUS)
        assert not (cleared_before & STATUS_BM), (
            f"CTRL_STATUS pre-trigger read {cleared_before:#018x} already has "
            f"STATUS set (mask {STATUS_BM:#018x}); the lifecycle cannot start "
            f"from a cleared state"
        )

        cocotb.log.info(
            "STEP S5: prove CTRL_STATUS.STATUS can read 1 -- re-arm with "
            f"SIZE={BUSY_PROBE_SIZE:#x} ({BUSY_PROBE_BEATS} beats) and sample "
            "STATUS inside the trigger-to-idle window"
        )
        await self.csr_write("ZEROER_SIZE_BUSY_PROBE", ZEROER_SIZE, BUSY_PROBE_SIZE, length=8)
        await self.csr_write(
            "ZEROER_CTRL_STATUS_BUSY_PROBE", ZEROER_CTRL_STATUS, ZEROER_CTRL_STATUS_START, length=8
        )

        busy_word = None
        for _ in range(BUSY_PROBE_ASSERT_CYCLES):
            word = await self.csr_read("ZEROER_CTRL_STATUS_BUSY_POLL", ZEROER_CTRL_STATUS, length=8)
            if word & STATUS_BM:
                busy_word = word
                break
        assert busy_word is not None, (
            f"CTRL_STATUS.STATUS (mask {STATUS_BM:#018x}) never read 1 while a "
            f"{BUSY_PROBE_SIZE:#x}-byte ({BUSY_PROBE_BEATS}-beat) zeroing was in "
            f"flight, polled {BUSY_PROBE_ASSERT_CYCLES} times -- the busy state "
            f"is unobservable, so every STATUS == 0 in this testcase is an "
            f"idle-zero a dead bit would also satisfy"
        )
        cocotb.log.info(
            "CHK-ZEROER-STATUS-BUSY-ASSERTED: CTRL_STATUS read "
            f"{busy_word:#018x} with STATUS[32]=1 during the "
            f"{BUSY_PROBE_BEATS}-beat zeroing"
        )

        cleared_word = None
        for _ in range(BUSY_PROBE_CLEAR_CYCLES):
            word = await self.csr_read(
                "ZEROER_CTRL_STATUS_CLEAR_POLL", ZEROER_CTRL_STATUS, length=8
            )
            if not (word & STATUS_BM):
                cleared_word = word
                break
        assert cleared_word is not None, (
            f"CTRL_STATUS.STATUS stayed 1 after the {BUSY_PROBE_BEATS}-beat "
            f"zeroing should have retired, polled {BUSY_PROBE_CLEAR_CYCLES} "
            f"times -- a stuck-high busy flag"
        )
        assert cleared_word == ZEROER_CTRL_STATUS_DONE, (
            f"CTRL_STATUS settled to {cleared_word:#018x}, expected "
            f"{ZEROER_CTRL_STATUS_DONE:#018x} (INT_EN latched, STATUS clear, "
            f"reserved zero)"
        )
        cocotb.log.info(
            "CHK-ZEROER-STATUS-LIFECYCLE: CTRL_STATUS.STATUS observed "
            f"0 (S4 {cleared_before:#018x}) -> 1 ({busy_word:#018x}) -> "
            f"0 ({cleared_word:#018x}); the field tracks zeroer_busy_o through "
            "the hwif path and is not a tied-low bit"
        )
