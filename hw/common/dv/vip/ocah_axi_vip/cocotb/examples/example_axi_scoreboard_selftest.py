# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Simulator-free self-test for the AXI reference model and scoreboard.

Runs the positive evidence flow plus the negative suite below (each case
labelled in the output), proving fail-closed finalization per
``vip-checker-model.adoc`` §"Prove Failure Is Retained":

1. wrong model expectation is rejected;
2. an unexpected (un-armed) DECERR is rejected;
3. a stale armed credit (error never observed) is rejected;
4. a zero-check scoreboard is rejected;
5. a transaction observed inside a declared blocked region is rejected;
6. per-beat error responses in the wrong burst position are rejected;
7. observed write strobes that differ from the armed stimulus intent are
   rejected;
8. a response credit conflicting with the model's expectation is rejected;
9. a timeout that no test armed is rejected;
10. a burst whose LATER beat enters a blocked region is rejected;
11. a blocked region SMALLER than a bus word still flags the covering beat
    (while a narrow transfer that does NOT touch the blocked byte passes);
12. a transaction observed after finalize() is rejected;
13. in-flight requests, orphan completions (which is also how read data
    beginning before its AR surfaces), and swallowed callback errors are
    rejected at drain;
14. a duplicate/stale commit_order can never displace a buffered
    transaction;
15. commit-order buffering cannot bypass temporal policy: a transaction
    observed during a blocked window fails even when replayed after
    closure, a credit armed after observation never classifies it, and
    corrupted expected-EXOKAY read data is rejected.

Run from the repository root::

    PYTHONPATH="$PWD/hw/common/dv/vip" .venv/bin/python \\
      hw/common/dv/vip/ocah_axi_vip/cocotb/examples/example_axi_scoreboard_selftest.py
"""

from __future__ import annotations

import logging

from ocah_checker import OcahCheckerError

from ocah_axi_vip import (
    RESP_DECERR,
    RESP_OKAY,
    OcahAxiItem,
    OcahAxiRefModel,
    OcahAxiRegionExpectation,
    OcahAxiScoreboard,
)

BEAT_BYTES = 4
RAM_BASE = 0x0000_1000
ERROR_ADDR = 0x0000_2000


def _write_item(address: int, data: int, strobe: int, resp: int = RESP_OKAY) -> OcahAxiItem:
    return OcahAxiItem.write(
        protocol="axi4-lite",
        address=address,
        data_words=(data,),
        strobes=(strobe,),
        resp_list=(resp,),
        source="selftest",
    )


def _read_item(address: int, data: int, resp: int = RESP_OKAY) -> OcahAxiItem:
    return OcahAxiItem.read(
        protocol="axi4-lite",
        address=address,
        data_words=(data,),
        resp_list=(resp,),
        source="selftest",
    )


def positive_flow() -> None:
    """Strobed write, readback, armed DECERR, no-activity, memory audit."""
    model = OcahAxiRefModel(name="selftest-model", beat_bytes=BEAT_BYTES)
    scoreboard = OcahAxiScoreboard(
        name="axi-selftest",
        model=model,
        raise_on_error=False,
        required_ids={
            "CHK-AXI-RESP",
            "CHK-AXI-RESP-EXPECTED",
            "CHK-AXI-RDATA",
            "CHK-AXI-WMEM",
            "CHK-AXI-STRB",
            "CHK-AXI-NOACT",
            "CHK-AXI-TIMEOUT",
            "CHK-AXI-CREDITS",
            "CHK-AXI-STREAM-MIN",
            "CHK-AXI-NONVAC",
        },
        min_transactions_per_stream={"default": 3},
    )

    # Full write then a strobe-masked partial write: only lanes 0 and 2 update.
    # Both writes arm their stimulus-intent strobes (CHK-AXI-STRB).
    scoreboard.arm_expected_strobes((0xF,), address=RAM_BASE, context="case=full-write")
    scoreboard.add_observed(_write_item(RAM_BASE, 0x11223344, 0xF))
    scoreboard.arm_expected_strobes((0x5,), address=RAM_BASE, context="case=partial-write")
    scoreboard.add_observed(_write_item(RAM_BASE, 0xAABBCCDD, 0x5))
    expected_word = 0x11BB33DD

    # Readback must match the strobe-merged shadow memory.
    scoreboard.add_observed(_read_item(RAM_BASE, expected_word))

    # Armed expected DECERR: model predicts it, credit classifies it.
    model.expect_error(ERROR_ADDR, RESP_DECERR, read=True, write=False)
    scoreboard.arm_expected_resp(
        RESP_DECERR, address=ERROR_ADDR, direction="read", context="case=armed-decerr"
    )
    scoreboard.add_observed(_read_item(ERROR_ADDR, 0, resp=RESP_DECERR))

    # Armed expected timeout: only the test can authorize a timed-out access.
    scoreboard.arm_expected_timeout(
        timeout_ns=500.0,
        address=ERROR_ADDR + 0x100,
        direction="read",
        context="case=armed-timeout",
    )
    timed_out_item = OcahAxiItem.read(
        protocol="axi4-lite",
        address=ERROR_ADDR + 0x100,
        timed_out=True,
        source="selftest",
    )
    scoreboard.add_observed(timed_out_item)

    # Blocked window: counters unchanged across the window.
    before = {"aw": 3, "w": 3, "ar": 2}
    after = {"aw": 3, "w": 3, "ar": 2}
    scoreboard.expect_no_activity(before=before, after=after, context="gate=example")

    # Memory audit: the "DUT" image equals the model's own snapshot here, which
    # is exactly what a backdoor RAM read returns after matching traffic.
    scoreboard.check_memory(
        dut_bytes=model.read_bytes(RAM_BASE, BEAT_BYTES),
        address=RAM_BASE,
        length=BEAT_BYTES,
        context="post-write",
    )

    scoreboard.expect_nonvacuous(
        expected_word != 0x11223344 and expected_word != 0xAABBCCDD,
        context="strobe-merge produced a value neither write carried",
    )
    scoreboard.finalize()
    print("selftest positive PASS: scoreboard finalized cleanly")


def negative_wrong_expectation() -> None:
    """A wrong model expectation must be rejected at finalize."""
    model = OcahAxiRefModel(name="neg-model", beat_bytes=BEAT_BYTES)
    scoreboard = OcahAxiScoreboard(name="neg-wrong", model=model, raise_on_error=False)
    model.write_bytes(RAM_BASE, (0xB4).to_bytes(BEAT_BYTES, "little"))
    scoreboard.add_observed(_read_item(RAM_BASE, 0x5A))
    try:
        scoreboard.finalize()
    except OcahCheckerError as exc:
        assert "failed=1" in str(exc), exc
        print("selftest negative-A PASS: wrong expectation rejected")
    else:
        raise AssertionError("wrong model expectation did not fail")


def negative_unexpected_decerr() -> None:
    """An un-armed DECERR must fail the plain response comparison."""
    model = OcahAxiRefModel(name="neg-model-2", beat_bytes=BEAT_BYTES)
    scoreboard = OcahAxiScoreboard(name="neg-unexpected", model=model, raise_on_error=False)
    scoreboard.add_observed(_read_item(RAM_BASE, 0, resp=RESP_DECERR))
    try:
        scoreboard.finalize()
    except OcahCheckerError as exc:
        assert "CHK-AXI-RESP" in str(exc), exc
        print("selftest negative-B PASS: unexpected DECERR rejected")
    else:
        raise AssertionError("unexpected DECERR did not fail")


def negative_stale_credit() -> None:
    """An armed error that never happens must fail CHK-AXI-CREDITS."""
    scoreboard = OcahAxiScoreboard(name="neg-credit", raise_on_error=False)
    scoreboard.arm_expected_resp(RESP_DECERR, context="case=never-consumed")
    scoreboard.add_observed(_read_item(RAM_BASE, 0))
    try:
        scoreboard.finalize()
    except OcahCheckerError as exc:
        assert "CHK-AXI-CREDITS" in str(exc), exc
        print("selftest negative-C PASS: stale credit rejected")
    else:
        raise AssertionError("stale expected-response credit did not fail")


def negative_zero_checks() -> None:
    """A scoreboard that never checked anything must not pass."""
    scoreboard = OcahAxiScoreboard(name="neg-zero", raise_on_error=False)
    try:
        scoreboard.finalize()
    except OcahCheckerError as exc:
        assert "zero checks" in str(exc), exc
        print("selftest negative-D PASS: zero checks rejected")
    else:
        raise AssertionError("zero-check scoreboard did not fail")


def negative_blocked_region() -> None:
    """A transaction observed inside a blocked region must fail, even OKAY."""
    model = OcahAxiRefModel(name="neg-model-blocked", beat_bytes=BEAT_BYTES)
    model.add_region(
        OcahAxiRegionExpectation(base=0x4000, size=0x100, blocked=True, label="secure")
    )
    scoreboard = OcahAxiScoreboard(name="neg-blocked", model=model, raise_on_error=False)
    scoreboard.add_observed(_read_item(0x4000, 0, resp=RESP_OKAY))
    try:
        scoreboard.finalize()
    except OcahCheckerError as exc:
        assert "CHK-AXI-BLOCKED" in str(exc), exc
        print("selftest negative-E PASS: blocked-region transaction rejected")
    else:
        raise AssertionError("blocked-region transaction did not fail")


def negative_beat_swap() -> None:
    """A per-beat error response in the wrong burst position must fail."""
    model = OcahAxiRefModel(name="neg-model-beats", beat_bytes=BEAT_BYTES)
    model.expect_error(0x5004, RESP_DECERR, read=True, write=False)  # beat 1
    scoreboard = OcahAxiScoreboard(name="neg-beats", model=model, raise_on_error=False)
    scoreboard.arm_expected_resp(RESP_DECERR, address=0x5000, direction="read")
    swapped = OcahAxiItem.read(
        protocol="axi4",
        address=0x5000,
        size=2,
        burst=1,
        data_words=(0, 7),
        resp_list=(RESP_DECERR, RESP_OKAY),  # DECERR on beat 0, expected beat 1
        source="selftest",
    )
    scoreboard.add_observed(swapped)
    try:
        scoreboard.finalize()
    except OcahCheckerError as exc:
        assert "CHK-AXI-RESP" in str(exc), exc
        print("selftest negative-F PASS: swapped beat responses rejected")
    else:
        raise AssertionError("swapped per-beat responses did not fail")


def negative_wrong_strobes() -> None:
    """Observed strobes differing from the armed stimulus intent must fail."""
    model = OcahAxiRefModel(name="neg-model-strb", beat_bytes=BEAT_BYTES)
    scoreboard = OcahAxiScoreboard(name="neg-strb", model=model, raise_on_error=False)
    scoreboard.arm_expected_strobes((0xF,), address=RAM_BASE, context="case=intent-full")
    scoreboard.add_observed(_write_item(RAM_BASE, 0x11223344, 0x3))  # DUT dropped lanes
    try:
        scoreboard.finalize()
    except OcahCheckerError as exc:
        assert "CHK-AXI-STRB" in str(exc), exc
        print("selftest negative-G PASS: wrong write strobes rejected")
    else:
        raise AssertionError("wrong write strobes did not fail")


def negative_credit_model_conflict() -> None:
    """A credit conflicting with the model's expectation must fail."""
    model = OcahAxiRefModel(name="neg-model-conflict", beat_bytes=BEAT_BYTES)
    model.expect_error(0x7000, 2, read=True, write=False)  # model expects SLVERR
    scoreboard = OcahAxiScoreboard(name="neg-conflict", model=model, raise_on_error=False)
    scoreboard.arm_expected_resp(RESP_DECERR, address=0x7000, direction="read")
    scoreboard.add_observed(_read_item(0x7000, 0, resp=RESP_DECERR))
    try:
        scoreboard.finalize()
    except OcahCheckerError as exc:
        assert "CHK-AXI-RESP" in str(exc), exc
        print("selftest negative-H PASS: credit conflicting with model rejected")
    else:
        raise AssertionError("credit conflicting with model did not fail")


def negative_unauthorized_timeout() -> None:
    """A timed-out transaction that no test armed must fail."""
    scoreboard = OcahAxiScoreboard(name="neg-timeout", raise_on_error=False)
    item = OcahAxiItem.read(
        protocol="axi4-lite", address=RAM_BASE, timed_out=True, source="selftest"
    )
    scoreboard.add_observed(item)
    try:
        scoreboard.finalize()
    except OcahCheckerError as exc:
        assert "CHK-AXI-COMPLETION" in str(exc), exc
        print("selftest negative-I PASS: unauthorized timeout rejected")
    else:
        raise AssertionError("unauthorized timeout did not fail")


def negative_midburst_blocked() -> None:
    """A burst whose LATER beat enters a blocked region must fail."""
    model = OcahAxiRefModel(name="neg-model-midburst", beat_bytes=BEAT_BYTES)
    model.add_region(OcahAxiRegionExpectation(base=0x6004, size=4, blocked=True, label="secure"))
    scoreboard = OcahAxiScoreboard(name="neg-midburst", model=model, raise_on_error=False)
    burst = OcahAxiItem.read(
        protocol="axi4",
        address=0x6000,  # starts OUTSIDE the region; beat 1 lands at 0x6004
        size=2,
        burst=1,
        data_words=(0, 0),
        resp_list=(RESP_OKAY, RESP_OKAY),
        source="selftest",
    )
    scoreboard.add_observed(burst)
    try:
        scoreboard.finalize()
    except OcahCheckerError as exc:
        assert "CHK-AXI-BLOCKED" in str(exc), exc
        print("selftest negative-J PASS: mid-burst blocked region rejected")
    else:
        raise AssertionError("mid-burst blocked region did not fail")


def negative_subword_blocked() -> None:
    """A blocked region smaller than a bus word must flag the covering beat,
    while a narrow transfer that does not touch the blocked byte passes."""
    model = OcahAxiRefModel(name="neg-model-subword", beat_bytes=BEAT_BYTES)
    model.add_region(OcahAxiRegionExpectation(base=0x8002, size=1, blocked=True, label="fuse-bit"))
    scoreboard = OcahAxiScoreboard(name="neg-subword", model=model, raise_on_error=False)
    # Narrow 1-byte read at 0x8000 (size=0) touches only 0x8000: must PASS.
    narrow = OcahAxiItem.read(
        protocol="axi4",
        address=0x8000,
        size=0,
        burst=1,
        data_words=(0,),
        resp_list=(RESP_OKAY,),
        source="selftest",
    )
    scoreboard.add_observed(narrow)
    assert not scoreboard.errors, "narrow non-touching transfer was blocked"
    # Word-aligned write at 0x8000 covers 0x8000-0x8003, overlapping the
    # 1-byte blocked region at 0x8002 even though 0x8000 itself is outside it.
    scoreboard.add_observed(_write_item(0x8000, 0xDEAD_BEEF, 0xF))
    try:
        scoreboard.finalize()
    except OcahCheckerError as exc:
        assert "CHK-AXI-BLOCKED" in str(exc), exc
        print(
            "selftest negative-K PASS: sub-word blocked region rejected "
            "(narrow non-touching transfer passed)"
        )
    else:
        raise AssertionError("sub-word blocked region did not fail")


def negative_late_callback() -> None:
    """A transaction observed after finalize() must be rejected loudly."""
    scoreboard = OcahAxiScoreboard(name="neg-late", raise_on_error=False)
    scoreboard.add_observed(_read_item(RAM_BASE, 0))
    scoreboard.finalize()
    try:
        scoreboard.add_observed(_read_item(RAM_BASE, 0))
    except AssertionError:
        print("selftest negative-L PASS: post-finalize transaction rejected")
    else:
        raise AssertionError("post-finalize transaction was accepted")


class _FakeMonitor:
    """Minimal monitor stand-in for drain-path proofs."""

    name = "fake-monitor"

    def __init__(self, pending, orphans=0, callback_errors=0):
        self._pending = dict(pending)
        self.orphan_responses = orphans
        self.callback_errors = callback_errors

    def add_item_callback(self, fn):
        pass

    def pending_transactions(self):
        return dict(self._pending)


def negative_drain_pending() -> None:
    """An accepted request that never completed must fail at drain."""
    scoreboard = OcahAxiScoreboard(name="neg-drain", raise_on_error=False)
    scoreboard.attach_monitor(_FakeMonitor({"write": 0, "read": 1}), stream="s")
    scoreboard.add_observed(_read_item(RAM_BASE, 0), stream="s")
    try:
        scoreboard.finalize()
    except OcahCheckerError as exc:
        assert "CHK-AXI-DRAIN" in str(exc), exc
        print("selftest negative-M PASS: in-flight request rejected at drain")
    else:
        raise AssertionError("in-flight request did not fail at drain")


def negative_drain_orphans_and_callbacks() -> None:
    """Orphan completions and swallowed callback errors must fail at drain."""
    scoreboard = OcahAxiScoreboard(name="neg-orphan", raise_on_error=False)
    scoreboard.attach_monitor(
        _FakeMonitor({"write": 0, "read": 0}, orphans=1, callback_errors=1),
        stream="s",
    )
    scoreboard.add_observed(_read_item(RAM_BASE, 0), stream="s")
    try:
        scoreboard.finalize()
    except OcahCheckerError as exc:
        assert "CHK-AXI-DRAIN" in str(exc), exc
        print("selftest negative-N PASS: orphans/callback errors rejected at drain")
    else:
        raise AssertionError("orphans/callback errors did not fail at drain")


def negative_duplicate_commit_order() -> None:
    """A duplicate commit_order must not displace a buffered transaction."""
    model = OcahAxiRefModel(name="neg-model-dup", beat_bytes=BEAT_BYTES)
    scoreboard = OcahAxiScoreboard(name="neg-dup", model=model, raise_on_error=False)
    bad = _read_item(RAM_BASE, 0, resp=RESP_DECERR)
    bad.metadata["commit_order"] = 1  # buffered: waits for order 0
    scoreboard.add_observed(bad)
    benign = _read_item(RAM_BASE, 0)
    benign.metadata["commit_order"] = 1  # duplicate slot: must NOT replace
    scoreboard.add_observed(benign)
    first = _read_item(RAM_BASE, 0)
    first.metadata["commit_order"] = 0
    scoreboard.add_observed(first)
    try:
        scoreboard.finalize()
    except (OcahCheckerError, AssertionError) as exc:
        assert "CHK-AXI-RESP" in str(exc) or "duplicate" in str(exc), exc
        print("selftest negative-O PASS: duplicate commit_order rejected")
    else:
        raise AssertionError("duplicate commit_order displaced a failure")


def negative_temporal_policy_bypass() -> None:
    """Buffered replay must not escape window membership or credit timing,
    and corrupted expected-EXOKAY read data must fail."""
    # (a) observed during a blocked window, processed after closure.
    scoreboard = OcahAxiScoreboard(name="neg-window-bypass", raise_on_error=False)
    scoreboard.begin_blocked_window()
    late = _read_item(RAM_BASE, 0)
    late.metadata["commit_order"] = 1
    scoreboard.add_observed(late)  # arrival is INSIDE the window
    scoreboard.end_blocked_window(context="case=window-bypass")
    first = _read_item(RAM_BASE, 0)
    first.metadata["commit_order"] = 0
    scoreboard.add_observed(first)  # releases the buffered item
    try:
        scoreboard.finalize()
    except (OcahCheckerError, AssertionError) as exc:
        assert "blocked window" in str(exc) or "CHK-AXI-NOACT" in str(exc), exc
        print("selftest negative-P PASS: window bypass via buffering rejected")
    else:
        raise AssertionError("buffered item escaped the blocked window")

    # (b) credit armed AFTER the error was observed must not classify it.
    scoreboard2 = OcahAxiScoreboard(name="neg-late-credit", raise_on_error=False)
    err = _read_item(RAM_BASE, 0, resp=RESP_DECERR)
    err.metadata["commit_order"] = 1
    scoreboard2.add_observed(err)  # buffered, unprocessed
    scoreboard2.arm_expected_resp(RESP_DECERR, address=RAM_BASE, direction="read")
    first2 = _read_item(RAM_BASE + 0x10, 0)
    first2.metadata["commit_order"] = 0
    scoreboard2.add_observed(first2)  # releases the buffered error
    try:
        scoreboard2.finalize()
    except (OcahCheckerError, AssertionError) as exc:
        assert "CHK-AXI-RESP" in str(exc) or "CHK-AXI-CREDITS" in str(exc), exc
        print("selftest negative-Q PASS: late-armed credit rejected")
    else:
        raise AssertionError("credit armed after observation classified the error")

    # (c) expected-EXOKAY read data is checked and corruption fails.
    model = OcahAxiRefModel(name="neg-model-exokay", beat_bytes=BEAT_BYTES)
    model.add_region(OcahAxiRegionExpectation(base=0x9000, size=0x10, read_resp=1, label="excl"))
    model.write_bytes(0x9000, (0x11223344).to_bytes(BEAT_BYTES, "little"))
    scoreboard3 = OcahAxiScoreboard(name="neg-exokay", model=model, raise_on_error=False)
    scoreboard3.add_observed(_read_item(0x9000, 0xBAD0_BAD0, resp=1))  # corrupt data
    try:
        scoreboard3.finalize()
    except OcahCheckerError as exc:
        assert "CHK-AXI-RDATA" in str(exc), exc
        print("selftest negative-R PASS: corrupted expected-EXOKAY data rejected")
    else:
        raise AssertionError("corrupted expected-EXOKAY read data passed")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    positive_flow()
    negative_wrong_expectation()
    negative_unexpected_decerr()
    negative_stale_credit()
    negative_zero_checks()
    negative_blocked_region()
    negative_beat_swap()
    negative_wrong_strobes()
    negative_credit_model_conflict()
    negative_unauthorized_timeout()
    negative_midburst_blocked()
    negative_subword_blocked()
    negative_late_callback()
    negative_drain_pending()
    negative_drain_orphans_and_callbacks()
    negative_duplicate_commit_order()
    negative_temporal_policy_bypass()
    print("example_axi_scoreboard_selftest: ALL CASES PASS")


if __name__ == "__main__":
    main()
