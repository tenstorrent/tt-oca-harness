# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared leaf helpers of the Phase 3 eFuse, lifecycle and SEC_DIS tests.

The tests of the VPLAN area "eFuse, lifecycle, SEC_DIS, locked-field, Phase 3"
use these helpers; ``env/sep_efuse_plan.py`` holds their seed plans and goldens.

* ``SepEfuseFd``: the frontdoor (CPU-side bench master of ``lsu_stub_all_live``).
  ``rd``/``wr`` are 32-bit accesses that fail on a response that is not OKAY;
  ``rd64``/``wr64`` are 64-bit single beats; ``access`` returns the sequence of an
  access whose response the leaf grades or logs itself.
* ``chk_bind``: CHK-BIND of every leaf that makes a SEC_DIS go. The bound digest is
  read from the simulator handle of the bench parameter only; a build that does not
  show the handle fails the leaf with ``CHK-HOOK FAIL``.
* ``hook_fail``: ``CHK-HOOK FAIL`` and the leaf verdict (the later steps are not
  graded).
* ``log_line``: a ``<tag> LOG seed=<n> k=v ...`` line. It has no PASS token, so the
  evidence filter does not count it.
* ``hold_strap`` / ``StrapHold``: ``secure_tm_req_i`` (bench port
  ``test_en_strap_i``) held from before the first reset release, and changed only
  while ``rst_ni`` is low.
* ``rst_pulse``: a cold reset with the clocks running and no wait for sense, so no
  post-sense backdoor compare of the base test runs.
* ``clocks_to_sense`` / ``SenseClock``: clocks from the ``rst_ni`` release to the
  ``sep_fuse_sense_done_o`` rise (the sense time of the VPLAN Time rule).
* ``set_shadow_golden``: the post-sense shadow golden of the base test after a
  program (the staged image with the programmed bits, or the bank content).
* ``wait_bit``, ``sig_bits``, ``probe_word``, ``probe_words``, ``tap_words``:
  bounded single-bit waits and packed-probe decode.
* ``sec_dis_go``, ``match_read``, ``feat_ctrl_read``, ``direct_word``: token,
  ``FEAT_CTRL`` and direct OTP word accesses.
"""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Sequence
from typing import Any

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from sep_reg_meta import SEP_LIFECYCLE_CTRL
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_efuse_direct_read_seq import sep_efuse_direct_read_seq

from env.sep_axi_agent import SepAxiOp
from env.sep_efuse_plan import (
    CH_SEC_DIS,
    MATCH_ADDR,
    MATCH_STATUS_MASK,
    poll_code,
    token_go,
    write_token,
)

M32 = 0xFFFF_FFFF
FEAT_CTRL_ADDR = SEP_LIFECYCLE_CTRL.addr("FEAT_CTRL")

# Bench net that carries the bound SEC_DIS expected digest (``tb/tb_top.sv``).
SEC_DIS_DIGEST_HANDLE = "sec_dis_digest_probe_o"
# SHA-256 of 32 zero bytes, read as the 256-bit value of FIPS 180-4.
SEC_DIS_ZERO_DIGEST = int.from_bytes(hashlib.sha256(bytes(32)).digest(), "big")
# Clocks rst_ni stays low in a cold reset of these tests.
RST_HOLD = 20


# --------------------------------------------------------------------------
# Frontdoor
# --------------------------------------------------------------------------


class SepEfuseFd(SepAxiRegDriver):
    """Frontdoor register access of the eFuse/lifecycle leaves."""

    _DRIVER_TAG = "FD"

    async def access(
        self,
        op: SepAxiOp,
        addr: int,
        data: int = 0,
        *,
        length: int = 4,
        ungraded_read: bool = False,
        unverified_write: bool = False,
        allow_timeout: bool = False,
    ) -> SepAxiAccessSeq:
        """One single-beat access; the leaf reads ``resp_ok``/``resp_code``/``rdata``.

        ``ungraded_read`` and ``unverified_write`` let a response that is not OKAY
        pass the scoreboard, for an access whose effect or data the leaf grades.
        """
        seq = SepAxiAccessSeq(
            f"fd_{op.value}_0x{addr:08x}",
            op=op,
            addr=addr,
            wdata=data,
            length=length,
            size=2 if length == 4 else None,
            allow_ungraded_read_resp=ungraded_read and op is SepAxiOp.READ,
            allow_unverified_write_resp=unverified_write and op is SepAxiOp.WRITE,
            allow_timeout=allow_timeout,
        )
        await self.test.start_seq(seq)
        return seq

    async def rd(self, addr: int) -> int:
        """32-bit read; fails on a response that is not OKAY."""
        return (await self._read_access(addr, size=2, length=4)) & M32

    async def wr(self, addr: int, data: int) -> None:
        """32-bit write; fails on a response that is not OKAY."""
        await self._write_access(addr, data & M32, size=2, length=4)

    async def rd64(self, addr: int) -> int:
        return await self._read_access(addr, size=None, length=8)

    async def wr64(self, addr: int, data: int) -> None:
        await self._write_access(addr, data, size=None, length=8)

    async def rd_graded_by_data(self, addr: int) -> tuple[int, int]:
        """32-bit read whose response the leaf grades: (response code, data)."""
        seq = await self.access(SepAxiOp.READ, addr, ungraded_read=True)
        return int(seq.resp_code), seq.rdata & M32

    async def wr_graded_by_readback(self, addr: int, data: int, *, length: int = 4) -> int:
        """Write whose effect the leaf grades by a readback: the response code."""
        seq = await self.access(SepAxiOp.WRITE, addr, data, length=length, unverified_write=True)
        return int(seq.resp_code)

    async def feat_ctrl(self) -> int:
        """``SEP_LIFECYCLE_CTRL.FEAT_CTRL`` as one 64-bit read."""
        return await self.rd64(FEAT_CTRL_ADDR)

    async def match(self, ch: str) -> int:
        """``token_match_status`` of channel ``ch``."""
        return (await self.rd(MATCH_ADDR[ch])) & MATCH_STATUS_MASK


async def direct_word(test: Any, word: int) -> int:
    """OTP word ``word`` through the frontdoor read interface (``sep_efuse_direct_read_seq``)."""
    seq = sep_efuse_direct_read_seq(word)
    await test.start_seq(seq)
    if seq.rdata is None:
        raise AssertionError(f"direct read of OTP word {word} returned no data")
    return int(seq.rdata) & M32


async def sec_dis_go(
    fd: SepEfuseFd, token: int, until: int, *, max_reads: int, order: Sequence[int] = range(8)
) -> tuple[int | None, int]:
    """Write ``token`` to the SEC_DIS array, go, poll the match code until ``until``."""
    await write_token(fd.wr, CH_SEC_DIS, token, order)
    await token_go(fd.wr, CH_SEC_DIS)
    return await poll_code(fd.rd, CH_SEC_DIS, max_reads=max_reads, until=until)


# --------------------------------------------------------------------------
# Check lines
# --------------------------------------------------------------------------


def hook_fail(chk: Any, **fields: Any) -> None:
    """A hook control that does not show: ``CHK-HOOK FAIL`` and the leaf verdict.

    ``SepChkLog.finish`` raises, so the leaf ends and its later steps are not graded.
    """
    chk.ok("HOOK", False, **fields)
    chk.finish()


def log_line(logger: Any, tag: str, seed: int, **fields: Any) -> None:
    """``<tag> LOG seed=<n> k=v ...``: a logged value, not a graded check."""
    body = " ".join(f"{k}={v}" for k, v in fields.items())
    logger.info("%s LOG seed=%d %s", tag, seed, body)


def bound_sec_dis_digest() -> int | None:
    """The SEC_DIS digest the bench binds, from the simulator handle; None when hidden."""
    handle = getattr(cocotb.top, SEC_DIS_DIGEST_HANDLE, None)
    if handle is None:
        return None
    try:
        return int(handle.value)
    except (TypeError, ValueError):
        return None


def chk_bind(chk: Any) -> int:
    """CHK-BIND: SHA-256 of 32 zero bytes equals the bound SEC_DIS digest.

    The bound digest comes from the simulator handle of the bench net, never
    from the bench source text. A build that does not show the handle fails the leaf
    with ``CHK-HOOK FAIL``.
    """
    bound = bound_sec_dis_digest()
    if bound is None:
        hook_fail(chk, reason="bound_digest_handle_not_visible", handle=SEC_DIS_DIGEST_HANDLE)
        raise AssertionError("unreachable: hook_fail ends the leaf")
    chk.ok(
        "BIND",
        bound == SEC_DIS_ZERO_DIGEST,
        digest=f"0x{SEC_DIS_ZERO_DIGEST:064x}",
        bound=f"0x{bound:064x}",
        src="handle",
    )
    return bound


# --------------------------------------------------------------------------
# Probe decode and waits
# --------------------------------------------------------------------------


def sig_bits(sig: Any) -> str:
    """The value of ``sig`` as a 0/1/X/Z string, MSB first."""
    v = sig.value
    s = getattr(v, "binstr", None)
    return (s if s is not None else str(v)).strip()


def probe_word(bits: str, word: int) -> int | None:
    """Word ``word`` of a packed ``[N-1:0][31:0]`` probe string; None if it holds X/Z."""
    n = len(bits)
    w = bits[n - 32 * word - 32 : n - 32 * word]
    return int(w, 2) if w and set(w) <= {"0", "1"} else None


def tap_words(bits: str, n_words: int = 8) -> list[str]:
    """``n_words`` 32-character words of a packed tap string, word 0 first."""
    n = len(bits)
    return [bits[n - 32 * k - 32 : n - 32 * k] for k in range(n_words)]


def probe_words(test: Any, sig: Any, n_words: int) -> list[int]:
    """All words of a packed probe; an X/Z bit fails (``rd_known``)."""
    v = test.rd_known(sig)
    return [(v >> (32 * i)) & M32 for i in range(n_words)]


def shadow_word(test: Any, idx: int) -> int:
    """Word ``idx`` of the sensed-shadow output ``efuse_shadow_probe_o``."""
    sh = 32 * idx
    return test.rd_known(cocotb.top.efuse_shadow_probe_o, M32 << sh) >> sh


def bit(test: Any, name: str) -> int:
    """Bit 0 of the top-level signal ``name``; X/Z fails."""
    return test.rd_known(getattr(cocotb.top, name)) & 1


async def wait_bit(test: Any, name: str, want: int, bound: int) -> int | None:
    """Clocks until ``name`` reads ``want`` (0 if it already does); None at ``bound``."""
    sig = getattr(cocotb.top, name)
    for n in range(bound + 1):
        await ReadOnly()
        if test.rd_known(sig) & 1 == want:
            return n
        await RisingEdge(cocotb.top.clk_i)
    return None


# --------------------------------------------------------------------------
# Reset, strap and sense time
# --------------------------------------------------------------------------


class StrapHold:
    """Mixin for a ``sep_base_test`` leaf that holds ``secure_tm_req_i``.

    Put it before ``sep_base_test`` in the bases. The strap value in ``_strap`` is
    driven with the idle defaults, so it holds from before the first reset release.
    """

    _strap = 0

    def drive_idle_defaults(self, dut: Any = None, **kwargs: Any) -> None:
        super().drive_idle_defaults(dut, **kwargs)  # type: ignore[misc]
        (dut if dut is not None else cocotb.top).test_en_strap_i.value = self._strap


def hold_strap(test: Any, value: int) -> None:
    """Drive the strap now and keep it for later idle-default drives (``StrapHold``)."""
    test._strap = value
    cocotb.top.test_en_strap_i.value = value


async def rst_pulse(test: Any, *, hold: int = RST_HOLD, strap: int | None = None) -> None:
    """Cold reset with the clocks running; returns on the ``rst_ni`` release edge.

    There is no wait for sense and so no post-sense backdoor compare. A strap value
    changes only while ``rst_ni`` is low.
    """
    dut = cocotb.top
    await RisingEdge(dut.clk_i)
    dut.rst_ni.value = 0
    if strap is not None:
        hold_strap(test, strap)
    await ClockCycles(dut.clk_i, hold)
    dut.rst_ni.value = 1


async def clocks_to_sense(test: Any, bound: int, *, started: bool) -> int | None:
    """Clocks from the first clock with ``rst_ni`` high to the sense-done rise.

    ``started`` says that ``rst_ni`` is already high. None when ``bound`` clocks pass
    after the release with no rise. The wait before the release is bounded too.
    """
    dut = cocotb.top
    n = 0
    for _ in range(bound + 4 * RST_HOLD + 64):
        await RisingEdge(dut.clk_i)
        await ReadOnly()
        if not started:
            started = bool(test.rd(dut.rst_ni, allow_unknown=True))
            if not started:
                continue
        n += 1
        if test.rd(dut.sep_fuse_sense_done_o, allow_unknown=True):
            return n
        if n >= bound:
            return None
    return None


class SenseClock:
    """Background sampler from a ``rst_ni`` low-to-high to the sense-done rise.

    ``start()`` before the reset that it measures. ``clocks`` is the sense time;
    ``samples`` holds the value of each named extra signal on every clock of the
    window (the last sample is the clock on which sense done reads 1).
    """

    def __init__(self, test: Any, extra: Sequence[str] = ()) -> None:
        self.test = test
        self.extra = tuple(extra)
        self.clocks: int | None = None
        self.samples: dict[str, list[int]] = {n: [] for n in self.extra}
        self._task: Any = None

    def start(self) -> SenseClock:
        self._task = cocotb.start_soon(self._run())
        return self

    @property
    def done(self) -> bool:
        return self.clocks is not None

    def stop(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()

    async def _run(self) -> None:
        dut = cocotb.top
        seen_low = False
        n = 0
        while True:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            if not self.test.rd(dut.rst_ni, allow_unknown=True):
                seen_low = True
                continue
            if not seen_low:
                continue
            n += 1
            for name in self.extra:
                self.samples[name].append(self.test.rd_known(getattr(dut, name)) & 1)
            if self.test.rd(dut.sep_fuse_sense_done_o, allow_unknown=True):
                self.clocks = n
                return


def set_shadow_golden(
    test: Any,
    image: Any,
    *,
    burned: Sequence[int] = (),
    words: Sequence[int] | None = None,
) -> Any:
    """Post-sense shadow golden of the base test after a program; returns the image.

    The golden is ``image`` with the bit addresses ``burned`` set, or ``words``
    (for example the bank content at ``otp_bank_probe_o``) when given. The bank
    keeps every program over reset, so the next sense loads that content. The
    staged t=0 image is never restaged: this changes only the test golden.
    """
    img = copy.deepcopy(image)
    if words is not None:
        img.words = list(words)
    for addr in burned:
        img.words[addr // 32] |= 1 << (addr % 32)
    test.write_efuse_image(img)
    return img
