# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OTBN runs ADD, XOR, AND and five capability programs, each to its ISA golden.

Loads a short OTBN program into IMEM over the CPU-LSU AXI master, stages
seeded DMEM operands, issues EXECUTE, and grades STATUS, ERR_BITS and the DMEM
result against an independent Python golden. Every run walks:

* ADD, XOR and AND of two 32-bit words (CHK-ERRBITS, CHK-DMEM);
* the five capabilities of hw/sys/sep/doc/otbn.adoc:16-21 (CHK-OTBN-CAP):
  a ``loopi`` loop, taken and not-taken ``beq`` / ``bne``, a ``jal x1`` call
  with its ``jalr x0, x1, 0`` return, ``bn.add`` then ``bn.addc`` with the
  carry set, and ``bn.addm`` with a + b > MOD. The goldens follow
  vendor/lowRISC/opentitan/upstream/hw/ip/otbn/data/base-insns.yml and
  bignum-insns.yml. The seed sets the operands only (RANDCFG).

Distinct from sep_otbn_mem_smoke_test (write/readback, no EXECUTE) and from
sep_km_otbn_sideload_kat_test (WSR reconstruct, no ALU golden).

FCOV: each capability program runs inside the graded window of this leaf. The
leaf writes the stimulus label ``otbn_cap_kind`` only after CHK-OTBN-CAP of
that program passed, so ``sep_otbn_op_cg.cp_capability`` never samples a
program whose check failed. The first FAIL closes the window for the rest of
the run.

no_cpu + +skip_fuse_sense + +esrc_noise_force: post-reset secure wipe consumes
OTBN URND, so the real entropy stack is brought up and other crypto-EDN
clients are parked.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_chk_log import SepChkLog
from env.sep_fcov_gate import close_graded_window, open_graded_window, set_otbn_cap_kind
from sep_base_test import sep_base_test
from seq_lib.sep_otbn_compute_seq import (
    CAP_DMEM_FG0,
    CAP_KINDS,
    SepOtbnCapPlan,
    SepOtbnCompute,
    SepOtbnComputeCfg,
    cap_golden,
    cap_prog,
    cap_stage,
)
from seq_lib.sep_otbn_seq import OTBN_STATUS_IDLE

_NAME = "sep_otbn_compute_rand_test"

# clk_i edges between a gate or label write and the next one, so the sampler
# sees each value on at least one edge.
_GATE_SETTLE = 2


def _hex_words(words: list[int]) -> str:
    return "0x" + "".join(f"{w:08x}" for w in reversed(words))


@pyuvm.test()
class sep_otbn_compute_rand_test(sep_base_test):
    """Each program retires at IDLE with ERR_BITS 0 and writes its ISA golden to DMEM."""

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu(park=("aes", "hmac", "kmac"))
        await self.bring_up_entropy(
            strict=True, score_km=False, score_sinks={"otbn_urnd": "observe"}
        )
        self.start_fifo_drain()

        seed = self.random_seed()
        self.chk = SepChkLog(self, _NAME, seed)
        cfg = SepOtbnComputeCfg.from_seed(seed)
        cap = SepOtbnCapPlan.from_seed(seed)
        self.logger.info("OTBN compute RANDCFG %s", cfg.summary())
        self.logger.info("OTBN capability RANDCFG %s", cap.summary())
        otbn = SepOtbnCompute(self)
        await otbn.wait_idle("post-wipe", timeout=8_000)

        for op, a, b, expect in cfg.cells():
            err, got = await otbn.run_cell(op, a, b, expect)
            fields = {"op": op, "a": f"0x{a:08x}", "b": f"0x{b:08x}"}
            self.chk.ok("ERRBITS", err == 0, **fields, err_bits=f"0x{err:08x}")
            self.chk.ok("DMEM", got == expect, **fields, got=f"0x{got:08x}", exp=f"0x{expect:08x}")
        self.chk.info(
            "RANDCFG", cells=list(op for op, *_ in cfg.cells()), capabilities=list(CAP_KINDS)
        )

        self._cap_window_ok = True
        for k, kind in enumerate(CAP_KINDS, start=1):
            await self._run_capability(otbn, cap, k, kind)

        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        assert self.drbg_sb.report()
        self.chk.finish()

    async def _run_capability(
        self, otbn: SepOtbnCompute, cap: SepOtbnCapPlan, k: int, kind: str
    ) -> None:
        """One capability program: stage, EXECUTE in the window, grade, then label."""
        clk = cocotb.top.clk_i
        golden = cap_golden(cap, kind)
        stage = cap_stage(cap, kind)
        # Each result word starts at the complement of its golden, so a word
        # the program never stores cannot match.
        stage.update({off: w ^ 0xFFFF_FFFF for off, w in golden.items()})
        await otbn.stage_program(cap_prog(cap, kind), stage)

        if self._cap_window_ok:
            open_graded_window(_NAME, self.logger)
            await ClockCycles(clk, _GATE_SETTLE)
        status, polls = await otbn.execute_to_end()
        err = await otbn.read_errbits()
        offs = sorted(golden)
        got = [await otbn.read_dmem(off) for off in offs]
        exp = [golden[off] for off in offs]

        fields = {
            "kind": kind,
            "label": k,
            "status": f"0x{status:02x}",
            "polls": polls,
            "err_bits": f"0x{err:08x}",
            "dmem_base": f"0x{offs[0]:03x}",
            "words": len(offs),
            "got": _hex_words(got),
            "exp": _hex_words(exp),
        }
        probe = True
        if kind == "loop":
            fields.update(n=cap.loop_n, step=cap.loop_step)
        elif kind == "branch":
            fields.update(eq=cap.br_eq, ne=cap.br_ne)
        elif kind == "call_return":
            fields.update(m1=cap.call_m1, m2=cap.call_m2)
        elif kind == "bn_addc_carry":
            # FG0.C as the program stored it between bn.add and bn.addc: the
            # carry that bn.addc consumes was set in the DUT.
            dut_carry = got[offs.index(CAP_DMEM_FG0)] & 1
            fields.update(carry=dut_carry, model_carry=cap.carry())
            probe = dut_carry == 1 and cap.carry() == 1
        elif kind == "bn_addm_reduce":
            fields.update(sum_gt_mod=int(cap.sum_gt_mod()), mod=f"0x{cap.mod:064x}")
            probe = cap.sum_gt_mod()
        passed = status == OTBN_STATUS_IDLE and err == 0 and got == exp and probe
        if not passed:
            close_graded_window(self.logger)
            self._cap_window_ok = False
        if kind in ("bn_addc_carry", "bn_addm_reduce"):
            self.chk.ctrl("OTBN-CAP", probe, **fields)
        self.chk.ok("OTBN-CAP", passed, **fields)

        if passed and self._cap_window_ok:
            set_otbn_cap_kind(k, self.logger)
            await ClockCycles(clk, _GATE_SETTLE)
            set_otbn_cap_kind(0, self.logger)
            await ClockCycles(clk, _GATE_SETTLE)
        close_graded_window(self.logger)
        await ClockCycles(clk, _GATE_SETTLE)
