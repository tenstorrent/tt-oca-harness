# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The CSRNG and EDN ``REGWEN`` lock, its RW0C behaviour and its reset.

Contract (``vendor/lowRISC/opentitan/overlay/regs/csrng/regs/gen/adoc/csrng.adoc``,
REGWEN, lines 97-98; ``vendor/lowRISC/opentitan/overlay/regs/edn/regs/gen/adoc/edn.adoc``,
REGWEN, lines 85-86; the ``regwen`` binding of each register in
``vendor/lowRISC/opentitan/upstream/hw/ip/csrng/data/csrng.hjson`` and
``vendor/lowRISC/opentitan/upstream/hw/ip/edn/data/edn.hjson``):
  * ``REGWEN`` is RW0C and resets to 1. With it cleared, the registers bound to
    it are read-only: CSRNG ``CTRL`` and ``FIPS_FORCE``, EDN ``CTRL``.
  * A write of 1 does not set a cleared ``REGWEN``; only a reset sets it.
  * The TRNG reset is a full-IP reset of the entropy source and the DRBG
    (``hw/ip/entropy_source/doc/architecture.adoc``, Reset), so it restores
    ``REGWEN`` and the reset value of each target.

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense``, VCS only (the
reset readback must show no X). Baseline ``SW_RESET_N`` = 0x20: the TRNG domain
released, the Key Manager and every crypto engine held. ESRC, CSRNG and EDN are
not started: ``ENABLE``, ``EDN_ENABLE`` and ``CMD_FIFO_RST`` stay False.

Randomization (``SepSeededRng`` from the run seed, drawn before the first
stimulus): the order of the three targets, the values A and B of each target
(multi-bit-boolean fields from True 6 and False 9; ``FIPS_FORCE`` non-zero
3-bit values), the data on the inactive 32-bit lane of the 64-bit bus of each
write (the strobe covers the register lane only), the ``INT_STATE_READ_ENABLE``
value of the observation, and the count r (1 to 3) of re-set attempts.

Checkers:
  CHK-REGWEN-LOCK     after the write of 0, ``REGWEN`` reads 0 and a write of B
                      leaves A in the target. Control ``CTRL-REGWEN-PRE``: the
                      write of A before the lock reads back A.
  CHK-REGWEN-NOREARM  ``REGWEN`` reads 0 after each of r writes of 1. Control:
                      it reads 0 before the first write of 1.
  CHK-REGWEN-RESET    after a TRNG reset ``REGWEN`` reads 1, the target reads its
                      RDL reset value with no X on the bus, and a write of B
                      lands. Control: ``REGWEN`` reads 0 before the reset.
``INT_STATE_READ_ENABLE`` under the CSRNG ``REGWEN`` is logged only
(``OBS-REGWEN-OWN``).
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_chk_log import SepChkLog
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_field_compare import field_compare
from env.sep_reg_meta import CSRNG, EDN, sym
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_monitor_life import MonitorLife
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq

TEST = "sep_drbg_regwen_lock_rand_test"

# Multi-bit-boolean codes (csrng.adoc and edn.adoc CTRL: kMultiBitBool4True/False).
MUBI_TRUE = 0x6
MUBI_FALSE = 0x9
MUBI = (MUBI_TRUE, MUBI_FALSE)

CSRNG_REGWEN = sym("CSRNG_REGWEN_REG_ADDR")
EDN_REGWEN = sym("EDN_REGWEN_REG_ADDR")
CSRNG_INT_STATE_READ_ENABLE = sym("CSRNG_INT_STATE_READ_ENABLE_REG_ADDR")


@dataclass(frozen=True)
class Target:
    """One locked register: its unit, name, address, field mask, RDL reset value and
    the ``REGWEN`` of its unit."""

    unit: str
    reg: str
    addr: int
    mask: int
    reset: int
    regwen: int
    regwen_mask: int


TARGETS = {
    "csrng_ctrl": Target(
        "csrng",
        "CTRL",
        sym("CSRNG_CTRL_REG_ADDR"),
        CSRNG.mask("CTRL"),
        CSRNG.reset("CTRL"),
        CSRNG_REGWEN,
        CSRNG.mask("REGWEN"),
    ),
    "csrng_fips_force": Target(
        "csrng",
        "FIPS_FORCE",
        sym("CSRNG_FIPS_FORCE_REG_ADDR"),
        CSRNG.mask("FIPS_FORCE"),
        CSRNG.reset("FIPS_FORCE"),
        CSRNG_REGWEN,
        CSRNG.mask("REGWEN"),
    ),
    "edn_ctrl": Target(
        "edn",
        "CTRL",
        sym("EDN_CTRL_REG_ADDR"),
        EDN.mask("CTRL"),
        EDN.reset("CTRL"),
        EDN_REGWEN,
        EDN.mask("REGWEN"),
    ),
}
REGWEN_RESET = {"csrng": CSRNG.reset("REGWEN"), "edn": EDN.reset("REGWEN")}
ISRE_MASK = CSRNG.mask("INT_STATE_READ_ENABLE")
ISRE_RESET = CSRNG.reset("INT_STATE_READ_ENABLE")

# Outer cap of the TRNG reset waits (design rule: 20 x the clean value of the logs).
TRNG_RESET_CAP = 4_000


def _csrng_ctrl(rng: SepSeededRng) -> int:
    """A CSRNG CTRL value: ENABLE False, every other field True or False."""
    return CSRNG.value(
        "CTRL",
        ENABLE=MUBI_FALSE,
        SW_APP_ENABLE=rng.choice(MUBI),
        READ_INT_STATE=rng.choice(MUBI),
        FIPS_FORCE_ENABLE=rng.choice(MUBI),
    )


def _edn_ctrl(rng: SepSeededRng) -> int:
    """An EDN CTRL value: EDN_ENABLE and CMD_FIFO_RST False, the modes True or False."""
    return EDN.value(
        "CTRL",
        EDN_ENABLE=MUBI_FALSE,
        BOOT_REQ_MODE=rng.choice(MUBI),
        AUTO_REQ_MODE=rng.choice(MUBI),
        CMD_FIFO_RST=MUBI_FALSE,
    )


def _fips_force(rng: SepSeededRng) -> int:
    return rng.randrange(1, CSRNG.mask("FIPS_FORCE") + 1)


_DRAW = {"csrng_ctrl": _csrng_ctrl, "csrng_fips_force": _fips_force, "edn_ctrl": _edn_ctrl}


@dataclass(frozen=True)
class TargetPlan:
    key: str
    a: int
    b: int
    isre: int
    rearm: int
    fills: tuple[int, ...]


@dataclass(frozen=True)
class Plan:
    seed: int
    targets: tuple[TargetPlan, ...]

    def describe(self) -> str:
        return " ".join(
            f"{t.key}:a=0x{t.a:x},b=0x{t.b:x},r={t.rearm},isre=0x{t.isre:x}" for t in self.targets
        )


# Writes per target that carry a drawn inactive-lane fill: A, REGWEN=0, B, the
# INT_STATE_READ_ENABLE write, r REGWEN=1 writes (at most 3) and B after the reset.
_FILLS_PER_TARGET = 8


def draw_plan(seed: int) -> Plan:
    """Every draw of the leaf, in a fixed order, with no simulator access."""
    rng = SepSeededRng(seed)
    order = list(TARGETS)
    rng.shuffle(order)
    out = []
    for key in order:
        tgt = TARGETS[key]
        draw = _DRAW[key]
        a = draw(rng)
        while (a & tgt.mask) == (tgt.reset & tgt.mask):
            a = draw(rng)
        b = draw(rng)
        while (b & tgt.mask) in ((tgt.reset & tgt.mask), (a & tgt.mask)):
            b = draw(rng)
        isre = rng.randrange(0, ISRE_MASK + 1)
        while isre == ISRE_RESET:
            isre = rng.randrange(0, ISRE_MASK + 1)
        rearm = rng.randrange(1, 4)
        fills = tuple(rng.getrandbits(32) for _ in range(_FILLS_PER_TARGET))
        out.append(TargetPlan(key, a, b, isre, rearm, fills))
    return Plan(seed, tuple(out))


def _bitstr(sig) -> str:
    """The per-bit string of a signal, MSB first (cocotb 1.x ``binstr``, 2.x ``str``)."""
    value = sig.value
    bits = getattr(value, "binstr", None)
    return (bits if bits is not None else str(value)).strip()


def _known_int(sig) -> int | None:
    bits = _bitstr(sig)
    return int(bits, 2) if bits and all(c in "01" for c in bits) else None


class _ReadXTap:
    """Counts X/Z bits in the read data of 32-bit reads at the graded addresses on ``s_axi``.

    The AXI master converts each R beat to an integer and raises on an X/Z bit, which
    ends the leaf before a check line. The tap samples the bus after each falling clock
    edge, half a clock before the master takes the beat. ARs pair with R beats by ID,
    in order. ``beats`` counts the graded beats, ``unknown`` the graded beats with an
    X/Z bit in the accessed lane.
    """

    def __init__(self, dut, graded: set[int]) -> None:
        names = ("arvalid", "arready", "araddr", "arid", "rvalid", "rready", "rdata", "rid")
        self.sig = {n: getattr(dut, f"s_axi_{n}") for n in names}
        self.graded = graded
        self.clk = 0
        self.beats = 0
        self.unknown = 0
        self.lanes: list[str] = []
        self._pending: dict[int, list[int | None]] = {}
        self.life = MonitorLife("READ-X-TAP s_axi", lambda: self.clk)

    def start(self) -> "_ReadXTap":
        self.life.start(self._run())
        return self

    async def stop(self) -> None:
        await self.life.stop()

    async def _run(self) -> None:
        sig = self.sig
        clk = cocotb.top.clk_i
        while True:
            await FallingEdge(clk)
            await ReadOnly()
            self.clk += 1
            if _known_int(sig["arvalid"]) == 1 and _known_int(sig["arready"]) == 1:
                rid = _known_int(sig["arid"])
                self._pending.setdefault(rid, []).append(_known_int(sig["araddr"]))
            if _known_int(sig["rvalid"]) == 1 and _known_int(sig["rready"]) == 1:
                queue = self._pending.get(_known_int(sig["rid"]))
                if not queue:
                    continue
                addr = queue.pop(0)
                if addr not in self.graded:
                    continue
                self.beats += 1
                bits = _bitstr(sig["rdata"])
                lo = (addr % max(1, len(bits) // 8)) * 8
                lane = bits[len(bits) - lo - 32 : len(bits) - lo]
                if any(c not in "01" for c in lane):
                    self.unknown += 1
                    self.lanes.append(f"0x{addr:08x}:{lane}")


@pyuvm.test()
class sep_drbg_regwen_lock_rand_test(sep_base_test):
    """CSRNG and EDN REGWEN: the lock, no re-arm by a write of 1, and the TRNG reset."""

    required_evidence = (
        "CHK-REGWEN-LOCK",
        "CHK-REGWEN-NOREARM",
        "CHK-REGWEN-RESET",
    )

    async def run_scenario(self) -> None:
        # Baseline 0x20: TRNG released, the Key Manager and every engine held.
        await self.bring_up_no_cpu(park=("otbn", "aes", "hmac", "kmac", "abr"))
        self.logger.info("BASELINE sw_reset_n=0x%02x", self.swrst.value)
        seed = self.random_seed()
        plan = draw_plan(seed)
        self.logger.info("PLAN seed=%d %s", seed, plan.describe())
        self.chk = SepChkLog(self, TEST, seed)
        self._fill: int | None = None
        self._arm_w_channel()
        try:
            for tp in plan.targets:
                await self._target(tp)
        finally:
            close_graded_window(self.logger)
            self._restore_w_channel()
        self.chk.finish()

    # --- bus --------------------------------------------------------------------
    def _arm_w_channel(self) -> None:
        """Put the drawn fill on the inactive lane of the next 32-bit write beat.

        The VIP backend zero-pads the inactive lane. The wrapper replaces those bytes
        on the beat object just before it is queued and keeps WSTRB as is, so the
        strobe covers the register lane only.
        """
        w_channel = self.env.axi_agent.driver.axi.driver.channels["w_delay"]
        self._w_channel = w_channel
        if "send" in vars(w_channel):
            return
        original = w_channel.send

        async def send(beat, _orig=original):
            if self._fill is not None:
                strb = int(beat.wstrb)
                active = 0
                for lane in range(8):
                    if strb >> lane & 1:
                        active |= 0xFF << (8 * lane)
                fill64 = self._fill | (self._fill << 32)
                beat.wdata = (int(beat.wdata) & active) | (fill64 & ~active)
            await _orig(beat)

        w_channel.send = send

    def _restore_w_channel(self) -> None:
        self._fill = None
        if "send" in vars(self._w_channel):
            del self._w_channel.send

    async def _wr(self, addr: int, data: int, fill: int) -> None:
        """One 32-bit write (AxSIZE 2) with ``fill`` on the inactive lane."""
        self._fill = fill
        try:
            seq = SepAxiAccessSeq(
                "regwen_wr", op=SepAxiOp.WRITE, addr=addr, wdata=data, length=4, size=2
            )
            await self.start_seq(seq)
        finally:
            self._fill = None
        if not seq.resp_ok:
            raise AssertionError(f"write @0x{addr:08x} not OKAY (resp={seq.resp_code})")
        self.logger.info("WR 0x%08x data=0x%08x inactive_lane=0x%08x", addr, data, fill)

    async def _rd(self, addr: int) -> int:
        seq = SepAxiAccessSeq("regwen_rd", op=SepAxiOp.READ, addr=addr, length=4, size=2)
        await self.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(f"read @0x{addr:08x} not OKAY (resp={seq.resp_code})")
        return seq.rdata & 0xFFFF_FFFF

    # --- TRNG reset -------------------------------------------------------------
    async def _wait_probe(self, sig, want_zero: bool, what: str) -> int:
        dut = cocotb.top
        for clk in range(TRNG_RESET_CAP):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            v = self.rd(sig, allow_unknown=True)
            if (v == 0) == want_zero:
                return clk
        raise AssertionError(f"{what}: no change within {TRNG_RESET_CAP} clocks")

    async def _trng_reset(self) -> None:
        """Bit 5 of SW_RESET_N to 0 then 1; wait for the reset and the isolation to end.

        No ESRC, CSRNG or EDN access comes between the two writes: the write of 0
        isolates their host paths (``hw/sys/sep/doc/reset_controller.adoc``,
        Isolation and Reset Sequencing).
        """
        dut = cocotb.top
        await self.swrst.park("trng")
        rise = await self._wait_probe(dut.trng_reset_active_probe_o, False, "trng reset rise")
        await RisingEdge(dut.clk_i)
        await self.swrst.release("trng")
        fall = await self._wait_probe(dut.trng_reset_active_probe_o, True, "trng reset fall")
        iso = await self._wait_probe(dut.trng_axi_isolated_probe_o, True, "trng isolation end")
        await ClockCycles(dut.clk_i, 2)
        self.logger.info(
            "TRNG reset: rise_clk=%d fall_clk=%d isolation_end_clk=%d cap=%d",
            rise,
            fall,
            iso,
            TRNG_RESET_CAP,
        )

    # --- one target ---------------------------------------------------------------
    async def _target(self, tp: TargetPlan) -> None:
        t = TARGETS[tp.key]
        rw_mask = t.regwen_mask
        fills = list(tp.fills)
        unit = t.unit
        reg = t.reg

        # Step 3: TRNG reset, REGWEN 1, target at its RDL reset value.
        await self._trng_reset()
        regwen_start = await self._rd(t.regwen)
        start = await self._rd(t.addr)
        # Step 4: the write of A lands (control).
        await self._wr(t.addr, tp.a, fills.pop(0))
        pre = await self._rd(t.addr)
        fc_pre = field_compare(pre, tp.a, t.mask)
        fc_start = field_compare(start, t.reset, t.mask)
        self.chk.ctrl(
            "REGWEN-PRE",
            fc_pre.ok and regwen_start & rw_mask == REGWEN_RESET[unit] and fc_start.ok,
            unit=unit,
            reg=reg,
            wrote=f"0x{tp.a:x}",
            read=f"0x{pre & t.mask:x}",
            rsvd=f"0x{fc_pre.rsvd:x}",
            regwen_start=regwen_start & rw_mask,
            start=f"0x{start & t.mask:x}",
            reset=f"0x{t.reset & t.mask:x}",
        )

        # Step 5: the lock. The graded window opens at the lock write.
        open_graded_window(TEST, self.logger)
        await self._wr(t.regwen, 0, fills.pop(0))
        regwen_locked = await self._rd(t.regwen)
        # Step 6: the write of B under the lock.
        await self._wr(t.addr, tp.b, fills.pop(0))
        kept = await self._rd(t.addr)
        fc_lock = field_compare(kept, tp.a, t.mask)
        self.chk.ok(
            "REGWEN-LOCK",
            regwen_locked & rw_mask == 0 and fc_lock.ok,
            unit=unit,
            reg=reg,
            regwen=regwen_locked & rw_mask,
            kept=f"0x{tp.a:x}",
            tried=f"0x{tp.b:x}",
            read=f"0x{kept & t.mask:x}",
            rsvd=f"0x{fc_lock.rsvd:x}",
        )

        # Step 7: INT_STATE_READ_ENABLE has its own regwen; logged, not graded.
        isre_fill = fills.pop(0)
        if unit == "csrng":
            await self._wr(CSRNG_INT_STATE_READ_ENABLE, tp.isre, isre_fill)
            isre = await self._rd(CSRNG_INT_STATE_READ_ENABLE)
            self.chk.obs(
                "REGWEN-OWN",
                reg="INT_STATE_READ_ENABLE",
                wrote=f"0x{tp.isre:x}",
                read=f"0x{isre & ISRE_MASK:x}",
            )

        # Step 8: r writes of 1 to the cleared REGWEN.
        after: list[int] = []
        for _ in range(tp.rearm):
            await self._wr(t.regwen, rw_mask, fills.pop(0))
            after.append(await self._rd(t.regwen) & rw_mask)
        self.chk.ctrl(
            "REGWEN-NOREARM",
            regwen_locked & rw_mask == 0,
            unit=unit,
            before_first_write1=regwen_locked & rw_mask,
        )
        self.chk.ok(
            "REGWEN-NOREARM",
            all(v == 0 for v in after),
            unit=unit,
            writes=tp.rearm,
            after_write1=max(after),
            reads=after,
        )
        pre_reset_regwen = after[-1]

        # Steps 9-11: the TRNG reset is the graded stimulus; the window stays open.
        tap = _ReadXTap(cocotb.top, {t.regwen, t.addr}).start()
        await self._trng_reset()
        regwen_after = await self._rd(t.regwen)
        target_after = await self._rd(t.addr)
        await tap.stop()
        close_graded_window(self.logger)
        post_fill = tp.fills[_FILLS_PER_TARGET - 1]
        await self._wr(t.addr, tp.b, post_fill)
        landed = await self._rd(t.addr)
        fc_reset = field_compare(target_after, t.reset, t.mask)
        fc_land = field_compare(landed, tp.b, t.mask)
        x_free = int(tap.unknown == 0)
        self.chk.ctrl(
            "REGWEN-RESET",
            pre_reset_regwen == 0 and tap.beats >= 2,
            unit=unit,
            regwen_before_reset=pre_reset_regwen,
            graded_read_beats=tap.beats,
        )
        self.chk.ok(
            "REGWEN-RESET",
            regwen_after & rw_mask == REGWEN_RESET[unit] and fc_reset.ok and x_free and fc_land.ok,
            unit=unit,
            regwen=regwen_after & rw_mask,
            reg=f"0x{target_after & t.mask:x}",
            reset=f"0x{t.reset & t.mask:x}",
            rsvd=f"0x{fc_reset.rsvd:x}",
            post_write_lands=int(fc_land.ok),
            wrote=f"0x{tp.b:x}",
            read=f"0x{landed & t.mask:x}",
            x_free=x_free,
            x_lanes=tap.lanes or "none",
        )
