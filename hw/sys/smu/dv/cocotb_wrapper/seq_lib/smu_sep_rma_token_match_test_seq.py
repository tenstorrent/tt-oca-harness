# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""RMA token submission and match/mismatch results from the SEP debug system bus.

Bring-up is the SEP debug-module steps of ``smu_dtp_sep_dm_dmi_test`` and every later access is
a debug system-bus access (RISC-V Debug Specification 0.13). The eFuse MMR token window takes
the eight-word ``RMA_SIP_TOKEN_I`` and ``RMA_CHIPLET_TOKEN_I`` arrays; a write of 1 to the lane's
``TOKEN_EOP`` bit starts the hash, and the lane's result register holds idle until the digest is
compared with the RMA digest of the SEP eFuse shadow map (``hw/sys/sep/doc/token_processing.adoc``,
"Token Submission" and "Token result encodings").
"""

from __future__ import annotations

import hashlib
from collections import Counter

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time

from seq_lib.smu_addr_map import c_header_u32
from seq_lib.smu_compose_helpers import sample
from seq_lib.smu_dtp_sep_dm_dmi_test_seq import smu_dtp_sep_dm_dmi_test_seq
from seq_lib.smu_dtp_sep_dm_sba_test_seq import _REPO_ROOT, _SEP_ADDR_H, _indexed_addr
from seq_lib.smu_sep_sba_fabric_sweep_test_seq import smu_sep_sba_fabric_sweep_test_seq

_MMR_H = _REPO_ROOT / "hw" / "ip" / "efuse" / "regs" / "gen" / "c" / "efuse_mmr.h"

SIP_TOKEN_WORDS = [
    _indexed_addr("SEP_TOP_EFUSE_MMR_RMA_SIP_TOKEN_I_BASE_ADDR", i) for i in range(8)
]
CHIPLET_TOKEN_WORDS = [
    _indexed_addr("SEP_TOP_EFUSE_MMR_RMA_CHIPLET_TOKEN_I_BASE_ADDR", i) for i in range(8)
]
TOKEN_EOP = c_header_u32(_SEP_ADDR_H, "SEP_TOP_EFUSE_MMR_TOKEN_EOP_BASE_ADDR")
SIP_MATCH = c_header_u32(_SEP_ADDR_H, "SEP_TOP_EFUSE_MMR_RMA_SIP_TOKEN_MATCH_BASE_ADDR")
CHIPLET_MATCH = c_header_u32(_SEP_ADDR_H, "SEP_TOP_EFUSE_MMR_RMA_CHIPLET_TOKEN_MATCH_BASE_ADDR")
MATCH_FAULT = c_header_u32(_SEP_ADDR_H, "SEP_TOP_EFUSE_MMR_TOKEN_MATCH_FAULT_BASE_ADDR")
SIP_DIGEST_FIRST = c_header_u32(_SEP_ADDR_H, "SEP_TOP_SEP_EFUSE_MAP_RMA_SIP_TOKEN_DIGEST_BASE_ADDR")
# sep_efuse_map.rdl RMA_SIP_TOKEN_DIGEST is a 256-bit field of eight 32-bit words.
SIP_DIGEST_LAST = SIP_DIGEST_FIRST + 7 * 4

# efuse_mmr.rdl TOKEN_EOP: rma_sip_token_go is bit 0 and rma_chiplet_token_go is bit 8.
SIP_GO = c_header_u32(_MMR_H, "EFUSE_MMR__TOKEN_EOP__RMA_SIP_TOKEN_GO_bm")
CHIPLET_GO = c_header_u32(_MMR_H, "EFUSE_MMR__TOKEN_EOP__RMA_CHIPLET_TOKEN_GO_bm")
STATUS_MASK = c_header_u32(_MMR_H, "EFUSE_MMR__TOKEN_MATCH__TOKEN_MATCH_STATUS_bm")
# token_processing.adoc, "Token result encodings"; efuse_mmr.rdl TOKEN_MATCH:
# "Match = 6'b010101, Mismatch = 6'b101010".
RESULT_IDLE = 0x00
RESULT_MATCH = 0b010101
RESULT_MISMATCH = 0b101010
# System-bus access size 2 is a 32-bit access (RISC-V Debug Specification 0.13, sbcs.sbaccess).
SB_ACCESS_32 = 2

# Stimulus tokens: 256-bit values written as eight words, index 0 holding token[31:0]
# (token_processing.adoc, "Token Submission"). The two lanes use different tokens, and every word
# of each token differs, so a word written to the wrong index or lane is a different token.
T_SIP = 0x11111111_22222222_33333333_44444444_55555555_66666666_77777777_88888888
T_CHIP = 0xA1A2A3A4_B1B2B3B4_C1C2C3C4_D1D2D3D4_E1E2E3E4_F1F2F3F4_01020304_05060708
T_CHIP_ONE_BIT_OFF = T_CHIP ^ 1


def _digest(token: int) -> int:
    """SHA-256 of the 32-byte big-endian token (token_processing.adoc, digest comparator)."""
    return int.from_bytes(hashlib.sha256(token.to_bytes(32, "big")).digest(), "big")


def _words(value: int) -> list[int]:
    """Eight 32-bit words, index 0 holding bits [31:0]."""
    return [(value >> (32 * i)) & 0xFFFF_FFFF for i in range(8)]


# sep_efuse_map.rdl RMA_SIP_TOKEN_DIGEST token_digest[255:0]: bits [31:0] sit in the lowest word.
SIP_DIGEST_WORDS = _words(_digest(T_SIP))

# Result polls per started leg, in system-bus reads.
RESULT_POLLS = 8
STEP_CLOCK_GAP = 2

EXPECTED_SITE_KINDS = {"sip_match": 1, "chiplet_mismatch": 1, "chiplet_match": 1}
EXPECTED_SITES = 3

STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10")


class smu_sep_rma_token_match_test_seq(smu_sep_sba_fabric_sweep_test_seq):
    """RMA SIP and chiplet token legs: idle, match, mismatch, match, independence."""

    def __init__(self, test) -> None:
        super().__init__(test)
        self.clk = self.dut.clk_smu_i
        self.period_ps = round(self.cfg.smu_clk_period_ns * 1000)
        self.sites: list[dict] = []
        self.stamp_ps: dict[str, int] = {}
        self.accesses = 0
        self.done = False

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    async def _mark(self, step: str, text: str) -> None:
        await RisingEdge(self.clk)
        self.stamp_ps[step] = int(get_sim_time(unit="ps"))
        self._log(f"STEP {step} @{self.stamp_ps[step] / 1000:.3f}ns: {text}")

    async def _write(self, jtag, addr: int, data: int) -> None:
        self.accesses += 1
        await self._sb_ok(jtag, addr, SB_ACCESS_32, data)

    async def _read(self, jtag, addr: int) -> int:
        self.accesses += 1
        err, value = await self._sb(jtag, addr, SB_ACCESS_32)
        if err:
            raise AssertionError(f"system-bus read 0x{addr:08x}: sberror={err}")
        return value

    async def _write_token(self, jtag, addrs: list[int], token: int) -> None:
        for addr, word in zip(addrs, _words(token)):
            await self._write(jtag, addr, word)

    async def _poll(self, jtag, kind: str, label: str, addr: int) -> int:
        """Read the result register until it leaves idle; the site is recorded."""
        status = RESULT_IDLE
        used = 0
        while status == RESULT_IDLE and used < RESULT_POLLS:
            status = await self._read(jtag, addr) & STATUS_MASK
            used += 1
        expired = status == RESULT_IDLE
        self.sites.append(
            {
                "kind": kind,
                "label": label,
                "bound": RESULT_POLLS,
                "used": used,
                "last": f"0x{status:02x}",
                "expired": int(expired),
            }
        )
        if expired:
            raise AssertionError(
                f"TIMEOUT {kind} {label}: bound={RESULT_POLLS} used={used} "
                f"last_state=0x{status:02x}"
            )
        return status

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        await smu_dtp_sep_dm_dmi_test_seq.run(self)
        assert self.s1_ok and self.s2_ok and self.s3_ok, "SEP debug bring-up incomplete"
        jtag = self.jtag
        await self._mark(
            "S1", "bring-up with the RMA token image, debug module and system bus ready"
        )

        sense_done = sample(self.dut.sep_fuse_sense_done_o, "sep_fuse_sense_done_o")
        self._log(
            f"OBSERVATION sep_fuse_sense_done_o={sense_done} before the first token write; "
            "supplied by +skip_fuse_sense, logged only"
        )
        digest_first = await self._read(jtag, SIP_DIGEST_FIRST)
        digest_last = await self._read(jtag, SIP_DIGEST_LAST)
        self._log(
            f"OBSERVATION RMA_SIP_TOKEN_DIGEST first word=0x{digest_first:08x} last word="
            f"0x{digest_last:08x} image words=(0x{SIP_DIGEST_WORDS[0]:08x}, "
            f"0x{SIP_DIGEST_WORDS[7]:08x}); bench image values, logged only"
        )
        await self._mark("S2", f"sep_fuse_sense_done_o={sense_done} digest words read back")

        await self._write_token(jtag, SIP_TOKEN_WORDS, T_SIP)
        sip_idle = await self._read(jtag, SIP_MATCH) & STATUS_MASK
        await self._mark("S3", f"eight SIP words written, result before TOKEN_EOP 0x{sip_idle:02x}")

        await self._write(jtag, TOKEN_EOP, SIP_GO)
        chiplet_at_sip_start = await self._read(jtag, CHIPLET_MATCH) & STATUS_MASK
        sip_match = await self._poll(jtag, "sip_match", "RMA_SIP_TOKEN_MATCH", SIP_MATCH)
        await self._mark(
            "S4",
            f"SIP started, chiplet result at the start 0x{chiplet_at_sip_start:02x}, "
            f"SIP result 0x{sip_match:02x}",
        )

        chiplet_idle = await self._read(jtag, CHIPLET_MATCH) & STATUS_MASK
        await self._mark("S5", f"chiplet result while the SIP result holds 0x{chiplet_idle:02x}")

        await self._write_token(jtag, CHIPLET_TOKEN_WORDS, T_CHIP_ONE_BIT_OFF)
        await self._write(jtag, TOKEN_EOP, CHIPLET_GO)
        sip_at_chiplet_start = await self._read(jtag, SIP_MATCH) & STATUS_MASK
        chiplet_mismatch = await self._poll(
            jtag, "chiplet_mismatch", "RMA_CHIPLET_TOKEN_MATCH", CHIPLET_MATCH
        )
        await self._mark(
            "S6",
            f"chiplet token one bit off, SIP result at the start 0x{sip_at_chiplet_start:02x}, "
            f"chiplet result 0x{chiplet_mismatch:02x}",
        )

        await self._write_token(jtag, CHIPLET_TOKEN_WORDS, T_CHIP)
        await self._write(jtag, TOKEN_EOP, CHIPLET_GO)
        chiplet_match = await self._poll(
            jtag, "chiplet_match", "RMA_CHIPLET_TOKEN_MATCH", CHIPLET_MATCH
        )
        await self._mark("S7", f"chiplet token correct, result 0x{chiplet_match:02x}")

        sip_after = await self._read(jtag, SIP_MATCH) & STATUS_MASK
        await self._mark("S8", f"SIP result after the chiplet legs 0x{sip_after:02x}")

        fault = await self._read(jtag, MATCH_FAULT)
        self._log(f"OBSERVATION TOKEN_MATCH_FAULT=0x{fault:08x} measured and logged only")
        await self._mark("S9", "TOKEN_MATCH_FAULT read and logged")

        await ClockCycles(self.clk, STEP_CLOCK_GAP)
        self.stamp_ps["S10"] = int(get_sim_time(unit="ps"))
        self._log(f"STEP S10 @{self.stamp_ps['S10'] / 1000:.3f}ns: PASS stamp")
        self._log(f"system-bus accesses used={self.accesses}")

        self._check_idle(sb, sip_idle, chiplet_idle)
        self._check_start(sb, chiplet_at_sip_start, sip_at_chiplet_start)
        self._check_results(sb, sip_idle, sip_match, chiplet_idle, chiplet_mismatch, chiplet_match)
        self._check_indep(sb, sip_match, sip_after, chiplet_mismatch, chiplet_match)
        self._check_integrity(sb)
        self.done = True

    def _check_idle(self, sb, sip_idle, chiplet_idle) -> None:
        got = (sip_idle, chiplet_idle)
        want = (RESULT_IDLE, RESULT_IDLE)
        self._log(
            f"CHK-SEP-RMA-IDLE: SIP result with eight words written and no TOKEN_EOP="
            f"0x{got[0]:02x} expected=0x{want[0]:02x}; chiplet result while the SIP result "
            f"holds a result=0x{got[1]:02x} expected=0x{want[1]:02x}"
        )
        sb.expect_eq(
            "CHK-SEP-RMA-IDLE no result before TOKEN_EOP, no result on the lane not started",
            got,
            want,
            evidence="CHK-SEP-RMA-IDLE",
        )

    def _check_start(self, sb, chiplet_at_sip_start, sip_at_chiplet_start) -> None:
        got = (chiplet_at_sip_start, sip_at_chiplet_start)
        want = (RESULT_IDLE, RESULT_MATCH)
        self._log(
            f"CHK-SEP-RMA-START: chiplet result read right after TOKEN_EOP 0x1=0x{got[0]:02x} "
            f"expected=0x{want[0]:02x}; SIP result read right after TOKEN_EOP 0x100="
            f"0x{got[1]:02x} expected=0x{want[1]:02x}"
        )
        sb.expect_eq(
            "CHK-SEP-RMA-START each TOKEN_EOP bit leaves the other lane's result unchanged",
            got,
            want,
            evidence="CHK-SEP-RMA-START",
        )

    def _check_results(
        self, sb, sip_idle, sip_match, chiplet_idle, chiplet_mismatch, chiplet_match
    ) -> None:
        got = (sip_idle, sip_match)
        want = (RESULT_IDLE, RESULT_MATCH)
        self._log(
            f"CHK-SEP-RMA-SIP-MATCH: SIP result before/after TOKEN_EOP="
            f"{tuple(f'0x{v:02x}' for v in got)} expected={tuple(f'0x{v:02x}' for v in want)}"
        )
        sb.expect_eq(
            "CHK-SEP-RMA-SIP-MATCH the SIP token reads match",
            got,
            want,
            evidence="CHK-SEP-RMA-SIP-MATCH",
        )
        got = (chiplet_idle, chiplet_mismatch)
        want = (RESULT_IDLE, RESULT_MISMATCH)
        self._log(
            f"CHK-SEP-RMA-CHIP-MISMATCH: chiplet result before/after the one-bit-off token="
            f"{tuple(f'0x{v:02x}' for v in got)} expected={tuple(f'0x{v:02x}' for v in want)}"
        )
        sb.expect_eq(
            "CHK-SEP-RMA-CHIP-MISMATCH the one-bit-off chiplet token reads mismatch",
            got,
            want,
            evidence="CHK-SEP-RMA-CHIP-MISMATCH",
        )
        got = (chiplet_mismatch, chiplet_match)
        want = (RESULT_MISMATCH, RESULT_MATCH)
        self._log(
            f"CHK-SEP-RMA-CHIP-MATCH: chiplet result after the one-bit-off/correct token="
            f"{tuple(f'0x{v:02x}' for v in got)} expected={tuple(f'0x{v:02x}' for v in want)}"
        )
        sb.expect_eq(
            "CHK-SEP-RMA-CHIP-MATCH the correct chiplet token reads match after the mismatch",
            got,
            want,
            evidence="CHK-SEP-RMA-CHIP-MATCH",
        )

    def _check_indep(self, sb, sip_match, sip_after, chiplet_mismatch, chiplet_match) -> None:
        got = (sip_match, sip_after, chiplet_mismatch != chiplet_match)
        want = (RESULT_MATCH, RESULT_MATCH, True)
        self._log(
            f"CHK-SEP-RMA-INDEP: SIP result before/after the chiplet legs="
            f"{tuple(f'0x{v:02x}' for v in got[:2])} expected="
            f"{tuple(f'0x{v:02x}' for v in want[:2])}; chiplet result changed meanwhile={got[2]}"
        )
        sb.expect_eq(
            "CHK-SEP-RMA-INDEP the SIP result is unchanged by the chiplet legs",
            got,
            want,
            evidence="CHK-SEP-RMA-INDEP",
        )

    def _check_integrity(self, sb) -> None:
        for rec in self.sites:
            self._log(
                f"TIMEOUT-PATH {rec['kind']} {rec['label']}: bound={rec['bound']} "
                f"used={rec['used']} {'EXPIRED' if rec['expired'] else 'ok'} last={rec['last']}"
            )
        expired = sum(rec["expired"] for rec in self.sites)
        kinds = dict(Counter(rec["kind"] for rec in self.sites))
        self._log(
            f"CHK-TIMEOUT-PATHS: sites={len(self.sites)} expected={EXPECTED_SITES} kinds={kinds} "
            f"expired={expired}"
        )
        sb.expect_eq("expired TIMEOUT-PATH records", expired, 0, evidence="CHK-TIMEOUT-PATHS")
        sb.expect_eq(
            "bounded wait sites per kind",
            (len(self.sites), kinds),
            (EXPECTED_SITES, EXPECTED_SITE_KINDS),
            evidence="CHK-TIMEOUT-PATHS",
        )

        stamps = [self.stamp_ps[s] for s in STEPS]
        fence = "<".join(f"{s}@{t / 1000:.1f}" for s, t in zip(STEPS, stamps))
        pass_gap = round((stamps[-1] - stamps[-2]) / self.period_ps)
        self._log(f"CHK-NONVAC: ordered sim-time fence {fence} pass_gap_cycles={pass_gap}")
        sb.expect_eq(
            "CHK-NONVAC ordered sim-time fence, PASS stamp two cycles after S9",
            (all(b > a for a, b in zip(stamps, stamps[1:])), pass_gap),
            (True, STEP_CLOCK_GAP),
            evidence="CHK-NONVAC",
        )
