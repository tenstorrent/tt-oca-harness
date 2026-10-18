# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ESRC read-only registers, the TRNG-reset restore, the MODULE_ENABLE lock and INTR_STATUS.

Contract (``hw/ip/entropy_source/regs/gen/adoc/entropy_source.adoc``, golden lines cited
per check; ``hw/ip/entropy_source/doc/architecture.adoc:220-223``, Reset):
  * A write of the complement of the value read to a read-only ESRC register leaves its
    field bits unchanged (access R, for example ``COMPONENT_ID``, :91-95) and answers
    OKAY or SLVERR; a DECERR means the write reached no block
    (``hw/sys/sep/doc/crypto.adoc:174-176``).
  * A TRNG reset is a full-IP reset: every unlocked read-write field outside ``CTRL``
    reads its RDL reset value after it (architecture.adoc:220-223).
  * Once ``FIPS_LOCK.LOCK`` is set (:752), a write of ``CTRL.MODULE_ENABLE`` = 0 is
    ignored (:112): ``MAIN_SM_STATUS.IDLE`` (:412) reads 0 and ``FIFO_STATUS.LEVEL``
    (:235) rises after a drain. Without the lock the same write stops the module.
  * With the eight defined ``INTR_ENABLE`` bits set, the eight ``INTR_STATUS`` bits equal
    the ``INTR_TEST`` mask, are independent of each other and clear on write-one; a
    write to ``INTR_TEST`` leaves ``INTR_ENABLE`` unchanged (:128-148, :152-172,
    :176-196).

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense``, ``+esrc_noise_force``.
``SW_RESET_N`` baseline 0x20: the TRNG is released, the Key Manager and every engine
are held. The noise model drives ``balanced`` on all 12 lanes from before the first
TRNG reset release to the end of the leaf.

Register lists come from the generated register export and the RDL text at run time:
the read-only leg takes every register whose fields are all read-only, except the
FIFO data ports; the restore leg takes every stored read-write field (no RDL write or
read side effect such as ``woclr``, and not written by hardware alone) whose RDL text
lacks "FIPS_LOCK.LOCK prevents software changes", outside ``CTRL``.
``HEALTH_TEST_CTRL.ENABLE`` lacks the phrase and is walked as unlocked
(``OBS-LOCK-LIST``). The read-write status and alert latches that hardware sets
(``INTR_STATUS``, ``*_HEALTH_STATUS``, ``MAIN_SM_STATUS.ALERT``/``ERR``) are not
stored configuration; the restore leg logs their non-zero fields before and after
the reset as ``OBS-ESRC-VOLATILE`` and grades none of them.

Randomization (``SepSeededRng`` from the run seed, drawn before the first stimulus):
the ``balanced`` masks and permutation, the order of the read-only leg and of the
restore leg, the restore value v1 of each field (it differs from the reset value;
``HT_WATERMARK_NUM`` takes 1 to 4, ``NOISE_OBS_CTRL.LANE_SEL`` takes 1 to 11), the
order of the two ``MODULE_ENABLE`` trials, the enable mask E and the test mask T (each
with a 0 and a 1 over the eight defined bits; T holds ``FIFO_OVERFLOW`` and
``FIFO_UNDERFLOW`` and one more bit), the bit i of the one-bit control (a set bit of T)
and the clear subset C (holds bits 8 and 12, a proper subset of T).

Checkers:
  CHK-ESRC-RO       field bits after the complement write equal the first read and
                    the write answers OKAY or SLVERR, per written register. Control: at least one register and
                    ``COMPONENT_ID`` are written.
  CHK-ESRC-RESTORE  each restore field reads its RDL reset value after the TRNG reset;
                    VCS: no readback bit of a field is X. Control: the walked restore
                    fields are exactly the 12 the contract names (``CONTRACT_RESTORE``)
                    and each reads its written v1 before the reset.
  CHK-LOCK-MEN      locked trial: ``IDLE`` = 0 and ``LEVEL`` > 0 within 2 t_ref after a
                    drain and the write of 0. Control: the unlocked trial of the same
                    seed reads ``IDLE`` = 1 and an empty FIFO for 2 t_ref after
                    ``SHA256_STATUS.BUSY`` (:209) reads 0 and a drain.
  CHK-ESRC-INTR     zero corner status 0; all-ones status = all defined bits; drawn T
                    status = T; after the clear of C status = T & ~C; ``INTR_ENABLE``
                    reads as written (all ones, E, ~E) before and after each clear.
                    Control: the one-bit control reads exactly bit i.
The status of a drawn enable mask is logged (``OBS-STATUS-E``), not graded: the
register text does not state whether a status bit latches with its enable clear.
t_ref is the clocks from the end of a drain to the 24th word of the entropy stream
(``esrc_compress_vld_o``); with whitening on a digest gives 8 stream words
(architecture.adoc:142), so 24 words span two whole digest periods.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import ReadOnly, RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_bit_watch import SepBitWatch
from env.sep_chk_log import SepChkLog
from env.sep_esrc_pattern_noise import Balanced, SepEsrcPatternNoise, balanced_lanes, describe
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_seeded_rng import SepSeededRng
from env.sep_trial_wait import TrialTimeout, poll_until, wait_until
from sep_base_test import sep_base_test
from sep_reg_meta import ENTROPY_SOURCE, reg_sw_readonly, sym
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_esrc_clean_start_seq import (
    LATENCY_FACTOR,
    SepEsrcCleanStart,
    SepEsrcLeafSetup,
)

TEST = "sep_esrc_csr_rw_walk_rand_test"

BASELINE_PARK = ("otbn", "aes", "hmac", "kmac", "abr")
RDL = Path(__file__).resolve().parents[7] / "hw/ip/entropy_source/regs/entropy_source.rdl"
LOCK_PHRASE = "FIPS_LOCK.LOCK prevents software changes"

# Excluded from both legs (contract step 2): the FIFO data ports, the trigger and the
# lock register. NOISE_OBS_CTRL.FLUSH is a pulse field, so it is not read-write.
DATA_PORTS = frozenset({"FIFO_RDATA", "BIW_OBS_RDATA", "NOISE_OBS_RDATA"})
NOT_WALKED = DATA_PORTS | {"INTR_TEST", "FIPS_LOCK", "CTRL"}
# The restore fields the contract names (Test Procedure step 1), by RDL register and field
# name (``hw/ip/entropy_source/regs/entropy_source.rdl``: INTR_ENABLE :168-210,
# HEALTH_TEST_CTRL :309, HEALTH_TEST_WINDOW_SIZE :325, HT_WATERMARK_NUM :799,
# NOISE_OBS_CTRL :1028). The run-time walk must give exactly this set.
CONTRACT_RESTORE = frozenset(
    {
        ("INTR_ENABLE", "HEALTH_TEST_FAILED"),
        ("INTR_ENABLE", "FIFO_ERROR"),
        ("INTR_ENABLE", "FIFO_OVERFLOW"),
        ("INTR_ENABLE", "FIFO_UNDERFLOW"),
        ("INTR_ENABLE", "PERSISTENT_FAILURE"),
        ("INTR_ENABLE", "AUTOTUNE_FAIL"),
        ("INTR_ENABLE", "BIW_OBS_OVERFLOW"),
        ("INTR_ENABLE", "NOISE_OBS_OVERFLOW"),
        ("HEALTH_TEST_CTRL", "ENABLE"),
        ("HEALTH_TEST_WINDOW_SIZE", "SIZE"),
        ("HT_WATERMARK_NUM", "WATERMARK_NUM"),
        ("NOISE_OBS_CTRL", "LANE_SEL"),
    }
)
# Restore-value draws with a stated legal range (contract, Randomization).
V1_RANGE = {
    ("HT_WATERMARK_NUM", "WATERMARK_NUM"): (1, 5),
    ("NOISE_OBS_CTRL", "LANE_SEL"): (1, 12),
}

WINDOW = 2048
T_REF_WORDS = 24
IDLE_CAP = 4_000  # outer limit of the first IDLE poll (clocks)
DRAIN_CAP = 20_000  # outer limit of the first FIFO drain (clocks)
RESP_NAME = {0: "okay", 1: "exokay", 2: "slverr", 3: "decerr"}
RESP_ACCEPTED = (0, 2)  # okay, slverr


def _addr(reg: str) -> int:
    return sym(f"ENTROPY_SOURCE_{reg}_REG_ADDR")


def _fmeta(reg: str, field: str) -> dict[str, int]:
    return ENTROPY_SOURCE.fields(reg)[field]


def _fget(reg: str, field: str, value: int) -> int:
    m = _fmeta(reg, field)
    return (value & m["bm"]) >> m["bp"]


def _fmask(reg: str, field: str) -> int:
    return _fmeta(reg, field)["bm"]


# INTR_STATUS / INTR_ENABLE / INTR_TEST share one bit layout (entropy_source.adoc:128-196).
INTR_FIELDS = tuple(
    sorted(ENTROPY_SOURCE.fields("INTR_STATUS"), key=lambda f: _fmeta("INTR_STATUS", f)["bp"])
)
INTR_BITS = tuple(_fmeta("INTR_STATUS", f)["bp"] for f in INTR_FIELDS)
INTR_DEF = ENTROPY_SOURCE.mask("INTR_STATUS")
INTR_KEEP = (
    INTR_BITS.index(_fmeta("INTR_STATUS", "FIFO_OVERFLOW")["bp"]),
    INTR_BITS.index(_fmeta("INTR_STATUS", "FIFO_UNDERFLOW")["bp"]),
)
FULL8 = (1 << len(INTR_BITS)) - 1


def intr_value(mask8: int) -> int:
    """Register value of an 8-bit index mask over the defined interrupt bits."""
    return sum(1 << INTR_BITS[j] for j in range(len(INTR_BITS)) if (mask8 >> j) & 1)


# RDL write and read side effects: a field with one of them is not a stored read-write
# field (contract step 1: not RW1C, RW1S, W1C or W1P).
SIDE_EFFECT = re.compile(r"\b(onwrite|onread|singlepulse|woclr|woset|rclr|rset)\b")


def _rdl_field_text() -> dict[tuple[str, str], tuple[str, str, bool, str]]:
    """(reg, field) -> (sw access, desc, has a side effect, hw access) from the RDL text."""
    text = RDL.read_text(encoding="utf-8")
    out: dict[tuple[str, str], tuple[str, str, bool, str]] = {}
    for reg in re.finditer(r"\breg\s+(\w+)\s*\{(.*?)\n\s*\}\s*;", text, re.S):
        for fld in re.finditer(r"field\s*\{(.*?)\}\s*(\w+)\s*\[", reg.group(2), re.S):
            body = fld.group(1)
            desc = re.search(r'desc\s*=\s*"(.*?)"\s*;', body, re.S)
            sw = re.search(r"\bsw\s*=\s*(\w+)", body)
            hw = re.search(r"\bhw\s*=\s*(\w+)", body)
            out[(reg.group(1), fld.group(2))] = (
                sw.group(1) if sw else "",
                desc.group(1) if desc else "",
                SIDE_EFFECT.search(body) is not None,
                hw.group(1) if hw else "",
            )
    if not out:
        raise RuntimeError(f"{RDL}: no field parsed")
    return out


@dataclass(frozen=True)
class RestoreField:
    reg: str
    field: str
    reset: int
    v1: int

    @property
    def name(self) -> str:
        return f"{self.reg}.{self.field}"


def register_lists() -> tuple[
    tuple[str, ...], tuple[tuple[str, str, int, int], ...], int, tuple[tuple[str, str], ...]
]:
    """(read-only registers, restore fields (reg, field, width, reset), locked-list size,
    volatile fields).

    A restore field is a stored read-write field: sw = rw, no RDL side effect, hardware
    does not write it alone (hw is not ``w``), outside the locked list and outside
    ``NOT_WALKED``. A volatile field is an sw = rw field outside ``NOT_WALKED`` that
    hardware updates or software clears by write-one (status and alert latches); the
    restore leg reads it as ``OBS-ESRC-VOLATILE`` only (contract step 2).
    """
    ro = tuple(sorted(reg_sw_readonly("entropy_source") - DATA_PORTS))
    rdl = _rdl_field_text()
    locked = sum(1 for (_r, _f), (_sw, desc, _se, _hw) in rdl.items() if LOCK_PHRASE in desc)
    restore: list[tuple[str, str, int, int]] = []
    volatile: list[tuple[str, str]] = []
    for (reg, field), (sw, desc, side_effect, hw) in sorted(rdl.items()):
        if reg in NOT_WALKED or sw != "rw" or LOCK_PHRASE in desc:
            continue
        if side_effect or hw == "w":
            volatile.append((reg, field))
            continue
        m = _fmeta(reg, field)
        restore.append((reg, field, m["bw"], m["reset"]))
    return ro, tuple(restore), locked, tuple(volatile)


@dataclass(frozen=True)
class Plan:
    seed: int
    balanced: tuple[Balanced, ...]
    ro_order: tuple[str, ...]
    restore: tuple[RestoreField, ...]
    volatile: tuple[tuple[str, str], ...]
    trial_order: tuple[str, ...]
    e8: int
    t8: int
    i_bit: int
    c8: int
    locked_count: int

    def describe(self) -> str:
        return (
            f"ro_order={','.join(self.ro_order)} "
            f"restore={','.join(f'{f.name}=0x{f.v1:x}' for f in self.restore)} "
            f"trials={','.join(self.trial_order)} E=0x{intr_value(self.e8):08x} "
            f"T=0x{intr_value(self.t8):08x} i={INTR_BITS[self.i_bit]} "
            f"C=0x{intr_value(self.c8):08x} {describe(self.balanced)}"
        )


def _mixed8(rng: SepSeededRng) -> int:
    while True:
        v = rng.getrandbits(len(INTR_BITS))
        if v not in (0, FULL8):
            return v


def draw_plan(seed: int) -> Plan:
    """Every draw of the leaf, in a fixed order, with no simulator access."""
    rng = SepSeededRng(seed)
    balanced = tuple(balanced_lanes(rng))
    ro, restore_meta, locked, volatile = register_lists()
    ro_order = list(ro)
    rng.shuffle(ro_order)
    fields: list[RestoreField] = []
    for reg, field, width, reset in restore_meta:
        lo_hi = V1_RANGE.get((reg, field))
        while True:
            v1 = rng.randrange(*lo_hi) if lo_hi else rng.getrandbits(width)
            if v1 != reset:
                break
        fields.append(RestoreField(reg, field, reset, v1))
    rng.shuffle(fields)
    trials = ["locked", "unlocked"]
    rng.shuffle(trials)
    e8 = _mixed8(rng)
    keep = (1 << INTR_KEEP[0]) | (1 << INTR_KEEP[1])
    while True:
        t8 = _mixed8(rng)
        if t8 & keep == keep and (t8 & ~keep) != 0:
            break
    i_bit = rng.choice([j for j in range(len(INTR_BITS)) if (t8 >> j) & 1])
    others = t8 & ~keep
    while True:
        c8 = keep | (rng.getrandbits(len(INTR_BITS)) & others)
        if c8 != t8:
            break
    return Plan(
        seed,
        balanced,
        tuple(ro_order),
        tuple(fields),
        volatile,
        tuple(trials),
        e8,
        t8,
        i_bit,
        c8,
        locked,
    )


class _Esrc(SepAxiRegDriver):
    _DRIVER_TAG = "ESRC"


@pyuvm.test()
class sep_esrc_csr_rw_walk_rand_test(sep_base_test):
    """ESRC read-only writes, TRNG-reset restore, the MODULE_ENABLE lock, INTR_STATUS."""

    required_evidence = (
        "CHK-ESRC-RO",
        "CHK-ESRC-RESTORE",
        "CHK-LOCK-MEN",
        "CHK-ESRC-INTR",
    )

    async def run_scenario(self) -> None:
        dut = cocotb.top
        await self.bring_up_no_cpu(park=BASELINE_PARK)
        self.logger.info("BASELINE sw_reset_n=0x%02x", self.swrst.value)
        seed = self.random_seed()
        plan = draw_plan(seed)
        self.logger.info("PLAN seed=%d %s", seed, plan.describe())
        self.plan = plan
        self.chk = SepChkLog(self, TEST, seed)
        self.esrc = _Esrc(self)
        self.clk = SepBitWatch(dut.rst_ni, {"rst_ni": 0}, name="clk_count").start()
        self.stream = SepBitWatch(dut.esrc_compress_vld_o, name="esrc_compress_vld_o").start()
        self.four_state = "verilator" not in str(getattr(cocotb, "SIM_NAME", "") or "").lower()
        self.rbeats: list = []
        self._rmon = cocotb.start_soon(self._r_monitor()) if self.four_state else None
        self.t_idle: int | None = None
        self.t_drain: int | None = None
        self.p: int | None = None

        self.chk.obs("LOCK-COUNT", locked_fields=plan.locked_count)
        self.chk.obs("LOCK-LIST", field="HEALTH_TEST_CTRL.ENABLE", walked="unlocked")
        self.logger.info(
            "WALK ro=%s restore=%s",
            ",".join(sorted(plan.ro_order)),
            ",".join(sorted(f.name for f in plan.restore)),
        )

        # Noise runs from before the first TRNG reset release (the testers run from it).
        self.noise = SepEsrcPatternNoise(logger=self.logger)
        self.noise.start(plan.balanced)
        self.setup = SepEsrcLeafSetup(self, self.swrst, self.noise)

        await self._trng_reset()
        await self._quiet_state()
        await self._ro_leg()
        await self._intr_leg()
        await self._restore_leg()
        await self._enable_trials()

        close_graded_window(self.logger)
        if self._rmon is not None:
            self._rmon.kill()
        await self.stream.stop()
        await self.noise.stop()
        await self.clk.stop()
        self.chk.finish()

    # --- bus, probes and waits --------------------------------------------------
    def _now(self) -> int:
        return self.clk.clk

    async def _rd(self, reg: str) -> int:
        return await self.esrc._rd(_addr(reg))

    async def _wr(self, reg: str, value: int) -> None:
        await self.esrc._wr(_addr(reg), value)

    async def _r_monitor(self) -> None:
        """Every R beat of the CPU-LSU master as sampled (four-state X check)."""
        dut = cocotb.top
        while True:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if dut.s_axi_rvalid.value == 1 and dut.s_axi_rready.value == 1:
                self.rbeats.append(dut.s_axi_rdata.value)

    async def _rd_x(self, reg: str) -> tuple[int, bool]:
        """Read ``reg``; on a four-state simulator also return whether its field bits are known."""
        n0 = len(self.rbeats)
        value = await self._rd(reg)
        if not self.four_state:
            return value, True
        await RisingEdge(cocotb.top.clk_i)
        if len(self.rbeats) <= n0:
            return value, False
        bits = self.rbeats[n0].binstr
        addr = _addr(reg)
        lane = bits[-64:][:32] if addr & 0x4 else bits[-32:]
        mask = ENTROPY_SOURCE.mask(reg)
        known = all(c in "01" for k, c in enumerate(reversed(lane)) if (mask >> k) & 1)
        return value, known

    async def _trng_reset(self) -> int:
        """TRNG bit 0 then 1 at baseline 0x20 (SepEsrcLeafSetup). Returns the mark."""
        return await self.setup.trng_reset()

    async def _poll(self, reg: str, mask: int, want: int, bound: int):
        return await poll_until(lambda: self._rd(reg), self._now, mask, want, bound)

    async def _idle(self, what: str) -> int:
        """Poll MAIN_SM_STATUS.IDLE = 1; returns the clocks; raises TrialTimeout."""
        bound = IDLE_CAP if self.t_idle is None else LATENCY_FACTOR * self.t_idle
        t0 = self._now()
        idle = _fmask("MAIN_SM_STATUS", "IDLE")
        await wait_until(lambda: self._rd("MAIN_SM_STATUS"), self._now, idle, idle, bound, what)
        t = max(1, self._now() - t0)
        if self.t_idle is None:
            self.t_idle = t
        self.logger.info("IDLE %s clk=%d clean=%d bound=%d", what, t, self.t_idle, bound)
        return t

    async def _level(self) -> int:
        return _fget("FIFO_STATUS", "LEVEL", await self._rd("FIFO_STATUS"))

    async def _drain(self, what: str) -> int:
        """Pop FIFO_RDATA until LEVEL reads 0. Returns the pops; raises TrialTimeout."""
        bound = DRAIN_CAP if self.t_drain is None else LATENCY_FACTOR * self.t_drain
        t0 = self._now()
        pops = 0
        while True:
            lvl = await self._level()
            if lvl == 0:
                break
            if self._now() - t0 > bound:
                raise TrialTimeout(f"drain:{what}", bound)
            for _ in range(lvl):
                await self._rd("FIFO_RDATA")
                pops += 1
        if self.t_drain is None:
            self.t_drain = max(1, self._now() - t0)
        return pops

    def _ctrl_word(self, module_enable: int) -> int:
        return ENTROPY_SOURCE.value("CTRL", MODULE_ENABLE=module_enable)

    # --- quiet state --------------------------------------------------------------
    async def _quiet_state(self) -> None:
        await self._wr("RING_OSC_ENABLE", ENTROPY_SOURCE.value("RING_OSC_ENABLE", ENABLE=0))
        await self._wr("CTRL", self._ctrl_word(0))
        try:
            await self._idle("quiet")
        except TrialTimeout as exc:
            raise AssertionError(f"{TEST}: quiet state IDLE not 1 bound={exc.bound}") from exc

    # --- read-only leg --------------------------------------------------------------
    async def _write_resp(self, reg: str, value: int) -> int:
        seq = SepAxiAccessSeq(
            "esrc_ro_wr",
            op=SepAxiOp.WRITE,
            addr=_addr(reg),
            wdata=value,
            length=4,
            size=2,
            allow_unverified_write_resp=True,
        )
        await self.start_seq(seq)
        return seq.resp_code

    async def _ro_leg(self) -> None:
        open_graded_window(TEST, self.logger)
        rows: list[dict] = []
        for reg in self.plan.ro_order:
            mask = ENTROPY_SOURCE.mask(reg)
            r1 = await self._rd(reg)
            r2 = await self._rd(reg)
            if (r1 ^ r2) & mask:
                self.chk.obs("RO-DYNAMIC", reg=reg, read1=f"0x{r1:08x}", read2=f"0x{r2:08x}")
                continue
            wrote = ~r1 & 0xFFFF_FFFF
            resp = await self._write_resp(reg, wrote)
            r3 = await self._rd(reg)
            self.chk.obs("RO-RESP", reg=reg, resp=RESP_NAME.get(resp, str(resp)))
            if r3 & ~mask & 0xFFFF_FFFF:
                self.chk.obs("RO-RSVD", reg=reg, rsvd=f"0x{r3 & ~mask & 0xFFFF_FFFF:08x}")
            rows.append(
                {
                    "reg": reg,
                    "wrote": wrote,
                    "first": r1,
                    "read": r3,
                    "mask": mask,
                    "unchanged": (r3 & mask) == (r1 & mask),
                    "resp": resp,
                }
            )
        close_graded_window(self.logger)
        written = len(rows)
        comp = any(r["reg"] == "COMPONENT_ID" for r in rows)
        self.chk.ctrl(
            "ESRC-RO", written >= 1 and comp, written_regs=written, component_id_written=comp
        )
        # The register text states no response code for the write, so OKAY and SLVERR
        # both pass. DECERR is the crypto demux answer for an access that reaches no
        # block (hw/sys/sep/doc/crypto.adoc:174-176), and an unchanged readback after
        # it proves nothing; any code other than OKAY or SLVERR fails.
        for r in rows:
            resp_ok = r["resp"] in RESP_ACCEPTED
            self.chk.ok(
                "ESRC-RO",
                r["unchanged"] and resp_ok,
                reg=r["reg"],
                resp=RESP_NAME.get(r["resp"], str(r["resp"])),
                wrote=f"0x{r['wrote']:08x}",
                read=f"0x{r['read']:08x}",
                first=f"0x{r['first']:08x}",
                field_mask=f"0x{r['mask']:08x}",
                unchanged=r["unchanged"],
                written_regs=written,
            )

    # --- interrupt leg ------------------------------------------------------------------
    async def _status(self) -> int:
        return await self._rd("INTR_STATUS")

    async def _enable(self) -> int:
        return await self._rd("INTR_ENABLE")

    async def _w1c(self, value: int) -> int:
        await self._wr("INTR_STATUS", value)
        return await self._status()

    async def _intr_leg(self) -> None:
        dut = cocotb.top
        plan = self.plan
        d = INTR_DEF
        rsvd: list[int] = []

        def f(v: int) -> int:
            rsvd.append(v & ~d & 0xFFFF_FFFF)
            return v & d

        # Clean-up before the corners.
        clean = f(await self._w1c(d))
        self.chk.ctrl("INTR-CLEAN", clean == 0, status=f"0x{clean:08x}")

        open_graded_window(TEST, self.logger)
        # Zero corner: quiet state, enable 0, test 0.
        await self._wr("INTR_ENABLE", 0)
        await self._wr("INTR_TEST", 0)
        zero_st = f(await self._status())
        zero_en = f(await self._enable())
        # All-ones corner.
        await self._wr("INTR_ENABLE", d)
        await self._wr("INTR_TEST", d)
        ones_st = f(await self._status())
        ones_en = f(await self._enable())
        ones_after = f(await self._w1c(d))
        ones_en_after = f(await self._enable())
        close_graded_window(self.logger)

        # One-bit control (fills no bin).
        bit_i = 1 << INTR_BITS[plan.i_bit]
        await self._wr("INTR_ENABLE", d)
        await self._wr("INTR_TEST", bit_i)
        one_st = f(await self._status())
        one_en = f(await self._enable())
        one_after = f(await self._w1c(bit_i))
        self.chk.ctrl(
            "INTR-ONEBIT",
            one_st == bit_i and one_en == d and one_after == 0,
            bit=INTR_BITS[plan.i_bit],
            status=f"0x{one_st:08x}",
            enable_rb=f"0x{one_en:08x}",
            after_w1c=f"0x{one_after:08x}",
        )

        open_graded_window(TEST, self.logger)
        # Drawn enable mask: (E, T), then (~E, all ones).
        e_val = intr_value(plan.e8)
        t_val = intr_value(plan.t8)
        e_runs = ((e_val, t_val), (d & ~e_val, d))
        e_ok = True
        e_rb: list[int] = []
        pic16 = []
        for en, te in e_runs:
            await self._wr("INTR_ENABLE", en)
            await self._wr("INTR_TEST", te)
            st = f(await self._status())
            rb = f(await self._enable())
            p = self.rd(dut.sep_internal_interrupts_probe_o, allow_unknown=True)
            pic16.append((p >> 15) & 1)
            self.chk.obs("STATUS-E", enable=f"0x{en:08x}", test=f"0x{te:08x}", status=f"0x{st:08x}")
            self.chk.obs("PIC16", enable=f"0x{en:08x}", vector_bit15=(p >> 15) & 1)
            after = f(await self._w1c(d))
            rb_after = f(await self._enable())
            e_rb.append(rb)
            e_ok = e_ok and rb == en and rb_after == en and after == 0
        # Drawn test mask with all enables set, then the clear of the proper subset C.
        await self._wr("INTR_ENABLE", d)
        await self._wr("INTR_TEST", t_val)
        t_st = f(await self._status())
        t_en = f(await self._enable())
        c_val = intr_value(plan.c8)
        c_st = f(await self._w1c(c_val))
        c_en = f(await self._enable())
        final = f(await self._w1c(d))
        close_graded_window(self.logger)

        ok = (
            zero_st == 0
            and zero_en == 0
            and ones_st == d
            and ones_en == d
            and ones_after == 0
            and ones_en_after == d
            and e_ok
            and t_st == t_val
            and t_en == d
            and c_st == (t_val & ~c_val)
            and c_en == d
            and final == 0
        )
        self.chk.ok(
            "ESRC-INTR",
            ok,
            zero_corner_status=f"0x{zero_st:x}",
            zero_enable_rb=f"0x{zero_en:x}",
            all_ones_status=f"0x{ones_st:08x}",
            all_ones_enable_rb=f"0x{ones_en:08x}",
            all_ones_after_w1c=f"0x{ones_after:x}",
            test=f"0x{t_val:08x}",
            status=f"0x{t_st:08x}",
            enable_rb=f"0x{t_en:08x}",
            drawn_enable=f"0x{e_val:08x}",
            drawn_enable_rb=f"0x{e_rb[0]:08x}",
            compl_enable_rb=f"0x{e_rb[1]:08x}",
            clear=f"0x{c_val:08x}",
            after_w1c=f"0x{c_st:08x}",
            expect_after_w1c=f"0x{t_val & ~c_val:08x}",
            final_status=f"0x{final:x}",
            ctrl_single_bit=f"0x{one_st:08x}",
            pic16=pic16,
            rsvd=f"0x{max(rsvd) if rsvd else 0:x}",
        )

    # --- restore leg ----------------------------------------------------------------------
    async def _read_fields(self) -> tuple[dict[str, int], int]:
        """Each restore field as read; the count of field reads with an X bit (four-state)."""
        values: dict[str, int] = {}
        x_regs = 0
        for reg in sorted({f.reg for f in self.plan.restore}):
            v, known = await self._rd_x(reg)
            x_regs += 0 if known else 1
            for fld in self.plan.restore:
                if fld.reg == reg:
                    values[fld.name] = _fget(reg, fld.field, v)
        return values, x_regs

    async def _read_volatile(self) -> str:
        """The non-zero volatile fields as ``reg.field=0xV`` (logged only, never graded)."""
        out: list[str] = []
        for reg in sorted({r for r, _f in self.plan.volatile}):
            v = await self._rd(reg)
            for r, fld in self.plan.volatile:
                if r == reg and _fget(reg, fld, v):
                    out.append(f"{reg}.{fld}=0x{_fget(reg, fld, v):x}")
        return ",".join(out)

    async def _restore_leg(self) -> None:
        plan = self.plan
        for fld in plan.restore:
            cur = await self._rd(fld.reg)
            m = _fmeta(fld.reg, fld.field)
            new = ((cur & ~m["bm"]) | ((fld.v1 << m["bp"]) & m["bm"])) & ENTROPY_SOURCE.mask(
                fld.reg
            )
            await self._wr(fld.reg, new)
        # The arming read: the window stays open through the first read after the reset.
        open_graded_window(TEST, self.logger)
        pre, _ = await self._read_fields()
        pre_bad = [f.name for f in plan.restore if pre[f.name] != f.v1]
        vol_pre = await self._read_volatile()
        await self._trng_reset()
        post, x_regs = await self._read_fields()
        close_graded_window(self.logger)
        vol_post = await self._read_volatile()
        self.chk.obs(
            "ESRC-VOLATILE",
            fields=len(plan.volatile),
            pre=vol_pre or "none",
            post=vol_post or "none",
        )
        post_bad = [
            f"{f.name}=0x{post[f.name]:x}/0x{f.reset:x}"
            for f in plan.restore
            if post[f.name] != f.reset
        ]
        walked = {(f.reg, f.field) for f in plan.restore}
        missing = sorted(f"{r}.{f}" for r, f in CONTRACT_RESTORE - walked)
        extra = sorted(f"{r}.{f}" for r, f in walked - CONTRACT_RESTORE)
        set_ok = not missing and not extra and len(plan.restore) == len(CONTRACT_RESTORE)
        self.chk.ctrl(
            "ESRC-RESTORE",
            not pre_bad and set_ok,
            fields=len(plan.restore),
            expected_fields=len(CONTRACT_RESTORE),
            missing=",".join(missing) or "none",
            extra=",".join(extra) or "none",
            pre_mismatch=",".join(pre_bad) or "none",
        )
        self.chk.ok(
            "ESRC-RESTORE",
            not post_bad and x_regs == 0 and set_ok,
            fields=len(plan.restore),
            expected_fields=len(CONTRACT_RESTORE),
            pre="v1",
            post="reset",
            mismatches=len(post_bad),
            field=",".join(post_bad) or "none",
            x_free=("1" if x_regs == 0 else "0") if self.four_state else "na",
        )
        # Back to the quiet state for the trials (each trial starts with its own reset).
        await self._quiet_state()

    # --- MODULE_ENABLE trials -----------------------------------------------------------
    async def _start_trial(self) -> int:
        """Reset, clean start, BOOT_PHASE_DONE, drain, t_ref. Returns t_ref in clocks."""
        mark = await self._trng_reset()
        cs = SepEsrcCleanStart(self, self.noise, self.plan.balanced, window=WINDOW)
        await cs.run(release_mark=mark)
        self.p = await self.setup.measure_period(self.chk)
        await self.setup.wait_boot_done(self.esrc, WINDOW)
        await self._drain("t_ref")
        t0 = self._now()
        m = self.stream.mark()
        t_cap = 1024 * self.p
        # The level read takes clocks, so the watcher has a sample after the mark at
        # the first count.
        while True:
            if self._now() - t0 > t_cap:
                raise AssertionError(f"{TEST}: {T_REF_WORDS} stream words not seen bound={t_cap}")
            lvl = await self._level()
            for _ in range(lvl):
                await self._rd("FIFO_RDATA")
            if self.stream.high_clocks_since(m) >= T_REF_WORDS:
                break
        t_ref = max(1, self._now() - t0)
        self.logger.info("T-REF clk=%d words=%d bound=%d", t_ref, T_REF_WORDS, t_cap)
        return t_ref

    async def _enable_trials(self) -> None:
        res: dict[str, dict] = {}
        for trial in self.plan.trial_order:
            t_ref = await self._start_trial()
            if trial == "locked":
                res[trial] = await self._locked_trial(t_ref)
            else:
                res[trial] = await self._unlocked_trial(t_ref)
        lk, ul = res["locked"], res["unlocked"]
        self.chk.ctrl(
            "LOCK-MEN",
            ul["ok"],
            ctrl_idle_unlocked=ul.get("idle"),
            ctrl_busy_polled=ul.get("busy0"),
            ctrl_level_after_drain=ul.get("level_max"),
            t_ref=ul["t_ref"],
            reason=ul.get("reason", "none"),
        )
        self.chk.ok(
            "LOCK-MEN",
            lk["ok"],
            t_ref=lk["t_ref"],
            lock_rb=lk.get("lock_rb"),
            idle_locked=lk.get("idle"),
            level_after_drain=lk.get("level"),
            bound=2 * lk["t_ref"],
            ctrl_idle_unlocked=ul.get("idle"),
            ctrl_level_after_drain=ul.get("level_max"),
            reason=lk.get("reason", "none"),
        )

    async def _locked_trial(self, t_ref: int) -> dict:
        out: dict = {"t_ref": t_ref, "ok": False}
        try:
            await self._wr("FIPS_LOCK", ENTROPY_SOURCE.value("FIPS_LOCK", LOCK=1))
            out["lock_rb"] = _fget("FIPS_LOCK", "LOCK", await self._rd("FIPS_LOCK"))
            await self._drain("locked")
            open_graded_window(TEST, self.logger)
            await self._wr("CTRL", self._ctrl_word(0))
            t0 = self._now()
            rose = False
            lvl = 0
            while self._now() - t0 <= 2 * t_ref:
                lvl = await self._level()
                if lvl > 0:
                    rose = True
                    break
            out["level"] = lvl
            out["idle"] = _fget("MAIN_SM_STATUS", "IDLE", await self._rd("MAIN_SM_STATUS"))
            close_graded_window(self.logger)
            if not rose:
                out["reason"] = f"timeout:level bound={2 * t_ref}"
            out["ok"] = rose and out["idle"] == 0 and out["lock_rb"] == 1
        except TrialTimeout as exc:
            close_graded_window(self.logger)
            out["reason"] = f"timeout:{exc.what} bound={exc.bound}"
        return out

    async def _unlocked_trial(self, t_ref: int) -> dict:
        out: dict = {"t_ref": t_ref, "ok": False}
        try:
            await self._drain("unlocked")
            await self._wr("CTRL", self._ctrl_word(0))
            await self._idle("unlocked")
            out["idle"] = 1
            busy = _fmask("SHA256_STATUS", "BUSY")
            await wait_until(
                lambda: self._rd("SHA256_STATUS"), self._now, busy, 0, 2 * t_ref, "busy0"
            )
            out["busy0"] = 1
            await self._drain("unlocked_hold")
            t0 = self._now()
            level_max = 0
            polls = 0
            while self._now() - t0 <= 2 * t_ref:
                level_max = max(level_max, await self._level())
                polls += 1
            out["level_max"] = level_max
            out["polls"] = polls
            out["ok"] = level_max == 0 and polls > 0
        except TrialTimeout as exc:
            out["reason"] = f"timeout:{exc.what} bound={exc.bound}"
        return out
