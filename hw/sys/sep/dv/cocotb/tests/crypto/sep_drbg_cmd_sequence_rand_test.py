# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""EDN boot-mode precedence, the EDN and CSRNG software command handshakes, and the
invalid command sequence alert.

Contract (``vendor/lowRISC/opentitan/overlay/regs/edn/regs/gen/adoc/edn.adoc``: CTRL,
BOOT_INS_CMD, SW_CMD_REQ, SW_CMD_STS, HW_CMD_STS;
``vendor/lowRISC/opentitan/overlay/regs/csrng/regs/gen/adoc/csrng.adoc``: CMD_REQ,
SW_CMD_STS, RECOV_ALERT_STS; ``hw/sys/sep/doc/interrupts.adoc``: source N on vector
bit N - 1):
  * With ``CTRL.BOOT_REQ_MODE`` true EDN reports ``HW_CMD_STS.BOOT_MODE`` = 1 and
    ``AUTO_MODE`` = 0, also with ``AUTO_REQ_MODE`` true (boot mode takes precedence).
  * With both modes false EDN is in software port mode: ``CMD_REG_RDY`` and
    ``CMD_RDY`` are 1 before a command, ``CMD_ACK`` rises once CSRNG acknowledges
    it, and ``INTR_STATE.edn_cmd_req_done`` sets.
  * The CSRNG software instance follows the same handshake (``CMD_RDY``,
    ``CMD_ACK``, ``INTR_STATE.cs_cmd_req_done``).
  * An instantiate (0x901, the RDL reset value of ``BOOT_INS_CMD``) sent to an
    instantiated state is ignored and sets ``RECOV_ALERT_STS`` bit 14
    (``CMD_STAGE_INVALID_CMD_SEQ_ALERT``); a write of 0 clears it.

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense``,
``+esrc_noise_force``. Baseline ``SW_RESET_N`` = 0x20 (TRNG released; the Key
Manager and every engine held) and ``EXT_TRNG_SRC_SEL`` = 0x0. The clean start of
every group is a TRNG reset, the open entropy bring-up without the EDN step, a
CSRNG ``CTRL`` write with ``ENABLE`` and ``SW_APP_ENABLE`` true, and a
``RECOV_ALERT_STS`` read with bit 14 at 0. The entropy scoreboard runs non-strict
for the bring-up only: this leaf grades register state, not data.

Randomization (``SepSeededRng`` from the run seed, drawn before the first stimulus):
the order of the boot group, the EDN software port leg and the CSRNG software
instance leg, and the idle gap (0 to 16 clocks) before each poll read. The command
words, the mode codes and the checked values do not depend on the seed.

Checkers:
  CHK-EDN-BOOT   for each graded boot (AUTO_REQ_MODE true, then false) the first
                 ``HW_CMD_STS`` read with ``BOOT_MODE`` = 1 has ``AUTO_MODE`` = 0,
                 within 16 x the reference boot time t0.
  CHK-EDN-SW-HS  ``CMD_REG_RDY`` and ``CMD_RDY`` 1 before the command; ``CMD_ACK``
                 and ``CMD_RDY`` 1 after it; ``edn_cmd_req_done`` and vector bit 27
                 read 0 before the command, and 1 (a rise of bit 27) after it.
  CHK-EDN-INVSEQ the second instantiate through EDN sets CSRNG bit 14 and a write
                 of 0 clears it. Control: bit 14 reads 0 after the first command.
  CHK-CSRNG-SW   the same handshake for the CSRNG software instance (vector bit
                 23), and bit 14 on the second command. Control: bit 14 reads 0
                 after the first command.
The unstated effects are logged only (``OBS-EDN-*``, ``OBS-CSRNG-*``).
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env.sep_bit_watch import BitWatchTimeout, SepBitWatch
from env.sep_chk_log import SepChkLog
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_reg_meta import CSRNG, EDN, SEP_CPU_CTRL, sym
from env.sep_seeded_rng import SepSeededRng
from env.sep_trial_wait import TrialTimeout, wait_until
from sep_base_test import sep_base_test
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_drbg_mode_bringup_seq import drbg_bring_up
from seq_lib.sep_irq_aggregator_seq import IRQ_TABLE

TEST = "sep_drbg_cmd_sequence_rand_test"

MUBI_TRUE = 0x6
MUBI_FALSE = 0x9

EXT_TRNG_SRC_SEL = SEP_CPU_CTRL.addr("EXT_TRNG_SRC_SEL")

CSRNG_CTRL = sym("CSRNG_CTRL_REG_ADDR")
CSRNG_CMD_REQ = sym("CSRNG_CMD_REQ_REG_ADDR")
CSRNG_SW_CMD_STS = sym("CSRNG_SW_CMD_STS_REG_ADDR")
CSRNG_RECOV_ALERT_STS = sym("CSRNG_RECOV_ALERT_STS_REG_ADDR")
CSRNG_INTR_STATE = sym("CSRNG_INTR_STATE_REG_ADDR")
CSRNG_INTR_ENABLE = sym("CSRNG_INTR_ENABLE_REG_ADDR")
CSRNG_HW_EXC_STS = sym("CSRNG_HW_EXC_STS_REG_ADDR")
EDN_CTRL = sym("EDN_CTRL_REG_ADDR")
EDN_SW_CMD_REQ = sym("EDN_SW_CMD_REQ_REG_ADDR")
EDN_SW_CMD_STS = sym("EDN_SW_CMD_STS_REG_ADDR")
EDN_HW_CMD_STS = sym("EDN_HW_CMD_STS_REG_ADDR")
EDN_INTR_STATE = sym("EDN_INTR_STATE_REG_ADDR")
EDN_INTR_ENABLE = sym("EDN_INTR_ENABLE_REG_ADDR")
EDN_RECOV_ALERT_STS = sym("EDN_RECOV_ALERT_STS_REG_ADDR")

# Field bits from the generated register headers (csrng.rdl, edn.rdl).
CS_STS_RDY = CSRNG.fields("SW_CMD_STS")["CMD_RDY"]["bm"]
CS_STS_ACK = CSRNG.fields("SW_CMD_STS")["CMD_ACK"]["bm"]
CS_STS_STS = CSRNG.fields("SW_CMD_STS")["CMD_STS"]
CS_INVSEQ = CSRNG.fields("RECOV_ALERT_STS")["CMD_STAGE_INVALID_CMD_SEQ_ALERT"]["bm"]
CS_DONE = CSRNG.fields("INTR_STATE")["CS_CMD_REQ_DONE"]["bm"]
CS_HW_INST_EXC = CSRNG.fields("INTR_STATE")["CS_HW_INST_EXC"]["bm"]
ED_STS_REG_RDY = EDN.fields("SW_CMD_STS")["CMD_REG_RDY"]["bm"]
ED_STS_RDY = EDN.fields("SW_CMD_STS")["CMD_RDY"]["bm"]
ED_STS_ACK = EDN.fields("SW_CMD_STS")["CMD_ACK"]["bm"]
ED_STS_STS = EDN.fields("SW_CMD_STS")["CMD_STS"]
ED_BOOT_MODE = EDN.fields("HW_CMD_STS")["BOOT_MODE"]["bm"]
ED_AUTO_MODE = EDN.fields("HW_CMD_STS")["AUTO_MODE"]["bm"]
ED_DONE = EDN.fields("INTR_STATE")["EDN_CMD_REQ_DONE"]["bm"]
ED_ACK_ERR = EDN.fields("RECOV_ALERT_STS")["CSRNG_ACK_ERR"]["bm"]

# The instantiate word: the RDL reset value of EDN BOOT_INS_CMD (edn.adoc BOOT_INS_CMD).
CMD_INSTANTIATE = EDN.reset("BOOT_INS_CMD")

CSRNG_CTRL_ON = CSRNG.value("CTRL", ENABLE=MUBI_TRUE, SW_APP_ENABLE=MUBI_TRUE)


def _edn_ctrl(boot: bool, auto: bool, enable: bool) -> int:
    return EDN.value(
        "CTRL",
        EDN_ENABLE=MUBI_TRUE if enable else MUBI_FALSE,
        BOOT_REQ_MODE=MUBI_TRUE if boot else MUBI_FALSE,
        AUTO_REQ_MODE=MUBI_TRUE if auto else MUBI_FALSE,
        CMD_FIFO_RST=MUBI_FALSE,
    )


_IRQ = {s.name: s.agg_idx for s in IRQ_TABLE}
VEC_EDN_DONE = _IRQ["edn_cmd_req_done"]
VEC_CS_DONE = _IRQ["csrng_cmd_req_done"]
VEC_CS_HW_INST_EXC = _IRQ["csrng_hw_inst_exc"]

GROUPS = ("boot", "edn_sw", "csrng_sw")
N_GAPS = 256

# Outer caps of a first measurement (design rule: 20 x the clean value of the logs).
TRNG_RESET_CAP = 4_000
FIRST_CAP = 20_000
VEC_CAP = 2_000
BOUND_FACTOR = 16


@dataclass(frozen=True)
class Plan:
    seed: int
    groups: tuple[str, ...]
    gaps: tuple[int, ...]

    def describe(self) -> str:
        return f"groups={','.join(self.groups)} gaps[0:8]={list(self.gaps[:8])}"


def draw_plan(seed: int) -> Plan:
    """Every draw of the leaf, in a fixed order, with no simulator access."""
    rng = SepSeededRng(seed)
    groups = list(GROUPS)
    rng.shuffle(groups)
    gaps = tuple(rng.randrange(0, 17) for _ in range(N_GAPS))
    return Plan(seed, tuple(groups), gaps)


class _Reg(SepAxiRegDriver):
    _DRIVER_TAG = "DRBG"


def _field(value: int, meta: dict[str, int]) -> int:
    return (value & meta["bm"]) >> meta["bp"]


@pyuvm.test()
class sep_drbg_cmd_sequence_rand_test(sep_base_test):
    """EDN boot precedence, EDN and CSRNG software handshakes, invalid sequence alert."""

    required_evidence = (
        "CHK-EDN-BOOT",
        "CHK-EDN-SW-HS",
        "CHK-EDN-INVSEQ",
        "CHK-CSRNG-SW",
    )

    async def run_scenario(self) -> None:
        dut = cocotb.top
        await self.bring_up_no_cpu(park=("otbn", "aes", "hmac", "kmac", "abr"))
        self.reg = _Reg(self)
        await self.reg._wr(EXT_TRNG_SRC_SEL, 0)
        self.logger.info("BASELINE sw_reset_n=0x%02x ext_trng_src_sel=0x0", self.swrst.value)
        seed = self.random_seed()
        plan = draw_plan(seed)
        self.logger.info("PLAN seed=%d %s", seed, plan.describe())
        self.plan = plan
        self.chk = SepChkLog(self, TEST, seed)
        self.clk = SepBitWatch(dut.rst_ni, {"rst_ni": 0}, name="clk_count").start()
        self.vec = SepBitWatch(
            dut.sep_internal_interrupts_probe_o,
            {"edn_done": VEC_EDN_DONE, "cs_done": VEC_CS_DONE, "cs_exc": VEC_CS_HW_INST_EXC},
            name="sep_internal_interrupts_probe_o",
        ).start()
        self._gap_i = 0
        self.sb = None
        try:
            for group in plan.groups:
                if group == "boot":
                    await self._boot_group()
                elif group == "edn_sw":
                    await self._edn_sw_leg()
                else:
                    await self._csrng_sw_leg()
        finally:
            close_graded_window(self.logger)
            if self.sb is not None:
                self.sb.stop()
        await self.vec.stop()
        await self.clk.stop()
        self.chk.finish()

    # --- waits ----------------------------------------------------------------------
    def _now(self) -> int:
        return self.clk.clk

    def _next_gap(self) -> int:
        gap = self.plan.gaps[self._gap_i % N_GAPS]
        self._gap_i += 1
        return gap

    def _reader(self, addr: int):
        async def read() -> int:
            gap = self._next_gap()
            if gap:
                await ClockCycles(cocotb.top.clk_i, gap)
            return await self.reg._rd(addr)

        return read

    async def _wait(self, addr: int, mask: int, want: int, bound: int, what: str):
        """Poll ``addr`` with the drawn gaps until ``(value & mask) == want``.

        Returns ``(clocks, last value)``; raises ``TrialTimeout`` at the bound.
        """
        t0 = self._now()
        samples = await wait_until(self._reader(addr), self._now, mask, want, bound, what)
        return samples[-1][0] - t0, samples[-1][1]

    async def _wait_vec(self, mark, bit: str, bound: int) -> int:
        """Clocks from ``mark`` to the first rise of the vector bit after it. The caller
        reads the bit as 0 at the mark, so only a 0 -> 1 change counts."""
        rise = await self.vec.wait_rise(mark, bound, bit)
        return rise - mark.clk

    # --- clean start ----------------------------------------------------------------
    async def _wait_probe(self, sig, want_zero: bool, what: str) -> int:
        dut = cocotb.top
        for clk in range(TRNG_RESET_CAP):
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if (self.rd(sig, allow_unknown=True) == 0) == want_zero:
                return clk
        raise AssertionError(f"{what}: no change within {TRNG_RESET_CAP} clocks")

    async def _trng_reset(self) -> None:
        dut = cocotb.top
        if self.sb is not None:
            self.sb.stop()
            self.sb = None
        await self.swrst.park("trng")
        rise = await self._wait_probe(dut.trng_reset_active_probe_o, False, "trng reset rise")
        await RisingEdge(dut.clk_i)
        await self.swrst.release("trng")
        fall = await self._wait_probe(dut.trng_reset_active_probe_o, True, "trng reset fall")
        await RisingEdge(dut.clk_i)
        self.logger.info("TRNG reset: rise_clk=%d fall_clk=%d cap=%d", rise, fall, TRNG_RESET_CAP)

    async def _clean_start(self, group: str) -> int:
        """TRNG reset, bring-up without the EDN step, CSRNG enable. Returns bit 14."""
        close_graded_window(self.logger)
        await self._trng_reset()
        self.sb = await drbg_bring_up(self, edn_ctrl=None, strict=False)
        await self.reg._wr(CSRNG_CTRL, CSRNG_CTRL_ON)
        recov = await self.reg._rd(CSRNG_RECOV_ALERT_STS)
        bit14 = int(bool(recov & CS_INVSEQ))
        self.chk.ctrl("CLEAN-START", bit14 == 0, group=group, csrng_invseq=bit14)
        return bit14

    # --- boot group -----------------------------------------------------------------
    async def _boot(self, auto: bool, bound: int) -> tuple[int | None, int, int]:
        """One boot with BOOT_REQ_MODE true. Returns (clocks to BOOT_MODE or None, the
        HW_CMD_STS read that first shows BOOT_MODE, the CTRL word)."""
        off = _edn_ctrl(boot=True, auto=auto, enable=False)
        on = _edn_ctrl(boot=True, auto=auto, enable=True)
        open_graded_window(TEST, self.logger)
        await self.reg._wr(EDN_CTRL, off)
        await self.reg._wr(EDN_CTRL, on)
        try:
            clk, sts = await self._wait(
                EDN_HW_CMD_STS, ED_BOOT_MODE, ED_BOOT_MODE, bound, "boot_mode"
            )
        except TrialTimeout:
            close_graded_window(self.logger)
            return None, 0, on
        close_graded_window(self.logger)
        return clk, sts, on

    async def _boot_group(self) -> None:
        await self._clean_start("boot_ref")
        t0, sts, ctrl = await self._boot(auto=False, bound=FIRST_CAP)
        if t0 is None:
            self.chk.ok(
                "EDN-BOOT",
                False,
                run="reference",
                ctrl=f"0x{ctrl:04x}",
                reason=f"timeout:boot_mode bound={FIRST_CAP}",
            )
            return
        t0 = max(t0, 1)
        self.chk.obs("EDN-TSEED", tseed_clk=t0, auto_mode=int(bool(sts & ED_AUTO_MODE)))
        bound = BOUND_FACTOR * t0
        for auto in (True, False):
            await self._clean_start(f"boot_auto{int(auto)}")
            clk, sts, ctrl = await self._boot(auto=auto, bound=bound)
            fields = {
                "ctrl": f"0x{ctrl:04x}",
                "boot_mode": int(bool(sts & ED_BOOT_MODE)),
                "auto_mode": int(bool(sts & ED_AUTO_MODE)),
                "boot_clk": clk if clk is not None else "na",
                "clean": t0,
                "bound": bound,
                "rsvd": f"0x{sts & ~EDN.mask('HW_CMD_STS') & 0xFFFF_FFFF:x}",
            }
            if clk is None:
                fields["reason"] = f"timeout:boot_mode bound={bound}"
            self.chk.ok("EDN-BOOT", clk is not None and not sts & ED_AUTO_MODE, **fields)

    # --- EDN software port leg -----------------------------------------------------
    async def _edn_sw_leg(self) -> None:
        await self._clean_start("edn_sw")
        r = self.reg
        open_graded_window(TEST, self.logger)
        await r._wr(EDN_CTRL, _edn_ctrl(boot=False, auto=False, enable=False))
        await r._wr(EDN_CTRL, _edn_ctrl(boot=False, auto=False, enable=True))
        await r._wr(EDN_INTR_ENABLE, ED_DONE)
        enable = int(bool(await r._rd(EDN_INTR_ENABLE) & ED_DONE))
        rdy_mask = ED_STS_REG_RDY | ED_STS_RDY
        hs = {"cmd_reg_rdy": 0, "cmd_rdy": 0, "ack_done": 0, "rdy_done": 0, "edn_done": 0}
        hs.update({"enable": enable, "vec27": 0})
        # Before the command: edn_cmd_req_done (W1C) and vector bit 27 read 0, so the
        # rise after the command is a change the command causes.
        await r._wr(EDN_INTR_STATE, ED_DONE)
        hs["edn_done_pre0"] = int(not await r._rd(EDN_INTR_STATE) & ED_DONE)
        hs["vec27_pre0"] = int(self.vec.level("edn_done") == 0)
        reason = ""
        t_cmd = None
        try:
            _, pre = await self._wait(EDN_SW_CMD_STS, rdy_mask, rdy_mask, FIRST_CAP, "edn_rdy")
            hs["cmd_reg_rdy"] = int(bool(pre & ED_STS_REG_RDY))
            hs["cmd_rdy"] = int(bool(pre & ED_STS_RDY))
            t_wr = self._now()
            m = self.vec.mark()
            await r._wr(EDN_SW_CMD_REQ, CMD_INSTANTIATE)
            ack0 = await r._rd(EDN_SW_CMD_STS)
            self.chk.obs("EDN-ACK0", ack_first_read=int(bool(ack0 & ED_STS_ACK)))
            want = ED_STS_ACK | ED_STS_RDY
            _, done = await self._wait(EDN_SW_CMD_STS, want, want, FIRST_CAP, "edn_ack")
            t_cmd = max(self._now() - t_wr, 1)
            hs["ack_done"] = int(bool(done & ED_STS_ACK))
            hs["rdy_done"] = int(bool(done & ED_STS_RDY))
            state = await r._rd(EDN_INTR_STATE)
            hs["edn_done"] = int(bool(state & ED_DONE))
            vclk = await self._wait_vec(m, "edn_done", VEC_CAP)
            hs["vec27"] = 1
            hs["vec_clk"] = vclk
            self.chk.obs("EDN-STS", cmd_sts=_field(done, ED_STS_STS), t_cmd=t_cmd)
            self.chk.obs("EDN-VEC", vec23=self.vec.level("cs_done"))
            await r._wr(EDN_INTR_STATE, ED_DONE)
        except TrialTimeout as exc:
            reason = f"timeout:{exc.what} bound={exc.bound}"
        except BitWatchTimeout:
            reason = f"timeout:vec27 bound={VEC_CAP}"
        close_graded_window(self.logger)
        if reason:
            hs["reason"] = reason
        self.chk.ok(
            "EDN-SW-HS",
            not reason
            and all(
                hs[k] == 1
                for k in (
                    "cmd_reg_rdy",
                    "cmd_rdy",
                    "ack_done",
                    "rdy_done",
                    "edn_done",
                    "enable",
                    "vec27",
                    "edn_done_pre0",
                    "vec27_pre0",
                )
            ),
            **hs,
        )
        if reason:
            self.chk.ok("EDN-INVSEQ", False, reason=f"no_first_command:{reason}")
            return
        await self._edn_invseq(t_cmd)

    async def _edn_invseq(self, t_cmd: int) -> None:
        r = self.reg
        bound = BOUND_FACTOR * t_cmd
        first = int(bool(await r._rd(CSRNG_RECOV_ALERT_STS) & CS_INVSEQ))
        self.chk.ctrl("EDN-INVSEQ", first == 0, ctrl_first_invseq=first)
        open_graded_window(TEST, self.logger)
        rdy_mask = ED_STS_REG_RDY | ED_STS_RDY
        invseq = 0
        cleared = 0
        reason = ""
        try:
            await self._wait(EDN_SW_CMD_STS, rdy_mask, rdy_mask, bound, "edn_rdy2")
            await r._wr(EDN_SW_CMD_REQ, CMD_INSTANTIATE)
            _, recov = await self._wait(
                CSRNG_RECOV_ALERT_STS, CS_INVSEQ, CS_INVSEQ, bound, "csrng_invseq"
            )
            invseq = int(bool(recov & CS_INVSEQ))
        except TrialTimeout as exc:
            reason = f"timeout:{exc.what} bound={exc.bound}"
        sts = await r._rd(EDN_SW_CMD_STS)
        self.chk.obs(
            "EDN-INVSEQ",
            cmd_ack=int(bool(sts & ED_STS_ACK)),
            cmd_sts=_field(sts, ED_STS_STS),
            ack_err=int(bool(await r._rd(EDN_RECOV_ALERT_STS) & ED_ACK_ERR)),
            hw_exc=f"0x{await r._rd(CSRNG_HW_EXC_STS):x}",
            hw_inst_exc=int(bool(await r._rd(CSRNG_INTR_STATE) & CS_HW_INST_EXC)),
            vec25=self.vec.level("cs_exc"),
            cmd_rdy_after=int(bool(sts & ED_STS_RDY)),
        )
        await r._wr(CSRNG_RECOV_ALERT_STS, 0)
        after = await r._rd(CSRNG_RECOV_ALERT_STS)
        cleared = int(not after & CS_INVSEQ)
        close_graded_window(self.logger)
        fields = {
            "ctrl_first_invseq": first,
            "csrng_invseq": invseq,
            "cleared_by_write0": cleared,
            "bound": bound,
        }
        if reason:
            fields["reason"] = reason
        self.chk.ok("EDN-INVSEQ", not reason and invseq == 1 and cleared == 1, **fields)

    # --- CSRNG software instance leg ---------------------------------------------
    async def _csrng_sw_leg(self) -> None:
        await self._clean_start("csrng_sw")
        r = self.reg
        open_graded_window(TEST, self.logger)
        await r._wr(CSRNG_INTR_ENABLE, CS_DONE)
        enable = int(bool(await r._rd(CSRNG_INTR_ENABLE) & CS_DONE))
        hs = {"cmd_rdy": 0, "ack": 0, "rdy_done": 0, "done": 0, "enable": enable, "vec23": 0}
        # Before the command: cs_cmd_req_done (W1C) and vector bit 23 read 0, so the
        # rise after the command is a change the command causes.
        await r._wr(CSRNG_INTR_STATE, CS_DONE)
        hs["done_pre0"] = int(not await r._rd(CSRNG_INTR_STATE) & CS_DONE)
        hs["vec23_pre0"] = int(self.vec.level("cs_done") == 0)
        reason = ""
        first = 1
        invseq = 0
        cleared = 0
        try:
            _, pre = await self._wait(CSRNG_SW_CMD_STS, CS_STS_RDY, CS_STS_RDY, FIRST_CAP, "rdy")
            hs["cmd_rdy"] = int(bool(pre & CS_STS_RDY))
            t_wr = self._now()
            m = self.vec.mark()
            await r._wr(CSRNG_CMD_REQ, CMD_INSTANTIATE)
            ack0 = await r._rd(CSRNG_SW_CMD_STS)
            self.chk.obs("CSRNG-ACK0", ack_first_read=int(bool(ack0 & CS_STS_ACK)))
            want = CS_STS_ACK | CS_STS_RDY
            _, done = await self._wait(CSRNG_SW_CMD_STS, want, want, FIRST_CAP, "ack")
            t_cmd = max(self._now() - t_wr, 1)
            hs["ack"] = int(bool(done & CS_STS_ACK))
            hs["rdy_done"] = int(bool(done & CS_STS_RDY))
            state = await r._rd(CSRNG_INTR_STATE)
            hs["done"] = int(bool(state & CS_DONE))
            hs["vec_clk"] = await self._wait_vec(m, "cs_done", VEC_CAP)
            hs["vec23"] = 1
            self.chk.obs("CSRNG-STS", cmd_sts=_field(done, CS_STS_STS), t_cmd=t_cmd)
            await r._wr(CSRNG_INTR_STATE, CS_DONE)
            # Control: bit 14 is 0 after the first command.
            first = int(bool(await r._rd(CSRNG_RECOV_ALERT_STS) & CS_INVSEQ))
            self.chk.ctrl("CSRNG-SW", first == 0, ctrl_first_invseq=first)
            bound = BOUND_FACTOR * t_cmd
            hs["bound"] = bound
            await self._wait(CSRNG_SW_CMD_STS, CS_STS_RDY, CS_STS_RDY, bound, "rdy2")
            await r._wr(CSRNG_CMD_REQ, CMD_INSTANTIATE)
            _, recov = await self._wait(CSRNG_RECOV_ALERT_STS, CS_INVSEQ, CS_INVSEQ, bound, "inv")
            invseq = int(bool(recov & CS_INVSEQ))
            sts = await r._rd(CSRNG_SW_CMD_STS)
            self.chk.obs(
                "CSRNG-INVSEQ",
                cmd_sts=_field(sts, CS_STS_STS),
                hw_exc=f"0x{await r._rd(CSRNG_HW_EXC_STS):x}",
            )
            await r._wr(CSRNG_RECOV_ALERT_STS, 0)
            cleared = int(not await r._rd(CSRNG_RECOV_ALERT_STS) & CS_INVSEQ)
        except TrialTimeout as exc:
            reason = f"timeout:{exc.what} bound={exc.bound}"
        except BitWatchTimeout:
            reason = f"timeout:vec23 bound={VEC_CAP}"
        close_graded_window(self.logger)
        hs.update({"ctrl_first_invseq": first, "invseq": invseq, "cleared_by_write0": cleared})
        if reason:
            hs["reason"] = reason
        ok = not reason and all(
            hs[k] == 1
            for k in (
                "cmd_rdy",
                "ack",
                "rdy_done",
                "done",
                "enable",
                "vec23",
                "invseq",
                "done_pre0",
                "vec23_pre0",
            )
        )
        self.chk.ok("CSRNG-SW", ok and first == 0 and cleared == 1, **hs)
