# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""An unsupported SHAKE or cSHAKE strength raises kmac_err and does not start, and err_processed recovers.

Contract (``vendor/lowRISC/opentitan/overlay/regs/kmac/regs/gen/adoc/kmac.adoc``):
``CFG_SHADOWED.kstrength`` (lines 177-181): with mode SHAKE or cSHAKE only the
strengths 128 and 256 are legal, and another strength gives an error when
hashing starts. ``CFG_SHADOWED.en_unsupported_modestrength`` (lines 112-118):
with the bit clear KMAC does not propagate ``CMD.start`` to the SHA3 engine;
with the bit set it moves forward. ``CMD.err_processed`` (lines 195-197) lets
the state machine return to its reset state. ``ERR_CODE`` (lines 343-345) is 0
at reset and holds the cause after ``kmac_err``; its value is logged and only
"non-zero" is graded. Mode and command codes come from
``vendor/lowRISC/opentitan/upstream/hw/ip/kmac/data/kmac.hjson``.

The 20 cells are mode {SHAKE, cSHAKE} x strength {128, 224, 256, 384, 512} x
``en_unsupported_modestrength`` {0, 1}, with ``kmac_en`` = 0 in EDN entropy
mode. The 8 supported cells are controls and are not graded here. Each blocked
start is followed by ``CMD.err_processed``, a write-one clear of ``kmac_err``
and a legal SHA3-256 hash of a drawn message.

Checkers:
  CHK-KMAC-UNSUP     en bit 0, unsupported strength: after CMD.start kmac_err=1,
                     sha3_idle=1, sha3_absorb=0, kmac_done=0 and ERR_CODE != 0;
                     STATUS still idle and not absorbing after a hold of t_clean.
                     kmac_err and ERR_CODE read 0 before the start.
  CHK-KMAC-UNSUP-EN  en bit 1, unsupported strength: STATUS.sha3_absorb=1 after
                     CMD.start. kmac_err is logged only.
  CHK-KMAC-ERRPROC   after err_processed and the W1C: kmac_err=0, sha3_idle=1;
                     the next SHA3-256 digest equals the golden and kmac_err
                     still reads 0.

Controls and observations: ``CTRL-KMAC-UNSUP`` per supported cell (no
kmac_err, absorb reached; its start time sets t_clean). ``OBS-KMAC-ERRCODE``
logs each error code. ``OBS-KMAC-UNSUP-EN-ERR`` logs kmac_err of the enabled
group.

Time bounds: t_clean is the longest clean start time of the supported group,
measured from the ``CMD.start`` write to the read that shows absorb. The
kmac_err wait and the enabled-group absorb wait are ``_ERR_BOUND_MULT`` x
t_clean. The hash waits of the recovery use the outer limit ``_OUTER_CLK`` and
log the measured clocks.

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense
+esrc_noise_force``. RAND-REP: the seed draws the three cell orders and the
recovery messages; the 20 cells are the same on every seed.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.sep_chk_log import SepChkLog
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_kmac_golden import encode_string, sha3
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import KMAC
from seq_lib.sep_kmac_seq import (
    KMAC_CFG_SHADOWED,
    KMAC_CMD,
    KMAC_CMD_DONE,
    KMAC_CMD_PROCESS,
    KMAC_CMD_START,
    KMAC_ERR_CODE,
    KMAC_INTR_STATE,
    KMAC_MODE,
    KMAC_STATUS,
    KMAC_STRENGTH,
    SepKmac,
    build_kmac_cfg,
)

TEST = "sep_kmac_unsupported_cfg_inject_test"

_IDLE = KMAC.field_mask("STATUS", "sha3_idle")
_ABSORB = KMAC.field_mask("STATUS", "sha3_absorb")
_SQUEEZE = KMAC.field_mask("STATUS", "sha3_squeeze")
_STAGE_MASK = _IDLE | _ABSORB | _SQUEEZE
_DONE = KMAC.field_mask("INTR_STATE", "kmac_done")
_ERR = KMAC.field_mask("INTR_STATE", "kmac_err")
_INTR_MASK = KMAC.mask32("INTR_STATE")
_ERR_CODE_MASK = KMAC.field_mask("ERR_CODE", "err_code")
_CMD_ERR_PROCESSED = KMAC.field_mask("CMD", "err_processed")
_EN_UNSUP_LSB = KMAC.field_lsb("CFG_SHADOWED", "en_unsupported_modestrength")

# cSHAKE PREFIX of the open helper: empty function name and empty
# customization string, encode_string("") || encode_string("").
_CSHAKE_EMPTY_PREFIX = encode_string(b"") + encode_string(b"")

_XOF_MODES = ("shake", "cshake")
# kmac.adoc CFG_SHADOWED.kstrength (lines 177-181): only 128 and 256 are legal
# for SHAKE and cSHAKE.
_LEGAL_STRENGTHS = (128, 256)
_UNSUP_STRENGTHS = (224, 384, 512)
_SUPPORTED = tuple((m, s, e) for m in _XOF_MODES for s in _LEGAL_STRENGTHS for e in (0, 1))
_BLOCKED = tuple((m, s) for m in _XOF_MODES for s in _UNSUP_STRENGTHS)
_MSG_MAX_BYTES = 100
_RECOVER_STRENGTH = 256
_RECOVER_DIGEST_WORDS = _RECOVER_STRENGTH // 32

# Bound multiples and the outer limit of the clean-time measurements.
_ERR_BOUND_MULT = 8
_OUTER_CLK = 20_000
_RESET_EDGE_CLK = 200


@dataclass(frozen=True)
class Plan:
    supported: tuple[tuple[str, int, int], ...]
    blocked: tuple[tuple[str, int], ...]
    enabled: tuple[tuple[str, int], ...]
    messages: tuple[bytes, ...]


def _draw_message(rng: SepSeededRng, nbytes: int) -> bytes:
    """``nbytes`` of test data whose 32-bit words differ from each other and from 0."""
    words: list[int] = []
    while len(words) * 4 < nbytes:
        w = rng.getrandbits(32)
        if w and w not in words:
            words.append(w)
    return b"".join(w.to_bytes(4, "little") for w in words)[:nbytes]


def draw_plan(seed: int) -> Plan:
    """The whole plan of one seed. Pure: no simulator access."""
    rng = SepSeededRng(seed)
    supported = list(_SUPPORTED)
    rng.shuffle(supported)
    blocked = list(_BLOCKED)
    rng.shuffle(blocked)
    enabled = list(_BLOCKED)
    rng.shuffle(enabled)
    messages = tuple(_draw_message(rng, rng.randrange(0, _MSG_MAX_BYTES + 1)) for _ in blocked)
    return Plan(tuple(supported), tuple(blocked), tuple(enabled), messages)


def _cfg_word(mode: str, strength: int, en_unsup: int) -> int:
    """CFG_SHADOWED: kmac_en 0, sideload 0, EDN entropy mode, entropy_ready 1."""
    return build_kmac_cfg(
        mode=KMAC_MODE[mode], kstrength=KMAC_STRENGTH[strength], kmac_en=False, sideload=False
    ) | (int(en_unsup) << _EN_UNSUP_LSB)


def _bits(v: int, m: int) -> int:
    return int(bool(v & m))


@pyuvm.test()
class sep_kmac_unsupported_cfg_inject_test(sep_base_test):
    """Unsupported SHAKE/cSHAKE strengths raise kmac_err and stay idle; err_processed recovers."""

    required_evidence = ("CHK-KMAC-UNSUP", "CHK-KMAC-UNSUP-EN", "CHK-KMAC-ERRPROC")

    # --- clocks and register access -----------------------------------------
    def _now_clk(self) -> int:
        return int(get_sim_time("ps")) // self._clk_ps

    async def _rd(self, addr: int) -> int:
        return await self.kmac._rd(addr)

    async def _wr(self, addr: int, data: int) -> None:
        await self.kmac._wr(addr, data)

    async def _write_cfg(self, word: int) -> None:
        await self._wr(KMAC_CFG_SHADOWED, word)
        await self._wr(KMAC_CFG_SHADOWED, word)

    async def _poll(self, addr: int, mask: int, t0: int, bound: int) -> tuple[bool, int, int]:
        """Read ``addr`` until a bit of ``mask`` is set or ``bound`` clocks pass from ``t0``.

        Returns (seen, last value, clocks from ``t0`` to the read that showed it).
        """
        value = 0
        while True:
            value = await self._rd(addr)
            elapsed = self._now_clk() - t0
            if value & mask:
                return True, value, elapsed
            if elapsed > bound:
                return False, value, elapsed
            await ClockCycles(cocotb.top.clk_i, 4)

    async def _wait_probe(self, sig, level: int, bound: int) -> None:
        for _ in range(bound):
            await RisingEdge(cocotb.top.clk_i)
            await ReadOnly()
            if self.rd_known(sig) == level:
                return
        raise AssertionError(f"{sig._name} did not read {level} within {bound} clocks")

    async def _reset_kmac(self) -> None:
        """One KMAC reset: bit 4 of SW_RESET_N low, then high, then idle."""
        probe = cocotb.top.kmac_gated_rst_n_probe_o
        await self.swrst.park("kmac")
        await self._wait_probe(probe, 0, _RESET_EDGE_CLK)
        await self.swrst.release("kmac")
        await self._wait_probe(probe, 1, _RESET_EDGE_CLK)
        await RisingEdge(cocotb.top.clk_i)
        ok, status, _ = await self._poll(KMAC_STATUS, _IDLE, self._now_clk(), _OUTER_CLK)
        if not ok:
            raise AssertionError(f"KMAC not idle after reset (STATUS=0x{status:08x})")

    async def _arm_cell(self, mode: str, strength: int, en_unsup: int) -> tuple[int, int]:
        """Reset, read the reset values, write PREFIX (cSHAKE) and CFG_SHADOWED twice."""
        close_graded_window()
        await self._reset_kmac()
        if self._graded:
            open_graded_window(TEST)
        pre_intr = await self._rd(KMAC_INTR_STATE)
        pre_code = await self._rd(KMAC_ERR_CODE)
        if mode == "cshake":
            await self.kmac._write_prefix(_CSHAKE_EMPTY_PREFIX)
        await self._write_cfg(_cfg_word(mode, strength, en_unsup))
        return pre_intr, pre_code

    # --- scenario -------------------------------------------------------------
    async def run_scenario(self) -> None:
        self._clk_ps = int(round(self.cfg.sys_clk_period_ns * 1000))
        self._graded = False
        # Step 1: OTBN, AES, HMAC and ABR held in reset; KMAC and TRNG released.
        await self.bring_up_no_cpu(park=("otbn", "aes", "hmac", "abr"))
        await self.bring_up_entropy(strict=True, score_km=False)
        self.start_fifo_drain()
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        baseline = await self.swrst.read_back()
        self.logger.info("SW_RESET_N baseline=0x%08x", baseline)

        seed = self.random_seed()
        self.kmac = SepKmac(self)
        self.chk = SepChkLog(self, TEST, seed)
        plan = draw_plan(seed)
        self.logger.info(
            "PLAN seed=%d supported=%s blocked=%s enabled=%s msg_len=%s",
            seed,
            ",".join(f"{m}{s}/e{e}" for m, s, e in plan.supported),
            ",".join(f"{m}{s}" for m, s in plan.blocked),
            ",".join(f"{m}{s}" for m, s in plan.enabled),
            ",".join(str(len(b)) for b in plan.messages),
        )

        t_clean = await self._supported_group(seed, plan)
        blocked_absorb = await self._blocked_group(seed, plan, t_clean)
        await self._enabled_group(seed, plan, t_clean, blocked_absorb)

        self._graded = False
        close_graded_window()
        await self.stop_fifo_drain()
        assert self.drbg_sb.report()
        self.chk.finish()

    async def _supported_group(self, seed: int, plan: Plan) -> int:
        """Steps 3-4: the 8 legal cells reach absorb with no kmac_err; t_clean."""
        starts: list[int] = []
        for mode, strength, en in plan.supported:
            await self._arm_cell(mode, strength, en)
            t0 = self._now_clk()
            await self._wr(KMAC_CMD, KMAC_CMD_START)
            seen, status, clk = await self._poll(KMAC_STATUS, _ABSORB, t0, _OUTER_CLK)
            intr = await self._rd(KMAC_INTR_STATE)
            err = _bits(intr, _ERR)
            ok = seen and err == 0
            self.chk.ctrl(
                "KMAC-UNSUP",
                ok,
                seed=seed,
                mode=mode,
                kstrength=strength,
                en_unsup=en,
                err=err,
                absorb=_bits(status, _ABSORB),
                start_clk=clk,
                bound=_OUTER_CLK,
            )
            if ok:
                starts.append(clk)
        # With no clean start the controls above already logged CTRL-MISSING and
        # fail the leaf; the outer limit then stands in for t_clean.
        t_clean = max(starts) if starts else _OUTER_CLK
        self.logger.info(
            "t_clean seed=%d t_clean=%d starts=%s", seed, t_clean, ",".join(map(str, starts))
        )
        return t_clean

    async def _blocked_group(self, seed: int, plan: Plan, t_clean: int) -> dict:
        """Steps 5-6: each unsupported cell with en bit 0, then its recovery."""
        self._graded = True
        open_graded_window(TEST)
        bound = _ERR_BOUND_MULT * t_clean
        absorb_of: dict[tuple[str, int], int] = {}
        for (mode, strength), msg in zip(plan.blocked, plan.messages):
            cell = dict(seed=seed, mode=mode, kstrength=strength, en_unsup=0)
            pre_intr, pre_code = await self._arm_cell(mode, strength, 0)
            t0 = self._now_clk()
            await self._wr(KMAC_CMD, KMAC_CMD_START)
            seen, intr, err_clk = await self._poll(KMAC_INTR_STATE, _ERR, t0, bound)
            if not seen:
                status = await self._rd(KMAC_STATUS)
                absorb_of[(mode, strength)] = _bits(status, _ABSORB)
                self.chk.ok(
                    "KMAC-UNSUP",
                    False,
                    **cell,
                    reason="timeout",
                    bound=bound,
                    err=0,
                    absorb=_bits(status, _ABSORB),
                    idle=_bits(status, _IDLE),
                )
                continue
            status1 = await self._rd(KMAC_STATUS)
            intr1 = await self._rd(KMAC_INTR_STATE)
            code1 = await self._rd(KMAC_ERR_CODE) & _ERR_CODE_MASK
            h0 = self._now_clk()
            await ClockCycles(cocotb.top.clk_i, t_clean)
            status2 = await self._rd(KMAC_STATUS)
            code2 = await self._rd(KMAC_ERR_CODE) & _ERR_CODE_MASK
            hold_clk = self._now_clk() - h0
            absorb = _bits(status1, _ABSORB) | _bits(status2, _ABSORB)
            absorb_of[(mode, strength)] = absorb
            ok = (
                (pre_intr & _ERR) == 0
                and (pre_code & _ERR_CODE_MASK) == 0
                and _bits(intr1, _ERR) == 1
                and _bits(status1, _IDLE) == 1
                and _bits(status2, _IDLE) == 1
                and absorb == 0
                and _bits(intr1, _DONE) == 0
                and code1 != 0
                and code2 != 0
            )
            self.chk.ok(
                "KMAC-UNSUP",
                ok,
                **cell,
                pre_err=_bits(pre_intr, _ERR),
                pre_code=f"0x{pre_code & _ERR_CODE_MASK:x}",
                err=_bits(intr1, _ERR),
                absorb=absorb,
                idle=_bits(status1, _IDLE) & _bits(status2, _IDLE),
                done=_bits(intr1, _DONE),
                err_code_nonzero=int(code1 != 0 and code2 != 0),
                err_clk=err_clk,
                hold_clk=hold_clk,
                status=f"0x{status1 & _STAGE_MASK:x}/0x{status2 & _STAGE_MASK:x}",
                intr_rsvd=f"0x{intr1 & ~_INTR_MASK & 0xFFFF_FFFF:x}",
            )
            self.chk.obs(
                "KMAC-ERRCODE", seed=seed, mode=mode, kstrength=strength, err_code=f"0x{code1:x}"
            )
            await self._recover(seed, mode, strength, msg)
        return absorb_of

    async def _recover(self, seed: int, mode: str, strength: int, msg: bytes) -> None:
        """Step 6: err_processed, W1C of kmac_err, then a SHA3-256 hash of ``msg``."""
        fields = dict(seed=seed, mode=mode, kstrength=strength, len=len(msg))
        await self._wr(KMAC_CMD, _CMD_ERR_PROCESSED)
        await self._wr(KMAC_INTR_STATE, _ERR)
        intr = await self._rd(KMAC_INTR_STATE)
        status = await self._rd(KMAC_STATUS)
        err_cleared = int(_bits(intr, _ERR) == 0)
        idle = _bits(status, _IDLE)

        await self._write_cfg(_cfg_word("sha3", _RECOVER_STRENGTH, 0))
        t0 = self._now_clk()
        await self._wr(KMAC_CMD, KMAC_CMD_START)
        seen, status, clk = await self._poll(KMAC_STATUS, _ABSORB, t0, _OUTER_CLK)
        if not seen:
            await self._fail_recover(fields, err_cleared, idle, "timeout_absorb", clk)
            return
        await self.kmac._push_msg_bytes(msg)
        t1 = self._now_clk()
        await self._wr(KMAC_CMD, KMAC_CMD_PROCESS)
        seen, status, sq_clk = await self._poll(KMAC_STATUS, _SQUEEZE, t1, _OUTER_CLK)
        if seen:
            seen, intr, _ = await self._poll(KMAC_INTR_STATE, _DONE, t1, _OUTER_CLK)
        if not seen:
            await self._fail_recover(fields, err_cleared, idle, "timeout_squeeze", sq_clk)
            return
        digest = await self.kmac.read_digest(_RECOVER_DIGEST_WORDS)
        await self._wr(KMAC_CMD, KMAC_CMD_DONE)
        err_after = _bits(await self._rd(KMAC_INTR_STATE), _ERR)
        # FIPS 202 SHA3-256 (kmac.hjson line 264), little-endian STATE words.
        gold = sha3(msg, _RECOVER_STRENGTH)
        golden = [int.from_bytes(gold[i : i + 4], "little") for i in range(0, len(gold), 4)]
        match = digest == golden
        ok = err_cleared == 1 and idle == 1 and match and err_after == 0
        self.chk.ok(
            "KMAC-ERRPROC",
            ok,
            **fields,
            err_cleared=err_cleared,
            idle=idle,
            digest_eq_golden=int(match),
            err_after=err_after,
            squeeze_clk=sq_clk,
            digest="" if match else ":".join(f"{w:08x}" for w in digest),
            golden="" if match else ":".join(f"{w:08x}" for w in golden),
        )

    async def _fail_recover(self, fields: dict, err_cleared: int, idle: int, why: str, clk: int):
        self.chk.ok(
            "KMAC-ERRPROC",
            False,
            **fields,
            err_cleared=err_cleared,
            idle=idle,
            reason=why,
            clk=clk,
            bound=_OUTER_CLK,
        )
        close_graded_window()
        await self._reset_kmac()
        open_graded_window(TEST)

    async def _enabled_group(self, seed: int, plan: Plan, t_clean: int, blocked_absorb: dict):
        """Step 7: each unsupported cell with en bit 1 reaches absorb."""
        bound = _ERR_BOUND_MULT * t_clean
        for mode, strength in plan.enabled:
            pre_intr, pre_code = await self._arm_cell(mode, strength, 1)
            t0 = self._now_clk()
            await self._wr(KMAC_CMD, KMAC_CMD_START)
            seen, status, clk = await self._poll(KMAC_STATUS, _ABSORB, t0, bound)
            intr = await self._rd(KMAC_INTR_STATE)
            self.chk.ok(
                "KMAC-UNSUP-EN",
                seen,
                seed=seed,
                mode=mode,
                kstrength=strength,
                en_unsup=1,
                absorb=_bits(status, _ABSORB),
                absorb_clk=clk,
                bound=bound,
                pre_err=_bits(pre_intr, _ERR),
                pre_code=f"0x{pre_code & _ERR_CODE_MASK:x}",
                ctrl_absorb=blocked_absorb.get((mode, strength), "na"),
                **({} if seen else {"reason": "timeout"}),
            )
            self.chk.obs(
                "KMAC-UNSUP-EN-ERR", seed=seed, mode=mode, kstrength=strength, err=_bits(intr, _ERR)
            )
        self._graded = False
        close_graded_window()
        await self._reset_kmac()
