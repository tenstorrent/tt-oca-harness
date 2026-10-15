# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Forced CSRNG and EDN errors, their interrupt and alert, and the EDN command FIFO limit.

Contract (``vendor/lowRISC/opentitan/overlay/regs/csrng/regs/gen/adoc/csrng.adoc`` and
``vendor/lowRISC/opentitan/overlay/regs/edn/regs/gen/adoc/edn.adoc``, ``INTR_STATE``,
``ERR_CODE``, ``ERR_CODE_TEST``, ``RESEED_CMD``, ``GENERATE_CMD``;
``hw/sys/sep/doc/interrupts.adoc``; ``hw/sys/sep/doc/crypto.adoc``):
  * A write of a defined source bit number to ``ERR_CODE_TEST`` forces that error
    (csrng.adoc:417-422; edn.adoc:336). The ``ERR_CODE`` source bit stays set until
    reset, except EDN bit 0, whose text does not say so (csrng.adoc:382-407;
    edn.adoc:310-322).
  * CSRNG sets ``CS_FATAL_ERR`` for a FIFO error or a fatal alert (csrng.adoc:47);
    EDN sets ``edn_fatal_err`` for a FIFO error (edn.adoc:41). Both clear by
    write-one. CSRNG fatal error is vector bit 26 and EDN fatal error vector bit 28
    (interrupts.adoc:153-155, :161-163).
  * The sources that "signal a fatal alert" (CSRNG 20, 21, 22, 25, 26; EDN 20, 21,
    22) pulse the Crypto alert, vector bit 32 (csrng.adoc:381-396; edn.adoc:309-315;
    crypto.adoc:151; interrupts.adoc:177-178).
  * A TRNG reset clears ``ERR_CODE`` (hw/ip/entropy_source/doc/architecture.adoc:219-223).
  * ``RESEED_CMD`` and ``GENERATE_CMD`` take up to 13 words; a 14th is ignored and
    sets ``SFIFO_RESCMD_ERR`` or ``SFIFO_GENCMD_ERR``, ``edn_fatal_err`` and a fatal
    alert (edn.adoc:225, :232, :241, :249, :318, :323).

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense``,
``+esrc_noise_force``. ``SW_RESET_N`` baseline 0x20. Each trial pulses the TRNG
reset, brings up ESRC and CSRNG (``seq_lib/sep_drbg_mode_bringup_seq.py``) and
enables EDN in software-port mode, so no command consumes the EDN command FIFOs.
The interrupt vector probe ``sep_internal_interrupts_probe_o`` is watched on
every ``clk_i``.

Randomization (``SepSeededRng`` from the run seed, drawn before the first
stimulus): the order of the 12 source-bit cells, the order of the two FIFO
trials, the extra word count e (2 to 12) of each FIFO and the test data words.

Checkers:
  CHK-DRBG-ERRCODE  the forced bit sets; the fatal state is 1 (CSRNG all, EDN 0 and 1)
                    and reaches the vector bit. Control: ERR_CODE and state 0 before.
  CHK-DRBG-ALERT    vector bit 32 is high for at least one clock after the write and
                    0 before it, for the fatal-alert sources.
  CHK-DRBG-STICKY   after a write-one clear of the state the source bit stays (all but
                    EDN 0); the FIFO-error cells read the state 0 after the clear.
  CHK-DRBG-RESET    ERR_CODE reads 0 after a TRNG reset. Control: non-zero before.
  CHK-EDN-FIFO13    1, e and 13 words: ERR_CODE 0, INTR_STATE 0, vector bits 28 and 32 low.
  CHK-EDN-FIFO14    the 14th word: the FIFO error bit, edn_fatal_err, vector bit 28 and
                    at least one clock of vector bit 32.
Every ERR_CODE compare uses the field bits of the register text; the Reserved
bits are logged as ``rsvd``.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge
from env.sep_bit_watch import SepBitWatch
from env.sep_chk_log import SepChkLog
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import CSRNG, EDN, sym
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_drbg_mode_bringup_seq import drbg_bring_up

TEST = "sep_drbg_fatal_err_inject_rand_test"

PARK = ("otbn", "aes", "hmac", "kmac", "abr")
TRNG_RELEASE_CAP = 4_000
LAT_FACTOR = 16
FIFO_WORDS = 13  # edn.adoc:225, :241
FIFO_BITS = (0, 1)
FIFO_TRIALS = ("reseed", "generate")

# Multi-bit booleans: the RDL resets EDN CTRL fields to kMultiBitBool4False (0x9);
# kMultiBitBool4True is its complement over the 4-bit field (0x6).
_MUBI_FALSE = EDN.fields("CTRL")["EDN_ENABLE"]["reset"]
_MUBI_TRUE = (~_MUBI_FALSE) & ((1 << EDN.fields("CTRL")["EDN_ENABLE"]["bw"]) - 1)
# Software-port mode: BOOT_REQ_MODE, AUTO_REQ_MODE and CMD_FIFO_RST False.
EDN_CTRL_SW_PORT = EDN.value(
    "CTRL",
    EDN_ENABLE=_MUBI_TRUE,
    BOOT_REQ_MODE=_MUBI_FALSE,
    AUTO_REQ_MODE=_MUBI_FALSE,
    CMD_FIFO_RST=_MUBI_FALSE,
)

TYPE_BITS = 0x7 << 28  # ERR_CODE bits 28 to 30: the error type bits
SOURCE_BITS = (1 << 28) - 1


@dataclass(frozen=True)
class Unit:
    name: str
    block: object
    err_code: int
    err_code_test: int
    intr_state: int
    intr_enable: int
    fatal_bm: int
    vec_key: str
    alert_bits: tuple[int, ...]
    cells: tuple[int, ...]

    @property
    def err_mask(self) -> int:
        return self.block.mask("ERR_CODE")

    @property
    def state_mask(self) -> int:
        return self.block.mask("INTR_STATE")


UNITS = {
    "csrng": Unit(
        "csrng",
        CSRNG,
        sym("CSRNG_ERR_CODE_REG_ADDR"),
        sym("CSRNG_ERR_CODE_TEST_REG_ADDR"),
        sym("CSRNG_INTR_STATE_REG_ADDR"),
        sym("CSRNG_INTR_ENABLE_REG_ADDR"),
        CSRNG.fields("INTR_STATE")["CS_FATAL_ERR"]["bm"],
        "cs_fatal",
        (20, 21, 22, 25, 26),
        (0, 1, 20, 21, 22, 25, 26),
    ),
    "edn": Unit(
        "edn",
        EDN,
        sym("EDN_ERR_CODE_REG_ADDR"),
        sym("EDN_ERR_CODE_TEST_REG_ADDR"),
        sym("EDN_INTR_STATE_REG_ADDR"),
        sym("EDN_INTR_ENABLE_REG_ADDR"),
        EDN.fields("INTR_STATE")["EDN_FATAL_ERR"]["bm"],
        "edn_fatal",
        (20, 21, 22),
        (0, 1, 20, 21, 22),
    ),
}
EDN_CMD_FIFO = {
    "reseed": (sym("EDN_RESEED_CMD_REG_ADDR"), EDN.fields("ERR_CODE")["SFIFO_RESCMD_ERR"]),
    "generate": (sym("EDN_GENERATE_CMD_REG_ADDR"), EDN.fields("ERR_CODE")["SFIFO_GENCMD_ERR"]),
}
# interrupts.adoc: source N is vector bit N-1; CSRNG fatal error 27, EDN fatal
# error 29, Crypto alert 33.
VEC_BITS = {"cs_fatal": 26, "edn_fatal": 28, "alert": 32}


@dataclass(frozen=True)
class Plan:
    seed: int
    cells: tuple[tuple[str, int], ...]
    fifo_order: tuple[str, ...]
    extra: dict
    words: dict

    def describe(self) -> str:
        cells = ",".join(f"{u}:{b}" for u, b in self.cells)
        words = " ".join(
            f"{f}_words={[f'0x{w:08x}' for w in self.words[f]]}" for f in self.fifo_order
        )
        return (
            f"cells={cells} fifo_order={','.join(self.fifo_order)} "
            f"e_reseed={self.extra['reseed']} e_generate={self.extra['generate']} "
            f"fatal_enable=1 {words}"
        )


def draw_plan(seed: int) -> Plan:
    """Every draw of the leaf, in a fixed order, with no simulator access."""
    rng = SepSeededRng(seed)
    cells = [(u, b) for u in ("csrng", "edn") for b in UNITS[u].cells]
    rng.shuffle(cells)
    fifo_order = list(FIFO_TRIALS)
    rng.shuffle(fifo_order)
    extra = {f: rng.randrange(2, FIFO_WORDS) for f in FIFO_TRIALS}
    used: set[int] = set()
    words: dict[str, tuple[int, ...]] = {}
    for f in FIFO_TRIALS:
        out: list[int] = []
        while len(out) < FIFO_WORDS + 1:
            w = rng.getrandbits(32)
            if w not in used:
                used.add(w)
                out.append(w)
        words[f] = tuple(out)
    return Plan(seed, tuple(cells), tuple(fifo_order), extra, words)


class _DrbgRegs(SepAxiRegDriver):
    _DRIVER_TAG = "DRBG"


@pyuvm.test()
class sep_drbg_fatal_err_inject_rand_test(sep_base_test):
    """Forced CSRNG/EDN error sources and the EDN command FIFO limit."""

    required_evidence = (
        "CHK-DRBG-ERRCODE",
        "CHK-DRBG-ALERT",
        "CHK-DRBG-STICKY",
        "CHK-DRBG-RESET",
        "CHK-EDN-FIFO13",
        "CHK-EDN-FIFO14",
    )

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu(park=PARK)
        seed = self.random_seed()
        plan = draw_plan(seed)
        self.logger.info("PLAN seed=%d %s", seed, plan.describe())
        self.plan = plan
        self.chk = SepChkLog(self, TEST, seed)
        self.regs = _DrbgRegs(self)
        self.sb = None
        self.t_ref = 1
        self.logger.info("BASELINE sw_reset_n=0x%02x", self.swrst.value)
        self.vec = SepBitWatch(
            cocotb.top.sep_internal_interrupts_probe_o, dict(VEC_BITS), name="pic_vec"
        ).start()

        for unit, bit in plan.cells:
            await self._cell(UNITS[unit], bit)
        for fifo in plan.fifo_order:
            await self._fifo_trial(fifo)
        close_graded_window(self.logger)
        self._stop_sb()
        await self.vec.stop()
        self.chk.finish()

    # --- bus, clocks and set-up ---------------------------------------------------
    async def _wr(self, addr: int, data: int) -> None:
        await self.regs._wr(addr, data)

    async def _rd(self, addr: int) -> int:
        return await self.regs._rd(addr)

    def _now(self) -> int:
        return self.vec.clk

    def _stop_sb(self) -> None:
        if self.sb is not None:
            self.sb.stop()
            self.sb = None

    async def _wait_probe(self, cond, bound: int) -> bool:
        for _ in range(bound):
            await RisingEdge(cocotb.top.clk_i)
            await ReadOnly()
            if cond():
                await NextTimeStep()
                return True
        await NextTimeStep()
        return False

    async def _trng_reset(self) -> None:
        """TRNG reset 0 then 1 on SW_RESET_N bit 5, with the probes of the release."""
        dut = cocotb.top
        self._stop_sb()
        await self.swrst.park("trng")
        if not await self._wait_probe(
            lambda: self.rd(dut.trng_reset_active_probe_o, mask=1) == 1, TRNG_RELEASE_CAP
        ):
            raise AssertionError(f"TRNG reset not active bound={TRNG_RELEASE_CAP}")
        await self.swrst.release("trng")
        if not await self._wait_probe(
            lambda: (
                self.rd(dut.trng_reset_active_probe_o, mask=1) == 0
                and self.rd(dut.trng_axi_isolated_probe_o) == 0
            ),
            TRNG_RELEASE_CAP,
        ):
            raise AssertionError(f"TRNG reset release not seen bound={TRNG_RELEASE_CAP}")

    async def _setup(self) -> None:
        close_graded_window(self.logger)
        await self._trng_reset()
        self.sb = await drbg_bring_up(self, edn_ctrl=EDN_CTRL_SW_PORT, strict=False)
        t0 = self._now()
        await self._rd(UNITS["csrng"].err_code)
        self.t_ref = max(1, self._now() - t0)
        self.logger.info("T-REF t_ref=%d bound=%d", self.t_ref, LAT_FACTOR * self.t_ref)

    async def _wait_err_bit(self, unit: Unit, bit_mask: int) -> tuple[bool, int, int]:
        """Read ERR_CODE until ``bit_mask`` is set, at most 16 x t_ref clocks."""
        bound = LAT_FACTOR * self.t_ref
        t0 = self._now()
        value = 0
        for _ in range(bound + 1):
            value = await self._rd(unit.err_code)
            if value & bit_mask:
                return True, value, bound
            if self._now() - t0 > bound:
                break
        return False, value, bound

    @staticmethod
    def _err_fields(unit: Unit, value: int) -> dict:
        return {
            "err_code": f"0x{value & unit.err_mask:08x}",
            "rsvd": f"0x{value & ~unit.err_mask & 0xFFFF_FFFF:08x}",
        }

    async def _reset_leg(self, unit: Unit, **key) -> None:
        before = await self._rd(unit.err_code)
        self.chk.ctrl(
            "DRBG-RESET",
            (before & unit.err_mask) != 0,
            unit=unit.name,
            **key,
            err_code_before=f"0x{before & unit.err_mask:08x}",
        )
        await self._trng_reset()
        after = await self._rd(unit.err_code)
        self.chk.ok(
            "DRBG-RESET",
            (after & unit.err_mask) == 0,
            unit=unit.name,
            **key,
            after_trng_reset=1,
            **self._err_fields(unit, after),
        )

    # --- source-bit cells (steps 3-8) -------------------------------------------------
    async def _cell(self, unit: Unit, bit: int) -> None:
        await self._setup()
        open_graded_window(TEST, self.logger)
        vec_key = unit.vec_key
        fifo_bit = bit in FIFO_BITS
        alert_src = bit in unit.alert_bits
        state_graded = unit.name == "csrng" or fifo_bit
        src = 1 << bit

        err0 = await self._rd(unit.err_code)
        st0 = await self._rd(unit.intr_state)
        m_watch = self.vec.mark()
        await self._wr(unit.intr_enable, unit.fatal_bm)
        pre_alert_clocks = self.vec.high_clocks_since(m_watch, "alert")
        pre_level = self.vec.level("alert")
        m_err = self.vec.mark()
        await self._wr(unit.err_code_test, unit.block.value("ERR_CODE_TEST", ERR_CODE_TEST=bit))
        set_ok, err, bound = await self._wait_err_bit(unit, src)
        st = await self._rd(unit.intr_state)
        en = await self._rd(unit.intr_enable)
        fatal_state = int(bool(st & unit.fatal_bm))
        vec_level = self.vec.level(vec_key)
        other = err & unit.err_mask & SOURCE_BITS & ~src
        typ = err & unit.err_mask & TYPE_BITS

        pre_ok = (err0 & unit.err_mask) == 0 and (st0 & unit.fatal_bm) == 0
        self.chk.ctrl(
            "DRBG-ERRCODE",
            pre_ok,
            unit=unit.name,
            bit=bit,
            err_code_before=f"0x{err0 & unit.err_mask:08x}",
            fatal_state_before=int(bool(st0 & unit.fatal_bm)),
        )
        fields = {
            "unit": unit.name,
            "bit": bit,
            **self._err_fields(unit, err),
            "source_bit_set": int(bool(err & src)),
            "OBS-other-src": f"0x{other:08x}",
            "OBS-type": f"0x{typ:08x}",
            "fatal_state": fatal_state,
            "enable": int(bool(en & unit.fatal_bm)),
            "vec": vec_level,
            "state_graded": int(state_graded),
        }
        if not set_ok:
            fields["reason"] = f"timeout:err_code bound={bound}"
        graded = set_ok and (not state_graded or (fatal_state == 1 and vec_level == 1))
        self.chk.ok("DRBG-ERRCODE", graded, **fields)

        # Sticky leg (step 8).
        s_before = int(bool(await self._rd(unit.intr_state) & unit.fatal_bm))
        await self._wr(unit.intr_state, unit.fatal_bm)
        s_after = int(bool(await self._rd(unit.intr_state) & unit.fatal_bm))
        err2 = await self._rd(unit.err_code)
        kept = int(bool(err2 & src))
        alert_cycles = self.vec.high_clocks_since(m_err, "alert")

        if alert_src:
            pre = pre_alert_clocks + (pre_level or 0)
            self.chk.ctrl("DRBG-ALERT", pre == 0, unit=unit.name, bit=bit, pre=pre)
            self.chk.ok(
                "DRBG-ALERT",
                pre == 0 and alert_cycles >= 1,
                unit=unit.name,
                bit=bit,
                pic33_high_cycles=alert_cycles,
                pre=pre,
                t_ref=self.t_ref,
            )
        else:
            self.chk.obs("DRBG-ALERT", unit=unit.name, bit=bit, pic33_high_cycles=alert_cycles)

        if fifo_bit:
            self.chk.ctrl("DRBG-STICKY", s_before == 1, unit=unit.name, bit=bit, state_before=1)
        else:
            self.chk.obs(
                "DRBG-STATE-AFTER-W1C", unit=unit.name, bit=bit, before=s_before, after=s_after
            )
        edn0 = unit.name == "edn" and bit == 0
        if edn0:
            self.chk.obs("EDN-STICKY0", **self._err_fields(unit, err2))
        sticky = (edn0 or kept == 1) and (not fifo_bit or s_after == 0)
        self.chk.ok(
            "DRBG-STICKY",
            set_ok and sticky,
            unit=unit.name,
            bit=bit,
            after_w1c=1,
            **self._err_fields(unit, err2),
            source_bit_kept="na" if edn0 else kept,
            state_graded=int(fifo_bit),
            fatal_state=s_after,
        )

        # Reset leg (step 9).
        await self._reset_leg(unit, bit=bit)
        close_graded_window(self.logger)

    # --- EDN command FIFO trials (steps 10-13) -----------------------------------------
    async def _fifo_trial(self, fifo: str) -> None:
        plan = self.plan
        unit = UNITS["edn"]
        addr, err_meta = EDN_CMD_FIFO[fifo]
        words = plan.words[fifo]
        e = plan.extra[fifo]
        await self._setup()
        open_graded_window(TEST, self.logger)
        await self._wr(unit.intr_enable, unit.fatal_bm)
        m = self.vec.mark()
        n = 0
        ok13 = True
        for target in (1, e, FIFO_WORDS):
            while n < target:
                await self._wr(addr, words[n])
                n += 1
            err = await self._rd(unit.err_code)
            st = await self._rd(unit.intr_state)
            hi28 = self.vec.high_clocks_since(m, "edn_fatal")
            hi32 = self.vec.high_clocks_since(m, "alert")
            ok = (err & unit.err_mask) == 0 and (st & unit.state_mask) == 0 and hi28 == hi32 == 0
            ok13 = ok13 and ok
            self.chk.ok(
                "EDN-FIFO13",
                ok,
                fifo=fifo,
                words=n,
                **self._err_fields(unit, err),
                intr_state=f"0x{st & unit.state_mask:x}",
                vec28_high_cycles=hi28,
                vec32_high_cycles=hi32,
            )
        m14 = self.vec.mark()
        await self._wr(addr, words[FIFO_WORDS])
        set_ok, err, bound = await self._wait_err_bit(unit, err_meta["bm"])
        st = await self._rd(unit.intr_state)
        fatal = int(bool(st & unit.fatal_bm))
        vec28 = self.vec.level("edn_fatal")
        alert = self.vec.high_clocks_since(m14, "alert")
        self.chk.ctrl("EDN-FIFO14", ok13, fifo=fifo, ctrl_fifo13_ok=ok13)
        fields = {
            "fifo": fifo,
            "words": FIFO_WORDS + 1,
            **self._err_fields(unit, err),
            "fifo_err_bit": err_meta["bp"],
            "fatal_intr": fatal,
            "vec28": vec28,
            "alert_cycles": alert,
        }
        if not set_ok:
            fields["reason"] = f"timeout:err_code bound={bound}"
        self.chk.ok("EDN-FIFO14", set_ok and fatal == 1 and vec28 == 1 and alert >= 1, **fields)
        await self._reset_leg(unit, trial=f"fifo_{fifo}")
        close_graded_window(self.logger)
