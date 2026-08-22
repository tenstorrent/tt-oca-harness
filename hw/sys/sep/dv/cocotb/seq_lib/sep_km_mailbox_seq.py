# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Host-side Key Manager (KM) mailbox command driver.

Reproduces the SEP<->KM mailbox wire protocol that the real KM ROM firmware
(`hw/ip/key_manager/dv/fw`, `rom_main`) implements, so an OSS cocotb test
can drive the KM the same way the reference suite `sep_subsystem_km_consume_base_seq` does:
send CMD_KEY_GENERATE / CMD_KEY_TRANSFER framed messages and parse the responses.

Frame format (32-bit words, little-endian on the wire):
  header = {crc8[31:24], payload_len[23:16], cmd_id[15:8], seq_num[7:0]}
    crc8     = CRC-8/ROHC over the 3 header bytes [seq_num, cmd_id, payload_len]
  payload  = payload_len data words (0..255)
  crc32c   = CRC-32C over the payload bytes (only present when payload_len > 0)
The separator bit is applied to the LAST written word (write WRITE_SEPARATOR=1
immediately before writing that word). A response is read word-by-word until the
STATUS OUTBOUND_SEPARATOR bit marks the final word.

All AXI accesses go through the SEP AXI agent via SepAxiAccessSeq.
"""

from __future__ import annotations

from sep_reg_meta import sym

import cocotb
from cocotb.triggers import ClockCycles

from env.sep_axi_agent import SepAxiOp
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq

# --- mailbox register map (SEP/host side) ---------------------------------
KM_MBOX_BASE = sym("KM_MAILBOX_SEP_REG_MAP_BASE_ADDR")
KM_MBOX_WRITE_DATA = 0x000
KM_MBOX_WRITE_SEPARATOR = 0x004
KM_MBOX_READ_DATA = 0x008
KM_MBOX_STATUS = 0x00C

# STATUS bit positions
KM_STATUS_OUTBOUND_EMPTY = 2
KM_STATUS_OUTBOUND_SEPARATOR = 25

# --- commands / responses / destinations ----------------------------------
KM_CMD_KEY_GENERATE = 0x22
KM_CMD_KEY_TRANSFER = 0x24
KM_CMD_KEY_LOAD = 0x26
KM_RESP_CMD = 0x00
KM_RESP_KM_READY = 0x55
KM_RC_SUCCESS = 0

# Destination bitmask (rom_defs.h / sep_km_types.sv): bit3 = OTBN
KM_DEST_HMAC = 0x01
KM_DEST_KMAC = 0x02
KM_DEST_AES = 0x04
KM_DEST_OTBN = 0x08


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
    return ((crc & 0xFF) << 24) | ((payload_len & 0xFF) << 16) | ((cmd_id & 0xFF) << 8) | (
        seq_num & 0xFF
    )


class SepKmMailbox:
    """Drives the KM mailbox over the SEP AXI agent.

    The test owns one instance (``self.km = SepKmMailbox(self)``) and calls the
    high-level command methods. ``seq_num`` is tracked here exactly like the reference suite
    base sequence (incremented per command, must match the firmware's expected
    sequence counter).
    """

    def __init__(self, test, *, base: int = KM_MBOX_BASE, logger=None) -> None:
        self.test = test
        self.base = base
        self.log = logger if logger is not None else test.logger
        self.seq_num = 0       # next outbound command sequence number
        self._resp_seq = 0     # next expected response sequence; the firmware bumps
                               # rom_resp_seq_num on EVERY frame, incl. boot RESP_KM_READY

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
        payload_len = len(payload_words)
        words = [build_header(cmd_id, sent_seq, payload_len)]
        words.extend(w & 0xFFFF_FFFF for w in payload_words)
        if payload_len > 0:
            words.append(crc32c(_payload_bytes(payload_words)))
        for i, word in enumerate(words):
            if i == len(words) - 1:
                await self._wr(KM_MBOX_WRITE_SEPARATOR, 1)
            await self._wr(KM_MBOX_WRITE_DATA, word)
        self.seq_num = (self.seq_num + 1) & 0xFF
        return sent_seq

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
            payload = words[1:1 + payload_len]
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
        self, expected_cmd_id: int, expected_cmd_seq: int, *, timeout: int = 200_000
    ) -> tuple[int, int]:
        """Receive and fully validate a RESP_CMD for a command we sent, returning
        (return_code_signed, return_arg). recv_frame() has already checked header/
        payload CRCs and the response sequence; here we additionally require the
        frame to be a RESP_CMD that echoes our command's sequence and id (RESP_CMD
        payload = [cmd_seq, cmd_id, rc, arg?], per rom_msg_rx.c send_resp_cmd)."""
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
        return_arg = words[4] if (payload_len >= 4 and len(words) >= 5) else 0
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
        parts = [f"km_rom_req_count={rom}", f"km_sram_write_count={sram_wr}",
                 f"km_sram_req_count={sram_rq}",
                 f"km_entropy_tvalid={tvalid}", f"km_entropy_tready={tready}",
                 f"drbg_seed_valid={seed_v}", f"drbg_genbits_vld={genbits}"]
        if rom == 0:
            parts.append("=> KM CPU NEVER FETCHED: it is still in reset "
                         "(SW_RESET_N bit0) or unclocked, so no ROM image can help")
        elif rom and not sram_wr:
            parts.append("=> KM fetched but never wrote SRAM: suspect the loaded "
                         "ROM image (+km_rom_hex) or an early fault")
        elif rom and not tvalid:
            parts.append("=> KM is running but EDN never presented a word on its lane "
                         "(tvalid=0): rom_drbg_init() is spinning on STATUS.drbg_ready, "
                         "which mirrors this tvalid. The stall is EDN->KM routing, NOT "
                         "the KM firmware and NOT CFG.TIMEOUT")
        return " ".join(parts)

    async def wait_km_ready(self, *, timeout: int = 8_000, poll_cycles: int = 50) -> None:
        """Wait for the KM firmware's unsolicited RESP_KM_READY boot announcement.

        Bounded and attributed: on timeout this reports the KM ROM/SRAM activity
        counters so the failure names which stage did not retire, rather than
        silently polling an empty mailbox for milliseconds of sim time.

        The 8000-poll budget is 400k core cycles (~460 us), roughly 1.5x the
        ~300 us the KM ROM needs to reach RESP_KM_READY in the reference subsystem tb.
        Generous for a healthy boot, but bounded enough that a KM which never
        boots fails in minutes instead of running the test to its 7200 s cap.
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
        self.log.info("KM firmware booted: RESP_KM_READY received (%s)",
                      self._km_boot_evidence())

    async def key_generate(self, *, dest: int, req_size: int, timeout: int = 200_000) -> int:
        """CMD_KEY_GENERATE; returns the (nonzero) key handle. ``req_size`` is
        word_count-1 (11 -> 12 words / 384b)."""
        seq = await self.send_command(KM_CMD_KEY_GENERATE, [req_size & 0xFFFF_FFFF, dest & 0xFFFF_FFFF])
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

    async def key_transfer(self, *, handle: int, dest: int, timeout: int = 200_000) -> int:
        """CMD_KEY_TRANSFER; returns the signed return code (0 = success)."""
        seq = await self.send_command(KM_CMD_KEY_TRANSFER, [handle & 0xFFFF_FFFF, dest & 0xFFFF_FFFF])
        rc, _arg = await self.recv_resp_cmd(KM_CMD_KEY_TRANSFER, seq, timeout=timeout)
        await self.check_outbound_empty("POST-KEY-TRANSFER")
        self.log.info("KM CMD_KEY_TRANSFER ok: handle=0x%02x dest=0x%02x rc=%d", handle, dest, rc)
        return rc

    async def check_outbound_empty(self, tag: str) -> None:
        status = await self._status()
        if not (status & (1 << KM_STATUS_OUTBOUND_EMPTY)):
            raise AssertionError(f"[{tag}] KM mailbox outbound FIFO not empty: 0x{status:08x}")
