# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AES and KMAC contend at the crypto-EDN arbiter, and both compute correctly on routed DRBG words.

OCAH provenance: ``sep_drbg_real_sink_multi_rand_test`` checks simultaneous
delivery to multiple real entropy sinks.

AES (crypto_edn[0]) and KMAC (crypto_edn[1]) both pull
the shared crypto-EDN leg (drbg_axis_edn_adapter -> u_axis_edn_crypto_s3c_scan round-robin
arbiter, sep_crypto.sv) concurrently off ONE verified DRBG stream: TWO real
crypto clients contend the crypto arbiter.
`sep_drbg_real_sink_multi_km_aes_test` has AES as the sole crypto client (KMAC parked)
and uses KM (a different leg) as the second sink; the standalone AES/KMAC breadth
tests are single-engine KATs. DISTINCT from all of those -- do NOT re-prove
single-sink routing here.

The two sinks are crypto engines that share one EDN adapter at the crypto-endpoint
arbiter. No KM firmware / no
rom_main / no real fuse-sense (+skip_fuse_sense), so it follows the standalone
crypto-engine bring-up style.

CHK5 ROUTING: each AES and each KMAC post-adapter beat equals the AXIS1 word
the adapter granted that cycle. Membership of those words in the CHK4 genbits
set follows because AXIS1 is chained to genbits in report().

Budget: total genbits consumption is kept < cfg.glen=32 blocks so the CHK4
one-Generate-per-seed golden stays bit-exact (do not overrun glen). No KM boot
here, so the full 32-block budget is available for AES+KMAC; a few ops each is far
under it.

Checkers:
  CHK1..CHK4     bit-exact golden (decor/compress/seed/CTR_DRBG genbits) -- strict;
                 the correctness anchor the AXIS1 routing stream draws from.
  CHK-SINK-BIND  AES alone scores AES-named beats and the KMAC sink takes zero
                 beats, so the sink map is bound independently of adapter order.
  CHK-NONVAC     single-engine baseline: AES-alone ct == AES-256-ECB golden, and the
                 KMAC sink takes zero beats while idle (proves the both-beats check
                 is not always-true).
  CHK-BOTH-COMPLETE  under contention: every contended AES block == golden and every
                 KMAC digest == golden (both engines compute correctly while sharing
                 the arbiter).
  CHK-BOTH-BEATS every engaged crypto sink (AES, KMAC) takes real post-adapter EDN
                 beats DURING the concurrent fork (per-sink beat delta > 0).
  CHK-OVERLAP    positive arbiter-CONTENTION proof: AES's and KMAC's crypto-EDN beat
                 TIME-SPANS overlap during the fork (each was being granted words by
                 u_axis_edn_crypto_s3c_scan in an overlapping window), so neither sink
                 drained fully before the other started. This is interval-span
                 containment, not per-cycle interleaving: it does not prove the two
                 clients were granted on alternating cycles.
  CHK-ROUTING    each AES beat and each KMAC beat equals the AXIS1 word granted
                 that cycle (dual-sink bit-exact CHK5).
  CHK-MEMBERSHIP each routed word is a CHK4 genbits-golden word (AXIS1 chain).

Four-engine concurrency leg (runs after CHK-MEMBERSHIP, on the same entropy stack):
three groups per seed -- HMAC+AES+KMAC+OTBN, AES+KMAC+OTBN, and one drawn pair that
is not AES+KMAC. Each member runs alone first (CTRL-CONC-CLEAN, golden compare and
clean busy time t_op), then all members of the group run as concurrent tasks on the
CPU-LSU master with distinct non-zero AXI IDs and drawn start skews. In a group
without an HMAC member, HMAC holds a finished SHA-256 digest (the bystander) and a
further task reads its DIGEST words while the peers run. The EDN words acked on
crypto_edn_ack_o[3:0] are counted from the first word of the run against the
generate budget of the open boot Generate (CTRL-CONC-BUDGET).
  CHK-CONC-RESULT  each member result under overlap equals its independent golden
                   (SHA-2/HMAC, Keccak, AES, Python operator) and every host access
                   of the member answers OKAY; control: CTRL-CONC-CLEAN of the same
                   member and CTRL-CONC-OVERLAP > 0 for every pair of the group.
  CHK-CONC-HOLD    every bystander DIGEST read equals the bystander golden; control:
                   at least one read completes while a peer is busy.
The specification implies the independence of the engines (separate host paths,
hw/sys/sep/doc/crypto.adoc; per-domain resets, hw/sys/sep/doc/reset_controller.adoc)
and states no direct rule, so both checks grade the implied contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from itertools import combinations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, Event, RisingEdge
from env.sep_aes_golden import aes256_ecb_encrypt_words, aes_encrypt_words
from env.sep_axi_agent import SepAxiOp
from env.sep_bit_watch import SepBitWatch
from env.sep_chk_log import SepChkLog
from env.sep_crypto_kat_rows import (
    FIPS197_C1_KEY,
    FIPS197_C3_KEY,
    RFC4231_KEYS,
    SP800_38A_AES128_KEY,
    SP800_38A_AES256_KEY,
    SP800_38A_CBC_IV,
    SP800_38A_CTR_COUNTER,
)
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_hmac_golden import hmac_sha2_bytes, sha2_bytes
from env.sep_kmac_golden import kmac_family_words, sha3, shake
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from seq_lib.sep_aes_seq import (
    AES_CTRL_SHADOWED,
    AES_DATA_IN_0,
    AES_KEYLEN_CTRL,
    AES_MODE_CTRL,
    AES_STATUS,
    AES_STATUS_IDLE,
    AES_STATUS_INPUT_READY,
    AES_STATUS_OUTPUT_VALID,
    SepAes,
)
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_hmac_seq import (
    HMAC_CFG,
    HMAC_CMD,
    HMAC_CMD_HASH_PROCESS,
    HMAC_CMD_HASH_START,
    HMAC_DIGEST_0,
    HMAC_ILLEGAL_KEYED,
    HMAC_INTR_DONE,
    HMAC_INTR_STATE,
    HMAC_KEY_LENGTH,
    HMAC_MSG_FIFO,
    HMAC_STATUS,
    SepHmac,
    build_cfg,
)
from seq_lib.sep_kmac_seq import (
    KMAC_CFG_SHADOWED,
    KMAC_CMD,
    KMAC_CMD_DONE,
    KMAC_CMD_PROCESS,
    KMAC_CMD_START,
    KMAC_MODE,
    KMAC_MSG_FIFO,
    KMAC_STATE_S0,
    KMAC_STATE_S1,
    KMAC_STATUS,
    KMAC_STATUS_IDLE,
    KMAC_STATUS_SQUEEZE,
    KMAC_STRENGTH,
    SepKmac,
    SepKmacCfg,
    build_kmac_cfg,
)
from seq_lib.sep_otbn_compute_seq import (
    OPS as OTBN_OPS,
)
from seq_lib.sep_otbn_compute_seq import (
    SepOtbnComputeCfg,
    golden_result,
    otbn_compute_prog,
)
from seq_lib.sep_otbn_seq import (
    OTBN_ADDR_CMD,
    OTBN_ADDR_STATUS,
    OTBN_CMD_EXECUTE,
    OTBN_STATUS_IDLE,
    SepOtbn,
)
from seq_lib.sep_sw_reset_seq import SW_RESET_N_BIT, SepSwReset

# AES SW-key path: arbitrary key (the test exercises the entropy datapath + the
# arbiter, not a key contract -- same as `sep_drbg_real_sink_multi_km_aes_test`).
# Plaintext is seed-randomized.
AES_KEY = (
    0x0F0E0D0C,
    0x0B0A0908,
    0x07060504,
    0x03020100,
    0x1F1E1D1C,
    0x1B1A1918,
    0x17161514,
    0x13121110,
)
# KMAC-256 keyed cell: arbitrary 256-bit key + customization; message seed-randomized.
KMAC_KEY = (
    0x03020100,
    0x07060504,
    0x0B0A0908,
    0x0F0E0D0C,
    0x13121110,
    0x17161514,
    0x1B1A1918,
    0x1F1E1D1C,
)
KMAC_S = b"crypto EDN arbiter"

# Concurrent-window op counts. Kept small so AES+KMAC consumption stays well under
# one CSRNG Generate (cfg.glen=32 genbits blocks) -- else the bit-exact CHK4 golden
# (one Generate per seed) desyncs. No KM boot here, so the whole 32-block budget is
# for these ops.
AES_BLOCKS_FORK = 2
KMAC_OPS_FORK = 2


@dataclass
class CryptoEdnMultisinkCfg:
    """Single source for the crypto-EDN multisink arbitration seeded payload policy.

    Key material is fixed -- the test exercises the entropy datapath and the
    crypto-EDN arbiter, not a key contract -- while the seed randomizes the AES
    plaintext and the KMAC message shape/content. All resolved values are logged
    so any seeded failure is reproducible. The fork op counts are pinned and
    budget-bounded to keep total genbits consumption under one CSRNG Generate.
    """

    seed: int
    aes_key: tuple = AES_KEY
    kmac_key: tuple = KMAC_KEY
    kmac_s: bytes = KMAC_S
    aes_blocks_fork: int = AES_BLOCKS_FORK
    kmac_ops_fork: int = KMAC_OPS_FORK
    aes_pt: list = field(default_factory=list)  # resolved from seed
    kmac_msg: list = field(default_factory=list)  # resolved from seed

    @classmethod
    def randomize(cls, seed: int) -> "CryptoEdnMultisinkCfg":
        """Resolve the seeded fields from `seed` (single RNG = reproducible)."""
        rng = SepSeededRng(seed)
        return cls(
            seed=seed,
            aes_pt=[rng.getrandbits(32) for _ in range(4)],
            kmac_msg=[rng.getrandbits(32) for _ in range(rng.randrange(2, 7))],
        )

    def log_resolved(self, logger) -> None:
        """Log every resolved value so a seeded failure is reproducible."""
        logger.info(
            "crypto-EDN multisink arbitration RANDCFG resolved (seed=%d):",
            self.seed,
        )
        logger.info("  aes_pt   = %s", [hex(w) for w in self.aes_pt])
        logger.info(
            "  kmac_msg = %s (%d words)", [hex(w) for w in self.kmac_msg], len(self.kmac_msg)
        )
        logger.info("  aes_key/kmac_key = <fixed 256b>  kmac_s = %r", self.kmac_s)
        logger.info(
            "  aes_blocks_fork=%d  kmac_ops_fork=%d (pinned, budget-bounded)",
            self.aes_blocks_fork,
            self.kmac_ops_fork,
        )


# --- Four-engine concurrency leg: tables, plan, drivers ----------------------

_TEST_NAME = "sep_crypto_edn_multisink_arbitration_test"

# Generate budget of the leg, in 32-bit EDN words. The open test writes no
# EDN.BOOT_GEN_CMD, so EDN issues the boot Generate with the reset word 0xFFF003
# (vendor/lowRISC/opentitan/overlay/regs/edn/regs/gen/adoc/edn.adoc, BOOT_GEN_CMD):
# GLEN 0xFFF blocks of 128 bits = 16380 words. Half of it is the budget; the other
# half covers the words the endpoint FIFOs of the other clients buffer.
_EDN_BUDGET_WORDS = 8190

# crypto_edn_*_o client index per engine: 0 AES, 1 KMAC, 2 OTBN RND, 3 OTBN URND.
_EDN_CLIENTS = {"aes": (0,), "kmac": (1,), "otbn": (2, 3), "hmac": ()}
_ENGINES = ("hmac", "aes", "kmac", "otbn")
# Configuration order of a group run: KMAC last, because its entropy_ready write
# starts its EDN seeding.
_CFG_ORDER = ("hmac", "aes", "otbn", "kmac")
_PAIRS = (("hmac", "aes"), ("hmac", "kmac"), ("hmac", "otbn"), ("aes", "otbn"), ("kmac", "otbn"))
# Non-zero AXI ID per task on the CPU-LSU master.
_AXI_ID = {"hmac": 1, "aes": 2, "kmac": 3, "otbn": 4, "bystander": 5}
_SW_RESET_BASELINE = 0x7E
# Clocks between two polls of a task, and between two bystander reads (the
# read interval I that the leaf chooses and logs).
_POLL_GAP_CLK = 8
_BYSTANDER_GAP_CLK = 8
# Outer limits of the bring-up and reset waits. They bound a wait; they are
# not a contract.
_RESET_WAIT_CLK = 4_000
_REQ_LOW_WAIT_CLK = 20_000
_BYSTANDER_DONE_CLK = 40_000
_CLEAN_RUN_CLK = 400_000
# Domain tag that separates the leg stream from the stream of the open test.
# A tag, not a credential.
_LEG_RNG_TAG = 0xC0_7C_26

# HMAC test keys: RFC 4231 test cases 1 to 5, zero-padded to the 128 bytes of
# KEY_0..KEY_31. AES keys: FIPS 197 Appendix C.1 / C.3 and SP 800-38A AES-128 / AES-256
# keys. AES IVs: the SP 800-38A F.2.1 IV and F.5.1 initial counter block. All rows are in
# env/sep_crypto_kat_rows.py. The seed picks the row, never the bytes.
_HMAC_KEY_ROWS = RFC4231_KEYS[:5]
_AES_KEY_ROWS = {
    128: (FIPS197_C1_KEY, SP800_38A_AES128_KEY),
    256: (FIPS197_C3_KEY, SP800_38A_AES256_KEY),
}
_AES_IV_ROWS = (SP800_38A_CBC_IV, SP800_38A_CTR_COUNTER)


def _le_words(data: bytes) -> list[int]:
    """Register words of a byte string, little-endian per 32-bit word (AES/KMAC)."""
    return [int.from_bytes(data[i : i + 4], "little") for i in range(0, len(data), 4)]


def _unique_words(rng: SepSeededRng, n: int) -> list[int]:
    """n test-data words, unique and non-zero (different from the reset value)."""
    out: list[int] = []
    seen: set[int] = set()
    while len(out) < n:
        w = rng.getrandbits(32)
        if w and w not in seen:
            seen.add(w)
            out.append(w)
    return out


def _unique_bytes(rng: SepSeededRng, nbytes: int) -> bytes:
    words = _unique_words(rng, (nbytes + 3) // 4)
    return b"".join(w.to_bytes(4, "little") for w in words)[:nbytes]


def _hmac_key_words(row: int) -> list[int]:
    """KEY_0..KEY_31 of a row. hmac.hjson KEY multireg: key[1023:0] = {KEY0, ..,
    KEY31}, so KEY_0 is the most-significant word, big-endian per word."""
    key = _HMAC_KEY_ROWS[row].ljust(128, b"\x00")
    return [int.from_bytes(key[i : i + 4], "big") for i in range(0, 128, 4)]


def _digest_words_be(digest: bytes) -> list[int]:
    """DIGEST words at digest_swap = 0: DIGEST_0 holds the first 4 digest bytes."""
    return [int.from_bytes(digest[i : i + 4], "big") for i in range(0, len(digest), 4)]


@dataclass(frozen=True)
class HmacOp:
    sha_bits: int
    key_bits: int
    key_row: int
    msg: bytes
    min_len: int = 64

    eng = "hmac"

    def golden(self) -> list[int]:
        key = _HMAC_KEY_ROWS[self.key_row].ljust(128, b"\x00")[: self.key_bits // 8]
        return _digest_words_be(hmac_sha2_bytes(key, self.msg, self.sha_bits))

    def count(self) -> int:
        return len(self.msg)

    def halved(self) -> "HmacOp":
        return replace(self, msg=self.msg[: max(self.min_len, len(self.msg) // 2)])

    def desc(self) -> str:
        return (
            f"hmac(sha={self.sha_bits},klen={self.key_bits},row={self.key_row},len={len(self.msg)})"
        )


@dataclass(frozen=True)
class AesOp:
    mode: str
    key_bits: int
    key_row: int
    iv_row: int
    pt: tuple[int, ...]
    min_blocks: int = 4

    eng = "aes"

    def key_words(self) -> list[int]:
        return _le_words(_AES_KEY_ROWS[self.key_bits][self.key_row])

    def iv_words(self) -> list[int] | None:
        return _le_words(_AES_IV_ROWS[self.iv_row]) if self.mode == "cbc" else None

    def golden(self) -> list[int]:
        return aes_encrypt_words(self.mode, self.key_words(), list(self.pt), self.iv_words())

    def count(self) -> int:
        return len(self.pt) // 4

    def halved(self) -> "AesOp":
        return replace(self, pt=self.pt[: 4 * max(self.min_blocks, self.count() // 2)])

    def desc(self) -> str:
        return (
            f"aes(mode={self.mode},klen={self.key_bits},row={self.key_row},"
            f"iv_row={self.iv_row},blocks={self.count()})"
        )


@dataclass(frozen=True)
class KmacOp:
    mode: str  # "sha3" (SHA3-256) or "shake" (SHAKE-128)
    msg: bytes
    out_bytes: int = 32

    eng = "kmac"

    @property
    def sec(self) -> int:
        return 256 if self.mode == "sha3" else 128

    def golden(self) -> list[int]:
        out = sha3(self.msg, 256) if self.mode == "sha3" else shake(self.msg, 128, self.out_bytes)
        return _le_words(out[: self.out_bytes])

    def count(self) -> int:
        return len(self.msg)

    def halved(self) -> "KmacOp":
        return replace(self, msg=self.msg[: len(self.msg) // 2])

    def desc(self) -> str:
        return f"kmac(mode={self.mode},len={len(self.msg)})"


@dataclass(frozen=True)
class OtbnOp:
    op: str
    a: int
    b: int

    eng = "otbn"

    def golden(self) -> list[int]:
        return [golden_result(self.op, self.a, self.b)]

    def count(self) -> int:
        return 0

    def halved(self) -> "OtbnOp":
        return self

    def desc(self) -> str:
        return f"otbn(op={self.op},a=0x{self.a:08x},b=0x{self.b:08x})"


@dataclass
class LegGroup:
    name: str
    members: tuple[str, ...]
    order: list[str]  # drawn start order
    ops: dict  # engine -> op
    bystander_msg: bytes | None  # 64-byte message when HMAC is not a member

    @property
    def has_bystander(self) -> bool:
        return self.bystander_msg is not None


def _draw_op(rng: SepSeededRng, eng: str):
    if eng == "hmac":
        sha_bits = rng.choice((256, 512))
        msg_len = rng.randrange(64, 513)
        key_row = rng.randrange(len(_HMAC_KEY_ROWS))
        legal = [k for k in HMAC_KEY_LENGTH if (sha_bits, k) not in HMAC_ILLEGAL_KEYED]
        key_bits = rng.choice(legal)
        return HmacOp(sha_bits, key_bits, key_row, _unique_bytes(rng, msg_len))
    if eng == "aes":
        mode = rng.choice(("ecb", "cbc"))
        key_bits = rng.choice((128, 256))
        blocks = rng.randrange(4, 65)
        key_row = rng.randrange(len(_AES_KEY_ROWS[key_bits]))
        iv_row = rng.randrange(len(_AES_IV_ROWS))
        return AesOp(mode, key_bits, key_row, iv_row, tuple(_unique_words(rng, 4 * blocks)))
    if eng == "kmac":
        mode = rng.choice(("sha3", "shake"))
        return KmacOp(mode, _unique_bytes(rng, rng.randrange(0, 301)))
    if eng == "otbn":
        op = rng.choice(OTBN_OPS)
        operands = SepOtbnComputeCfg.from_seed(rng.getrandbits(32))
        return OtbnOp(op, operands.a, operands.b)
    raise ValueError(eng)


def _draw_bystander_msg(rng: SepSeededRng) -> bytes:
    """A 64-byte message whose SHA-256 digest has no zero word, so a cleared or
    reset DIGEST register cannot match the bystander golden."""
    while True:
        msg = _unique_bytes(rng, 64)
        if all(_digest_words_be(sha2_bytes(msg, 256))):
            return msg


def draw_plan(seed: int) -> tuple[list[LegGroup], SepSeededRng]:
    """The leg plan, a pure function of the seed (no simulator access).

    Returns the three groups and the generator, whose stream continues with the
    start skews. A skew depends on the clean busy times of its group, so the leaf
    draws the skews from the same generator after the clean runs of that group.
    """
    rng = SepSeededRng(seed ^ _LEG_RNG_TAG)
    pair = rng.choice(_PAIRS)
    groups: list[LegGroup] = []
    for name, members in (
        ("G4", ("hmac", "aes", "kmac", "otbn")),
        ("G3", ("aes", "kmac", "otbn")),
        ("P", pair),
    ):
        order = list(members)
        rng.shuffle(order)
        ops = {eng: _draw_op(rng, eng) for eng in members}
        bystander = None if "hmac" in members else _draw_bystander_msg(rng)
        groups.append(LegGroup(name, tuple(members), order, ops, bystander))
    return groups, rng


class _LegAccess:
    """CPU-LSU register access with a fixed non-zero AXI ID.

    Overrides the access pair of ``SepAxiRegDriver``. While ``record`` is a list,
    every access is appended as ``(op, addr, ok)`` and a non-OKAY response
    returns instead of raising, so the group check reports it in its own line.
    Outside a group run a non-OKAY response raises, as the base driver does.
    """

    def __init__(self, test, *, axi_id: int, clk) -> None:
        super().__init__(test)
        self.axi_id = axi_id
        self.clk = clk
        self.record: list[tuple[str, int, bool]] | None = None
        self.last_resp_clk = 0

    async def _access(self, op: SepAxiOp, addr: int, data: int, size, length: int) -> int:
        seq = SepAxiAccessSeq(
            f"{self._DRIVER_TAG.lower()}_id{self.axi_id}",
            op=op,
            addr=addr,
            wdata=data,
            length=length,
            size=size,
            axi_id=self.axi_id,
        )
        await self.test.start_seq(seq)
        self.last_resp_clk = self.clk()
        if self.record is not None:
            self.record.append((op.value, addr, bool(seq.resp_ok)))
        elif not seq.resp_ok:
            raise AssertionError(f"{self._DRIVER_TAG} {op.value} @0x{addr:08x} not OKAY")
        return seq.rdata

    async def _write_access(self, addr: int, data: int, *, size, length: int) -> None:
        await self._access(SepAxiOp.WRITE, addr, data, size, length)

    async def _read_access(self, addr: int, *, size, length: int) -> int:
        return await self._access(SepAxiOp.READ, addr, 0, size, length)

    async def try_read(self, addr: int) -> bool:
        """One read that tolerates a non-OKAY or missing response; True when OKAY.
        Used only to find the first OKAY readback after a reset release."""
        seq = SepAxiAccessSeq(
            f"{self._DRIVER_TAG.lower()}_ready",
            op=SepAxiOp.READ,
            addr=addr,
            length=4,
            size=self._AXI_SIZE,
            axi_id=self.axi_id,
            allow_ungraded_read_resp=True,
            allow_timeout=True,
        )
        await self.test.start_seq(seq)
        return bool(seq.resp_ok) and not seq.timed_out

    async def write_bytes(self, addr: int, data: bytes) -> None:
        """Full 32-bit beats, then one partial beat with the byte strobes of the tail."""
        off = 0
        while off + 4 <= len(data):
            await self._wr(addr, int.from_bytes(data[off : off + 4], "little"))
            off += 4
        if off < len(data):
            rem = data[off:]
            await self._write_access(
                addr, int.from_bytes(rem, "little"), size=self._AXI_SIZE, length=len(rem)
            )


@dataclass
class _TaskResult:
    """One member task of a group run (clocks are counts of the ack watcher)."""

    start_clk: int = -1
    busy_end_clk: int = -1
    result: list[int] = field(default_factory=list)
    timeout: bool = False
    err_bits: int = 0

    @property
    def busy_clk(self) -> int:
        return max(0, self.busy_end_clk - self.start_clk)


class _LegMember:
    """Configure and run of one engine; ``run`` returns a ``_TaskResult``.

    ``bound`` is the clock limit of the run, counted from the start write
    response. The busy window ends at the last status read that shows busy, or
    at the last write of the operation when that write is later (the engine is
    busy while it takes the message), so a short operation still has a window.
    """

    status_addr = 0

    async def _poll(self, res: _TaskResult, bound: int, done) -> int | None:
        """Read the status register until ``done(value)``; None on timeout."""
        while True:
            value = await self._rd(self.status_addr)
            if done(value):
                return value
            res.busy_end_clk = max(res.busy_end_clk, self.last_resp_clk)
            if self.clk() - res.start_clk > bound:
                res.timeout = True
                return None
            await ClockCycles(cocotb.top.clk_i, _POLL_GAP_CLK)


class LegHmac(_LegAccess, SepHmac, _LegMember):
    status_addr = HMAC_INTR_STATE

    async def configure_op(self, op: HmacOp) -> int:
        cfg = build_cfg(hmac_en=True, sha_bits=op.sha_bits, key_bits=op.key_bits)
        await self._wr(HMAC_CFG, cfg)
        await self.write_key(_hmac_key_words(op.key_row))
        return await self._rd(HMAC_CFG)

    async def run_op(self, op: HmacOp, bound: int, on_start) -> _TaskResult:
        res = _TaskResult()
        await self._wr(HMAC_CMD, HMAC_CMD_HASH_START)
        res.start_clk = res.busy_end_clk = self.last_resp_clk
        on_start(res.start_clk)
        await self.write_bytes(HMAC_MSG_FIFO, op.msg)
        await self._wr(HMAC_CMD, HMAC_CMD_HASH_PROCESS)
        res.busy_end_clk = self.last_resp_clk
        # hmac.hjson INTR_STATE.hmac_done: HMAC/SHA-2 has completed. A read with
        # hmac_done = 0 shows busy.
        if await self._poll(res, bound, lambda v: v & HMAC_INTR_DONE) is None:
            return res
        n = len(op.golden())
        res.result = [await self._rd(HMAC_DIGEST_0 + i * 4) for i in range(n)]
        await self._wr(HMAC_INTR_STATE, HMAC_INTR_DONE)
        return res


class LegAes(_LegAccess, SepAes, _LegMember):
    status_addr = AES_STATUS

    async def configure_op(self, op: AesOp) -> int:
        await self.configure(mode=AES_MODE_CTRL[op.mode], key_len=AES_KEYLEN_CTRL[op.key_bits])
        # load_key_iv: KEY words, a bounded wait for STATUS.IDLE, then the IV.
        await self.load_key_iv(op.key_words(), op.iv_words())
        return await self._rd(AES_CTRL_SHADOWED)

    async def run_op(self, op: AesOp, bound: int, on_start) -> _TaskResult:
        res = _TaskResult()
        idle = 1 << AES_STATUS_IDLE

        def _busy(v: int) -> None:
            if not v & idle:
                res.busy_end_clk = max(res.busy_end_clk, self.last_resp_clk)

        t_begin = self.clk()

        async def _wait_bit(bit: int) -> bool:
            while True:
                v = await self._rd(AES_STATUS)
                if res.start_clk >= 0:
                    _busy(v)
                if v & (1 << bit):
                    return True
                origin = res.start_clk if res.start_clk >= 0 else t_begin
                if self.clk() - origin > bound:
                    res.timeout = True
                    return False
                await ClockCycles(cocotb.top.clk_i, _POLL_GAP_CLK)

        out: list[int] = []
        for blk in range(op.count()):
            if not await _wait_bit(AES_STATUS_INPUT_READY):
                return res
            for i, word in enumerate(op.pt[4 * blk : 4 * blk + 4]):
                await self._wr(AES_DATA_IN_0 + i * 4, word)
            if blk == 0:
                res.start_clk = res.busy_end_clk = self.last_resp_clk
                on_start(res.start_clk)
            if not await _wait_bit(AES_STATUS_OUTPUT_VALID):
                return res
            out += await self.read_data_out()
        if not await _wait_bit(AES_STATUS_IDLE):
            return res
        res.result = out
        return res


class LegKmac(_LegAccess, SepKmac, _LegMember):
    status_addr = KMAC_STATUS

    async def configure_op(self, op: KmacOp) -> int:
        await self._write_prefix(b"")
        cfg = build_kmac_cfg(
            mode=KMAC_MODE[op.mode], kstrength=KMAC_STRENGTH[op.sec], kmac_en=False
        )
        await self._wr(KMAC_CFG_SHADOWED, cfg)
        await self._wr(KMAC_CFG_SHADOWED, cfg)
        await self._wait_idle("leg-pre-start")
        return await self._rd(KMAC_CFG_SHADOWED)

    async def run_op(self, op: KmacOp, bound: int, on_start) -> _TaskResult:
        res = _TaskResult()
        await self._wr(KMAC_CMD, KMAC_CMD_START)
        res.start_clk = res.busy_end_clk = self.last_resp_clk
        on_start(res.start_clk)
        await self.write_bytes(KMAC_MSG_FIFO, op.msg)
        await self._wr(KMAC_CMD, KMAC_CMD_PROCESS)
        res.busy_end_clk = self.last_resp_clk
        # kmac.hjson STATUS.sha3_squeeze: a read with sha3_squeeze = 0 shows busy.
        if await self._poll(res, bound, lambda v: v & KMAC_STATUS_SQUEEZE) is None:
            return res
        digest = []
        for i in range(op.out_bytes // 4):
            s0 = await self._rd(KMAC_STATE_S0 + i * 4)
            s1 = await self._rd(KMAC_STATE_S1 + i * 4)
            digest.append((s0 ^ s1) & 0xFFFF_FFFF)
        # kmac.hjson CMD.done: the engine goes back to idle.
        await self._wr(KMAC_CMD, KMAC_CMD_DONE)
        await self._poll(_TaskResult(start_clk=self.clk()), bound, lambda v: v & KMAC_STATUS_IDLE)
        res.result = digest
        return res


class LegOtbn(_LegAccess, SepOtbn, _LegMember):
    status_addr = OTBN_ADDR_STATUS

    async def configure_op(self, op: OtbnOp) -> int:
        await self.load_program(otbn_compute_prog(op.op))
        await self.write_dmem(0, op.a)
        await self.write_dmem(4, op.b)
        # The result word holds the complement of the golden, so a missing store
        # cannot match.
        await self.write_dmem(8, op.golden()[0] ^ 0xFFFF_FFFF)
        return await self.read_dmem(8)

    async def run_op(self, op: OtbnOp, bound: int, on_start) -> _TaskResult:
        res = _TaskResult()
        await self._wr(OTBN_ADDR_CMD, OTBN_CMD_EXECUTE)
        res.start_clk = res.busy_end_clk = self.last_resp_clk
        on_start(res.start_clk)
        if await self._poll(res, bound, lambda v: v == OTBN_STATUS_IDLE) is None:
            return res
        res.err_bits = await self.read_errbits()
        res.result = [await self.read_dmem(8)]
        return res


_LEG_DRIVERS = {"hmac": LegHmac, "aes": LegAes, "kmac": LegKmac, "otbn": LegOtbn}
_STATUS_ADDR = {
    "hmac": HMAC_STATUS,
    "aes": AES_STATUS,
    "kmac": KMAC_STATUS,
    "otbn": OTBN_ADDR_STATUS,
}


@pyuvm.test()
class sep_crypto_edn_multisink_arbitration_test(sep_base_test):
    """Concurrent AES and KMAC each match their golden, and each beat routes the granted word."""

    required_evidence = ("CHK-CONC-RESULT", "CHK-CONC-HOLD")

    def _aes_beats(self) -> int:
        """Live count of AES crypto-EDN post-adapter beats (public scoreboard accessor)."""
        return self.drbg_sb.sink_beats("aes")

    def _kmac_beats(self) -> int:
        """Live count of KMAC crypto-EDN post-adapter beats (public scoreboard accessor)."""
        return self.drbg_sb.sink_beats("kmac")

    async def run_scenario(self) -> None:
        self._start_edn_watch()
        await self.bring_up_no_cpu()

        # Do not park OTBN/HMAC via SW_RESET_N. Holding a crypto engine in
        # reset while the crypto-EDN adapter is live wedges the AES masking reseed
        # (AES sits idle, no OUTPUT_VALID). OTBN/HMAC are
        # left released (SW_RESET_N reset 0x7E): OTBN does a one-shot post-reset
        # secure wipe then goes idle, and HMAC is not a crypto-EDN client, so AES +
        # KMAC are the sustained clients contending the arbiter (the standalone
        # AES recipe likewise leaves all crypto released and drives AES on entropy).

        # RANDCFG single source: one config object owns the seeded payload policy and logs
        # every resolved value (reproducibility). Key material fixed; seed randomizes
        # the AES plaintext + KMAC message.
        cfg = CryptoEdnMultisinkCfg.randomize(self.random_seed())
        self.logger.info("Crypto-EDN AES+KMAC arbiter contention:")
        cfg.log_resolved(self.logger)
        aes_pt = cfg.aes_pt
        kmac_msg = cfg.kmac_msg

        # Strict entropy bring-up: CHK1..CHK4 bit-exact anchors the one DRBG. Both
        # crypto sinks score CHK5 ROUTING (each post-adapter beat equals the AXIS1
        # word granted that cycle). KM leg unused.
        await self.bring_up_entropy(
            strict=True, score_km=False, score_sinks={"aes": "golden", "kmac": "golden"}
        )
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.start_fifo_drain()  # frontdoor CHK2 drain

        self.aes = SepAes(self)
        self.kmac = SepKmac(self)
        # Reseed the AES masking PRNG ONCE up front, BEFORE configure -- the
        # standalone AES order. Do NOT issue an explicit PRNG_RESEED between the key
        # load and an encrypt: that wedges the auto-start (AES accepts DATA_IN but
        # never asserts OUTPUT_VALID). Each `load_key_iv` kicks off its OWN key-
        # triggered reseed (spec-ordered, waits idle after the key) -- that reseed is
        # what pulls a crypto-EDN word, so re-loading the key per AES op makes AES a
        # live EDN client for the arbiter contention with no separate reseed trigger.
        await self.aes.trigger_prng_reseed()
        await self.aes.configure_ecb_enc_256(sideload=False)
        aes_golden = aes256_ecb_encrypt_words(list(cfg.aes_key), aes_pt)

        kmac_cfg = SepKmacCfg(
            mode="kmac",
            sec=256,
            msg_words=kmac_msg,
            outlen_bytes=32,
            key_words=list(cfg.kmac_key),
            key_bits=256,
            s=cfg.kmac_s,
        )
        kmac_golden = kmac_family_words(**kmac_cfg.golden_kwargs())

        # --- CHK-NONVAC: single-engine AES baseline (correct in isolation, and with
        # KMAC idle the KMAC sink takes ZERO beats -- the not-always-true evidence for
        # the both-beats check below). KMAC's KAT is proven under contention in the
        # fork (a masking engine reseeds once and would not re-pull per op, so putting
        # its first op in the fork lands its seeding beats in the contention window).
        await self.aes.load_key_iv(list(cfg.aes_key))  # key-load reseed pulls crypto-EDN
        base_ct = await self.aes.run_ecb_block(aes_pt)
        assert base_ct == aes_golden, (
            "AES baseline ct != AES-256-ECB golden:\n"
            f"  ct    ={[hex(w) for w in base_ct]}\n  golden={[hex(w) for w in aes_golden]}"
        )
        assert self._aes_beats() > 0, (
            "CHK-SINK-BIND FAIL: AES-alone produced no AES-named beats, so the "
            "sink map is not bound independently of the adapter order"
        )
        assert self._kmac_beats() == 0, (
            f"KMAC took crypto-EDN beats before it was driven "
            f"({self._kmac_beats()}) -- both-beats check would be vacuous"
        )
        self.logger.info(
            "CHK-SINK-BIND PASS: AES-alone scored %d AES beats and 0 KMAC beats",
            self._aes_beats(),
        )
        self.logger.info(
            "CHK-NONVAC PASS: AES single-engine baseline reproduces its KAT "
            "(AES-256-ECB ct==golden) with the KMAC sink idle (0 beats)"
        )

        # --- CHK-BOTH-*: AES + KMAC as CONCURRENT crypto-EDN clients ---------------
        aes_before, kmac_before = self._aes_beats(), self._kmac_beats()

        async def aes_arm():
            """AES crypto-EDN pulls: each iteration re-loads the key (its key-write
            reseed pulls a fresh crypto-EDN word) then runs an ECB block; every block's ct
            is value-checked against the golden under contention."""
            for i in range(cfg.aes_blocks_fork):
                await self.aes.load_key_iv(list(cfg.aes_key))
                ct = await self.aes.run_ecb_block(aes_pt)
                # Every fork block is compared bit-exact: ECB is stateless and the
                # key/plaintext are identical per iteration, so the expected value is
                # known for every block and each one is a contended data point.
                assert ct == aes_golden, (
                    f"AES contended block-{i} ct != golden:\n"
                    f"  ct    ={[hex(w) for w in ct]}\n"
                    f"  golden={[hex(w) for w in aes_golden]}"
                )

        async def kmac_arm():
            """KMAC crypto-EDN pulls: each keyed KMAC-256 op reseeds masking from EDN;
            digest value-checked against the Keccak golden under contention."""
            for i in range(cfg.kmac_ops_fork):
                digest = await self.kmac.run_family(kmac_cfg, tag=f"KMAC-fork{i}")
                assert digest == kmac_golden, (
                    f"KMAC contended op-{i} digest != golden:\n"
                    f"  digest={[hex(w) for w in digest]}\n"
                    f"  golden={[hex(w) for w in kmac_golden]}"
                )

        # TRUE fork: both arms run as concurrent cocotb tasks, so the AES and KMAC
        # masking-EDN pulls overlap and contend at the crypto arbiter in one window.
        aes_task = cocotb.start_soon(aes_arm())
        kmac_task = cocotb.start_soon(kmac_arm())
        await aes_task
        await kmac_task
        self.logger.info(
            "CHK-BOTH-COMPLETE PASS: under contention every AES block ct==golden AND "
            "KMAC digest==golden"
        )

        aes_after, kmac_after = self._aes_beats(), self._kmac_beats()
        assert aes_after > aes_before, (
            f"AES took no crypto-EDN beats during the concurrent fork "
            f"(beats {aes_before}->{aes_after})"
        )
        assert kmac_after > kmac_before, (
            f"KMAC took no crypto-EDN beats during the concurrent fork "
            f"(beats {kmac_before}->{kmac_after})"
        )
        self.logger.info(
            "CHK-BOTH-BEATS PASS: both crypto sinks took real post-adapter EDN beats "
            "in the contention window (AES %d->%d, KMAC %d->%d)",
            aes_before,
            aes_after,
            kmac_before,
            kmac_after,
        )

        # --- CHK-OVERLAP: positive arbiter-CONTENTION proof. CHK-BOTH-BEATS only
        # proves each client took beats SOMEWHERE in the fork; this proves AES's and
        # KMAC's crypto-EDN beat TIME-SPANS overlap -- both were being granted words by
        # u_axis_edn_crypto_s3c_scan during an overlapping window, so neither sink
        # drained fully before the other started. Interval-span containment, not
        # per-cycle interleaving. Scoping by the pre-fork beat count isolates the
        # fork's beats. Same-cycle dual req does not occur here: each masking reseed
        # is a brief req pulse separated by long AXI configuration.
        aes_ft = self.drbg_sb.sink_beat_times("aes")[aes_before:]
        kmac_ft = self.drbg_sb.sink_beat_times("kmac")[kmac_before:]
        assert aes_ft and kmac_ft, (
            f"missing fork beats (AES {len(aes_ft)}, KMAC {len(kmac_ft)}) -- "
            "cannot evaluate contention overlap"
        )
        overlap = aes_ft[0] <= kmac_ft[-1] and kmac_ft[0] <= aes_ft[-1]
        assert overlap, (
            "AES and KMAC crypto-EDN beat windows do not overlap during the fork "
            f"(AES [{aes_ft[0]:.0f},{aes_ft[-1]:.0f}]ns, KMAC [{kmac_ft[0]:.0f},"
            f"{kmac_ft[-1]:.0f}]ns): the arbiter served them sequentially, not "
            "concurrently -- the 'contention' claim would be vacuous"
        )
        ov_lo, ov_hi = max(aes_ft[0], kmac_ft[0]), min(aes_ft[-1], kmac_ft[-1])
        self.logger.info(
            "CHK-OVERLAP PASS: AES and KMAC crypto-EDN beat windows overlap over "
            "[%.0f,%.0f]ns (AES [%.0f,%.0f], KMAC [%.0f,%.0f]) -- neither sink drained "
            "before the other started (interval-span containment, not per-cycle interleaving)",
            ov_lo,
            ov_hi,
            aes_ft[0],
            aes_ft[-1],
            kmac_ft[0],
            kmac_ft[-1],
        )

        # --- EOT: engine status clean, entropy health, dual-sink CHK5 routing ------
        await self.aes.check_status_clean("EOT")
        await self.kmac.check_status_clean("EOT")
        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        # Strict report: CHK1..CHK4 bit-exact + CHK5_aes/CHK5_kmac ROUTING
        # (each post-adapter beat == the AXIS1 word granted that cycle).
        assert self.drbg_sb.report()
        ra = self.drbg_sb.results["CHK5_aes"]
        rk = self.drbg_sb.results["CHK5_kmac"]
        self.logger.info(
            "CHK-ROUTING PASS: CHK5_aes match=%d and CHK5_kmac match=%d equal the "
            "AXIS1 grant-order stream (mismatch=0)",
            ra.matches,
            rk.matches,
        )
        self.logger.info(
            "CHK-MEMBERSHIP PASS: every AES and every KMAC crypto-EDN word is a CHK4 "
            "genbits-golden word (AXIS1 chained to genbits) -- one DRBG partitions "
            "into the two contending crypto sinks; CHK1..CHK4 bit-exact; alerts zero"
        )

        await self._concurrency_leg()

    # --- Four-engine concurrency leg -----------------------------------------

    def _start_edn_watch(self) -> None:
        """Count the EDN words of the whole run, all four clients, from clock 0.

        One ``crypto_edn_ack_o`` high clock is one 32-bit word. ``xz_fail`` is off
        because the ports are X before the reset release on a 4-state simulator;
        an X sample is skipped and never counts as a word.
        """
        dut = cocotb.top
        bits = {f"c{i}": i for i in range(4)}
        self._edn_ack_watch = SepBitWatch(
            dut.crypto_edn_ack_o, bits, name="crypto_edn_ack_o", xz_fail=False
        ).start()
        self._edn_req_watch = SepBitWatch(
            dut.crypto_edn_req_o, dict(bits), name="crypto_edn_req_o", xz_fail=False
        ).start()
        self._edn_mark0 = self._edn_ack_watch.mark()

    def _leg_clk(self) -> int:
        return self._edn_ack_watch.clk

    def _edn_words(self) -> int:
        """W: EDN words acked on crypto_edn_ack_o[3:0] since the first clock of the run."""
        return sum(
            self._edn_ack_watch.high_clocks_since(self._edn_mark0, f"c{i}") for i in range(4)
        )

    async def _wait_edn_req_low(self, eng: str) -> None:
        for bit in _EDN_CLIENTS[eng]:
            await self._edn_req_watch.wait_level(0, _REQ_LOW_WAIT_CLK, f"c{bit}")

    async def _wait_probe(self, eng: str, level: int) -> None:
        dut = cocotb.top
        sig = getattr(dut, f"{eng}_gated_rst_n_probe_o")
        for _ in range(_RESET_WAIT_CLK):
            if self.rd(sig) == level:
                return
            await RisingEdge(dut.clk_i)
        raise AssertionError(
            f"{eng}_gated_rst_n_probe_o did not read {level} within {_RESET_WAIT_CLK} clocks"
        )

    async def _wait_ready(self, eng: str, drv) -> None:
        """First OKAY readback of STATUS after a release, then the engine idle."""
        t0 = self._leg_clk()
        while not await drv.try_read(_STATUS_ADDR[eng]):
            if self._leg_clk() - t0 > _RESET_WAIT_CLK:
                raise AssertionError(
                    f"{eng} STATUS gave no OKAY readback within {_RESET_WAIT_CLK} clocks "
                    "after the reset release"
                )
            await ClockCycles(cocotb.top.clk_i, _POLL_GAP_CLK)
        if eng in ("aes", "otbn"):
            # EDN is up, so the AES reseed and the OTBN wipe after the reset end.
            await drv.wait_idle(f"leg-{eng}-reset")

    async def _reset_one(self, eng: str, drv) -> None:
        """Clear the bit, wait for the gated reset, set the bit, wait until ready."""
        await self._wait_edn_req_low(eng)
        await self.leg_swrst.park(eng)
        await self._wait_probe(eng, 0)
        await self.leg_swrst.release(eng)
        await self._wait_ready(eng, drv)

    async def _group_reset(self, g: LegGroup, drivers: dict) -> None:
        """SW_RESET_N = baseline with the engines outside the group cleared.

        HMAC is not an EDN client and stays released in a group without an HMAC
        member (the bystander). An engine with a live EDN request is cleared only
        after the request drops.
        """
        outside = [e for e in _ENGINES if e not in g.members and e != "hmac"]
        for eng in outside:
            await self._wait_edn_req_low(eng)
        value = _SW_RESET_BASELINE
        for eng in outside:
            value &= ~(1 << SW_RESET_N_BIT[eng])
        self.leg_swrst.value = value
        await self.leg_swrst.release()
        self.logger.info(
            "LEG group=%s SW_RESET_N=0x%02x outside=%s", g.name, value, ",".join(outside) or "-"
        )
        for eng in outside:
            await self._wait_probe(eng, 0)
        for eng in g.members:
            if eng in ("aes", "otbn"):
                await self._wait_ready(eng, drivers[eng])

    async def _clean_run(self, chk, g: LegGroup, eng: str, op, drv) -> tuple[int, int]:
        """One member alone: golden compare, t_op and the EDN words of the run."""
        w_before = self._edn_words()
        await drv.configure_op(op)
        res = await drv.run_op(op, _CLEAN_RUN_CLK, lambda _clk: None)
        if res.timeout:
            raise AssertionError(
                f"clean run of {eng} in group {g.name} showed no end within {_CLEAN_RUN_CLK} clocks"
            )
        words = self._edn_words() - w_before
        golden_ok = res.result == op.golden() and res.err_bits == 0
        chk.ctrl(
            "CONC-CLEAN",
            golden_ok,
            group=g.name,
            engine=eng,
            golden_ok=int(golden_ok),
            t_op=res.busy_clk,
            edn_words=words,
            op=op.desc(),
        )
        await self._reset_one(eng, drv)
        return res.busy_clk, words

    async def _bystander_job(self, chk, g: LegGroup, drv) -> list[int]:
        """Finished plain SHA-256 in an idle HMAC; returns the bystander golden."""
        await self._reset_one("hmac", drv)
        await drv._wr(HMAC_CFG, build_cfg(hmac_en=False, sha_bits=256))
        await drv._wr(HMAC_CMD, HMAC_CMD_HASH_START)
        await drv.write_bytes(HMAC_MSG_FIFO, g.bystander_msg)
        await drv._wr(HMAC_CMD, HMAC_CMD_HASH_PROCESS)
        poll = _TaskResult(start_clk=self._leg_clk())
        if await drv._poll(poll, _BYSTANDER_DONE_CLK, lambda v: v & HMAC_INTR_DONE) is None:
            raise AssertionError(
                f"bystander SHA-256 in group {g.name} set no hmac_done within "
                f"{_BYSTANDER_DONE_CLK} clocks"
            )
        digest = [await drv._rd(HMAC_DIGEST_0 + i * 4) for i in range(8)]
        golden = _digest_words_be(sha2_bytes(g.bystander_msg, 256))
        chk.ctrl(
            "CONC-BYSTANDER",
            digest == golden,
            group=g.name,
            digest0=f"0x{digest[0]:08x}",
            golden0=f"0x{golden[0]:08x}",
        )
        await drv._wr(HMAC_INTR_STATE, HMAC_INTR_DONE)
        return golden

    async def _run_group(self, chk, g: LegGroup, rng: SepSeededRng, drivers: dict, by) -> None:
        dut = cocotb.top
        w_group0 = self._edn_words()
        await self._group_reset(g, drivers)

        # Clean runs, with the budget guard: halve the count of the member with
        # the most clean EDN words while the group would exceed the budget.
        ops = dict(g.ops)
        while True:
            for eng in g.members:
                await self._reset_one(eng, drivers[eng])
            if g.has_bystander:
                await self._reset_one("hmac", drivers["hmac"])
            clean = {}
            for eng in g.order:
                clean[eng] = await self._clean_run(chk, g, eng, ops[eng], drivers[eng])
            need = self._edn_words() + sum(words for _t, words in clean.values())
            if need <= _EDN_BUDGET_WORDS:
                break
            halvable = [e for e in g.members if ops[e].halved() != ops[e]]
            if not halvable:
                chk.ctrl(
                    "CONC-BUDGET",
                    False,
                    group=g.name,
                    words=need - self._edn_words(),
                    run_total=need,
                    budget=_EDN_BUDGET_WORDS,
                    reason="minimum_counts",
                )
                return
            big = max(halvable, key=lambda e: clean[e][1])
            ops[big] = ops[big].halved()
            self.logger.info(
                "LEG group=%s budget halving %s -> %s (need=%d budget=%d)",
                g.name,
                big,
                ops[big].desc(),
                need,
                _EDN_BUDGET_WORDS,
            )

        # Skews: drawn after the clean runs, from the plan generator, 0 to half
        # the shortest clean busy time of the group.
        min_t = min(t for t, _w in clean.values())
        skew = {g.order[0]: 0}
        for eng in g.order[1:]:
            skew[eng] = rng.randrange(0, min_t // 2 + 1)
        self.logger.info(
            "LEG group=%s skews %s min_t_op=%d",
            g.name,
            " ".join(f"{e}={skew[e]}" for e in g.order),
            min_t,
        )

        by_golden = await self._bystander_job(chk, g, drivers["hmac"]) if g.has_bystander else None

        open_graded_window(_TEST_NAME, self.logger)
        for eng in _CFG_ORDER:
            if eng in g.members:
                readback = await drivers[eng].configure_op(ops[eng])
                chk.obs("CONC-CFG", group=g.name, engine=eng, readback=f"0x{readback:08x}")

        records: dict[str, list] = {eng: [] for eng in g.members}
        for eng in g.members:
            drivers[eng].record = records[eng]
        first = Event()
        first_clk = [0]

        def _first_started(clk: int) -> None:
            if not first.is_set():
                first_clk[0] = clk
                first.set()

        async def _member(eng: str) -> _TaskResult:
            on_start = _first_started if eng == g.order[0] else (lambda _clk: None)
            if eng != g.order[0]:
                await first.wait()
                while self._leg_clk() < first_clk[0] + skew[eng]:
                    await RisingEdge(dut.clk_i)
            bound = 8 * max(clean[eng][0], 1) + skew[eng]
            res = await drivers[eng].run_op(ops[eng], bound, on_start)
            # Releases the other members when the first one ends before its start write.
            _first_started(self._leg_clk())
            return res

        reads: list[tuple[int, int, int, bool]] = []
        stop = Event()

        async def _bystander_reads() -> None:
            by.record = []
            await first.wait()
            idx = 0
            while not stop.is_set():
                value = await by._rd(HMAC_DIGEST_0 + idx * 4)
                reads.append((by.last_resp_clk, idx, value, by.record[-1][2]))
                idx = (idx + 1) % 8
                await ClockCycles(dut.clk_i, _BYSTANDER_GAP_CLK)
            by.record = None

        tasks = {eng: cocotb.start_soon(_member(eng)) for eng in g.order}
        by_task = cocotb.start_soon(_bystander_reads()) if g.has_bystander else None
        results = {eng: await tasks[eng] for eng in g.order}
        stop.set()
        if by_task is not None:
            await by_task
        for eng in g.members:
            drivers[eng].record = None

        for a, b in combinations(g.members, 2):
            ra, rb = results[a], results[b]
            overlap = max(
                0, min(ra.busy_end_clk, rb.busy_end_clk) - max(ra.start_clk, rb.start_clk)
            )
            chk.ctrl(
                "CONC-OVERLAP", overlap > 0, group=g.name, pair=f"{a},{b}", overlap_clk=overlap
            )

        w_now = self._edn_words()
        chk.ctrl(
            "CONC-BUDGET",
            w_now <= _EDN_BUDGET_WORDS,
            group=g.name,
            words=w_now - w_group0,
            run_total=w_now,
            budget=_EDN_BUDGET_WORDS,
        )

        for eng in g.order:
            res = results[eng]
            golden = ops[eng].golden()
            golden_ok = res.result == golden and res.err_bits == 0
            bad = [f"{op}@0x{addr:08x}" for op, addr, ok in records[eng] if not ok]
            chk.ok(
                "CONC-RESULT",
                golden_ok and not bad and not res.timeout,
                group=g.name,
                engine=eng,
                golden_ok=int(golden_ok),
                all_okay=int(not bad),
                accesses=len(records[eng]),
                timeout=int(res.timeout),
                skew=skew[eng],
                busy_clk=res.busy_clk,
                err_bits=f"0x{res.err_bits:x}",
                result0=f"0x{res.result[0]:08x}" if res.result else "none",
                golden0=f"0x{golden[0]:08x}",
                not_okay=",".join(bad[:4]) or "-",
            )

        if by_golden is not None:
            windows = [(results[e].start_clk, results[e].busy_end_clk) for e in g.members]
            busy_reads = sum(1 for clk, *_ in reads if any(s <= clk <= e for s, e in windows))
            chk.ctrl(
                "CONC-HOLD-BUSY-READS",
                busy_reads >= 1,
                group=g.name,
                reads=busy_reads,
                total_reads=len(reads),
            )
            wrong = [(clk, i, v) for clk, i, v, ok in reads if not ok or v != by_golden[i]]
            chk.ok(
                "CONC-HOLD",
                bool(reads) and not wrong,
                group=g.name,
                bystander="hmac",
                reads=busy_reads,
                total_reads=len(reads),
                stable=int(bool(reads) and not wrong),
                interval_clk=_BYSTANDER_GAP_CLK,
                first_wrong=(
                    f"clk{wrong[0][0]}:DIGEST_{wrong[0][1]}=0x{wrong[0][2]:08x}" if wrong else "-"
                ),
            )
        close_graded_window(self.logger)

    async def _concurrency_leg(self) -> None:
        """HMAC, KMAC, AES and OTBN in overlap each return their own golden."""
        seed = self.random_seed()
        chk = SepChkLog(self, _TEST_NAME, seed)
        groups, rng = draw_plan(seed)
        for g in groups:
            self.logger.info(
                "PLAN seed=%d group=%s members=%s order=%s bystander=%d ops=[%s]",
                seed,
                g.name,
                ",".join(g.members),
                ",".join(g.order),
                int(g.has_bystander),
                " ".join(g.ops[e].desc() for e in g.members),
            )
        w_start = self._edn_words()
        chk.ctrl(
            "CONC-BUDGET",
            w_start <= _EDN_BUDGET_WORDS,
            start=w_start,
            budget=_EDN_BUDGET_WORDS,
        )
        self.leg_swrst = SepSwReset(self)
        self.leg_swrst.value = await self.leg_swrst.read_back()
        drivers = {
            eng: _LEG_DRIVERS[eng](self, axi_id=_AXI_ID[eng], clk=self._leg_clk) for eng in _ENGINES
        }
        bystander = LegHmac(self, axi_id=_AXI_ID["bystander"], clk=self._leg_clk)
        for g in groups:
            await self._run_group(chk, g, rng, drivers, bystander)
        close_graded_window(self.logger)
        total = self._edn_words()
        chk.ctrl("CONC-BUDGET", total <= _EDN_BUDGET_WORDS, total=total, budget=_EDN_BUDGET_WORDS)
        chk.finish()
