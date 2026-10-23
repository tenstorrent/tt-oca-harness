# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ABR ML-DSA ZEROIZE returns STATUS to READY from every state, and how long it takes.

``STATUS.READY`` re-asserts only after a zeroize or a reset
(hw/sys/sep/doc/adams_bridge.adoc), and ZEROIZE clears every internal register
and memory (abr_reg.rdl, MLDSA_CTRL.ZEROIZE). This leaf zeroizes from three
states an ML-DSA command can leave the engine in: idle at READY, waiting for a
streamed message (``MSG_STREAM_READY``), and parked at ``VALID`` after a
completed VERIFY. From each it grades that STATUS returns to READY with VALID
clear.

No document states how long the zeroize takes, so the leaf measures it and logs
the result without grading it (``OBS-ABR-ZEROIZE-CYCLES``). The engine-side count
runs from the first clk_i edge on which the zeroize request is high to the first
on which the sequencer is back at RESET (``abr_zeroize_ready_probe_o``); the
bus-side count runs from the ZEROIZE write's completion to the first STATUS read,
polled back to back, that returns READY after one that did not. The first read
after the write is logged as well (``first=ready`` or ``first=busy``): it can
still see the READY from before the request reached the engine. The graded
STATUS read follows the engine's return to RESET, so it does not depend on that
window. The virtual platform's Adams Bridge model takes its ``zeroize_cycles``
default from the engine-side measurement.

The VERIFY vectors are the NIST ones the other ABR tests use: the external-mu
accept case for the VALID state and the pure-with-context accept case of the
hint table for the streaming state. no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from env.sep_abr_nist import NIST_HINT_CASES, NIST_SV_ACCEPT
from env.sep_spec_tables import abr_field_mask, abr_off
from sep_base_test import sep_base_test
from seq_lib.sep_abr_keygen_seq import (
    ABR_BASE,
    ABR_CTRL,
    ABR_EXTERNAL_MU,
    ABR_PUBKEY,
    ABR_SIGNATURE,
    ABR_STATUS,
    CMD_VERIFY,
    CTRL_EXTERNAL_MU,
    CTRL_ZEROIZE,
    ST_ERROR,
    ST_READY,
    ST_VALID,
    SepAbr,
)

ABR_CTX_CONFIG = ABR_BASE + abr_off("MLDSA_CTX_CONFIG")
ABR_CTX = ABR_BASE + abr_off("MLDSA_CTX")
CTRL_STREAM_MSG = abr_field_mask("MLDSA_CTRL", "STREAM_MSG")
ST_MSG_STREAM_READY = abr_field_mask("MLDSA_STATUS", "MSG_STREAM_READY")

# abr_zeroize_ready_probe_o bits.
_PROBE_ZEROIZE = 1 << 0
_PROBE_READY = 1 << 1

# Backstops so a hang fails the wait rather than the simulation timeout. The
# sweep is a few thousand cycles; a VERIFY a few hundred thousand.
_SWEEP_CYCLES_MAX = 100_000
_STATUS_POLLS_MAX = 100_000


@pyuvm.test()
class sep_abr_zeroize_latency_test(sep_base_test):
    """ZEROIZE from idle, mid-stream and VALID returns STATUS to READY; its latency is logged."""

    required_evidence = ("CHK-ABR-ZEROIZE-READY",)

    async def _wait_status(self, abr: SepAbr, mask: int, expect: int, *, what: str) -> int:
        for _ in range(_STATUS_POLLS_MAX):
            st = await abr.rd32(ABR_STATUS)
            if (st & mask) == expect:
                return st
            if st & ST_ERROR:
                raise AssertionError(f"{what}: STATUS.ERROR set (0x{st:08x})")
        raise AssertionError(f"{what}: STATUS mask 0x{mask:x} never 0x{expect:x}")

    async def _sweep_cycles(self) -> int:
        """clk_i edges from the zeroize request to the sequencer's return to RESET.

        Ready can still read high on the edge the request first appears, so the
        count ends at ready rising again after it has fallen."""
        probe = cocotb.top.abr_zeroize_ready_probe_o
        clk = cocotb.top.clk_i
        start = fell = None
        for cycle in range(_SWEEP_CYCLES_MAX):
            await RisingEdge(clk)
            v = int(probe.value)
            if start is None:
                if v & _PROBE_ZEROIZE:
                    start = cycle
                continue
            if fell is None:
                if not v & _PROBE_READY:
                    fell = cycle
                continue
            if v & _PROBE_READY:
                return cycle - start
        raise AssertionError(
            f"zeroize request {'seen' if start is not None else 'never seen'}, ready "
            f"{'fell' if fell is not None else 'never fell'}, and never returned in "
            f"{_SWEEP_CYCLES_MAX} cycles"
        )

    async def _zeroize_and_measure(self, abr: SepAbr, state: str) -> None:
        sweep = cocotb.start_soon(self._sweep_cycles())
        await abr.wr32(ABR_CTRL, CTRL_ZEROIZE)
        start = self._cycle
        first = await abr.rd32(ABR_STATUS)
        busy_seen = not first & ST_READY
        bus = None
        for _ in range(_STATUS_POLLS_MAX):
            polled = await abr.rd32(ABR_STATUS)
            if not polled & ST_READY:
                busy_seen = True
            elif busy_seen:
                bus = self._cycle - start
                break
        engine = await sweep
        st = await abr.rd32(ABR_STATUS)
        assert st & ST_READY and not st & ST_VALID, (
            f"CHK-ABR-ZEROIZE-READY FAIL: state={state}: STATUS 0x{st:08x} after ZEROIZE, "
            "not READY with VALID clear"
        )
        self.logger.info(
            "CHK-ABR-ZEROIZE-READY PASS: state=%s STATUS=0x%08x after ZEROIZE", state, st
        )
        self.logger.info(
            "OBS-ABR-ZEROIZE-CYCLES: state=%s engine=%d bus=%s first=%s",
            state,
            engine,
            "unseen" if bus is None else bus,
            "ready" if first & ST_READY else "busy",
        )

    async def _count_cycles(self) -> None:
        while True:
            await RisingEdge(cocotb.top.clk_i)
            self._cycle += 1

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        abr = SepAbr(self)
        self._cycle = 0
        cocotb.start_soon(self._count_cycles())

        # Idle: READY from bring-up.
        await self._wait_status(abr, ST_READY, ST_READY, what="idle READY")
        await self._zeroize_and_measure(abr, "idle")

        # Streaming: VERIFY accepted, the engine waiting for the message.
        case = NIST_HINT_CASES[0]
        await abr.write_words(ABR_PUBKEY, case.pk)
        await abr.write_words(ABR_SIGNATURE, case.sig)
        await abr.wr32(ABR_CTX_CONFIG, case.ctx_bytes)
        await abr.write_words(ABR_CTX, case.ctx)
        await abr.wr32(ABR_CTRL, CMD_VERIFY | CTRL_STREAM_MSG)
        await self._wait_status(
            abr, ST_MSG_STREAM_READY, ST_MSG_STREAM_READY, what="MSG_STREAM_READY"
        )
        await self._zeroize_and_measure(abr, "streaming")

        # VALID: a completed external-mu VERIFY, parked until the zeroize.
        await abr.write_words(ABR_PUBKEY, NIST_SV_ACCEPT.pk)
        await abr.write_words(ABR_SIGNATURE, NIST_SV_ACCEPT.sig)
        await abr.write_words(ABR_EXTERNAL_MU, NIST_SV_ACCEPT.mu)
        await abr.wr32(ABR_CTRL, CMD_VERIFY | CTRL_EXTERNAL_MU)
        await self._wait_status(abr, ST_VALID, ST_VALID, what="VERIFY VALID")
        await self._zeroize_and_measure(abr, "valid")
