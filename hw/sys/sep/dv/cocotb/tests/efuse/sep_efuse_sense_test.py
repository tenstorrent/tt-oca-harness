# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The sensed eFuse shadow registers equal the staged OTP image.

Selects an OTP image through the shared eFuse image policy and senses it through
the behavioral OTP responder. The common sense-done helper compares the sensed
shadow registers against the golden via the backdoor probe.

``CHK-SENSE-WORD-ORDER`` grades the load order that
``hw/sys/sep/doc/otp_fuse_controller.adoc`` (eFuse sensing) states: each response strobe
stores the shadow word indexed by the word counter and increments it, and
``fuse_sense_done_o`` rises one cycle after the strobe that stores the last word. Over the
words whose staged value differs from reset, the first clock on which each word changes at
``efuse_shadow_probe_o`` must rise strictly with the word index, and the
``sep_fuse_sense_done_o`` rise must come one clock after the change of word 255 (or after
the last changed word when word 255 stays at reset). At least two changed words are required.

``CHK-LC-STATE-PRESENSE-HOLD`` grades the ``LC_STATE`` hold that
``hw/sys/sep/doc/otp_fuse_controller.adoc`` (Fuse Sensing and Boot Sequencing) states: the
logical ``LC_STATE`` output remains ``4'b1111`` until fuse sensing completes. On every clock
from the ``rst_ni`` release until the ``sep_fuse_sense_done_o`` rise, the port ``lc_state_o``
(tap ``lc_state_probe_o``, ``{~raw, raw}`` by ``doc/integrator/src/smu-sep.adoc``) must equal
the ``LC_STATE`` RDL reset value 0x0F, the INVALID encoding, with ``security_disable_o`` at 0.
The check also requires that the sensed ``LC_STATE`` byte at ``efuse_shadow_probe_o`` equals
the staged encoding on at least one of those clocks, so the hold is graded while the sensed value
is already present. The staged ``LC_STATE`` must not encode INVALID.

``CHK-LC-STATE-RELEASE`` grades the other half of the same sentence. The sentence names no
clock; this test takes the first clock with ``sep_fuse_sense_done_o`` = 1 as the point where
sensing has completed, and requires ``lc_state_o`` on that clock to equal the sensed
``LC_STATE`` byte and the encoding of the staged raw state.

Log-only: ``OBS-SHADOW-PRESENSE-WITHHELD`` records, for the three public identity fields
``SEP_CHIPLET_ID``, ``SEP_SIP_ID`` and ``SEP_SYS_ID``, the first clock on which the field at
``efuse_shadow_probe_o`` holds its sensed value, the first clock on which the Key Manager OTP
input (taps ``km_otp_sep_*_id_o``, ``{~value, value}``) carries that value, and the clock of the
``sep_fuse_sense_done_o`` rise. ``hw/sys/sep/doc/otp_fuse_controller.adoc`` (Fuse Sensing and
Boot Sequencing) makes every field other than LOCKS and LC_STATE available downstream as soon as
it is ready; the description of ``assets/sep-token-processing.svg`` has the shadow map withheld
until sensing completes. The two texts disagree, so the record grades nothing.

Log-only: ``OBS-SENSE-FIELD-ORDER`` gives, per field, the first clock on which one of its
words changed and the clock of the ``sep_fuse_sense_done_o`` rise, counted from the start of
the leaf.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ReadOnly, RisingEdge
from env.sep_efuse_image import LC_FIELD_MASK, SepEfuseImage, lc_encode
from env.sep_efuse_plan import FIELD_NAMES, field_n_words, field_word
from env.sep_fcov_gate import close_graded_window, open_graded_window
from sep_base_test import sep_base_test
from sep_reg_meta import word_reset

_MAX_SENSE_CYCLES = 20_000


def _bits(sig) -> str:
    v = sig.value
    s = getattr(v, "binstr", None)
    return (s if s is not None else str(v)).strip()


def _lc_byte(shadow: str) -> int | None:
    """The ``LC_STATE`` field bits (``LC_FIELD_MASK``) of a shadow-probe value, or None when
    one of them is X or Z."""
    w = field_word("LC_STATE")
    lo = len(shadow) - 32 * (w + 1)
    word = shadow[lo : lo + 32]
    bits = [(i, word[31 - i]) for i in range(32) if LC_FIELD_MASK >> i & 1]
    if not {b for _, b in bits} <= {"0", "1"}:
        return None
    return sum(int(b) << i for i, b in bits)


def _bits_int(sig) -> int | None:
    s = _bits(sig)
    return int(s, 2) if set(s) <= {"0", "1"} else None


_ID_TAPS = (
    ("SEP_CHIPLET_ID", "km_otp_sep_chiplet_id_o"),
    ("SEP_SIP_ID", "km_otp_sep_sip_id_o"),
    ("SEP_SYS_ID", "km_otp_sep_sys_id_o"),
)


def _field_bits(shadow: str, name: str) -> str:
    """The packed bits of field ``name`` in a shadow-probe value, MSB first."""
    lo = len(shadow) - 32 * (field_word(name) + field_n_words(name))
    return shadow[lo : lo + 32 * field_n_words(name)]


def _dual_rail_value(tap: str) -> str | None:
    """The value half of a ``{~value, value}`` tap, or None when the rails disagree or carry
    X or Z."""
    half = len(tap) // 2
    hi, lo = tap[:half], tap[half:]
    if not set(tap) <= {"0", "1"} or any(a == b for a, b in zip(hi, lo)):
        return None
    return lo


async def _sense_order(rec: dict) -> None:
    """Per shadow word, the first clock it differs from the previous clock; stops at the
    ``sep_fuse_sense_done_o`` rise. From the ``rst_ni`` release it also records, per clock
    before that rise, ``lc_state_o``, the sensed ``LC_STATE`` byte and ``security_disable_o``,
    and on the rise clock ``lc_state_o`` and the sensed byte."""
    dut = cocotb.top
    lc = rec["lc"]
    prev = None
    clk = 0
    seen_low = False
    while True:
        await RisingEdge(dut.clk_i)
        await ReadOnly()
        clk += 1
        cur = _bits(dut.efuse_shadow_probe_o)
        rst = _bits(dut.rst_ni)
        if rst != "1":
            seen_low = seen_low or rst == "0"
        elif seen_low:
            port = _bits_int(dut.lc_state_probe_o)
            sensed = _lc_byte(cur)
            rec["ids"].append(
                (
                    clk,
                    [_field_bits(cur, name) for name, _ in _ID_TAPS],
                    [_dual_rail_value(_bits(getattr(dut, tap))) for _, tap in _ID_TAPS],
                )
            )
            if _bits(dut.sep_fuse_sense_done_o) == "1":
                lc["rel"] = (clk, port, sensed)
            else:
                lc["clocks"] += 1
                if port != lc["want"] and lc["bad"] is None:
                    lc["bad"] = (clk, port, sensed)
                if sensed == lc["staged"]:
                    lc["loaded"] += 1
                    if lc["first_loaded"] is None:
                        lc["first_loaded"] = clk
                if _bits(dut.lcc_security_disable_probe_o) != "0":
                    lc["sdis"] += 1
        if prev is not None and cur != prev:
            n = len(cur) // 32
            for w in range(n):
                if w in rec["first"]:
                    continue
                lo = len(cur) - 32 * (w + 1)
                if cur[lo : lo + 32] != prev[lo : lo + 32]:
                    rec["first"][w] = clk
        prev = cur
        if _bits(dut.sep_fuse_sense_done_o) == "1":
            rec["done"] = clk
            return


@pyuvm.test()
class sep_efuse_sense_test(sep_base_test):
    """After sense-done every shadow register equals the staged image (backdoor probe compare)."""

    # Backdoor-only: no AXI sequencer/scoreboard needed (the shadow probe is
    # read directly), so skip the AXI env -- otherwise its check_phase fails the
    # test for "no AXI transactions".
    build_env = False
    required_evidence = (
        "CHK-SENSE-DONE",
        "CHK-SENSE-WORD-ORDER",
        "CHK-SENSE-BACKDOOR",
        "CHK-IMAGE-MATCH",
        "CHK-LC-STATE-PRESENSE-HOLD",
        "CHK-LC-STATE-RELEASE",
    )

    def _log_id_withhold(self, rec: dict) -> None:
        """OBS-SHADOW-PRESENSE-WITHHELD: when each identity field lands in the sensed shadow,
        and when the Key Manager OTP input first carries it."""
        rows = rec["ids"]
        parts = [] if rows else ["none"]
        for i, (name, _) in enumerate(_ID_TAPS if rows else ()):
            final = rows[-1][1][i]
            landed = next((c for c, s, _ in rows if s[i] == final), None)
            down = next((c for c, _, d in rows if d[i] == final), None)
            withheld = sum(1 for c, s, d in rows if s[i] == final and d[i] != final)
            zero = set(final) == {"0"}
            parts.append(
                f"{name}:landed={landed},downstream={down},"
                f"withheld_clocks={withheld},sensed_zero={int(zero)}"
            )
        self.logger.info(
            "OBS-SHADOW-PRESENSE-WITHHELD %s sense_done_cycle=%s",
            " ".join(parts),
            "none" if rec["done"] is None else rec["done"],
        )

    async def run_scenario(self) -> None:
        img = self.select_efuse_image()
        self.write_efuse_image(img)
        invalid = word_reset(SepEfuseImage.field("LC_STATE").shadow_addr) & LC_FIELD_MASK
        assert invalid == lc_encode(0xF), (
            f"test bug: LC_STATE RDL reset 0x{invalid:02x} is not INVALID 0x{lc_encode(0xF):02x}"
        )
        staged_lc = lc_encode(img.lc_raw())
        assert staged_lc != invalid, (
            f"test bug: staged LC_STATE 0x{staged_lc:02x} is INVALID; the hold check needs "
            "a sensed value that differs from the held one"
        )
        lc = {
            "want": invalid,
            "staged": staged_lc,
            "clocks": 0,
            "bad": None,
            "loaded": 0,
            "first_loaded": None,
            "sdis": 0,
            "rel": None,
        }
        rec: dict = {"first": {}, "done": None, "lc": lc, "ids": []}
        open_graded_window("sep_efuse_sense_test", self.logger)
        sampler = cocotb.start_soon(_sense_order(rec))
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
        if not sampler.done():
            sampler.cancel()
        close_graded_window(self.logger)
        first = {
            f: min(
                (
                    rec["first"][w]
                    for w in range(field_word(f), field_word(f) + field_n_words(f))
                    if w in rec["first"]
                ),
                default=None,
            )
            for f in FIELD_NAMES
        }
        seen = sorted((c, f) for f, c in first.items() if c is not None)
        unseen = [f for f, c in first.items() if c is None]
        self.logger.info(
            "OBS-SENSE-FIELD-ORDER first_change=%s sense_done_cycle=%s",
            ",".join([f"{f}:{c}" for c, f in seen] + [f"{f}:none" for f in unseen]),
            "none" if rec["done"] is None else rec["done"],
        )
        self._log_id_withhold(rec)
        assert rec["done"] is not None, "CHK-SENSE-DONE FAIL: no sep_fuse_sense_done_o rise seen"
        self.logger.info("CHK-SENSE-DONE PASS: sep_fuse_sense_done_o rose at clock %d", rec["done"])
        words = sorted(rec["first"].items())
        last = rec["first"].get(255)
        order_ok = all(a[1] < b[1] for a, b in zip(words, words[1:]))
        done_ok = rec["done"] is not None and (
            rec["done"] == last + 1
            if last is not None
            else bool(words) and rec["done"] > words[-1][1]
        )
        assert len(words) >= 2 and order_ok and done_ok, (
            f"CHK-SENSE-WORD-ORDER FAIL: changed_words={len(words)} order_ok={order_ok} "
            f"done={rec['done']} word255_clk={last} first={words}"
        )
        self.logger.info(
            "CHK-SENSE-WORD-ORDER PASS: changed_words=%d ascending by word index, "
            "done=%s word255_clk=%s",
            len(words),
            rec["done"],
            last,
        )
        hold_ok = lc["clocks"] > 0 and lc["bad"] is None and lc["loaded"] > 0 and lc["sdis"] == 0
        assert hold_ok, (
            f"CHK-LC-STATE-PRESENSE-HOLD FAIL: presense_clocks={lc['clocks']} "
            f"first_bad(clk,port,sensed)={lc['bad']} loaded_clocks={lc['loaded']} "
            f"secdis_clocks={lc['sdis']} want=0x{invalid:02x}"
        )
        self.logger.info(
            "CHK-LC-STATE-PRESENSE-HOLD PASS: lc_state_o=0x%02x on all %d clocks from the "
            "rst_ni release to the sense-done rise; sensed LC_STATE byte 0x%02x present on "
            "%d of them from clock %d; secdis_clocks=0",
            invalid,
            lc["clocks"],
            staged_lc,
            lc["loaded"],
            lc["first_loaded"],
        )
        rel = lc["rel"]
        assert rel is not None and rel[1] == rel[2] == staged_lc, (
            f"CHK-LC-STATE-RELEASE FAIL: sense-done clock (clk,port,sensed)={rel} "
            f"want port == sensed == staged 0x{staged_lc:02x}"
        )
        self.logger.info(
            "CHK-LC-STATE-RELEASE PASS: sense-done clock %d lc_state_o=0x%02x "
            "sensed=0x%02x staged=0x%02x",
            rel[0],
            rel[1],
            rel[2],
            staged_lc,
        )
        # The bring-up runs the shared backdoor compare of every shadow word
        # (CHK-SENSE-BACKDOOR); +skip_fuse_sense skips it.
        backdoor = "CHK-SENSE-BACKDOOR" in self._evidence.seen
        assert "skip_fuse_sense" not in cocotb.plusargs and backdoor, (
            f"CHK-IMAGE-MATCH FAIL: backdoor compare logged={int(backdoor)}; "
            "+skip_fuse_sense skips the shadow compare this record names"
        )
        self.logger.info(
            "CHK-IMAGE-MATCH PASS: words=%d sensed shadow equals the staged image",
            len(img.words),
        )
