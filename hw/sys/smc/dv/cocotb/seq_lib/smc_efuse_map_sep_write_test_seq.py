# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unlocked SEP_IN writes over an all-zero SMC_EFUSE_MAP image.

Contract SMC_EFUSE_MAP_012, anchor smc_efuse_map_sep_write_test.
Scenarios EMAP-WR-SEP.S1-S5, EMAP-RESERVED-BITS.S1-S3, EMAP-ACCESS-WIDTH.S4, EMAP-SHADOW-OUT.S2.
Sources: smc_efuse_map.rdl (address map, reserved fields), port_table.adoc (shadow_regs_o).

Every read is compared against ``shadow``, a per-word model that starts from the image and
changes only when the sequence writes a word. The port compare reads ``shadow_regs`` as one
value against the model packed word n at bits [32n+31:32n]; ``efuse_shadow_probe_o`` is compared
word for word as the secondary observation.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.utils import get_sim_time

from .smc_csr_seq_utils import SmcCsrSeq
from .smc_efuse_image_pattern_test_seq import (
    EFUSE_MAP_BASE,
    EFUSE_MAP_WORDS,
    LOCKS_WORDS,
    REGIONS,
    EfuseImage,
    word_addr,
)

_WORD_MASK = 0xFFFF_FFFF
_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
_SENSE_BOUND_CYCLES = 200_000
_CFG_PATTERN = 0xFFFF_FFFF_FFFF_7F7E
_OCCP_PATTERN = 0xA5A5_A5A5_5A5A_5A5A
_CFG_RSVD = 0xFFFF_FFFF_FFFF_0000 | 0x7E | 0x7F00
_HALF_LO = 0x1234_5678
_HALF_HI = 0x9ABC_DEF0
_CHK_STEP = {
    "CHK-EMAP-WR-JPI": "S2",
    "CHK-EMAP-WR-I2C": "S3",
    "CHK-EMAP-WR-CFG-OCCP": "S4",
    "CHK-EMAP-RSVD-BITS": "S4",
    "CHK-EMAP-WR-SPARE": "S5",
    "CHK-EMAP-WR-NEIGHBOUR": "S5",
    "CHK-EMAP-WR-HALVES": "S6",
    "CHK-EMAP-SHADOW-OUT-WRITE": "S7",
}


class smc_efuse_map_sep_write_test_seq(SmcCsrSeq):
    """Unlocked writes to JPI, I2C_I3C_ID, SMC_CONFIG, OCCP_TRANSPORT_TIMEOUT and SPARE."""

    def __init__(self, name: str = "smc_efuse_map_sep_write_test_seq") -> None:
        super().__init__(name)
        self.image: EfuseImage | None = None
        self.seed = 1
        self.access_floor = 0
        self.shadow: list[int] = []
        self._calls = 0
        self._neighbour_reads = 0
        self._events: list[tuple[str, str]] = []
        self._stamps: list[tuple[str, int]] = []
        self._waits: list[tuple[str, int, str]] = []
        self._used: set[int] = set()
        self._rnd = random.Random(1)

    # --- fence ----------------------------------------------------------
    def _done(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))
        self._events.append(("step", step))

    def _chk(self, chk_id: str, fmt: str, *args) -> None:
        self._events.append(("chk", chk_id))
        cocotb.log.info("%s: " + fmt, chk_id, *args)

    # --- probes ---------------------------------------------------------
    @staticmethod
    def _sig(name: str) -> int:
        dut = cocotb.top
        assert hasattr(dut, name), f"{name} is not a signal of the testbench top"
        value = getattr(dut, name).value
        assert value.is_resolvable, f"{name} is X/Z: {value}"
        return int(value)

    def _sense_state(self) -> str:
        return (
            f"tb_fuse_sense_done={self._sig('tb_fuse_sense_done')},"
            f"tb_fuse_reset_n={self._sig('tb_fuse_reset_n')},"
            f"tb_rst_warm_smc_clk_n={self._sig('tb_rst_warm_smc_clk_n')}"
        )

    async def _sense_wait(self, label: str) -> None:
        try:
            await self.wait_fuse_sense_done(_SENSE_BOUND_CYCLES)
        except AssertionError as exc:
            raise AssertionError(f"{label}: {exc}; {self._sense_state()}") from exc
        self._waits.append((label, _SENSE_BOUND_CYCLES, self._sense_state()))

    # --- access ---------------------------------------------------------
    async def _rd(self, label: str, word: int) -> int:
        self._calls += 1
        return await self.csr_read(label, word_addr(word), expected=self.shadow[word])

    async def _rd64(self, label: str, word: int) -> int:
        self._calls += 1
        expected = self.shadow[word] | (self.shadow[word + 1] << 32)
        return await self.csr_read(label, word_addr(word), expected=expected, length=8)

    async def _wr(self, label: str, word: int, data: int, length: int = 4) -> None:
        self._calls += 1
        await self.csr_write(label, word_addr(word), data, length=length)
        for k in range(length // 4):
            self.shadow[word + k] = (data >> (32 * k)) & _WORD_MASK

    async def _neighbours(self, label: str, below: int | None, above: int | None) -> None:
        """Read the word below and above a written range against the model."""
        for tag, word in (("BELOW", below), ("ABOVE", above)):
            if word is None:
                continue
            await self._rd(f"{label}_{tag}_{word}", word)
            self._neighbour_reads += 1

    def _fresh(self) -> int:
        while True:
            value = self._rnd.getrandbits(32)
            if value in (0, _WORD_MASK) or value in self._used:
                continue
            self._used.add(value)
            return value

    def _probe_matches_model(self) -> int:
        probe = self._sig("efuse_shadow_probe_o")
        for word in range(EFUSE_MAP_WORDS):
            got = (probe >> (32 * word)) & _WORD_MASK
            assert got == self.shadow[word], (
                f"S7: efuse_shadow_probe_o word {word} (0x{word_addr(word) - EFUSE_MAP_BASE:03x}) "
                f"is 0x{got:08x}, model 0x{self.shadow[word]:08x}"
            )
        return EFUSE_MAP_WORDS

    def _port_matches_model(self) -> None:
        expected = sum(self.shadow[n] << (32 * n) for n in range(EFUSE_MAP_WORDS))
        port = self._sig("shadow_regs")
        if port != expected:
            first = next(
                n
                for n in range(EFUSE_MAP_WORDS)
                if (port >> (32 * n)) & _WORD_MASK != self.shadow[n]
            )
            got = (port >> (32 * first)) & _WORD_MASK
            try:
                self._probe_matches_model()
                probe = "efuse_shadow_probe_o == model"
            except AssertionError as exc:
                probe = str(exc)
            raise AssertionError(
                f"S7: shadow_regs port != model; first differing word {first} "
                f"(0x{word_addr(first) - EFUSE_MAP_BASE:03x}) port 0x{got:08x} "
                f"model 0x{self.shadow[first]:08x}; {probe}"
            )

    # --- body -----------------------------------------------------------
    async def body(self) -> None:
        image = self.image
        assert image is not None, "the testcase module sets the image before starting"
        self._rnd = random.Random(self.seed)
        reg = {r.name: r for r in REGIONS}
        jpi = range(reg["JTAG_PUBLIC_IDENTITY"].first_word, reg["JTAG_PUBLIC_IDENTITY"].end_word)
        i2c = range(reg["I2C_I3C_ID"].first_word, reg["I2C_I3C_ID"].end_word)
        cfg = reg["SMC_CONFIG"].first_word
        occp = reg["OCCP_TRANSPORT_TIMEOUT"].first_word
        spare = [range(reg[f"SPARE{k}"].first_word, reg[f"SPARE{k}"].end_word) for k in range(28)]
        locks_hi = LOCKS_WORDS[-1]
        assert len(jpi) == 8 and len(i2c) == 18 and all(len(r) == 8 for r in spare), (
            f"field sizes jpi={len(jpi)} i2c={len(i2c)} spare={[len(r) for r in spare]}"
        )
        assert word_addr(jpi[0]) - EFUSE_MAP_BASE == 0x08, f"JPI starts at word {jpi[0]}"
        assert word_addr(i2c[0]) - EFUSE_MAP_BASE == 0x28, f"I2C_I3C_ID starts at word {i2c[0]}"
        assert word_addr(cfg) - EFUSE_MAP_BASE == 0x70, f"SMC_CONFIG at word {cfg}"
        assert word_addr(occp) - EFUSE_MAP_BASE == 0x78, f"OCCP at word {occp}"
        assert all(w == 0 for w in image.words), "the image has a non-zero word"
        assert image.locks == 0, f"image LOCKS 0x{image.locks:x} is not 0"
        self.shadow = list(image.words)

        # S1: sense, then every class to be written reads 0
        await self._sense_wait("sense1")
        for word in (*LOCKS_WORDS, *jpi, *i2c, cfg, cfg + 1, occp, occp + 1):
            await self._rd(f"S1_{word}", word)
        for rng in spare:
            for word in rng:
                await self._rd(f"S1_{word}", word)
        self._done("S1")

        # S2: JPI, one word at a time
        sent_jpi = []
        for word in jpi:
            value = self._fresh()
            await self._wr(f"S2_WR_{word}", word, value)
            sent_jpi.append(value)
            await self._neighbours(f"S2_{word}", locks_hi, i2c[0])
            await self._rd(f"S2_RB_{word}", word)
        self._done("S2")
        self._chk(
            "CHK-EMAP-WR-JPI",
            "8 JPI words 0x08-0x24 read back their distinct patterns %s",
            ",".join(f"0x{v:08x}" for v in sent_jpi),
        )

        # S3: I2C_I3C_ID, 64-bit writes with bits [63:7] non-zero
        sent_i2c = []
        for word in range(i2c[0], i2c[-1] + 1, 2):
            lo = self._fresh()
            hi = self._fresh()
            value = (hi << 32) | lo
            assert value >> 7, "pattern has no bit above bit 6"
            await self._wr(f"S3_WR_{word}", word, value, length=8)
            sent_i2c.append(value)
            await self._neighbours(f"S3_{word}", jpi[-1], cfg)
            await self._rd(f"S3_RB_LO_{word}", word)
            await self._rd(f"S3_RB_HI_{word}", word + 1)
            await self._rd64(f"S3_RB64_{word}", word)
        self._done("S3")
        self._chk(
            "CHK-EMAP-WR-I2C",
            "9 I2C_I3C_ID elements (64-bit writes accepted) read back both halves incl. bits "
            "[63:7]: %s",
            ",".join(f"0x{v:016x}" for v in sent_i2c),
        )

        # S4: SMC_CONFIG and OCCP_TRANSPORT_TIMEOUT
        await self._wr("S4_WR_CFG", cfg, _CFG_PATTERN, length=8)
        await self._wr("S4_WR_OCCP", occp, _OCCP_PATTERN, length=8)
        cfg_rb = await self._rd64("S4_RB_CFG", cfg)
        occp_rb = await self._rd64("S4_RB_OCCP", occp)
        assert cfg_rb & _CFG_RSVD == _CFG_PATTERN & _CFG_RSVD, (
            f"S4: SMC_CONFIG reserved bits read 0x{cfg_rb & _CFG_RSVD:016x}"
        )
        assert cfg_rb == _CFG_PATTERN and occp_rb == _OCCP_PATTERN, (
            f"S4: SMC_CONFIG 0x{cfg_rb:016x}, OCCP 0x{occp_rb:016x}"
        )
        self._done("S4")
        self._chk(
            "CHK-EMAP-WR-CFG-OCCP",
            "SMC_CONFIG 0x%016x and OCCP_TRANSPORT_TIMEOUT 0x%016x read back as written",
            cfg_rb,
            occp_rb,
        )
        self._chk(
            "CHK-EMAP-RSVD-BITS",
            "SMC_CONFIG reserved [6:1],[14:8],[63:16] (mask 0x%016x) read back as written: "
            "reserved bits 0x%016x; OCCP [63:32] read back 0x%08x",
            _CFG_RSVD,
            cfg_rb & _CFG_RSVD,
            occp_rb >> 32,
        )

        # S5: SPARE in seeded random element order
        rnd = random.Random(self.seed)
        order = list(range(28))
        rnd.shuffle(order)
        patterns = {k: rnd.getrandbits(256) for k in range(28)}
        cocotb.log.info("S5 seed=%d element order=%s", self.seed, order)
        past_extent = ""
        for k in order:
            rng = spare[k]
            for n, word in enumerate(rng):
                await self._wr(f"S5_WR_{k}_{n}", word, (patterns[k] >> (32 * n)) & _WORD_MASK)
            for n, word in enumerate(rng):
                got = await self._rd(f"S5_RB_{k}_{n}", word)
                assert got == (patterns[k] >> (32 * n)) & _WORD_MASK, (
                    f"S5: SPARE[{k}] word {n} reads 0x{got:08x}"
                )
            below = occp + 1 if k == 0 else spare[k - 1][-1]
            await self._neighbours(f"S5_{k}", below, spare[k + 1][0] if k < 27 else None)
            if k == 27:
                self._calls += 1
                rdata = await self.csr_read_expect_error(
                    "S5_PAST_EXTENT", word_addr(EFUSE_MAP_WORDS)
                )
                past_extent = (
                    f"0x{word_addr(EFUSE_MAP_WORDS):08x} answered with an error, rdata=0x{rdata:x}"
                )
        self._done("S5")
        self._chk(
            "CHK-EMAP-WR-SPARE",
            "28 SPARE elements, 8 x 32-bit writes each, read back their 256-bit patterns; seed=%d "
            "order=%s",
            self.seed,
            order,
        )
        self._chk(
            "CHK-EMAP-WR-NEIGHBOUR",
            "%d word-below/above reads kept their model values across S2, S3 and S5; word above "
            "SPARE[27]: %s (error response asserted, no value compared)",
            self._neighbour_reads,
            past_extent,
        )

        # S6: half-register writes
        occp_hi_before = self.shadow[occp + 1]
        await self._wr("S6_WR_LO", occp, _HALF_LO)
        lo1 = await self._rd("S6_RB1_LO", occp)
        hi1 = await self._rd("S6_RB1_HI", occp + 1)
        assert hi1 == occp_hi_before
        occp_lo_before = self.shadow[occp]
        await self._wr("S6_WR_HI", occp + 1, _HALF_HI)
        lo2 = await self._rd("S6_RB2_LO", occp)
        hi2 = await self._rd("S6_RB2_HI", occp + 1)
        assert lo2 == occp_lo_before
        self._done("S6")
        self._chk(
            "CHK-EMAP-WR-HALVES",
            "32-bit write 0x%08x at 0x78: low 0x%08x, high unchanged 0x%08x; 32-bit write "
            "0x%08x at 0x7C: high 0x%08x, low unchanged 0x%08x",
            _HALF_LO,
            lo1,
            hi1,
            _HALF_HI,
            hi2,
            lo2,
        )

        # S7: shadow port, sampled after the LOCKS words read back unchanged
        for word in LOCKS_WORDS:
            await self._rd(f"S7_LOCKS_{word}", word)
        self._port_matches_model()
        compared = self._probe_matches_model()
        locks_port = self._sig("tb_efuse_locks")
        assert locks_port == 0, f"S7: tb_efuse_locks is 0x{locks_port:x}, expected 0"
        self._done("S7")
        self._chk(
            "CHK-EMAP-SHADOW-OUT-WRITE",
            "shadow_regs port == model (%d words written S2-S6 + 2 LOCKS words compared; "
            "layout word n at bits [32n+31:32n]); efuse_shadow_probe_o also == model; "
            "tb_efuse_locks=0x%x",
            compared - len(LOCKS_WORDS),
            locks_port,
        )
        self.access_floor = self._calls

        # fence
        assert [s for s, _t in self._stamps] == list(_STEPS), (
            f"steps completed {[s for s, _t in self._stamps]}, expected {list(_STEPS)}"
        )
        times = [t for _s, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        printed = [ident for kind, ident in self._events if kind == "chk"]
        assert printed == list(_CHK_STEP), f"checker lines printed {printed}"
        for index, (kind, ident) in enumerate(self._events):
            if kind == "chk":
                assert ("step", _CHK_STEP[ident]) in self._events[:index], (
                    f"{ident} printed before step {_CHK_STEP[ident]} completed"
                )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence ZERO IMAGE < JPI < I2C < CFG-OCCP < SPARE < HALVES < "
            "SHADOW-OUT; checker lines %s; stamps %s ps",
            ", ".join(printed),
            ", ".join(f"{s}={t}" for s, t in self._stamps),
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s",
            len(self._waits),
            " ".join(
                f"{name}={bound}smc_clk(fails with AssertionError on expiry) last={state}"
                for name, bound, state in self._waits
            ),
        )
