# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Host-side Key Manager (KM) mailbox command driver.

Implements the SEP<->KM mailbox wire protocol of the KM ROM firmware
(`hw/ip/key_manager/approm/prod`, `rom_main`): sends framed commands and parses
the responses.

Frame format (32-bit words, little-endian on the wire):
  header = {crc8[31:24], payload_len[23:16], cmd_id[15:8], seq_num[7:0]}
    crc8     = CRC-8/ROHC over the 3 header bytes [seq_num, cmd_id, payload_len]
  payload  = payload_len data words (0..255)
  crc32c   = CRC-32C over the payload bytes (only present when payload_len > 0)
The separator bit is applied to the LAST written word (write WRITE_SEPARATOR=1
immediately before writing that word). A response is read word-by-word until the
STATUS OUTBOUND_SEPARATOR bit marks the final word.
"""

from __future__ import annotations

from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles
from env.sep_axi_agent import SepAxiOp
from env.sep_spec_tables import agg_from_pic
from sep_reg_meta import KM_MAILBOX_SEP, sym

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq

# --- mailbox register map (SEP/host side) ---------------------------------
KM_MBOX_BASE = sym("KM_MAILBOX_SEP_REG_MAP_BASE_ADDR")
# Offsets from the generated map, not literals: a register-flow rename or a
# moved register then surfaces as an import-time error instead of a silently
# stale constant that reads or writes the wrong port.
KM_MBOX_WRITE_DATA = sym("KM_MAILBOX_SEP_SEP_WRITE_DATA_REG_OFFSET")
KM_MBOX_WRITE_SEPARATOR = sym("KM_MAILBOX_SEP_SEP_WRITE_SEPARATOR_REG_OFFSET")
KM_MBOX_READ_DATA = sym("KM_MAILBOX_SEP_SEP_READ_DATA_REG_OFFSET")
KM_MBOX_STATUS = sym("KM_MAILBOX_SEP_SEP_STATUS_REG_OFFSET")
KM_MBOX_IRQ_STATUS = sym("KM_MAILBOX_SEP_SEP_IRQ_STATUS_REG_OFFSET")
KM_MBOX_IRQ_ENABLE = sym("KM_MAILBOX_SEP_SEP_IRQ_ENABLE_REG_OFFSET")
KM_MBOX_CTRL = sym("KM_MAILBOX_SEP_SEP_CTRL_REG_OFFSET")
# Byte size of the SEP-side window. SEP_CTRL is its last register, so the
# first offset past the window is the upper word of a 64-bit beat at SEP_CTRL.
KM_MBOX_SIZE = sym("KM_MAILBOX_SEP_REG_MAP_SIZE")

# SEP_STATUS bit positions, from the generated export like the offsets above.
# km_mailbox_sep.rdl declares SEP_STATUS with the `status_reg` typedef, so the
# emitted name is KM_MAILBOX_SEP_STATUS_REG_*; sep_reg_meta._TYPE_ALIAS bridges
# that. A field that moves in the RDL moves these with it.
_KM_MBOX = KM_MAILBOX_SEP.field_lsb
KM_STATUS_INBOUND_EMPTY = _KM_MBOX("SEP_STATUS", "inbound_empty")
KM_STATUS_INBOUND_FULL = _KM_MBOX("SEP_STATUS", "inbound_full")
KM_STATUS_OUTBOUND_EMPTY = _KM_MBOX("SEP_STATUS", "outbound_empty")
KM_STATUS_OUTBOUND_FULL = _KM_MBOX("SEP_STATUS", "outbound_full")
KM_STATUS_INBOUND_DEPTH_LSB = _KM_MBOX("SEP_STATUS", "inbound_depth")
KM_STATUS_OUTBOUND_DEPTH_LSB = _KM_MBOX("SEP_STATUS", "outbound_depth")
KM_STATUS_INBOUND_DEPTH_MASK = (1 << KM_MAILBOX_SEP.field_width("SEP_STATUS", "inbound_depth")) - 1
KM_STATUS_OUTBOUND_DEPTH_MASK = (
    1 << KM_MAILBOX_SEP.field_width("SEP_STATUS", "outbound_depth")
) - 1
KM_STATUS_INBOUND_OVERFLOW = _KM_MBOX("SEP_STATUS", "inbound_overflow")
KM_STATUS_LOW_MASK = (1 << KM_STATUS_INBOUND_OVERFLOW) - 1
KM_STATUS_OUTBOUND_OVERFLOW = _KM_MBOX("SEP_STATUS", "outbound_overflow")
KM_STATUS_INBOUND_UNDERFLOW = _KM_MBOX("SEP_STATUS", "inbound_underflow")
KM_STATUS_OUTBOUND_UNDERFLOW = _KM_MBOX("SEP_STATUS", "outbound_underflow")
KM_STATUS_INBOUND_SEPARATOR = _KM_MBOX("SEP_STATUS", "inbound_separator")
KM_STATUS_OUTBOUND_SEPARATOR = _KM_MBOX("SEP_STATUS", "outbound_separator")

# SEP_IRQ_STATUS / SEP_IRQ_ENABLE bit positions, from the generated export.
KM_IRQ_OUTBOUND_DATA_AVAIL = _KM_MBOX("SEP_IRQ_STATUS", "outbound_read_data_avail")
KM_IRQ_INBOUND_SPACE_AVAIL = _KM_MBOX("SEP_IRQ_STATUS", "inbound_write_space_avail")
KM_IRQ_INBOUND_OVERFLOW = _KM_MBOX("SEP_IRQ_STATUS", "inbound_overflow")
KM_IRQ_OUTBOUND_UNDERFLOW = _KM_MBOX("SEP_IRQ_STATUS", "outbound_underflow")
KM_IRQ_FLUSHED_BY_KM = _KM_MBOX("SEP_IRQ_STATUS", "flushed_by_km")
KM_IRQ_EN_OUTBOUND_DATA_AVAIL = _KM_MBOX("SEP_IRQ_ENABLE", "outbound_read_data_avail_en")
KM_IRQ_EN_INBOUND_SPACE_AVAIL = _KM_MBOX("SEP_IRQ_ENABLE", "inbound_write_space_avail_en")
KM_IRQ_EN_INBOUND_OVERFLOW = _KM_MBOX("SEP_IRQ_ENABLE", "inbound_overflow_en")
KM_IRQ_EN_OUTBOUND_UNDERFLOW = _KM_MBOX("SEP_IRQ_ENABLE", "outbound_underflow_en")
KM_IRQ_EN_FLUSHED_BY_KM = _KM_MBOX("SEP_IRQ_ENABLE", "flushed_by_km_en")

KM_MBOX_IRQ_AGG = agg_from_pic("KM mailbox IRQ")

RESP_OKAY = 0
RESP_SLVERR = 2
RESP_DECERR = 3

# SEP_CTRL bit positions, from the generated export.
KM_CTRL_INBOUND_OVERFLOW_RESP = _KM_MBOX("SEP_CTRL", "inbound_overflow_resp")
KM_CTRL_OUTBOUND_UNDERFLOW_RESP = _KM_MBOX("SEP_CTRL", "outbound_underflow_resp")
KM_CTRL_FLUSH = _KM_MBOX("SEP_CTRL", "flush")

# Both FIFOs are 16 words deep. hw/ip/key_manager/doc/architecture.adoc
# (mailbox) gives the inbound and outbound FIFOs a "minimum depth 16 words
# each"; this DV-owned constant takes that minimum as the depth the full,
# space-available and overflow goldens expect.
KM_MBOX_DEPTH = 16

# --- commands / responses / destinations ----------------------------------
# rom_defs.h rom_km_cmd_id_t / rom_km_resp_id_t.
KM_CMD_HW_VER = 0x00
KM_CMD_ROM_VER = 0x01
KM_CMD_SRAM_VER = 0x02
KM_CMD_STAT = 0x03
KM_CMD_RECOV_ACK = 0x04
KM_CMD_EXEC_ROM = 0x10
KM_CMD_SRAM_LOAD_EXEC = 0x11
KM_CMD_SRAM_EXEC = 0x12
KM_CMD_KEY_GENERATE = 0x22
KM_CMD_KEY_REVOKE = 0x23
KM_CMD_KEY_TRANSFER = 0x24
KM_CMD_ENGINE_SHRED = 0x25
KM_CMD_KEY_LOAD = 0x26
KM_CMD_ABR_SK_TRANSFER = 0x27
KM_CMD_OTP_READ_LOCK_COLD = 0x28
KM_RESP_CMD = 0x00
KM_RESP_KM_READY = 0x55
# Unsolicited: the firmware posts this when Adams Bridge has written an ML-KEM
# shared key into the sideload CSR and the block's KEY_VALID latched. It is the
# only observation of the shim's interrupt path from the host side.
KM_RESP_ABR_SHARED_KEY_READY = 0x56
KM_RESP_RECOVERABLE_FAULT = 0xFE
KM_RESP_UNRECOVERABLE_FAULT = 0xFF

# Return codes (signed int8 in the RESP_CMD payload).
KM_RC_SUCCESS = 0
KM_RC_FAILURE = -1
KM_RC_HEADER_CRC = -2
KM_RC_CMD_NOSEQ = -3
KM_RC_INVALID_CMD = -4
KM_RC_INVALID_LEN = -5
KM_RC_PAYLOAD_CRC = -6
KM_RC_INVALID_ARG = -7

# The command-ID space is sparse: 0x00-0x04, 0x10-0x12 and 0x22-0x28 are the
# only defined opcodes, so every other ID must come back KM_RC_INVALID_CMD.
KM_VALID_CMD_IDS = (
    frozenset(range(0x00, 0x05)) | frozenset(range(0x10, 0x13)) | frozenset(range(0x22, 0x29))
)

# The null handle is reserved and never allocated, so it is always a legal
# stand-in for "a handle the key registry does not hold".
KM_KEY_HANDLE_NULL = 0x00

# Destination bitmask (`rom_defs.h` rom_km_dest_bits_t /
# `hw/ip/key_manager/doc/firmware.adoc` DEST_VALID): bit0 HMAC, bit1 KMAC,
# bit2 AES, bit3 OTBN, bit4 ABR ML-DSA seed, bits 5-7 ABR ML-KEM.
KM_DEST_HMAC = 0x01
KM_DEST_KMAC = 0x02
KM_DEST_AES = 0x04
KM_DEST_OTBN = 0x08
KM_DEST_ABR_MLDSA_SEED = 0x10
KM_DEST_ABR_MLKEM_SEED_D = 0x20
KM_DEST_ABR_MLKEM_SEED_Z = 0x40
KM_DEST_ABR_MLKEM_MSG = 0x80


def _hw_root() -> Path:
    return Path(__file__).resolve().parents[5]


def _km_csr_version_reset() -> int:
    import importlib.util

    reg_py = _hw_root() / "ip/key_manager/regs/gen/py/key_manager_reg.py"
    spec = importlib.util.spec_from_file_location("key_manager_reg", reg_py)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {reg_py}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return int(mod.KM_CSR_VERSION_REG_REG_DEFAULT)


# KMCSR VERSION reset from the RDL: patch[7:0], minor[15:8], major[23:16].
KM_HW_VER_1_0_0 = _km_csr_version_reset()


def crc8_rohc(data: bytes) -> int:
    """CRC-8/ROHC (init 0xFF, reflected poly 0xE0, xorout 0x00)."""
    crc = 0xFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xE0 if (crc & 1) else (crc >> 1)
    return crc & 0xFF


def crc32c(data: bytes) -> int:
    """CRC-32C / Castagnoli (init 0xFFFFFFFF, reflected poly 0x82F63B78,
    xorout 0xFFFFFFFF)."""
    crc = 0xFFFF_FFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0x82F6_3B78 if (crc & 1) else (crc >> 1)
    return (crc ^ 0xFFFF_FFFF) & 0xFFFF_FFFF


# Self-test the CRCs against the firmware's documented check vectors at import,
# so a transcription error in the polynomial/reflection fails loudly here rather
# than as a silent KM RC_HEADER_CRC/RC_PAYLOAD_CRC rejection deep in a sim.
assert crc8_rohc(b"123456789") == 0xD0, "CRC-8/ROHC self-test failed"
assert crc32c(b"123456789") == 0xE306_9283, "CRC-32C self-test failed"


def _payload_bytes(words: list[int]) -> bytes:
    return b"".join((w & 0xFFFF_FFFF).to_bytes(4, "little") for w in words)


def build_header(cmd_id: int, seq_num: int, payload_len: int) -> int:
    crc = crc8_rohc(bytes([seq_num & 0xFF, cmd_id & 0xFF, payload_len & 0xFF]))
    return (
        ((crc & 0xFF) << 24)
        | ((payload_len & 0xFF) << 16)
        | ((cmd_id & 0xFF) << 8)
        | (seq_num & 0xFF)
    )


class SepKmMailbox:
    """Drives the KM mailbox over the SEP AXI agent.

    The test owns one instance (``self.km = SepKmMailbox(self)``) and calls the
    high-level command methods. ``seq_num`` is tracked here: incremented per
    command, and it must match the firmware's expected sequence counter.
    """

    def __init__(self, test, *, base: int = KM_MBOX_BASE, logger=None) -> None:
        self.test = test
        self.base = base
        self.log = logger if logger is not None else test.logger
        self.seq_num = 0  # next outbound command sequence number
        self._resp_seq = 0  # next expected response sequence; the firmware bumps
        # rom_resp_seq_num on EVERY frame, incl. boot RESP_KM_READY

    def reset_host_seq(self) -> None:
        """Resynchronize host counters with a KM that just reset its own.

        ``rom_boot_init`` and the mailbox ISR flush path both zero
        ``rom_cmd_seq_num`` / ``rom_resp_seq_num``. After a warm reset or a
        SEP-initiated flush the next command and the next response are
        sequence 0; leaving the host counters where they were produces a
        false ``RC_CMD_NOSEQ``.
        """
        self.seq_num = 0
        self._resp_seq = 0

    # --- raw register access ----------------------------------------------
    async def _wr(self, offset: int, data: int) -> None:
        seq = SepAxiAccessSeq("km_mbox_wr", op=SepAxiOp.WRITE, addr=self.base + offset, wdata=data)
        await self.test.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(f"KM mailbox write @0x{self.base + offset:08x} not OKAY")

    async def _rd(self, offset: int) -> int:
        seq = SepAxiAccessSeq("km_mbox_rd", op=SepAxiOp.READ, addr=self.base + offset)
        await self.test.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(f"KM mailbox read @0x{self.base + offset:08x} not OKAY")
        return seq.rdata

    async def _status(self) -> int:
        return await self._rd(KM_MBOX_STATUS)

    # --- framing ----------------------------------------------------------
    async def send_command(self, cmd_id: int, payload_words: list[int]) -> int:
        """Frame and write one command (header + payload + CRC32C), applying the
        separator to the final word, then bump the sequence number. Returns the
        command sequence number used (the firmware echoes it in the RESP_CMD)."""
        sent_seq = self.seq_num
        words = self.build_frame(cmd_id, sent_seq, payload_words)
        await self._post_words(words)
        self.seq_num = (self.seq_num + 1) & 0xFF
        return sent_seq

    def build_frame(self, cmd_id: int, seq_num: int, payload_words: list[int]) -> list[int]:
        """Build a well-formed frame: header, payload, and the payload CRC."""
        payload_len = len(payload_words)
        words = [build_header(cmd_id, seq_num, payload_len)]
        words.extend(w & 0xFFFF_FFFF for w in payload_words)
        if payload_len > 0:
            words.append(crc32c(_payload_bytes(payload_words)))
        return words

    async def _post_words(self, words: list[int]) -> None:
        """Write one frame, applying the separator to its final word."""
        for i, word in enumerate(words):
            if i == len(words) - 1:
                await self._wr(KM_MBOX_WRITE_SEPARATOR, 1)
            await self._wr(KM_MBOX_WRITE_DATA, word)

    async def recv_frame(self, *, timeout: int = 200_000, poll_cycles: int = 20) -> list[int]:
        """Read a full response frame (words up to and including the one whose
        read leaves STATUS.OUTBOUND_SEPARATOR set)."""
        words: list[int] = []
        for _ in range(32):
            if not await self._wait_outbound_data(timeout=timeout, poll_cycles=poll_cycles):
                raise AssertionError("timeout waiting for a KM response word")
            words.append(await self._rd(KM_MBOX_READ_DATA))
            if await self._status() & (1 << KM_STATUS_OUTBOUND_SEPARATOR):
                self._validate_frame(words)
                return words
        raise AssertionError("KM response exceeded 32 words without a separator")

    def _validate_frame(self, words: list[int]) -> None:
        """Integrity-check a received frame against the KM wire protocol: header
        CRC-8, declared payload length, payload CRC-32C, and the monotonic response
        sequence number. A stale/misframed frame fails here instead of being
        silently trusted by a downstream value check."""
        hdr = words[0]
        resp_seq = hdr & 0xFF
        resp_id = (hdr >> 8) & 0xFF
        payload_len = (hdr >> 16) & 0xFF
        hdr_crc = (hdr >> 24) & 0xFF
        exp_hdr_crc = crc8_rohc(bytes([resp_seq, resp_id, payload_len]))
        if hdr_crc != exp_hdr_crc:
            raise AssertionError(
                f"KM resp header CRC8 mismatch: got 0x{hdr_crc:02x} exp 0x{exp_hdr_crc:02x} "
                f"(hdr=0x{hdr:08x})"
            )
        # Frame = header + payload_len data words + (CRC-32C word iff payload_len>0).
        exp_words = 1 + payload_len + (1 if payload_len > 0 else 0)
        if len(words) != exp_words:
            raise AssertionError(
                f"KM resp length mismatch: separator after {len(words)} words but header "
                f"payload_len={payload_len} implies {exp_words} (frame={[hex(w) for w in words]})"
            )
        if payload_len > 0:
            payload = words[1 : 1 + payload_len]
            exp_c32 = crc32c(_payload_bytes(payload))
            got_c32 = words[1 + payload_len]
            if got_c32 != exp_c32:
                raise AssertionError(
                    f"KM resp payload CRC32C mismatch: got 0x{got_c32:08x} exp 0x{exp_c32:08x}"
                )
        if resp_seq != self._resp_seq:
            raise AssertionError(
                f"KM resp sequence mismatch: got {resp_seq} exp {self._resp_seq} "
                f"(resp_id=0x{resp_id:02x})"
            )
        self._resp_seq = (self._resp_seq + 1) & 0xFF

    async def _wait_outbound_data(self, *, timeout: int, poll_cycles: int) -> bool:
        """Poll STATUS until the outbound FIFO has a word (OUTBOUND_EMPTY clear)."""
        for i in range(timeout):
            if not (await self._status() & (1 << KM_STATUS_OUTBOUND_EMPTY)):
                return True
            if i and i % 1000 == 0:
                self.log.info("KM mailbox wait: poll %d (no outbound data yet)", i)
            await ClockCycles(cocotb.top.clk_i, poll_cycles)
        return False

    async def recv_resp_cmd(
        self,
        expected_cmd_id: int,
        expected_cmd_seq: int,
        *,
        timeout: int = 200_000,
        require_arg: bool = False,
    ) -> tuple[int, int]:
        """Receive and fully validate a RESP_CMD for a command we sent, returning
        (return_code_signed, return_arg). recv_frame() has already checked header/
        payload CRCs and the response sequence; here we additionally require the
        frame to be a RESP_CMD that echoes our command's sequence and id (RESP_CMD
        payload = [cmd_seq, cmd_id, rc, arg?], per rom_msg_rx.c send_resp_cmd).

        RETURN_ARG is optional on the wire and reads as 0 when absent. A caller
        whose command the KM firmware specification defines with a return
        argument passes ``require_arg=True``, so a response without one fails
        here instead of reading as a zero argument."""
        words = await self.recv_frame(timeout=timeout)
        resp_id = (words[0] >> 8) & 0xFF
        payload_len = (words[0] >> 16) & 0xFF
        if resp_id != KM_RESP_CMD:
            raise AssertionError(
                f"expected RESP_CMD (0x{KM_RESP_CMD:02x}) for cmd 0x{expected_cmd_id:02x}, "
                f"got 0x{resp_id:02x} (frame={[hex(w) for w in words]})"
            )
        if payload_len < 3:
            raise AssertionError(f"RESP_CMD payload_len {payload_len} < 3 (cmd_seq,cmd_id,rc)")
        echo_seq = words[1] & 0xFF
        echo_id = words[2] & 0xFF
        if echo_seq != (expected_cmd_seq & 0xFF):
            raise AssertionError(
                f"RESP_CMD echoed cmd_seq {echo_seq} != sent {expected_cmd_seq & 0xFF}"
            )
        if echo_id != (expected_cmd_id & 0xFF):
            raise AssertionError(
                f"RESP_CMD echoed cmd_id 0x{echo_id:02x} != sent 0x{expected_cmd_id & 0xFF:02x}"
            )
        rc_raw = words[3] & 0xFF
        return_code = rc_raw - 256 if rc_raw >= 128 else rc_raw  # signed int8
        has_arg = payload_len >= 4 and len(words) >= 5
        if require_arg and not has_arg:
            raise AssertionError(
                f"RESP_CMD for cmd 0x{expected_cmd_id:02x} carries no RETURN_ARG "
                f"(payload_len {payload_len}); this command's response defines one"
            )
        return_arg = words[4] if has_arg else 0
        return return_code, return_arg

    # --- high-level commands ----------------------------------------------
    def _km_boot_evidence(self) -> str:
        """Snapshot the observables that say WHERE a KM boot stalled.

        A bare "no RESP_KM_READY" is unattributed: it cannot distinguish a KM held
        in reset, a KM fetching from an empty/!loaded ROM, and a KM that booted but
        never posted. The ROM/SRAM request counters separate exactly those cases:
          rom_req == 0            -> the KM CPU never fetched (held in reset, or
                                     unclocked) -- look at SW_RESET_N bit0.
          rom_req > 0, sram_wr==0 -> fetching but not progressing (bad image /
                                     immediate fault on the first instructions).
          both > 0                -> firmware ran; the stall is later than boot.
        """
        dut = cocotb.top

        def _rd(name):
            try:
                return int(getattr(dut, name).value)
            except Exception:
                return None

        rom = _rd("km_rom_req_count_o")
        sram_wr = _rd("km_sram_write_count_o")
        sram_rq = _rd("km_sram_req_count_o")
        # The KM ROM's rom_drbg_init() spins on STATUS.drbg_ready, and the RTL ties
        # that bit directly to the EDN->KM stream tvalid
        # (km_drbg_sampler.sv: hwif_in.STATUS.drbg_ready.next = tvalid). So a KM that
        # fetches but never announces is usually parked in that spin, and these
        # signals say which half of the handshake is missing.
        tvalid = _rd("km_entropy_tvalid_o")
        tready = _rd("km_entropy_tready_o")
        seed_v = _rd("drbg_seed_valid_o")
        genbits = _rd("drbg_genbits_vld_o")
        parts = [
            f"km_rom_req_count={rom}",
            f"km_sram_write_count={sram_wr}",
            f"km_sram_req_count={sram_rq}",
            f"km_entropy_tvalid={tvalid}",
            f"km_entropy_tready={tready}",
            f"drbg_seed_valid={seed_v}",
            f"drbg_genbits_vld={genbits}",
        ]
        if rom == 0:
            parts.append(
                "=> KM CPU NEVER FETCHED: it is still in reset "
                "(SW_RESET_N bit0) or unclocked, so no ROM image can help"
            )
        elif rom and not sram_wr:
            parts.append(
                "=> KM fetched but never wrote SRAM: suspect the loaded "
                "ROM image (+km_rom_hex) or an early fault"
            )
        elif rom and not tvalid:
            parts.append(
                "=> KM is running but EDN never presented a word on its lane "
                "(tvalid=0): rom_drbg_init() is spinning on STATUS.drbg_ready, "
                "which mirrors this tvalid. The stall is EDN->KM routing, NOT "
                "the KM firmware and NOT CFG.TIMEOUT"
            )
        return " ".join(parts)

    async def wait_km_ready(self, *, timeout: int = 8_000, poll_cycles: int = 50) -> None:
        """Wait for the KM firmware's unsolicited RESP_KM_READY boot announcement.

        Bounded and attributed: on timeout this reports the KM ROM/SRAM activity
        counters so the failure names which stage did not retire, rather than
        silently polling an empty mailbox for milliseconds of sim time.

        The 8000-poll budget is 400k core cycles: generous for a healthy boot, but
        bounded so a KM that never boots fails here rather than at the run timeout.
        """
        try:
            words = await self.recv_frame(timeout=timeout, poll_cycles=poll_cycles)
        except AssertionError as exc:
            raise AssertionError(
                f"KM never announced RESP_KM_READY ({exc}). {self._km_boot_evidence()}"
            ) from exc
        resp_id = (words[0] >> 8) & 0xFF
        if resp_id != KM_RESP_KM_READY:
            raise AssertionError(
                f"expected RESP_KM_READY (0x{KM_RESP_KM_READY:02x}), got 0x{resp_id:02x} "
                f"(frame={[hex(w) for w in words]})"
            )
        self.log.info("KM firmware booted: RESP_KM_READY received (%s)", self._km_boot_evidence())

    async def key_generate(self, *, dest: int, req_size: int, timeout: int = 200_000) -> int:
        """CMD_KEY_GENERATE; returns the (nonzero) key handle. ``req_size`` is
        word_count-1 (11 -> 12 words / 384b)."""
        seq = await self.send_command(
            KM_CMD_KEY_GENERATE, [req_size & 0xFFFF_FFFF, dest & 0xFFFF_FFFF]
        )
        rc, arg = await self.recv_resp_cmd(KM_CMD_KEY_GENERATE, seq, timeout=timeout)
        if rc != KM_RC_SUCCESS:
            raise AssertionError(f"CMD_KEY_GENERATE failed rc={rc}")
        handle = arg & 0xFF
        if handle == 0:
            raise AssertionError("CMD_KEY_GENERATE returned a zero handle")
        await self.check_outbound_empty("POST-KEY-GENERATE")
        self.log.info("KM CMD_KEY_GENERATE ok: dest=0x%02x handle=0x%02x", dest, handle)
        return handle

    async def key_load(self, *, key_words: list[int], dest: int, timeout: int = 200_000) -> int:
        """CMD_KEY_LOAD: provision a KNOWN key value into a handle (frontdoor, no
        backdoor needed to know the key). Payload = [KEY_SIZE-1, DEST_VALID,
        key_words...]. Returns the (nonzero) key handle."""
        payload = [len(key_words) - 1, dest & 0xFFFF_FFFF] + [w & 0xFFFF_FFFF for w in key_words]
        seq = await self.send_command(KM_CMD_KEY_LOAD, payload)
        rc, arg = await self.recv_resp_cmd(KM_CMD_KEY_LOAD, seq, timeout=timeout)
        if rc != KM_RC_SUCCESS:
            raise AssertionError(f"CMD_KEY_LOAD failed rc={rc}")
        handle = arg & 0xFF
        if handle == 0:
            raise AssertionError("CMD_KEY_LOAD returned a zero handle")
        await self.check_outbound_empty("POST-KEY-LOAD")
        self.log.info("KM CMD_KEY_LOAD ok: dest=0x%02x handle=0x%02x", dest, handle)
        return handle

    async def key_transfer(
        self, *, handle: int, dest: int, timeout: int = 200_000
    ) -> tuple[int, int]:
        """CMD_KEY_TRANSFER; returns (return_code, return_arg).

        The argument is returned rather than dropped so a caller can check the
        echo, as it does for generate, revoke and shred: on success it packs
        the handle and the destination mask."""
        seq = await self.send_command(
            KM_CMD_KEY_TRANSFER, [handle & 0xFFFF_FFFF, dest & 0xFFFF_FFFF]
        )
        rc, arg = await self.recv_resp_cmd(KM_CMD_KEY_TRANSFER, seq, timeout=timeout)
        await self.check_outbound_empty("POST-KEY-TRANSFER")
        self.log.info(
            "KM CMD_KEY_TRANSFER: handle=0x%02x dest=0x%02x rc=%d arg=0x%08x",
            handle,
            dest,
            rc,
            arg,
        )
        return rc, arg

    async def abr_sk_transfer(self, *, dest: int, timeout: int = 200_000) -> tuple[int, int]:
        """CMD_ABR_SK_TRANSFER; returns (return_code, return_arg).

        Consumes the ML-KEM shared key Adams Bridge posted into the sideload
        CSR and stores it in the KPV. The firmware rejects the command while
        that block's KEY_VALID is clear, so the reject leg is the negative
        control for the writeback path and the raw result is returned rather
        than raised on."""
        seq = await self.send_command(KM_CMD_ABR_SK_TRANSFER, [dest & 0xFFFF_FFFF])
        rc, arg = await self.recv_resp_cmd(KM_CMD_ABR_SK_TRANSFER, seq, timeout=timeout)
        await self.check_outbound_empty("POST-ABR-SK-TRANSFER")
        self.log.info("KM CMD_ABR_SK_TRANSFER: dest=0x%02x rc=%d arg=0x%08x", dest, rc, arg)
        return rc, arg

    async def check_outbound_empty(self, tag: str) -> None:
        status = await self._status()
        if not (status & (1 << KM_STATUS_OUTBOUND_EMPTY)):
            raise AssertionError(f"[{tag}] KM mailbox outbound FIFO not empty: 0x{status:08x}")

    async def key_revoke(self, *, handle: int, timeout: int = 200_000) -> tuple[int, int]:
        """CMD_KEY_REVOKE; returns (return_code, return_arg).

        Revoke erases every KPV slot the key spans and destroys the registry
        entry, so a later CMD_KEY_TRANSFER on the same handle must fail the
        lookup. Returns the raw result rather than raising, because the reject
        legs are the point of the negative cases."""
        seq = await self.send_command(KM_CMD_KEY_REVOKE, [handle & 0xFFFF_FFFF])
        rc, arg = await self.recv_resp_cmd(KM_CMD_KEY_REVOKE, seq, timeout=timeout)
        await self.check_outbound_empty("POST-KEY-REVOKE")
        self.log.info("KM CMD_KEY_REVOKE: handle=0x%02x rc=%d arg=0x%08x", handle, rc, arg)
        return rc, arg

    async def engine_shred(self, *, dest: int, timeout: int = 200_000) -> tuple[int, int]:
        """CMD_ENGINE_SHRED; returns (return_code, return_arg).

        Clears KEY_VALID on every selected engine and overwrites both key
        shares with fresh random data, so a consume attempted afterwards has
        no valid key to use."""
        seq = await self.send_command(KM_CMD_ENGINE_SHRED, [dest & 0xFFFF_FFFF])
        rc, arg = await self.recv_resp_cmd(KM_CMD_ENGINE_SHRED, seq, timeout=timeout)
        await self.check_outbound_empty("POST-ENGINE-SHRED")
        self.log.info("KM CMD_ENGINE_SHRED: dest=0x%02x rc=%d arg=0x%08x", dest, rc, arg)
        return rc, arg

    async def flush(self, *, timeout: int = 4_000) -> None:
        """Pulse SEP_CTRL.FLUSH and wait until the bit self-clears.

        While the KM is running this is the frontdoor that raises
        ``RFAULT_FLUSHED_BY_SEP``: the firmware ISR resets both sequence
        counters and posts ``RESP_RECOVERABLE_FAULT``. Call
        ``reset_host_seq`` before receiving that frame.
        """
        await self.write_ctrl(1 << KM_CTRL_FLUSH)
        for _ in range(timeout):
            if (await self.read_ctrl() & (1 << KM_CTRL_FLUSH)) == 0:
                return
            await ClockCycles(cocotb.top.clk_i, 20)
        raise AssertionError("KM mailbox CTRL.flush did not self-clear")

    async def recv_unsolicited(self, expected_id: int, *, timeout: int = 200_000) -> list[int]:
        """Receive one framed response that is not a RESP_CMD echo.

        Used for ``RESP_KM_READY``, ``RESP_RECOVERABLE_FAULT`` and
        ``RESP_UNRECOVERABLE_FAULT``. Frame integrity and the response
        sequence still apply; the caller is responsible for
        ``reset_host_seq`` when the KM has just zeroed its counters.
        """
        words = await self.recv_frame(timeout=timeout)
        resp_id = (words[0] >> 8) & 0xFF
        if resp_id != (expected_id & 0xFF):
            raise AssertionError(
                f"expected resp_id 0x{expected_id:02x}, got 0x{resp_id:02x} "
                f"(frame={[hex(w) for w in words]})"
            )
        return words

    async def post_raw_words(self, words: list[int]) -> None:
        """Write raw inbound words, separator on the last. Not a command frame."""
        await self._post_words(words)

    async def stat(self, *, timeout: int = 200_000) -> tuple[int, int]:
        """CMD_STAT; returns (return_code, return_arg).

        Used after a rejected command as a liveness-and-no-side-effect probe:
        a KM that answers STAT normally has stayed in its command loop rather
        than wedging or faulting on the rejected frame.

        The response must carry RETURN_ARG: hw/ip/key_manager/doc/firmware.adoc
        ("0x03 - CMD_STAT") defines it as the KM status word, so a missing
        argument is a failure rather than a status of 0."""
        seq = await self.send_command(KM_CMD_STAT, [])
        rc, arg = await self.recv_resp_cmd(KM_CMD_STAT, seq, timeout=timeout, require_arg=True)
        await self.check_outbound_empty("POST-STAT")
        return rc, arg

    async def send_raw_expect_rc(
        self, cmd_id: int, payload_words: list[int], *, timeout: int = 200_000
    ) -> tuple[int, int]:
        """Send an arbitrary (including undefined) command and return its
        (return_code, return_arg) without judging it.

        The frame itself stays well formed -- correct header CRC-8, correct
        declared length, correct payload CRC-32C -- so the KM rejects it on the
        command ID or the argument, not on framing."""
        seq = await self.send_command(cmd_id, payload_words)
        rc, arg = await self.recv_resp_cmd(cmd_id, seq, timeout=timeout)
        await self.check_outbound_empty(f"POST-RAW-0x{cmd_id:02x}")
        return rc, arg

    async def send_bad_header_crc(self, cmd_id: int, *, timeout: int = 200_000) -> tuple[int, int]:
        """Send a frame whose header CRC-8 is wrong; return (rc, arg).

        The KM rejects this before it validates the sequence number, so its
        expected sequence counter does NOT advance. This helper never
        increments the host counter either (it posts the frame directly), so
        the two stay aligned for later commands."""
        seq_used = self.seq_num
        words = self.build_frame(cmd_id, seq_used, [])
        words[0] ^= 1 << 24  # flip a bit inside the header CRC-8 field
        await self._post_words(words)
        rc, arg = await self.recv_resp_cmd(cmd_id, seq_used, timeout=timeout)
        await self.check_outbound_empty("POST-BAD-HEADER-CRC")
        return rc, arg

    async def send_bad_seq(self, cmd_id: int, *, timeout: int = 200_000) -> tuple[int, int]:
        """Send a well-formed frame carrying the wrong sequence number.

        Rejected at the sequence check, which is also before the counter
        advances, so the host counter is left where it was."""
        wrong = (self.seq_num + 7) & 0xFF
        await self._post_words(self.build_frame(cmd_id, wrong, []))
        rc, arg = await self.recv_resp_cmd(cmd_id, wrong, timeout=timeout)
        await self.check_outbound_empty("POST-BAD-SEQ")
        return rc, arg

    async def send_bad_payload_crc(
        self, cmd_id: int, payload_words: list[int], *, timeout: int = 200_000
    ) -> tuple[int, int]:
        """Send a frame whose payload CRC-32C is wrong; return (rc, arg).

        This one is rejected AFTER the sequence check, so the KM's counter has
        advanced and the host's must too -- the opposite of the two above."""
        sent_seq = self.seq_num
        words = self.build_frame(cmd_id, sent_seq, payload_words)
        words[-1] ^= 0x0000_0001
        await self._post_words(words)
        self.seq_num = (self.seq_num + 1) & 0xFF
        rc, arg = await self.recv_resp_cmd(cmd_id, sent_seq, timeout=timeout)
        await self.check_outbound_empty("POST-BAD-PAYLOAD-CRC")
        return rc, arg

    # --- raw register access, for grading the mailbox as a register surface ---
    async def read_status(self) -> int:
        return await self._rd32(KM_MBOX_STATUS)

    async def _wr32(self, offset: int, data: int) -> None:
        """32-bit write. A 64-bit beat at SEP_CTRL (offset 0x18) spans past
        the 0x1C mailbox window and the fabric refuses it."""
        seq = SepAxiAccessSeq(
            "km_mbox_wr32",
            op=SepAxiOp.WRITE,
            addr=self.base + offset,
            wdata=data,
            size=2,
        )
        await self.test.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(
                f"KM mailbox 32-bit write @0x{self.base + offset:08x} not OKAY "
                f"(resp={seq.resp_code})"
            )

    async def _rd32(self, offset: int) -> int:
        seq = SepAxiAccessSeq(
            "km_mbox_rd32",
            op=SepAxiOp.READ,
            addr=self.base + offset,
            size=2,
        )
        await self.test.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(
                f"KM mailbox 32-bit read @0x{self.base + offset:08x} not OKAY "
                f"(resp={seq.resp_code})"
            )
        return seq.rdata

    async def write_status(self, value: int) -> None:
        await self._wr32(KM_MBOX_STATUS, value)

    async def read_irq_status(self) -> int:
        return await self._rd32(KM_MBOX_IRQ_STATUS)

    async def write_irq_status(self, value: int) -> None:
        await self._wr32(KM_MBOX_IRQ_STATUS, value)

    async def read_irq_enable(self) -> int:
        return await self._rd32(KM_MBOX_IRQ_ENABLE)

    async def write_irq_enable(self, value: int) -> None:
        await self._wr32(KM_MBOX_IRQ_ENABLE, value)

    async def write_ctrl(self, value: int) -> None:
        await self._wr32(KM_MBOX_CTRL, value)

    async def read_ctrl(self) -> int:
        return await self._rd32(KM_MBOX_CTRL)

    async def write_ctrl_wide_raw(self, value: int) -> tuple[int, bool]:
        """One 64-bit write beat (AxSIZE=3, 8 bytes) at SEP_CTRL.

        The upper four bytes of this beat fall past the register file. Returns
        (resp_code, timed_out) so the caller can grade the single write
        response. expect_error tells the scoreboard a non-OKAY response is the
        contract.
        """
        seq = SepAxiAccessSeq(
            "km_mbox_ctrl_wr64",
            op=SepAxiOp.WRITE,
            addr=self.base + KM_MBOX_CTRL,
            wdata=value & 0xFFFF_FFFF_FFFF_FFFF,
            length=8,
            size=3,
            expect_error=True,
        )
        await self.test.start_seq(seq)
        return seq.resp_code, seq.timed_out

    async def read_data_raw(self, *, expect_error: bool = False) -> tuple[int, int]:
        """Read SEP_READ_DATA. Returns (resp_code, data).

        The underflow leg needs the response itself as evidence, so this cannot
        go through the raising helper. Pass expect_error when a non-OKAY
        response is the contract, or the environment scoreboard fails it.
        """
        seq = SepAxiAccessSeq(
            "km_mbox_rd_raw",
            op=SepAxiOp.READ,
            addr=self.base + KM_MBOX_READ_DATA,
            size=2,
            expect_error=expect_error,
        )
        await self.test.start_seq(seq)
        return seq.resp_code, seq.rdata

    async def write_data_raw(self, value: int, *, expect_error: bool = False) -> int:
        """Write SEP_WRITE_DATA. Returns resp_code."""
        seq = SepAxiAccessSeq(
            "km_mbox_wr_raw",
            op=SepAxiOp.WRITE,
            addr=self.base + KM_MBOX_WRITE_DATA,
            wdata=value,
            size=2,
            expect_error=expect_error,
        )
        await self.test.start_seq(seq)
        return seq.resp_code
