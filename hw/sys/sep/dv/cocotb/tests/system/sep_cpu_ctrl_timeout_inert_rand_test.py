# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The SEP_CPU_CTRL timeout registers hold a written 1, and a real stall raises nothing.

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense``.

Contract (``hw/sys/sep/regs/gen/adoc/blocks/sep_cpu_ctrl.adoc``,
``TIMEOUT_INTERRUPT``, ``TIMEOUT_ENABLE``, ``TIMEOUT_COUNT_*``;
``hw/sys/sep/doc/fabric.adoc``, System Interface initiator, Fabric Topology;
``hw/sys/sep/doc/cpu.adoc``, Dual Scratch Register Banks;
``hw/sys/sep/regs/gen/adoc/blocks/sep_scratch.adoc``, ``SCRATCH``;
``hw/ip/axi_lite_mailbox_unit/regs/gen/adoc/axil_mailbox.adoc``, ``WIRQT``;
``hw/sys/sep/doc/entropy_pool.adoc``, "Access Policy";
``vendor/lowRISC/opentitan/overlay/regs/secure_dma/regs/gen/adoc/secure_dma.adoc``,
``STATUS``): the timeout block is reserved and not implemented.
``TIMEOUT_INTERRUPT`` (R, reset 0) reads 0. ``TIMEOUT_ENABLE`` and each
``TIMEOUT_COUNT_*`` register have one RW bit 0 (reset 0) that holds a written
1. A stall of a block path beyond its armed count sets no ``TIMEOUT_INTERRUPT``
bit, raises no PIC source and aborts no access. ``TIMEOUT_CLEAR`` and
``TIMEOUT_MODE`` are not accessed.

Stall legs, in the drawn block order:

* system input (``SCRATCH[0]`` of the cold bank) and inbound mailbox
  (``WIRQT`` of the inbound port of mailbox 0): the SMN master (``m_axi``)
  holds RREADY, then BREADY, low;
* outbound mailbox (``WIRQT`` of the outbound port of mailbox 0) and the
  entropy pool ``STATUS`` (64-bit read; a write answers SLVERR): the CPU-LSU
  master (``s_axi``) holds RREADY, then BREADY, low;
* outbound filter (an SMU window word), alias remap (a remapped page) and DMA
  (a one-word copy from the SMU window word): the error inject
  ``smn_outbound_resp_hold_i`` of the outbound responder
  (``tb/sep_outbound_mbx.sv``) holds the response; the request reaches
  ``smn_outbound_axi_req_o`` (tap ``PR-OUT``).

During each hold the master that does not hold reads ``TIMEOUT_INTERRUPT``
(the SMN master through an inbound filter entry). The spec does not state that
this read completes while the other response is held, so a read that does not
complete in its bound prints ``OBS-TO-INERT ... status=not_sampled`` and is
not a sample. The vector (``sep_internal_interrupts_probe_o``, the six
excluded idle sources masked) is compared with the baseline at the end of the
hold and after release.

Randomization (``SepSeededRng`` from the run seed): the order of the nine
arming writes and the order of the stalled blocks. The hold length, the
addresses and the write data are fixed.

Checkers:
  CHK-ARMED       the six counts not written by the open tests read 0x1.
  CHK-STALL-REAL  the stalled access gets no response during the hold and one
                  after release (one line per block and direction).
  CHK-TO-INERT    TIMEOUT_INTERRUPT 0x0, the masked vector equal to the
                  baseline, and the stated response of the stalled access.
  CTL-ARMED       reset reads and the three registers the open tests write.
  CTL-VEC-LIVE    a mailbox push raises vector bit 0 and its release drops it.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, NextTimeStep, ReadOnly, RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_axi_chan_mon import SepAxiChanMon, SepAxiReadyHold
from env.sep_fabric_tap import SepFabricTap
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_field_compare import field_compare
from env.sep_filter_model import FilterEntry
from env.sep_mbox_golden import IRQ_WTIRQ
from env.sep_pic_map import VEC_GRADED, idle_unstated_line
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import LOCAL_MASTER_ALIAS_REMAP_CTRL_0, SEP_CPU_CTRL, RegBlock, sym
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_dma_ops import _D, ST_BUSY, ST_DONE, ST_ERROR, SepDmaOps
from seq_lib.sep_fabric_csr_bank_seq import ALIAS_ATTRS, ALIAS_BASE, ALIAS_END, ALIAS_START
from seq_lib.sep_fabric_filter_bank_seq import SepFilterBank
from seq_lib.sep_mailbox_iface_seq import SepMbox
from seq_lib.sep_mbox_port_ops import REG_OFFSETS, port_base

TEST = "sep_cpu_ctrl_timeout_inert_rand_test"
RESP_OKAY, RESP_SLVERR = 0, 2
RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}

COUNTS_NEW = (
    "TIMEOUT_COUNT_MAILBOX_INBOUND",
    "TIMEOUT_COUNT_MAILBOX_OUTBOUND",
    "TIMEOUT_COUNT_ENTROPY_WRITE",
    "TIMEOUT_COUNT_ENTROPY_READ",
    "TIMEOUT_COUNT_FILTER_OUT",
    "TIMEOUT_COUNT_ALIAS_REMAP",
)
ARM_OPEN = ("TIMEOUT_ENABLE", "TIMEOUT_COUNT_DMA", "TIMEOUT_COUNT_SYS_IN")
ARM_REGS = COUNTS_NEW + ARM_OPEN
TO_INT = SEP_CPU_CTRL.addr("TIMEOUT_INTERRUPT")
TO_INT_FIELD = SEP_CPU_CTRL.field_mask("TIMEOUT_INTERRUPT", "reserved")
ARM_FIELD = {r: SEP_CPU_CTRL.field_mask(r, "reserved") for r in ARM_REGS}

_SCR = RegBlock("SEP_SCRATCH_COLD")
SCRATCH0 = sym("SEP_SCRATCH_COLD_REG_MAP_BASE_ADDR")
SCRATCH_FIELD = _SCR.field_mask("SCRATCH_0_", "data") & 0xFFFF_FFFF
POOL_STATUS = sym("ENTROPY_POOL_STATUS_REG_ADDR")
_POOL = RegBlock("SEP_ENTROPY_POOL")
POOL_LEVEL_MASK = _POOL.field_mask("STATUS", "fifo_level")
POOL_LEVEL_LSB = _POOL.field_lsb("STATUS", "fifo_level")

SMU_BASE = SEP_CPU_CTRL.reset("SMU_GLOBAL_BASE_ADDR")
SMU_WORD = SMU_BASE + 0x0002_0000  # outbound filter leg and DMA source
ALIAS_SRC_PAGE = SMU_BASE + 0x0004_0000  # alias region (one page)
ALIAS_OFFSET = 1 << 32
ALIAS_ACCESS = ALIAS_SRC_PAGE + 0x100
ALIAS_TARGET = ALIAS_ACCESS + ALIAS_OFFSET
ALIAS_REGION = 0
OUT_PAIR_SMU = (4, 5)
OUT_PAIR_ALIAS = (6, 7)
_AM = LOCAL_MASTER_ALIAS_REMAP_CTRL_0
ALIAS_OFFSET_FIELD = _AM.field_mask("REGION_REGION_ATTRS", "offset")
ALIAS_VALID_FIELD = _AM.field_mask("REGION_REGION_ATTRS", "valid")
SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
DMA_DST = SRAM_BASE + 0x0003_0000
ASID_RESET = _D.reset32("ADDR_SPACE_ID")
IN_ENTRY = {"mbox0": 0, "scratch": 1, "to_int": 2}

BLOCKS = (
    "sys_in",
    "mailbox_inbound",
    "mailbox_outbound",
    "entropy_read",
    "entropy_write",
    "filter_out",
    "alias_remap",
    "dma",
)
HOLD = 400  # clocks a response is held
VALID_BOUND = 2_000  # clocks to wait for the held response VALID
REQ_BOUND = 2_000  # clocks to wait for the request at the outbound port
DURING_BOUND = 300  # clocks the during-hold read may take
RELEASE_BOUND = 2_000  # clocks to wait for the response after release
QUIET = 64
DONE_POLL = 400


class _Cfg:
    def __init__(self, seed: int) -> None:
        rng = SepSeededRng(seed)
        self.seed = seed
        self.arm_order = list(ARM_REGS)
        rng.shuffle(self.arm_order)
        self.block_order = list(BLOCKS)
        rng.shuffle(self.block_order)

    def draw_lines(self) -> list[str]:
        return [
            "arm_order=" + ",".join(self.arm_order),
            "block_order=" + ",".join(self.block_order),
        ]


class _AliasReg(SepAxiRegDriver):
    _DRIVER_TAG = "ALIASREG"

    async def program(self) -> None:
        base = ALIAS_BASE + ALIAS_REGION * (
            sym("LOCAL_MASTER_ALIAS_REMAP_CTRL_1__REG_MAP_BASE_ADDR")
            - sym("LOCAL_MASTER_ALIAS_REMAP_CTRL_0__REG_MAP_BASE_ADDR")
        )
        attrs = (ALIAS_OFFSET & ALIAS_OFFSET_FIELD) | ALIAS_VALID_FIELD
        for off, v in (
            (ALIAS_START, ALIAS_SRC_PAGE),
            (ALIAS_END, ALIAS_SRC_PAGE + 0x1000),
            (ALIAS_ATTRS, attrs),
        ):
            await self._wr(base + off, v & 0xFFFF_FFFF)
            await self._wr(base + off + 4, v >> 32)
        got = await self._rd(base + ALIAS_ATTRS) | (await self._rd(base + ALIAS_ATTRS + 4) << 32)
        fc = field_compare(got, attrs, ALIAS_OFFSET_FIELD | ALIAS_VALID_FIELD)
        if not fc.ok:
            raise AssertionError(f"ALIAS-READBACK FAIL: region={ALIAS_REGION} {fc.fields()}")
        self.log.info("ALIAS-READBACK LOG: region=%d %s", ALIAS_REGION, fc.fields())


@pyuvm.test()
class sep_cpu_ctrl_timeout_inert_rand_test(sep_base_test):
    """Timeout registers hold a written 1; real stalls of every block path raise nothing."""

    required_evidence = ("CHK-ARMED", "CHK-STALL-REAL", "CHK-TO-INERT")

    # ---- log helpers -----------------------------------------------------------
    def _pass(self, chk: str, line: str) -> None:
        self.logger.info("%s PASS seed=%d %s", chk, self.c.seed, line)
        self.n_checks += 1
        self.counts[chk] = self.counts.get(chk, 0) + 1

    def _fail(self, chk: str, line: str) -> None:
        msg = f"{chk} FAIL seed={self.c.seed} {line}"
        self.logger.error(msg)
        raise AssertionError(msg)

    def _ctl_fail(self, name: str, line: str) -> None:
        msg = f"{name} FAIL seed={self.c.seed} {line}"
        self.logger.error(msg)
        raise AssertionError(msg)

    # ---- accesses ----------------------------------------------------------------
    def _seq(self, op: SepAxiOp, addr: int, data: int = 0, *, size: int = 2, ext: bool = False):
        nbytes = 1 << size
        kw = {"op": op, "addr": addr, "length": nbytes, "size": size}
        if op is SepAxiOp.READ:
            kw["allow_ungraded_read_resp"] = True
        else:
            kw["wdata"] = data & ((1 << (8 * nbytes)) - 1)
            kw["allow_unverified_write_resp"] = True
        if ext:
            kw["prot"] = 0
            kw["user"] = 0
        return SepAxiAccessSeq("to_acc", **kw)

    async def _run(self, seq, ext: bool):
        if ext:
            await self.start_ext_seq(seq)
        else:
            await self.start_seq(seq)
        return seq

    async def _lsu_rd(self, addr: int) -> int:
        s = await self._run(self._seq(SepAxiOp.READ, addr), False)
        if s.resp_code != RESP_OKAY:
            raise AssertionError(f"CPU-LSU read 0x{addr:08x} answered {s.resp_code}")
        return s.rdata & 0xFFFF_FFFF

    async def _lsu_wr(self, addr: int, v: int) -> None:
        s = await self._run(self._seq(SepAxiOp.WRITE, addr, v), False)
        if s.resp_code != RESP_OKAY:
            raise AssertionError(f"CPU-LSU write 0x{addr:08x} answered {s.resp_code}")

    async def _ext_acc(self, op: SepAxiOp, addr: int, v: int = 0) -> tuple[int, int]:
        s = await self._run(self._seq(op, addr, v, ext=True), True)
        return s.resp_code, s.rdata & 0xFFFF_FFFF

    async def _vec(self) -> int:
        await RisingEdge(cocotb.top.clk_i)
        await ReadOnly()
        v = self.rd_known(cocotb.top.sep_internal_interrupts_probe_o, VEC_GRADED)
        await NextTimeStep()
        return v

    async def _vec_masked(self) -> int:
        return (await self._vec()) & VEC_GRADED

    # ---- set-up --------------------------------------------------------------------
    async def _program_inbound(self) -> None:
        mb = port_base(0, "in")
        for key, lo, hi in (
            ("mbox0", mb, mb + 0x7FF),
            ("scratch", SCRATCH0, SCRATCH0 + 7),
            ("to_int", TO_INT, TO_INT + 7),
        ):
            await self.ibank.program(
                IN_ENTRY[key],
                FilterEntry(
                    start=lo,
                    end=hi,
                    enabled=True,
                    read_allowed=True,
                    write_allowed=True,
                    allow_ns=False,
                    src_id=0,
                ),
            )

    async def _program_outbound(self) -> None:
        for pair, word in ((OUT_PAIR_SMU, SMU_WORD), (OUT_PAIR_ALIAS, ALIAS_TARGET)):
            for idx, ns in zip(pair, (False, True)):
                await self.obank.program(
                    idx,
                    FilterEntry(
                        start=word,
                        end=word + 7,
                        enabled=True,
                        read_allowed=True,
                        write_allowed=True,
                        allow_ns=ns,
                        src_id=0,
                    ),
                )
        await _AliasReg(self).program()
        await self.dma.program_range(0x0, 0xFFFF_FFFF, valid=True)
        await self.dma.wr(_D.addr("ADDR_SPACE_ID"), ASID_RESET)

    async def _reset_reads(self) -> None:
        vals = {}
        for r in ("TIMEOUT_INTERRUPT",) + ARM_REGS:
            vals[r] = await self._lsu_rd(SEP_CPU_CTRL.addr(r))
        scr = await self._lsu_rd(SCRATCH0)
        bad = [r for r, v in vals.items() if v & SEP_CPU_CTRL.field_mask(r, "reserved")]
        if scr & SCRATCH_FIELD:
            bad.append("SCRATCH0")
        line = f"reset_regs={len(vals)} base=0x0 scratch0=0x{scr:x} " + " ".join(
            f"{r}=0x{v:x}" for r, v in vals.items()
        )
        if bad:
            self._ctl_fail("CTL-ARMED", line + f" bad={','.join(bad)}")
        self.logger.info("CTL-ARMED LOG seed=%d %s", self.c.seed, line)
        self.reset_vals = vals

    async def _arm(self) -> None:
        for r in self.c.arm_order:
            await self._lsu_wr(SEP_CPU_CTRL.addr(r), 0x1)
        got = {}
        for r in self.c.arm_order:
            got[r] = await self._lsu_rd(SEP_CPU_CTRL.addr(r))
        fcs = {r: field_compare(got[r], 1, ARM_FIELD[r]) for r in ARM_REGS}
        new_ok = all(fcs[r].ok for r in COUNTS_NEW)
        base_ok = all(not self.reset_vals[r] & ARM_FIELD[r] for r in COUNTS_NEW)
        line = f"regs={len(COUNTS_NEW)} base=0x0 read=0x1 " + " ".join(
            f"{r}[{fcs[r].fields()}]" for r in COUNTS_NEW
        )
        if not new_ok or not base_ok:
            self._fail("CHK-ARMED", line)
        self._pass("CHK-ARMED", line)
        ctl = f"reset_regs=10 base=0x0 armed_regs={len(ARM_OPEN)} armed=0x1 " + " ".join(
            f"{r}=0x{got[r] & ARM_FIELD[r]:x}" for r in ARM_OPEN
        )
        if not all(fcs[r].ok for r in ARM_OPEN):
            self._ctl_fail("CTL-ARMED", ctl)
        self.logger.info("CTL-ARMED LOG seed=%d %s", self.c.seed, ctl)

    # ---- one stall ----------------------------------------------------------------------
    def _target(self, block: str) -> tuple[int, bool, int, int]:
        """(address, held on the SMN master, AxSIZE, expected write response)."""
        if block == "sys_in":
            return SCRATCH0, True, 2, RESP_OKAY
        if block == "mailbox_inbound":
            return port_base(0, "in") + self.wirqt_off, True, 2, RESP_OKAY
        if block == "mailbox_outbound":
            return port_base(0, "out") + self.wirqt_off, False, 2, RESP_OKAY
        if block in ("entropy_read", "entropy_write"):
            return POOL_STATUS, False, 3, RESP_SLVERR
        if block == "filter_out":
            return SMU_WORD, False, 2, RESP_OKAY
        if block == "alias_remap":
            return ALIAS_ACCESS, False, 2, RESP_OKAY
        raise KeyError(block)

    async def _during_read(self, ext: bool):
        """TIMEOUT_INTERRUPT read from the master that does not hold; (task, seq)."""
        seq = self._seq(SepAxiOp.READ, TO_INT, ext=ext)
        return cocotb.start_soon(self._run(seq, ext)), seq

    async def _wait_task(self, task, bound: int) -> bool:
        for _ in range(bound):
            if task.done():
                return True
            await RisingEdge(cocotb.top.clk_i)
        return task.done()

    async def _after_release(
        self,
        block: str,
        d: str,
        stalled,
        during_ok: bool,
        during_v,
        vec_hold: int,
        resp_txt: str,
        resp_ok: bool,
    ) -> None:
        await ClockCycles(cocotb.top.clk_i, QUIET)
        to_after = await self._lsu_rd(TO_INT)
        vec_after = await self._vec_masked()
        fcs = [field_compare(to_after, 0, TO_INT_FIELD)]
        if during_ok:
            fcs.append(field_compare(during_v, 0, TO_INT_FIELD))
        line = (
            f"block={block} dir={d} timeout_int=0x{to_after & TO_INT_FIELD:x} "
            f"during_hold={'0x%x' % (during_v & TO_INT_FIELD) if during_ok else 'not_sampled'} "
            f"vec={'baseline' if vec_hold == self.base and vec_after == self.base else 'changed'} "
            f"vec_hold=0x{vec_hold:011x} vec_after=0x{vec_after:011x} "
            f"vec_base=0x{self.base:011x} resp={resp_txt}"
        )
        if (
            not all(f.ok for f in fcs)
            or vec_hold != self.base
            or vec_after != self.base
            or not resp_ok
        ):
            self._fail("CHK-TO-INERT", line)
        self._pass("CHK-TO-INERT", line)

    async def _stall_master(self, block: str, write: bool) -> None:
        """A stall held by the master READY (system input, mailboxes, entropy pool)."""
        addr, ext, size, wresp = self._target(block)
        d = "write" if write else "read"
        ch = "b" if write else "r"
        mon = self.mon_m if ext else self.mon_s
        hold = self.hold_m if ext else self.hold_s
        port = "xm" if ext else "lsu"
        seq = self._seq(SepAxiOp.WRITE if write else SepAxiOp.READ, addr, 0, size=size, ext=ext)
        hold.hold(ch)
        await RisingEdge(cocotb.top.clk_i)
        mark = mon.mark()
        w0 = mon.waiting_clocks(ch)
        task = cocotb.start_soon(self._run(seq, ext))
        try:
            await mon.wait_valid_waiting(ch, VALID_BOUND)
        except AssertionError as exc:
            hold.release_all()
            self._fail("CHK-STALL-REAL", f"block={block} dir={d} port={port} no held VALID: {exc}")
        dtask, dseq = await self._during_read(not ext)
        await ClockCycles(cocotb.top.clk_i, HOLD)
        valid_end = int(mon.valid_waiting(ch))
        during_ok = dtask.done()
        if not during_ok:
            self.logger.info(
                "OBS-TO-INERT LOG seed=%d block=%s dir=%s sample=during_hold status=not_sampled",
                self.c.seed,
                block,
                d,
            )
        vec_hold = await self._vec_masked()
        held_clocks = mon.waiting_clocks(ch) - w0
        during_hold = mon.count(mark, ch)
        hold.release(ch)
        if not await self._wait_task(task, RELEASE_BOUND):
            self._fail("CHK-STALL-REAL", f"block={block} dir={d} no response after release")
        if not await self._wait_task(dtask, RELEASE_BOUND):
            self._fail("CHK-TO-INERT", f"block={block} dir={d} TIMEOUT_INTERRUPT read hung")
        if not during_ok:
            self.logger.info(
                "OBS-TO-INERT LOG seed=%d block=%s dir=%s sample=after_release_late value=0x%x "
                "resp=%s",
                self.c.seed,
                block,
                d,
                dseq.rdata,
                RESP_NAME.get(dseq.resp_code),
            )
        after = mon.count(mark, ch)
        line = (
            f"block={block} dir={d} port={port} valid_during_hold={valid_end} "
            f"responses_during_hold={during_hold} responses_after_release={after} "
            f"held_clocks={held_clocks} hold={HOLD}"
        )
        if not valid_end or during_hold != 0 or after != 1 or held_clocks < HOLD:
            self._fail("CHK-STALL-REAL", line)
        self._pass("CHK-STALL-REAL", line)
        if block == "entropy_read":
            self.logger.info(
                "OBS-ENTROPY-STATUS LOG seed=%d fifo_level=%d status=0x%x",
                self.c.seed,
                (seq.rdata & POOL_LEVEL_MASK) >> POOL_LEVEL_LSB,
                seq.rdata,
            )
        if write:
            want = wresp
            resp_ok = seq.resp_code == want
            resp_txt = RESP_NAME.get(seq.resp_code, str(seq.resp_code))
        elif block == "entropy_read":
            resp_ok = seq.resp_code == RESP_OKAY
            resp_txt = RESP_NAME.get(seq.resp_code, str(seq.resp_code))
        else:
            resp_ok = seq.resp_code == RESP_OKAY and (seq.rdata & 0xFFFF_FFFF) == 0
            resp_txt = f"{RESP_NAME.get(seq.resp_code, seq.resp_code)}/data=0x{seq.rdata:x}"
        dv = dseq.rdata if during_ok and dseq.resp_code == RESP_OKAY else None
        await self._after_release(
            block, d, seq, dv is not None, dv or 0, vec_hold, resp_txt, resp_ok
        )

    async def _stall_responder(self, block: str, write: bool) -> None:
        """A stall held by the outbound responder (outbound filter, alias remap)."""
        dut = cocotb.top
        addr, _, size, _ = self._target(block)
        d = "write" if write else "read"
        ch = "b" if write else "r"
        seq = self._seq(SepAxiOp.WRITE if write else SepAxiOp.READ, addr, 0, size=size)
        m_req = self.out.mark()
        mark = self.mon_s.mark()
        dut.smn_outbound_resp_hold_i.value = 1
        task = cocotb.start_soon(self._run(seq, False))
        req = 0
        for _ in range(REQ_BOUND):
            req = self.out.count(m_req, "aw" if write else "ar")
            if req:
                break
            await RisingEdge(dut.clk_i)
        if not req:
            dut.smn_outbound_resp_hold_i.value = 0
            self._fail("CHK-STALL-REAL", f"block={block} dir={d} req_at_port=0")
        dtask, dseq = await self._during_read(True)
        await ClockCycles(dut.clk_i, HOLD)
        during_ok = dtask.done()
        if not during_ok:
            self.logger.info(
                "OBS-TO-INERT LOG seed=%d block=%s dir=%s sample=during_hold status=not_sampled",
                self.c.seed,
                block,
                d,
            )
        vec_hold = await self._vec_masked()
        during_hold = self.mon_s.count(mark, ch)
        req = self.out.count(m_req, "aw" if write else "ar")
        dut.smn_outbound_resp_hold_i.value = 0
        if not await self._wait_task(task, RELEASE_BOUND):
            self._fail("CHK-STALL-REAL", f"block={block} dir={d} no response after release")
        if not await self._wait_task(dtask, RELEASE_BOUND):
            self._fail("CHK-TO-INERT", f"block={block} dir={d} TIMEOUT_INTERRUPT read hung")
        after = self.mon_s.count(mark, ch)
        line = (
            f"block={block} dir={d} port=lsu req_at_port={req} responses_during_hold={during_hold} "
            f"responses_after_release={after} hold={HOLD}"
        )
        if req != 1 or during_hold != 0 or after != 1:
            self._fail("CHK-STALL-REAL", line)
        self._pass("CHK-STALL-REAL", line)
        if write:
            resp_ok = seq.resp_code == RESP_OKAY
            resp_txt = RESP_NAME.get(seq.resp_code, str(seq.resp_code))
        else:
            resp_ok = seq.resp_code == RESP_OKAY and (seq.rdata & 0xFFFF_FFFF) == 0
            resp_txt = f"{RESP_NAME.get(seq.resp_code, seq.resp_code)}/data=0x{seq.rdata:x}"
        dv = dseq.rdata if during_ok and dseq.resp_code == RESP_OKAY else None
        await self._after_release(
            block, d, seq, dv is not None, dv or 0, vec_hold, resp_txt, resp_ok
        )

    async def _stall_dma(self) -> None:
        dut = cocotb.top
        await self.dma.wr(_D.addr("STATUS"), ST_DONE | ST_ERROR)
        await self.dma.program_transfer(src=SMU_WORD, dst=DMA_DST, total=4, chunk=4)
        m_req = self.out.mark()
        dut.smn_outbound_resp_hold_i.value = 1
        await self.dma.go()
        req = 0
        for _ in range(REQ_BOUND):
            req = self.out.count(m_req, "ar")
            if req:
                break
            await RisingEdge(dut.clk_i)
        if not req:
            dut.smn_outbound_resp_hold_i.value = 0
            self._fail("CHK-STALL-REAL", "block=dma dir=read req_at_port=0")
        dtask, dseq = await self._during_read(True)
        st_hold = await self.dma.read_status()
        await ClockCycles(dut.clk_i, HOLD)
        during_ok = dtask.done()
        if not during_ok:
            self.logger.info(
                "OBS-TO-INERT LOG seed=%d block=dma dir=read sample=during_hold status=not_sampled",
                self.c.seed,
            )
        st_hold2 = await self.dma.read_status()
        vec_hold = await self._vec_masked()
        req = self.out.count(m_req, "ar")
        dut.smn_outbound_resp_hold_i.value = 0
        st = None
        for _ in range(DONE_POLL):
            st = await self.dma.read_status()
            if st.done or st.error:
                break
        if not await self._wait_task(dtask, RELEASE_BOUND):
            self._fail("CHK-TO-INERT", "block=dma dir=read TIMEOUT_INTERRUPT read hung")
        busy = int(bool(st_hold.raw & ST_BUSY) and bool(st_hold2.raw & ST_BUSY))
        line = (
            f"block=dma dir=read req_at_port={req} busy_during_hold={busy} "
            f"done_after_release={st.done} status_hold=0x{st_hold.raw:x}/0x{st_hold2.raw:x} "
            f"hold={HOLD}"
        )
        if req != 1 or not busy or not st.done:
            self._fail("CHK-STALL-REAL", line)
        self._pass("CHK-STALL-REAL", line)
        resp_ok = bool(st.done) and not st.error
        dv = dseq.rdata if during_ok and dseq.resp_code == RESP_OKAY else None
        await self._after_release(
            "dma",
            "read",
            None,
            dv is not None,
            dv or 0,
            vec_hold,
            f"done/done={st.done}/error={st.error}",
            resp_ok,
        )
        await self.dma.wr(_D.addr("STATUS"), ST_DONE)

    async def _vec_live(self) -> None:
        b = 0
        base0 = (self.base >> b) & 1
        for reg, v in (("IRQEN", IRQ_WTIRQ),):
            resp, _ = await self._ext_acc(SepAxiOp.WRITE, port_base(0, "in") + self.reg_off[reg], v)
            if resp != RESP_OKAY:
                self._ctl_fail("CTL-VEC-LIVE", f"IRQEN write answered {RESP_NAME.get(resp)}")
        s = self._seq(
            SepAxiOp.WRITE,
            port_base(0, "in") + self.reg_off["WRITE_DATA"],
            0x1234_5678_9ABC_DEF1,
            size=3,
            ext=True,
        )
        await self._run(s, True)
        rise = 0
        for _ in range(400):
            if (await self._vec()) & 1:
                rise = 1
                break
        s = self._seq(SepAxiOp.READ, port_base(0, "out") + self.reg_off["READ_DATA"], size=3)
        await self._run(s, False)
        await self._ext_acc(SepAxiOp.WRITE, port_base(0, "in") + self.reg_off["IRQS"], IRQ_WTIRQ)
        await self._ext_acc(SepAxiOp.WRITE, port_base(0, "in") + self.reg_off["IRQEN"], 0)
        fall = 0
        for _ in range(400):
            if not (await self._vec()) & 1:
                fall = 1
                break
        line = f"bit0_base={base0} bit0_after_push={rise} bit0_after_release={0 if fall else 1}"
        if base0 != 0 or not rise or not fall:
            self._ctl_fail("CTL-VEC-LIVE", line)
        self.logger.info("CTL-VEC-LIVE PASS seed=%d %s", self.c.seed, line)

    # ---- scenario ------------------------------------------------------------------------
    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.c = c = _Cfg(seed)
        self.n_checks = 0
        self.counts: dict[str, int] = {}
        self.reg_off = REG_OFFSETS
        self.wirqt_off = REG_OFFSETS["WIRQT"]
        self.logger.info("SEED seed=%d", seed)
        for d in c.draw_lines():
            self.logger.info("DRAW %s", d)
        await self.bring_up_no_cpu()
        self.suppress_host_axi_transaction_info()
        await self.stop_fifo_drain()
        await SepMbox(self).ungate_clock()
        self.ibank = SepFilterBank(self, "in")
        self.obank = SepFilterBank(self, "out")
        self.dma = SepDmaOps(self)
        self.mon_s = SepAxiChanMon("s_axi").start()
        self.mon_m = SepAxiChanMon("m_axi").start()
        self.hold_s = SepAxiReadyHold(self, "s_axi")
        self.hold_m = SepAxiReadyHold(self, "m_axi")
        self.out = SepFabricTap("PR-OUT").start()
        await self._program_inbound()
        await self._program_outbound()
        await self._reset_reads()
        await ClockCycles(cocotb.top.clk_i, QUIET)
        raw = await self._vec()
        self.base = raw & VEC_GRADED
        self.logger.info("%s seed=%d baseline", idle_unstated_line(vec=raw), seed)
        self.logger.info(
            "VEC-BASELINE LOG seed=%d vec=0x%011x masked=0x%011x", seed, raw, self.base
        )

        open_graded_window(TEST, self.logger)
        await self._arm()
        for blk in c.block_order:
            if blk in ("sys_in", "mailbox_inbound", "mailbox_outbound"):
                await self._stall_master(blk, False)
                await self._stall_master(blk, True)
            elif blk == "entropy_read":
                await self._stall_master(blk, False)
            elif blk == "entropy_write":
                await self._stall_master(blk, True)
            elif blk in ("filter_out", "alias_remap"):
                await self._stall_responder(blk, False)
                await self._stall_responder(blk, True)
            else:
                await self._stall_dma()
        close_graded_window(self.logger)
        await self._vec_live()
        await self.mon_s.stop()
        await self.mon_m.stop()
        await self.out.stop()
        expect = {"CHK-ARMED": 1, "CHK-STALL-REAL": 13, "CHK-TO-INERT": 13}
        if self.counts != expect:
            raise AssertionError(f"CHK-COUNT FAIL seed={seed} counts={self.counts} expect={expect}")
        self.logger.info(
            "RESULT %s seed=%d PASS checks=%d counts=%s", TEST, seed, self.n_checks, self.counts
        )
