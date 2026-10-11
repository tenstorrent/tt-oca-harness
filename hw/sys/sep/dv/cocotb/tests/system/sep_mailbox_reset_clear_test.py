# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP reset in the middle of a mailbox push, pop or IRQS write clears every mailbox.

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense``. One reset
round per leaf. VCS grades the X-free part of CHK-RESET-STATE; Verilator
(2-state) grades the values and logs ``x_free=na``. The reset is a full SEP
reset on ``rst_ni``; the leaf drives no CPU-only reset and no JTAG reset.

Contract (``hw/ip/axi_lite_mailbox_unit/doc/architecture.adoc``, "Clock and
Reset"; ``hw/sys/sep/doc/mailbox.adoc``, "Mailboxes";
``hw/ip/axi_filter/regs/gen/adoc/filter_ctrl.adoc``, ``FILTER_CONFIG``;
``hw/ip/axi_lite_mailbox_unit/doc/interface.adoc``, "Sending and Receiving"):
SEP reset empties every FIFO, clears thresholds, error flags, interrupt status
and enables, drops every mailbox line, and restores the ISS source ID of an
inbound filter entry to its reset value 0. The mailbox works after the reset.
The reset source of ``locked`` and ``entry_enabled`` is not stated: both are
logged (``OBS-FILTER-RESET``), never graded.

Flow: thresholds and enables on all 16 ports; one locked ISS entry (``src_id``
5) over the inbound half of the filter mailbox with one admitted external
write; error injection 1 (empty inbound read, SLVERR) and 2 (full outbound
write, SLVERR); FIFO fills; a pre-state read-back. Then the drawn operation
(push, pop or IRQS write) starts on the CPU-LSU master with the response ready
held low, and ``rst_ni`` falls at the drawn offset after the request
handshake. The interrupted access is abandoned by the master (its AXI agent
resets with ``rst_ni``) and its response is not graded. After the bring-up
the leaf samples the lines, reads all 16 apertures and the filter entry, and
reuses one mailbox.

The offset is the number of clocks between the clock of the request handshake
(the later of AW and W for a write) and the first clock sampled with
``rst_ni`` low, minus one; 0 is the earliest assertion after the handshake.

Randomization (``SepSeededRng`` from the run seed): the thresholds (1 to 6),
the enables (1 to 7; the two error ports include ``eirq``), the FIFO counts
(1 to 8, FIFO A above the outbound ``WIRQT``), the filter mailbox and the two
error mailboxes (all different), the reset cell (operation x offset class, one
of nine), the mailbox, port and offset of the operation, the data words and
the reuse mailbox.

Checkers:
  CTL-OP-INFLIGHT   request handshake before the ``rst_ni`` fall, no B or R
                    handshake after it; else ``CTRL-MISSING``.
  CHK-PRE-NONZERO   pre-state differs from the reset state (per mailbox).
  CHK-RESET-STATE   16 apertures read the reset values (VCS: no X bit).
  CHK-RESET-LINES   probe bits [7:0] and the SMC port read 0x00.
  CHK-RESET-FILTER  the ISS ``src_id`` reads 0 after the reset.
  CHK-REUSE         one push answers OKAY and the pop returns the word.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, NextTimeStep, ReadOnly, RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_axi_chan_mon import SepAxiChanMon, SepAxiReadyHold
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_field_compare import field_compare
from env.sep_filter_model import FilterEntry
from env.sep_mbox_golden import AXIL_MAILBOX_OUTBOUND_0, IRQ_EIRQ, IRQ_WTIRQ, ST_EMPTY
from env.sep_mbox_pair_model import MAILBOX_DEPTH, MboxSystem
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_fabric_csr_bank_seq import F_ALLOW_NS, F_ENTRY_ENABLED, F_SRC_ID_LSB
from seq_lib.sep_fabric_filter_bank_seq import SRC_ID_MASK, SepFilterBank
from seq_lib.sep_inbound_filter_rule_seq import FILTER_LOCKED_HI_BIT, SepInboundFilter
from seq_lib.sep_mailbox_iface_seq import SepMbox
from seq_lib.sep_mbox_port_ops import (
    MAILBOX_COUNT,
    REG_OFFSETS,
    RESP_OKAY,
    RESP_SLVERR,
    SepMboxPortOps,
    port_base,
    resp_name,
)

TEST = "sep_mailbox_reset_clear_test"
PORTS = ("out", "in")
OPS = ("push", "pop", "irqs")
CLASSES = ((0, 7), (8, 31), (32, 64))
# rst_ni low time of the step-1 bring-up (sep_base_test.release_no_cpu_reset).
RESET_HOLD = 20
QUIET = 32
HS_BOUND = 2_000  # clocks to wait for the request handshake
ABANDON_NS = 20_000  # VIP timeout of the interrupted access
FILTER_SRC = 5
_M = AXIL_MAILBOX_OUTBOUND_0
REGS_READ = ("STATUS", "IRQS", "IRQEN", "WIRQT", "RIRQT", "IRQP", "ERROR_FLAGS")
MASK = {r: _M.mask32(r) for r in REGS_READ}
RESET = {r: _M.reset32(r) for r in REGS_READ}
SRC_ID_FIELD = SRC_ID_MASK << F_SRC_ID_LSB
FILTER_ENTRY = 0


class _Cfg:
    """Seed-drawn plan of the leaf."""

    def __init__(self, seed: int) -> None:
        rng = SepSeededRng(seed)
        self.seed = seed
        self.filt_m, self.err1_m, self.err2_m = rng.sample(range(MAILBOX_COUNT), 3)
        self.wirqt = {(m, p): rng.randrange(1, 7) for m in range(MAILBOX_COUNT) for p in PORTS}
        self.rirqt = {(m, p): rng.randrange(1, 7) for m in range(MAILBOX_COUNT) for p in PORTS}
        self.irqen = {}
        for m in range(MAILBOX_COUNT):
            for p in PORTS:
                err_port = (m, p) in ((self.err1_m, "in"), (self.err2_m, "out"))
                self.irqen[(m, p)] = rng.randrange(4, 8) if err_port else rng.randrange(1, 8)
        self.cnt_a = {}
        self.cnt_b = {}
        for m in range(MAILBOX_COUNT):
            w = self.wirqt[(m, "out")]
            self.cnt_a[m] = MAILBOX_DEPTH if m == self.err2_m else rng.randrange(w + 1, 9)
            self.cnt_b[m] = rng.randrange(1, 9)
        self.words = {m: [rng.getrandbits(64) for _ in range(16)] for m in range(MAILBOX_COUNT)}
        self.filt_word = rng.getrandbits(64)
        # The reset cell.
        cell = rng.randrange(len(OPS) * len(CLASSES))
        self.op = OPS[cell // len(CLASSES)]
        self.cls = cell % len(CLASSES)
        lo, hi = CLASSES[self.cls]
        self.offset = rng.randrange(lo, hi + 1)
        cand = []
        for m in range(MAILBOX_COUNT):
            for p in PORTS:
                wocc = self.cnt_a[m] if p == "out" else self.cnt_b[m]
                if self.op == "push" and wocc >= MAILBOX_DEPTH:
                    continue
                cand.append((m, p))
        self.op_m, self.op_port = rng.choice(cand)
        self.op_word = rng.getrandbits(64)
        self.op_irqs = rng.randrange(1, 8)
        self.reuse_m = rng.randrange(MAILBOX_COUNT)
        self.reuse_word = rng.getrandbits(64)

    @property
    def cls_name(self) -> str:
        lo, hi = CLASSES[self.cls]
        return f"{lo}-{hi}"

    def draw_lines(self) -> list[str]:
        out = [
            f"filter_mbox={self.filt_m} err1_mbox={self.err1_m} err2_mbox={self.err2_m}",
            f"reset_cell op={self.op} offset_class={self.cls_name} offset={self.offset} "
            f"mbox={self.op_m} port={self.op_port} word=0x{self.op_word:016x} "
            f"irqs_value=0x{self.op_irqs:x}",
            f"reuse_mbox={self.reuse_m} reuse_word=0x{self.reuse_word:016x} "
            f"filter_word=0x{self.filt_word:016x}",
        ]
        for m in range(MAILBOX_COUNT):
            out.append(
                f"mbox={m} cnt_a={self.cnt_a[m]} cnt_b={self.cnt_b[m]} "
                + " ".join(
                    f"{p}:wirqt={self.wirqt[(m, p)]},rirqt={self.rirqt[(m, p)]},"
                    f"irqen=0x{self.irqen[(m, p)]:x}"
                    for p in PORTS
                )
            )
        return out


@pyuvm.test()
class sep_mailbox_reset_clear_test(sep_base_test):
    """Reset mid-operation: all apertures, lines and the ISS source ID clear; reuse works."""

    required_evidence = (
        "CHK-PRE-NONZERO",
        "CHK-RESET-STATE",
        "CHK-RESET-LINES",
        "CHK-RESET-FILTER",
        "CHK-REUSE",
    )

    # ---- log helpers -----------------------------------------------------------
    def _pass(self, chk: str, line: str) -> None:
        self.logger.info("%s PASS seed=%d %s", chk, self.c.seed, line)
        self.n_checks += 1

    def _fail(self, chk: str, line: str) -> None:
        msg = f"{chk} FAIL seed={self.c.seed} {line}"
        self.logger.error(msg)
        raise AssertionError(msg)

    def _ctrl_missing(self, line: str) -> None:
        msg = f"CTRL-MISSING seed={self.c.seed} {line}"
        self.logger.error(msg)
        raise AssertionError(msg)

    # ---- CPU-LSU accesses to any port --------------------------------------------
    def _addr(self, m: int, port: str, reg: str) -> int:
        return port_base(m, port) + REG_OFFSETS[reg]

    async def _lsu(self, op: SepAxiOp, addr: int, *, wdata: int = 0, size: int = 2):
        nbytes = 1 << size
        kw = {"op": op, "addr": addr, "length": nbytes, "size": size}
        if op is SepAxiOp.READ:
            kw["allow_ungraded_read_resp"] = True
        else:
            kw["wdata"] = wdata & ((1 << (8 * nbytes)) - 1)
            kw["allow_unverified_write_resp"] = True
        seq = SepAxiAccessSeq("rst_mbx", **kw)
        await self.start_seq(seq)
        if seq.timed_out:
            raise AssertionError(f"CPU-LSU access 0x{addr:08x} timed out")
        return seq.resp_code, seq.rdata & ((1 << (8 * nbytes)) - 1)

    async def _wr_ok(self, m: int, port: str, reg: str, v: int) -> None:
        resp, _ = await self._lsu(SepAxiOp.WRITE, self._addr(m, port, reg), wdata=v)
        if resp != RESP_OKAY:
            raise AssertionError(
                f"MBX-SETUP FAIL: mbox {m} {port} {reg}=0x{v:x} answered {resp_name(resp)}"
            )
        self.model[m].write_reg(port, reg, v)

    async def _rd(self, m: int, port: str, reg: str) -> tuple[int, int]:
        return await self._lsu(SepAxiOp.READ, self._addr(m, port, reg))

    async def _push(self, m: int, port: str, data: int) -> int:
        resp, _ = await self._lsu(
            SepAxiOp.WRITE, self._addr(m, port, "WRITE_DATA"), wdata=data, size=3
        )
        self.model[m].push(port, data)
        return resp

    async def _lines(self) -> tuple[int, int]:
        await RisingEdge(cocotb.top.clk_i)
        await ReadOnly()
        probe = self.rd_known(cocotb.top.sep_internal_interrupts_probe_o, 0xFF) & 0xFF
        smc = self.rd_known(cocotb.top.smc_mailbox_interrupt_o)
        await NextTimeStep()
        return probe, smc

    # ---- steps -----------------------------------------------------------------
    async def _setup(self) -> None:
        c = self.c
        for m in range(MAILBOX_COUNT):
            for p in PORTS:
                await self._wr_ok(m, p, "WIRQT", c.wirqt[(m, p)])
                await self._wr_ok(m, p, "RIRQT", c.rirqt[(m, p)])
                await self._wr_ok(m, p, "IRQEN", c.irqen[(m, p)])
        # Filter entry: src_id 5, allow_ns 0, over the inbound half of the filter mailbox.
        base = port_base(c.filt_m, "in")
        await self.bank.program(
            FILTER_ENTRY,
            FilterEntry(
                start=base,
                end=base + 0x7FF,
                enabled=True,
                read_allowed=True,
                write_allowed=True,
                allow_ns=False,
                src_id=FILTER_SRC,
            ),
        )
        ext = SepMboxPortOps(self, c.filt_m, in_prot1=0, in_user=FILTER_SRC)
        resp = await ext.push("in", c.filt_word)
        if resp != RESP_OKAY:
            self._ctrl_missing(
                f"filter mailbox {c.filt_m} admitted write answered {resp_name(resp)} (expect OKAY)"
            )
        self.model[c.filt_m].push("in", c.filt_word)
        self.pre_ext_resp = resp
        await self.infilt.lock_entry(FILTER_ENTRY)
        cfg_addr = self.bank.cfg_addr(FILTER_ENTRY)
        lo = await self.infilt.read_cpu(cfg_addr)
        hi = await self.infilt.read_cpu(cfg_addr + 4)
        self.pre_cfg = (hi << 32) | lo
        self.pre_src = (lo >> F_SRC_ID_LSB) & SRC_ID_MASK
        self.pre_locked = (hi >> FILTER_LOCKED_HI_BIT) & 1
        if self.pre_src != FILTER_SRC or self.pre_locked != 1:
            self._ctrl_missing(
                f"FILTER_CONFIG before reset 0x{self.pre_cfg:016x} src_id={self.pre_src} "
                f"locked={self.pre_locked} (expect src_id={FILTER_SRC} locked=1)"
            )
        # Error injection 1: empty inbound read of the first error mailbox.
        resp, _ = await self._lsu(SepAxiOp.READ, self._addr(c.err1_m, "in", "READ_DATA"), size=3)
        self.model[c.err1_m].pop("in")
        self.inj_rd = resp
        # Fill the FIFOs.
        for m in range(MAILBOX_COUNT):
            w = iter(c.words[m])
            for _ in range(c.cnt_a[m]):
                r = await self._push(m, "out", next(w))
                if r != RESP_OKAY:
                    raise AssertionError(f"MBX-SETUP FAIL: mbox {m} out fill {resp_name(r)}")
            n_b = c.cnt_b[m] - (1 if m == c.filt_m else 0)
            for _ in range(n_b):
                r = await self._push(m, "in", next(w))
                if r != RESP_OKAY:
                    raise AssertionError(f"MBX-SETUP FAIL: mbox {m} in fill {resp_name(r)}")
        # Error injection 2: full outbound write of the second error mailbox.
        self.inj_wr = await self._push(c.err2_m, "out", c.words[c.err2_m][15])

    async def _pre_state(self) -> None:
        c = self.c
        await ClockCycles(cocotb.top.clk_i, QUIET)
        probe, smc = await self._lines()
        self.pre_probe, self.pre_smc = probe, smc
        self.logger.info(
            "PRE-LINES LOG seed=%d probe=0x%02x smc=0x%02x model_in=0x%02x model_out_count=%d",
            c.seed,
            probe,
            smc,
            self.model.in_lines(),
            self.model.out_count(),
        )
        for m in range(MAILBOX_COUNT):
            vals = {}
            for p in PORTS:
                for reg in ("STATUS", "WIRQT", "RIRQT", "IRQEN", "IRQS"):
                    resp, v = await self._rd(m, p, reg)
                    if resp != RESP_OKAY:
                        raise AssertionError(f"MBX-SETUP FAIL: mbox {m} {p} {reg} read {resp}")
                    vals[(p, reg)] = v & MASK[reg]
            bad = []
            for p in PORTS:
                if vals[(p, "STATUS")] & ST_EMPTY:
                    bad.append(f"{p}.STATUS.empty=1")
                for reg in ("WIRQT", "RIRQT", "IRQEN"):
                    if vals[(p, reg)] == 0:
                        bad.append(f"{p}.{reg}=0")
            if not vals[("out", "IRQS")] & IRQ_WTIRQ:
                bad.append("out.IRQS.wtirq=0")
            if m == c.err1_m and not vals[("in", "IRQS")] & IRQ_EIRQ:
                bad.append("in.IRQS.eirq=0")
            if m == c.err2_m and not vals[("out", "IRQS")] & IRQ_EIRQ:
                bad.append("out.IRQS.eirq=0")
            if self.inj_rd != RESP_SLVERR or self.inj_wr != RESP_SLVERR:
                bad.append("injection_resp")
            if probe == 0 or smc == 0:
                bad.append("no_line_high")
            line = (
                f"mbox={m} status_out=0x{vals[('out', 'STATUS')]:x} "
                f"status_in=0x{vals[('in', 'STATUS')]:x} "
                f"wirqt={vals[('out', 'WIRQT')]}/{vals[('in', 'WIRQT')]} "
                f"rirqt={vals[('out', 'RIRQT')]}/{vals[('in', 'RIRQT')]} "
                f"irqen=0x{vals[('out', 'IRQEN')]:x}/0x{vals[('in', 'IRQEN')]:x} "
                f"irqs_out=0x{vals[('out', 'IRQS')]:x} irqs_in=0x{vals[('in', 'IRQS')]:x} "
                f"inj_rd={resp_name(self.inj_rd)} inj_wr={resp_name(self.inj_wr)} "
                f"lines_pre_probe=0x{probe:02x} lines_pre_smc=0x{smc:02x}"
                + (f" bad={','.join(bad)}" if bad else "")
            )
            if bad:
                self._fail("CHK-PRE-NONZERO", line)
            self._pass("CHK-PRE-NONZERO", line)

    async def _reset_in_flight(self) -> None:
        """Start the drawn operation with the response ready held, then pulse rst_ni."""
        c = self.c
        dut = cocotb.top
        await self.stop_fifo_drain()
        mon = SepAxiChanMon("s_axi").start()
        hold = SepAxiReadyHold(self, "s_axi")
        vip = self.env.axi_agent.driver.axi
        write = c.op in ("push", "irqs")
        resp_ch = "b" if write else "r"
        if c.op == "push":
            addr, size, payload = self._addr(c.op_m, c.op_port, "WRITE_DATA"), 3, c.op_word
        elif c.op == "pop":
            addr, size, payload = self._addr(c.op_m, c.op_port, "READ_DATA"), 3, 0
        else:
            addr, size, payload = self._addr(c.op_m, c.op_port, "IRQS"), 2, c.op_irqs
        nbytes = 1 << size
        hold.hold(resp_ch)
        await RisingEdge(dut.clk_i)
        mark = mon.mark()
        outcome: dict = {}

        async def _op() -> None:
            try:
                if write:
                    r = await vip.write_bytes_result(
                        addr,
                        payload.to_bytes(nbytes, "little"),
                        size=size,
                        check_response=False,
                        timeout_ns=ABANDON_NS,
                        allow_timeout=True,
                    )
                else:
                    r = await vip.read_bytes_result(
                        addr,
                        nbytes,
                        size=size,
                        check_response=False,
                        timeout_ns=ABANDON_NS,
                        allow_timeout=True,
                    )
                outcome["result"] = (getattr(r, "resp", None), getattr(r, "timed_out", None))
            except Exception as exc:  # the reset flushes the access
                outcome["result"] = ("abandoned", type(exc).__name__)

        task = cocotb.start_soon(_op())
        # Request handshake: the later of AW and W (write) or AR (read), seen on the
        # master port with VALID and READY high on one clock.
        seen = {"aw": False, "w": False, "ar": False}
        need = ("aw", "w") if write else ("ar",)
        for _ in range(HS_BOUND):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            for ch in need:
                v = getattr(dut, f"s_axi_{ch}valid").value
                r = getattr(dut, f"s_axi_{ch}ready").value
                if v.is_resolvable and r.is_resolvable and int(v) and int(r):
                    seen[ch] = True
            if all(seen[ch] for ch in need):
                break
        else:
            hold.release_all()
            self._ctrl_missing(
                f"CTL-OP-INFLIGHT op={c.op} mbox={c.op_m} port={c.op_port} req_hs=0 "
                f"(no request handshake in {HS_BOUND} clocks) seen={seen}"
            )
        pre_resp_valid = mon.waiting_clocks(resp_ch)

        async def _count_to_fall() -> int:
            n = 0
            while True:
                await RisingEdge(dut.clk_i)
                await ReadOnly()
                n += 1
                if self.rd(dut.rst_ni, allow_unknown=True) == 0:
                    return n

        fall_task = cocotb.start_soon(_count_to_fall())
        if c.offset:
            await ClockCycles(dut.clk_i, c.offset)
        resp_valid_seen = int(mon.waiting_clocks(resp_ch) > 0)
        resp_hs_before = mon.count(mark, resp_ch)
        rel = await self.pulse_rst_ni(hold_cycles=RESET_HOLD)
        fall_n = fall_task.result() if fall_task.done() else None
        if not fall_task.done():
            fall_task.kill()
        resp_hs_total = mon.count(mark, resp_ch)
        hold.release_all()
        await ClockCycles(dut.clk_i, 2)
        if not task.done():
            task.kill()
            outcome.setdefault("result", ("killed", None))
        if not write:
            self.env.axi_monitor.forget_pending_reads(0)
        await mon.stop()
        offset = None if fall_n is None else fall_n - 1
        self.cell_offset = offset
        self.logger.info(
            "OBS-OP-INFLIGHT LOG seed=%d op=%s resp_valid=%d valid_clocks_at_hs=%d result=%s "
            "release_clks=%d",
            c.seed,
            c.op,
            resp_valid_seen,
            pre_resp_valid,
            outcome.get("result"),
            rel["release_clks"],
        )
        lo, hi = CLASSES[c.cls]
        line = (
            f"op={c.op} mbox={c.op_m} port={c.op_port} req_hs=1 resp_hs={resp_hs_total} "
            f"resp_hs_before_fall={resp_hs_before} offset={offset} offset_class={c.cls_name} "
            f"drawn_offset={c.offset}"
        )
        if resp_hs_total or offset is None or not lo <= offset <= hi:
            self._ctrl_missing(f"CTL-OP-INFLIGHT {line}")
        self.logger.info("CTL-OP-INFLIGHT PASS seed=%d %s", c.seed, line)
        self.model.reset()

    async def _post(self) -> None:
        c = self.c
        sim = str(getattr(cocotb, "SIM_NAME", "") or "").lower()
        four_state = "verilator" not in sim
        await ClockCycles(cocotb.top.clk_i, QUIET)
        probe, smc = await self._lines()
        line = (
            f"probe=0x{probe:02x} smc=0x{smc:02x} pre_probe=0x{self.pre_probe:02x} "
            f"pre_smc=0x{self.pre_smc:02x}"
        )
        if probe != 0 or smc != 0 or self.pre_probe == 0 or self.pre_smc == 0:
            self._fail("CHK-RESET-LINES", line)
        self._pass("CHK-RESET-LINES", line)

        # Read all 16 apertures; keep every bit as sampled.
        rbeats: list = []
        dut = cocotb.top

        async def _rmon() -> None:
            while True:
                await RisingEdge(dut.clk_i)
                await ReadOnly()
                if dut.s_axi_rvalid.value == 1 and dut.s_axi_rready.value == 1:
                    rbeats.append(dut.s_axi_rdata.value)

        rtask = cocotb.start_soon(_rmon())
        bad = []
        n_status = n_zero = 0
        xs = 0
        for m in range(MAILBOX_COUNT):
            for p in PORTS:
                regs_ok = True
                for reg in REGS_READ:
                    addr = self._addr(m, p, reg)
                    n0 = len(rbeats)
                    resp, v = await self._rd(m, p, reg)
                    await ClockCycles(dut.clk_i, 1)
                    beat = rbeats[n0] if len(rbeats) > n0 else None
                    lane_ok = True
                    if beat is not None and four_state:
                        s = beat.binstr
                        lane = s[-64:][:32] if addr & 4 else s[-32:]
                        lane_ok = all(ch in "01" for ch in lane)
                    if not lane_ok:
                        xs += 1
                    exp = (
                        self.model[m].reg(p, reg)
                        if reg not in ("STATUS", "ERROR_FLAGS")
                        else (
                            self.model[m].status(p)
                            if reg == "STATUS"
                            else self.model[m].error_flags(p)
                        )
                    )
                    fc = field_compare(v, exp, MASK[reg])
                    if resp != RESP_OKAY or not fc.ok or not lane_ok:
                        regs_ok = False
                        bad.append(f"{m}.{p}.{reg}:resp={resp_name(resp)}[{fc.fields()}]")
                    elif reg == "STATUS":
                        n_status += 1
                if regs_ok:
                    n_zero += 1
        rtask.kill()
        x_free = ("1" if xs == 0 else "0") if four_state else "na"
        line = (
            f"op={c.op} offset={self.cell_offset} offset_class={c.cls_name} apertures=16 "
            f"status_empty={n_status} regs_zero={n_zero} x_free={x_free} "
            f"expect_status=0x{RESET['STATUS']:x} r_beats={len(rbeats)}"
            + (f" bad={';'.join(bad[:6])}" if bad else "")
        )
        if bad or n_status != 16 or n_zero != 16 or x_free == "0":
            self._fail("CHK-RESET-STATE", line)
        self._pass("CHK-RESET-STATE", line)

        # Filter entry after the reset.
        cfg_addr = self.bank.cfg_addr(FILTER_ENTRY)
        lo = await self.infilt.read_cpu(cfg_addr)
        hi = await self.infilt.read_cpu(cfg_addr + 4)
        src = (lo >> F_SRC_ID_LSB) & SRC_ID_MASK
        fc = field_compare(lo, 0, SRC_ID_FIELD)
        ext = SepMboxPortOps(self, c.filt_m, in_prot1=0, in_user=FILTER_SRC)
        ext_resp = await ext.push("in", c.filt_word)
        line = (
            f"pre_cfg=0x{self.pre_cfg:016x} pre_src_id={self.pre_src} src_id=0x{src:x} "
            f"src_field[{fc.fields()}]"
        )
        if not fc.ok:
            self._fail("CHK-RESET-FILTER", line)
        self._pass("CHK-RESET-FILTER", line)
        self.logger.info(
            "OBS-FILTER-RESET LOG seed=%d cfg=0x%016x locked=%d entry_enabled=%d allow_ns=%d "
            "ext_write=%s",
            c.seed,
            (hi << 32) | lo,
            (hi >> FILTER_LOCKED_HI_BIT) & 1,
            int(bool(lo & F_ENTRY_ENABLED)),
            int(bool(lo & F_ALLOW_NS)),
            resp_name(ext_resp),
        )

        # Reuse.
        m = c.reuse_m
        push_resp = await self._push(m, "out", c.reuse_word)
        pop_resp, data = await self._lsu(SepAxiOp.READ, self._addr(m, "in", "READ_DATA"), size=3)
        line = (
            f"mbox={m} push_resp={resp_name(push_resp)} pop_resp={resp_name(pop_resp)} "
            f"pop_data=0x{data:016x} exp=0x{c.reuse_word:016x}"
        )
        if push_resp != RESP_OKAY or pop_resp != RESP_OKAY or data != c.reuse_word:
            self._fail("CHK-REUSE", line)
        self._pass("CHK-REUSE", line)

    # ---- scenario --------------------------------------------------------------
    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.c = c = _Cfg(seed)
        self.n_checks = 0
        self.logger.info("SEED seed=%d", seed)
        for d in c.draw_lines():
            self.logger.info("DRAW %s", d)
        await self.bring_up_no_cpu()
        self.suppress_host_axi_transaction_info()
        self.model = MboxSystem()
        self.bank = SepFilterBank(self, "in")
        self.infilt = SepInboundFilter(self)
        await SepMbox(self).ungate_clock()

        open_graded_window(TEST, self.logger)
        await self._setup()
        await self._pre_state()
        await self._reset_in_flight()
        close_graded_window(self.logger)
        await SepMbox(self).ungate_clock()
        open_graded_window(TEST, self.logger)
        await self._post()
        close_graded_window(self.logger)
        self.logger.info("RESULT %s seed=%d PASS checks=%d", TEST, seed, self.n_checks)
