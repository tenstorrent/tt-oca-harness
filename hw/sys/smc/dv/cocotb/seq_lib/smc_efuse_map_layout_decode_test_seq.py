# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Address decode of SMC_EFUSE_MAP over a unique-index marker image.

Sources: smc_efuse_map.rdl (address map), smc.rdl (smc_efuse_map ocah_past_extent_resp).

Every expected word is ``image.words[n]`` of the generated image. The past-extent responder
answers read DECERR with data 0xBADCAB1E and write SLVERR; the items carry ``resp_code`` and
``rdata`` for the compare.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import (
    _component_row,
    generated_past_extent_resp,
    smc_addr,
    smc_indexed_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_efuse_image_pattern_test_seq import EFUSE_MAP_WORDS, EfuseImage

_MASK32 = 0xFFFF_FFFF
_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11")
_SENSE_BOUND_CYCLES = 200_000
_AXI_OKAY = 0
_AXI_CODES = {"OKAY": 0, "EXOKAY": 1, "SLVERR": 2, "DECERR": 3}
_PAST_RRESP, _PAST_BRESP = generated_past_extent_resp("smc_efuse_map")
_PAST_DATA = _component_row("smc_efuse_map")["past_response"]["rdata"]
_PAST_OFFSETS = (0x100, 0xFFC)
_CHK_STEP = {
    "CHK-EMAP-LAYOUT-JPI-I2C": "S2",
    "CHK-EMAP-LAYOUT-CFG-OCCP": "S3",
    "CHK-EMAP-LAYOUT-SPARE": "S4",
    "CHK-EMAP-LAYOUT-SWEEP": "S5",
    "CHK-EMAP-WIDTH-32": "S6",
    "CHK-EMAP-WIDTH-64": "S7",
    "CHK-EMAP-WIDTH-CFG": "S8",
    "CHK-EMAP-PAST-READ": "S9",
    "CHK-EMAP-PAST-WRITE": "S10",
    "CHK-EMAP-PAST-NOCHANGE": "S11",
}
_EDGE_OFFSETS = (0x0C, 0x10, 0x2C, 0x30, 0x74, 0x78, 0x7C, 0x80, 0x84, 0x88, 0xE4, 0xE8)


class smc_efuse_map_layout_decode_test_seq(SmcCsrSeq):
    """Decode of every region, both read widths and the past-extent responder."""

    def __init__(self, name: str = "smc_efuse_map_layout_decode_test_seq") -> None:
        super().__init__(name)
        self.image: EfuseImage | None = None
        self.access_floor = 0
        self._calls = 0
        self._events: list[tuple[str, str]] = []
        self._stamps: list[tuple[str, int]] = []
        self._waits: list[tuple[str, int, str]] = []

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
    async def _rd(self, label: str, offset: int, expected: int) -> int:
        self._calls += 1
        return await self.csr_read(label, self.base + offset, expected=expected)

    async def _rd64(self, label: str, offset: int, expected: int) -> int:
        self._calls += 1
        return await self.csr_read(label, self.base + offset, expected=expected, length=8)

    def _word(self, offset: int) -> int:
        return self.image.words[offset // 4]

    def _pair(self, word: int) -> int:
        return (self.image.words[word + 1] << 32) | self.image.words[word]

    async def _sweep(self, tag: str) -> None:
        for n in range(EFUSE_MAP_WORDS):
            await self._rd(f"{tag}_{n}", 4 * n, self.image.words[n])

    # --- body -----------------------------------------------------------
    async def body(self) -> None:
        image = self.image
        assert image is not None, "the testcase module sets the image before starting"
        self.base = smc_addr("SMC_TOP_SMC_EFUSE_MAP_BASE_ADDR")
        words = image.words
        assert smc_addr("SMC_TOP_SMC_EFUSE_MAP_SIZE") == 0x100, "SMC_EFUSE_MAP size is not 0x100"
        bases = {
            "HARNESS_LOCKS": (smc_addr("SMC_TOP_SMC_EFUSE_MAP_HARNESS_LOCKS_BASE_ADDR"), 0x00),
            "SUPPLEMENTARY_LOCKS": (
                smc_addr("SMC_TOP_SMC_EFUSE_MAP_SUPPLEMENTARY_LOCKS_BASE_ADDR"),
                0x08,
            ),
            "JPI": (smc_addr("SMC_TOP_SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY_BASE_ADDR"), 0x10),
            "SMC_CONFIG": (smc_addr("SMC_TOP_SMC_EFUSE_MAP_SMC_CONFIG_BASE_ADDR"), 0x78),
            "OCCP": (smc_addr("SMC_TOP_SMC_EFUSE_MAP_OCCP_TRANSPORT_TIMEOUT_BASE_ADDR"), 0x80),
        }
        for name, (addr, offset) in bases.items():
            assert addr - self.base == offset, f"{name} base is +0x{addr - self.base:x}"
        i2c = [
            smc_indexed_addr("SMC_TOP_SMC_EFUSE_MAP_I2C_I3C_ID_BASE_ADDR", i) - self.base
            for i in range(9)
        ]
        spare_num = smc_addr("SMC_TOP_SMC_EFUSE_MAP_SPARE_NUM")
        tail_num = smc_addr("SMC_TOP_SMC_EFUSE_MAP_SPARE_TAIL_NUM")
        spare = [
            smc_indexed_addr("SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR", k) - self.base
            for k in range(spare_num)
        ]
        tail = [
            smc_indexed_addr("SMC_TOP_SMC_EFUSE_MAP_SPARE_TAIL_BASE_ADDR", k) - self.base
            for k in range(tail_num)
        ]
        assert i2c == [0x30 + 8 * i for i in range(9)], f"I2C_I3C_ID offsets {i2c}"
        assert spare == [0x88 + 0x20 * k for k in range(3)], f"SPARE offsets {spare}"
        assert tail == [0xE8 + 8 * k for k in range(3)], f"SPARE_TAIL offsets {tail}"

        assert len(words) == EFUSE_MAP_WORDS and len(set(words)) == EFUSE_MAP_WORDS, (
            f"image holds {len(set(words))} distinct words of {len(words)}"
        )
        assert words[0] == 0 and words[1] == 0x4000_0000, (
            f"LOCKS words 0x{words[0]:08x}/0x{words[1]:08x}"
        )
        assert not any(
            image.write_locked(w) or image.read_locked(w) for w in range(EFUSE_MAP_WORDS)
        ), f"image LOCKS 0x{image.locks:x} locks a map region"

        # S1
        await self._sense_wait("sense1")
        self._done("S1")

        # S2
        jpi = [await self._rd(f"S2_JPI_{w}", 4 * w, words[w]) for w in range(4, 12)]
        i2c_vals = []
        for i, off in enumerate(i2c):
            w = off // 4
            lo = await self._rd(f"S2_I2C_{i}_LO", off, words[w])
            hi = await self._rd(f"S2_I2C_{i}_HI", off + 4, words[w + 1])
            i2c_vals.append((hi << 32) | lo)
        allv = jpi + [v for pair in i2c_vals for v in (pair & _MASK32, pair >> 32)]
        assert len(set(allv)) == len(allv), "S2: two JPI/I2C_I3C_ID words read equal"
        assert i2c[0] == 0x30 and i2c[-1] == 0x70, f"I2C first/last 0x{i2c[0]:x}/0x{i2c[-1]:x}"
        self._done("S2")
        self._chk(
            "CHK-EMAP-LAYOUT-JPI-I2C",
            "JPI 0x10-0x2C read marker words 4-11 (%s); I2C_I3C_ID[0..8] at 0x30+8i (first 0x%x, "
            "last 0x%x) read marker words 12-29, all 26 values pairwise distinct",
            ",".join(f"0x{v:08x}" for v in jpi),
            i2c[0],
            i2c[-1],
        )

        # S3
        cfg_lo = await self._rd("S3_CFG_LO", 0x78, words[30])
        cfg_hi = await self._rd("S3_CFG_HI", 0x7C, words[31])
        occp_lo = await self._rd("S3_OCCP_LO", 0x80, words[32])
        occp_hi = await self._rd("S3_OCCP_HI", 0x84, words[33])
        cfg = (cfg_hi << 32) | cfg_lo
        occp = (occp_hi << 32) | occp_lo
        assert cfg != occp, f"S3: SMC_CONFIG and OCCP alias at 0x{cfg:016x}"
        self._done("S3")
        self._chk(
            "CHK-EMAP-LAYOUT-CFG-OCCP",
            "0x78/0x7C/0x80/0x84 read marker words 30-33 (0x%08x 0x%08x 0x%08x 0x%08x); "
            "SMC_CONFIG 0x%016x differs from OCCP 0x%016x",
            cfg_lo,
            cfg_hi,
            occp_lo,
            occp_hi,
            cfg,
            occp,
        )

        # S4
        firsts = []
        for k, off in enumerate(spare):
            firsts.append(await self._rd(f"S4_SPARE{k}_FIRST", off, words[off // 4]))
        last0 = await self._rd("S4_SPARE0_LAST", 0xA4, words[0xA4 // 4])
        last2 = await self._rd("S4_SPARE2_LAST", 0xE4, words[0xE4 // 4])
        tails = []
        for k, off in enumerate(tail):
            tails.append(await self._rd(f"S4_SPARE_TAIL{k}_FIRST", off, words[off // 4]))
        tail_last = await self._rd("S4_SPARE_TAIL2_LAST", 0xFC, words[0xFC // 4])
        assert len({*firsts, last0, last2, *tails, tail_last}) == 9, (
            "S4: two SPARE words read equal"
        )
        self._done("S4")
        self._chk(
            "CHK-EMAP-LAYOUT-SPARE",
            "SPARE[0..2] first words at 0x88+0x20k read their marker words (k=0 0x%08x, k=2 "
            "0x%08x); SPARE[0] last word 0xA4 0x%08x, SPARE[2] last word 0xE4 0x%08x; "
            "SPARE_TAIL[0..2] first words at 0xE8+8k (0x%08x 0x%08x 0x%08x) and SPARE_TAIL[2] "
            "last word 0xFC 0x%08x (marker word 63), all 9 values pairwise distinct",
            firsts[0],
            firsts[2],
            last0,
            last2,
            *tails,
            tail_last,
        )

        # S5
        await self._sweep("S5")
        self._done("S5")
        self._chk(
            "CHK-EMAP-LAYOUT-SWEEP",
            "all %d words at 0x4n read marker word n; region-edge offsets included (%s)",
            EFUSE_MAP_WORDS,
            " ".join(f"0x{o:x}=0x{self._word(o):08x}" for o in _EDGE_OFFSETS),
        )

        # S6
        halves = []
        regs = [("HARNESS_LOCKS", 0), ("SUPPLEMENTARY_LOCKS", 2)]
        regs += [(f"I2C{i}", off // 4) for i, off in enumerate(i2c)]
        regs += [("SMC_CONFIG", 30), ("OCCP", 32)]
        for name, w in regs:
            lo = await self._rd(f"S6_{name}_LO", 4 * w, words[w])
            hi = await self._rd(f"S6_{name}_HI", 4 * w + 4, words[w + 1])
            assert lo != hi, f"S6: {name} halves read equal 0x{lo:08x}"
            halves.append((name, lo, hi))
        self._done("S6")
        self._chk(
            "CHK-EMAP-WIDTH-32",
            "%d 64-bit registers (HARNESS_LOCKS, SUPPLEMENTARY_LOCKS, 9 I2C_I3C_ID, SMC_CONFIG, "
            "OCCP) read as separate 32-bit halves equal the marker halves; HARNESS_LOCKS "
            "0x%08x/0x%08x OCCP 0x%08x/0x%08x",
            len(halves),
            halves[0][1],
            halves[0][2],
            halves[-1][1],
            halves[-1][2],
        )

        # S7
        locks64 = await self._rd64("S7_LOCKS", 0, self._pair(0))
        occp64 = await self._rd64("S7_OCCP", 0x80, self._pair(32))
        assert locks64 == (words[1] << 32) | words[0], f"S7: HARNESS_LOCKS 0x{locks64:016x}"
        assert occp64 == (words[33] << 32) | words[32], f"S7: OCCP 0x{occp64:016x}"
        self._done("S7")
        self._chk(
            "CHK-EMAP-WIDTH-64",
            "64-bit read of HARNESS_LOCKS 0x%016x = {word1,word0}; OCCP 0x%016x = {word33,word32}",
            locks64,
            occp64,
        )

        # S8
        item = SmcSysAxiItem("rd_S8_CFG")
        item.op = SmcSysAxiOp.READ
        item.addr = self.base + 0x78
        item.length = 4
        item.expected = words[30]
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self._calls += 1
        assert item.beats == 1 and item.transfer_bytes == 4, (
            f"S8: item beats={item.beats} transfer_bytes={item.transfer_bytes}"
        )
        assert item.resp_code == _AXI_OKAY, f"S8: resp_code={item.resp_code}"
        assert item.rdata == words[30], f"S8: rdata 0x{item.rdata:x} != 0x{words[30]:08x}"
        self._done("S8")
        self._chk(
            "CHK-EMAP-WIDTH-CFG",
            "32-bit read of 0x78 completed as one item (beats=%d, transfer_bytes=%d, one R "
            "handshake) with resp_code=%d and rdata 0x%08x = marker word 30",
            item.beats,
            item.transfer_bytes,
            item.resp_code,
            item.rdata,
        )

        # S9
        edge = await self._rd("S9_LAST", 0xFC, words[EFUSE_MAP_WORDS - 1])
        past = []
        for off in _PAST_OFFSETS:
            self._calls += 1
            rdata = await self.csr_read_err_signature(
                f"S9_PAST_{off:x}", self.base + off, resp=_AXI_CODES[_PAST_RRESP]
            )
            assert rdata == _PAST_DATA, f"S9: 0x{off:x} rdata 0x{rdata:x}"
            past.append(rdata)
        self._done("S9")
        self._chk(
            "CHK-EMAP-PAST-READ",
            "0xFC read marker word 63 0x%08x with OKAY; 0x100 and 0xFFC each answered "
            "resp=%s(%d) with rdata 0x%08x / 0x%08x (smc.rdl smc_efuse_map "
            "ocah_past_extent_resp)",
            edge,
            _PAST_RRESP,
            _AXI_CODES[_PAST_RRESP],
            past[0],
            past[1],
        )

        # S10
        resps = []
        for off in _PAST_OFFSETS:
            self._calls += 1
            resps.append(
                await self.csr_write_expect_error(f"S10_PAST_{off:x}", self.base + off, 0xFFFF_FFFF)
            )
        assert all(r > _AXI_OKAY for r in resps), f"S10: non-error bresp {resps}"
        self._done("S10")
        self._chk(
            "CHK-EMAP-PAST-WRITE",
            "0x100 bresp=%d 0xFFC bresp=%d; smc.rdl smc_efuse_map ocah_past_extent_resp declares "
            "%s (%d); the bresp values show which one was returned",
            resps[0],
            resps[1],
            _PAST_BRESP,
            _AXI_CODES[_PAST_BRESP],
        )

        # S11
        await self._sweep("S11")
        locks_lo = await self._rd("S11_LOCKS_LO", 0, 0x0000_0000)
        locks_hi = await self._rd("S11_LOCKS_HI", 4, 0x4000_0000)
        assert (locks_lo, locks_hi) == (0, 0x4000_0000), f"S11: LOCKS {locks_lo:x}/{locks_hi:x}"
        self._done("S11")
        self._chk(
            "CHK-EMAP-PAST-NOCHANGE",
            "after the past-extent accesses all %d words equal their marker words; HARNESS_LOCKS "
            "0x%08x / 0x%08x",
            EFUSE_MAP_WORDS,
            locks_lo,
            locks_hi,
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
            "CHK-NONVAC: ordered fence SENSE DONE < LAYOUT < WIDTH < PAST-READ < PAST-WRITE < "
            "PAST-NOCHANGE; checker lines %s; stamps %s ps",
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
