# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shadowed-register update errors, the AES AUX lock and reset, and malformed crypto alerts.

Contract:
  * Two different writes to AES CTRL_SHADOWED set
    STATUS.ALERT_RECOV_CTRL_UPDATE_ERR and a recoverable alert, leave
    ALERT_FATAL_FAULT at 0, and the unit restarts when the register is written
    again (``vendor/lowRISC/opentitan/upstream/hw/ip/aes/data/aes.hjson``,
    CTRL_SHADOWED and ``recov_ctrl_update_err``). An equal pair commits and
    raises no alert.
  * AES CTRL_AUX_SHADOWED: "This register is shadowed, meaning two subsequent
    write operations are required to change its content. If the two write
    operations try to set a different value, a recoverable alert is triggered
    (See Status Register)." (``vendor/lowRISC/opentitan/upstream/hw/ip/aes/data/aes.hjson:825-826``).
    The AES recoverable alert channel is ORed into the Crypto alert source
    (``hw/sys/sep/doc/crypto.adoc:122-127``, routing table row AES, ``:150-151``).
  * CTRL_AUX_REGWEN is RW0C: once cleared it blocks CTRL_AUX_SHADOWED writes,
    and a write of 1 does not set it again
    (``vendor/lowRISC/opentitan/overlay/regs/aes/regs/gen/adoc/aes.adoc``).
  * An AES reset clears the update error; the AES core uses ``rst_ni`` for
    both reset domains (``hw/sys/sep/doc/aes.adoc``, OCAH Modifications).
  * A malformed encoding on the alert pair of a crypto alert receiver raises
    its integrity fail, and the Crypto alert source (PIC source 33, vector bit
    32) is the OR of every receiver pulse and integrity fail
    (``hw/sys/sep/doc/crypto.adoc``, OpenTitan Alert Termination;
    ``hw/sys/sep/doc/interrupts.adoc``).

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense``,
``+esrc_noise_force``, VCS only (the AES reset leg reads state after reset
and requires every bit to be known). AES and KMAC run; HMAC and OTBN are
released for the malformed alert leg; ABR and the Key Manager stay in reset.
The malformed pair uses the crypto alert sender inject of ``tb/tb_top.sv``
(``crypto_alert_inject_i``, ``crypto_alert_inject_idx_i``,
``crypto_alert_inject_val_i``).

Randomization (``SepSeededRng`` from the run seed, drawn before the first
stimulus): the AES values A and B (legal, different in one drawn field), the
AUX pair order (the values differ in KEY_TOUCH_FORCES_RESEED only), the KMAC
values (different in one drawn endianness bit), the KMAC threshold pair, the
gap of each pair (0 to 64 clocks), the KMAC message, the AES data, the order
of the six blocks of the malformed alert leg, the receiver of each block, the
wire value of each malformed pair and the ALERT_TEST bit of each block.

Checkers:
  CHK-SHADOW-ERR       AES mismatched pair: status bit set, bit 32 pulses,
                       ALERT_FATAL_FAULT 0.
  CHK-SHADOW-CTRL      AES equal pair: no pulse over 4 x c_err clocks and the
                       register reads A. Control: the mismatched pair pulsed.
  CHK-SHADOW-RESTART   after R written twice the next AES block equals its golden.
  CHK-AUX-SHADOW-ERR   AES AUX mismatched pair: bit 32 pulses (alert_cycles > 0)
                       within 4 x c_err clocks of the second write. Control:
                       CTRL-AUX-SHADOW-EQ, the equal pair gives no pulse.
  CHK-AUX-SHADOW-WRITE AES AUX equal pair of A_AUX: the register reads A_AUX.
                       Control: CTRL-AUX-SHADOW-PRE, the read before the pair
                       gives the reset value 0x1 (``aes.adoc:131``), which
                       differs from A_AUX.
  CHK-AUX-REGWEN       REGWEN reads 0 after a 0 write, a new AUX pair does not
                       land, a 1 write leaves REGWEN at 0. Control: the same
                       AUX write lands before the lock.
  CHK-AUX-RESET        after an AES reset the update error reads 0 with no X
                       and both new AUX pairs land. Control: before the reset
                       the AUX register differs from its reset value and the
                       update error reads 1.
  CHK-ALERT-MALFORMED  per block: bit 32 stays 0 over a quiet window before,
                       rises during the malformed pair on a clock 2 to
                       4 x c - 1 (inclusive) after the mark, reads 0 after the
                       release and stays 0 over a quiet window after it.
                       c: the ALERT_TEST delay of the block in the same trial.
                       The mark is the last clock sampled before the inject:
                       the leaf drives the inject on clock 1 and the pair is
                       forced at the falling edge after it, so clock 2 is the
                       first clock that can show the rise. The FCOV sampler
                       counts the same clocks from the same mark and fills
                       ``x_alert_source`` only inside the same window
                       (``alert_rise_bound`` = 4 x c).
``OBS-SHADOW-AUX`` logs ``STATUS.ALERT_RECOV_CTRL_UPDATE_ERR`` after each AES AUX
pair: the status text names "the shadowed Control Register" (aes.hjson:995) and
no text states that it covers CTRL_AUX_SHADOWED. Every KMAC result
(``CFG_SHADOWED`` and ``ENTROPY_REFRESH_THRESHOLD_SHADOWED``) is logged as
``OBS-SHADOW-KMAC`` and not graded: no KMAC text defines the update-error write
sequence of those registers; the ALERT_TEST write of each block is the
timing reference ``OBS-ALERT-REF``.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge
from env.sep_aes_golden import aes_encrypt_words
from env.sep_bit_watch import BitWatchTimeout, SepBitWatch
from env.sep_chk_log import SepChkLog
from env.sep_crypto_kat_rows import AES_KEY_ROWS, SP800_38A_PT_BLOCK1
from env.sep_fcov_gate import close_graded_window, open_graded_window, set_alert_rise_bound
from env.sep_kmac_golden import kmac_family_words
from env.sep_seeded_rng import SepSeededRng
from env.sep_trial_wait import TrialTimeout, wait_until
from sep_base_test import sep_base_test
from sep_monitor_life import MonitorLife
from sep_reg_meta import AES, KMAC, sep_addr_define
from seq_lib.sep_aes_seq import (
    AES_CTRL_SHADOWED,
    AES_DATA_IN_0,
    AES_DATA_OUT_0,
    AES_KEY_LEN_256,
    AES_KEYLEN_CTRL,
    AES_MODE_CTRL,
    AES_MODE_ECB,
    AES_OP_DEC,
    AES_OP_ENC,
    AES_STATUS,
    AES_TRIGGER,
    AES_TRIGGER_DATA_OUT_CLEAR,
    SepAes,
    build_aes_ctrl,
)
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_kmac_seq import (
    KMAC_CFG_SHADOWED,
    KMAC_MODE,
    KMAC_STATUS,
    KMAC_STATUS_IDLE,
    KMAC_STRENGTH,
    SepKmac,
    SepKmacCfg,
    build_kmac_cfg,
)

TEST = "sep_crypto_shadow_update_err_rand_test"

# Published 256-bit test constants (env/sep_crypto_kat_rows.py). The seed picks a row,
# never the bytes.
KEY_ROWS = AES_KEY_ROWS[256]
AES_PT = SP800_38A_PT_BLOCK1

VEC_ALERT_BIT = 32  # source 33, Crypto alert (hw/sys/sep/doc/interrupts.adoc)
# Receiver index range of each block (hw/sys/sep/doc/crypto.adoc, alert routing table)
# and the ALERT_TEST register of each block.
BLOCKS = {
    "hmac": ((0,), "SEP_TOP_HMAC_ALERT_TEST_BASE_ADDR", 1),
    "otbn": ((1, 2), "SEP_TOP_OTBN_ALERT_TEST_BASE_ADDR", 2),
    "aes": ((3, 4), "SEP_TOP_AES_ALERT_TEST_BASE_ADDR", 2),
    "kmac": ((5, 6), "SEP_TOP_KMAC_ALERT_TEST_BASE_ADDR", 2),
    "csrng": ((7, 8), "SEP_TOP_CSRNG_ALERT_TEST_BASE_ADDR", 2),
    "edn": ((9, 10), "SEP_TOP_EDN_ALERT_TEST_BASE_ADDR", 2),
}

AES_ST_IDLE = AES.field_mask("STATUS", "idle")
AES_ST_OV = AES.field_mask("STATUS", "output_valid")
AES_ST_ERR = AES.field_mask("STATUS", "alert_recov_ctrl_update_err")
AES_ST_FATAL = AES.field_mask("STATUS", "alert_fatal_fault")
AES_CTRL_MASK = AES.mask32("CTRL_SHADOWED")
AES_AUX = AES.addr("CTRL_AUX_SHADOWED")
AES_AUX_MASK = AES.mask32("CTRL_AUX_SHADOWED")
AES_AUX_KTFR = AES.field_mask("CTRL_AUX_SHADOWED", "key_touch_forces_reseed")
AES_AUX_RESET = AES.reset32("CTRL_AUX_SHADOWED")
AES_REGWEN = AES.addr("CTRL_AUX_REGWEN")
AES_REGWEN_MASK = AES.field_mask("CTRL_AUX_REGWEN", "ctrl_aux_regwen")
AES_ST_FIELDS = AES.mask32("STATUS")
A_AUX = 0  # KEY_TOUCH_FORCES_RESEED = 0, FORCE_MASKS = 0 (differs from the reset value 0x1)
B_AUX = AES_AUX_KTFR  # KEY_TOUCH_FORCES_RESEED = 1, FORCE_MASKS = 0

KMAC_ST_ERR = KMAC.field_mask("STATUS", "alert_recov_ctrl_update_err")
KMAC_ST_FATAL = KMAC.field_mask("STATUS", "alert_fatal_fault")
KMAC_THR = KMAC.addr("ENTROPY_REFRESH_THRESHOLD_SHADOWED")
KMAC_ENDIAN = {
    "msg_endianness": KMAC.field_mask("CFG_SHADOWED", "msg_endianness"),
    "state_endianness": KMAC.field_mask("CFG_SHADOWED", "state_endianness"),
}
# R of KMAC: SHA3-256, kmac_en = 0, sideload = 0, entropy_mode = EDN,
# entropy_ready = 1, both endianness bits 0.
KMAC_R = build_kmac_cfg(mode=KMAC_MODE["sha3"], kstrength=KMAC_STRENGTH[256], kmac_en=False)

WAIT_LIMIT = 20_000  # outer limit of a wait with no clean time (logged as bound=)
ALERT_REF_BOUND = 2_000  # outer limit of the ALERT_TEST reference wait (logged)
WINDOW_FACTOR = 4  # 4 x c_err and 4 x c (test parameter)
# First clock after the mark that can show the malformed-alert rise: the leaf drives
# the inject on clock 1 and tb_top forces the pair at the falling edge after it.
ALERT_RISE_CLK_MIN = 2


def _le_words(data: bytes) -> list[int]:
    return [int.from_bytes(data[i : i + 4], "little") for i in range(0, len(data), 4)]


def _aes_word(key_bits: int, mode: str, op: str) -> int:
    return build_aes_ctrl(
        sideload=False,
        operation=AES_OP_ENC if op == "enc" else AES_OP_DEC,
        mode=AES_MODE_CTRL[mode],
        key_len=AES_KEYLEN_CTRL[key_bits],
    )


@dataclass(frozen=True)
class Plan:
    seed: int
    a: int
    b: int
    a_desc: str
    aux_first: int
    kmac_bit: str
    thr: tuple[int, int]
    gaps: dict[str, int]
    kmac_msg: tuple[int, ...]
    key_row: int
    block_order: tuple[str, ...]
    receiver: dict[str, int]
    wire: dict[str, int]
    test_bit: dict[str, int]

    @property
    def aux_pair(self) -> tuple[int, int]:
        return (self.aux_first, B_AUX if self.aux_first == A_AUX else A_AUX)

    @property
    def key(self) -> list[int]:
        return _le_words(KEY_ROWS[self.key_row][1])

    def describe(self) -> str:
        return (
            f"aes_a=0x{self.a:04x} aes_b=0x{self.b:04x} ({self.a_desc}) "
            f"aux_pair=0x{self.aux_pair[0]:x},0x{self.aux_pair[1]:x} kmac_bit={self.kmac_bit} "
            f"thr=0x{self.thr[0]:03x},0x{self.thr[1]:03x} "
            f"gaps={','.join(f'{k}:{v}' for k, v in self.gaps.items())} "
            f"key_row={KEY_ROWS[self.key_row][0]} "
            f"blocks={','.join(f'{b}/rx{self.receiver[b]}/v{self.wire[b]}/t{self.test_bit[b]}' for b in self.block_order)}"
        )


GAP_KEYS = ("aes_mis", "aes_eq", "aux_mis", "kmac_mis", "kmac_eq", "thr_mis", "reset_leg")


def draw_plan(seed: int) -> Plan:
    """Every draw of the leaf, in a fixed order, with no simulator access."""
    rng = SepSeededRng(seed)
    sizes, modes, ops = (128, 192, 256), ("ecb", "cbc", "ctr"), ("enc", "dec")
    cell = {"key_len": rng.choice(sizes), "mode": rng.choice(modes), "operation": rng.choice(ops)}
    field = rng.choice(("key_len", "mode", "operation"))
    pool = {"key_len": sizes, "mode": modes, "operation": ops}[field]
    other = dict(cell)
    other[field] = rng.choice([v for v in pool if v != cell[field]])
    a = _aes_word(cell["key_len"], cell["mode"], cell["operation"])
    b = _aes_word(other["key_len"], other["mode"], other["operation"])
    a_desc = f"field={field} a={cell[field]} b={other[field]}"
    aux_first = rng.choice((A_AUX, B_AUX))
    kmac_bit = rng.choice(tuple(KMAC_ENDIAN))
    t1 = rng.getrandbits(10)
    t2 = rng.getrandbits(10)
    while t2 == t1:
        t2 = rng.getrandbits(10)
    gaps = {k: rng.randrange(0, 65) for k in GAP_KEYS}
    kmac_msg = tuple(rng.getrandbits(32) for _ in range(8))
    key_row = rng.randrange(len(KEY_ROWS))
    order = list(BLOCKS)
    rng.shuffle(order)
    receiver = {b: rng.choice(BLOCKS[b][0]) for b in BLOCKS}
    wire = {b: rng.choice((0, 1)) for b in BLOCKS}
    test_bit = {b: rng.randrange(BLOCKS[b][2]) for b in BLOCKS}
    return Plan(
        seed, a, b, a_desc, aux_first, kmac_bit, (t1, t2), gaps, kmac_msg, key_row,
        tuple(order), receiver, wire, test_bit,
    )  # fmt: skip


def _bitstr(sig) -> str:
    """The per-bit string of a signal, MSB first (cocotb 1.x ``binstr``, 2.x ``str``)."""
    value = sig.value
    bits = getattr(value, "binstr", None)
    return (bits if bits is not None else str(value)).strip()


def _known_int(sig) -> int | None:
    bits = _bitstr(sig)
    return int(bits, 2) if bits and all(c in "01" for c in bits) else None


class _ReadXTap:
    """Grades the read data of 32-bit reads at the graded addresses on ``s_axi`` for X/Z.

    The AXI master converts each R beat to an integer and raises on an X/Z bit,
    which ends the leaf before any check line. The tap samples the bus at the
    falling clock edge, half a clock before the master takes the beat, and calls
    ``on_x(reg, addr, lanes)`` for an accepted beat of a graded read whose
    accessed byte lanes carry X/Z. ARs pair with R beats by ID, in order.
    """

    def __init__(self, dut, graded: dict[int, str], on_x) -> None:
        names = ("arvalid", "arready", "araddr", "arid", "rvalid", "rready", "rdata", "rid")
        self.sig = {n: getattr(dut, f"s_axi_{n}") for n in names}
        self.graded = graded
        self.on_x = on_x
        self.clk = 0
        self.beats = 0
        self.unknown = 0
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
                lanes = bits[len(bits) - lo - 32 : len(bits) - lo]
                if any(c not in "01" for c in lanes):
                    self.unknown += 1
                    self.on_x(self.graded[addr], addr, lanes)


@pyuvm.test()
class sep_crypto_shadow_update_err_rand_test(sep_base_test):
    """Shadow update errors, AUX lock and reset, and malformed alert pairs reach bit 32."""

    required_evidence = (
        "CHK-SHADOW-ERR",
        "CHK-SHADOW-CTRL",
        "CHK-SHADOW-RESTART",
        "CHK-AUX-SHADOW-ERR",
        "CHK-AUX-SHADOW-WRITE",
        "CHK-AUX-REGWEN",
        "CHK-AUX-RESET",
        "CHK-ALERT-MALFORMED",
    )

    async def run_scenario(self) -> None:
        dut = cocotb.top
        await self.bring_up_no_cpu(park=("otbn", "hmac", "kmac", "abr"))
        await self.bring_up_entropy(strict=True, score_km=False)
        self.start_fifo_drain()
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        await self.swrst.release("kmac")
        self.logger.info("BASELINE sw_reset_n=0x%02x", self.swrst.value)

        seed = self.random_seed()
        plan = draw_plan(seed)
        self.logger.info("PLAN seed=%d %s", seed, plan.describe())
        self.plan = plan
        self.chk = SepChkLog(self, TEST, seed)
        self.aes = SepAes(self)
        self.kmac = SepKmac(self)
        self.bus = SepAxiRegDriver(self)
        self.vec = SepBitWatch(
            dut.sep_internal_interrupts_probe_o, {"alert": VEC_ALERT_BIT}, name="vec32"
        ).start()

        c_err = await self._aes_pass()
        await self._kmac_pass(c_err)
        await self._aux_lock_leg()
        await self._aes_reset_leg()
        await self._malformed_leg()
        close_graded_window(self.logger)

        await self.stop_fifo_drain()
        assert self.drbg_sb.report()
        self.chk.finish()

    # --- helpers --------------------------------------------------------------------
    async def _pulse(self, eng: str) -> None:
        """Reset bit 0 then 1 and the gated-reset probe; a timeout raises."""
        dut = cocotb.top
        probe = getattr(dut, f"{eng}_gated_rst_n_probe_o")
        await self.swrst.park(eng)
        for _ in range(WAIT_LIMIT):
            if self.rd(probe) == 0:
                break
            await RisingEdge(dut.clk_i)
        else:
            raise AssertionError(f"{eng} gated reset never asserted after SW_RESET_N park")
        await self.swrst.release(eng)
        for _ in range(WAIT_LIMIT):
            if self.rd(probe) == 1:
                return
            await RisingEdge(dut.clk_i)
        raise AssertionError(f"{eng} gated reset never released")

    async def _poll(self, drv, addr: int, mask: int, want: int, bound: int, what: str) -> int:
        samples = await wait_until(
            lambda: drv._rd(addr), lambda: self.vec.clk, mask, want, bound, what
        )
        return samples[-1][1]

    async def _pair(self, drv, addr: int, first: int, second: int, gap: int):
        """Two writes with ``gap`` clocks between, no read between. Returns the two marks."""
        m1 = self.vec.mark()
        await drv._wr(addr, first)
        if gap:
            await ClockCycles(cocotb.top.clk_i, gap)
        m2 = self.vec.mark()
        await drv._wr(addr, second)
        return m1, m2

    async def _until(self, mark, clocks: int) -> None:
        """Wait until ``clocks`` clocks after ``mark`` have been sampled."""
        while self.vec.clk < mark.clk + clocks:
            await RisingEdge(cocotb.top.clk_i)

    def _first_rise(self, mark) -> int | None:
        rises = self.vec.rise_clks_since(mark, "alert")
        return rises[0] - mark.clk if rises else None

    async def _aes_idle(self, what: str) -> None:
        await self._poll(self.aes, AES_STATUS, AES_ST_IDLE, AES_ST_IDLE, WAIT_LIMIT, what)

    async def _aes_reset(self) -> None:
        await self._pulse("aes")
        await self._aes_idle("aes_idle_after_reset")

    # --- AES pass -------------------------------------------------------------------
    async def _aes_pass(self) -> int:
        plan = self.plan
        await self._aes_reset()
        open_graded_window(TEST, self.logger)
        status_err = 0
        fatal = -1
        c_err: int | None = None
        reason = ""
        m1 = None
        try:
            m1, m2 = await self._pair(
                self.aes, AES_CTRL_SHADOWED, plan.a, plan.b, plan.gaps["aes_mis"]
            )
            await self._poll(self.aes, AES_STATUS, AES_ST_ERR, AES_ST_ERR, WAIT_LIMIT, "update_err")
            status_err = 1
            try:
                rise = await self.vec.wait_rise(m2, WAIT_LIMIT, "alert")
                c_err = max(1, rise - m2.clk)
            except BitWatchTimeout:
                reason = f"no_alert_rise bound={WAIT_LIMIT}"
            fatal = int(bool(await self.aes._rd(AES_STATUS) & AES_ST_FATAL))
        except TrialTimeout as exc:
            reason = f"timeout:{exc.what} bound={exc.bound}"
        cycles = self.vec.high_clocks_since(m1, "alert") if m1 is not None else 0
        fields = {
            "reg": "aes_ctrl",
            "a": f"0x{plan.a:x}",
            "b": f"0x{plan.b:x}",
            "status_err": status_err,
            "alert_cycles": cycles,
            "fatal": fatal,
            "c_err": c_err,
        }
        if reason:
            fields["reason"] = reason
        self.chk.ok(
            "SHADOW-ERR", not reason and status_err == 1 and cycles > 0 and fatal == 0, **fields
        )

        # Recovery: R written twice, then one block.
        key = plan.key
        golden = aes_encrypt_words("ecb", key, _le_words(AES_PT))
        r = build_aes_ctrl(
            sideload=False, operation=AES_OP_ENC, mode=AES_MODE_ECB, key_len=AES_KEY_LEN_256
        )
        ct = None
        reason = ""
        try:
            await self.aes._wr(AES_CTRL_SHADOWED, r)
            await self.aes._wr(AES_CTRL_SHADOWED, r)
            await self.aes.write_key(key)
            await self._aes_idle("idle_after_key")
            await self.aes._wr(AES_TRIGGER, AES_TRIGGER_DATA_OUT_CLEAR)
            await self._aes_idle("idle_after_clear")
            for i, w in enumerate(_le_words(AES_PT)):
                await self.aes._wr(AES_DATA_IN_0 + 4 * i, w)
            await self._poll(self.aes, AES_STATUS, AES_ST_OV, AES_ST_OV, WAIT_LIMIT, "output_valid")
            ct = [await self.aes._rd(AES_DATA_OUT_0 + 4 * i) for i in range(4)]
        except TrialTimeout as exc:
            reason = f"timeout:{exc.what} bound={exc.bound}"
        fields = {"reg": "aes_ctrl", "op==golden": int(ct == golden)}
        if reason:
            fields["reason"] = reason
        self.chk.ok("SHADOW-RESTART", ct == golden, **fields)
        close_graded_window(self.logger)

        # Equal pair (A, A).
        await self._aes_reset()
        open_graded_window(TEST, self.logger)
        base = c_err or 1
        window = WINDOW_FACTOR * base
        cycles = -1
        rb = -1
        try:
            m1, m2 = await self._pair(
                self.aes, AES_CTRL_SHADOWED, plan.a, plan.a, plan.gaps["aes_eq"]
            )
            await self._until(m2, window)
            cycles = self.vec.high_clocks_since(m1, "alert")
            st = await self.aes._rd(AES_STATUS)
            self.chk.obs("SHADOW-STATUS", reg="aes_ctrl", status_err=int(bool(st & AES_ST_ERR)))
            rb = await self.aes._rd(AES_CTRL_SHADOWED)
        except TrialTimeout:
            cycles = -1
        close_graded_window(self.logger)
        self.chk.ctrl("SHADOW-CTRL", c_err is not None and c_err > 0, ctrl_c_err=c_err)
        rb_ok = rb >= 0 and (rb & AES_CTRL_MASK) == (plan.a & AES_CTRL_MASK)
        self.chk.ok(
            "SHADOW-CTRL",
            cycles == 0 and rb_ok,
            reg="aes_ctrl",
            a=f"0x{plan.a:x}",
            alert_cycles=cycles,
            readback=f"0x{rb & AES_CTRL_MASK:x}" if rb >= 0 else "none",
            rsvd=f"0x{rb & ~AES_CTRL_MASK & 0xFFFF_FFFF:x}" if rb >= 0 else "none",
            window_clk=window,
            ctrl_c_err=c_err,
        )

        # AUX pairs: the alert of the mismatched pair and the write of the equal pair.
        aux1, aux2 = plan.aux_pair
        await self._aes_reset()
        open_graded_window(TEST, self.logger)
        m1, m2 = await self._pair(self.aes, AES_AUX, aux1, aux2, plan.gaps["aux_mis"])
        await self._until(m2, window)
        mis_cycles = self.vec.high_clocks_since(m1, "alert")
        st = await self.aes._rd(AES_STATUS)
        close_graded_window(self.logger)
        self.chk.obs(
            "SHADOW-AUX", reg="aes_aux", pair="mismatched", status_err=int(bool(st & AES_ST_ERR))
        )
        # The equal pair writes A_AUX, which differs from the reset value, so a pair
        # that does not land reads the reset value.
        await self._aes_reset()
        open_graded_window(TEST, self.logger)
        aux_pre = await self.aes._rd(AES_AUX) & AES_AUX_MASK
        m1, m2 = await self._pair(self.aes, AES_AUX, A_AUX, A_AUX, 0)
        await self._until(m2, window)
        eq_cycles = self.vec.high_clocks_since(m1, "alert")
        st = await self.aes._rd(AES_STATUS)
        aux_rb = await self.aes._rd(AES_AUX) & AES_AUX_MASK
        close_graded_window(self.logger)
        self.chk.obs(
            "SHADOW-AUX", reg="aes_aux", pair="equal", status_err=int(bool(st & AES_ST_ERR))
        )
        self.chk.ctrl("AUX-SHADOW-EQ", eq_cycles == 0, ctrl_eq_alert_cycles=eq_cycles)
        self.chk.ok(
            "AUX-SHADOW-ERR",
            mis_cycles > 0,
            reg="aes_aux",
            first=f"0x{aux1:x}",
            second=f"0x{aux2:x}",
            alert_cycles=mis_cycles,
            window_clk=window,
            ctrl_eq_alert_cycles=eq_cycles,
        )
        reset_aux = AES_AUX_RESET & AES_AUX_MASK
        self.chk.ctrl(
            "AUX-SHADOW-PRE",
            aux_pre == reset_aux and reset_aux != A_AUX,
            ctrl_aux_pre=f"0x{aux_pre:x}",
            reset=f"0x{reset_aux:x}",
        )
        self.chk.ok(
            "AUX-SHADOW-WRITE",
            aux_rb == A_AUX,
            reg="aes_aux",
            value=f"0x{A_AUX:x}",
            readback=f"0x{aux_rb:x}",
            ctrl_aux_pre=f"0x{aux_pre:x}",
        )
        return base

    # --- KMAC pass (logged only) ------------------------------------------------------
    async def _kmac_idle(self) -> None:
        await self._poll(
            self.kmac, KMAC_STATUS, KMAC_STATUS_IDLE, KMAC_STATUS_IDLE, WAIT_LIMIT, "sha3_idle"
        )

    async def _kmac_pair_obs(
        self, reg: str, addr: int, first: int, second: int, gap: int, c_err: int
    ) -> None:
        pair = "equal" if first == second else "mismatched"
        try:
            await self._pulse("kmac")
            await self._kmac_idle()
            m1, m2 = await self._pair(self.kmac, addr, first, second, gap)
            await self._until(m2, WINDOW_FACTOR * c_err)
            st = await self.kmac._rd(KMAC_STATUS)
            rb = await self.kmac._rd(addr) if pair == "equal" else None
            self.chk.obs(
                "SHADOW-KMAC",
                reg=reg,
                pair=pair,
                status_err=int(bool(st & KMAC_ST_ERR)),
                fatal=int(bool(st & KMAC_ST_FATAL)),
                alert_cycles=self.vec.high_clocks_since(m1, "alert"),
                c_err=self._first_rise(m2),
                readback="na" if rb is None else f"0x{rb:x}",
            )
        except TrialTimeout as exc:
            self.chk.obs(
                "SHADOW-KMAC", reg=reg, pair=pair, reason=f"timeout:{exc.what}", bound=exc.bound
            )

    async def _kmac_pass(self, c_err: int) -> None:
        plan = self.plan
        a = KMAC_R
        b = KMAC_R | KMAC_ENDIAN[plan.kmac_bit]
        await self._kmac_pair_obs("kmac_cfg", KMAC_CFG_SHADOWED, a, b, plan.gaps["kmac_mis"], c_err)
        # Recovery: R twice (written by the driver) and one SHA3-256 hash.
        cfg = SepKmacCfg(mode="sha3", sec=256, msg_words=list(plan.kmac_msg), outlen_bytes=32)
        assert cfg.cfg_word() == KMAC_R, "the KMAC recovery word is not R"
        try:
            digest = await self.kmac.run_family(cfg, tag="shadow-recovery")
            self.chk.obs(
                "SHADOW-KMAC",
                reg="kmac_cfg",
                step="recovery",
                **{"digest==golden": int(digest == kmac_family_words(**cfg.golden_kwargs()))},
            )
        except AssertionError as exc:
            # Only a bounded wait of the helper ends here. A helper check of the
            # DUT (the kmac_done write-one clear) is not caught and fails the leaf.
            if "timeout" not in str(exc):
                raise
            self.chk.obs("SHADOW-KMAC", reg="kmac_cfg", step="recovery", reason=str(exc)[:80])
        await self._kmac_pair_obs("kmac_cfg", KMAC_CFG_SHADOWED, a, a, plan.gaps["kmac_eq"], c_err)
        t1, t2 = plan.thr
        await self._kmac_pair_obs("kmac_thr", KMAC_THR, t1, t2, plan.gaps["thr_mis"], c_err)
        await self._kmac_pair_obs("kmac_thr", KMAC_THR, t1, t1, 0, c_err)

    # --- AUX lock and AES reset --------------------------------------------------------
    async def _aux_write(self, value: int) -> int:
        await self.aes._wr(AES_AUX, value)
        await self.aes._wr(AES_AUX, value)
        return await self.aes._rd(AES_AUX) & AES_AUX_MASK

    async def _aux_lock_leg(self) -> None:
        await self._aes_reset()
        open_graded_window(TEST, self.logger)
        pre = await self._aux_write(A_AUX)
        await self.aes._wr(AES_REGWEN, 0)
        r0 = await self.aes._rd(AES_REGWEN) & AES_REGWEN_MASK
        after = await self._aux_write(B_AUX)
        await self.aes._wr(AES_REGWEN, AES_REGWEN_MASK)
        r1 = await self.aes._rd(AES_REGWEN) & AES_REGWEN_MASK
        self.chk.ctrl("AUX-REGWEN", pre == A_AUX, ctrl_pre_lock_lands=int(pre == A_AUX))
        self.chk.ok(
            "AUX-REGWEN",
            r0 == 0 and after == pre and r1 == 0,
            regwen_after0=r0,
            aux_before=f"0x{pre:x}",
            aux_after=f"0x{after:x}",
            regwen_after1=r1,
            ctrl_pre_lock_lands=int(pre == A_AUX),
        )

    async def _aes_reset_leg(self) -> None:
        plan = self.plan
        err_pre = 0
        try:
            await self._pair(self.aes, AES_CTRL_SHADOWED, plan.a, plan.b, plan.gaps["reset_leg"])
            await self._poll(self.aes, AES_STATUS, AES_ST_ERR, AES_ST_ERR, WAIT_LIMIT, "update_err")
            err_pre = 1
        except TrialTimeout:
            err_pre = 0
        aux_pre = await self.aes._rd(AES_AUX) & AES_AUX_MASK

        # Every STATUS and CTRL_AUX_SHADOWED read from the reset to the last AUX pair
        # is graded for X/Z. An X/Z read is a CHK-AUX-RESET FAIL at the bus, before
        # the AXI master raises on the same beat.
        def _on_x(reg: str, addr: int, lanes: str) -> None:
            self.chk.ok(
                "AUX-RESET", False, x_free=0, reg=reg, addr=f"0x{addr:08x}", rdata_bits=lanes
            )

        tap = _ReadXTap(cocotb.top, {AES_STATUS: "STATUS", AES_AUX: "CTRL_AUX_SHADOWED"}, _on_x)
        tap.start()
        # The reset is the graded stimulus: the window stays open across it.
        await self._aes_reset()
        aux = await self.aes._rd(AES_AUX)
        st = await self.aes._rd(AES_STATUS)
        status_err = int(bool(st & AES_ST_ERR))
        self.chk.obs(
            "AUX-RESET",
            aux=f"0x{aux & AES_AUX_MASK:x}",
            status_rsvd=f"0x{st & ~AES_ST_FIELDS & 0xFFFF_FFFF:x}",
        )
        after_b = await self._aux_write(B_AUX)
        after_a = await self._aux_write(A_AUX)
        await tap.stop()
        # Positive evidence that the tap saw the graded reads: at least one idle poll
        # read, the two reads above and the two AUX readbacks.
        x_free = int(tap.unknown == 0)
        self.chk.ctrl("AUX-RESET-TAP", tap.beats >= 5, graded_read_beats=tap.beats)
        ctrl_ok = aux_pre != (AES_AUX_RESET & AES_AUX_MASK) and err_pre == 1
        self.chk.ctrl(
            "AUX-RESET", ctrl_ok, ctrl_aux_pre_reset=f"0x{aux_pre:x}", ctrl_err_pre_reset=err_pre
        )
        lands = after_b == B_AUX and after_a == A_AUX
        self.chk.ok(
            "AUX-RESET",
            status_err == 0 and x_free == 1 and lands,
            ctrl_aux_pre_reset=f"0x{aux_pre:x}",
            ctrl_err_pre_reset=err_pre,
            status_err=status_err,
            x_free=x_free,
            graded_read_beats=tap.beats,
            aux_after_b=f"0x{after_b:x}",
            aux_after_a=f"0x{after_a:x}",
            write_pairs_land=int(lands),
        )
        close_graded_window(self.logger)

    # --- malformed alert leg -----------------------------------------------------------
    def _bit32(self) -> int:
        return (
            self.rd(cocotb.top.sep_internal_interrupts_probe_o, mask=1 << VEC_ALERT_BIT)
            >> VEC_ALERT_BIT
        ) & 1

    async def _malformed_leg(self) -> None:
        dut = cocotb.top
        plan = self.plan
        await self.swrst.release("hmac", "otbn")
        for eng in ("hmac", "otbn"):
            probe = getattr(dut, f"{eng}_gated_rst_n_probe_o")
            for _ in range(WAIT_LIMIT):
                if self.rd(probe) == 1:
                    break
                await RisingEdge(dut.clk_i)
            else:
                raise AssertionError(f"{eng} gated reset never released")
        await ClockCycles(dut.clk_i, 16)
        for blk in plan.block_order:
            rx, test_reg, _ = BLOCKS[blk]
            idx, val, bit = plan.receiver[blk], plan.wire[blk], plan.test_bit[blk]
            # Timing reference: one ALERT_TEST event of the block (not graded here).
            close_graded_window(self.logger)
            m = self.vec.mark()
            await self.bus._wr(sep_addr_define(test_reg), 1 << bit)
            try:
                c = max(1, await self.vec.wait_rise(m, ALERT_REF_BOUND, "alert") - m.clk)
                await self.vec.wait_level(0, ALERT_REF_BOUND, "alert")
            except BitWatchTimeout:
                self.chk.ctrl(
                    "ALERT-REF", False, block=blk, alert_test_bit=bit, bound=ALERT_REF_BOUND
                )
                self.chk.ok("ALERT-MALFORMED", False, block=blk, index=idx, reason="no_reference")
                continue
            self.chk.obs("ALERT-REF", block=blk, clk=c, alert_test_bit=bit)
            # Quiet window before the inject: bit 32 stays 0 for WINDOW_FACTOR x c clocks
            # with no stimulus, so a rise in the inject window comes from the inject.
            mq = self.vec.mark()
            await ClockCycles(dut.clk_i, WINDOW_FACTOR * c)
            quiet_pre = self.vec.high_clocks_since(mq, "alert")
            pre = self._bit32()

            open_graded_window(TEST, self.logger)
            rise_bound = WINDOW_FACTOR * c
            rise_max = rise_bound - 1
            # The mark is the last clock the watcher sampled; this clock is clock 1 after it.
            m2 = self.vec.mark()
            # The FCOV sampler counts from the same mark and takes the same inclusive
            # window ALERT_RISE_CLK_MIN to rise_bound - 1 (sep_fcov_gate.set_alert_rise_bound).
            set_alert_rise_bound(rise_bound)
            dut.crypto_alert_inject_idx_i.value = idx
            dut.crypto_alert_inject_val_i.value = val
            dut.crypto_alert_inject_i.value = 1
            raise_clk = None
            try:
                raise_clk = await self.vec.wait_rise(m2, rise_bound, "alert") - m2.clk
            except BitWatchTimeout:
                raise_clk = None
            set_alert_rise_bound(0)
            dut.crypto_alert_inject_i.value = 0
            await ClockCycles(dut.clk_i, WINDOW_FACTOR * c)
            post = self._bit32()
            # Quiet window after the release: bit 32 stays 0 for WINDOW_FACTOR x c clocks.
            mp = self.vec.mark()
            await ClockCycles(dut.clk_i, WINDOW_FACTOR * c)
            quiet_post = self.vec.high_clocks_since(mp, "alert")
            close_graded_window(self.logger)
            # The rise counts only on a clock ALERT_RISE_CLK_MIN to rise_max after the mark.
            raised = int(raise_clk is not None and ALERT_RISE_CLK_MIN <= raise_clk <= rise_max)
            self.chk.ok(
                "ALERT-MALFORMED",
                pre == 0 and quiet_pre == 0 and raised == 1 and post == 0 and quiet_post == 0,
                block=blk,
                index=idx,
                wire=val,
                pre=pre,
                quiet_pre_high_clk=quiet_pre,
                raised=raised,
                post=post,
                quiet_post_high_clk=quiet_post,
                quiet_clk=WINDOW_FACTOR * c,
                raise_clk=raise_clk,
                expect_raise_clk_min=ALERT_RISE_CLK_MIN,
                expect_raise_clk_max=rise_max,
                ref_clk=c,
            )
        dut.crypto_alert_inject_idx_i.value = 0
        dut.crypto_alert_inject_val_i.value = 0
