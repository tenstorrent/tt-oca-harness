# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""
OcahEntropySource — OCAH AXI-Stream entropy driver for SEP TRNG DV.

This module drives the external TRNG AXI-Stream entropy path into the SEP DUT
(``ext_trng_axis_req_i`` / ``ext_trng_axis_rsp_o``) and can assert
``ext_trng_irq_i`` and ``ext_trng_alarm_i`` for negative tests.

Key design principles
---------------------
- **Deterministic by default.** After ``init_signals()`` the BFM emits the
  word from ``+sep_entropy_word`` (default ``0xDEAD_BEEF``) exactly once, then
  stalls — mirroring the Task #12 ``trng_core_stub`` behavior so the BFM and
  stub are interchangeable for Tier-0/Tier-1 tests.
- **Random mode is opt-in.** ``enable_random()`` must be called explicitly.
  Time-of-day seeds are forbidden.
- **Backpressure is modelled.** ``set_backpressure(prob)`` inserts stall cycles
  on tready according to the supplied probability.

AXI-Stream handshake
--------------------
The BFM drives TVALID/TDATA/TSTRB as a *producer* (the trng_wrapper role) and
samples TREADY from the DUT.  A transfer occurs when both TVALID and TREADY are
high on the rising clock edge.

AXI-Stream is implemented locally (no cocotbext-axi dependency) because:
1. The project does not guarantee cocotbext-axi is installed.
2. The entropy stream is 32-bit wide with no ID/LAST/USER fields; a minimal
   local implementation is cleaner than importing a full AXI-Stream VIP.

If cocotbext-axi is later added to the project environment, replace the
``_run_stream_loop`` body with a cocotbext-axi AxiStreamSource instance —
the public API of OcahEntropySource will not change.

Signal mapping
--------------
The BFM accepts either:
  a) A cocotb handle ``dut`` that has signal attributes structured as::

       dut.ext_trng_axis_req_i_tvalid[stream_idx]
       dut.ext_trng_axis_req_i_tdata[stream_idx]
       dut.ext_trng_axis_req_i_tstrb[stream_idx]
       dut.ext_trng_axis_rsp_o_tready[stream_idx]
       dut.ext_trng_irq_i
       dut.ext_trng_alarm_i

  b) A ``signals`` dict with keys:
       ``tvalid``, ``tdata``, ``tstrb``, ``tready``, ``irq``, ``alarm``
     mapping to cocotb signal handles (use for non-standard naming).

  See ``__init__`` for details.
"""

import logging
import os
import random as _random
from typing import Any, Dict, Iterator, List, Optional, Sequence

import cocotb
from cocotb.triggers import RisingEdge, Timer

__all__ = ["OcahEntropySource", "OcahEntropySourceError"]

_DEFAULT_WORD: int = 0xDEAD_BEEF
_FULL_STRB: int = 0xF  # 4-bit strobe for 32-bit data


class OcahEntropySourceError(RuntimeError):
    """Raised on configuration or protocol violations detected by the BFM."""


# ---------------------------------------------------------------------------
# Internal generator helpers (pure Python — no cocotb handles)
# ---------------------------------------------------------------------------

def _constant_generator(word: int) -> Iterator[int]:
    """Yield the same word indefinitely."""
    while True:
        yield word & 0xFFFF_FFFF


def _pattern_generator(words: List[int]) -> Iterator[int]:
    """Yield each word in sequence, then stall by raising StopIteration."""
    yield from (w & 0xFFFF_FFFF for w in words)


def _prng_generator(seed: int) -> Iterator[int]:
    """Yield 32-bit words from a seeded Mersenne-Twister PRNG."""
    rng = _random.Random(seed)
    while True:
        yield rng.getrandbits(32)


# ---------------------------------------------------------------------------
# OcahEntropySource
# ---------------------------------------------------------------------------

class OcahEntropySource:
    """
    Configurable AXI-Stream entropy driver for the SEP TRNG DV path.

    Default mode
    ------------
    After ``init_signals()``, the BFM emits the word from plusarg
    ``+sep_entropy_word`` (default ``0xDEAD_BEEF``) exactly once, then deasserts
    TVALID and stalls.  This matches the Task #12 ``trng_core_stub`` behavior.

    Parameters
    ----------
    clock:
        Cocotb handle for the driving clock.
    signals:
        Dict with keys ``tvalid``, ``tdata``, ``tstrb``, ``tready``,
        ``irq``, ``alarm`` mapping to cocotb signal handles.
        Use this when the DUT wire names differ from the defaults.
    dut:
        If ``signals`` is not supplied, the BFM resolves signal handles from
        ``dut`` using the standard naming convention (see module docstring).
    stream_idx:
        Which stream lane to drive when using ``dut``-based signal resolution.
        Ignored when ``signals`` is provided.  Default 0.
    name:
        Instance label used in log messages.
    """

    def __init__(
        self,
        clock,
        *,
        signals: Optional[Dict[str, Any]] = None,
        dut=None,
        stream_idx: int = 0,
        name: str = "OcahEntropySource",
    ):
        self.name = name
        self.log = logging.getLogger(name)
        self._clock = clock
        self._stream_idx = stream_idx

        # ---- Resolve signal handles ----------------------------------------
        if signals is not None:
            required = {"tvalid", "tdata", "tstrb", "tready", "irq", "alarm"}
            missing = required - signals.keys()
            if missing:
                raise OcahEntropySourceError(
                    f"{name}: 'signals' dict is missing keys: {missing}"
                )
            self._sig_tvalid = signals["tvalid"]
            self._sig_tdata  = signals["tdata"]
            self._sig_tstrb  = signals["tstrb"]
            self._sig_tready = signals["tready"]
            self._sig_irq    = signals["irq"]
            self._sig_alarm  = signals["alarm"]
        elif dut is not None:
            self._sig_tvalid = dut.ext_trng_axis_req_i_tvalid[stream_idx]
            self._sig_tdata  = dut.ext_trng_axis_req_i_tdata[stream_idx]
            self._sig_tstrb  = dut.ext_trng_axis_req_i_tstrb[stream_idx]
            self._sig_tready = dut.ext_trng_axis_rsp_o_tready[stream_idx]
            self._sig_irq    = dut.ext_trng_irq_i
            self._sig_alarm  = dut.ext_trng_alarm_i
        else:
            raise OcahEntropySourceError(
                f"{name}: supply either 'signals' or 'dut'."
            )

        # ---- Internal state -------------------------------------------------
        self._gen: Optional[Iterator[int]] = None  # None = stall mode
        self._backpressure_prob: float = 0.0
        self._bp_rng = _random.Random(0)  # fixed seed for reproducibility
        self._task: Optional[Any] = None
        self._running = False

        # Statistics counters (incremented atomically from the stream loop)
        self._handshake_count: int = 0
        self._backpressure_cycles: int = 0

        # ---- Resolve default word from plusarg ------------------------------
        plus_word = _read_plusarg_hex("sep_entropy_word", _DEFAULT_WORD)
        self._default_word: int = plus_word

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def init_signals(self) -> None:
        """Drive all output signals to their safe idle state.

        Must be called before the first clock edge to avoid X-propagation.
        After this call the BFM is in **single-word stall** mode:
          - ``tvalid=0``, ``tdata=<default_word>``, ``tstrb=0xF``
          - ``irq=0``, ``alarm=0``

        Call ``start()`` to begin the stream loop.
        """
        self._sig_tvalid.value = 0
        self._sig_tdata.value  = self._default_word
        self._sig_tstrb.value  = _FULL_STRB
        self._sig_irq.value    = 0
        self._sig_alarm.value  = 0

        # Configure the default single-word generator (emits one word then stops)
        self._gen = _pattern_generator([self._default_word])
        self.log.debug(
            "%s: init_signals — default word=0x%08X", self.name, self._default_word
        )

    async def start(self) -> None:
        """Start the AXI-Stream driver loop.

        Safe to call multiple times; a second call while running is a no-op.
        """
        if self._running:
            return
        self._running = True
        self._task = cocotb.start_soon(self._run_stream_loop())
        self.log.info("%s: stream driver started", self.name)

    async def stop(self) -> None:
        """Stop the stream loop and drive tvalid low.

        After stop, signals remain at their last driven value until ``init_signals``
        or ``start`` is called again.
        """
        if not self._running:
            return
        self._running = False
        if self._task is not None:
            self._task.kill()
            self._task = None
        self._sig_tvalid.value = 0
        self.log.info(
            "%s: stream driver stopped — %d handshakes completed",
            self.name, self._handshake_count,
        )

    # ------------------------------------------------------------------
    # Configuration — call before start() or between stop()/start() cycles
    # ------------------------------------------------------------------

    def set_pattern(self, words: List[int]) -> None:
        """Drive a fixed sequence of entropy words, then stall.

        The sequence is emitted once in order.  After the last word is accepted
        by the DUT (tvalid && tready), the BFM deasserts tvalid and stalls.
        Call ``set_pattern`` again or reset to emit another sequence.

        Parameters
        ----------
        words : list[int]
            Sequence of 32-bit entropy words.  Must not be empty.
        """
        if not words:
            raise OcahEntropySourceError(f"{self.name}: set_pattern called with empty list")
        self._gen = _pattern_generator([w & 0xFFFF_FFFF for w in words])
        self.log.debug("%s: set_pattern — %d words", self.name, len(words))

    def set_constant_word(self, w: int) -> None:
        """Drive the same 32-bit word indefinitely (no stall).

        Every accepted handshake presents the same value.  Use this for
        long-running deterministic tests where the entropy value is
        irrelevant (just needs to be non-zero / non-stuck).

        Parameters
        ----------
        w : int
            32-bit entropy word.
        """
        w = w & 0xFFFF_FFFF
        self._gen = _constant_generator(w)
        self.log.debug("%s: set_constant_word — 0x%08X", self.name, w)

    def enable_random(self, seed: int) -> None:
        """Switch to opt-in PRNG mode.

        Generates an unlimited stream of 32-bit random words using a
        seeded Mersenne-Twister.  The seed MUST be a fixed integer supplied
        by the caller — time-of-day seeds are forbidden.

        Parameters
        ----------
        seed : int
            Deterministic PRNG seed.  Must be a plain Python int.
            The same seed always produces the same entropy stream.

        Raises
        ------
        OcahEntropySourceError
            If ``seed`` is not an int, to guard against accidental
            float/None values from misconfigured callers.
        """
        if not isinstance(seed, int):
            raise OcahEntropySourceError(
                f"{self.name}: enable_random requires an int seed, got {type(seed).__name__!r}. "
                "Time-of-day seeds are forbidden."
            )
        self._gen = _prng_generator(seed)
        self.log.info("%s: enable_random — seed=%d", self.name, seed)

    def set_backpressure(self, prob: float) -> None:
        """Configure the probability of inserting a tready stall cycle.

        On each cycle where the BFM would assert tvalid, it samples a uniform
        random number.  If the number is less than ``prob`` the BFM deasserts
        tvalid for one additional cycle before presenting the word.

        This uses the BFM's internal reproducible PRNG seeded at construction
        (seed=0).  The backpressure pattern is therefore deterministic unless
        the caller also calls ``enable_random`` (which uses a separate PRNG).

        Parameters
        ----------
        prob : float
            Stall probability in [0.0, 1.0].
            0.0 = never stall (default), 1.0 = stall every cycle.
        """
        if not 0.0 <= prob <= 1.0:
            raise OcahEntropySourceError(
                f"{self.name}: backpressure prob must be in [0.0, 1.0], got {prob}"
            )
        self._backpressure_prob = prob
        self.log.debug("%s: set_backpressure — prob=%.2f", self.name, prob)

    # ------------------------------------------------------------------
    # Injection helpers (for negative/fault tests)
    # ------------------------------------------------------------------

    async def inject_irq(self, duration_cycles: int = 1) -> None:
        """Assert ext_trng_irq_i for ``duration_cycles`` rising edges.

        Parameters
        ----------
        duration_cycles : int
            Number of clock cycles the IRQ remains high.  Default 1.
        """
        self.log.info(
            "%s: inject_irq — asserting for %d cycles", self.name, duration_cycles
        )
        self._sig_irq.value = 1
        for _ in range(duration_cycles):
            await RisingEdge(self._clock)
        self._sig_irq.value = 0
        self.log.debug("%s: inject_irq — deasserted", self.name)

    async def inject_alarm(self, duration_cycles: int = 1) -> None:
        """Assert ext_trng_alarm_i for ``duration_cycles`` rising edges.

        Parameters
        ----------
        duration_cycles : int
            Number of clock cycles the alarm remains high.  Default 1.
        """
        self.log.info(
            "%s: inject_alarm — asserting for %d cycles", self.name, duration_cycles
        )
        self._sig_alarm.value = 1
        for _ in range(duration_cycles):
            await RisingEdge(self._clock)
        self._sig_alarm.value = 0
        self.log.debug("%s: inject_alarm — deasserted", self.name)

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_statistics(self) -> Dict[str, int]:
        """Return a snapshot of BFM counters.

        Returns
        -------
        dict
            ``handshakes``       — accepted transfers (tvalid && tready rising edge).
            ``backpressure_cycles`` — cycles where tvalid was held low by the BFM.
        """
        return {
            "handshakes":          self._handshake_count,
            "backpressure_cycles": self._backpressure_cycles,
        }

    def reset_statistics(self) -> None:
        """Zero all BFM counters."""
        self._handshake_count = 0
        self._backpressure_cycles = 0

    # ------------------------------------------------------------------
    # Internal AXI-Stream driver loop
    # ------------------------------------------------------------------

    async def _run_stream_loop(self) -> None:
        """Main coroutine: drives tvalid/tdata on each clock edge.

        Implements the AXI-Stream producer protocol:
          - When a word is available from the generator, assert tvalid and present
            tdata/tstrb.
          - If backpressure probability fires, deassert tvalid for one cycle.
          - A transfer completes when tvalid && tready on a rising edge.
          - When the generator is exhausted (StopIteration), deassert tvalid and
            stay idle until ``_gen`` is replaced or the task is killed.
        """
        while self._running:
            # --- Try to get the next word from the generator ----------------
            if self._gen is None:
                # Stall mode: no generator
                self._sig_tvalid.value = 0
                await RisingEdge(self._clock)
                continue

            try:
                word = next(self._gen)
            except StopIteration:
                # Generator exhausted — enter stall, keep gen=None
                self._gen = None
                self._sig_tvalid.value = 0
                self.log.debug("%s: generator exhausted — stalling", self.name)
                await RisingEdge(self._clock)
                continue

            # --- Optional backpressure: skip one cycle ----------------------
            if self._backpressure_prob > 0.0:
                if self._bp_rng.random() < self._backpressure_prob:
                    self._sig_tvalid.value = 0
                    self._backpressure_cycles += 1
                    await RisingEdge(self._clock)
                    # After the stall cycle, re-present the same word next time
                    # by pushing it back — wrap the current word in a one-element
                    # prefix to the remaining generator.
                    self._gen = _prepend_word(word, self._gen)
                    continue

            # --- Present word on bus ----------------------------------------
            self._sig_tdata.value  = word
            self._sig_tstrb.value  = _FULL_STRB
            self._sig_tvalid.value = 1

            await RisingEdge(self._clock)

            # Check handshake (DUT accepted the word)
            if int(self._sig_tready.value) == 1:
                self._handshake_count += 1
                self.log.debug(
                    "%s: handshake #%d — word=0x%08X",
                    self.name, self._handshake_count, word,
                )
            else:
                # DUT not ready — must hold tvalid/tdata until accepted.
                # Loop until tready is seen.
                while int(self._sig_tready.value) == 0:
                    await RisingEdge(self._clock)
                self._handshake_count += 1
                self.log.debug(
                    "%s: handshake #%d (after wait) — word=0x%08X",
                    self.name, self._handshake_count, word,
                )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _prepend_word(word: int, gen: Iterator[int]) -> Iterator[int]:
    """Yield ``word`` once, then yield from ``gen``."""
    yield word
    yield from gen


def _read_plusarg_hex(key: str, default: int) -> int:
    """Read a hex-valued cocotb plusarg from the environment.

    Cocotb surfaces simulator plusargs as ``COCOTB_PLUSARG_<KEY>=<VALUE>``
    in the process environment when using cocotb >= 1.8 and a runner that
    forwards plusargs.  For simulators that do not forward them the default
    is returned silently.

    Parameters
    ----------
    key : str
        Plusarg name (without the leading ``+``).
    default : int
        Value to return when the plusarg is absent.
    """
    env_key = f"COCOTB_PLUSARG_{key.upper()}"
    raw = os.environ.get(env_key, "")
    if raw:
        try:
            return int(raw, 16)
        except ValueError:
            logging.getLogger(__name__).warning(
                "Could not parse plusarg +%s=%r as hex int; using default 0x%08X",
                key, raw, default,
            )
    return default
