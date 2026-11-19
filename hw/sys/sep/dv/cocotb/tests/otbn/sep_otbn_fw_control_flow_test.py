# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Firmware drives OTBN from load to result, once on the done interrupt and once by polling.

Spec (``OTBN/`` = ``vendor/lowRISC/opentitan/upstream/hw/ip/otbn/``, ``ToO`` =
``OTBN/doc/theory_of_operation.md``): ``CMD`` EXECUTE (``OTBN/data/otbn.hjson``
:453, :479-481); ``STATUS`` codes (:536-541); "All operations signal their
completion by raising the done interrupt; alternatively, software may poll the
STATUS register" (:460-461); ``done`` (:153-156); EXECUTE runs until ``ecall``, then
the internal wipe, ``ERR_BITS``, IDLE and ``done`` (ToO:132-139); ``INTR_STATE``
is RW1C and ``INTR_ENABLE.done`` gates the line (``OTBN/doc/registers.md`` :37,
:54); OTBN done is vector bit 29, PIC source 30 (``hw/sys/sep/doc/interrupts.adoc``
:22-27, :165-167).

The firmware (``fw/tests/otbn_fw_control_flow_test``) brings the entropy stack up
(EXECUTE reseeds URND from EDN, ToO:80-81, :133), waits for IDLE after the reset
wipe, loads an 11-word program of base instructions into IMEM (``lw``, ``add``,
``xor``, ``addi``, ``bne``, ``sw``, ``ecall``; encodings of ``OTBN/data/base-insns.yml``,
semantics of RV32I by ``OTBN/data/insns.yml`` :225-229) and runs two legs. Each leg
stages DMEM words a, b, n and the sentinels ~s, ~t, writes ``CMD`` = EXECUTE and
reads back DMEM[8] and DMEM[12]:

  irq   ``INTR_ENABLE.done`` = 1; the handler reads the claim id, writes 1 to
        ``INTR_STATE.done`` and counts; the firmware waits for the count.
  poll  ``INTR_ENABLE.done`` = 0; the firmware polls ``STATUS`` until IDLE,
        reads ``INTR_STATE``, writes 1 to it and reads it again.

The program computes s = (a + b) mod 2^32 and t = ((s ^ a) + n * s) mod 2^32 and
stores s at DMEM byte 8 and t at DMEM byte 12. The leaf draws a, b and n from the
seed and patches them into the firmware parameter block: the irq leg carries out
of bit 31 (a + b > 2^32), the poll leg does not, and n is 1 to 8 per leg.

Checks:
  CHK-OTBN-FW-RESULT  per leg: the printed DMEM[8] and DMEM[12] equal s and t of
                      the leaf's own golden, and ``ERR_BITS`` reads 0 ("set to
                      indicate either a successful execution (value 0)", ToO:137).
  CHK-OTBN-FW-STATUS  ``otbn_status_probe_o`` after the reset wipe ends at IDLE
                      shows exactly two operations, each with BUSY_EXECUTE (0x01)
                      as the first code, only 0x01 or BUSY_SEC_WIPE_INT (0x04)
                      until IDLE, and never LOCKED (0xFF) or X; the firmware read
                      of ``STATUS`` at the end of each leg is IDLE.
  CHK-OTBN-FW-IRQ     irq leg: one handler entry, claim id 30, ``INTR_STATE.done``
                      reads 0 after the handler, and one rise of vector bit 29
                      from the start of that operation to the start of the next.
                      Poll leg: no handler entry, no rise of bit 29 from the start
                      of that operation to the end of the run,
                      ``INTR_STATE.done`` reads 1, then 0 after the write of 1.

Control:
  CTRL-OTBN-FW-POLL-REACH  the poll leg read a busy code at least once, so it
                      polled a running operation.

Log-only:
  OBS-OTBN-FW-INIT-INTR    ``INTR_STATE`` after the reset wipe: ToO:139 states
                      ``done`` for EXECUTE only.
  OBS-OTBN-FW-STATUS-SEQ   the probe codes of each operation and the firmware's
                      first ``STATUS`` read after ``CMD``: no sentence states
                      whether EXECUTE shows 0x04 during its end-of-run wipe.
  INFO-OTBN-FW-INSN        ``INSN_CNT`` of each leg and 3n + 8, the count with
                      ``ecall`` included (not graded).

``STATUS`` is read from ``otbn_status_probe_o`` and the done line from
``sep_internal_interrupts_probe_o`` bit 29 (docs/SEP_TB_ARCH.adoc), both from
before the boot.

Run mode: cpu, ``+skip_fuse_sense +esrc_noise_force`` (no fuse data is read; the
raw noise is driven by the testbench).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import cocotb
import pyuvm
from cocotb.utils import get_sim_time
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_chk_log import SepChkLog
from env.sep_dtcm_param_patch import patch_param_block
from env.sep_edge_timer import SepEdgeTimer
from env.sep_seeded_rng import SepSeededRng
from env.sep_spec_tables import ot_rdl_table_code
from sep_base_test import sep_base_test
from sep_reg_meta import OTBN, sym

TEST = "sep_otbn_fw_control_flow_test"

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "otbn_fw_control_flow_test")
_ITCM_HEX = os.path.join(_FW_DIR, "otbn_fw_control_flow_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "otbn_fw_control_flow_test.dtcm.hex")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
# The entropy boot window and two short operations; the run loop ends at fw_done.
_MAX_RUN_CYCLES = 2_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
_BANNER = "SEP OTBN firmware control flow test"

# g_otbn_params in otbn_fw_control_flow_test.c: magic, a1, b1, n1, a2, b2, n2, s1, t1, s2, t2.
_PARAM_MAGIC = 0x0B7EF10C
# The firmware accepts n in [1, _N_MAX].
_N_MAX = 8
_M32 = 1 << 32

ST_IDLE = ot_rdl_table_code("otbn", "STATUS", "IDLE")
ST_BUSY_EXECUTE = ot_rdl_table_code("otbn", "STATUS", "BUSY_EXECUTE")
ST_SEC_WIPE_INT = ot_rdl_table_code("otbn", "STATUS", "BUSY_SEC_WIPE_INT")
M_STATUS = OTBN.field_mask("STATUS", "status")
M_DONE = OTBN.field_mask("INTR_STATE", "done")
EXEC_CODES = (ST_BUSY_EXECUTE, ST_SEC_WIPE_INT)

# Vector bit 29 is PIC source 30, OTBN done (interrupts.adoc:22-27, :165-167).
VEC_OTBN_DONE = 29
PIC_SRC_OTBN_DONE = VEC_OTBN_DONE + 1

LEGS = ("irq", "poll")
_FIELD = re.compile(r"(\w+)=(0x[0-9a-f]+|\w+)")


def golden(a: int, b: int, n: int) -> tuple[int, int]:
    """(s, t) of the OTBN program: s = a + b, t = (s ^ a) + n * s, modulo 2^32."""
    s = (a + b) % _M32
    return s, ((s ^ a) + n * s) % _M32


def draw_plan(seed: int) -> dict[str, tuple[int, int, int]]:
    """Per leg (a, b, n): the irq leg carries out of bit 31, the poll leg does not."""
    rng = SepSeededRng(seed)
    a1 = rng.randrange(2, _M32)
    b1 = rng.randrange(_M32 - a1 + 1, _M32)
    n1 = rng.randrange(1, _N_MAX + 1)
    a2 = rng.randrange(1, _M32 - 1)
    b2 = rng.randrange(0, _M32 - a2)
    n2 = rng.randrange(1, _N_MAX + 1)
    return {"irq": (a1, b1, n1), "poll": (a2, b2, n2)}


def parse_line(console: str, head: str) -> dict[str, str] | None:
    """Fields of the first console line that starts with ``head``, or None."""
    for ln in console.splitlines():
        if ln.startswith(head):
            return dict(_FIELD.findall(ln[len(head) :]))
    return None


def episodes(changes: list[tuple[int, int | None]]) -> tuple[list, list[tuple[int, list, bool]]]:
    """Split the (time, code) changes of the probe where the reset wipe ends.

    The reset wipe ends at the first IDLE after the first BUSY_SEC_WIPE_INT; a
    2-state simulator reads IDLE during reset, before the wipe starts. Returns
    the codes before that IDLE and, per operation after it, (start time, codes,
    ended): an operation is the codes from a change away from IDLE up to the next
    IDLE; ``ended`` is False for one still open at the end of the record.
    """
    codes = [c for _, c in changes]
    wipe = codes.index(ST_SEC_WIPE_INT) if ST_SEC_WIPE_INT in codes else len(codes)
    if ST_IDLE not in codes[wipe:]:
        return codes, []
    first = codes.index(ST_IDLE, wipe)
    ops: list[tuple[int, list, bool]] = []
    for t_ps, c in changes[first + 1 :]:
        if c == ST_IDLE:
            if ops and not ops[-1][2]:
                ops[-1] = (ops[-1][0], ops[-1][1], True)
        elif ops and not ops[-1][2]:
            ops[-1][1].append(c)
        else:
            ops.append((t_ps, [c], False))
    return codes[:first], ops


def _fmt_codes(codes: list[int | None]) -> str:
    return ",".join("X" if c is None else f"0x{c:02x}" for c in codes) or "-"


@pyuvm.test()
class sep_otbn_fw_control_flow_test(sep_base_test):
    """Firmware loads, starts and reads OTBN with the done interrupt and with STATUS polling."""

    build_env = False
    required_evidence = ("CHK-OTBN-FW-RESULT", "CHK-OTBN-FW-STATUS", "CHK-OTBN-FW-IRQ")

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    def _stage_dtcm(self, plan: dict[str, tuple[int, int, int]]) -> str:
        words = [_PARAM_MAGIC]
        for leg in LEGS:
            words += list(plan[leg])
        for leg in LEGS:
            words += list(golden(*plan[leg]))
        patched = os.path.join(os.getcwd(), "sep_dtcm_otbn_fw_control_flow.hex")
        patch_param_block(_DTCM_HEX, patched, _PARAM_MAGIC, words)
        return patched

    async def run_scenario(self) -> None:
        dut = cocotb.top
        self.sb.expected_line = _BANNER
        seed = self.random_seed()
        plan = draw_plan(seed)
        self.chk = chk = SepChkLog(self, TEST, seed)
        chk.info(
            "RANDCFG",
            **{f"{k}_{leg}": f"0x{v:08x}" for leg in LEGS for k, v in zip("abn", plan[leg])},
        )
        dtcm = self._stage_dtcm(plan)

        status_t = SepEdgeTimer(dut.otbn_status_probe_o, name="otbn_status").start()
        irq_t = SepEdgeTimer(dut.sep_internal_interrupts_probe_o, name="internal_irq").start()
        noise = self.start_esrc_noise_driver()
        try:
            await self.boot_firmware(
                self.sb,
                _ITCM_HEX,
                dtcm,
                rst_vec=_ICCM_BASE >> 1,
                max_run_cycles=_MAX_RUN_CYCLES,
                no_boot_cycles=_NO_BOOT_CYCLES,
                progress_every=_PROGRESS_EVERY,
            )
        finally:
            await noise.stop()
        t_end = int(get_sim_time("ps"))
        await status_t.stop()
        await irq_t.stop()

        console = self.sb.console_text()
        legs = {leg: parse_line(console, f"INFO-OTBN-FW-LEG leg={leg}") for leg in LEGS}
        init = parse_line(console, "INFO-OTBN-FW-INIT")
        chk.obs(
            "OTBN-FW-INIT-INTR",
            intr=init.get("intr", "none") if init else "none",
            polls=init.get("polls", "none") if init else "none",
        )

        # Result per leg.
        for leg in LEGS:
            s, t = golden(*plan[leg])
            f = legs[leg]
            if f is None:
                chk.ok("OTBN-FW-RESULT", False, leg=leg, reason="no_leg_line")
                continue
            got_s, got_t, err = int(f["s"], 16), int(f["t"], 16), int(f["err"], 16)
            chk.ok(
                "OTBN-FW-RESULT",
                got_s == s and got_t == t and err == 0,
                leg=leg,
                a=f"0x{plan[leg][0]:08x}",
                b=f"0x{plan[leg][1]:08x}",
                n=plan[leg][2],
                s=f["s"],
                s_exp=f"0x{s:08x}",
                t=f["t"],
                t_exp=f"0x{t:08x}",
                err_bits=f["err"],
            )
            chk.info(
                "OTBN-FW-INSN",
                leg=leg,
                insn_cnt=int(f["insn"], 16),
                count_with_ecall=3 * plan[leg][2] + 8,
            )

        # STATUS sequence on the probe.
        changes = [
            (c.t_ps, None if c.value is None else c.value & M_STATUS)
            for c in status_t.since(until_ps=t_end)
        ]
        pre, ops = episodes(changes)
        run_ok = [
            ended and codes[0] == ST_BUSY_EXECUTE and all(c in EXEC_CODES for c in codes)
            for _, codes, ended in ops
        ]
        starts = [t_ps for t_ps, _, _ in ops]
        st_end = {leg: int(legs[leg]["st_end"], 16) if legs[leg] else None for leg in LEGS}
        chk.obs(
            "OTBN-FW-STATUS-SEQ",
            before_idle=_fmt_codes(pre),
            ops=len(ops),
            **{f"op{i}": _fmt_codes(codes) for i, (_, codes, _) in enumerate(ops)},
            **{f"op{i}_ended": ended for i, (_, _, ended) in enumerate(ops)},
            **{f"st0_{leg}": legs[leg]["st0"] if legs[leg] else "none" for leg in LEGS},
        )
        chk.ok(
            "OTBN-FW-STATUS",
            len(ops) == len(LEGS) and all(run_ok) and all(v == ST_IDLE for v in st_end.values()),
            ops=len(ops),
            expect_ops=len(LEGS),
            op_ok=[int(x) for x in run_ok],
            **{f"st_end_{leg}": "none" if v is None else f"0x{v:02x}" for leg, v in st_end.items()},
        )

        poll = legs["poll"]
        if poll is not None:
            busy_reads = int(poll["busy_reads"], 16)
            chk.ctrl(
                "OTBN-FW-POLL-REACH",
                busy_reads >= 1,
                busy_reads=busy_reads,
                polls=int(poll["polls"], 16),
                bad_code=poll["bad_code"],
            )

        # Done interrupt.
        irq = legs["irq"]
        if irq is None or poll is None or len(starts) < len(LEGS):
            chk.ok(
                "OTBN-FW-IRQ",
                False,
                reason="missing_leg_or_operation",
                irq_line=int(irq is not None),
                poll_line=int(poll is not None),
                ops=len(starts),
            )
        else:
            rises_irq = irq_t.rises(starts[0], until_ps=starts[1] - 1, bit=VEC_OTBN_DONE)
            rises_poll = irq_t.rises(starts[1], until_ps=t_end, bit=VEC_OTBN_DONE)
            irqs_irq, irqs_poll = int(irq["irqs"], 16), int(poll["irqs"], 16)
            claim = int(irq["claim"], 16)
            intr_irq = int(irq["intr"], 16) & M_DONE
            intr_poll = int(poll["intr"], 16) & M_DONE
            intr_poll_clr = int(poll["intr_clr"], 16) & M_DONE
            chk.ok(
                "OTBN-FW-IRQ",
                irqs_irq == 1
                and claim == PIC_SRC_OTBN_DONE
                and intr_irq == 0
                and len(rises_irq) == 1
                and irqs_poll == irqs_irq
                and len(rises_poll) == 0
                and intr_poll == 1
                and intr_poll_clr == 0,
                irq_handler_entries=irqs_irq,
                claim=claim,
                claim_exp=PIC_SRC_OTBN_DONE,
                irq_done_after_handler=intr_irq,
                irq_line_rises=len(rises_irq),
                poll_handler_entries=irqs_poll - irqs_irq,
                poll_line_rises=len(rises_poll),
                poll_done=intr_poll,
                poll_done_after_w1c=intr_poll_clr,
            )

        assert self.sb.fw_done and self.sb.fw_pass, (
            f"firmware did not complete with PASS: fw_done={self.sb.fw_done} "
            f"fw_pass={self.sb.fw_pass}. Console was:\n{console}"
        )
        chk.finish()
