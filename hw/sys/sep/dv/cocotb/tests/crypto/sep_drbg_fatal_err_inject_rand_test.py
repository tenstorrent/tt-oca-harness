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
  * ``CTRL.CMD_FIFO_RST`` True clears both command FIFOs (edn.adoc:98-101).
  * ``RESEED_CMD`` and ``GENERATE_CMD`` take up to 13 words; a 14th sets
    ``SFIFO_RESCMD_ERR`` or ``SFIFO_GENCMD_ERR``, ``edn_fatal_err`` and a fatal
    alert (edn.adoc:225, :232, :241, :249, :318, :323), and ``FIFO_WRITE_ERR``,
    the type bit of a write to a full FIFO (edn.adoc:305). The drop of the 14th
    word is not graded: no register reads the FIFO level or contents.

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense``,
``+esrc_noise_force``. ``SW_RESET_N`` baseline 0x20. Each trial pulses the TRNG
reset, brings up ESRC and CSRNG (``seq_lib/sep_drbg_mode_bringup_seq.py``) and
enables EDN in software-port mode, so no command consumes the EDN command FIFOs.
The interrupt vector probe ``sep_internal_interrupts_probe_o`` is watched on
every ``clk_i``.

Randomization (``SepSeededRng`` from the run seed, drawn before the first
stimulus): the order of the 12 source-bit cells, the order of the two FIFO
trials, the extra word count e (2 to 12) of each FIFO, the test data words, the
count k (1 to 12) of words each FIFO holds before the clear and those words.

Checkers:
  CHK-DRBG-ERRCODE  the forced bit sets; the fatal state is 1 (CSRNG all, EDN 0 and 1)
                    and the vector bit reads 0 after the enable write and rises after
                    the ERR_CODE_TEST write. Control: ERR_CODE and state 0 before.
  CHK-DRBG-ALERT    vector bit 32 is high for at least one clock after the write and
                    0 before it, for the fatal-alert sources.
  CHK-DRBG-STICKY   after a write-one clear of the state the source bit stays (all but
                    EDN 0); the FIFO-error cells read the state 0 after the clear.
  CHK-DRBG-RESET    ERR_CODE reads 0 after a TRNG reset. Control: non-zero before.
  CHK-EDN-FIFO13    the FIFO holds k words, then a CTRL.CMD_FIFO_RST pulse
                    (edn.adoc:98-101), then 1, e and 13 words: ERR_CODE 0, INTR_STATE 0,
                    vector bits 28 and 32 low. A clear that keeps the k words errs at
                    word 14 - k, at or before the 13-word read. Control: ERR_CODE 0
                    with the k words held, before the clear.
  CHK-EDN-FIFO14    the 14th word: ERR_CODE equals the FIFO error bit plus
                    FIFO_WRITE_ERR, INTR_STATE equals edn_fatal_err, vector bit 28 high
                    and at least one clock of vector bit 32.
Every ERR_CODE compare uses the field bits of the register text; the Reserved
bits are logged as ``rsvd``.

FCOV (owner of the graded window, ``env/sep_fcov_gate.py``): each source-bit
cell and each FIFO trial opens the window after its set-up and sets the pass
label ``drbg_fatal_pass`` only after every check of that step passed; the
sampler holds the cells of the step until then. The first FAIL closes the
window, and no later step opens it.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, NextTimeStep, ReadOnly, RisingEdge
from env.sep_bit_watch import SepBitWatch
from env.sep_chk_log import SepChkLog
from env.sep_fcov_gate import close_graded_window, open_graded_window, set_drbg_fatal_pass
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
EDN_CTRL_FIFO_RST = EDN.value(
    "CTRL",
    EDN_ENABLE=_MUBI_TRUE,
    BOOT_REQ_MODE=_MUBI_FALSE,
    AUTO_REQ_MODE=_MUBI_FALSE,
    CMD_FIFO_RST=_MUBI_TRUE,
)
EDN_CTRL_ADDR = sym("EDN_CTRL_REG_ADDR")


def _bits(block, *names: str) -> tuple[int, ...]:
    """Bit positions of the named ``ERR_CODE`` fields, from the generated register map."""
    fields = block.fields("ERR_CODE")
    return tuple(fields[n]["bp"] for n in names)


# ERR_CODE type bits (FIFO_WRITE_ERR, FIFO_READ_ERR, FIFO_STATE_ERR); the source
# bits are every bit below the lowest type bit.
_TYPE_NAMES = ("FIFO_WRITE_ERR", "FIFO_READ_ERR", "FIFO_STATE_ERR")
TYPE_BITS = sum(1 << b for b in _bits(EDN, *_TYPE_NAMES))
SOURCE_BITS = (1 << min(_bits(EDN, *_TYPE_NAMES))) - 1
# Source bits per unit: the FIFO errors, and the sources that signal a fatal alert
# (csrng.adoc:381-407; edn.adoc:309-322).
CSRNG_FIFO_BITS = _bits(CSRNG, "SFIFO_CMD_ERR", "SFIFO_GENBITS_ERR")
CSRNG_ALERT_BITS = _bits(
    CSRNG, "CMD_STAGE_SM_ERR", "MAIN_SM_ERR", "CTR_DRBG_SM_ERR", "AES_CIPHER_SM_ERR", "CTR_ERR"
)
EDN_FIFO_BITS = _bits(EDN, "SFIFO_RESCMD_ERR", "SFIFO_GENCMD_ERR")
EDN_ALERT_BITS = _bits(EDN, "EDN_ACK_SM_ERR", "EDN_MAIN_SM_ERR", "EDN_CNTR_ERR")


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
    fifo_bits: tuple[int, ...]

    @property
    def cells(self) -> tuple[int, ...]:
        return tuple(sorted(self.fifo_bits + self.alert_bits))

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
        CSRNG_ALERT_BITS,
        CSRNG_FIFO_BITS,
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
        EDN_ALERT_BITS,
        EDN_FIFO_BITS,
    ),
}
# ERR_CODE after the 14th word: the FIFO source bit and the full-FIFO write type
# bit (edn.adoc:305, :318-326).
EDN_FIFO_WRITE_ERR = EDN.fields("ERR_CODE")["FIFO_WRITE_ERR"]["bm"]
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
    pre: dict
    pre_words: dict

    def describe(self) -> str:
        cells = ",".join(f"{u}:{b}" for u, b in self.cells)
        words = " ".join(
            f"{f}_words={[f'0x{w:08x}' for w in self.words[f]]}" for f in self.fifo_order
        )
        pre = " ".join(
            f"{f}_held={[f'0x{w:08x}' for w in self.pre_words[f]]}" for f in self.fifo_order
        )
        return (
            f"cells={cells} fifo_order={','.join(self.fifo_order)} "
            f"e_reseed={self.extra['reseed']} e_generate={self.extra['generate']} "
            f"fatal_enable=1 {words} k_reseed={self.pre['reseed']} "
            f"k_generate={self.pre['generate']} {pre}"
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
    pre = {f: rng.randrange(1, FIFO_WORDS) for f in FIFO_TRIALS}
    pre_words: dict[str, tuple[int, ...]] = {}
    for f in FIFO_TRIALS:
        held: list[int] = []
        while len(held) < pre[f]:
            w = rng.getrandbits(32)
            if w not in used:
                used.add(w)
                held.append(w)
        pre_words[f] = tuple(held)
    return Plan(seed, tuple(cells), tuple(fifo_order), extra, words, pre, pre_words)


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
        set_drbg_fatal_pass(False, self.logger)
        self._stop_sb()
        await self.vec.stop()
        self.chk.finish()

    # --- graded window and pass label ---------------------------------------------
    def _open_window(self) -> None:
        """Open the window of the leaf unless a check or control already failed."""
        if self.chk.failures == 0:
            open_graded_window(TEST, self.logger)

    def _ok(self, name: str, cond: bool, **fields) -> bool:
        """Grade one check; a FAIL is recorded, then the window closes."""
        res = self.chk.ok(name, cond, **fields)
        if not cond:
            close_graded_window(self.logger)
        return res

    def _ctrl(self, name: str, cond: bool, **fields) -> bool:
        """Log one control; an absent control is recorded, then the window closes."""
        res = self.chk.ctrl(name, cond, **fields)
        if not cond:
            close_graded_window(self.logger)
        return res

    async def _release(self) -> None:
        """Pulse the pass label after every check of the step passed, then close."""
        if self.chk.failures == 0:
            set_drbg_fatal_pass(True, self.logger)
            await ClockCycles(cocotb.top.clk_i, 2)
            set_drbg_fatal_pass(False, self.logger)
        close_graded_window(self.logger)

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
        self._ctrl(
            "DRBG-RESET",
            (before & unit.err_mask) != 0,
            unit=unit.name,
            **key,
            err_code_before=f"0x{before & unit.err_mask:08x}",
        )
        await self._trng_reset()
        after = await self._rd(unit.err_code)
        self._ok(
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
        self._open_window()
        vec_key = unit.vec_key
        fifo_bit = bit in unit.fifo_bits
        alert_src = bit in unit.alert_bits
        state_graded = unit.name == "csrng" or fifo_bit
        src = 1 << bit

        err0 = await self._rd(unit.err_code)
        st0 = await self._rd(unit.intr_state)
        m_watch = self.vec.mark()
        await self._wr(unit.intr_enable, unit.fatal_bm)
        pre_alert_clocks = self.vec.high_clocks_since(m_watch, "alert")
        pre_level = self.vec.level("alert")
        # The vector bit of the unit reads 0 with the fatal enable set and the state
        # clear, so a rise after the forced error is a change the error causes.
        vec_pre = self.vec.level(vec_key)
        m_err = self.vec.mark()
        await self._wr(unit.err_code_test, unit.block.value("ERR_CODE_TEST", ERR_CODE_TEST=bit))
        set_ok, err, bound = await self._wait_err_bit(unit, src)
        st = await self._rd(unit.intr_state)
        en = await self._rd(unit.intr_enable)
        fatal_state = int(bool(st & unit.fatal_bm))
        enabled = int(bool(en & unit.fatal_bm))
        vec_level = self.vec.level(vec_key)
        vec_rose = int(self.vec.rises_since(m_err, vec_key) >= 1)
        other = err & unit.err_mask & SOURCE_BITS & ~src
        typ = err & unit.err_mask & TYPE_BITS

        pre_ok = (err0 & unit.err_mask) == 0 and (st0 & unit.fatal_bm) == 0
        self._ctrl(
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
            "enable": enabled,
            "vec": vec_level,
            "vec_pre": vec_pre,
            "vec_rose": vec_rose,
            "state_graded": int(state_graded),
        }
        if not set_ok:
            fields["reason"] = f"timeout:err_code bound={bound}"
        graded = (
            set_ok
            and enabled == 1
            and (
                not state_graded
                or (fatal_state == 1 and vec_pre == 0 and vec_rose == 1 and vec_level == 1)
            )
        )
        self._ok("DRBG-ERRCODE", graded, **fields)

        # Sticky leg (step 8).
        s_before = int(bool(await self._rd(unit.intr_state) & unit.fatal_bm))
        await self._wr(unit.intr_state, unit.fatal_bm)
        s_after = int(bool(await self._rd(unit.intr_state) & unit.fatal_bm))
        err2 = await self._rd(unit.err_code)
        kept = int(bool(err2 & src))
        alert_cycles = self.vec.high_clocks_since(m_err, "alert")

        if alert_src:
            pre = pre_alert_clocks + (pre_level or 0)
            self._ctrl("DRBG-ALERT", pre == 0, unit=unit.name, bit=bit, pre=pre)
            self._ok(
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
            self._ctrl("DRBG-STICKY", s_before == 1, unit=unit.name, bit=bit, state_before=s_before)
        else:
            self.chk.obs(
                "DRBG-STATE-AFTER-W1C", unit=unit.name, bit=bit, before=s_before, after=s_after
            )
        edn0 = unit.name == "edn" and bit == 0
        if edn0:
            self.chk.obs("EDN-STICKY0", **self._err_fields(unit, err2))
        sticky = (edn0 or kept == 1) and (not fifo_bit or s_after == 0)
        self._ok(
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
        await self._release()

    # --- EDN command FIFO trials (steps 10-13) -----------------------------------------
    async def _fifo_trial(self, fifo: str) -> None:
        plan = self.plan
        unit = UNITS["edn"]
        addr, err_meta = EDN_CMD_FIFO[fifo]
        words = plan.words[fifo]
        e = plan.extra[fifo]
        k = plan.pre[fifo]
        await self._setup()
        # The FIFO holds k words (1 to 12) before the clear. CMD_FIFO_RST True clears
        # both command FIFOs, and software returns it to its reset state before the
        # next command word (edn.adoc:98-101), so the FIFO takes 13 words after the
        # clear and errs on the 14th. A FIFO that keeps the k words errs at word 14 - k.
        for w in plan.pre_words[fifo]:
            await self._wr(addr, w)
        held = await self._rd(unit.err_code)
        self._ctrl(
            "EDN-FIFO-HELD",
            (held & unit.err_mask) == 0,
            fifo=fifo,
            held_before_clear=k,
            **self._err_fields(unit, held),
        )
        self._open_window()
        await self._wr(EDN_CTRL_ADDR, EDN_CTRL_FIFO_RST)
        await self._wr(EDN_CTRL_ADDR, EDN_CTRL_SW_PORT)
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
            self._ok(
                "EDN-FIFO13",
                ok,
                fifo=fifo,
                held_before_clear=k,
                words=n,
                **self._err_fields(unit, err),
                intr_state=f"0x{st & unit.state_mask:x}",
                vec28_high_cycles=hi28,
                vec32_high_cycles=hi32,
            )
        m14 = self.vec.mark()
        await self._wr(addr, words[FIFO_WORDS])
        # The graded ERR_CODE value is the first read that shows the FIFO source bit.
        set_ok, err, bound = await self._wait_err_bit(unit, err_meta["bm"])
        st = await self._rd(unit.intr_state)
        vec28 = self.vec.level("edn_fatal")
        alert = self.vec.high_clocks_since(m14, "alert")
        want_err = err_meta["bm"] | EDN_FIFO_WRITE_ERR
        self._ctrl("EDN-FIFO14", ok13, fifo=fifo, ctrl_fifo13_ok=ok13)
        fields = {
            "fifo": fifo,
            "held_before_clear": k,
            "words": FIFO_WORDS + 1,
            **self._err_fields(unit, err),
            "err_code_expected": f"0x{want_err:08x}",
            "intr_state": f"0x{st & unit.state_mask:x}",
            "intr_state_expected": f"0x{unit.fatal_bm:x}",
            "vec28": vec28,
            "alert_cycles": alert,
        }
        if not set_ok:
            fields["reason"] = f"timeout:err_code bound={bound}"
        self._ok(
            "EDN-FIFO14",
            set_ok
            and (err & unit.err_mask) == want_err
            and (st & unit.state_mask) == unit.fatal_bm
            and vec28 == 1
            and alert >= 1,
            **fields,
        )
        await self._reset_leg(unit, trial=f"fifo_{fifo}")
        await self._release()
