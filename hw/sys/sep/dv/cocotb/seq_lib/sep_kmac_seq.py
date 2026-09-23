# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OpenTitan KMAC run-control driver (direct AXI on the SEP CPU-LSU bus).

Runs one keyed KMAC-256 (cSHAKE, PREFIX="KMAC") over a message, with the key
either from the KM sideload port (CFG.sideload=1) or the public KEY_SHARE CSRs
(SW-key path, sideload=0) -- mirroring the reference sep_km_kmac_sideload_kat_test_seq
op helper (RAL there; direct AXI here, like SepAes/SepHmac). Masking is enabled
(EnMasking), so the digest is read as STATE share0 ^ share1. 32-bit beats (size=2).

KMAC register map (base from the generated SEP header; offsets from kmac.adoc):
  CFG_SHADOWED @ 0x014 (shadowed: written twice)   CMD @ 0x018   STATUS @ 0x01C
  KEY_SHARE0_0 @ 0x030 .. KEY_SHARE0_15 @ 0x06C    KEY_SHARE1_0 @ 0x070
  KEY_LEN @ 0x0B0   PREFIX_0 @ 0x0B4   ERR_CODE @ 0x0E0
  STATE share0 @ 0x400, share1 @ 0x500   MSG_FIFO window @ 0x800
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
from cocotb.triggers import ClockCycles
from env.sep_axi_agent import SepAxiOp

# Shared SP800-185 encoders so the DUT PREFIX / KMAC right_encode(L) bytes match
# the golden by construction.
from env.sep_kmac_golden import encode_string, right_encode
from sep_reg_meta import KMAC, sym

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver

KMAC_BASE = sym("KMAC_REG_MAP_BASE_ADDR")
KMAC_INTR_STATE = KMAC.addr("INTR_STATE")
KMAC_CFG_SHADOWED = KMAC.addr("CFG_SHADOWED")
KMAC_CMD = KMAC.addr("CMD")
KMAC_STATUS = KMAC.addr("STATUS")
KMAC_KEY_SHARE0_0 = sym("KMAC_KEY_SHARE0_0__REG_ADDR")
KMAC_KEY_SHARE1_0 = sym("KMAC_KEY_SHARE1_0__REG_ADDR")
KMAC_KEY_LEN = KMAC.addr("KEY_LEN")
KMAC_PREFIX_0 = sym("KMAC_PREFIX_0__REG_ADDR")
KMAC_ERR_CODE = KMAC.addr("ERR_CODE")
KMAC_STATE_S0 = sym("KMAC_STATE_MEM_BASE_ADDR")
KMAC_STATE_S1 = sym("KMAC_STATE_MEM_BASE_ADDR") + (sym("KMAC_STATE_MEM_SIZE") // 2)
KMAC_MSG_FIFO = sym("KMAC_MSG_FIFO_MEM_BASE_ADDR")

KMAC_NUM_PUBLIC_KEY = 16  # KEY_SHARE0_0..15 / KEY_SHARE1_0..15
KMAC_NUM_PREFIX = 11  # PREFIX_0..10
KMAC_KEY_WORDS = 8  # 256-bit key
KMAC_DIGEST_WORDS = 8  # 256-bit MAC

# CMD sparse encodings (kmac.adoc / OpenTitan CMD field).
KMAC_CMD_START = 0x1D
KMAC_CMD_PROCESS = 0x2E
KMAC_CMD_DONE = 0x16

# STATUS bits from the generated export, as the CFG path already does.
KMAC_STATUS_IDLE = KMAC.field_mask("STATUS", "sha3_idle")
KMAC_STATUS_SQUEEZE = KMAC.field_mask("STATUS", "sha3_squeeze")

# INTR_STATE bits (kmac.adoc: kmac_done[0], fifo_empty[1], kmac_err[2]).
# kmac_done fires on the absorbed event (SHA3 message fully absorbed -> squeeze
# ready) and is a RW1C status bit (write 1 to clear).
KMAC_INTR_KMAC_DONE = KMAC.field_mask("INTR_STATE", "kmac_done")
KMAC_INTR_KMAC_ERR = KMAC.field_mask("INTR_STATE", "kmac_err")

# PREFIX for KMAC mode: encode_string("KMAC"), S empty.
KMAC_PREFIX_WORD0 = 0x4D4B_2001
KMAC_PREFIX_WORD1 = 0x0000_4341

# right_encode(256) appended after the message -> spec-correct KMAC.
KMAC_RIGHT_ENCODE_256 = 0x0002_0001

# CFG_SHADOWED write map. kmac.adoc names mode[5:4] and kstrength[3:1];
# the RDL fields have no enum. These are the DV-owned programming values.
# Keyed KMAC is mode=cSHAKE with kmac_en=1: PREFIX is absorbed only in
# cSHAKE, so SHAKE+kmac_en is not the SP800-185 KMAC construction.
KMAC_MODE = {"sha3": 0, "shake": 2, "cshake": 3}
KMAC_STRENGTH = {128: 0, 224: 1, 256: 2, 384: 3, 512: 4}
KMAC_KEYLEN = {128: 0, 192: 1, 256: 2, 384: 3, 512: 4}
KMAC_KEY_LEN_256 = KMAC_KEYLEN[256]


def build_kmac_cfg(*, mode: int, kstrength: int, kmac_en: bool, sideload: bool = False) -> int:
    """CFG_SHADOWED word with EDN entropy (entropy_mode=EDN + entropy_ready), the
    masking-required config. Keyed KMAC-256 is mode=CShake: SW key 0x0101_0035,
    sideload 0x0101_1035."""
    return (
        int(bool(kmac_en))
        | (kstrength << KMAC.field_lsb("CFG_SHADOWED", "kstrength"))
        | (mode << KMAC.field_lsb("CFG_SHADOWED", "mode"))
        | (int(bool(sideload)) << KMAC.field_lsb("CFG_SHADOWED", "sideload"))
        | (0x1 << KMAC.field_lsb("CFG_SHADOWED", "entropy_mode"))
        | KMAC.field_mask("CFG_SHADOWED", "entropy_ready")
    )


@dataclass
class SepKmacCfg:
    """Single source of truth for one KMAC-engine cell: drives BOTH the DUT
    programming (CFG + KEY_LEN + PREFIX + key + message tail) AND the golden
    (env/sep_kmac_golden.kmac_family_words). ``mode`` in {sha3,shake,cshake,kmac};
    ``sec`` is the keccak strength (128/256/512); ``outlen_bytes`` the digest size."""

    mode: str
    sec: int
    msg_words: list[int]
    outlen_bytes: int
    key_words: list[int] | None = None  # KMAC only (len = key_bits/32)
    key_bits: int | None = None  # KMAC only (128/256)
    n: bytes = b""  # cSHAKE function-name (usually empty)
    s: bytes = b""  # cSHAKE/KMAC customization string

    @property
    def kmac_en(self) -> bool:
        return self.mode == "kmac"

    def mode_val(self) -> int:
        # KMAC is programmed as mode=cSHAKE + kmac_en=1 (kmac programmers_guide.md
        # §"Initialization": "configure CFG_SHADOWED.mode to cSHAKE"). This is the
        # spec-correct KMAC mode. Do not program mode=SHAKE for keyed KMAC.
        return KMAC_MODE["cshake" if self.mode == "kmac" else self.mode]

    def cfg_word(self, *, sideload: bool = False) -> int:
        return build_kmac_cfg(
            mode=self.mode_val(),
            kstrength=KMAC_STRENGTH[self.sec],
            kmac_en=self.kmac_en,
            sideload=sideload,
        )

    def prefix_bytes(self) -> bytes:
        """PREFIX = encode_string(N)||encode_string(S). KMAC forces N='KMAC';
        cSHAKE uses (N,S); SHA3/SHAKE have no prefix."""
        if self.mode == "kmac":
            return encode_string(b"KMAC") + encode_string(self.s)
        if self.mode == "cshake":
            return encode_string(self.n) + encode_string(self.s)
        return b""

    def golden_kwargs(self) -> dict:
        return dict(
            mode=self.mode,
            sec=self.sec,
            msg_words=self.msg_words,
            outlen_bytes=self.outlen_bytes,
            key_words=self.key_words,
            n=self.n,
            s=self.s,
        )


class SepKmac(SepAxiRegDriver):
    """Direct-AXI OpenTitan KMAC run control. The test owns one instance."""

    _DRIVER_TAG = "KMAC"

    async def read_public_key_shares(self) -> tuple[list[int], list[int], int]:
        """Read the public KEY_SHARE0/1 CSRs, plus a positive control.

        These key registers are declared write-only and the generated register
        block ties their read data to a constant '0. Reading them back as zero is
        therefore NOT evidence that the sideloaded key is unexposed -- they read
        zero whether the key is protected, mirrored elsewhere, or never delivered.
        (Directly demonstrated: a decoy value written to these addresses earlier in
        the run still reads back as zero here.) What the readback can do is catch
        the day they become readable.

        For that to be worth anything the read path must be known alive, so this
        also returns STATUS, a readable register in the same window over the same
        bus. A caller asserting the shares are zero must also assert the control
        read is non-zero; otherwise a dead read path returning zeros for everything
        would look identical to a pass.
        """
        s0 = [await self._rd(KMAC_KEY_SHARE0_0 + i * 4) for i in range(KMAC_NUM_PUBLIC_KEY)]
        s1 = [await self._rd(KMAC_KEY_SHARE1_0 + i * 4) for i in range(KMAC_NUM_PUBLIC_KEY)]
        control = await self._rd(KMAC_STATUS)
        return s0, s1, control

    async def keyed_mac(
        self, msg_words: list[int], *, sideload: bool, sw_key: list[int] | None = None
    ) -> list[int]:
        """Run one keyed KMAC-256 over msg_words; return the 8-word digest
        (STATE share0 ^ share1). sideload=1 uses the KM key; sideload=0 uses
        sw_key written to KEY_SHARE0 (KEY_SHARE1=0)."""
        # KEY_LEN must precede CmdStart (CFG_REGWEN locks after Start).
        await self._wr(KMAC_KEY_LEN, KMAC_KEY_LEN_256)
        # PREFIX: encode_string("KMAC"), remaining words zero.
        await self._wr(KMAC_PREFIX_0, KMAC_PREFIX_WORD0)
        await self._wr(KMAC_PREFIX_0 + 4, KMAC_PREFIX_WORD1)
        for i in range(2, KMAC_NUM_PREFIX):
            await self._wr(KMAC_PREFIX_0 + i * 4, 0)
        # SW key shares only matter when sideload=0.
        if not sideload:
            assert sw_key is not None and len(sw_key) == KMAC_KEY_WORDS, "sw_key needs 8 words"
            for i, word in enumerate(sw_key):
                await self._wr(KMAC_KEY_SHARE0_0 + i * 4, word & 0xFFFF_FFFF)
                await self._wr(KMAC_KEY_SHARE1_0 + i * 4, 0)
        # CFG_SHADOWED double-write. Keyed KMAC is mode=cSHAKE + kmac_en=1.
        cfg = build_kmac_cfg(
            mode=KMAC_MODE["cshake"],
            kstrength=KMAC_STRENGTH[256],
            kmac_en=True,
            sideload=sideload,
        )
        await self._wr(KMAC_CFG_SHADOWED, cfg)
        await self._wr(KMAC_CFG_SHADOWED, cfg)
        await self._wait_idle("pre-start")

        await self._wr(KMAC_CMD, KMAC_CMD_START)
        for word in msg_words:
            await self._wr(KMAC_MSG_FIFO, word & 0xFFFF_FFFF)
        await self._wr(KMAC_MSG_FIFO, KMAC_RIGHT_ENCODE_256)  # spec-correct KMAC
        await self._wr(KMAC_CMD, KMAC_CMD_PROCESS)
        await self._wait_squeeze()

        # Masking on -> digest = share0 ^ share1 (reading one share alone is a mask).
        digest = []
        for i in range(KMAC_DIGEST_WORDS):
            s0 = await self._rd(KMAC_STATE_S0 + i * 4)
            s1 = await self._rd(KMAC_STATE_S1 + i * 4)
            digest.append((s0 ^ s1) & 0xFFFF_FFFF)

        await self._wr(KMAC_CMD, KMAC_CMD_DONE)
        await self._wait_idle("post-done")
        return digest

    async def _write_prefix(self, prefix: bytes) -> None:
        """Program PREFIX_0..10 from encode_string(N)||encode_string(S) bytes (LE
        words); zero the unused registers (the encoded lengths self-delimit, so
        trailing zero-padding of the last word is ignored by the HW)."""
        words = [
            int.from_bytes(prefix[i : i + 4].ljust(4, b"\x00"), "little")
            for i in range(0, len(prefix), 4)
        ]
        for i in range(KMAC_NUM_PREFIX):
            await self._wr(KMAC_PREFIX_0 + i * 4, words[i] if i < len(words) else 0)

    async def _push_msg_bytes(self, data: bytes) -> None:
        """Absorb an exact byte string into MSG_FIFO: full 32-bit words, then a
        byte-accurate partial final beat (wstrb) so the message length is exact
        (needed for the KMAC right_encode(L) 3-byte tail, else a stray zero byte
        would corrupt the digest vs the golden)."""
        off = 0
        while off + 4 <= len(data):
            await self._wr(KMAC_MSG_FIFO, int.from_bytes(data[off : off + 4], "little"))
            off += 4
        rem = len(data) - off
        if rem:
            val = int.from_bytes(data[off : off + rem], "little")
            seq = SepAxiAccessSeq(
                f"{self._DRIVER_TAG.lower()}_wr_partial",
                op=SepAxiOp.WRITE,
                addr=KMAC_MSG_FIFO,
                wdata=val,
                length=rem,
                size=self._AXI_SIZE,
            )
            await self.test.start_seq(seq)
            if not seq.resp_ok:
                raise AssertionError(f"KMAC partial MSG_FIFO write ({rem}B) not OKAY")

    async def run_family(
        self, cfg: "SepKmacCfg", *, tag: str = "", hold: bool = False
    ) -> list[int]:
        """Run one KMAC-family op (sha3/shake/cshake/kmac SW-key) per ``cfg``;
        return the digest words (STATE share0 ^ share1, masking on). Proves the
        INTR_STATE.kmac_done RW1C contract (observed set -> W1C -> reads 0) before
        CmdDone."""
        if cfg.kmac_en:
            await self._wr(KMAC_KEY_LEN, KMAC_KEYLEN[cfg.key_bits])
        await self._write_prefix(cfg.prefix_bytes())
        if cfg.kmac_en:
            assert cfg.key_words is not None, "kmac needs sw key_words"
            for i, word in enumerate(cfg.key_words):
                await self._wr(KMAC_KEY_SHARE0_0 + i * 4, word & 0xFFFF_FFFF)
                await self._wr(KMAC_KEY_SHARE1_0 + i * 4, 0)
        cfg_word = cfg.cfg_word()
        await self._wr(KMAC_CFG_SHADOWED, cfg_word)
        await self._wr(KMAC_CFG_SHADOWED, cfg_word)
        await self._wait_idle("pre-start")

        await self._wr(KMAC_CMD, KMAC_CMD_START)
        msg = b"".join((w & 0xFFFF_FFFF).to_bytes(4, "little") for w in cfg.msg_words)
        if cfg.kmac_en:
            msg += right_encode(cfg.outlen_bytes * 8)  # spec-correct KMAC tail
        await self._push_msg_bytes(msg)
        await self._wr(KMAC_CMD, KMAC_CMD_PROCESS)
        await self._wait_squeeze()

        nwords = (cfg.outlen_bytes + 3) // 4
        digest = []
        for i in range(nwords):
            s0 = await self._rd(KMAC_STATE_S0 + i * 4)
            s1 = await self._rd(KMAC_STATE_S1 + i * 4)
            digest.append((s0 ^ s1) & 0xFFFF_FFFF)
        await self._check_done_rw1c(tag)
        if hold:
            # Leave STATE in squeeze so a later re-read is the held result.
            return digest
        await self._wr(KMAC_CMD, KMAC_CMD_DONE)
        await self._wait_idle("post-done")
        return digest

    async def read_digest(self, nwords: int = KMAC_DIGEST_WORDS) -> list[int]:
        """Re-read STATE share0^share1. Valid while the engine is still in squeeze
        (after run_family(..., hold=True)); a domain reset perturbs it."""
        digest = []
        for i in range(nwords):
            s0 = await self._rd(KMAC_STATE_S0 + i * 4)
            s1 = await self._rd(KMAC_STATE_S1 + i * 4)
            digest.append((s0 ^ s1) & 0xFFFF_FFFF)
        return digest

    async def read_status(self) -> int:
        """Read STATUS (sha3_idle[0], sha3_squeeze[2], fifo_empty, ...)."""
        return await self._rd(KMAC_STATUS)

    async def _check_done_rw1c(self, tag: str) -> None:
        """CHK-DONE-RW1C: after the message is absorbed (squeeze ready) the
        INTR_STATE.kmac_done status bit must be set; write 1 to clear it and prove
        it reads back 0. kmac_done is a sticky RW1C status bit (kmac.sv
        prim_intr_hw), independent of INTR_ENABLE, so it latches even though the
        no_cpu path leaves the PIC unreached."""
        pre = await self._rd(KMAC_INTR_STATE)
        assert pre & KMAC_INTR_KMAC_DONE, (
            f"KMAC INTR_STATE.kmac_done not set after absorb [{tag}] (0x{pre:08x})"
        )
        await self._wr(KMAC_INTR_STATE, KMAC_INTR_KMAC_DONE)
        post = await self._rd(KMAC_INTR_STATE)
        assert (post & KMAC_INTR_KMAC_DONE) == 0, (
            f"KMAC INTR_STATE.kmac_done not cleared by W1C [{tag}] (0x{post:08x})"
        )
        self.log.info(
            "CHK-DONE-RW1C PASS [%s]: INTR_STATE.kmac_done set (0x%08x) -> W1C -> reads 0 (0x%08x)",
            tag,
            pre,
            post,
        )

    async def wait_idle(self, tag: str, *, timeout: int = 4_000, poll_cycles: int = 20) -> None:
        """Poll STATUS until sha3_idle. Public form of the internal wait, for a
        caller that must know the core is accepting after a reset release."""
        await self._wait_idle(tag, timeout=timeout, poll_cycles=poll_cycles)

    async def _wait_idle(self, tag: str, *, timeout: int = 4_000, poll_cycles: int = 20) -> None:
        await self._poll(KMAC_STATUS_IDLE, f"idle/{tag}", timeout=timeout, poll_cycles=poll_cycles)

    async def _wait_squeeze(self, *, timeout: int = 4_000, poll_cycles: int = 20) -> None:
        await self._poll(KMAC_STATUS_SQUEEZE, "squeeze", timeout=timeout, poll_cycles=poll_cycles)

    async def _poll(self, mask: int, tag: str, *, timeout: int, poll_cycles: int) -> None:
        for i in range(timeout):
            if await self._rd(KMAC_STATUS) & mask:
                return
            if i and i % 500 == 0:
                self.log.info("KMAC wait %s: poll %d", tag, i)
            await ClockCycles(cocotb.top.clk_i, poll_cycles)
        raise AssertionError(f"KMAC {tag} timeout")

    async def check_status_clean(self, tag: str = "EOT") -> None:
        """Assert KMAC raised no error: ERR_CODE == 0 and INTR_STATE.kmac_err == 0."""
        err = await self._rd(KMAC_ERR_CODE)
        assert err == 0, f"KMAC ERR_CODE=0x{err:08x} [{tag}]"
        intr = await self._rd(KMAC_INTR_STATE)
        assert (intr & KMAC_INTR_KMAC_ERR) == 0, (
            f"KMAC INTR_STATE.kmac_err set [{tag}] (0x{intr:08x})"
        )
        self.log.info(
            "CHK-ERR PASS [%s]: ERR_CODE=0, INTR_STATE.kmac_err=0",
            tag,
        )
