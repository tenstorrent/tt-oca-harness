# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Spec tables, frame builders and the seeded plan of ``sep_km_command_protocol_rand_test``.

No cocotb import: the plan is a pure function of the seed, so it can be drawn
and checked without a simulator.

Every constant comes from ``hw/ip/key_manager/doc/firmware.adoc``: the command
IDs from the command summary table of "Command Message Reference", the return
codes from the return-code table of "0x00 - RESP_CMD", the fault codes from the
recoverable-fault table of "0xFE - RESP_RECOVERABLE_FAULT", the response IDs
from the headings of the response sections, and the frame layout and the
validation order from "Command Message Reference" and "Incoming Message
Handler". The CRC goldens are ``env/sep_crc_golden.py``, pinned to published
check values.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace

from env.sep_crc_golden import crc8_rohc, crc32c
from env.sep_seeded_rng import SepSeededRng

WORD_MASK = 0xFFFF_FFFF

# --- command IDs (command summary table) ----------------------------------------
CMD_HW_VER = 0x00
CMD_ROM_VER = 0x01
CMD_SRAM_VER = 0x02
CMD_STAT = 0x03
CMD_RECOV_ACK = 0x04
CMD_EXEC_ROM = 0x10
CMD_SRAM_LOAD_EXEC = 0x11
CMD_SRAM_EXEC = 0x12
CMD_KEY_GENERATE = 0x22
CMD_KEY_REVOKE = 0x23
CMD_KEY_TRANSFER = 0x24
CMD_ENGINE_SHRED = 0x25
CMD_KEY_LOAD = 0x26
CMD_ABR_SK_TRANSFER = 0x27
CMD_OTP_READ_LOCK_COLD = 0x28
SPEC_CMD_IDS = frozenset(
    (
        CMD_HW_VER,
        CMD_ROM_VER,
        CMD_SRAM_VER,
        CMD_STAT,
        CMD_RECOV_ACK,
        CMD_EXEC_ROM,
        CMD_SRAM_LOAD_EXEC,
        CMD_SRAM_EXEC,
        CMD_KEY_GENERATE,
        CMD_KEY_REVOKE,
        CMD_KEY_TRANSFER,
        CMD_ENGINE_SHRED,
        CMD_KEY_LOAD,
        CMD_ABR_SK_TRANSFER,
        CMD_OTP_READ_LOCK_COLD,
    )
)
INVALID_CMD_IDS = tuple(i for i in range(0x100) if i not in SPEC_CMD_IDS)

# The five commands that reach their handlers while RECOVERABLE_ERR is set
# ("Error Recovery"); every other valid command is gated.
ADMITTED = (CMD_HW_VER, CMD_ROM_VER, CMD_SRAM_VER, CMD_STAT)
GATED = (
    CMD_KEY_GENERATE,
    CMD_KEY_LOAD,
    CMD_KEY_REVOKE,
    CMD_KEY_TRANSFER,
    CMD_ENGINE_SHRED,
    CMD_OTP_READ_LOCK_COLD,
    CMD_ABR_SK_TRANSFER,
    CMD_EXEC_ROM,
    CMD_SRAM_LOAD_EXEC,
    CMD_SRAM_EXEC,
)
HANDOVER = (CMD_EXEC_ROM, CMD_SRAM_LOAD_EXEC, CMD_SRAM_EXEC)
# The gated commands whose handler result differs from failure in a clear
# window of this test, so their -1 under the gate is a witness of the gate.
KEY_OTP_WITNESSES = (
    CMD_KEY_GENERATE,
    CMD_KEY_LOAD,
    CMD_KEY_REVOKE,
    CMD_KEY_TRANSFER,
    CMD_ENGINE_SHRED,
    CMD_OTP_READ_LOCK_COLD,
)

# --- response IDs and codes -------------------------------------------------------
RESP_CMD = 0x00
RESP_KM_READY = 0x55
RESP_RECOVERABLE_FAULT = 0xFE

RC_SUCCESS = 0
RC_FAILURE = -1
RC_HEADER_CRC = -2
RC_CMD_NOSEQ = -3
RC_INVALID_CMD = -4
RC_INVALID_LEN = -5
RC_PAYLOAD_CRC = -6
RC_INVALID_ARG = -7

FAULT_RX_BUFF_OFLOW = -2
FAULT_FLUSHED_BY_SEP = -5

# "0x00 - CMD_HW_VER" .. "0x03 - CMD_STAT": the four admitted queries carry no
# payload, and "0x25 - CMD_ENGINE_SHRED" takes one mask word. The dispatch
# length check rejects any other PAYLOAD_LEN for these carriers.
REQUIRED_PLEN = {CMD_HW_VER: 0, CMD_ROM_VER: 0, CMD_SRAM_VER: 0, CMD_STAT: 0, CMD_ENGINE_SHRED: 1}
# The fixed result of each carrier of the wrap pass and of the cause loop. The
# ROM always returns failure to CMD_SRAM_VER ("0x02 - CMD_SRAM_VER").
CARRIER_CODE = {CMD_HW_VER: RC_SUCCESS, CMD_ROM_VER: RC_SUCCESS, CMD_SRAM_VER: RC_FAILURE}

DEST_AES = 0x04  # DEST_VALID bit 2 ("0x22 - CMD_KEY_GENERATE", destination policy)
SHRED_MASK = 0x80  # contract carrier: CMD_ENGINE_SHRED with mask 0x80
OTP_LOCK_MASK = 0x001  # contract: CMD_OTP_READ_LOCK_COLD with mask 0x001

# "Message Buffers": the receive buffer holds 257 words. 257 words with no
# separator fill it without a complete frame (rx_buff_oflow).
RX_BUFFER_WORDS = 257

# --- fault kinds of the frame leg ---------------------------------------------------
# Contract letters: (a) hdr_crc, (b) seq, (c) cmd_id, (d) len_wire, (f) pcrc,
# (e) len_self. The tuple is the order of the checks ("Incoming Message
# Handler"): header CRC, sequence, command ID, frame length, payload CRC,
# dispatch length.
KIND_ORDER = ("hdr_crc", "seq", "cmd_id", "len_wire", "pcrc", "len_self")
# The pairs (c, e) and (d, e) have no valid frame and are not drawn.
_NO_PAIR = {("cmd_id", "len_self"), ("len_wire", "len_self")}
PAIRS = tuple(
    (a, b) for i, a in enumerate(KIND_ORDER) for b in KIND_ORDER[i + 1 :] if (a, b) not in _NO_PAIR
)
assert len(PAIRS) == 13, PAIRS

# Expected-sequence rule: header_crc and cmd_noseq leave e unchanged; every
# later rejection advances it ("Command Message Reference").
E_ADVANCE = {"hdr_crc": 0, "seq": 0, "cmd_id": 1, "len_wire": 1, "pcrc": 1, "len_self": 1}
KIND_CODE = {
    "hdr_crc": RC_HEADER_CRC,
    "seq": RC_CMD_NOSEQ,
    "cmd_id": RC_INVALID_CMD,
    "len_wire": RC_INVALID_LEN,
    "pcrc": RC_PAYLOAD_CRC,
    "len_self": RC_INVALID_LEN,
}

# Sentinel for an argument that is logged and not graded (kind (d)).
ARG_LOGGED = "logged"


def signed8(value: int) -> int:
    v = value & 0xFF
    return v - 0x100 if v & 0x80 else v


def frame_len(plen: int) -> int:
    """Words of a frame with PAYLOAD_LEN ``plen``: header, payload, CRC if plen > 0."""
    return 1 + plen + (1 if plen > 0 else 0)


def payload_crc(words: list[int] | tuple[int, ...]) -> int:
    return crc32c(b"".join((w & WORD_MASK).to_bytes(4, "little") for w in words))


def header_crc(seq: int, cmd: int, plen: int) -> int:
    return crc8_rohc(bytes([seq & 0xFF, cmd & 0xFF, plen & 0xFF]))


def header(cmd: int, seq: int, plen: int, crc_xor: int = 0) -> int:
    crc = header_crc(seq, cmd, plen) ^ (crc_xor & 0xFF)
    return (crc << 24) | ((plen & 0xFF) << 16) | ((cmd & 0xFF) << 8) | (seq & 0xFF)


def cmd_frame(cmd: int, seq: int, payload: list[int] | tuple[int, ...]) -> list[int]:
    """A well-formed command frame: header, payload, CRC-32C when the payload is not empty."""
    words = [header(cmd, seq, len(payload))]
    words += [w & WORD_MASK for w in payload]
    if payload:
        words.append(payload_crc(payload))
    return words


# --- pair leg -----------------------------------------------------------------------


@dataclass(frozen=True)
class PairDraw:
    first: str
    second: str
    carrier: int
    crc_xor: int  # (a): wrong HEADER_CRC8 = right ^ crc_xor
    seq_delta: int  # (b): wrong CMD_SEQ_NUM = e + seq_delta (mod 256)
    bad_cmd: int  # (c): COMMAND_ID outside the valid IDs
    flip_bit: int  # (f): bit flipped in PAYLOAD_CRC32
    d_extra: tuple[int, ...]  # (d), CMD_HW_VER carrier: extra non-zero words on the wire
    d_plen: int  # (d): declared PAYLOAD_LEN that contradicts the wire
    e_words: tuple[int, ...]  # (e): self-consistent payload of the wrong length

    @property
    def kinds(self) -> tuple[str, str]:
        return (self.first, self.second)


@dataclass(frozen=True)
class FaultFrame:
    """One frame of the pair leg and the response the specification states for it."""

    words: tuple[int, ...]
    sent_seq: int
    sent_cmd: int
    kind: str  # the earliest failing check
    code: int
    arg: int | None | str  # int: graded value; None: no argument; ARG_LOGGED: not graded
    e_after: int
    payload: tuple[int, ...]
    declared_plen: int


def build_fault_frame(
    d: PairDraw, kinds: frozenset[str], e: int, payload: tuple[int, ...] | None = None
) -> FaultFrame:
    """Build the frame of ``d`` that carries the faults ``kinds`` (a subset of its pair).

    ``payload`` replaces the carrier payload when the frame has no (e) fault.

    Each wrong value is asserted to differ from the right value before the
    frame is returned, so a fault that is not one cannot reach the DUT.
    """
    if not kinds or not kinds <= set(d.kinds):
        raise ValueError(f"kinds {sorted(kinds)} not in pair {d.kinds}")
    carrier = d.carrier
    if "len_self" in kinds:
        payload = tuple(d.e_words)
        assert len(payload) != REQUIRED_PLEN[carrier], "len_self payload has the required length"
    elif payload is None:
        payload = (SHRED_MASK,) if carrier == CMD_ENGINE_SHRED else ()
    cmd = carrier
    if "cmd_id" in kinds:
        cmd = d.bad_cmd
        assert cmd not in SPEC_CMD_IDS, f"bad command ID 0x{cmd:02x} is a valid ID"
    seq = e & 0xFF
    if "seq" in kinds:
        seq = (e + d.seq_delta) & 0xFF
        assert seq != (e & 0xFF), "wrong sequence number equals the expected one"
    body = [w & WORD_MASK for w in payload]
    if payload:
        right_crc = payload_crc(payload)
        crc = right_crc
        if "pcrc" in kinds:
            crc = right_crc ^ (1 << d.flip_bit)
            assert crc != right_crc, "flipped payload CRC equals the right CRC"
        body.append(crc)
    elif "pcrc" in kinds:
        raise ValueError("pcrc fault needs a payload")
    plen = len(payload)
    if "len_wire" in kinds:
        body += list(d.d_extra)
        plen = d.d_plen
        assert frame_len(plen) != 1 + len(body), (
            f"len_wire PAYLOAD_LEN {plen} matches the wire length {1 + len(body)}"
        )
    crc_xor = 0
    if "hdr_crc" in kinds:
        crc_xor = d.crc_xor
        assert crc_xor & 0xFF, "wrong header CRC equals the right CRC"
    words = (header(cmd, seq, plen, crc_xor), *body)

    kind = next(k for k in KIND_ORDER if k in kinds)
    if kind == "hdr_crc":
        arg: int | None | str = header_crc(seq, cmd, plen)
    elif kind == "seq":
        arg = e & 0xFF
    elif kind == "cmd_id":
        arg = None
    elif kind == "len_wire":
        arg = ARG_LOGGED
    elif kind == "pcrc":
        arg = payload_crc(payload)
    else:
        arg = len(payload)
    return FaultFrame(
        words=words,
        sent_seq=seq,
        sent_cmd=cmd,
        kind=kind,
        code=KIND_CODE[kind],
        arg=arg,
        e_after=(e + E_ADVANCE[kind]) & 0xFF,
        payload=payload,
        declared_plen=plen,
    )


# The frame-level kinds a vault-writing command carries in the pair leg. Kinds
# (c) and (e) change the command or its required length, so they are not used.
VAULT_KINDS = ("hdr_crc", "seq", "len_wire", "pcrc")
VAULT_CMDS = (CMD_KEY_LOAD, CMD_KEY_GENERATE)


@dataclass(frozen=True)
class VaultDraw:
    """The vault-writing frame of one pair: its command, its payload and the (d) PAYLOAD_LEN."""

    cmd: int
    payload: tuple[int, ...]
    d_plen: int


def build_vault_frame(d: PairDraw, v: VaultDraw, e: int) -> FaultFrame:
    """The command of ``v`` with the frame-level faults of the pair ``d``."""
    kinds = frozenset(k for k in d.kinds if k in VAULT_KINDS)
    vd = replace(d, carrier=v.cmd, d_extra=(), d_plen=v.d_plen)
    return build_fault_frame(vd, kinds, e, payload=v.payload)


# --- seeded plan ----------------------------------------------------------------------


@dataclass(frozen=True)
class GateDraw:
    source: str  # "rx_oflow" or "flush"
    gen_words: int  # CMD_KEY_GENERATE size in words (REQ_SIZE + 1)
    gen_dest: int
    load_key: tuple[int, ...]
    load_dest: int
    h_key: tuple[int, ...]
    h_dest: int
    abr_dest: int
    order: tuple[int, ...]  # the 14 commands of the gate matrix in send order
    vf_crc_xor: int  # validation-first wrong header CRC
    vf_flip_bit: int  # validation-first wrong payload CRC bit
    ack_delay: int
    oflow_words: tuple[int, ...]  # 257 words when source is rx_oflow, else empty


@dataclass(frozen=True)
class HandoverDraw:
    cmd: int
    source: str
    oflow_words: tuple[int, ...]


def _nonzero(rng: SepSeededRng) -> int:
    return rng.randrange(1, 1 << 32)


def _words(rng: SepSeededRng, n: int) -> tuple[int, ...]:
    return tuple(_nonzero(rng) for _ in range(n))


def _key(rng: SepSeededRng, n: int) -> tuple[int, ...]:
    """Non-zero key words; the first eight are pairwise different."""
    out: list[int] = []
    while len(out) < n:
        w = _nonzero(rng)
        if len(out) < 8 and w in out:
            continue
        out.append(w)
    return tuple(out)


def _dest_with(rng: SepSeededRng, bit: int) -> int:
    return (rng.getrandbits(8) | bit) & 0xFF


def _fmt(value) -> str:
    if isinstance(value, (tuple, list)):
        if len(value) > 16:
            h = hashlib.sha256(b"".join((w & WORD_MASK).to_bytes(4, "little") for w in value))
            return f"n={len(value)}:sha256={h.hexdigest()[:16]}"
        return "[" + ",".join(f"0x{w:x}" if isinstance(w, int) else str(w) for w in value) + "]"
    return str(value)


class CommandProtocolPlan:
    """Every drawn value of one leaf, drawn once from the seed in a fixed order."""

    WRAP_FRAMES = 260
    WRAP_CARRIERS = (CMD_HW_VER, CMD_ROM_VER, CMD_SRAM_VER)
    LOOP_CARRIERS = (CMD_HW_VER, CMD_ROM_VER, CMD_STAT)
    CAUSES = ("rx_oflow", "flush", "warm_reset")
    SOURCES = ("rx_oflow", "flush")
    ACK_DELAYS = (0, 100, 2000)

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        self._draws: list[tuple[str, object]] = []

        order = list(PAIRS)
        rng.shuffle(order)
        self._log("pair_order", [f"{a}>{b}" for a, b in order])
        self.pairs = tuple(self._pair(rng, i, a, b) for i, (a, b) in enumerate(order))

        # Step 14 positive twins.
        self.twin_load_key = _key(rng, 4)
        self.twin_abr_dest = rng.randrange(1, 0x100)
        self._log("twin_load_key", self.twin_load_key)
        self._log("twin_abr_dest", self.twin_abr_dest)

        self.wrap_carriers = tuple(rng.choice(self.WRAP_CARRIERS) for _ in range(self.WRAP_FRAMES))
        self._log("wrap_carriers", "".join(str(c) for c in self.wrap_carriers))

        causes = list(self.CAUSES)
        rng.shuffle(causes)
        self.cause_order = tuple(causes)
        self._log("cause_order", self.cause_order)
        self.cause_p: dict[str, tuple[int, ...]] = {}
        self.cause_oflow: dict[str, tuple[int, ...]] = {}
        for cause in self.cause_order:
            p = rng.randrange(10, 41)
            self.cause_p[cause] = tuple(rng.choice(self.LOOP_CARRIERS) for _ in range(p))
            self._log(f"cause_{cause}_p", p)
            self._log(f"cause_{cause}_carriers", "".join(str(c) for c in self.cause_p[cause]))
            self.cause_oflow[cause] = _words(rng, RX_BUFFER_WORDS) if cause == "rx_oflow" else ()
            if cause == "rx_oflow":
                self._log("cause_rx_oflow_words", self.cause_oflow[cause])

        sources = list(self.SOURCES)
        rng.shuffle(sources)
        self._log("gate_source_order", sources)
        self.gates = tuple(self._gate(rng, s) for s in sources)

        self.handovers = []
        for cmd in HANDOVER:
            src = rng.choice(self.SOURCES)
            words = _words(rng, RX_BUFFER_WORDS) if src == "rx_oflow" else ()
            self._log(f"handover_0x{cmd:02x}_source", src)
            if words:
                self._log(f"handover_0x{cmd:02x}_oflow_words", words)
            self.handovers.append(HandoverDraw(cmd=cmd, source=src, oflow_words=words))
        self.handovers = tuple(self.handovers)

        # q is 3: with more unread frames the KM stops taking inbound words and
        # the overflow cannot be reached (firmware.adoc, "Message Buffers": a
        # complete frame blocks further writes until consumed; "Outgoing Message
        # Handler": TX spin-waits until the SEP drains the FIFO). The draw is kept
        # so that the later draws do not move.
        rng.randrange(3, 9)
        self.oflow_q = 3
        self.oflow_words = _words(rng, RX_BUFFER_WORDS)
        self._log("oflow_q", self.oflow_q)
        self._log("oflow_pend_words", self.oflow_words)

        self.vault = tuple(self._vault(rng, i, d) for i, d in enumerate(self.pairs))

    # -- draw helpers ------------------------------------------------------------------

    def _log(self, name: str, value: object) -> None:
        self._draws.append((name, value))

    def _pair(self, rng: SepSeededRng, idx: int, a: str, b: str) -> PairDraw:
        kinds = (a, b)
        carrier = CMD_ENGINE_SHRED if "pcrc" in kinds else CMD_HW_VER
        crc_xor = rng.randrange(1, 0x100) if "hdr_crc" in kinds else 0
        seq_delta = rng.randrange(1, 0x100) if "seq" in kinds else 0
        bad_cmd = rng.choice(INVALID_CMD_IDS) if "cmd_id" in kinds else 0
        flip_bit = rng.randrange(32) if "pcrc" in kinds else 0
        e_words: tuple[int, ...] = ()
        if "len_self" in kinds:
            lo = 2 if carrier == CMD_ENGINE_SHRED else 1
            e_words = _words(rng, rng.randrange(lo, 0x100))
        d_extra: tuple[int, ...] = ()
        d_plen = 0
        if "len_wire" in kinds:
            if carrier == CMD_HW_VER:
                d_extra = _words(rng, rng.randrange(0, 7))
                wire = 1 + len(d_extra)
            else:
                wire = frame_len(1)
            while True:
                d_plen = rng.randrange(0, 0x100)
                if frame_len(d_plen) != wire:
                    break
        d = PairDraw(a, b, carrier, crc_xor, seq_delta, bad_cmd, flip_bit, d_extra, d_plen, e_words)
        tag = f"pair{idx}_{a}_{b}"
        self._log(f"{tag}_carrier", f"0x{carrier:02x}")
        for name, val, used in (
            ("crc_xor", crc_xor, "hdr_crc"),
            ("seq_delta", seq_delta, "seq"),
            ("bad_cmd", bad_cmd, "cmd_id"),
            ("flip_bit", flip_bit, "pcrc"),
        ):
            if used in kinds:
                self._log(f"{tag}_{name}", val)
        if "len_self" in kinds:
            self._log(f"{tag}_plen_e", len(e_words))
            self._log(f"{tag}_e_words", e_words)
        if "len_wire" in kinds:
            self._log(f"{tag}_d_plen", d_plen)
            self._log(f"{tag}_d_extra", d_extra)
        return d

    def _vault(self, rng: SepSeededRng, idx: int, d: PairDraw) -> VaultDraw:
        cmd = rng.choice(VAULT_CMDS)
        if cmd == CMD_KEY_GENERATE:
            payload = (rng.randrange(1, 17) - 1, _dest_with(rng, DEST_AES))
        else:
            key = _key(rng, rng.randrange(8, 17))
            payload = (len(key) - 1, _dest_with(rng, DEST_AES), *key)
        d_plen = 0
        if "len_wire" in d.kinds:
            while True:
                d_plen = rng.randrange(0, 0x100)
                if frame_len(d_plen) != frame_len(len(payload)):
                    break
        tag = f"pair{idx}_vault"
        self._log(f"{tag}_cmd", f"0x{cmd:02x}")
        self._log(f"{tag}_payload", payload)
        if "len_wire" in d.kinds:
            self._log(f"{tag}_d_plen", d_plen)
        return VaultDraw(cmd, payload, d_plen)

    def _gate(self, rng: SepSeededRng, source: str) -> GateDraw:
        gen_words = rng.randrange(1, 17)
        gen_dest = _dest_with(rng, DEST_AES)
        load_key = _key(rng, rng.randrange(8, 17))
        load_dest = _dest_with(rng, DEST_AES)
        h_key = _key(rng, 8)
        h_dest = _dest_with(rng, DEST_AES)
        abr_dest = rng.randrange(1, 0x100)
        order = list(ADMITTED + GATED)
        rng.shuffle(order)
        vf_crc_xor = rng.randrange(1, 0x100)
        vf_flip_bit = rng.randrange(32)
        ack_delay = rng.choice(self.ACK_DELAYS)
        oflow = _words(rng, RX_BUFFER_WORDS) if source == "rx_oflow" else ()
        g = GateDraw(
            source,
            gen_words,
            gen_dest,
            load_key,
            load_dest,
            h_key,
            h_dest,
            abr_dest,
            tuple(order),
            vf_crc_xor,
            vf_flip_bit,
            ack_delay,
            oflow,
        )
        tag = f"gate_{source}"
        for name in (
            "gen_words",
            "gen_dest",
            "load_key",
            "load_dest",
            "h_key",
            "h_dest",
            "abr_dest",
            "order",
            "vf_crc_xor",
            "vf_flip_bit",
            "ack_delay",
        ):
            self._log(f"{tag}_{name}", getattr(g, name))
        if oflow:
            self._log(f"{tag}_oflow_words", oflow)
        return g

    def draw_lines(self) -> list[str]:
        """One ``DRAW <name>=<value>`` line for every drawn value."""
        return [f"DRAW {name}={_fmt(value)}" for name, value in self._draws]
