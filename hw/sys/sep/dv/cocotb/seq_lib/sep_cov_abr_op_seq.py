# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Frontdoor driver for the Adams Bridge operation-shape coverage leaves.

Stimulus only. Nothing here compares a read value against an expectation and
nothing here asserts a design contract. The only failure this module raises is
a bus error or a poll that never reaches its flow-control state, which says the
stimulus did not reach the target rather than that the target misbehaved.

Scope, against the merged VCS run ``build/runs/20260919_225443__vcs__all``:

* ``abr_ctrl`` FSM ``stream_msg_fsm_ps`` reports 1 of 6 states and 0 of 10
  transitions. ``MLDSA_CTRL.STREAM_MSG`` is the only way into it
  (``abr_ctrl.sv:757`` assigns ``stream_msg_mode`` from that field, and
  ``abr_ctrl.sv:1844`` gates ``stream_msg_ip`` on it). The three ML-DSA KAT
  leaves all use the ACVP external-mu vector groups, so they set
  ``MLDSA_CTRL.EXTERNAL_MU`` and hand the engine mu directly; the message
  never streams and the whole FSM stays in ``MLDSA_MSG_IDLE``.
* ``MLDSA_CTRL.CTRL`` command ``KEYGEN_SIGN`` (0x4) and ``MLKEM_CTRL.CTRL``
  command ``KEYGEN_DECAPS`` (0x4) are the two program-counter entry points in
  the ``ABR_RESET`` case (``abr_ctrl.sv:1673`` onward) that no leaf issues.

Register offsets and field masks are resolved by symbol out of the vendor
``abr_reg.rdl`` through ``env/sep_spec_tables.py``, the same way
``seq_lib/sep_abr_keygen_seq.py`` resolves the keygen ones, so a register move
fails at import rather than as a wrong-address access mid-simulation.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from env.sep_spec_tables import abr_ctrl_cmd, abr_field_mask, abr_off, window

from seq_lib.sep_abr_keygen_seq import ABR_MSG, ABR_STATUS, SepAbr

ABR_BASE = window("ABR").base

# Streaming-mode register set. MSG_STROBE, CTX_CONFIG and CTX sit immediately
# above the external-mu window in abr_reg.rdl.
ABR_MSG_STROBE = ABR_BASE + abr_off("MLDSA_MSG_STROBE")
ABR_CTX_CONFIG = ABR_BASE + abr_off("MLDSA_CTX_CONFIG")
ABR_CTX = ABR_BASE + abr_off("MLDSA_CTX")


CTRL_STREAM_MSG = abr_field_mask("MLDSA_CTRL", "STREAM_MSG")
ST_MSG_STREAM_READY = abr_field_mask("MLDSA_STATUS", "MSG_STREAM_READY")
STROBE_FULL = abr_field_mask("MLDSA_MSG_STROBE", "STROBE")

CMD_KEYGEN_SIGN = abr_ctrl_cmd("MLDSA_CTRL", "KEYGEN_SIGN")

# Byte strobe for the last streamed beat. Any value other than all-ones ends
# the stream; 0b0000 is the 32-bit-aligned form abr_reg.rdl describes for
# MLDSA_MSG_STROBE, and the other three are its listed partial values.
# MLDSA_SIGN_RND is eight 32-bit words (abr_reg.rdl:152, `MLDSA_SIGN_RND[8]`),
# alongside the seed and entropy counts sep_abr_keygen_seq already carries.
SIGN_RND_WORDS = 8

TAIL_STROBES = (0b0000, 0b0001, 0b0011, 0b0111)


class SepCovAbrOp(SepAbr):
    """ML-DSA / ML-KEM operation driver for the stimulus leaves.

    ``wr32`` / ``rd32`` come from ``SepAbr`` and raise on a non-OKAY response.
    Every wait below is flow control read out of the engine's own STATUS
    register, never a value compare.
    """

    _DRIVER_TAG = "ABRCOV"

    async def poll_status(
        self,
        addr: int,
        mask: int,
        expect: int,
        *,
        what: str,
        iters: int = 40000,
        gap: int = 200,
    ) -> int:
        """Spin on one STATUS register until the masked field reads ``expect``.

        This is flow control, not a check: the engine publishes READY,
        MSG_STREAM_READY and VALID so software knows when it may write. The
        bounded loop exists so a stalled engine fails here with the address and
        the last word rather than as a bare simulation timeout.
        """
        last = 0
        for _ in range(iters):
            last = await self.rd32(addr)
            if (last & mask) == expect:
                return last
            await ClockCycles(cocotb.top.clk_i, gap)
        raise AssertionError(
            f"{what}: STATUS @0x{addr:08x} mask 0x{mask:x} never read 0x{expect:x} "
            f"in {iters} polls (last 0x{last:08x})"
        )

    async def write_ctx(self, ctx_size: int, words: list[int]) -> None:
        """Load MLDSA_CTX_CONFIG.CTX_SIZE and the context words.

        ``ctx_size`` is a byte count. ``abr_ctrl.sv:1859`` splits it into
        ``ctx_cnt_required`` and ``ctx_cnt_offset``, which are the loop bound
        and the last-beat strobe of the MLDSA_MSG_CTX state.
        """
        await self.wr32(ABR_CTX_CONFIG, ctx_size)
        await self.write_words(ABR_CTX, words)

    async def stream_message(self, msg_words: list[int], tail_strobe: int, tail_word: int) -> int:
        """Stream a message through MLDSA_MSG while the engine holds
        MSG_STREAM_READY.

        One beat is one ``MLDSA_MSG_STROBE`` write followed by one
        ``MLDSA_MSG[0]`` write. The strobe write must come first: the MSG write
        is what raises ``stream_msg_valid`` (``abr_ctrl.sv:1838``), and the
        strobe is sampled in the same cycle. ``MLDSA_MSG_STROBE.STROBE`` is
        ``swwe = stream_msg_rdy``, so MSG_STREAM_READY is re-read before every
        beat; a strobe written outside that window is dropped silently and the
        beat would carry the previous value.

        A final beat whose strobe is not all-ones moves the FSM to
        MLDSA_MSG_FLUSH and then MLDSA_MSG_DONE. Returns the number of beats
        driven.
        """
        beats = 0
        for word in msg_words:
            await self.poll_status(
                ABR_STATUS, ST_MSG_STREAM_READY, ST_MSG_STREAM_READY, what="msg beat"
            )
            await self.wr32(ABR_MSG_STROBE, STROBE_FULL)
            await self.wr32(ABR_MSG, word)
            beats += 1

        await self.poll_status(
            ABR_STATUS, ST_MSG_STREAM_READY, ST_MSG_STREAM_READY, what="msg tail beat"
        )
        await self.wr32(ABR_MSG_STROBE, tail_strobe)
        await self.wr32(ABR_MSG, tail_word)
        return beats + 1
