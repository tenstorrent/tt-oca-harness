# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Software lock enforcement per field of SMC_EFUSE_MAP.

Sources: smc_efuse_map.rdl (LOCKS), architecture.adoc (Hardware vs. Software Locks),
smc-programming.adoc (whole-field locks), port_table.adoc (shadow_regs_o).

Every field word compare is against ``shadow``, a per-word model that starts from the image and
changes only when a write to an unlocked field lands. A read-locked word is read with errors
allowed and must equal neither its modelled value nor the complement.
"""

from __future__ import annotations

import hashlib
import random

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_csr_seq_utils import SmcCsrSeq
from .smc_efuse_image_pattern_test_seq import (
    LOCKS_WORDS,
    REGIONS,
    EfuseImage,
    word_addr,
)

_WORD_MASK = 0xFFFF_FFFF
_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
_SENSE_BOUND_CYCLES = 200_000
#: (region name, write lock bit, read lock bit) the register map names for orientation.
_CONTRACT_BITS = (
    ("SPARE0", 8, 9),
    ("SPARE1", None, 11),
    ("SPARE27", 62, None),
    ("I2C_I3C_ID", 2, 3),
    ("JTAG_PUBLIC_IDENTITY", 0, 1),
)


class smc_efuse_map_lock_field_enforce_test_seq(SmcCsrSeq):
    """Write-lock, read-lock and both-lock enforcement over SEP_IN."""

    def __init__(self, name: str = "smc_efuse_map_lock_field_enforce_test_seq") -> None:
        super().__init__(name)
        self.image: EfuseImage | None = None
        self.seed = 1
        self.access_floor = 0
        self.locks_model = 0
        self.shadow: list[int] = []
        self._calls = 0
        self._events: list[tuple[str, str]] = []
        self._stamps: list[tuple[str, int]] = []
        self._waits: list[tuple[str, int, str]] = []
        self._used: set[int] = set()
        self._rnd = random.Random(1)
        self._port_mode = ""

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

    def _probe_word(self, word: int) -> int:
        return (self._sig("efuse_shadow_probe_o") >> (32 * word)) & _WORD_MASK

    def _port(self) -> tuple[int, ...]:
        """The shadow_regs port value; the packed struct when cocotb reads it as one value."""
        if not self._port_mode:
            try:
                self._sig("shadow_regs")
                self._port_mode = "shadow_regs"
            except (TypeError, ValueError, AttributeError):
                self._port_mode = "probe+locks"
        if self._port_mode == "shadow_regs":
            return (self._sig("shadow_regs"),)
        return (self._sig("efuse_shadow_probe_o"), self._sig("tb_efuse_locks"))

    @staticmethod
    def _digest(port: tuple[int, ...]) -> str:
        return hashlib.sha256(b"".join(v.to_bytes(2048, "little") for v in port)).hexdigest()[:12]

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
    async def _rd(self, label: str, addr: int, expected: int, length: int = 4) -> int:
        self._calls += 1
        return await self.csr_read(label, addr, expected=expected, length=length)

    async def _read_locks(self, label: str) -> tuple[int, int]:
        addr = word_addr(LOCKS_WORDS[0])
        lo = await self._rd(f"{label}_LO", addr, self.locks_model & _WORD_MASK)
        hi = await self._rd(f"{label}_HI", addr + 4, self.locks_model >> 32)
        return lo & _WORD_MASK, hi & _WORD_MASK

    async def _set_locks(self, label: str, bits: int) -> tuple[int, int]:
        self._calls += 1
        await self.csr_write(label, word_addr(LOCKS_WORDS[0]), bits, length=8)
        self.locks_model |= bits
        return await self._read_locks(f"{label}_RB")

    async def _write_word(self, label: str, word: int, data: int) -> int:
        item = SmcSysAxiItem(f"wr_{label}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = word_addr(word)
        item.length = 4
        item.wdata = data
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self._calls += 1
        assert item.resp_code is not None, f"{label}: the field write got no response"
        return item.resp_code

    async def _read_any(self, label: str, word: int) -> int:
        item = SmcSysAxiItem(f"rd_{label}")
        item.op = SmcSysAxiOp.READ
        item.addr = word_addr(word)
        item.length = 4
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self._calls += 1
        assert item.resp_code is not None, f"{label}: the read got no response"
        return item.rdata & _WORD_MASK

    def _fresh(self) -> int:
        while True:
            value = self._rnd.getrandbits(32)
            if value in (0, _WORD_MASK) or value in self._used or ~value & _WORD_MASK in self._used:
                continue
            self._used.add(value)
            return value

    async def _write_pattern(self, label: str, words: range, *, lands: bool) -> list[int]:
        """Write a new distinct pattern to each word; the model follows when it lands."""
        sent = []
        for word in words:
            value = self._fresh()
            await self._write_word(f"{label}_{word}", word, value)
            sent.append(value)
            if lands:
                self.shadow[word] = value
        return sent

    async def _expect_words(self, label: str, words: range) -> None:
        for word in words:
            await self._rd(f"{label}_{word}", word_addr(word), self.shadow[word])

    async def _expect_hidden(self, label: str, words: range) -> int:
        for word in words:
            held = self.shadow[word]
            got = await self._read_any(f"{label}_{word}", word)
            assert got not in (held, ~held & _WORD_MASK), (
                f"{label}: word {word} reads 0x{got:08x} with its read lock set; "
                f"the field holds 0x{held:08x}"
            )
        return len(words)

    def _probe_matches_model(self, label: str, words: range) -> None:
        for word in words:
            got = self._probe_word(word)
            assert got == self.shadow[word], (
                f"{label}: efuse_shadow_probe_o word {word} is 0x{got:08x}, "
                f"model 0x{self.shadow[word]:08x}"
            )

    # --- body -----------------------------------------------------------
    async def body(self) -> None:
        image = self.image
        assert image is not None, "the testcase module sets the image before starting"
        self._rnd = random.Random(self.seed)
        reg = {r.name: r for r in REGIONS}
        for name, wbit, rbit in _CONTRACT_BITS:
            for kind, bit, mask in (
                ("write", wbit, reg[name].write_lock),
                ("read", rbit, reg[name].read_lock),
            ):
                if bit is not None:
                    assert mask == 1 << bit, (
                        f"{name} {kind} lock mask 0x{mask:x} is not LOCKS bit {bit}"
                    )
        spare = {
            k: range(reg[f"SPARE{k}"].first_word, reg[f"SPARE{k}"].end_word) for k in (0, 1, 26, 27)
        }
        i2c = range(reg["I2C_I3C_ID"].first_word, reg["I2C_I3C_ID"].end_word)
        jpi = range(reg["JTAG_PUBLIC_IDENTITY"].first_word, reg["JTAG_PUBLIC_IDENTITY"].end_word)
        assert len(i2c) == 18 and len(jpi) == 8 and all(len(r) == 8 for r in spare.values()), (
            f"field sizes i2c={len(i2c)} jpi={len(jpi)} spare={[len(r) for r in spare.values()]}"
        )
        assert all(w == 0 for w in image.words), "the image has a non-zero word"
        self.shadow = list(image.words)
        self.locks_model = image.locks
        assert self.locks_model == 0, f"image LOCKS 0x{self.locks_model:x} is not 0"
        wl = {n: reg[n].write_lock for n in reg}
        rl = {n: reg[n].read_lock for n in reg}

        # S1: sense, LOCKS 0
        await self._sense_wait("sense1")
        lo, hi = await self._read_locks("BASE_LOCKS")
        self._done("S1")

        # S2: positive control
        groups = [spare[0], spare[1], spare[27], i2c, jpi]
        for rng in groups:
            await self._write_pattern("S2_WR", rng, lands=True)
            await self._expect_words("S2_RB", rng)
        self._done("S2")

        # S3: SPARE[0] and SPARE[27] write locks, neighbours
        await self._set_locks("S3_WLOCK", wl["SPARE0"] | wl["SPARE27"])
        port_a = self._port()
        held = {}
        for k in (0, 27):
            held[k] = list(self.shadow[w] for w in spare[k])
            await self._write_pattern(f"S3_LOCKED_SPARE{k}", spare[k], lands=False)
        port_b = self._port()
        assert port_a == port_b, (
            f"shadow port changed across rejected writes: {self._digest(port_a)} -> "
            f"{self._digest(port_b)}"
        )
        for k in (0, 27):
            await self._expect_words(f"S3_HELD_SPARE{k}", spare[k])
            assert [self.shadow[w] for w in spare[k]] == held[k]
        for k in (1, 26):
            await self._write_pattern(f"S3_NB_SPARE{k}", spare[k], lands=True)
            await self._expect_words(f"S3_NB_RB_SPARE{k}", spare[k])
        self._done("S3")
        self._chk(
            "CHK-EMAP-ENF-WR-SPARE",
            "LOCKS=0x%016x write locks SPARE[0] bit 8 and SPARE[27] bit 62: 16 words rejected a "
            "new pattern and read their S2 pattern",
            self.locks_model,
        )
        self._chk(
            "CHK-EMAP-ENF-NEIGHBOUR",
            "SPARE[1] and SPARE[26] accepted a new pattern and read it back: 16 words",
        )
        port_s3 = self._digest(port_a)

        # S4: I2C write lock
        await self._set_locks("S4_WLOCK", wl["I2C_I3C_ID"])
        await self._write_pattern("S4_LOCKED_I2C", i2c, lands=False)
        await self._expect_words("S4_HELD_I2C", i2c)
        self._done("S4")
        self._chk(
            "CHK-EMAP-WHOLE-I2C-WR",
            "LOCKS=0x%016x I2C_I3C_ID write lock bit 2: all %d words kept their S2 pattern",
            self.locks_model,
            len(i2c),
        )

        # S5: JPI write lock
        await self._set_locks("S5_WLOCK", wl["JTAG_PUBLIC_IDENTITY"])
        await self._write_pattern("S5_LOCKED_JPI", jpi, lands=False)
        await self._expect_words("S5_HELD_JPI", jpi)
        self._done("S5")

        # S6: read-only locks
        await self._set_locks("S6_RLOCK_SPARE1", rl["SPARE1"])
        hidden1 = await self._expect_hidden("S6_HIDDEN_SPARE1", spare[1])
        self._probe_matches_model("S6_PRE", spare[1])
        sent = await self._write_pattern("S6_RDONLY_WR_SPARE1", spare[1], lands=True)
        self._probe_matches_model("S6_POST", spare[1])
        await self._set_locks("S6_RLOCK_I2C", rl["I2C_I3C_ID"])
        port_d = self._port()
        hidden_i2c = await self._expect_hidden("S6_HIDDEN_I2C", i2c)
        port_e = self._port()
        assert port_d == port_e, (
            f"shadow port changed across hidden reads: {self._digest(port_d)} -> "
            f"{self._digest(port_e)}"
        )
        self._done("S6")
        self._chk(
            "CHK-EMAP-PAIR-RDONLY",
            "LOCKS=0x%016x SPARE[1] read lock bit 11 only: %d words read neither value nor "
            "complement; a write of %d new words landed (efuse_shadow_probe_o == pattern, "
            "first 0x%08x)",
            self.locks_model,
            hidden1,
            len(sent),
            sent[0],
        )
        self._chk(
            "CHK-EMAP-WHOLE-I2C-RD",
            "LOCKS=0x%016x I2C_I3C_ID read lock bit 3: all %d words read neither value nor "
            "complement",
            self.locks_model,
            hidden_i2c,
        )
        self._chk(
            "CHK-EMAP-ENF-PORT",
            "port bit-identical before/after rejected writes (S3) and across hidden reads "
            "(S6): mode %s, %d value(s), sha256 %s (S3) %s (S6 I2C)",
            self._port_mode,
            len(port_a),
            port_s3,
            self._digest(port_d),
        )

        # S7: both locks
        await self._set_locks("S7_RLOCK", rl["JTAG_PUBLIC_IDENTITY"] | rl["SPARE0"])
        both = [jpi, spare[0]]
        for rng in both:
            self._probe_matches_model("S7_PRE", rng)
        probe_before = {w: self._probe_word(w) for rng in both for w in rng}
        hidden_both = 0
        for name, rng in (("JPI", jpi), ("SPARE0", spare[0])):
            hidden_both += await self._expect_hidden(f"S7_HIDDEN_{name}", rng)
        for name, rng in (("JPI", jpi), ("SPARE0", spare[0])):
            await self._write_pattern(f"S7_BOTH_WR_{name}", rng, lands=False)
        probe_after = {w: self._probe_word(w) for rng in both for w in rng}
        assert probe_before == probe_after, "efuse_shadow_probe_o changed under write+read locks"
        hidden_after = 0
        for name, rng in (("JPI", jpi), ("SPARE0", spare[0])):
            hidden_after += await self._expect_hidden(f"S7_HIDDEN2_{name}", rng)
        self._done("S7")
        self._chk(
            "CHK-EMAP-WHOLE-JPI",
            "JPI write lock bit 0 (S5) kept %d words after a write; read lock bit 1 (S7) hid %d "
            "words (neither value nor complement)",
            len(jpi),
            len(jpi),
        )
        self._chk(
            "CHK-EMAP-WHOLE-SPARE",
            "SPARE[0] write lock bit 8 (S3) kept %d words after a write; read lock bit 9 (S7) "
            "hid %d words (neither value nor complement)",
            len(spare[0]),
            len(spare[0]),
        )
        self._chk(
            "CHK-EMAP-PAIR-BOTH",
            "LOCKS=0x%016x JPI and SPARE[0] write+read locks: %d words hid their value before "
            "and %d after a further write; %d probe words unchanged",
            self.locks_model,
            hidden_both,
            hidden_after,
            len(probe_after),
        )
        assert (lo, hi) == (0, 0)
        self.access_floor = self._calls

        # fence
        assert [s for s, _t in self._stamps] == list(_STEPS), (
            f"steps completed {[s for s, _t in self._stamps]}, expected {list(_STEPS)}"
        )
        times = [t for _s, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        chk_step = {
            "CHK-EMAP-ENF-WR-SPARE": "S3",
            "CHK-EMAP-ENF-NEIGHBOUR": "S3",
            "CHK-EMAP-WHOLE-I2C-WR": "S4",
            "CHK-EMAP-PAIR-RDONLY": "S6",
            "CHK-EMAP-WHOLE-I2C-RD": "S6",
            "CHK-EMAP-ENF-PORT": "S6",
            "CHK-EMAP-WHOLE-JPI": "S7",
            "CHK-EMAP-WHOLE-SPARE": "S7",
            "CHK-EMAP-PAIR-BOTH": "S7",
        }
        printed = [ident for kind, ident in self._events if kind == "chk"]
        assert printed == list(chk_step), f"checker lines printed {printed}"
        for index, (kind, ident) in enumerate(self._events):
            if kind == "chk":
                assert ("step", chk_step[ident]) in self._events[:index], (
                    f"{ident} printed before step {chk_step[ident]} completed"
                )
        pos = {ident: i for i, (_k, ident) in enumerate(self._events)}
        assert (
            pos["S2"]
            < pos["CHK-EMAP-ENF-WR-SPARE"]
            < pos["CHK-EMAP-WHOLE-I2C-WR"]
            < pos["S5"]
            < pos["S6"]
            < pos["CHK-EMAP-PAIR-RDONLY"]
            < pos["S7"]
            < pos["CHK-EMAP-PAIR-BOTH"]
        )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence BASELINE < WRITE LOCKS < READ-ONLY LOCKS < BOTH LOCKS; "
            "checker lines %s; stamps %s ps",
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
