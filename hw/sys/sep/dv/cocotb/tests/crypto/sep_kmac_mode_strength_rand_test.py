# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Each SHA-3, SHAKE, cSHAKE and KMAC mode and strength matches an independent Keccak golden.

RAND-REP. The test drives the OpenTitan KMAC engine directly over the CPU-LSU AXI master (no_cpu, no
firmware) across the SHA-3 / SHAKE / cSHAKE / KMAC family the KM->KMAC
sideload KAT (`sep_km_kmac_sideload_kat_test`, KMAC-256 keyed via keymgr,
cross-check only) does not reach:

    SHA3-224/256/384/512, SHAKE-128/256, cSHAKE-128/256,
    KMAC-128/256 across all five key lengths, and cSHAKE-256 with
    N = S = ""  (14 cells).

The independent pure-Python Keccak golden (env/sep_kmac_golden.py: SHA3/SHAKE cross-checked
vs hashlib, cSHAKE/KMAC vs NIST SP800-185) is the reference. The cSHAKE-256 cell with
N = S = "" is the one exception: SP 800-185 defines cSHAKE(X, L, "", "") as
SHAKE, but the KMAC programmer guide says "Current design does not convert
cSHAKE mode to SHAKE even if PREFIX is empty string" and "The KMAC/SHA3 HWIP
uses PREFIX registers as it is"
(``vendor/lowRISC/opentitan/upstream/hw/ip/kmac/doc/programmers_guide.md`` lines
15-19). That cell writes PREFIX = encode_string("") || encode_string("") and its
golden is the cSHAKE construction with no collapse:
KECCAK[c](bytepad(encode_string("") || encode_string(""), rate) || X || 00, L),
built from the building blocks of ``env/sep_kmac_golden.py``. Distinct from
`sep_km_kmac_sideload_kat_test` (KMAC-256 via sideload, cross-check) -- KMAC
mode/strength breadth is standalone SW-key with an exact golden.

Entropy: the KMAC engine has masking hardwired on (EnMasking=1) and requires EDN
entropy (entropy_mode=EDN) before it produces output, so the test brings up the
real ESRC->DRBG->EDN stack (+esrc_noise_force) or the engine stalls. OTBN/AES/HMAC
are parked so KMAC is the only crypto EDN client: CHK1..CHK4 are bit-exact,
CHK5_kmac is per-sink ROUTING golden. KM is unused.

One SepKmacCfg object drives both the DUT programming (CFG, KEY_LEN, PREFIX, key,
message tail) and the golden. The (mode, strength, key length) cells are walked on
every seed. The seed sets only the message and key content. The digest is read
from STATE share0 ^ share1 (masking on).

Checkers:
  CHK-CELL       per cell (one log line): engine digest == independent
                 Keccak/SP800-185 golden
  CHK-DONE-RW1C  per cell (sep_kmac_seq.run_family): INTR_STATE.kmac_done set ->
                 W1C -> reads 0; CMD DONE returns to idle
  CHK-ERR        per cell: ERR_CODE == 0 and INTR_STATE.kmac_err == 0
  CHK1..CHK4     bit-exact entropy golden (strict scoreboard report); PASS line
                 ``CHK-ENTROPY-CHAIN`` with the match/mismatch count per stage
  CHK5_kmac      post-adapter KMAC beats == AXIS1 in order (single live crypto sink);
                 PASS line ``CHK-KMAC-ROUTING`` with the beat counts (floor 3)
  CHK-RAND-REP   every discrete cell produced its own golden-matching digest,
                 and all digests are distinct (seed logged)
  CHK-KMAC-ALERT-QUIET  bits 5 and 6 of ``crypto_alert_pulse_probe_o`` (the KMAC
                 alert receivers, ``hw/sys/sep/doc/crypto.adoc`` alert routing
                 table; ``hw/sys/sep/doc/kmac.adoc`` "occupies alert indices
                 [6:5]") rise on no clock from before the first cell to after the
                 last CHK-CELL. The KMAC alerts are sent only on an error or an
                 ``ALERT_TEST`` write (``vendor/lowRISC/opentitan/upstream/hw/ip/kmac/data/kmac.hjson``
                 lines 70-86), and the walk has neither.
  CTRL-KMAC-ALERT-LIVE  after the undefined KEY_LEN run, one ``ALERT_TEST`` write
                 of each field (``recov_operation_err``, then ``fatal_fault_err``;
                 "Write 1 to trigger one alert event of this kind",
                 ``vendor/lowRISC/opentitan/overlay/regs/kmac/regs/gen/adoc/kmac.adoc``
                 lines 84-92): bit 5 or bit 6 rises within ``_ALERT_LIVE_CLK``
                 clocks of the write. This is the control of CHK-KMAC-ALERT-QUIET:
                 the same watcher sees a live KMAC alert.

Log-only: ``OBS-KMAC-ALERT-BIT`` logs, per ``ALERT_TEST`` field, the rises and
high clocks of bit 5 and bit 6 in the ``_ALERT_LIVE_CLK`` window after the write,
and for ``fatal_fault_err`` also the rises up to the end of the KMAC reset that
follows it. No text states which receiver index each field reaches, or whether
the fatal sender repeats. ``OBS-KMAC-KEYLEN-UNDEF``, one KMAC-256 run after the walk with ``KEY_LEN``
drawn from the undefined codes 5 to 7 and a 512-bit software key: kmac_err,
ERR_CODE and whether the digest equals the 512-bit-key golden. No text states the
outcome of these codes.

FCOV gate: the leaf opens the graded window of its owner code before the cells
and closes it after the last cell. After each CHK-CELL passes it writes the pass
label ``kmac_mode_pass`` (``set_kmac_mode_pass``), holds it for ``_LABEL_EDGES``
clk_i edges and writes 0 before the next cell; ``cp_prefix_custom`` and
``cp_cell_digest_ok`` sample only on that rise.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env.sep_bit_watch import SepBitWatch
from env.sep_fcov_gate import close_graded_window, open_graded_window, set_kmac_mode_pass
from env.sep_kmac_golden import (
    _RATE,
    _bytepad,
    _keccak,
    _le_bytes_to_words,
    _words_to_le_bytes,
    encode_string,
    kmac_family_words,
    right_encode,
)
from env.sep_seeded_rng import SepSeededRng
from env.sep_spec_tables import (
    KMAC_KEY_LENGTHS,
    KMAC_SHA3_DIGEST_BYTES,
    KMAC_SHA3_STRENGTHS,
    KMAC_XOF_STRENGTHS,
)
from sep_base_test import sep_base_test
from sep_reg_meta import KMAC
from seq_lib.sep_kmac_seq import (
    KMAC_CFG_SHADOWED,
    KMAC_CMD,
    KMAC_CMD_DONE,
    KMAC_CMD_PROCESS,
    KMAC_CMD_START,
    KMAC_ERR_CODE,
    KMAC_INTR_KMAC_DONE,
    KMAC_INTR_KMAC_ERR,
    KMAC_INTR_STATE,
    KMAC_KEY_LEN,
    KMAC_KEY_SHARE0,
    KMAC_KEY_SHARE1,
    KMAC_STATUS,
    KMAC_STATUS_SQUEEZE,
    SepKmac,
    SepKmacCfg,
)

TEST = "sep_kmac_mode_strength_rand_test"

# Walk set: FIPS 202 SHA-3 family + kmac.adoc/RDL SHAKE/cSHAKE 128/256 +
# keyed KMAC (cSHAKE + kmac_en) at those XOF strengths. XOF output lengths
# and customization strings are the test instance. KEY_LEN widths are the
# DV-owned walk (RDL has no enum). The last cell is cSHAKE-256 with N = S = "":
# the engine does not convert cSHAKE to SHAKE for an empty PREFIX
# (programmers_guide.md lines 15-19), so its golden is cshake_empty_prefix_words.
CELLS = (
    [("sha3", s, KMAC_SHA3_DIGEST_BYTES[s], None, b"") for s in KMAC_SHA3_STRENGTHS]
    + [("shake", s, 32, None, b"") for s in KMAC_XOF_STRENGTHS]
    + [
        ("cshake", 128, 32, None, b"OSS DV cSHAKE"),
        ("cshake", 256, 32, None, b"Email Signature"),
        ("kmac", 128, 32, 128, b""),
        ("kmac", 256, 64, 256, b"My Tagged Application"),
        ("kmac", 256, 32, 192, b""),
        ("kmac", 256, 32, 384, b"Key384"),
        ("kmac", 256, 32, 512, b"Key512"),
        ("cshake", 256, 32, None, b""),
    ]
)
assert {c[3] for c in CELLS if c[0] == "kmac"} == set(KMAC_KEY_LENGTHS)

# KEY_LEN.len codes 5 to 7: "Other values are reserved."
# (vendor/lowRISC/opentitan/upstream/hw/ip/kmac/doc/registers.md lines 695-703).
UNDEF_KEY_LEN_CODES = range(5, 8)
_CMD_ERR_PROCESSED = KMAC.field_mask("CMD", "err_processed")
# Outer limit, in clk_i cycles, of the squeeze-or-error wait of the undefined KEY_LEN run.
_UNDEF_BOUND_CLK = 80_000
_POLL_CLK = 20
# Minimum scored CHK5_kmac beats of the walk (see the set_min_matches call).
_CHK5_KMAC_MIN = 3

# KMAC alert receivers [6:5] of crypto_alert_pulse_probe_o (crypto.adoc alert
# routing table; hw/sys/sep/doc/kmac.adoc).
KMAC_ALERT_IDX = {"a5": 5, "a6": 6}
_ALERT_TEST = KMAC.addr("ALERT_TEST")
_ALERT_FIELDS = ("recov_operation_err", "fatal_fault_err")
# Clocks after an ALERT_TEST write in which a receiver pulse must rise, and the
# OBS-KMAC-ALERT-BIT window. A testbench bound, not a spec value.
_ALERT_LIVE_CLK = 256
_RESET_EDGE_CLK = 200
# clk_i edges the pass label stays 1: the edge that registers the write and one
# on which the sampler sees the rise.
_LABEL_EDGES = 2


def cshake_empty_prefix_words(msg_words: list[int], sec: int, outlen_bytes: int) -> list[int]:
    """cSHAKE with N = S = "" and no collapse to SHAKE, as STATE words.

    KECCAK[c](bytepad(encode_string("") || encode_string(""), rate) || X || 00, L):
    the SP 800-185 cSHAKE construction (domain bits 00, byte 0x04) with the empty
    PREFIX the engine absorbs as written (programmers_guide.md lines 15-19).
    """
    rate = _RATE[sec]
    x = _bytepad(encode_string(b"") + encode_string(b""), rate) + _words_to_le_bytes(msg_words)
    return _le_bytes_to_words(_keccak(rate, x, 0x04, outlen_bytes))


@pyuvm.test()
class sep_kmac_mode_strength_rand_test(sep_base_test):
    """SHA3/SHAKE/cSHAKE/KMAC at every strength with a SW key each match the golden."""

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu(park=("otbn", "aes", "hmac"))
        # Every other crypto-EDN client is JTAG-held across rst_ni release, then
        # parked in SW_RESET_N, so CHK5_kmac golden routing is in order (one live
        # sink). KMAC stays released for the masking reseed.
        await self.bring_up_entropy(strict=True, score_km=False, score_sinks={"kmac": "golden"})
        # KMAC draws entropy once per operation rather than per block, so this
        # walk scores about six routed beats where the AES sweep scores over a
        # hundred. 3 sits well above the default floor of 1 and keeps margin if a
        # later seed or reseed shifts the draw count.
        self.drbg_sb.set_min_matches(CHK5_kmac=_CHK5_KMAC_MIN)
        self.start_fifo_drain()
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"

        self.kmac = SepKmac(self)
        seed = self.random_seed()
        self.rng = SepSeededRng(seed)
        self.logger.info("INFO-KMAC-SEED seed=%d", seed)

        # Collect each cell's DUT result so the matrix claim rests on observed
        # output, not on the loop's own trip count. Distinct results additionally
        # show the cells programmed different configurations.
        results: dict[str, tuple[int, ...]] = {}
        self.alert = SepBitWatch(
            cocotb.top.crypto_alert_pulse_probe_o, KMAC_ALERT_IDX, name="kmac_alert"
        ).start()
        quiet_mark = self.alert.mark()
        await RisingEdge(cocotb.top.clk_i)
        open_graded_window(TEST, self.logger)
        for mode, sec, outb, key_bits, s in CELLS:
            # Key the cell by every dimension that distinguishes it, key length
            # and customization included: two cells that differ only in key
            # length would otherwise overwrite each other and go uncounted.
            cell_key = f"{mode}-{sec}-{outb}-k{key_bits}-s{s.hex()}"
            assert cell_key not in results, f"duplicate cell key {cell_key} in CELLS"
            results[cell_key] = await self._run_cell(mode, sec, outb, key_bits, s)
        close_graded_window(self.logger)
        self._grade_alert_quiet(quiet_mark, len(results))

        walked = len(results)
        # Construction guard, not a DUT contract: this compares the walk against
        # the cell list that drove it, so only a table or keying mistake in this
        # file can trip it. The DUT evidence is the per-cell golden compare.
        assert walked == len(CELLS), f"walked {walked} cells != {len(CELLS)}"
        assert len(set(results.values())) == len(CELLS), (
            "KMAC cells produced duplicate digests, so they did not all run distinct "
            "configurations: " + ", ".join(f"{k}={results[k][0]:#010x}" for k in sorted(results))
        )
        await self._keylen_undef_cell()
        await self._alert_live_leg()
        await self.alert.stop()
        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        assert self.drbg_sb.report()
        res = self.drbg_sb.results
        self.logger.info(
            "CHK-ENTROPY-CHAIN PASS: seed=%d %s",
            seed,
            " ".join(
                f"{k}=match{res[k].matches}/mismatch{res[k].mismatches}"
                for k in ("CHK1_decor", "CHK2_compress", "CHK3_seed", "CHK4_genbits")
            ),
        )
        route = res["CHK5_kmac"]
        self.logger.info(
            "CHK-KMAC-ROUTING PASS: seed=%d dut_items=%d match=%d mismatch=%d min=%d",
            seed,
            route.dut_items,
            route.matches,
            route.mismatches,
            _CHK5_KMAC_MIN,
        )
        self.logger.info(
            "CHK-RAND-REP PASS: walked all %d discrete cells (%s) in one "
            "invocation (seed=%d); message/key randomized per cell; entropy clean",
            walked,
            ", ".join(sorted(results)),
            seed,
        )

    def _rand_words(self, n: int) -> list[int]:
        return [self.rng.getrandbits(32) for _ in range(n)]

    async def _run_cell(
        self, mode: str, sec: int, outb: int, key_bits: int | None, s: bytes
    ) -> tuple[int, ...]:
        msg = self._rand_words(self.rng.randrange(1, 9))
        key = self._rand_words(key_bits // 32) if mode == "kmac" else None
        cfg = SepKmacCfg(
            mode=mode,
            sec=sec,
            msg_words=msg,
            outlen_bytes=outb,
            key_words=key,
            key_bits=key_bits,
            s=s,
        )
        empty_prefix = mode == "cshake" and not s
        cell = (
            f"{mode.upper()}-{sec}"
            + (f"/key{key_bits}" if mode == "kmac" else "")
            + ("/S-empty" if empty_prefix else "")
        )

        # run_family also proves CHK-DONE-RW1C (kmac_done set -> W1C -> reads 0).
        digest = await self.kmac.run_family(cfg, tag=cell)
        if empty_prefix:
            golden = cshake_empty_prefix_words(msg, sec, outb)
        else:
            golden = kmac_family_words(**cfg.golden_kwargs())
        assert digest == golden, (
            f"{cell} digest != golden:\n  digest={[hex(w) for w in digest]}\n"
            f"  golden={[hex(w) for w in golden]}"
        )

        # Mode and key sensitivity live in sep_kmac_golden (hashlib / NIST SP800-185
        # self-tests at import). This cell only compares digest == golden.
        await self.kmac.check_status_clean(cell)  # CHK-ERR
        self.logger.info(
            "CHK-CELL PASS %s: digest==golden, DONE-RW1C, ERR clean, "
            "non-vacuous (out=%dB, msg=%d words)",
            cell,
            outb,
            len(msg),
        )
        set_kmac_mode_pass(True, self.logger)
        await ClockCycles(cocotb.top.clk_i, _LABEL_EDGES)
        set_kmac_mode_pass(False, self.logger)
        await ClockCycles(cocotb.top.clk_i, 1)
        return tuple(digest)

    def _grade_alert_quiet(self, mark, cells: int) -> None:
        """CHK-KMAC-ALERT-QUIET: no rise on bit 5 or bit 6 over the cell walk."""
        a5 = self.alert.rises_since(mark, "a5")
        a6 = self.alert.rises_since(mark, "a6")
        fields = f"cells={cells} a5_rises={a5} a6_rises={a6} window_clk={self.alert.clk - mark.clk}"
        assert a5 == 0 and a6 == 0, f"CHK-KMAC-ALERT-QUIET FAIL: {fields}"
        self.logger.info("CHK-KMAC-ALERT-QUIET PASS: %s", fields)

    async def _alert_live_leg(self) -> None:
        """CTRL-KMAC-ALERT-LIVE and OBS-KMAC-ALERT-BIT for each ALERT_TEST field.

        A KMAC reset follows the fatal_fault_err write, so the entropy and
        routing checks after this leg see no KMAC sender still active.
        """
        alert = self.alert
        for field in _ALERT_FIELDS:
            mark = alert.mark()
            await self.kmac._wr(_ALERT_TEST, KMAC.field_mask("ALERT_TEST", field))
            await ClockCycles(cocotb.top.clk_i, _ALERT_LIVE_CLK)
            a5 = alert.rise_clks_since(mark, "a5")
            a6 = alert.rise_clks_since(mark, "a6")
            a5_high = alert.high_clocks_since(mark, "a5")
            a6_high = alert.high_clocks_since(mark, "a6")
            first = min(a5 + a6) - mark.clk if a5 or a6 else None
            live = (
                f"field={field} rose={int(first is not None)} clk={first} bound={_ALERT_LIVE_CLK}"
            )
            assert first is not None, f"CTRL-KMAC-ALERT-LIVE FAIL: {live}"
            self.logger.info("CTRL-KMAC-ALERT-LIVE PASS: %s", live)
            to_reset = ""
            if field == "fatal_fault_err":
                await self._reset_kmac()
                to_reset = (
                    f" a5_rises_to_reset={alert.rises_since(mark, 'a5')}"
                    f" a6_rises_to_reset={alert.rises_since(mark, 'a6')}"
                )
            self.logger.info(
                "OBS-KMAC-ALERT-BIT field=%s a5_rises=%d a6_rises=%d a5_high_clk=%d "
                "a6_high_clk=%d window_clk=%d%s",
                field,
                len(a5),
                len(a6),
                a5_high,
                a6_high,
                _ALERT_LIVE_CLK,
                to_reset,
            )

    async def _reset_kmac(self) -> None:
        """One KMAC reset: bit 4 of SW_RESET_N low, then high, then idle."""
        probe = cocotb.top.kmac_gated_rst_n_probe_o
        await self.swrst.park("kmac")
        await self._wait_probe(probe, 0)
        await self.swrst.release("kmac")
        await self._wait_probe(probe, 1)
        await self.kmac._wait_idle("post-reset")

    async def _wait_probe(self, sig, level: int) -> None:
        for _ in range(_RESET_EDGE_CLK):
            await RisingEdge(cocotb.top.clk_i)
            await ReadOnly()
            if self.rd_known(sig) == level:
                return
        raise AssertionError(f"{sig._name} did not read {level} within {_RESET_EDGE_CLK} clocks")

    async def _keylen_undef_cell(self) -> None:
        """One KMAC-256 run with an undefined KEY_LEN code and a 512-bit key; logged only."""
        key_len = self.rng.choice(UNDEF_KEY_LEN_CODES)
        msg = self._rand_words(self.rng.randrange(1, 9))
        key = self._rand_words(512 // 32)
        cfg = SepKmacCfg(
            mode="kmac", sec=256, msg_words=msg, outlen_bytes=32, key_words=key, key_bits=512
        )
        kmac = self.kmac
        await kmac._wr(KMAC_KEY_LEN, key_len)
        await kmac._write_prefix(cfg.prefix_bytes())
        for i, word in enumerate(key):
            await kmac._wr(KMAC_KEY_SHARE0[i], word)
            await kmac._wr(KMAC_KEY_SHARE1[i], 0)
        await kmac._wr(KMAC_CFG_SHADOWED, cfg.cfg_word())
        await kmac._wr(KMAC_CFG_SHADOWED, cfg.cfg_word())
        # The cell only logs, so a KMAC that never returns to idle ends it
        # without failing the leaf.
        try:
            await kmac._wait_idle("keylen-undef")
        except AssertionError:
            self.logger.info(
                "INFO-KMAC-KEYLEN-UNDEF-SKIP key_len=%d: no idle before the run", key_len
            )
            return
        await kmac._wr(KMAC_CMD, KMAC_CMD_START)
        data = b"".join(w.to_bytes(4, "little") for w in msg)
        await kmac._push_msg_bytes(data + right_encode(cfg.outlen_bytes * 8))
        await kmac._wr(KMAC_CMD, KMAC_CMD_PROCESS)
        status = intr = 0
        for _ in range(_UNDEF_BOUND_CLK // _POLL_CLK):
            status = await kmac._rd(KMAC_STATUS)
            intr = await kmac._rd(KMAC_INTR_STATE)
            if status & KMAC_STATUS_SQUEEZE or intr & KMAC_INTR_KMAC_ERR:
                break
            await ClockCycles(cocotb.top.clk_i, _POLL_CLK)
        squeeze = int(bool(status & KMAC_STATUS_SQUEEZE))
        digest = await kmac.read_digest(cfg.outlen_bytes // 4) if squeeze else []
        code = await kmac._rd(KMAC_ERR_CODE)
        golden = kmac_family_words(**cfg.golden_kwargs())
        self.logger.info(
            "OBS-KMAC-KEYLEN-UNDEF key_len=%d squeeze=%d kmac_err=%d err_code=0x%08x "
            "digest_eq_512=%d digest0=%s",
            key_len,
            squeeze,
            int(bool(intr & KMAC_INTR_KMAC_ERR)),
            code,
            int(digest == golden),
            f"0x{digest[0]:08x}" if digest else "na",
        )
        if squeeze:
            await kmac._wr(KMAC_CMD, KMAC_CMD_DONE)
        if intr & KMAC_INTR_KMAC_ERR:
            await kmac._wr(KMAC_CMD, _CMD_ERR_PROCESSED)
        await kmac._wr(KMAC_INTR_STATE, KMAC_INTR_KMAC_DONE | KMAC_INTR_KMAC_ERR)
