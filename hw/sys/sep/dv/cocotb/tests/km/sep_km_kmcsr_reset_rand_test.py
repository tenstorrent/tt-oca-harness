# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""KMCSR registers, the KM SRAM write lock and size, and the KM reset domains.

no_cpu / lsu_stub_all_live / +skip_fuse_sense / +km_rom_hex=km_rom_poke.parhex.
SRAM scrambler off. Seeded (``SepSeededRng``): every draw is logged as ``DRAW``.

The KM CPU runs the POKE image (``tests/km_fw/km_rom_poke.S``), a legal master
of the KM bus that executes the op lists the host posts and stores what the DUT
returned in KM SRAM words 0 to 97 (``km_sram_probe_o``). The image grades
nothing. Every golden is in this leaf, from the generated KM register map and
RDL resets (``sep_km_kmcsr_reset_rand_plan.py``) and from the specification:
``hw/ip/key_manager/doc/architecture.adoc`` ("Reset Conditioning", "Key Manager
Control and Status Registers (KMCSR)", "SRAM Write Locking", "ROM
Warm-Persistent SRAM Region", "Parameters"), ``regs/gen/adoc/km_csr.adoc`` and
``hw/sys/sep/doc/reset_controller.adoc`` ("Isolation and Reset Sequencing",
"Resetting the Key Manager").

Checks (each anchored on a POKE readback, ``SEP_STATUS`` or a reset probe):
  CHK-CSR-VER       a VERSION write answers SLVERR and the value stays the RDL reset
  CHK-CSR-STATUS    each IRQ_STATUS bit is sticky; a W1C of the other bits and a write
                    of 0 keep it; its own W1C clears only it; bits [31:12] read 0
  CHK-CSR-SET       IRQ_SET sets exactly the mask bits
  CHK-CSR-ENABLE    the CPU IRQ line 3 handler enters once when S AND E is non-zero and
                    never when it is zero; a masked bit still sets
  CHK-CSR-ENTRY     IRQ_ENTRY_ADDR resets to 0x10, takes any value while unlocked, keeps
                    it after IRQ_ENTRY_LOCK; a write of 0 keeps the lock; a PARK resets both
  CHK-CSR-SCR       SCRAMBLER_CTRL reads 0 at boot; SCRAMBLER_KEY reads back while unlocked
  CHK-CSR-DEBUG     DEBUG reads 0xCAFEBEEF, CTRL reads 0
  CHK-SRAM-SIZE     22 tagged words (word 8191, 8191 - 2^k, 8 drawn) read back their own tag
  CHK-SRAM-LOCK     SRAM_LOCK holds the OR of two writes; a write of 0 changes nothing
  CHK-SRAM-DROP     a store to a locked region is dropped and sets exactly its region bit
                    and SRAM_WRITE_LOCK_ERR; the W1C rules of both registers
  CHK-SRAM-LAND     a store to an unlocked region lands and sets no violation bit
  CHK-SRAM-R31      with region 31 locked, stores at 0xFC00, 0xFC04, 0xFFFC are dropped
  CHK-SRAM-RELEASE  a PARK clears every lock and a store to a formerly locked region lands
  CHK-RST-WARM      SOFT and PARK reset the warm witnesses, keep the cold and data ones
  CHK-RST-COLD      a cold reset clears both domains and the mailbox word
  CHK-RST-WRONG     a wrong SOFT_RST_CODE takes no reset
  CHK-HOLD          the first ROM fetch after the km_sw_rst_n rise is at least
                    MIN_RESET_CYCLES (10) clocks later
  CHK-ISO           the three KM isolation probes stay 0 during a SOFT reset

Controls: the VERSION read before the write; the W1C of the other bits next to
the own W1C; E = 0 next to case (c), which raises the line for each of the 12
sources; a landed store in every round with a dropped one; region 31 unlocked in
round 2; the dropped store before each PARK; non-zero witnesses before every
reset; the exact code of the SOFT round next to the wrong codes; the probes that
read isolated during the PARK round. The real-cause pass (AXI_SLVERR, AXI_DECERR,
ROM_WRITE_ERR, DRBG_ERR) is logged only. Open-owner cells that run here are
logged with ``control=1``.

The extra PARK hold W counts host clocks from the ``km_sw_rst_n`` fall
(``km_gated_rst_n_probe_o``) to the first clock of AWVALID of the release write
on ``s_axi_aw*``. The first PARK uses the largest W and gives the fall delay and
the AW latency that time the shorter holds; the leaf logs the measured W of
every PARK and records a missed W as a missing control.

Not sent (not stated): an IRQ_SET read, the write response of DEBUG or CTRL.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env import sep_km_poke as kp
from env.sep_chk_log import SepChkLog
from env.sep_fcov_gate import close_graded_window, open_graded_window
from km import sep_km_kmcsr_reset_rand_plan as pl
from sep_base_test import sep_base_test
from seq_lib.sep_km_mailbox_seq import KM_STATUS_INBOUND_DEPTH_LSB, KM_STATUS_INBOUND_DEPTH_MASK
from seq_lib.sep_km_poke_seq import SepKmPoke
from seq_lib.sep_sw_reset_seq import (
    SEP_RESET_CTRL_SW_RESET_N,
    SW_RESET_N_BIT,
    SW_RESET_N_RESET_DEFAULT,
    SepSwReset,
)

TEST = "sep_km_kmcsr_reset_rand_test"

_SEP_RESET_BOUND = 20_000  # clocks for dbg_sep_reset_n_o to read 1
_PARK_BOUND = 20_000  # clocks for the fall, the rise and the first fetch
_REBOOT_BOUND = 200_000  # clocks for the image to restart after SOFT
_REBOOT_SETTLE = 4_000  # clocks for the restarted image to take a stale word
_MBOX_POLL_LOADS = 200_000  # loads of the KM-side poll for the pushed mailbox word
_DELAY_OPS = 2  # re-arm points between an interrupt source and the count read
_WRONG_GAP_OPS = 8  # idle ops after each wrong code (the no-reset window)


def _h(v: int | None) -> str:
    return "X" if v is None else f"0x{v:08x}"


@dataclass(frozen=True)
class _Smp:
    cyc: int
    rst: int | None
    iso: tuple[int | None, int | None, int | None]
    cnt: int | None
    aw: bool


class _ResetWatch:
    """Per-clock samples of KM-RST, KM-ISO, KM-COUNT and the SW_RESET_N AW start."""

    def __init__(self, test: sep_base_test, period_ps: int) -> None:
        dut = cocotb.top
        self.test = test
        self.period_ps = period_ps
        self.clk = dut.clk_i
        self.rst = dut.km_gated_rst_n_probe_o
        self.isos = (
            dut.hmac_km_isolated_probe_o,
            dut.kmac_km_isolated_probe_o,
            dut.abr_km_isolated_probe_o,
        )
        self.cnt = dut.km_rom_req_count_o
        self.awvalid = dut.s_axi_awvalid
        self.awaddr = dut.s_axi_awaddr
        self.rec: list[_Smp] = []
        self.by_cyc: dict[int, _Smp] = {}
        self._on = False

    def cyc(self) -> int:
        return round(get_sim_time("ps") / self.period_ps)

    def _bit(self, sig) -> int | None:
        try:
            return self.test.rd(sig)
        except AssertionError:
            return None

    def start(self) -> None:
        self.rec = []
        self.by_cyc = {}
        self._on = True
        cocotb.start_soon(self._run())

    async def stop(self) -> None:
        self._on = False
        await ClockCycles(self.clk, 2)

    async def _run(self) -> None:
        prev_aw = 1
        while True:
            await RisingEdge(self.clk)
            await ReadOnly()
            if not self._on:
                return
            awv = self._bit(self.awvalid)
            addr = self._bit(self.awaddr)
            aw = awv == 1 and prev_aw != 1 and addr == SEP_RESET_CTRL_SW_RESET_N
            prev_aw = awv if awv is not None else 1
            s = _Smp(
                self.cyc(),
                self._bit(self.rst),
                tuple(self._bit(p) for p in self.isos),
                self._bit(self.cnt),
                aw,
            )
            self.rec.append(s)
            self.by_cyc[s.cyc] = s

    def first_aw(self, after: int) -> int | None:
        return next((s.cyc for s in self.rec if s.cyc > after and s.aw), None)

    def _edge(self, after: int, frm: int, to: int) -> int | None:
        prev = None
        for s in self.rec:
            if s.cyc > after and prev is not None and prev.rst == frm and s.rst == to:
                return s.cyc
            prev = s
        return None

    def first_fall(self, after: int) -> int | None:
        return self._edge(after, 1, 0)

    def first_rise(self, after: int) -> int | None:
        return self._edge(after, 0, 1)

    def first_count_change(self, at: int) -> int | None:
        base = self.by_cyc[at].cnt
        return next((s.cyc for s in self.rec if s.cyc > at and s.cnt != base), None)

    def window(self, lo: int, hi: int) -> list[_Smp]:
        return [s for s in self.rec if lo <= s.cyc <= hi]


@pyuvm.test()
class sep_km_kmcsr_reset_rand_test(sep_base_test):
    """KMCSR register semantics, SRAM lock and size, KM reset-domain matrix."""

    required_evidence = (
        "CHK-CSR-VER",
        "CHK-CSR-STATUS",
        "CHK-CSR-SET",
        "CHK-CSR-ENABLE",
        "CHK-CSR-ENTRY",
        "CHK-CSR-SCR",
        "CHK-CSR-DEBUG",
        "CHK-SRAM-SIZE",
        "CHK-SRAM-LOCK",
        "CHK-SRAM-DROP",
        "CHK-SRAM-LAND",
        "CHK-SRAM-R31",
        "CHK-SRAM-RELEASE",
        "CHK-RST-WARM",
        "CHK-RST-COLD",
        "CHK-RST-WRONG",
        "CHK-HOLD",
        "CHK-ISO",
    )

    # ------------------------------------------------------------------ main

    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.logger.info("SEED seed=%d", seed)
        self.chk = SepChkLog(self, TEST, seed)
        self.plan = pl.draw_plan(seed)
        for line in pl.plan_draw_lines(self.plan):
            self.logger.info(line)
        self.chk.obs(
            "RSVD-MASKS",
            irq_status=_h(pl.IRQ_FIELDS),
            irq_enable=_h(pl.IRQ_EN_FIELDS),
            otp_lock=_h(pl.OTP_LOCK_FIELDS),
            otp_lock_cold=_h(pl.OTP_COLD_FIELDS),
            boot_status=_h(pl.CBD_BIT),
            entry_lock=_h(pl.ENTRY_LOCK_BIT),
            scrambler_ctrl=_h(pl.SCR_CTRL_FIELDS),
            smp_cfg=_h(pl.CFG_FIELDS),
        )
        self.dut = cocotb.top
        self.period_ps = self._whole_ps(self.cfg.sys_clk_period_ns, "clk_i period")
        self.lat: int | None = None  # clocks from a SW_RESET_N write launch to AWVALID
        self.fall_delay: int | None = None  # clocks from the PARK AWVALID to the fall
        self.iso_soft: tuple | None = None
        self.iso_park_seen: bool | None = None
        self.soft_cleared_lock: bool | None = None

        # Step 1: cold bring-up, KM release, start marker.
        await self.bring_up_no_cpu()
        self.swrst = SepSwReset(self)
        self.poke = SepKmPoke(self)
        self.watch = _ResetWatch(self, self.period_ps)
        await self._wait_sep_reset_n()
        self.watch.start()
        task, e = self._launch("release")
        await task
        await ClockCycles(self.dut.clk_i, 2)
        self._learn_lat(e, "initial release")
        await self.poke.wait_boot()
        await self.watch.stop()

        open_graded_window(TEST, self.logger)
        await self._csr_reset_reads()
        await self._csr_version()
        await self._irq_walk()
        close_graded_window(self.logger)
        await self._real_cause()
        open_graded_window(TEST, self.logger)
        await self._irq_set_masks()
        await self._irq_enable_cases()
        await self._scrambler()
        await self._irq_entry()
        await self._park_w(0, "before SRAM size walk")
        await self._entry_after_park()
        await self._sram_size()
        for k, rnd in enumerate(self.plan.sram_rounds):
            await self._sram_round(rnd)
            await self._park_w(k + 1, f"after SRAM round {rnd.index}")
            await self._sram_release(rnd)
        await self._reset_rounds()

        if not (self.swrst.value >> SW_RESET_N_BIT["km"]) & 1:
            await self.swrst.release("km")
        close_graded_window(self.logger)
        self.chk.finish()

    # ------------------------------------------------------------ plumbing

    async def _edge(self) -> int:
        await RisingEdge(self.dut.clk_i)
        return self.watch.cyc()

    def _launch(self, kind: str):
        """Start a SW_RESET_N write of the KM bit now; returns (task, launch clock)."""
        e = self.watch.cyc()
        coro = self.swrst.park("km") if kind == "park" else self.swrst.release("km")
        return cocotb.start_soon(coro), e

    def _learn_lat(self, launch: int, what: str) -> int:
        a = self.watch.first_aw(launch - 1)
        if a is None:
            raise AssertionError(f"no SW_RESET_N AWVALID seen after the {what} write")
        self.lat = a - launch
        self.logger.info("LOG sw_reset_n_aw_latency=%d clocks (%s)", self.lat, what)
        return a

    async def _wait_sep_reset_n(self) -> None:
        for _ in range(_SEP_RESET_BOUND):
            await RisingEdge(self.dut.clk_i)
            if self.rd(self.dut.dbg_sep_reset_n_o, allow_unknown=True):
                return
        raise AssertionError(f"dbg_sep_reset_n_o did not read 1 within {_SEP_RESET_BOUND} clocks")

    async def _run(self, ops, *, allow_unknown: bool = False) -> list[kp.PokeResult]:
        return await self.poke.run(ops, allow_unknown=allow_unknown)

    async def _run_items(self, items) -> None:
        """Pack (ops, handler) items into lists that fit the POKE buffer and run them."""
        batch: list = []
        words = slots = 0

        async def flush() -> None:
            nonlocal batch, words, slots
            if not batch:
                return
            res = await self._run([op for ops, _ in batch for op in ops])
            pos = 0
            for ops, fn in batch:
                fn(res[pos : pos + len(ops)])
                pos += len(ops)
            batch, words, slots = [], 0, 0

        for ops, fn in items:
            w, s = kp.list_words(ops), kp.list_slots(ops)
            if batch and (words + w > kp.BUF_WORDS or slots + s > kp.N_SLOTS):
                await flush()
            batch.append((ops, fn))
            words += w
            slots += s
        await flush()

    def _raw_clear_irq(self) -> kp.PokeOp:
        return kp.wr(pl.A_IRQ_STATUS, pl.IRQ_FIELDS, raw=True)

    # ------------------------------------------------- steps 2 and 3: resets, VERSION

    async def _csr_reset_reads(self) -> None:
        r = await self._run(
            [
                kp.rd(pl.A_IRQ_ENABLE),
                kp.rd(pl.A_ENTRY),
                kp.rd(pl.A_ENTRY_LOCK),
                kp.rd(pl.A_VERSION),
                kp.rd(pl.A_DEBUG),
                kp.rd(pl.A_CTRL),
                kp.rd(pl.A_SCR_CTRL),
            ]
        )
        en, entry, lock, ver, dbg, ctrl, scr = (x.value for x in r)
        self.entry_reset = (entry, lock & pl.ENTRY_LOCK_BIT, lock & ~pl.ENTRY_LOCK_BIT)
        self.scr_boot = scr
        self.chk.obs("CSR-VERSION-READ", control=1, version=_h(ver))
        self.chk.ok(
            "CSR-ENABLE",
            (en & pl.IRQ_EN_FIELDS) == pl.IRQ_ENABLE_RESET,
            case="reset",
            e=_h(en & pl.IRQ_EN_FIELDS),
            golden=_h(pl.IRQ_ENABLE_RESET),
            rsvd=_h(en & ~pl.IRQ_EN_FIELDS),
        )
        self.chk.ok(
            "CSR-DEBUG",
            dbg == pl.DEBUG_RESET and ctrl == pl.CTRL_RESET,
            debug=_h(dbg),
            ctrl=_h(ctrl),
            golden_debug=_h(pl.DEBUG_RESET),
            golden_ctrl=_h(pl.CTRL_RESET),
            slv=[x.slv for x in r[3:6]],
        )

    async def _csr_version(self) -> None:
        v = self.plan.ver_wr
        r = await self._run(
            [
                self._raw_clear_irq(),
                kp.rd(pl.A_VERSION, raw=True),
                kp.wr(pl.A_VERSION, v),
                kp.rd(pl.A_IRQ_STATUS, raw=True),
                kp.rd(pl.A_VERSION, raw=True),
                self._raw_clear_irq(),
            ]
        )
        before, wr, irq, after = r[1].value, r[2], r[3].value, r[4].value
        ok = (
            wr.clean
            and wr.slv == 1
            and wr.dec == 0
            and (irq & pl.IRQ_SLVERR) != 0
            and after == pl.VERSION_RESET
        )
        self.chk.ok(
            "CSR-VER",
            ok,
            wr_val=_h(v),
            wr_slv=wr.slv,
            wr_dec=wr.dec,
            wr_clean=wr.clean,
            irq_status=_h(irq),
            after=_h(after),
            golden=_h(pl.VERSION_RESET),
            control_rd=_h(before),
        )

    # ------------------------------------------------------- step 4: IRQ_STATUS walk

    async def _irq_walk(self) -> None:
        r = await self._run(
            [
                kp.arm([kp.IRQ_LINE_KMCSR], kp.ACT_CLEAR),
                kp.reseth(0),
                kp.wr(pl.A_IRQ_ENABLE, 0, raw=True),
                self._raw_clear_irq(),
                kp.rd(pl.A_IRQ_STATUS, raw=True),
            ]
        )
        self.chk.ctrl("CSR-STATUS-CLEAN", r[4].value == 0, irq_status=_h(r[4].value))
        entries = 0
        status_set = 0
        for i, j in self.plan.walk:
            bi, bj = 1 << i, 1 << j
            ops = [
                kp.wr(pl.A_IRQ_SET, bi, raw=True),
                kp.cnt(kp.IRQ_LINE_KMCSR),
                kp.rd(pl.A_IRQ_STATUS, raw=True),
                kp.wr(pl.A_IRQ_STATUS, pl.IRQ_FIELDS & ~bi, raw=True),
                kp.rd(pl.A_IRQ_STATUS, raw=True),
                kp.wr(pl.A_IRQ_STATUS, 0, raw=True),
                kp.rd(pl.A_IRQ_STATUS, raw=True),
                kp.wr(pl.A_IRQ_SET, bj, raw=True),
                kp.rd(pl.A_IRQ_STATUS, raw=True),
                kp.wr(pl.A_IRQ_STATUS, bi, raw=True),
                kp.rd(pl.A_IRQ_STATUS, raw=True),
                kp.wr(pl.A_IRQ_STATUS, bj, raw=True),
                kp.rd(pl.A_IRQ_STATUS, raw=True),
            ]
            r = await self._run(ops)
            n, s_set, s_oth, s_zero, s_both, s_self, s_j = (
                r[1].value,
                r[2].value,
                r[4].value,
                r[6].value,
                r[8].value,
                r[10].value,
                r[12].value,
            )
            entries += n
            status_set += int(s_set == bi)
            self.chk.ok(
                "CSR-STATUS",
                s_set == bi
                and s_oth == bi
                and s_zero == bi
                and s_both == (bi | bj)
                and s_self == bj
                and s_j == 0,
                bit=i,
                name=pl.IRQ_NAMES[i],
                src="irq_set",
                j=j,
                set=_h(s_set),
                w1c_other=_h(s_oth),
                zero_write=_h(s_zero),
                with_j=_h(s_both),
                w1c_self=_h(s_self),
                w1c_j=_h(s_j),
                rsvd=_h((s_set | s_oth | s_zero | s_both) & ~pl.IRQ_FIELDS),
            )
        await self._run([kp.disarm()])
        self.chk.ok(
            "CSR-ENABLE",
            entries == 0 and status_set == pl.IRQ_BITS,
            case="walk",
            e=0,
            bits=pl.IRQ_BITS,
            entries=entries,
            status_set=status_set,
        )

    # -------------------------------------------------- step 5: real causes (log only)

    async def _real_cause(self) -> None:
        to1 = pl.KM_SMP.value("CFG_REG", TIMEOUT=1, PREFETCH=0)
        causes = [
            ("kpv_past_extent", [kp.rd(pl.KPV_END, raw=True)]),
            ("reserved_span", [kp.rd(pl.ROM_END, raw=True)]),
            ("rom_store", [kp.wr(pl.ROM_BASE, 0x5A5A_5A5A, raw=True)]),
            (
                "drbg_timeout",
                [kp.wr(pl.A_SMP_CFG, to1, raw=True), kp.rd(pl.A_SMP_DATA, raw=True)],
            ),
        ]
        for name, ops in causes:
            r = await self._run(
                [
                    self._raw_clear_irq(),
                    *ops,
                    kp.rd(pl.A_IRQ_STATUS, raw=True),
                    self._raw_clear_irq(),
                    kp.wr(pl.A_SMP_CFG, pl.CFG_RESET, raw=True),
                ]
            )
            irq = r[1 + len(ops)].value
            rose = [pl.IRQ_NAMES[b] for b in range(pl.IRQ_BITS) if (irq >> b) & 1]
            self.chk.obs("REAL-CAUSE", cause=name, irq_status=_h(irq), rose=rose or "none")

    # ---------------------------------------------------------- step 6: IRQ_SET masks

    async def _irq_set_masks(self) -> None:
        for m in self.plan.set_masks:
            r = await self._run(
                [
                    kp.wr(pl.A_IRQ_SET, m, raw=True),
                    kp.rd(pl.A_IRQ_STATUS, raw=True),
                    self._raw_clear_irq(),
                    kp.rd(pl.A_IRQ_STATUS, raw=True),
                ]
            )
            st = r[1].value
            self.chk.ok(
                "CSR-SET",
                st == m,
                mask=_h(m),
                status=_h(st),
                rsvd=_h(st & ~pl.IRQ_FIELDS),
                after_clear=_h(r[3].value),
            )

    # ------------------------------------------------------ step 7: enable aggregate

    def _case_ops(self, c) -> list[kp.PokeOp]:
        line = kp.IRQ_LINE_KMCSR
        head = [kp.reseth(0)]
        tail = [
            kp.wr(pl.A_IRQ_ENABLE, 0, raw=True),
            self._raw_clear_irq(),
            kp.rd(pl.A_IRQ_STATUS, raw=True),
        ]
        if c.kind == "d":
            body = [
                kp.wr(pl.A_IRQ_ENABLE, 0, raw=True),
                kp.wr(pl.A_IRQ_SET, c.s, raw=True),
                kp.delay(_DELAY_OPS),
                kp.cnt(line),
                kp.rd(pl.A_IRQ_STATUS, raw=True),
                kp.wr(pl.A_IRQ_ENABLE, c.e, raw=True),
                kp.delay(_DELAY_OPS),
                kp.cnt(line),
                kp.rd(pl.A_IRQ_STATUS, raw=True),
            ]
        else:
            body = [
                kp.wr(pl.A_IRQ_ENABLE, c.e, raw=True),
                kp.wr(pl.A_IRQ_SET, c.s, raw=True),
                kp.delay(_DELAY_OPS),
                kp.cnt(line),
                kp.rd(pl.A_IRQ_STATUS, raw=True),
            ]
        return head + body + tail

    def _grade_case(self, c, res) -> None:
        vals = [x.value for x in res if x.op.code in (kp.OP_CNT, kp.OP_RD)]
        if c.kind == "d":
            n0, st0, n1, st1 = vals[0], vals[1], vals[2], vals[3]
            want = c.s & ~c.e
            ok = n0 == 0 and st0 == c.s and n1 == 1 and st1 == want
            self.chk.ok(
                "CSR-ENABLE",
                ok,
                case="d",
                e=_h(c.e),
                s=_h(c.s),
                entries_masked=n0,
                status_masked=_h(st0),
                entries=n1,
                status=_h(st1),
                golden_status=_h(want),
                masked_set=int(st0 == c.s),
            )
            self.cell_entries["d"] = n1
            return
        n, st = vals[0], vals[1]
        if c.kind == "c":
            want_n, want_st = 1, c.s & ~c.e
        else:
            want_n, want_st = 0, c.s
        self.chk.ok(
            "CSR-ENABLE",
            n == want_n and st == want_st,
            case=c.kind,
            src=c.src if c.kind == "c" else "-",
            e=_h(c.e),
            s=_h(c.s),
            entries=n,
            status=_h(st),
            golden_status=_h(want_st),
            masked_set=int((st & c.s & ~c.e) == (c.s & ~c.e)),
        )
        if c.kind == "c":
            self.cell_entries.setdefault("c", {})[c.src] = n
        else:
            self.cell_entries[c.kind] = n

    async def _irq_enable_cases(self) -> None:
        self.cell_entries: dict = {}
        p = self.plan
        cases = []
        for kind in p.en_order:
            cases += p.en_c if kind == "c" else [{"a": p.en_a, "b": p.en_b, "d": p.en_d}[kind]]
        items = [([kp.arm([kp.IRQ_LINE_KMCSR], kp.ACT_CLEAR)], lambda _r: None)]
        for c in cases:
            items.append((self._case_ops(c), lambda res, c=c: self._grade_case(c, res)))
        items.append(([kp.disarm()], lambda _r: None))
        await self._run_items(items)
        srcs = self.cell_entries.get("c", {})
        self.chk.ctrl(
            "CSR-ENABLE-TWIN",
            len(srcs) == pl.IRQ_BITS and all(n == 1 for n in srcs.values()),
            sources_entered=sum(1 for n in srcs.values() if n == 1),
            e0_entries=self.cell_entries.get("a"),
        )

    # ------------------------------------------------------- step 8: scrambler regs

    async def _scrambler(self) -> None:
        k, k2 = self.plan.scr_k, self.plan.scr_k2
        r = await self._run(
            [
                kp.rd(pl.A_SCR_CTRL),
                kp.wr(pl.A_SCR_KEY, k),
                kp.rd(pl.A_SCR_KEY),
                kp.wr(pl.A_SCR_KEY, k2),
                kp.rd(pl.A_SCR_KEY),
            ]
        )
        ctrl = r[0].value
        f = pl.SCR_CTRL_FIELDS
        self.chk.ok(
            "CSR-SCR",
            (ctrl & f) == pl.SCR_CTRL_RESET
            and (self.scr_boot & f) == pl.SCR_CTRL_RESET
            and r[2].value == k
            and r[4].value == k2,
            ctrl_rd=_h(ctrl & f),
            ctrl_boot_rd=_h(self.scr_boot & f),
            rsvd=_h((ctrl | self.scr_boot) & ~f),
            key=_h(k),
            key_rd=_h(r[2].value),
            key2=_h(k2),
            key2_rd=_h(r[4].value),
        )

    # ---------------------------------------------------------- step 9: IRQ entry

    async def _irq_entry(self) -> None:
        p = self.plan
        r = await self._run(
            [
                kp.wr(pl.A_ENTRY, p.entry_aligned),
                kp.rd(pl.A_ENTRY),
                kp.wr(pl.A_ENTRY, p.entry_unaligned),
                kp.rd(pl.A_ENTRY),
                kp.wr(pl.A_ENTRY, pl.WORD_MASK),
                kp.rd(pl.A_ENTRY),
                kp.wr(pl.A_ENTRY_LOCK, pl.ENTRY_LOCK_BIT),
                kp.rd(pl.A_ENTRY_LOCK),
                kp.wr(pl.A_ENTRY, p.entry_v2),
                kp.rd(pl.A_ENTRY),
                kp.wr(pl.A_ENTRY_LOCK, 0),
                kp.rd(pl.A_ENTRY_LOCK),
            ]
        )
        self.entry_res = [x.value for x in r[1::2]]

    async def _entry_after_park(self) -> None:
        r = await self._run([kp.rd(pl.A_ENTRY), kp.rd(pl.A_ENTRY_LOCK)])
        p = self.plan
        al, un, ff, lock1, v2_rd, lock_w0 = self.entry_res
        e0, l0, rsvd0 = self.entry_reset
        lk = pl.ENTRY_LOCK_BIT
        after, after_lock = r[0].value, r[1].value & lk
        ok = (
            e0 == pl.ENTRY_RESET
            and l0 == pl.ENTRY_LOCK_RESET
            and al == p.entry_aligned
            and un == p.entry_unaligned
            and ff == pl.WORD_MASK
            and (lock1 & lk) == lk
            and v2_rd == pl.WORD_MASK
            and (lock_w0 & lk) == lk
            and after == pl.ENTRY_RESET
            and after_lock == pl.ENTRY_LOCK_RESET
        )
        self.chk.ok(
            "CSR-ENTRY",
            ok,
            reset=_h(e0),
            lock_reset=l0,
            aligned=f"{_h(p.entry_aligned)}/{_h(al)}",
            unaligned=f"{_h(p.entry_unaligned)}/{_h(un)}",
            all_ones=_h(ff),
            lock=int((lock1 & lk) == lk),
            v2=_h(p.entry_v2),
            v2_kept=int(v2_rd == pl.WORD_MASK),
            lock_w0_kept=int((lock_w0 & lk) == lk),
            after_park=_h(after),
            after_park_lock=after_lock,
            rsvd=_h(rsvd0 | ((lock1 | lock_w0 | r[1].value) & ~lk)),
        )

    # ------------------------------------------------------- PARK with a timed hold

    async def _park(self, hold: int, *, exact: bool, label: str, during_hold=None) -> dict:
        """PARK: SW_RESET_N bit 0 low, hold ``hold`` clocks after the fall, then high.

        The release AWVALID is timed ``hold`` clocks after the ``km_sw_rst_n``
        fall. With ``exact`` and a hold shorter than the AW latency allows after
        the fall is seen, the launch uses the fall delay of an earlier PARK.
        """
        await self.poke.prepare_reset()
        if during_hold is None:
            # The SEP mailbox FIFO keeps its words across a warm reset and the
            # image reads a leftover word as a list header: start the leg empty.
            await self.poke.mbox.flush()
        w = self.watch
        w.start()
        await ClockCycles(self.dut.clk_i, 2)
        t_park, e_park = self._launch("park")
        a_park = fall = None
        rel = None
        held = during_hold is None
        for _ in range(_PARK_BOUND):
            e = await self._edge()
            if a_park is None:
                a_park = w.first_aw(e_park - 1)
            if fall is None and a_park is not None:
                fall = w.first_fall(a_park - 1)
            if fall is not None and not held:
                await during_hold()
                held = True
                continue
            target = None
            if fall is not None:
                target = fall + hold - self.lat
            elif (
                exact and a_park is not None and self.fall_delay is not None and hold - self.lat < 1
            ):
                target = a_park + self.fall_delay + hold - self.lat
            if target is not None and e >= target:
                rel = self._launch("release")
                break
        if rel is None:
            raise AssertionError(
                f"PARK {label}: no km_sw_rst_n fall within {_PARK_BOUND} clocks "
                f"(park AWVALID at {a_park})"
            )
        await t_park
        await rel[0]
        a_rel = self._learn_lat(rel[1], f"PARK {label} release")
        rise = cnt_at = None
        for _ in range(_PARK_BOUND):
            await self._edge()
            if fall is None:
                fall = w.first_fall(a_park - 1)
            if rise is None:
                rise = w.first_rise(a_rel - 1)
            if rise is not None:
                cnt_at = w.first_count_change(rise)
                if cnt_at is not None:
                    break
        if rise is None or cnt_at is None or fall is None:
            raise AssertionError(
                f"PARK {label}: fall={fall} rise={rise} first fetch={cnt_at} within "
                f"{_PARK_BOUND} clocks of the release"
            )
        await self.poke.wait_boot()
        await w.stop()
        if self.fall_delay is None:
            self.fall_delay = fall - a_park
        win = w.window(fall, a_rel)
        s_rel = w.by_cyc.get(a_rel)
        s_pre = w.by_cyc.get(a_rel - 1)
        rec = {
            "label": label,
            "hold": hold,
            "a_park": a_park,
            "fall": fall,
            "fall_delay": fall - a_park,
            "a_rel": a_rel,
            "w_act": a_rel - fall,
            "rise": rise,
            "first_fetch": cnt_at - rise - 1,
            "after_fall": a_rel > fall,
            "iso_at_rel": s_rel is not None and s_rel.iso == (1, 1, 1),
            "cnt_stable": s_rel is not None
            and s_pre is not None
            and s_rel.cnt is not None
            and s_rel.cnt == s_pre.cnt,
            "known": all(s.rst is not None and s.cnt is not None for s in win),
            "iso_seen": any(s.iso == (1, 1, 1) for s in win),
            "hold_fetches": (
                None
                if s_rel is None or s_rel.cnt is None or w.by_cyc[fall].cnt is None
                else s_rel.cnt - w.by_cyc[fall].cnt
            ),
        }
        self._grade_hold(rec, exact)
        return rec

    def _grade_hold(self, r: dict, exact: bool) -> None:
        self.chk.ctrl(
            "HOLD-PRE",
            r["after_fall"] and r["iso_at_rel"] and r["cnt_stable"] and r["known"],
            park=r["label"],
            fall=r["fall"],
            release_aw=r["a_rel"],
            iso_isolated_at_release=r["iso_at_rel"],
            count_stable=r["cnt_stable"],
            hold_fetches=r["hold_fetches"],
            known=r["known"],
        )
        if exact:
            self.chk.ctrl("HOLD-W", r["w_act"] == r["hold"], w=r["hold"], w_act=r["w_act"])
        self.chk.ok(
            "HOLD",
            r["first_fetch"] >= pl.MIN_RESET_CYCLES,
            w=r["hold"],
            w_act=r["w_act"],
            first_fetch_after_release=r["first_fetch"],
            bound=pl.MIN_RESET_CYCLES,
            fall_delay=r["fall_delay"],
            park=r["label"],
        )

    async def _park_w(self, k: int, label: str) -> None:
        w = self.plan.park_w[k]
        await self._park(w, exact=True, label=f"{label} w={w}")

    # ----------------------------------------------------- step 11: size and alias

    async def _sram_size(self) -> None:
        p = self.plan
        ops = [kp.wr(a, t) for a, t in zip(p.size_addrs, p.size_tags, strict=True)]
        ops += [kp.rd(a) for a in p.size_addrs]
        r = await self._run(ops)
        got = [x.value for x in r[len(p.size_addrs) :]]
        own = sum(1 for g, t in zip(got, p.size_tags, strict=True) if g == t)
        alias = sum(1 for g, t in zip(got, p.size_tags, strict=True) if g != t and g in p.size_tags)
        bad = [
            f"0x{a:04x}:{_h(g)}"
            for a, g, t in zip(p.size_addrs, got, p.size_tags, strict=True)
            if g != t
        ]
        self.chk.ok(
            "SRAM-SIZE",
            own == len(p.size_tags),
            tagged=len(p.size_tags),
            walk_bits=pl.WORD_ADDR_BITS,
            drawn=len(p.size_addrs) - pl.WORD_ADDR_BITS - 1,
            own_tag=own,
            alias=alias,
            bad=bad or "none",
        )

    # ------------------------------------------------------ steps 12-16: SRAM rounds

    def _store_item(self, rnd, a: int, locked: bool, sink: dict):
        r_a = pl.region_of(a)
        bit = 1 << r_a
        ops = [
            kp.wr(pl.A_VIOL, pl.WORD_MASK),
            kp.wr(pl.A_IRQ_STATUS, pl.IRQ_FIELDS),
            kp.wr(a, rnd.store[a]),
            kp.rd(a),
            kp.rd(pl.A_VIOL),
            kp.rd(pl.A_IRQ_STATUS),
        ]
        if locked:
            ops += [
                kp.wr(pl.A_VIOL, 0),
                kp.rd(pl.A_VIOL),
                kp.wr(pl.A_VIOL, bit),
                kp.rd(pl.A_VIOL),
                kp.rd(pl.A_IRQ_STATUS),
                kp.wr(pl.A_IRQ_STATUS, pl.IRQ_SRAM_LOCK),
                kp.rd(pl.A_IRQ_STATUS),
            ]

        def fn(res) -> None:
            word, viol, irq = res[3].value, res[4].value, res[5].value
            if not locked:
                ok = word == rnd.store[a] and viol == 0
                sink[a] = ok
                self.chk.ok(
                    "SRAM-LAND",
                    ok,
                    round=rnd.index,
                    addr=f"0x{a:04x}",
                    region=r_a,
                    locked=0,
                    word="new" if word == rnd.store[a] else _h(word),
                    viol=_h(viol),
                    irq=_h(irq),
                )
                return
            v0, v_clr, irq_kept, irq_clr = (
                res[7].value,
                res[9].value,
                res[10].value,
                res[12].value,
            )
            parity = irq & (pl.IRQ_ROM_PARITY | pl.IRQ_SRAM_PARITY)
            ok = (
                word == rnd.init[a]
                and viol == bit
                and (irq & pl.IRQ_SRAM_LOCK) != 0
                and parity == 0
                and (irq & pl.IRQ_ROM_WRITE) == 0
                and v0 == bit
                and v_clr == 0
                and (irq_kept & pl.IRQ_SRAM_LOCK) != 0
                and (irq_clr & pl.IRQ_SRAM_LOCK) == 0
            )
            sink[a] = ok
            self.chk.ok(
                "SRAM-DROP",
                ok,
                round=rnd.index,
                addr=f"0x{a:04x}",
                region=r_a,
                locked=1,
                word="old" if word == rnd.init[a] else _h(word),
                viol=_h(viol),
                golden_viol=_h(bit),
                irq=int((irq & pl.IRQ_SRAM_LOCK) != 0),
                parity=int(parity != 0),
                rom_write=int((irq & pl.IRQ_ROM_WRITE) != 0),
                viol_w0=_h(v0),
                viol_w1c=_h(v_clr),
                irq_after_viol_clr=_h(irq_kept),
                irq_w1c=_h(irq_clr),
            )

        return ops, fn

    async def _sram_round(self, rnd) -> None:
        init_items = [
            ([kp.wr(a, rnd.init[a])], lambda _r: None) for a in [*rnd.addrs, *pl.R31_FIXED]
        ]
        await self._run_items(init_items)
        r = await self._run(
            [
                kp.wr(pl.A_SRAM_LOCK, rnd.m),
                kp.wr(pl.A_SRAM_LOCK, rnd.m2),
                kp.rd(pl.A_SRAM_LOCK),
                kp.wr(pl.A_SRAM_LOCK, 0),
                kp.rd(pl.A_SRAM_LOCK),
            ]
        )
        or_rd, zero_rd = r[2].value, r[4].value
        self.chk.ok(
            "SRAM-LOCK",
            or_rd == rnd.lock and zero_rd == rnd.lock,
            round=rnd.index,
            m=_h(rnd.m),
            m2=_h(rnd.m2),
            mask=_h(rnd.lock),
            or_rd=_h(or_rd),
            zero_write=_h(zero_rd),
        )
        res: dict[int, bool] = {}
        items = [
            self._store_item(rnd, a, bool((rnd.lock >> pl.region_of(a)) & 1), res)
            for a in rnd.addrs
        ]
        await self._run_items(items)
        r31_locked = bool((rnd.lock >> 31) & 1)
        r31: dict[int, bool] = {}
        await self._run_items([self._store_item(rnd, a, r31_locked, r31) for a in pl.R31_FIXED])
        if r31_locked:
            self.chk.ok(
                "SRAM-R31",
                all(r31.values()) and len(r31) == len(pl.R31_FIXED),
                round=rnd.index,
                addrs=len(pl.R31_FIXED),
                dropped=sum(r31.values()),
                viol31=int(all(r31.values())),
            )
        else:
            self.chk.ctrl(
                "SRAM-R31-TWIN",
                all(r31.values()) and len(r31) == len(pl.R31_FIXED),
                round=rnd.index,
                landed=sum(r31.values()),
            )
        locked = [a for a in rnd.addrs if (rnd.lock >> pl.region_of(a)) & 1]
        self.chk.ctrl(
            "SRAM-LAND-TWIN",
            len(locked) < len(rnd.addrs),
            round=rnd.index,
            locked_stores=len(locked),
            unlocked_stores=len(rnd.addrs) - len(locked),
        )
        self.rel_dropped = res.get(rnd.rel_addr, False)

    async def _sram_release(self, rnd) -> None:
        a = rnd.rel_addr
        r = await self._run([kp.rd(pl.A_SRAM_LOCK), kp.wr(a, rnd.rel_val), kp.rd(a)])
        locks, word = r[0].value, r[2].value
        self.chk.ctrl("SRAM-RELEASE-DROP", self.rel_dropped, round=rnd.index, addr=f"0x{a:04x}")
        self.chk.ok(
            "SRAM-RELEASE",
            locks == pl.SRAM_LOCK_RESET and word == rnd.rel_val,
            round=rnd.index,
            locks=_h(locks),
            addr=f"0x{a:04x}",
            region=pl.region_of(a),
            store_lands=int(word == rnd.rel_val),
        )

    # -------------------------------------------------- steps 17-20: reset rounds

    def _witness_reads(self, w) -> tuple[list[kp.PokeOp], list[tuple[str, int]]]:
        names = [("otp_cold", pl.OTP_COLD_FIELDS), ("cbd", pl.CBD_BIT)]
        ops = [kp.rd(pl.A_OTP_LOCK_COLD, raw=True), kp.rd(pl.A_BOOT, raw=True)]
        for k, (a, _v) in enumerate(w.sram):
            names.append((f"sram{k}", pl.WORD_MASK))
            ops.append(kp.rd(a, raw=True))
        for name, addr, mask in (
            ("irq_en", pl.A_IRQ_ENABLE, pl.IRQ_EN_FIELDS),
            ("irq_status", pl.A_IRQ_STATUS, pl.WORD_MASK),
            ("entry", pl.A_ENTRY, pl.WORD_MASK),
            ("entry_lock", pl.A_ENTRY_LOCK, pl.ENTRY_LOCK_BIT),
            ("otp_lock", pl.A_OTP_LOCK, pl.OTP_LOCK_FIELDS),
            ("cfg", pl.A_SMP_CFG, pl.CFG_FIELDS),
            ("sram_lock", pl.A_SRAM_LOCK, pl.WORD_MASK),
        ):
            names.append((name, mask))
            ops.append(kp.rd(addr, raw=True))
        return ops, names

    @staticmethod
    def _decode(res, names) -> tuple[dict[str, int | None], dict[str, int]]:
        val: dict[str, int | None] = {}
        rsvd: dict[str, int] = {}
        for r, (name, mask) in zip(res, names, strict=True):
            val[name] = (r.value & mask) if r.known else None
            rsvd[name] = (r.value & ~mask & pl.WORD_MASK) if r.known else 0
        return val, rsvd

    def _warm_reset_model(self) -> None:
        m = self.model
        m.update(
            sram_lock=pl.SRAM_LOCK_RESET,
            irq_en=pl.IRQ_ENABLE_RESET,
            irq_status=pl.IRQ_STATUS_RESET,
            entry=pl.ENTRY_RESET,
            entry_lock=pl.ENTRY_LOCK_RESET,
            otp_lock=pl.OTP_LOCK_RESET,
            cfg=pl.CFG_RESET,
        )

    async def _reset_rounds(self) -> None:
        self.model = {"otp_cold": pl.OTP_COLD_RESET, "cbd": pl.CBD_RESET}
        self._warm_reset_model()
        await self._run(
            [
                kp.disarm(),
                self._raw_clear_irq(),
                kp.wr(pl.A_IRQ_ENABLE, 0, raw=True),
            ]
        )
        for k, w in enumerate(self.plan.rounds):
            await self._reset_round(k, w)
        self.chk.ok(
            "ISO",
            self.iso_soft is not None and self.iso_soft[0] == (0, 0, 0) and self.iso_soft[1] == 0,
            soft_iso=self.iso_soft[0] if self.iso_soft else "-",
            soft_unknown=self.iso_soft[1] if self.iso_soft else "-",
            soft_clocks=self.iso_soft[2] if self.iso_soft else "-",
            park_control=int(bool(self.iso_park_seen)),
        )
        self.chk.ctrl("ISO-PARK", bool(self.iso_park_seen), park_isolated_seen=self.iso_park_seen)
        self.chk.ctrl(
            "RST-WRONG-TWIN",
            bool(self.soft_cleared_lock),
            soft_code=_h(pl.SOFT_RST_CODE),
            soft_cleared_sram_lock=self.soft_cleared_lock,
        )

    async def _reset_round(self, k: int, w) -> None:
        m = self.model
        # Step 18: the witnesses, cold domain, then data, then warm domain.
        m["otp_cold"] |= 1 << w.otp_cold_bit
        m["cbd"] = pl.CBD_BIT
        m["irq_en"] = pl.W_IRQ_ENABLE
        m["irq_status"] |= pl.W_IRQ_SET
        if not m["entry_lock"]:
            m["entry"] = pl.W_ENTRY
        m["entry_lock"] = pl.ENTRY_LOCK_BIT
        m["otp_lock"] |= 1 << w.otp_bit
        m["cfg"] = pl.W_CFG & pl.CFG_FIELDS
        m["sram_lock"] |= w.sram_lock
        wr_ops = [
            kp.wr(pl.A_OTP_LOCK_COLD, 1 << w.otp_cold_bit, raw=True),
            kp.wr(pl.A_BOOT, pl.CBD_BIT, raw=True),
            kp.wr(pl.A_BOOT, 0, raw=True),
            *[kp.wr(a, v, raw=True) for a, v in w.sram],
            kp.wr(pl.A_IRQ_ENABLE, pl.W_IRQ_ENABLE, raw=True),
            kp.wr(pl.A_IRQ_SET, pl.W_IRQ_SET, raw=True),
            kp.wr(pl.A_ENTRY, pl.W_ENTRY, raw=True),
            kp.wr(pl.A_ENTRY_LOCK, pl.ENTRY_LOCK_BIT, raw=True),
            kp.wr(pl.A_OTP_LOCK, 1 << w.otp_bit, raw=True),
            kp.wr(pl.A_SMP_CFG, pl.W_CFG, raw=True),
            kp.wr(pl.A_SRAM_LOCK, w.sram_lock, raw=True),
        ]
        rd_ops, names = self._witness_reads(w)
        res = await self._run(wr_ops + rd_ops)
        pre, pre_rsvd = self._decode(res[len(wr_ops) :], names)
        want = dict(m)
        for i, (_a, v) in enumerate(w.sram):
            want[f"sram{i}"] = v
        miss = {n: _h(pre[n]) for n in want if pre.get(n) != want[n] or not pre[n]}
        self.chk.ctrl(
            "RST-PRE",
            not miss,
            round=k,
            kind=w.kind,
            nonzero=int(all(pre.values())),
            mismatch=miss or "none",
            rsvd={n: _h(v) for n, v in pre_rsvd.items() if v} or "none",
        )

        poll = kp.poll(pl.A_MBOX_KM_STATUS, pl.MBOX_KM_INBOUND_EMPTY, 0, _MBOX_POLL_LOADS, raw=True)
        if w.kind == "SOFT":
            await self._round_soft(k, w, pre, poll, names)
        elif w.kind == "SOFT-WRONG":
            await self._round_wrong(k, w, pre, poll, names)
        else:
            await self._round_park_cold(k, w, pre, poll, names)

    async def _post_and_push(self, ops, word: int):
        h = await self.poke.post(ops)
        await self.poke.wait(h, (kp.ST_RUN,))
        await self.poke.mbox.post_raw_words([word])
        self.logger.info("LOG mailbox word 0x%08x pushed after the image read its list", word)
        return h

    async def _readback(self, w, names, *, allow_unknown: bool = False):
        rd_ops, _ = self._witness_reads(w)
        res = await self._run(rd_ops, allow_unknown=allow_unknown)
        return self._decode(res, names)

    def _warm_fields(self, post) -> dict[str, bool]:
        return {
            "sram_lock": post["sram_lock"] == pl.SRAM_LOCK_RESET,
            "irq_en": post["irq_en"] == pl.IRQ_ENABLE_RESET,
            "irq_status": post["irq_status"] == pl.IRQ_STATUS_RESET,
            "entry": post["entry"] == pl.ENTRY_RESET,
            "entry_lock": post["entry_lock"] == pl.ENTRY_LOCK_RESET,
            "otp_lock": post["otp_lock"] == pl.OTP_LOCK_RESET,
        }

    async def _round_soft(self, k, w, pre, poll, names) -> None:
        await self.poke.prepare_reset()
        self.watch.start()
        await self._post_and_push(
            [poll, kp.wr(pl.A_SOFT_RST, pl.SOFT_RST_CODE, raw=True)], w.mbox_word
        )
        st = await self._wait_reboot()
        await self.watch.stop()
        smp = self.watch.rec
        iso_or = tuple(int(any(s.iso[i] for s in smp if s.iso[i] is not None)) for i in range(3))
        unknown = sum(1 for s in smp if None in s.iso)
        self.iso_soft = (iso_or, unknown, len(smp))
        depth = await self._inbound_depth()
        self.chk.obs(
            "RST-SOFT-MBOX",
            round=k,
            state=kp.STATE_NAMES.get(st[0], st[0]),
            err=_h(self.poke.word(kp.W_ERR)),
            word_low=_h(w.mbox_word & 0xFF_FFFF),
            sep_inbound_depth=depth,
        )
        post, rsvd = await self._readback(w, names)
        warm = self._warm_fields(post)
        cold_kept = post["otp_cold"] == pre["otp_cold"] and post["cbd"] == pl.CBD_BIT
        data_same = all(post[f"sram{i}"] == v for i, (_a, v) in enumerate(w.sram))
        cfg_ok = post["cfg"] == pl.CFG_RESET
        self.soft_cleared_lock = warm["sram_lock"] and pre["sram_lock"] != 0
        self.chk.ok(
            "RST-WARM",
            all(warm.values()) and cold_kept and data_same and cfg_ok,
            kind="soft",
            round=k,
            sram_lock=_h(post["sram_lock"]),
            irq_en=_h(post["irq_en"]),
            irq_status=_h(post["irq_status"]),
            entry=_h(post["entry"]),
            entry_lock=post["entry_lock"],
            otp_lock=_h(post["otp_lock"]),
            cfg=_h(post["cfg"]),
            otp_lock_cold=_h(post["otp_cold"]),
            cbd=post["cbd"],
            cold_kept=int(cold_kept),
            data_same=int(data_same),
            rsvd={n: _h(v) for n, v in rsvd.items() if v} or "none",
        )
        self._warm_reset_model()

    async def _round_wrong(self, k, w, pre, poll, names) -> None:
        ops = [poll]
        for c in self.plan.wrong_codes:
            if c == pl.SOFT_RST_CODE:
                raise AssertionError("a wrong SOFT_RST_CODE equals the reset code")
            ops += [
                kp.wr(pl.A_SOFT_RST, c, raw=True),
                kp.rd(pl.A_SRAM_LOCK, raw=True),
                kp.rd(pl.A_BOOT, raw=True),
                kp.delay(_WRONG_GAP_OPS),
            ]
        ops.append(kp.sync())
        h = await self._post_and_push(ops, w.mbox_word)
        await self.poke.wait(h, (kp.ST_DONE,))
        res = self.poke.results(h)
        saw_word = (res[0].data[0] & pl.MBOX_KM_INBOUND_EMPTY) == 0
        self.chk.ctrl("RST-WRONG-MBOX-SEEN", saw_word, round=k, km_status=_h(res[0].data[0]))
        for n, c in enumerate(self.plan.wrong_codes):
            lock = res[2 + 4 * n].value
            cbd = res[3 + 4 * n].value & pl.CBD_BIT
            self.chk.ok(
                "RST-WRONG",
                lock == pre["sram_lock"] and cbd == pl.CBD_BIT,
                val=_h(c),
                sram_lock=_h(lock),
                sram_lock_kept=int(lock == pre["sram_lock"]),
                cbd_kept=int(cbd == pl.CBD_BIT),
            )
        mbox_rd = res[-1].value
        post, rsvd = await self._readback(w, names)
        kept = {n: post[n] == pre[n] for n in pre}
        self.chk.ok(
            "RST-WRONG",
            all(kept.values()) and mbox_rd == w.mbox_word,
            val="all",
            round=k,
            witnesses_kept=int(all(kept.values())),
            changed=[n for n, v in kept.items() if not v] or "none",
            mbox_word=_h(w.mbox_word),
            mbox_read=_h(mbox_rd),
            restart=0,
            rsvd={n: _h(v) for n, v in rsvd.items() if v} or "none",
        )

    async def _round_park_cold(self, k, w, pre, poll, names) -> None:
        h = await self._post_and_push([poll, kp.jump(kp.ENTRY_SPIN, raw=True)], w.mbox_word)
        await self.poke.wait(h, (kp.ST_JUMP,))
        res = self.poke.results(h, partial=True)
        saw_word = bool(res) and (res[0].data[0] & pl.MBOX_KM_INBOUND_EMPTY) == 0
        self.chk.ctrl("RST-MBOX-SEEN", saw_word, round=k, kind=w.kind)
        if w.kind == "PARK":
            await self._round_park(k, w, pre, names)
        else:
            await self._round_cold(k, w, pre, names)

    async def _round_park(self, k, w, pre, names) -> None:
        held: dict[str, int] = {}

        async def during_hold() -> None:
            held["depth"] = await self._inbound_depth()
            await self.poke.mbox.flush()

        rec = await self._park(
            pl.PARK_ROUND_HOLD, exact=False, label=f"reset round {k}", during_hold=during_hold
        )
        self.iso_park_seen = rec["iso_seen"]
        post, rsvd = await self._readback(w, names)
        warm = self._warm_fields(post)
        cold_kept = post["otp_cold"] == pre["otp_cold"]
        data_same = all(post[f"sram{i}"] == v for i, (_a, v) in enumerate(w.sram))
        mbox_kept = held.get("depth") == 1
        self.chk.ok(
            "RST-WARM",
            all(warm.values()) and cold_kept and data_same and mbox_kept,
            kind="park",
            round=k,
            sram_lock=_h(post["sram_lock"]),
            irq_en=_h(post["irq_en"]),
            irq_status=_h(post["irq_status"]),
            entry=_h(post["entry"]),
            entry_lock=post["entry_lock"],
            otp_lock=_h(post["otp_lock"]),
            otp_lock_cold=_h(post["otp_cold"]),
            cold_kept=int(cold_kept),
            data_same=int(data_same),
            mbox_depth_hold=held.get("depth"),
            rsvd={n: _h(v) for n, v in rsvd.items() if v} or "none",
        )
        self.chk.obs("RST-PARK-OWNER", control=1, cfg=_h(post["cfg"]), cbd=post["cbd"])
        self._warm_reset_model()

    async def _round_cold(self, k, w, pre, names) -> None:
        await self.poke.prepare_reset()
        self.watch.start()
        await self.pulse_rst_ni()
        depth = await self._inbound_depth()
        self.swrst.value = SW_RESET_N_RESET_DEFAULT
        await self.swrst.release("km")
        await self.poke.wait_boot()
        await self.watch.stop()
        iso_or = tuple(
            int(any(s.iso[i] for s in self.watch.rec if s.iso[i] is not None)) for i in range(3)
        )
        self.chk.obs("RST-COLD-ISO", round=k, iso_seen=iso_or)
        post, rsvd = await self._readback(w, names, allow_unknown=True)
        warm = self._warm_fields(post)
        warm["cfg"] = post["cfg"] == pl.CFG_RESET
        cold = post["otp_cold"] == pl.OTP_COLD_RESET and post["cbd"] == pl.CBD_RESET
        self.chk.ok(
            "RST-COLD",
            all(warm.values()) and cold and depth == 0,
            kind="cold",
            round=k,
            cbd=post["cbd"],
            otp_lock_cold=_h(post["otp_cold"]),
            mbox_depth=depth,
            warm_cleared=int(all(warm.values())),
            not_cleared=[n for n, v in warm.items() if not v] or "none",
            rsvd={n: _h(v) for n, v in rsvd.items() if v} or "none",
        )
        self.chk.obs(
            "RST-COLD-SRAM",
            round=k,
            words=[_h(post[f"sram{i}"]) for i in range(len(w.sram))],
        )
        self.model = {"otp_cold": pl.OTP_COLD_RESET, "cbd": pl.CBD_RESET}
        self._warm_reset_model()

    async def _inbound_depth(self) -> int:
        st = await self.poke.mbox.read_status()
        return (st >> KM_STATUS_INBOUND_DEPTH_LSB) & KM_STATUS_INBOUND_DEPTH_MASK

    async def _wait_reboot(self) -> tuple[int, int]:
        """Wait for the restart of the image after SOFT, then for it to take a stale word."""
        restarted = ((kp.ST_BOOT, 0), (kp.ST_ERROR, 0))
        st = None
        for _ in range(0, _REBOOT_BOUND, 16):
            st = self.poke.state()
            if st in restarted:
                break
            await ClockCycles(self.dut.clk_i, 16)
        else:
            raise AssertionError(f"the image did not restart within {_REBOOT_BOUND} clocks: {st}")
        for _ in range(0, _REBOOT_SETTLE, 16):
            if st != (kp.ST_BOOT, 0):
                break
            await ClockCycles(self.dut.clk_i, 16)
            st = self.poke.state()
        return st
