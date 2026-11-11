# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""KM mailbox commands produce, move and destroy keys; illegal commands return their error codes.

no_cpu / real fuse-sense / +km_rom_hex=rom_main.rom.parhex. RANDCFG.

The sideload KATs prove that a consumer can consume a key. None of them
exercises the interface that PRODUCES, MOVES and DESTROYS one. This leaf owns
that surface: the SEP-facing KM mailbox command set, driven frontdoor against
the real KM firmware, with the AES engine as the consume witness.

Every command is framed by ``SepKmMailbox`` with a correct header CRC-8, a
correct declared length and a correct payload CRC-32C, so a rejection is a
verdict on the command ID or its arguments, never on framing.

Checkers:
  CHK-KM-READY rom_main boots on real entropy -> RESP_KM_READY
  CHK-BOOT-IRQ-EN
              at RESP_KM_READY the KM-CSR tap reads KMCSR IRQ_ENABLE bits 11:0
              equal to every fault and error enable set and OTP_CHANGE_EN
              clear, with the mask built from the generated field names
              (firmware.adoc, "Boot Sequence": the boot enables all fault and
              error interrupts; "OTP Change Status": the boot does not enable
              that source). Bits 31:12 are outside the tap and not graded
  CHK-BOOT-IRQ-STATUS
              at the same sample KMCSR IRQ_STATUS bits 11:0 read 0: the boot
              clears every status bit, an enabled source that sets after the
              clear enters a fatal handler that leaves its bit uncleared and
              traps the CPU until a reset, and OTP_CHANGE sets only on an OTP readout change,
              which the leaf does not cause before READY (firmware.adoc, "Boot
              Sequence" and "Interrupt Handlers"; km_csr.rdl IRQ_STATUS)
  CTRL-BOOT-FETCH-DECODE
              the KM-FETCH sampler covers the boot: it starts before the
              SW_RESET_N release of the KM and stops at RESP_KM_READY, reads
              km_cpu_rst_n_o 0 and then 1 inside that window, sees no unknown
              handshake bit, and decodes at least one completed store to KMCSR
              IRQ_ENABLE, which the boot writes. The store counts to IRQ_ENABLE
              and SRAM_LOCK and the total store count are logged
  CHK-BOOT-SRAM-LOCK-NOWR
              in the same window the KM CPU completes no store to KMCSR
              SRAM_LOCK: the boot list names no SRAM_LOCK write, and ROM sets
              the lock in the handover to mutable firmware (firmware.adoc,
              "Boot Sequence"; architecture.adoc, rom_persist_lock()). A store
              is a clock with valid, ready and a non-zero write strobe; the
              word address is compared
  CHK-HW-VER  CMD_HW_VER returns rc=0 and RETURN_ARG = KMCSR VERSION 1.0.0
  CHK-ROM-VER CMD_ROM_VER returns rc=0 with a return argument; the version
              value (bits 23:0) is logged as OBS-ROM-VER (no spec states it)
  CHK-ROM-VER-RSVD
              bits 31:24 of the CMD_ROM_VER RETURN_ARG read 0: they are
              RESERVED and reserved fields read as 0 (firmware.adoc,
              "Command Message Reference" and "0x01 - CMD_ROM_VER")
  CHK-SRAM-VER
              CMD_SRAM_VER returns RC_FAILURE: this image is ROM-only
  CHK-GEN     CMD_KEY_GENERATE with DEST_VALID = AES | gen_dest returns rc=0
              and a non-null handle, and its RETURN_ARG echoes the requested
              size and that destination mask. gen_dest is one of HMAC, KMAC
              and OTBN, drawn on its own salted seed stream
  CHK-SAMPLER CMD_KEY_GENERATE raises the observed EDN->KM beat count on
              the DRBG scoreboard CHK5_km stream. KMCSR sampler counters
              are not SEP-reachable.
  CHK-UNIQ    a second CMD_KEY_GENERATE, of the other key size, returns a
              DIFFERENT handle and echoes its size: handles are allocated,
              never recycled under the caller
  CHK-GEN-DEST
              the generated key moves only to an engine its DEST_VALID names.
              Refusal: a CMD_KEY_TRANSFER of the CHK-GEN handle to refuse_dest
              (the HMAC, KMAC or OTBN engine that is not gen_dest, released and
              idle for the beat, its SW_RESET_N bit read back 1) returns
              RC_FAILURE with no RETURN_ARG on the wire, and the KM-BUS
              key-path tap shows 0 AW and 0 W handshakes on all five ports from
              the send to RESP_CMD; CHK-ALIVE follows (firmware.adoc, "0x24 -
              CMD_KEY_TRANSFER" Response: a disallowed engine gets failure and
              no key transfer takes place). Allow, the control of the refusal:
              the same handle to gen_dest returns rc=0 with the handle and dest
              echoed, the gen_dest port carries at least one AW and one W
              handshake with equal counts, and the other four ports, AES
              included, carry none. No unknown handshake bit in either window.
              Each seed grades one allow port and one refusal port
  CHK-XFER    CMD_KEY_TRANSFER of a known loaded key to AES returns rc=0 and
              the AES ciphertext equals the independent AES-256-ECB golden, so
              the transfer moved that exact key
  CHK-XFER-DEST
              a dedicated CMD_KEY_TRANSFER of that same handle to the
              seed-selected dest (HMAC / KMAC / AES / OTBN) returns rc=0 and
              echoes the dest. Consume proof stays on the sideload KATs and
              on CHK-XFER; this checker is the mailbox dest cell. Each seed
              covers one dest; other seeds cover the other dests
  CHK-ABR-DEST
              a directed CMD_KEY_LOAD + CMD_KEY_TRANSFER of an 8-word
              seed to dest ABR ML-DSA seed (0x10) returns rc=0
              and echoes that dest. Every seed walks this cell. Consume of
              the seed (KV pull + KEYGEN vs direct-seed PK) is
              sep_km_abr_seed_sideload_test
  CHK-DEST    a transfer to an engine OUTSIDE the key's DEST_VALID is refused
              RC_FAILURE, with the target released (its SW_RESET_N bit read
              back 1) and idle so a parked engine is not the cause, and with
              an unconditional control beat -- the SAME handle to an in-mask
              dest returns rc=0 -- so a dead handle is not the cause either
  CHK-SHRED   CMD_ENGINE_SHRED returns rc=0 with its destination echoed, and
              the engine is still correctly re-keyable afterwards: a second,
              DISTINCT known key transferred after the shred encrypts to its
              own golden and NOT to the first key's
  CHK-SHRED-FILL
              on both AES shreds (CHK-SHRED, AES holding KAT_KEY_A, and
              CHK-GONE, AES holding KAT_KEY_B) the AES port of the KM-BUS
              key-path tap is captured from the CMD_ENGINE_SHRED send to its
              RESP_CMD, with no unknown handshake and as many W beats as AW
              beats; the k-th W beat is the data of the k-th AW. Beats outside
              the 16 share-word offsets (the key_valid clear of KEY_CTRL among
              them) are excluded from the terms. Graded: (a) every byte lane
              of each of the 16 share words is written at least once; (b) the
              CHK5_km EDN->KM beat count rises by at least 4 during the shred,
              the four DRBG words of one PRNG seed (the reseed of every
              further pass is not graded, because the pass count is not
              specified); (c) the final share-0 vector, the final share-1
              vector and their XOR each differ from the key the engine held;
              (d) per share, the data written to the share-0 words of one
              shred is not one repeated value, and neither is the data
              written to its share-1 words; (e) the ordered share data of the
              second shred differs from that of the first; (f) each final
              share vector differs from the vector that share held after the
              CMD_KEY_TRANSFER that loaded the key, which is captured on the
              same tap with every lane of the 16 share words written and its
              two share vectors XOR-ing to the key (firmware.adoc,
              "Crypto Engine Drivers", Shred: PRNG data, a DRBG reseed before
              each pass; architecture.adoc, "Key Delivery").
              Terms (c)-(f) compare whole vectors only. The shred data is
              xoshiro128++ output from a 128-bit seed of four DRBG words
              (firmware.adoc, "Firmware PRNG"), so a correct KM fails each of
              them with probability at most 2^-128, and every failure replays
              from its seed. INFO-SHRED-FILL logs the W beats and strobes per
              offset (the pass count is not specified) and the other beats
  CHK-REVOKE  CMD_KEY_REVOKE returns rc=0 with the handle echoed
  CHK-CLOSED  the generated handle transfers to AES (rc=0, handle and dest
              echoed) just before the revoke, and the same transfer on the
              REVOKED handle is refused RC_FAILURE: revoke fails closed
  CHK-REVOKE-TWICE
              CMD_KEY_REVOKE of the already-revoked generated handle is
              refused with RC_INVALID_ARG and RETURN_ARG 0, or with
              RC_FAILURE and no RETURN_ARG (firmware.adoc, "0x23 -
              CMD_KEY_REVOKE" Response; "Key Registry", Destroy), and CHK-ALIVE
              follows. It runs right after CHK-CLOSED and again on the full
              vault after CHK-VAULT-FULL, where the slot the revoked key held is
              in use again: there the single-slot CMD_KEY_LOAD that follows
              still returns RC_FAILURE with no RETURN_ARG, so the refused
              revoke freed no slot. Which refusal code is logged as
              OBS-REVOKE-TWICE (no spec line picks one)
  CHK-NULL    CMD_KEY_REVOKE of the reserved null handle is refused with
              RC_INVALID_ARG or RC_FAILURE; which of the two is logged as
              OBS-NULL (no spec line picks one)
  CHK-NULL-ARG
              that refusal carries the RETURN_ARG its code defines:
              RC_INVALID_ARG with RETURN_ARG 0 (the index of the handle word),
              or RC_FAILURE with no RETURN_ARG on the wire (firmware.adoc,
              "0x23 - CMD_KEY_REVOKE", Response)
  CHK-ILLEGAL every seeded undefined command ID returns RC_INVALID_CMD (-4)
  CHK-LEN     a defined command carrying the wrong payload length returns
              RC_INVALID_LEN (-5)
  CHK-FRAME   the three framing rejections, each with the value it carries: a
              corrupt header CRC-8 returns RC_HEADER_CRC with the CRC the KM
              computed, a wrong sequence number returns RC_CMD_NOSEQ with the
              number it expected, and a corrupt payload CRC-32C returns
              RC_PAYLOAD_CRC
  CHK-LEN-ARG the RC_INVALID_LEN response of the CHK-LEN frame carries the
              payload length the KM received (2) as RETURN_ARG
  CHK-PCRC-ARG
              the RC_PAYLOAD_CRC response of the corrupt-CRC frame of
              CHK-FRAME carries, as RETURN_ARG, the CRC-32C the KM computed
              over the payload as sent, not the corrupt CRC in the frame
  CHK-OTP     CMD_OTP_READ_LOCK_COLD of one identity bit returns rc=0 with
              an echo equal to that bit alone; a reserved bit returns RC_INVALID_ARG;
              a zero-length payload returns RC_INVALID_LEN
  CTRL-FLUSHED-BY-KM-CLR
              right before the SEP flush of CHK-RECOV, SEP_IRQ_STATUS
              flushed_by_km reads 1 (set by the boot flush of the KM), and
              after a write of 1 to that bit alone it reads 0 (km_mailbox_sep.rdl
              SEP_IRQ_STATUS: sticky, write 1 to clear)
  CHK-RECOV   SEP CTRL.FLUSH raises RESP_RECOVERABLE_FAULT; CMD_STAT reports
              the latched bit; aggregator [31] is 1; CMD_RECOV_ACK clears both
  CHK-SEP-FLUSH-NO-PEER
              after CHK-RECOV, SEP_IRQ_STATUS flushed_by_km reads 0: a SEP
              flush sets the flushed-by-other status of the KM, not of the SEP,
              and the KM handles it without a second FIFO flush
              (architecture.adoc, mailbox flush; firmware.adoc, flushed_by_sep)
  CHK-GONE    a shredded engine refuses to start: KAT_KEY_B is transferred to
              AES again and a sideload block encrypts to its golden, then a
              final CMD_ENGINE_SHRED follows and the same start produces no
              output within a bounded window, with STATUS.INPUT_READY then 0
              (the written block is held, not loaded). The shred is the only
              change between the two starts, so it reached the key rather than
              merely returning success. Runs after every AES leg, because an engine
              parked waiting for a key stays that way until its next valid
              key; the vault, OTP-change and warm-reset legs after it run no
              AES block
  CHK-GEN-ARG CMD_KEY_GENERATE with REQ_SIZE 128 returns RC_INVALID_ARG with
              RETURN_ARG 0, and with a reserved bit in DEST_VALID returns
              RC_INVALID_ARG with RETURN_ARG 1. Both responses must carry
              the RETURN_ARG word, so a missing one does not read as 0. The
              five other reserved-bit and empty-mask frames are logged as
              OBS-CMD-ARG-EDGE (no spec states their code or argument)
  CHK-VAULT-FILL
              with F = KPV_SLOTS minus the slots of the leaf's live keys
              (each live key is at most 16 words, one slot), F single-slot
              CMD_KEY_GENERATE commands (seeded REQ_SIZE 0 to 15) each return
              rc=0 with a new non-null handle: the free-slot search starts at a
              DRBG-selected slot and wraps once, so it finds a free slot from
              any start (firmware.adoc, "Key Management", Load; architecture.adoc,
              "Key and Policy Vault (KPV)": 64 slots)
  CHK-VAULT-FULL
              on that full vault one more single-slot CMD_KEY_GENERATE returns
              RC_FAILURE, and one single-slot CMD_KEY_LOAD returns RC_FAILURE
              with no RETURN_ARG on the wire (firmware.adoc, "0x22 -
              CMD_KEY_GENERATE" Response; "0x26 - CMD_KEY_LOAD", Capacity and
              success). The GENERATE argument is logged. Handles stay below the
              255 limit, so the failure is the vault, not the handle space
  CHK-OTP-CHG-DORMANT
              the shipped ROM leaves the OTP-change source masked: KMCSR
              IRQ_ENABLE.otp_change_en reads 0 after RESP_KM_READY and before
              the pulse, and after one HK-IRQSET pulse of OTP_CHANGE,
              IRQ_STATUS.otp_change reads 1 on every sample of a quiet window
              of OTP_QUIET_CLKS clocks while the KMCSR ISR entry count stays
              unchanged (firmware.adoc, "OTP Change Status"). The pulse itself
              is the control: HK-IRQSET fired and the status bit rose. Runs
              after every other key-command leg, since the bit stays set
  CHK-VAULT-WARM-LOAD
              with the vault still full, a KM warm reset (SW_RESET_N km bit
              parked and released, each read back) is followed by
              RESP_KM_READY, and the same single-slot CMD_KEY_LOAD that
              CHK-VAULT-FULL saw refused returns rc=0 with the size and
              destination echoed and handle 1: the boot re-initializes the key
              registry and the warm reset clears the slot locks
              (firmware.adoc, "Boot Sequence" and "Key Registry", Initialize;
              architecture.adoc, "Key and Policy Vault (KPV)": the lock/seal
              bits clear on warm reset). A CMD_KEY_TRANSFER to
              AES of handle_b, issued before the reset and cleared by the
              registry Initialize, so an unavailable handle, is then refused with
              RC_FAILURE and no RETURN_ARG (firmware.adoc:1069-1070, "Key
              Transfer and Sideload Purge": an unavailable handle gets
              failure; "0x24 - CMD_KEY_TRANSFER" Response), as CHK-CLOSED
              grades a revoked handle, and CHK-ALIVE follows. The code is also
              logged as OBS-WARM-STALE-HANDLE. The refused load of
              CHK-VAULT-FULL in the same seed
              is the control of the load. The control of the refusal is a
              CMD_KEY_TRANSFER of the new handle 1 to AES in the same state:
              it returns rc=0 with the handle and dest echoed (firmware.adoc,
              "0x24 - CMD_KEY_TRANSFER", Response), so the KM-to-AES transfer
              path is live after the warm reset, and CHK-ALIVE follows
  CHK-ALIVE   after every rejection, and once after the undefined-ID walk,
              CMD_STAT succeeds AND reports no latched recoverable error. The
              second half is what gives the refusal checkers their meaning:
              while a recoverable fault is pending the KM answers RC_FAILURE
              to every key command regardless of its arguments, which is the
              same code CHK-DEST and CHK-CLOSED expect, so without this a
              faulted KM would satisfy both

The mailbox is a TRANSPORT here, not the subject. Its register surface --
STATUS depth and full/overflow/underflow, IRQ_STATUS, and SEP_CTRL's response
modes and flush -- belongs to `sep_km_mailbox_protocol_rand_test`. Proving those
means deliberately reading an empty FIFO and overrunning a full one, which
corrupts whatever frame is in flight; it does not compose with a leaf whose
subject is the command stream.

Not covered:
  * A DRBG fault during a command is not graded here. The fault status is KMCSR
    IRQ_STATUS bit 6, which sits on the KM-internal bus and answers DECERR from
    the SEP fabric, and provoking the fault needs testbench knobs this bench
    does not have. At SEP level a DRBG fault is unrecoverable: the KM emits an
    unsolicited RESP_UNRECOVERABLE_FAULT, so it also cannot be a return-code
    check. Building it would need a backdoor.
  * The engine KEY_SHARE CSRs are write-only and read as zero, so the shredded
    key material has no frontdoor. CHK-SHRED-FILL grades it on the KM-BUS
    key-path tap instead, as whole-vector terms that a correct KM fails with
    probability at most 2^-128 each; the shred write order and the number of
    shred passes are not graded.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env.sep_aes_golden import aes256_ecb_encrypt_words
from env.sep_crc_golden import crc8_rohc, crc32c
from env.sep_km_img_h import KPV_SLOT_WORDS, KPV_SLOTS
from env.sep_reg_meta import CHeaderRegBlock, ip_c_header
from env.sep_seeded_rng import SepSeededRng
from env.sep_spec_tables import agg_from_pic
from sep_base_test import sep_base_test
from seq_lib.sep_aes_seq import AES_STATUS_INPUT_READY, SepAes
from seq_lib.sep_km_mailbox_seq import (
    KM_CMD_ENGINE_SHRED,
    KM_CMD_HW_VER,
    KM_CMD_KEY_GENERATE,
    KM_CMD_KEY_LOAD,
    KM_CMD_KEY_REVOKE,
    KM_CMD_KEY_TRANSFER,
    KM_CMD_OTP_READ_LOCK_COLD,
    KM_CMD_RECOV_ACK,
    KM_CMD_ROM_VER,
    KM_CMD_SRAM_VER,
    KM_CMD_STAT,
    KM_DEST_ABR_MLDSA_SEED,
    KM_DEST_ABR_MLKEM_MSG,
    KM_DEST_AES,
    KM_DEST_HMAC,
    KM_DEST_KMAC,
    KM_DEST_OTBN,
    KM_HW_VER_1_0_0,
    KM_IRQ_FLUSHED_BY_KM,
    KM_KEY_HANDLE_NULL,
    KM_RC_CMD_NOSEQ,
    KM_RC_FAILURE,
    KM_RC_HEADER_CRC,
    KM_RC_INVALID_ARG,
    KM_RC_INVALID_CMD,
    KM_RC_INVALID_LEN,
    KM_RC_PAYLOAD_CRC,
    KM_RC_SUCCESS,
    KM_RESP_CMD,
    KM_RESP_RECOVERABLE_FAULT,
    KM_VALID_CMD_IDS,
    SepKmMailbox,
)
from seq_lib.sep_sw_reset_seq import SW_RESET_N_BIT

# Lowest reserved bit of the KEY_HANDLE and DEST_VALID / DEST_ENGINE payload
# words (bits [7:0] carry the field), and the first REQ_SIZE above the 7-bit
# field: firmware.adoc, "0x22 - CMD_KEY_GENERATE" to "0x25 - CMD_ENGINE_SHRED".
_ARG_RESERVED = 1 << 8
_REQ_SIZE_OVER = 1 << 7

# Directed ABR ML-DSA seed for the CHK-ABR-DEST transfer cell. Its consume is
# graded by sep_km_abr_seed_sideload_test, not here.
_ABR_SEED = (
    0x0BADC0DE,
    0x13572468,
    0xA5A5A5A5,
    0xFEEDFACE,
    0x2468ACE0,
    0x5A5A0F0F,
    0x97531ECA,
    0x600DF00D,
)

# flushed_by_sep: firmware.adoc, "0xFE - RESP_RECOVERABLE_FAULT", fault-code table.
_RFAULT_FLUSHED_BY_SEP = -5
_KM_RECOV = agg_from_pic("KM recoverable error")

# Two DISTINCT known 256-bit keys. Every word differs between them and within
# them, so a truncated, word-swapped or stale sideload changes the ciphertext.
KAT_KEY_A = (
    0xDEADBEEF,
    0x00112233,
    0x44556677,
    0x8899AABB,
    0xCCDDEEFF,
    0x01234567,
    0x89ABCDEF,
    0xFEDCBA98,
)
KAT_KEY_B = (
    0x0F1E2D3C,
    0x4B5A6978,
    0x8796A5B4,
    0xC3D2E1F0,
    0x13579BDF,
    0x2468ACE0,
    0xA5A5A5A5,
    0x5A5A5A5A,
)

AES_ECB_PT = (0x00112233, 0x44556677, 0x8899AABB, 0xCCDDEEFF)

# CMD_KEY_LOAD payload of a one-slot AES key: KEY_SIZE 0 (one word), DEST_VALID
# AES, the key word.
_ONE_SLOT_LOAD = (0, KM_DEST_AES, KAT_KEY_A[0])

# firmware.adoc, "Key Registry": Initialize sets the next handle to 1.
_FIRST_HANDLE = 1

# AES key-path port of the KM-BUS tap (docs/SEP_TB_ARCH.adoc, KM-BUS key-path
# part) and the share-word offsets of its bank, from the generated Key Manager
# register header.
_KEY_PORT_NAME = ("otbn", "aes", "hmac", "kmac", "abr")
_AES_KEY_PORT = _KEY_PORT_NAME.index("aes")
_KM_GEN_PY = Path(__file__).resolve().parents[6] / "ip" / "key_manager" / "regs" / "gen" / "py"
_KM_REG_SPEC = importlib.util.spec_from_file_location(
    "km_command_set_key_manager_reg", _KM_GEN_PY / "key_manager_reg.py"
)
if _KM_REG_SPEC is None or _KM_REG_SPEC.loader is None:
    raise FileNotFoundError(_KM_GEN_PY / "key_manager_reg.py")
_KM_REG = importlib.util.module_from_spec(_KM_REG_SPEC)
_KM_REG_SPEC.loader.exec_module(_KM_REG)
_BLOCK_SPAN = 0x1000
_AES_KEY_BASE = int(_KM_REG.AES_WRAPPER_KEY_REG_MAP_BASE_ADDR)
if _AES_KEY_BASE % _BLOCK_SPAN or int(_KM_REG.AES_WRAPPER_KEY_REG_MAP_SIZE) > _BLOCK_SPAN:
    raise AssertionError("AES_WRAPPER_KEY: not a 4 KiB-aligned block below 4 KiB")
# AES_SHARE_OFFSETS[s][i]: block offset of KEY_SHARE<s>[i].
AES_SHARE_OFFSETS = tuple(
    tuple(
        int(getattr(_KM_REG, f"AES_WRAPPER_KEY_KEY_SHARE{s}_{i}__REG_ADDR")) - _AES_KEY_BASE
        for i in range(len(KAT_KEY_A))
    )
    for s in (0, 1)
)
_AES_SHARE_SET = frozenset(AES_SHARE_OFFSETS[0] + AES_SHARE_OFFSETS[1])
if len(_AES_SHARE_SET) != 2 * len(KAT_KEY_A) or hasattr(
    _KM_REG, f"AES_WRAPPER_KEY_KEY_SHARE0_{len(KAT_KEY_A)}__REG_ADDR"
):
    raise AssertionError(
        f"AES_WRAPPER_KEY: share offsets are not 2 x {len(KAT_KEY_A)} distinct words"
    )
_WORD_STRB = 0xF
# KMCSR word addresses as the KM CPU decodes them (key_manager.rdl kmcsr base
# plus the km_csr.rdl offset), for the KM-FETCH store decode.
KMCSR_IRQ_ENABLE_ADDR = int(_KM_REG.KMCSR_IRQ_ENABLE_REG_ADDR)
KMCSR_SRAM_LOCK_ADDR = int(_KM_REG.KMCSR_SRAM_LOCK_REG_ADDR)
# DRBG words that seed the firmware PRNG once (firmware.adoc, "Firmware PRNG").
_PRNG_SEED_WORDS = 4

# Sizes CMD_KEY_GENERATE is asked for, as word counts: CHK-GEN, then CHK-UNIQ.
GEN_KEY_WORDS = (8, 12)

# Sideload dest bits. AES is always permitted so CHK-XFER / CHK-SHRED /
# CHK-GONE keep a consume witness. The seed adds one of these four as the
# extra CMD_KEY_TRANSFER dest that sep_km_command_sideload_cg.cp_dest samples.
LEGAL_DESTS = (KM_DEST_HMAC, KM_DEST_KMAC, KM_DEST_AES, KM_DEST_OTBN)
# CHK-GEN-DEST engines: gen_dest joins AES on the generated key's DEST_VALID,
# refuse_dest is one of the other two. Drawn on their own salted stream so the
# main-stream draws keep their per-seed values.
GEN_DESTS = (KM_DEST_HMAC, KM_DEST_KMAC, KM_DEST_OTBN)
_GEN_DEST_SALT = 0x4745_4E44 << 32
DEST_NAME = {
    KM_DEST_HMAC: "hmac",
    KM_DEST_KMAC: "kmac",
    KM_DEST_AES: "aes",
    KM_DEST_OTBN: "otbn",
}

# KMCSR IRQ_STATUS / IRQ_ENABLE OTP-change masks, from the generated header.
_KM_CSR = CHeaderRegBlock("KM_CSR", ip_c_header("key_manager").with_name("km_csr.h"))
OTP_CHANGE = int(_KM_CSR.fields("IRQ_STATUS_REG")["OTP_CHANGE"]["bm"])
OTP_CHANGE_EN = int(_KM_CSR.fields("IRQ_ENABLE_REG")["OTP_CHANGE_EN"]["bm"])
# CHK-BOOT-IRQ-EN golden: every IRQ_ENABLE field except OTP_CHANGE_EN
# (firmware.adoc, "Boot Sequence" and "OTP Change Status"). RSVD lies outside
# the 12-bit KM-CSR tap.
BOOT_IRQ_ENABLE = sum(
    int(meta["bm"])
    for name, meta in _KM_CSR.fields("IRQ_ENABLE_REG").items()
    if name not in ("RSVD", "OTP_CHANGE_EN")
)
_IRQ_STATUS_NAMES = {
    int(meta["bm"]): name
    for name, meta in _KM_CSR.fields("IRQ_STATUS_REG").items()
    if name != "RSVD"
}
# CMD_OTP_READ_LOCK_COLD masks of the identity lock (SEP_SYS_ID) and of the
# lowest reserved bit: firmware.adoc, "0x28 - CMD_OTP_READ_LOCK_COLD", OTP
# cold-read-lock bit encoding.
_OTP_LOCK_COLD = _KM_CSR.fields("OTP_READ_LOCK_COLD_REG")
_OTP_LOCK_IDENTITY = int(_OTP_LOCK_COLD["SEP_SYS_ID"]["bm"])
_OTP_LOCK_RESERVED = 1 << _OTP_LOCK_COLD["RSVD"]["bp"]
# OTP_READ_LOCK_COLD after the first identity lock: its cold-reset value with the
# SEP_SYS_ID read-lock bit set.
_OTP_LOCK_COLD_AFTER_ID = _KM_CSR.reset("OTP_READ_LOCK_COLD_REG") | _OTP_LOCK_IDENTITY

# Quiet window of CHK-OTP-CHG-DORMANT, in clocks. An enabled handler enters
# and clears the bit within this many clocks (sep_km_otp_change_irq_test
# grades that bound with the source enabled).
OTP_QUIET_CLKS = 5000

# Largest single-slot encoded key size: KPV_SLOT_WORDS words.
_ONE_SLOT_MAX_REQ = KPV_SLOT_WORDS - 1

# Number of undefined command IDs to walk per run.
N_ILLEGAL_IDS = 7

# Negative window for the shredded-engine probe, in the 20-cycle polls of
# _poll_status_bit. The window is spent in full on every passing run.
_SHRED_REFUSE_POLLS = 50


def _arg_str(arg: int | None) -> str:
    return "none" if arg is None else f"0x{arg:08x}"


class _AesKeyPortWrites:
    """AW and W handshakes on the AES key-path port of the KM-BUS tap.

    The AW block offsets and the W (data, strobe) beats are recorded
    independently, each in clock order. AXI4-Lite has no write interleaving,
    so the k-th W beat carries the data of the k-th AW. ``xz`` counts clocks
    where a VALID or READY bit, or the address, data or strobe of a handshake,
    is not 0 or 1; the check that reads this monitor requires it to be 0.
    """

    def __init__(self, test: sep_base_test) -> None:
        top = cocotb.top
        self.test = test
        self.clk = top.clk_i
        self.aw_valid = top.km_key_aw_valid_o
        self.aw_ready = top.km_key_aw_ready_o
        self.aw_addr = top.km_key_aw_addr_o
        self.w_valid = top.km_key_w_valid_o
        self.w_ready = top.km_key_w_ready_o
        self.w_data = top.km_key_w_data_o
        self.w_strb = top.km_key_w_strb_o
        if len(self.aw_valid) != len(_KEY_PORT_NAME) or len(self.w_valid) != len(_KEY_PORT_NAME):
            raise AssertionError(
                f"km_key_aw_valid_o / km_key_w_valid_o are {len(self.aw_valid)} / "
                f"{len(self.w_valid)} bits, expected one per key-path port {_KEY_PORT_NAME}"
            )
        self.aw: list[int] = []
        self.w: list[tuple[int, int]] = []
        self.xz = 0
        self._on = False

    def start(self) -> None:
        self.aw = []
        self.w = []
        self.xz = 0
        self._on = True
        cocotb.start_soon(self._run())

    async def stop(self) -> None:
        self._on = False
        await ClockCycles(self.clk, 2)

    async def _run(self) -> None:
        port = _AES_KEY_PORT
        bit = 1 << port
        word = 0xFFFF_FFFF << (32 * port)
        strb = _WORD_STRB << (4 * port)
        rd = self.test.rd
        while True:
            await RisingEdge(self.clk)
            await ReadOnly()
            if not self._on:
                return
            try:
                if rd(self.aw_valid, bit) & rd(self.aw_ready, bit):
                    self.aw.append((rd(self.aw_addr, word) >> (32 * port)) % _BLOCK_SPAN)
                if rd(self.w_valid, bit) & rd(self.w_ready, bit):
                    self.w.append(
                        (rd(self.w_data, word) >> (32 * port), rd(self.w_strb, strb) >> (4 * port))
                    )
            except AssertionError:
                self.xz += 1


class _KeyBusWatch:
    """AW and W handshake counts per port on the five KM-BUS key-path ports.

    Samples every clock. ``xz`` counts clocks where a VALID or READY bit is not
    0 or 1; the check that reads this watch requires it to be 0.
    """

    def __init__(self, test: sep_base_test) -> None:
        top = cocotb.top
        self.test = test
        self.clk = top.clk_i
        self.sigs = (
            (top.km_key_aw_valid_o, top.km_key_aw_ready_o),
            (top.km_key_w_valid_o, top.km_key_w_ready_o),
        )
        self.aw = [0] * len(_KEY_PORT_NAME)
        self.w = [0] * len(_KEY_PORT_NAME)
        self.xz = 0
        self._on = False

    def start(self) -> None:
        self.aw = [0] * len(_KEY_PORT_NAME)
        self.w = [0] * len(_KEY_PORT_NAME)
        self.xz = 0
        self._on = True
        cocotb.start_soon(self._run())

    async def stop(self) -> None:
        self._on = False
        await ClockCycles(self.clk, 2)

    def counts(self) -> str:
        return " ".join(
            f"{name}:aw={a},w={w}" for name, a, w in zip(_KEY_PORT_NAME, self.aw, self.w)
        )

    async def _run(self) -> None:
        rd = self.test.rd
        while True:
            await RisingEdge(self.clk)
            await ReadOnly()
            if not self._on:
                return
            try:
                aw, w = (rd(valid) & rd(ready) for valid, ready in self.sigs)
            except AssertionError:
                self.xz += 1
                continue
            for p in range(len(_KEY_PORT_NAME)):
                self.aw[p] += aw >> p & 1
                self.w[p] += w >> p & 1


class _KmFetchWatch:
    """Completed KM CPU stores on the KM-FETCH tap, and the KM CPU reset.

    Samples every clock after ``ReadOnly``, so no handshake clock is skipped. A
    store is a clock with ``km_mem_valid_o``, ``km_mem_ready_o`` and a non-zero
    ``km_mem_wstrb_o``; ``stores`` counts the stores per decoded word address
    and ``total`` all of them. ``rst_low`` and ``rst_rose`` record that
    ``km_cpu_rst_n_o`` read 0 and later 1 inside the window. ``xz`` counts
    clocks where the reset, VALID or READY, or the strobe or address of a
    handshake, is not 0 or 1.
    """

    def __init__(self, test: sep_base_test, addrs: tuple[int, ...]) -> None:
        top = cocotb.top
        self.test = test
        self.clk = top.clk_i
        self.valid = top.km_mem_valid_o
        self.ready = top.km_mem_ready_o
        self.addr = top.km_mem_addr_o
        self.wstrb = top.km_mem_wstrb_o
        self.rst_n = top.km_cpu_rst_n_o
        self.stores = dict.fromkeys(addrs, 0)
        self.total = 0
        self.rst_low = False
        self.rst_rose = False
        self.clocks = 0
        self.xz = 0
        self._on = False

    def start(self) -> None:
        self._on = True
        cocotb.start_soon(self._run())

    async def stop(self) -> None:
        self._on = False
        await ClockCycles(self.clk, 2)

    async def _run(self) -> None:
        rd = self.test.rd
        while True:
            await RisingEdge(self.clk)
            await ReadOnly()
            if not self._on:
                return
            self.clocks += 1
            try:
                rst_n = rd(self.rst_n)
                hs = rd(self.valid) & rd(self.ready)
                strb = rd(self.wstrb) if hs else 0
                addr = rd(self.addr) & ~0x3 if strb else 0
            except AssertionError:
                self.xz += 1
                continue
            if not rst_n:
                self.rst_low = True
            elif self.rst_low:
                self.rst_rose = True
            if strb:
                self.total += 1
                if addr in self.stores:
                    self.stores[addr] += 1


class _ShareWrites:
    """The AES share writes of one capture, merged per word by strobe.

    ``share`` holds the (offset, data, strobe) beats at the 16 share-word
    offsets in order and ``other`` the rest; ``vectors`` is the final share-0
    and share-1 vector in index order, with an unwritten byte lane read as 0.
    """

    def __init__(self, cap: _AesKeyPortWrites) -> None:
        self.cap_aw = list(cap.aw)
        self.cap_w = list(cap.w)
        self.xz = cap.xz
        self.clean = cap.xz == 0 and len(cap.aw) == len(cap.w)
        pairs = list(zip(cap.aw, cap.w))
        self.share = [(off, d, st) for off, (d, st) in pairs if off in _AES_SHARE_SET]
        self.other = [(off, d, st) for off, (d, st) in pairs if off not in _AES_SHARE_SET]
        self.strobes: dict[int, list[int]] = {off: [] for off in sorted(_AES_SHARE_SET)}
        final = dict.fromkeys(self.strobes, 0)
        self.lanes = dict.fromkeys(self.strobes, 0)
        for off, data, strb in self.share:
            mask = sum(0xFF << (8 * b) for b in range(4) if (strb >> b) & 1)
            final[off] = (final[off] & ~mask) | (data & mask)
            self.lanes[off] |= strb
            self.strobes[off].append(strb)
        self.vectors = tuple(tuple(final[off] for off in AES_SHARE_OFFSETS[s]) for s in (0, 1))
        self.unwritten = [f"0x{off:03x}/{v:x}" for off, v in self.lanes.items() if v != _WORD_STRB]


class SepKmCommandSetCfg:
    """Single source of truth: the seeded command-set policy for one run."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        self.xfer_dest = rng.choice(LEGAL_DESTS)
        # AES stays on the mask so the consume / shred / gone path is unchanged.
        self.load_dest = KM_DEST_AES | self.xfer_dest
        others = tuple(d for d in LEGAL_DESTS if (d & self.load_dest) == 0)
        self.bad_dest = rng.choice(others)
        self.illegal_ids = self._pick_illegal(rng)
        # One REQ_SIZE per vault-fill command, plus one for the full-vault probe.
        self.fill_sizes = tuple(rng.randrange(_ONE_SLOT_MAX_REQ + 1) for _ in range(KPV_SLOTS + 1))
        gen = SepSeededRng(seed ^ _GEN_DEST_SALT)
        self.gen_dest = gen.choice(GEN_DESTS)
        self.refuse_dest = gen.choice(tuple(d for d in GEN_DESTS if d != self.gen_dest))

    @staticmethod
    def _pick_illegal(rng) -> tuple[int, ...]:
        """Draw distinct command IDs that the KM does not define.

        The boundaries just outside each defined run are always included: those
        are where an off-by-one in the validity test shows up. The rest come
        from the seed.
        """
        # The three defined runs are 0x00-0x04, 0x10-0x12 and 0x22-0x28, so these
        # are the IDs immediately outside them -- 0x21 included, since a
        # boundary slip there would invent a command inside the key range.
        picked = [0x05, 0x0F, 0x13, 0x21, 0x29]
        while len(picked) < N_ILLEGAL_IDS:
            cand = rng.randrange(0x100)
            if cand not in KM_VALID_CMD_IDS and cand not in picked:
                picked.append(cand)
        return tuple(picked)

    def summary(self) -> str:
        return (
            f"seed={self.seed} "
            f"xfer_dest=0x{self.xfer_dest:02x}({DEST_NAME[self.xfer_dest]}) "
            f"load_dest=0x{self.load_dest:02x} "
            f"bad_dest=0x{self.bad_dest:02x} "
            f"gen_dest=0x{self.gen_dest:02x}({DEST_NAME[self.gen_dest]}) "
            f"refuse_dest=0x{self.refuse_dest:02x}({DEST_NAME[self.refuse_dest]}) "
            f"illegal_ids={[hex(i) for i in self.illegal_ids]}"
        )


@pyuvm.test()
class sep_km_command_set_rand_test(sep_base_test):
    """Produce, move and destroy a key over the KM mailbox; reject the rest."""

    required_evidence = (
        "CHK-ROM-VER-RSVD",
        "CHK-NULL-ARG",
        "CHK-VAULT-FILL",
        "CHK-VAULT-FULL",
        "CHK-OTP-CHG-DORMANT",
        "CHK-SHRED-FILL",
        "CHK-REVOKE-TWICE",
        "CHK-VAULT-WARM-LOAD",
        "CHK-BOOT-IRQ-EN",
        "CHK-BOOT-IRQ-STATUS",
        "CHK-BOOT-SRAM-LOCK-NOWR",
        "CHK-GEN-DEST",
        "CHK-SEP-FLUSH-NO-PEER",
    )

    async def run_scenario(self) -> None:
        cfg = SepKmCommandSetCfg(self.random_seed())
        self.logger.info("INFO-CMDSET-CFG %s", cfg.summary())

        # --- Boot the real KM firmware on real entropy ------------------------
        # The KM firmware reads OTP at boot, so stage a valid PROD image and
        # sense it for real. AES stays released as the consume witness; the
        # other three sideload targets are parked, so a key can only land where
        # this test says it lands.
        image = self.select_efuse_image(lc_raw=0x1)  # LC_PROD
        self.write_efuse_image(image)
        await self.bring_up_no_cpu(park=("otbn", "kmac", "hmac"))

        # Checker and monitor summaries carry the retained evidence. Per-access
        # INFO records do not and dominate the log during the long mailbox waits.
        self.suppress_host_axi_transaction_info()

        self.km = SepKmMailbox(self)
        self.aes = SepAes(self)

        await self.bring_up_entropy(strict=True, score_km="observe", score_sinks={"aes": "observe"})
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.start_fifo_drain()

        # The KM is held in reset from the bench reset to this release, so the
        # KM-FETCH window from here to RESP_KM_READY holds the whole boot.
        fetch = _KmFetchWatch(self, (KMCSR_IRQ_ENABLE_ADDR, KMCSR_SRAM_LOCK_ADDR))
        fetch.start()
        await self.swrst.release("km")
        await self.km.wait_km_ready()
        self.logger.info("CHK-KM-READY PASS: rom_main booted, RESP_KM_READY over the mailbox")
        otp_en_boot = self.rd_known(cocotb.top.km_csr_irq_enable_o)
        status_boot = self.rd_known(cocotb.top.km_csr_irq_status_o)
        await fetch.stop()
        self._check_boot_irq(otp_en_boot, status_boot)
        self._check_boot_fetch(fetch)

        # --- CHK-HW-VER / CHK-ROM-VER / CHK-SRAM-VER -------------------------
        rc, arg = await self.km.send_raw_expect_rc(KM_CMD_HW_VER, [])
        assert rc == KM_RC_SUCCESS and arg == KM_HW_VER_1_0_0, (
            f"CHK-HW-VER FAIL: rc={rc} arg=0x{arg:08x}, expected rc=0 "
            f"arg=0x{KM_HW_VER_1_0_0:08x} (KMCSR VERSION 1.0.0)"
        )
        self.logger.info("CHK-HW-VER PASS: rc=0 RETURN_ARG=0x%08x (KMCSR 1.0.0)", arg)

        # hw/ip/key_manager/doc/firmware.adoc, "0x01 - CMD_ROM_VER": success and a
        # return argument whose bits 31:24 are RESERVED, and "Command Message
        # Reference": reserved fields read as 0. No spec states the version
        # value in bits 23:0, so it is logged only.
        seq = await self.km.send_command(KM_CMD_ROM_VER, [])
        rc, arg = await self.km.recv_resp_cmd(KM_CMD_ROM_VER, seq, require_arg=True)
        await self.km.check_outbound_empty("POST-ROM-VER")
        assert rc == KM_RC_SUCCESS, f"CHK-ROM-VER FAIL: rc={rc}, expected rc=0"
        self.logger.info("CHK-ROM-VER PASS: rc=0 with a RETURN_ARG")
        rsvd = arg >> 24
        assert rsvd == 0, (
            f"CHK-ROM-VER-RSVD FAIL: RETURN_ARG=0x{arg:08x} bits 31:24 = 0x{rsvd:02x}, "
            "expected 0x00 (firmware.adoc:36,149)"
        )
        self.logger.info(
            "CHK-ROM-VER-RSVD PASS: contract=key_manager/doc/firmware.adoc:36"
            "(Command_Message_Reference),:149(0x01_CMD_ROM_VER) arg=0x%08x rsvd=0x%02x "
            "exp_rsvd=0x00",
            arg,
            rsvd,
        )
        self.logger.info("OBS-ROM-VER LOG ver=0x%08x", arg & 0x00FF_FFFF)

        rc, _ = await self.km.send_raw_expect_rc(KM_CMD_SRAM_VER, [])
        assert rc == KM_RC_FAILURE, (
            f"CHK-SRAM-VER FAIL: rc={rc}, expected {KM_RC_FAILURE} -- ROM-only image"
        )
        self.logger.info("CHK-SRAM-VER PASS: ROM-only image returned RC_FAILURE")
        await self._check_alive("post-sram-ver")

        # --- CHK-GEN: the KM produces a key ----------------------------------
        # req_size is the word count minus one, per the command's argument
        # encoding; RETURN_ARG packs handle[7:0], req_size[14:8], dest[23:16].
        req_size = GEN_KEY_WORDS[0] - 1
        km_beats0 = self.drbg_sb.results["CHK5_km"].dut_items
        gen_mask = KM_DEST_AES | cfg.gen_dest
        gen_seq = await self.km.send_command(KM_CMD_KEY_GENERATE, [req_size, gen_mask])
        rc, arg = await self.km.recv_resp_cmd(KM_CMD_KEY_GENERATE, gen_seq)
        assert rc == KM_RC_SUCCESS, f"CHK-GEN FAIL: CMD_KEY_GENERATE rc={rc}"
        gen_handle = arg & 0xFF
        assert gen_handle != KM_KEY_HANDLE_NULL, (
            f"CHK-GEN FAIL: CMD_KEY_GENERATE returned the reserved null handle (arg=0x{arg:08x})"
        )
        echo_size = (arg >> 8) & 0x7F
        echo_dest = (arg >> 16) & 0xFF
        assert echo_size == req_size, (
            f"CHK-GEN FAIL: RETURN_ARG echoed size {echo_size}, requested {req_size} "
            f"(arg=0x{arg:08x})"
        )
        assert echo_dest == gen_mask, (
            f"CHK-GEN FAIL: RETURN_ARG echoed dest 0x{echo_dest:02x}, requested "
            f"0x{gen_mask:02x} (arg=0x{arg:08x})"
        )
        await self.km.check_outbound_empty("POST-KEY-GENERATE")
        self.logger.info(
            "CHK-GEN PASS: handle=0x%02x, RETURN_ARG echoes size=%d dest=0x%02x "
            "exp_size=%d exp_dest=0x%02x",
            gen_handle,
            echo_size,
            echo_dest,
            req_size,
            gen_mask,
        )
        km_beats1 = self.drbg_sb.results["CHK5_km"].dut_items
        assert km_beats1 > km_beats0, (
            f"CHK-SAMPLER FAIL: CHK5_km beats stayed at {km_beats0} through "
            "CMD_KEY_GENERATE -- no EDN->KM handshake"
        )
        self.logger.info(
            "CHK-SAMPLER PASS: CHK5_km observed %d EDN->KM beat(s) during "
            "CMD_KEY_GENERATE (was %d)",
            km_beats1 - km_beats0,
            km_beats0,
        )

        # --- CHK-UNIQ: handles are allocated, not recycled --------------------
        req_size2 = GEN_KEY_WORDS[1] - 1
        gen2_seq = await self.km.send_command(KM_CMD_KEY_GENERATE, [req_size2, KM_DEST_AES])
        rc, arg2 = await self.km.recv_resp_cmd(KM_CMD_KEY_GENERATE, gen2_seq)
        assert rc == KM_RC_SUCCESS, f"CHK-UNIQ FAIL: second CMD_KEY_GENERATE rc={rc}"
        gen_handle2 = arg2 & 0xFF
        assert gen_handle2 not in (KM_KEY_HANDLE_NULL, gen_handle), (
            f"CHK-UNIQ FAIL: second generate returned handle 0x{gen_handle2:02x}, "
            f"first returned 0x{gen_handle:02x}"
        )
        echo_size2 = (arg2 >> 8) & 0x7F
        assert echo_size2 == req_size2, (
            f"CHK-UNIQ FAIL: RETURN_ARG echoed size {echo_size2}, requested {req_size2} "
            f"(arg=0x{arg2:08x})"
        )
        await self.km.check_outbound_empty("POST-KEY-GENERATE-2")
        self.logger.info(
            "CHK-UNIQ PASS: distinct handles 0x%02x and 0x%02x, sizes %d and %d echoed",
            gen_handle,
            gen_handle2,
            echo_size,
            echo_size2,
        )

        # --- CHK-GEN-DEST: the generated key moves only inside its mask -------
        await self._gen_dest(gen_handle, cfg)

        # --- CHK-XFER: the KM moves a KNOWN key, and AES consumes it ----------
        golden_a = aes256_ecb_encrypt_words(list(KAT_KEY_A), list(AES_ECB_PT))
        golden_b = aes256_ecb_encrypt_words(list(KAT_KEY_B), list(AES_ECB_PT))
        assert golden_a != golden_b, (
            "test construction error: the two KAT keys encrypt the plaintext identically"
        )

        handle_a = await self.km.key_load(key_words=list(KAT_KEY_A), dest=cfg.load_dest)
        rc, arg = await self.km.key_transfer(handle=handle_a, dest=KM_DEST_AES)
        assert rc == KM_RC_SUCCESS, f"CHK-XFER FAIL: CMD_KEY_TRANSFER rc={rc}"
        assert (arg & 0xFF) == handle_a and ((arg >> 8) & 0xFF) == KM_DEST_AES, (
            f"CHK-XFER FAIL: RETURN_ARG 0x{arg:08x} does not echo handle 0x{handle_a:02x} "
            f"and dest 0x{KM_DEST_AES:02x}"
        )
        await self.aes.configure_ecb_enc_256(sideload=True)
        await self.aes.trigger_prng_reseed()
        ct_a = await self.aes.run_ecb_block(list(AES_ECB_PT))
        assert ct_a == golden_a, (
            "CHK-XFER FAIL: AES did not consume the transferred key:\n"
            f"  ct     ={[hex(w) for w in ct_a]}\n"
            f"  golden ={[hex(w) for w in golden_a]}"
        )
        self.logger.info("CHK-XFER PASS: rc=0 and ct == AES(KAT_KEY_A, PT) golden")

        # --- CHK-XFER-DEST: seed-selected mailbox dest -----------------------
        # AES consume stays on CHK-XFER. This extra transfer is the dest cell
        # sep_km_command_sideload_cg.cp_dest samples. The dest engine is
        # released only for this beat so it can accept the key-bus write, then
        # parked again. Consume of that dest stays on the sideload KAT.
        await self._transfer_seeded_dest(handle_a, cfg)

        # --- CHK-ABR-DEST: directed ABR ML-DSA seed cell, every seed ----------
        handle_abr = await self.km.key_load(key_words=list(_ABR_SEED), dest=KM_DEST_ABR_MLDSA_SEED)
        rc, arg = await self.km.key_transfer(handle=handle_abr, dest=KM_DEST_ABR_MLDSA_SEED)
        assert rc == KM_RC_SUCCESS, f"CHK-ABR-DEST FAIL: CMD_KEY_TRANSFER dest=0x10 rc={rc}"
        assert (arg & 0xFF) == handle_abr and ((arg >> 8) & 0xFF) == KM_DEST_ABR_MLDSA_SEED, (
            f"CHK-ABR-DEST FAIL: RETURN_ARG 0x{arg:08x} does not echo handle "
            f"0x{handle_abr:02x} and dest 0x{KM_DEST_ABR_MLDSA_SEED:02x}"
        )
        self.logger.info(
            "CHK-ABR-DEST PASS: dest=0x10 (abr_mldsa_seed) rc=0 handle=0x%02x", handle_abr
        )

        # --- CHK-DEST: the permitted destination set is enforced --------------
        # The destination is a legal engine bit, so the command passes argument
        # validation and is refused by the transfer itself: RC_FAILURE, not
        # RC_INVALID_ARG. Asserting the exact code keeps a refusal for the wrong
        # reason -- a malformed argument, say -- from reading as a pass.
        #
        # The engine is RELEASED for this beat. bad_dest is drawn from the three
        # engines this test parks, so with it parked a refusal is equally
        # consistent with the destination policy (the claim) and with the
        # sideload target simply not running -- and the checker could not tell
        # them apart. Released, the only thing still disqualifying it is that it
        # is outside the key's permitted mask.
        bad_name = DEST_NAME[cfg.bad_dest]
        await self._release_ready(bad_name, "bad-dest-release")
        sw_reset_n = await self.swrst.read_back()
        assert sw_reset_n >> SW_RESET_N_BIT[bad_name] & 1, (
            f"CHK-DEST FAIL: SW_RESET_N reads 0x{sw_reset_n:08x} after the release of "
            f"{bad_name}, so the engine is still held in reset for the refused transfer"
        )
        rc, _ = await self.km.key_transfer(handle=handle_a, dest=cfg.bad_dest)
        await self.swrst.park(bad_name)
        assert rc == KM_RC_FAILURE, (
            f"CHK-DEST FAIL: transfer to 0x{cfg.bad_dest:02x} returned rc={rc}, expected "
            f"{KM_RC_FAILURE} (RC_FAILURE) -- the key was loaded for "
            f"mask 0x{cfg.load_dest:02x}"
        )
        # The confirmation beat, and the reason the refusal above is attributable
        # to the destination argument. RC_FAILURE is also the code a KM returns
        # for a handle absent from the registry -- what CHK-CLOSED below grades
        # -- and a registry slot is a finite resource that every CMD_KEY_LOAD
        # between the load and this beat competes for. So the same handle is
        # transferred once more to a dest INSIDE its mask: load_dest always
        # contains KM_DEST_AES (SepKmCommandSetCfg), and AES is live throughout
        # this test. Same handle, same registry state, same KM state -- only the
        # dest differs, so rc=0 here means the refusal above was the destination
        # policy and not a dead handle. It is unconditional, so every seed
        # carries it.
        # This transfer is also the last AES key write before the CHK-SHRED
        # shred, so its capture is the pre-shred share state of CHK-SHRED-FILL (f).
        aes_writes = _AesKeyPortWrites(self)
        rc_ok, arg_ok, loaded_a = await self._aes_transfer_captured(aes_writes, handle_a)
        assert rc_ok == KM_RC_SUCCESS, (
            f"CHK-DEST FAIL: the in-mask control transfer of handle 0x{handle_a:02x} to "
            f"0x{KM_DEST_AES:02x} returned rc={rc_ok}, so the RC_FAILURE above is not "
            "attributable to the destination -- the handle or the KM was already refusing "
            "every transfer"
        )
        assert (arg_ok & 0xFF) == handle_a and ((arg_ok >> 8) & 0xFF) == KM_DEST_AES, (
            f"CHK-DEST FAIL: in-mask control RETURN_ARG 0x{arg_ok:08x} does not echo handle "
            f"0x{handle_a:02x} and dest 0x{KM_DEST_AES:02x}"
        )
        self.logger.info(
            "CHK-DEST PASS: transfer of handle 0x%02x to 0x%02x (%s, released and idle for "
            "the beat, SW_RESET_N=0x%08x) refused with RC_FAILURE, while the SAME handle to "
            "in-mask dest 0x%02x returned rc=0 -- the refusal is the destination policy, not a "
            "parked engine and not a dead handle",
            handle_a,
            cfg.bad_dest,
            bad_name,
            sw_reset_n,
            KM_DEST_AES,
        )
        await self._check_alive("post-dest-refusal")

        # --- CHK-SHRED: destroy the engine's key, then re-key it --------------
        rc, arg, shred_beats = await self._aes_shred(aes_writes)
        assert rc == KM_RC_SUCCESS, f"CHK-SHRED FAIL: CMD_ENGINE_SHRED rc={rc}"
        assert (arg & 0xFF) == KM_DEST_AES, (
            f"CHK-SHRED FAIL: RETURN_ARG echoed dest 0x{arg & 0xFF:02x}, requested "
            f"0x{KM_DEST_AES:02x}"
        )
        shred1_data = self._check_shred_fill(1, aes_writes, shred_beats, KAT_KEY_A, loaded_a, None)
        handle_b = await self.km.key_load(key_words=list(KAT_KEY_B), dest=KM_DEST_AES)
        rc, _ = await self.km.key_transfer(handle=handle_b, dest=KM_DEST_AES)
        assert rc == KM_RC_SUCCESS, f"CHK-SHRED FAIL: post-shred CMD_KEY_TRANSFER rc={rc}"
        await self.aes.configure_ecb_enc_256(sideload=True)
        await self.aes.trigger_prng_reseed()
        ct_b = await self.aes.run_ecb_block(list(AES_ECB_PT))
        assert ct_b == golden_b, (
            "CHK-SHRED FAIL: the re-keyed engine did not consume the second key:\n"
            f"  ct     ={[hex(w) for w in ct_b]}\n"
            f"  golden ={[hex(w) for w in golden_b]}"
        )
        assert ct_b != ct_a, (
            "CHK-SHRED FAIL: the engine produced the FIRST key's ciphertext after a "
            "shred and a transfer of a different key -- the old key was still in use"
        )
        self.logger.info(
            "CHK-SHRED PASS: rc=0 with dest echoed; engine re-keys to KAT_KEY_B's "
            "golden and does not produce KAT_KEY_A's ciphertext"
        )

        # --- CHK-REVOKE / CHK-CLOSED: destroy a key, then fail closed ---------
        # Allow leg of CHK-CLOSED: the generated handle transfers to AES (its
        # DEST_VALID) right before the revoke, so a refusal after the revoke
        # comes from the revoke and not from a KM that refuses generated keys.
        rc, arg = await self.km.key_transfer(handle=gen_handle, dest=KM_DEST_AES)
        assert rc == KM_RC_SUCCESS, (
            f"CHK-CLOSED FAIL: pre-revoke CMD_KEY_TRANSFER of generated handle "
            f"0x{gen_handle:02x} to 0x{KM_DEST_AES:02x} returned rc={rc}, expected rc=0, "
            "so a refusal after the revoke would not be attributable to the revoke"
        )
        assert (arg & 0xFF) == gen_handle and ((arg >> 8) & 0xFF) == KM_DEST_AES, (
            f"CHK-CLOSED FAIL: pre-revoke RETURN_ARG 0x{arg:08x} does not echo handle "
            f"0x{gen_handle:02x} and dest 0x{KM_DEST_AES:02x}"
        )
        allow_arg = arg

        rc, arg = await self.km.key_revoke(handle=gen_handle)
        assert rc == KM_RC_SUCCESS, f"CHK-REVOKE FAIL: CMD_KEY_REVOKE rc={rc}"
        assert (arg & 0xFF) == gen_handle, (
            f"CHK-REVOKE FAIL: RETURN_ARG echoed handle 0x{arg & 0xFF:02x}, revoked "
            f"0x{gen_handle:02x}"
        )
        self.logger.info("CHK-REVOKE PASS: rc=0 with handle 0x%02x echoed", gen_handle)

        # The handle is still a legal value, so this too is refused by the
        # registry lookup rather than by argument validation.
        rc, _ = await self.km.key_transfer(handle=gen_handle, dest=KM_DEST_AES)
        assert rc == KM_RC_FAILURE, (
            f"CHK-CLOSED FAIL: CMD_KEY_TRANSFER on revoked handle 0x{gen_handle:02x} "
            f"returned rc={rc}, expected {KM_RC_FAILURE} (RC_FAILURE) -- revoke did "
            "not fail closed"
        )
        self.logger.info(
            "CHK-CLOSED PASS: generated handle 0x%02x transferred to AES before the revoke "
            "(rc=0 RETURN_ARG=0x%08x) and the same transfer after the revoke returned "
            "rc=%d (RC_FAILURE)",
            gen_handle,
            allow_arg,
            rc,
        )
        await self._check_alive("post-revoked-transfer")
        await self._revoke_twice(gen_handle, "revoked", full_vault=False)
        await self._arg_edge(gen_handle)

        # --- CHK-NULL / CHK-NULL-ARG: the reserved handle is never a target ---
        # The specification gives two refusal codes, invalid_arg for an invalid
        # argument and failure for an unavailable handle, and does not say which
        # one the null handle gets, so the check accepts either and the code is
        # logged as OBS-NULL. Each code defines its RETURN_ARG: invalid_arg
        # carries the index of the invalid payload word (0, the handle word),
        # failure carries none. The frame is decoded here so that a missing
        # RETURN_ARG does not read as 0.
        rc, null_arg = await self._resp_cmd(KM_CMD_KEY_REVOKE, [KM_KEY_HANDLE_NULL])
        self.logger.info("OBS-NULL LOG rc=%d", rc)
        assert rc in (KM_RC_INVALID_ARG, KM_RC_FAILURE), (
            f"CHK-NULL FAIL: CMD_KEY_REVOKE of the null handle returned rc={rc}, "
            f"expected {KM_RC_INVALID_ARG} (RC_INVALID_ARG) or {KM_RC_FAILURE} (RC_FAILURE)"
        )
        self.logger.info("CHK-NULL PASS: revoke of the null handle refused with rc=%d", rc)
        exp_null_arg = 0 if rc == KM_RC_INVALID_ARG else None
        assert null_arg == exp_null_arg, (
            f"CHK-NULL-ARG FAIL: rc={rc} RETURN_ARG={_arg_str(null_arg)}, expected "
            f"{_arg_str(exp_null_arg)} (firmware.adoc:433-439)"
        )
        self.logger.info(
            "CHK-NULL-ARG PASS: contract=key_manager/doc/firmware.adoc:433-439"
            "(0x23_CMD_KEY_REVOKE_Response) rc=%d arg=%s exp_arg=%s",
            rc,
            _arg_str(null_arg),
            _arg_str(exp_null_arg),
        )
        await self._check_alive("post-null-revoke")

        # --- CHK-ILLEGAL: undefined command IDs -------------------------------
        # One CHK-ALIVE covers the whole walk: each ID must answer with its own
        # RC_INVALID_CMD, so the KM is still in its loop after the one before,
        # and a recoverable fault stays latched until CMD_RECOV_ACK, so a fault
        # raised by any ID is still set at the probe.
        for cmd_id in cfg.illegal_ids:
            rc, _ = await self.km.send_raw_expect_rc(cmd_id, [])
            assert rc == KM_RC_INVALID_CMD, (
                f"CHK-ILLEGAL FAIL: undefined command 0x{cmd_id:02x} returned rc={rc}, "
                f"expected {KM_RC_INVALID_CMD} (RC_INVALID_CMD)"
            )
        await self._check_alive("post-illegal-ids")
        self.logger.info(
            "CHK-ILLEGAL PASS: %d undefined command IDs each returned RC_INVALID_CMD "
            "and left the KM answering CMD_STAT: %s",
            len(cfg.illegal_ids),
            [hex(i) for i in cfg.illegal_ids],
        )

        # --- CHK-LEN: a defined command with the wrong payload length ---------
        # CMD_KEY_REVOKE takes exactly one payload word; two must be refused on
        # the length, not silently accepted with the surplus ignored.
        len_payload = [gen_handle2, 0]
        rc, len_arg = await self.km.send_raw_expect_rc(KM_CMD_KEY_REVOKE, len_payload)
        assert rc == KM_RC_INVALID_LEN, (
            f"CHK-LEN FAIL: CMD_KEY_REVOKE with a 2-word payload returned rc={rc}, "
            f"expected {KM_RC_INVALID_LEN} (RC_INVALID_LEN)"
        )
        self.logger.info("CHK-LEN PASS: over-long CMD_KEY_REVOKE payload returned RC_INVALID_LEN")

        # --- CHK-LEN-ARG: RC_INVALID_LEN carries the received payload length --
        # hw/ip/key_manager/doc/firmware.adoc, "0x00 - RESP_CMD", return-code
        # table, invalid_len: the argument is the length of the received
        # payload. The frame is self-consistent, so that is the PAYLOAD_LEN as
        # sent. The argument word is compared whole. A response without an
        # argument reads 0, and a KM that returns the required length returns
        # 1, so neither can equal 2.
        sent_plen = len(len_payload)
        assert len_arg == sent_plen, (
            f"CHK-LEN-ARG FAIL: RC_INVALID_LEN carried RETURN_ARG=0x{len_arg:08x}, "
            f"expected the received payload length {sent_plen}"
        )
        self.logger.info("CHK-LEN-ARG PASS: plen=%d arg=%d", sent_plen, len_arg)
        await self._check_alive("post-bad-length")

        # --- CHK-FRAME: the three framing rejections --------------------------
        # These are the only return codes the KM produces before it looks at the
        # command at all, and each carries a value worth checking: the CRC the KM
        # itself computed, or the sequence number it was expecting. The seq
        # counter side effects differ between them and are handled in the driver.
        seq_used = self.km.seq_num
        expected_crc = crc8_rohc(bytes([seq_used & 0xFF, KM_CMD_STAT & 0xFF, 0]))
        rc, arg = await self.km.send_bad_header_crc(KM_CMD_STAT)
        assert rc == KM_RC_HEADER_CRC, (
            f"CHK-FRAME FAIL: a corrupt header CRC-8 returned rc={rc}, expected "
            f"{KM_RC_HEADER_CRC} (RC_HEADER_CRC)"
        )
        assert (arg & 0xFF) == expected_crc, (
            f"CHK-FRAME FAIL: RC_HEADER_CRC carried 0x{arg & 0xFF:02x}, expected "
            f"CRC-8/ROHC 0x{expected_crc:02x} over [seq, cmd, len] "
            "(hw/ip/key_manager/doc/firmware.adoc HEADER_CRC8 / CRC-8/ROHC table)"
        )
        self.logger.info(
            "CHK-FRAME PASS: corrupt header CRC-8 refused RC_HEADER_CRC, KM computed 0x%02x",
            arg & 0xFF,
        )
        await self._check_alive("post-bad-header-crc")

        expected_seq = self.km.seq_num
        rc, arg = await self.km.send_bad_seq(KM_CMD_STAT)
        assert rc == KM_RC_CMD_NOSEQ, (
            f"CHK-FRAME FAIL: a wrong sequence number returned rc={rc}, expected "
            f"{KM_RC_CMD_NOSEQ} (RC_CMD_NOSEQ)"
        )
        assert (arg & 0xFF) == expected_seq, (
            f"CHK-FRAME FAIL: RC_CMD_NOSEQ reported expected sequence 0x{arg & 0xFF:02x}, "
            f"but the host is at 0x{expected_seq:02x} -- the two counters disagree"
        )
        self.logger.info(
            "CHK-FRAME PASS: wrong sequence number refused RC_CMD_NOSEQ, KM expecting %d",
            arg & 0xFF,
        )
        await self._check_alive("post-bad-seq")

        # CHK-PCRC-ARG golden: the CRC-32C of the payload words as sent, from
        # env/sep_crc_golden.py. send_bad_payload_crc sends the payload
        # unchanged and flips bit 0 of the CRC word, so the corrupt CRC in the
        # frame is golden ^ 1. The leaf asserts that the two differ before the
        # frame goes out, so an echo of the sent CRC cannot match the golden,
        # and that the golden is not 0, so a missing argument (read as 0)
        # cannot match it either.
        pcrc_payload = [gen_handle2]
        pcrc_golden = crc32c(b"".join(w.to_bytes(4, "little") for w in pcrc_payload))
        pcrc_sent = pcrc_golden ^ 0x0000_0001
        assert pcrc_sent != pcrc_golden and pcrc_golden != 0, (
            f"test construction error: CHK-PCRC-ARG golden 0x{pcrc_golden:08x} cannot be "
            f"told apart from the sent CRC 0x{pcrc_sent:08x} or from a missing argument"
        )
        rc, pcrc_arg = await self.km.send_bad_payload_crc(KM_CMD_KEY_REVOKE, pcrc_payload)
        assert rc == KM_RC_PAYLOAD_CRC, (
            f"CHK-FRAME FAIL: a corrupt payload CRC-32C returned rc={rc}, expected "
            f"{KM_RC_PAYLOAD_CRC} (RC_PAYLOAD_CRC)"
        )
        self.logger.info("CHK-FRAME PASS: corrupt payload CRC-32C refused RC_PAYLOAD_CRC")

        # --- CHK-PCRC-ARG: RC_PAYLOAD_CRC carries the CRC the KM computed -----
        # firmware.adoc, "0x00 - RESP_CMD", return-code table, payload_crc, and
        # the sentence below the table: both CRC return arguments carry the
        # value that the KM computed. The argument word is compared whole.
        assert pcrc_arg == pcrc_golden, (
            f"CHK-PCRC-ARG FAIL: RC_PAYLOAD_CRC carried RETURN_ARG=0x{pcrc_arg:08x}, "
            f"expected CRC-32C 0x{pcrc_golden:08x} of the payload as sent"
            + (" (it echoes the corrupt CRC in the frame)" if pcrc_arg == pcrc_sent else "")
        )
        self.logger.info(
            "CHK-PCRC-ARG PASS: arg=0x%08x golden=0x%08x sent=0x%08x",
            pcrc_arg,
            pcrc_golden,
            pcrc_sent,
        )
        await self._check_alive("post-bad-payload-crc")

        # --- CHK-OTP: cold OTP read-lock, one identity bit --------------------
        rc, arg = await self.km.send_raw_expect_rc(KM_CMD_OTP_READ_LOCK_COLD, [_OTP_LOCK_IDENTITY])
        assert rc == KM_RC_SUCCESS, f"CHK-OTP FAIL: lock identity bit rc={rc}"
        # firmware.adoc, "0x28 - CMD_OTP_READ_LOCK_COLD": RETURN_ARG is the
        # OTP_READ_LOCK_COLD value after the write. This is the leaf's first lock,
        # so the value is the register's cold-reset value with SEP_SYS_ID set.
        assert arg == _OTP_LOCK_COLD_AFTER_ID, (
            f"CHK-OTP FAIL: RETURN_ARG 0x{arg:08x}, expected 0x{_OTP_LOCK_COLD_AFTER_ID:08x} "
            "(OTP_READ_LOCK_COLD reset value with the SEP_SYS_ID bit set)"
        )
        rc, _ = await self.km.send_raw_expect_rc(KM_CMD_OTP_READ_LOCK_COLD, [_OTP_LOCK_RESERVED])
        assert rc == KM_RC_INVALID_ARG, (
            f"CHK-OTP FAIL: reserved lock bit returned rc={rc}, expected {KM_RC_INVALID_ARG}"
        )
        await self._check_alive("post-otp-reserved-bit")
        rc, _ = await self.km.send_raw_expect_rc(KM_CMD_OTP_READ_LOCK_COLD, [])
        assert rc == KM_RC_INVALID_LEN, (
            f"CHK-OTP FAIL: zero-length lock payload returned rc={rc}, expected {KM_RC_INVALID_LEN}"
        )
        self.logger.info(
            "CHK-OTP PASS: lock_arg=0x%08x identity bit locked and echoed; reserved bit "
            "RC_INVALID_ARG; empty payload RC_INVALID_LEN",
            arg,
        )
        await self._check_alive("post-otp-lock")

        # --- CHK-RECOV: SEP flush raises recoverable fault, ACK clears it -----
        await self.poll_internal_irq(_KM_RECOV, 0)
        flushed_bit = 1 << KM_IRQ_FLUSHED_BY_KM
        irq_pre = await self.km.read_irq_status()
        await self.km.write_irq_status(flushed_bit)
        irq_clr = await self.km.read_irq_status()
        assert irq_pre & flushed_bit and not irq_clr & flushed_bit, (
            f"CTRL-FLUSHED-BY-KM-CLR FAIL: SEP_IRQ_STATUS=0x{irq_pre:08x} before and "
            f"0x{irq_clr:08x} after the write of 0x{flushed_bit:08x}, expected flushed_by_km "
            "1 then 0"
        )
        self.logger.info(
            "CTRL-FLUSHED-BY-KM-CLR PASS: SEP_IRQ_STATUS pre=0x%08x clr=0x%08x "
            "flushed_by_km pre=1 exp_pre=1 clr=0 exp_clr=0",
            irq_pre,
            irq_clr,
        )
        await self.km.flush()
        self.km.reset_host_seq()
        words = await self.km.recv_unsolicited(KM_RESP_RECOVERABLE_FAULT)
        payload_len = (words[0] >> 16) & 0xFF
        assert payload_len >= 1, (
            f"CHK-RECOV FAIL: fault frame has no payload ({[hex(w) for w in words]})"
        )
        fault_raw = words[1] & 0xFF
        fault = fault_raw - 256 if fault_raw >= 128 else fault_raw
        assert fault == _RFAULT_FLUSHED_BY_SEP, (
            f"CHK-RECOV FAIL: fault code {fault}, expected {_RFAULT_FLUSHED_BY_SEP} "
            "(FLUSHED_BY_SEP)"
        )
        await self.poll_internal_irq(_KM_RECOV, 1)
        rc, arg = await self.km.stat()
        assert rc == KM_RC_SUCCESS and (arg & 0x1) == 1, (
            f"CHK-RECOV FAIL: CMD_STAT after flush rc={rc} arg=0x{arg:08x}, "
            "expected recoverable bit set"
        )
        rc, _ = await self.km.send_raw_expect_rc(KM_CMD_RECOV_ACK, [])
        assert rc == KM_RC_SUCCESS, f"CHK-RECOV FAIL: CMD_RECOV_ACK rc={rc}"
        rc, arg = await self.km.stat()
        assert rc == KM_RC_SUCCESS and (arg & 0x1) == 0, (
            f"CHK-RECOV FAIL: CMD_STAT after ACK rc={rc} arg=0x{arg:08x}, "
            "expected recoverable bit clear"
        )
        await self.poll_internal_irq(_KM_RECOV, 0)
        self.logger.info(
            "CHK-RECOV PASS: flush posted RESP_RECOVERABLE_FAULT code %d; "
            "CMD_RECOV_ACK cleared STAT bit 0 and aggregator [%d]",
            fault,
            _KM_RECOV,
        )
        irq_post = await self.km.read_irq_status()
        flushed_post = irq_post >> KM_IRQ_FLUSHED_BY_KM & 1
        assert flushed_post == 0, (
            f"CHK-SEP-FLUSH-NO-PEER FAIL: SEP_IRQ_STATUS=0x{irq_post:08x} after the SEP flush "
            f"has flushed_by_km={flushed_post}, expected 0 (firmware.adoc:983,1112-1113; "
            "architecture.adoc:240-241)"
        )
        self.logger.info(
            "CHK-SEP-FLUSH-NO-PEER PASS: contract=key_manager/doc/architecture.adoc:240-241"
            "(mailbox_flush),firmware.adoc:983(flushed_by_sep),:1112-1113 "
            "SEP_IRQ_STATUS=0x%08x flushed_by_km=%d exp_flushed_by_km=0",
            irq_post,
            flushed_post,
        )

        # --- CHK-GONE: a shredded engine will not run -------------------------
        # After every AES leg: the engine is left with no valid key, so it parks
        # waiting for one; nothing after this point may need it. This is the
        # direct observation of the shred: the engine key registers are
        # write-only, so refusal to start is the only frontdoor evidence that
        # the shred reached the key rather than just returning success.
        #
        # Positive control: re-key AES with KAT_KEY_B and run one sideload
        # block right before the shred, with the same start and the same
        # bounded window as the refusal below. The output must appear inside
        # that window and match the golden, so the key is live at the shred,
        # the window is long enough for a keyed block, and a missing output
        # afterwards is the shred's doing.
        rc, _, loaded_b = await self._aes_transfer_captured(aes_writes, handle_b)
        assert rc == KM_RC_SUCCESS, (
            f"CHK-GONE FAIL: pre-shred CMD_KEY_TRANSFER of handle 0x{handle_b:02x} rc={rc}"
        )
        await self.aes.configure_ecb_enc_256(sideload=True)
        await self.aes.trigger_prng_reseed()
        await self.aes.start_block_no_wait(list(AES_ECB_PT))
        assert await self.aes.output_valid_within(_SHRED_REFUSE_POLLS), (
            "CHK-GONE FAIL: the pre-shred control block with KAT_KEY_B sideloaded produced "
            f"no output in {_SHRED_REFUSE_POLLS} polls, so the key was not live before the "
            "shred or the refusal window is too short to grade"
        )
        ct_live = await self.aes.read_data_out()
        assert ct_live == golden_b, (
            "CHK-GONE FAIL: the pre-shred control block did not encrypt to KAT_KEY_B's "
            "golden, so the key was not live before the shred:\n"
            f"  ct     ={[hex(w) for w in ct_live]}\n"
            f"  golden ={[hex(w) for w in golden_b]}"
        )
        rc, _, shred_beats = await self._aes_shred(aes_writes)
        assert rc == KM_RC_SUCCESS, f"CHK-GONE FAIL: final CMD_ENGINE_SHRED rc={rc}"
        self._check_shred_fill(2, aes_writes, shred_beats, KAT_KEY_B, loaded_b, shred1_data)
        # Same configure + PRNG reseed as the control block above, so the
        # shredded sideload key is the only difference from a start that runs.
        await self.aes.configure_ecb_enc_256(sideload=True)
        await self.aes.trigger_prng_reseed()
        await self.aes.start_block_no_wait(list(AES_ECB_PT))
        assert not await self.aes.output_valid_within(_SHRED_REFUSE_POLLS), (
            "CHK-GONE FAIL: the AES produced a result with sideload selected after its "
            "key was shredded -- the shred did not reach the key"
        )
        # INPUT_READY reads 0 while the written DATA_IN block is not loaded
        # (OpenTitan aes registers.md, STATUS.INPUT_READY), and a sideload start
        # waits for a valid key (theory_of_operation.md, key sideload). A start
        # the AES never latched leaves INPUT_READY at 1.
        status_after = await self.aes.read_status()
        assert not status_after >> AES_STATUS_INPUT_READY & 1, (
            f"CHK-GONE FAIL: STATUS=0x{status_after:08x} after the refusal window has "
            "INPUT_READY=1, so the AES did not hold the written block and the missing output "
            "does not show a refused start"
        )
        self.logger.info(
            "CHK-GONE PASS: pre-shred sideload block gave output within %d polls, "
            "ct=%s == AES(KAT_KEY_B, PT) golden; after CMD_ENGINE_SHRED the same start "
            "produced no output in %d polls with the block held (STATUS=0x%08x, "
            "input_ready=0) (fail-closed START)",
            _SHRED_REFUSE_POLLS,
            [hex(w) for w in ct_live],
            _SHRED_REFUSE_POLLS,
            status_after,
        )

        # --- CHK-VAULT-FILL / CHK-VAULT-FULL: fill the KPV, then exhaust it ---
        # The live keys hold one slot each (16 words or fewer); the revoked key's
        # slot is free again (firmware.adoc, "Key Management", Revoke).
        live = {
            "gen2": (gen_handle2, GEN_KEY_WORDS[1]),
            "a": (handle_a, len(KAT_KEY_A)),
            "abr": (handle_abr, len(_ABR_SEED)),
            "b": (handle_b, len(KAT_KEY_B)),
        }
        assert all(words <= KPV_SLOT_WORDS for _, words in live.values()), (
            "test construction error: a live key spans more than one KPV slot"
        )
        await self._vault_fill(cfg, live, revoked=gen_handle)
        await self._revoke_twice(gen_handle, "full-vault", full_vault=True)

        # --- CHK-OTP-CHG-DORMANT: the OTP-change bit stays set -----------------
        await self._otp_change_dormant(otp_en_boot)

        # --- CHK-VAULT-WARM-LOAD: a warm reset re-opens the full vault ---------
        # handle_b was live and AES-permitted at the reset and is never revoked.
        await self._vault_warm_load(stale=handle_b)

        # --- EOT --------------------------------------------------------------
        await self.km.check_outbound_empty("EOT")
        await self.aes.check_status_clean("EOT")
        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        assert self.drbg_sb.report()
        self.logger.info("INFO-ENTROPY-CLEAN entropy alerts clear, DRBG scoreboard reports pass")

    async def _resp_cmd(self, cmd: int, payload: list[int]) -> tuple[int, int | None]:
        """Send one command and decode its RESP_CMD; RETURN_ARG is None when absent.

        ``recv_frame`` checks the header CRC-8, the declared length, the
        payload CRC-32C and the response sequence. The RESP_CMD payload is
        [cmd_seq, cmd_id, rc, arg?] (firmware.adoc, "0x00 - RESP_CMD").
        """
        seq = await self.km.send_command(cmd, payload)
        words = await self.km.recv_frame()
        resp_id = (words[0] >> 8) & 0xFF
        payload_len = (words[0] >> 16) & 0xFF
        assert resp_id == KM_RESP_CMD and payload_len >= 3, (
            f"cmd 0x{cmd:02x}: expected a RESP_CMD with at least 3 payload words, "
            f"got frame {[hex(w) for w in words]}"
        )
        assert (words[1] & 0xFF) == seq and (words[2] & 0xFF) == cmd, (
            f"cmd 0x{cmd:02x} seq {seq}: RESP_CMD echoes seq {words[1] & 0xFF} "
            f"cmd 0x{words[2] & 0xFF:02x}"
        )
        await self.km.check_outbound_empty(f"POST-RESP-0x{cmd:02x}")
        rc_raw = words[3] & 0xFF
        rc = rc_raw - 256 if rc_raw >= 128 else rc_raw
        return rc, (words[4] if payload_len >= 4 else None)

    def _check_boot_irq(self, en: int, status: int) -> None:
        """CHK-BOOT-IRQ-EN and CHK-BOOT-IRQ-STATUS on the RESP_KM_READY sample."""
        assert en == BOOT_IRQ_ENABLE, (
            f"CHK-BOOT-IRQ-EN FAIL: KMCSR IRQ_ENABLE[11:0]=0x{en:03x}, expected "
            f"0x{BOOT_IRQ_ENABLE:03x} (diff 0x{en ^ BOOT_IRQ_ENABLE:03x}; firmware.adoc:1349-1352, "
            ":1626)"
        )
        self.logger.info(
            "CHK-BOOT-IRQ-EN PASS: contract=key_manager/doc/firmware.adoc:1349-1352"
            "(Boot_Sequence),:1626(OTP_Change_Status) irq_enable=0x%03x exp=0x%03x",
            en,
            BOOT_IRQ_ENABLE,
        )
        set_names = [name for bm, name in _IRQ_STATUS_NAMES.items() if status & bm]
        assert status == 0, (
            f"CHK-BOOT-IRQ-STATUS FAIL: KMCSR IRQ_STATUS[11:0]=0x{status:03x} {set_names}, "
            "expected 0x000 (firmware.adoc:1349, :1532-1533)"
        )
        self.logger.info(
            "CHK-BOOT-IRQ-STATUS PASS: contract=key_manager/doc/firmware.adoc:1349"
            "(Boot_Sequence),:1532-1533(Interrupt_Priority) irq_status=0x%03x exp=0x000",
            status,
        )

    def _check_boot_fetch(self, fetch: _KmFetchWatch) -> None:
        """CTRL-BOOT-FETCH-DECODE, then CHK-BOOT-SRAM-LOCK-NOWR, on the boot window."""
        n_en = fetch.stores[KMCSR_IRQ_ENABLE_ADDR]
        n_lock = fetch.stores[KMCSR_SRAM_LOCK_ADDR]
        fields = (
            f"clocks={fetch.clocks} xz={fetch.xz} rst_n_low={int(fetch.rst_low)} "
            f"rst_n_rose={int(fetch.rst_rose)} stores={fetch.total} "
            f"irq_enable_stores={n_en} sram_lock_stores={n_lock} "
            f"irq_enable_addr=0x{KMCSR_IRQ_ENABLE_ADDR:08x} "
            f"sram_lock_addr=0x{KMCSR_SRAM_LOCK_ADDR:08x}"
        )
        assert fetch.xz == 0 and fetch.rst_low and fetch.rst_rose and n_en >= 1, (
            f"CTRL-BOOT-FETCH-DECODE FAIL: {fields}, expected xz=0, km_cpu_rst_n_o 0 then 1, "
            "irq_enable_stores>=1"
        )
        self.logger.info(
            "CTRL-BOOT-FETCH-DECODE PASS: %s exp_xz=0 exp_rst_n=0_then_1 exp_irq_enable_stores>=1",
            fields,
        )
        assert n_lock == 0, (
            f"CHK-BOOT-SRAM-LOCK-NOWR FAIL: {n_lock} KM CPU store(s) to KMCSR SRAM_LOCK "
            f"(0x{KMCSR_SRAM_LOCK_ADDR:08x}) between the KM release and RESP_KM_READY, "
            f"expected 0: {fields}"
        )
        self.logger.info(
            "CHK-BOOT-SRAM-LOCK-NOWR PASS: contract=key_manager/doc/firmware.adoc:1341-1394"
            "(Boot_Sequence),architecture.adoc:1140-1145(Write-lock_policy) "
            "sram_lock_stores=%d exp=0 window=release..RESP_KM_READY",
            n_lock,
        )

    async def _gen_dest(self, handle: int, cfg: SepKmCommandSetCfg) -> None:
        """CHK-GEN-DEST: the generated key is refused to refuse_dest and moves to gen_dest.

        Both engines are released and idle for their beat, then parked again.
        The KM-BUS key-path watch runs from the command send to its RESP_CMD.
        """
        watch = _KeyBusWatch(self)
        refuse_name = DEST_NAME[cfg.refuse_dest]
        await self._release_ready(refuse_name, "gen-refuse-release")
        sw_reset_n = await self.swrst.read_back()
        watch.start()
        rc, arg = await self._resp_cmd(KM_CMD_KEY_TRANSFER, [handle, cfg.refuse_dest])
        await watch.stop()
        await self.swrst.park(refuse_name)
        refuse = (
            f"refuse_dest=0x{cfg.refuse_dest:02x}({refuse_name}) sw_reset_n=0x{sw_reset_n:08x} "
            f"rc={rc} exp_rc={KM_RC_FAILURE} arg={_arg_str(arg)} exp_arg=none "
            f"xz={watch.xz} ports[{watch.counts()}] exp_all=0"
        )
        refuse_ok = (
            sw_reset_n >> SW_RESET_N_BIT[refuse_name] & 1
            and rc == KM_RC_FAILURE
            and arg is None
            and watch.xz == 0
            and not any(watch.aw)
            and not any(watch.w)
        )
        assert refuse_ok, f"CHK-GEN-DEST FAIL [refusal]: handle=0x{handle:02x} {refuse}"
        await self._check_alive("post-gen-dest-refusal")

        gen_name = DEST_NAME[cfg.gen_dest]
        port = _KEY_PORT_NAME.index(gen_name)
        await self._release_ready(gen_name, "gen-allow-release")
        watch.start()
        rc, arg = await self.km.key_transfer(handle=handle, dest=cfg.gen_dest)
        await watch.stop()
        await self.swrst.park(gen_name)
        echo = (arg & 0xFF, (arg >> 8) & 0xFF)
        others = [p for p in range(len(_KEY_PORT_NAME)) if p != port]
        allow = (
            f"gen_dest=0x{cfg.gen_dest:02x}({gen_name}) rc={rc} exp_rc={KM_RC_SUCCESS} "
            f"arg=0x{arg:08x} echo_handle=0x{echo[0]:02x} exp_handle=0x{handle:02x} "
            f"echo_dest=0x{echo[1]:02x} exp_dest=0x{cfg.gen_dest:02x} xz={watch.xz} "
            f"ports[{watch.counts()}] exp_{gen_name}:aw=w>=1,others=0"
        )
        allow_ok = (
            rc == KM_RC_SUCCESS
            and echo == (handle, cfg.gen_dest)
            and watch.xz == 0
            and watch.aw[port] >= 1
            and watch.aw[port] == watch.w[port]
            and not any(watch.aw[p] or watch.w[p] for p in others)
        )
        assert allow_ok, f"CHK-GEN-DEST FAIL [allow]: handle=0x{handle:02x} {allow}"
        self.logger.info(
            "CHK-GEN-DEST PASS: contract=key_manager/doc/firmware.adoc:497-500"
            "(0x24_CMD_KEY_TRANSFER_Response),:504-506 handle=0x%02x refusal: %s; allow: %s",
            handle,
            refuse,
            allow,
        )

    async def _vault_fill(self, cfg: SepKmCommandSetCfg, live: dict, *, revoked: int) -> None:
        """CHK-VAULT-FILL, then CHK-VAULT-FULL on the full vault."""
        free = KPV_SLOTS - len(live)
        self.logger.info(
            "INFO-VAULT-FILL kpv_slots=%d live_keys=%s free_slots=%d req_sizes=%s",
            KPV_SLOTS,
            {k: f"0x{h:02x}/{w}w" for k, (h, w) in live.items()},
            free,
            list(cfg.fill_sizes[: free + 1]),
        )
        seen = {h for h, _ in live.values()} | {revoked}
        bad: list[str] = []
        for i in range(free):
            req = cfg.fill_sizes[i]
            rc, arg = await self._resp_cmd(KM_CMD_KEY_GENERATE, [req, KM_DEST_AES])
            handle = (arg or 0) & 0xFF
            if rc != KM_RC_SUCCESS or arg is None or handle in seen or handle == 0:
                bad.append(f"#{i}:req={req},rc={rc},arg={_arg_str(arg)}")
            seen.add(handle)
        assert not bad, (
            f"CHK-VAULT-FILL FAIL: {len(bad)} of {free} single-slot CMD_KEY_GENERATE "
            f"commands did not return rc=0 with a new non-null handle: {bad[:8]}"
        )
        self.logger.info(
            "CHK-VAULT-FILL PASS: contract=key_manager/doc/firmware.adoc:1929-1931"
            "(Key_Management_Load),:396-397(0x22_CMD_KEY_GENERATE),"
            "architecture.adoc:414(KPV) generated=%d exp_generated=%d rc=0 all "
            "new_handles=%d",
            free - len(bad),
            free,
            len(seen) - len(live) - 1,
        )

        full_req = cfg.fill_sizes[free]
        gen_rc, gen_arg = await self._resp_cmd(KM_CMD_KEY_GENERATE, [full_req, KM_DEST_AES])
        load_rc, load_arg = await self._resp_cmd(KM_CMD_KEY_LOAD, list(_ONE_SLOT_LOAD))
        full_ok = gen_rc == KM_RC_FAILURE and load_rc == KM_RC_FAILURE and load_arg is None
        assert full_ok, (
            f"CHK-VAULT-FULL FAIL: on the full vault CMD_KEY_GENERATE rc={gen_rc} "
            f"arg={_arg_str(gen_arg)} and CMD_KEY_LOAD rc={load_rc} "
            f"arg={_arg_str(load_arg)}, expected rc={KM_RC_FAILURE} for both and no "
            "RETURN_ARG for the load"
        )
        self.logger.info(
            "CHK-VAULT-FULL PASS: contract=key_manager/doc/firmware.adoc:395-396"
            "(0x22_CMD_KEY_GENERATE),:680-682(0x26_CMD_KEY_LOAD) gen_rc=%d gen_req=%d "
            "load_rc=%d load_arg=%s exp_rc=%d exp_load_arg=none",
            gen_rc,
            full_req,
            load_rc,
            _arg_str(load_arg),
            KM_RC_FAILURE,
        )
        self.logger.info("OBS-VAULT-FULL-GEN-ARG LOG arg=%s", _arg_str(gen_arg))
        await self._check_alive("post-vault-full")

    async def _aes_shred(self, cap: _AesKeyPortWrites) -> tuple[int, int, int]:
        """CMD_ENGINE_SHRED of AES under the key-path capture.

        Returns (return_code, return_arg, CHK5_km EDN->KM beats during the
        command). The capture opens before the frame is sent and closes after
        RESP_CMD, which the KM sends when the shred is complete.
        """
        beats0 = self.drbg_sb.results["CHK5_km"].dut_items
        cap.start()
        rc, arg = await self.km.engine_shred(dest=KM_DEST_AES)
        beats = self.drbg_sb.results["CHK5_km"].dut_items - beats0
        await cap.stop()
        return rc, arg, beats

    async def _aes_transfer_captured(
        self, cap: _AesKeyPortWrites, handle: int
    ) -> tuple[int, int, _ShareWrites]:
        """CMD_KEY_TRANSFER of ``handle`` to AES under the key-path capture.

        Returns (return_code, return_arg, the share writes of the transfer).
        """
        cap.start()
        rc, arg = await self.km.key_transfer(handle=handle, dest=KM_DEST_AES)
        await cap.stop()
        return rc, arg, _ShareWrites(cap)

    def _check_shred_fill(
        self,
        shred: int,
        cap: _AesKeyPortWrites,
        drbg_beats: int,
        key: tuple[int, ...],
        loaded: _ShareWrites,
        prev: tuple[int, ...] | None,
    ) -> tuple[int, ...]:
        """CHK-SHRED-FILL and INFO-SHRED-FILL of one AES shred.

        ``loaded`` is the capture of the CMD_KEY_TRANSFER that loaded ``key``.
        Returns the ordered share data of the shred, which term (e) of the next
        shred compares against.
        """
        sw = _ShareWrites(cap)
        share, other, strobes, lanes = sw.share, sw.other, sw.strobes, sw.lanes
        s0, s1 = sw.vectors
        xor = tuple(a ^ b for a, b in zip(s0, s1))
        l0, l1 = loaded.vectors
        loaded_ok = (
            loaded.clean and not loaded.unwritten and tuple(a ^ b for a, b in zip(l0, l1)) == key
        )
        data = tuple(d for _, d, _ in share)
        distinct = [len({d for off, d, _ in share if off in AES_SHARE_OFFSETS[s]}) for s in (0, 1)]
        per_offset = " ".join(
            f"0x{off:03x}:n={len(v)},strb={'/'.join(f'{x:x}' for x in sorted(set(v))) or '-'}"
            for off, v in strobes.items()
        )
        self.logger.info(
            "INFO-SHRED-FILL shred=%d aw=%d w=%d xz=%d share_beats=%d per_offset=%s other_beats=%s",
            shred,
            len(cap.aw),
            len(cap.w),
            cap.xz,
            len(share),
            per_offset,
            [f"0x{off:03x}=0x{d:08x}/{st:x}" for off, d, st in other],
        )
        unwritten = sw.unwritten
        terms = {
            "capture": sw.clean,
            "a": not unwritten,
            "b": drbg_beats >= _PRNG_SEED_WORDS,
            "c": key not in (s0, s1, xor),
            "d_share0": distinct[0] > 1,
            "d_share1": distinct[1] > 1,
            "e": prev is None or data != prev,
            "f_loaded": loaded_ok,
            "f_share0": s0 != l0,
            "f_share1": s1 != l1,
        }
        failed = [t for t, ok in terms.items() if not ok]
        assert not failed, (
            f"CHK-SHRED-FILL FAIL: shred={shred} failed={failed} aw={len(cap.aw)} "
            f"w={len(cap.w)} xz={cap.xz} unwritten={unwritten} drbg_beats={drbg_beats} "
            f"distinct_share0_values={distinct[0]} distinct_share1_values={distinct[1]} "
            f"share0={[hex(v) for v in s0]} share1={[hex(v) for v in s1]} "
            f"xor={[hex(v) for v in xor]} key={[hex(v) for v in key]} "
            f"same_as_prev={prev is not None and data == prev} "
            f"loaded_aw={len(loaded.cap_aw)} loaded_w={len(loaded.cap_w)} "
            f"loaded_xz={loaded.xz} loaded_unwritten={loaded.unwritten} "
            f"loaded_share0={[hex(v) for v in l0]} loaded_share1={[hex(v) for v in l1]}"
        )
        self.logger.info(
            "CHK-SHRED-FILL PASS: contract=key_manager/doc/firmware.adoc:1803-1805"
            "(Crypto_Engine_Drivers_Shred),:1447-1453(Firmware_PRNG),"
            "architecture.adoc:292-294(Key_Delivery) shred=%d aw=%d w=%d xz=0 "
            "share_offsets=%d all_lanes_written=1 drbg_beats=%d exp_drbg_beats>=%d "
            "share0!=key share1!=key xor!=key distinct_share0_values=%d "
            "distinct_share1_values=%d exp_each>1 differs_from_prev=%s "
            "loaded_aw=%d loaded_w=%d loaded_all_lanes_written=1 loaded_xor==key "
            "share0!=loaded_share0 share1!=loaded_share1",
            shred,
            len(cap.aw),
            len(cap.w),
            len(lanes),
            drbg_beats,
            _PRNG_SEED_WORDS,
            distinct[0],
            distinct[1],
            "n/a" if prev is None else "1",
            len(loaded.cap_aw),
            len(loaded.cap_w),
        )
        return data

    async def _revoke_twice(self, handle: int, site: str, *, full_vault: bool) -> None:
        """CHK-REVOKE-TWICE: a revoke of a revoked handle is refused and frees nothing.

        On the full vault the slot the revoked key held is in use again, so a
        revoke that freed it would let the single-slot load that follows
        succeed.
        """
        rc, arg = await self._resp_cmd(KM_CMD_KEY_REVOKE, [handle])
        self.logger.info("OBS-REVOKE-TWICE LOG site=%s rc=%d", site, rc)
        exp_arg = 0 if rc == KM_RC_INVALID_ARG else None
        assert rc in (KM_RC_INVALID_ARG, KM_RC_FAILURE) and arg == exp_arg, (
            f"CHK-REVOKE-TWICE FAIL [{site}]: CMD_KEY_REVOKE of revoked handle "
            f"0x{handle:02x} returned rc={rc} RETURN_ARG={_arg_str(arg)}, expected "
            f"rc={KM_RC_INVALID_ARG} (RC_INVALID_ARG) with RETURN_ARG 0x00000000 or "
            f"rc={KM_RC_FAILURE} (RC_FAILURE) with none (firmware.adoc:433-439)"
        )
        cites = ":433-439(0x23_CMD_KEY_REVOKE_Response),:1909(Key_Registry_Destroy)"
        slot = ""
        if full_vault:
            load_rc, load_arg = await self._resp_cmd(KM_CMD_KEY_LOAD, list(_ONE_SLOT_LOAD))
            assert load_rc == KM_RC_FAILURE and load_arg is None, (
                f"CHK-REVOKE-TWICE FAIL [{site}]: after the refused revoke the single-slot "
                f"CMD_KEY_LOAD on the full vault returned rc={load_rc} "
                f"RETURN_ARG={_arg_str(load_arg)}, expected rc={KM_RC_FAILURE} with none "
                "(firmware.adoc:680-682) -- the refused revoke freed a slot"
            )
            cites += ",:680-682(0x26_CMD_KEY_LOAD)"
            slot = (
                f" load_rc={load_rc} load_arg={_arg_str(load_arg)} "
                f"exp_load_rc={KM_RC_FAILURE} exp_load_arg=none"
            )
        self.logger.info(
            "CHK-REVOKE-TWICE PASS: contract=key_manager/doc/firmware.adoc%s site=%s "
            "handle=0x%02x rc=%d arg=%s exp_arg=%s%s",
            cites,
            site,
            handle,
            rc,
            _arg_str(arg),
            _arg_str(exp_arg),
            slot,
        )
        await self._check_alive(f"post-revoke-twice-{site}")

    async def _vault_warm_load(self, *, stale: int) -> None:
        """CHK-VAULT-WARM-LOAD: after a KM warm reset the full vault takes a load
        from handle 1, a pre-reset handle is refused, and handle 1 transfers to AES."""
        km_bit = 1 << SW_RESET_N_BIT["km"]
        await self.swrst.park("km")
        parked = await self.swrst.read_back()
        await self.swrst.release("km")
        released = await self.swrst.read_back()
        assert not parked & km_bit and released & km_bit, (
            f"CHK-VAULT-WARM-LOAD FAIL: SW_RESET_N read back 0x{parked:08x} after the KM "
            f"park and 0x{released:08x} after the release, expected the km bit "
            f"(0x{km_bit:08x}) 0 and then 1"
        )
        self.km.reset_host_seq()
        await self.km.wait_km_ready()

        rc, arg = await self._resp_cmd(KM_CMD_KEY_LOAD, list(_ONE_SLOT_LOAD))
        word = arg or 0
        handle = word & 0xFF
        size = (word >> 8) & 0x7F
        dest = (word >> 16) & 0xFF
        fields = (
            f"sw_reset_n_parked=0x{parked:08x} sw_reset_n_released=0x{released:08x} "
            f"km_ready=1 rc={rc} arg={_arg_str(arg)} handle=0x{handle:02x} "
            f"exp_handle=0x{_FIRST_HANDLE:02x} size={size} exp_size={_ONE_SLOT_LOAD[0]} "
            f"dest=0x{dest:02x} exp_dest=0x{KM_DEST_AES:02x}"
        )
        load_ok = (
            rc == KM_RC_SUCCESS
            and arg is not None
            and handle == _FIRST_HANDLE
            and size == _ONE_SLOT_LOAD[0]
            and dest == KM_DEST_AES
        )
        assert load_ok, (
            "CHK-VAULT-WARM-LOAD FAIL: after the warm reset the single-slot CMD_KEY_LOAD "
            f"that the full vault refused did not succeed from a fresh registry: {fields}"
        )
        assert stale != handle, (
            f"test construction error: pre-reset handle 0x{stale:02x} is the handle the "
            "new registry issued"
        )

        rc, arg = await self._resp_cmd(KM_CMD_KEY_TRANSFER, [stale, KM_DEST_AES])
        self.logger.info("OBS-WARM-STALE-HANDLE LOG handle=0x%02x rc=%d", stale, rc)
        assert rc == KM_RC_FAILURE and arg is None, (
            f"CHK-VAULT-WARM-LOAD FAIL: CMD_KEY_TRANSFER of pre-reset handle 0x{stale:02x} "
            f"to AES after the warm reset returned rc={rc} RETURN_ARG={_arg_str(arg)}, "
            f"expected rc={KM_RC_FAILURE} (RC_FAILURE) with none for an unavailable handle "
            "(firmware.adoc:1069-1070, :491-499)"
        )
        await self._check_alive("post-warm-stale-handle")

        xfer_rc, xfer_arg = await self.km.key_transfer(handle=handle, dest=KM_DEST_AES)
        xfer_echo = (xfer_arg & 0xFF, (xfer_arg >> 8) & 0xFF)
        assert xfer_rc == KM_RC_SUCCESS and xfer_echo == (handle, KM_DEST_AES), (
            f"CHK-VAULT-WARM-LOAD FAIL: CMD_KEY_TRANSFER of new handle 0x{handle:02x} to AES "
            f"after the warm reset returned rc={xfer_rc} RETURN_ARG=0x{xfer_arg:08x}, expected "
            f"rc={KM_RC_SUCCESS} with handle 0x{handle:02x} and dest 0x{KM_DEST_AES:02x} "
            "echoed (firmware.adoc:504-513)"
        )
        self.logger.info(
            "CHK-VAULT-WARM-LOAD PASS: contract=key_manager/doc/firmware.adoc:1382"
            "(Boot_Sequence),:1889-1895(Key_Registry),:690-691(0x26_CMD_KEY_LOAD),"
            ":1763-1764(KPV_Driver),:1069-1070(Key_Transfer_and_Sideload_Purge),"
            ":491-499(0x24_CMD_KEY_TRANSFER_Response),"
            ":504-513(Key_Transfer_Success_Response),architecture.adoc:441(KPV) %s "
            "stale_handle=0x%02x stale_rc=%d exp_stale_rc=%d stale_arg=%s exp_stale_arg=none "
            "xfer_rc=%d exp_xfer_rc=%d xfer_arg=0x%08x xfer_handle=0x%02x exp_xfer_handle=0x%02x "
            "xfer_dest=0x%02x exp_xfer_dest=0x%02x",
            fields,
            stale,
            rc,
            KM_RC_FAILURE,
            _arg_str(arg),
            xfer_rc,
            KM_RC_SUCCESS,
            xfer_arg,
            xfer_echo[0],
            handle,
            xfer_echo[1],
            KM_DEST_AES,
        )
        await self._check_alive("post-warm-transfer")

    async def _otp_change_dormant(self, en_boot: int) -> None:
        """CHK-OTP-CHG-DORMANT: one OTP_CHANGE pulse enters no KMCSR ISR."""
        top = cocotb.top
        en_pre = self.rd_known(top.km_csr_irq_enable_o)
        ent0 = self.rd_known(top.km_kmcsr_irq_entry_count_o)
        try:
            await RisingEdge(top.clk_i)
            top.km_irqset_mask_i.value = OTP_CHANGE
            top.km_irqset_arm_i.value = 1
            fired = 0
            for _ in range(8):
                await RisingEdge(top.clk_i)
                await ReadOnly()
                fired = self.rd_known(top.km_irqset_fired_o)
                if fired == 1:
                    break
            await RisingEdge(top.clk_i)
        finally:
            top.km_irqset_arm_i.value = 0
            top.km_irqset_mask_i.value = 0
        rose = False
        for _ in range(64):
            await RisingEdge(top.clk_i)
            await ReadOnly()
            if self.rd_known(top.km_csr_irq_status_o) & OTP_CHANGE:
                rose = True
                break
        assert fired == 1 and rose, (
            f"CHK-OTP-CHG-DORMANT FAIL: the control pulse did not land: fired={fired} "
            f"status_otp_change={int(rose)}"
        )
        low = 0
        for _ in range(OTP_QUIET_CLKS):
            await RisingEdge(top.clk_i)
            await ReadOnly()
            if not self.rd_known(top.km_csr_irq_status_o) & OTP_CHANGE:
                low += 1
        entries = self.rd_known(top.km_kmcsr_irq_entry_count_o) - ent0
        en_post = self.rd_known(top.km_csr_irq_enable_o)
        await RisingEdge(top.clk_i)
        ok = (
            (en_boot & OTP_CHANGE_EN) == 0
            and (en_pre & OTP_CHANGE_EN) == 0
            and (en_post & OTP_CHANGE_EN) == 0
            and low == 0
            and entries == 0
        )
        fields = (
            f"en_boot=0x{en_boot:03x} en_pre=0x{en_pre:03x} en_post=0x{en_post:03x} "
            f"exp_otp_change_en=0 samples={OTP_QUIET_CLKS} samples_low={low} "
            f"exp_samples_low=0 kmcsr_irq_entries={entries} exp_kmcsr_irq_entries=0 "
            f"control_fired={fired} control_rose={int(rose)}"
        )
        assert ok, f"CHK-OTP-CHG-DORMANT FAIL: {fields}"
        self.logger.info(
            "CHK-OTP-CHG-DORMANT PASS: contract=key_manager/doc/firmware.adoc:1624-1626"
            "(OTP_Change_Status) %s",
            fields,
        )
        await self._check_alive("post-otp-change")

    async def _arg_edge(self, revoked: int) -> None:
        """Key commands with a reserved argument bit, an empty mask or an
        out-of-range field. Each targets the revoked handle or the unused ML-KEM
        message engine, so a command the KM accepts changes no state a later
        check reads. The two CMD_KEY_GENERATE frames are graded (CHK-GEN-ARG);
        the others are logged (OBS-CMD-ARG-EDGE)."""
        cases = (
            ("revoke_rsvd", KM_CMD_KEY_REVOKE, [revoked | _ARG_RESERVED]),
            ("transfer_rsvd", KM_CMD_KEY_TRANSFER, [revoked | _ARG_RESERVED, KM_DEST_AES]),
            ("transfer_mask0", KM_CMD_KEY_TRANSFER, [revoked, 0]),
            ("shred_rsvd", KM_CMD_ENGINE_SHRED, [KM_DEST_ABR_MLKEM_MSG | _ARG_RESERVED]),
            ("shred_mask0", KM_CMD_ENGINE_SHRED, [0]),
            ("generate_size", KM_CMD_KEY_GENERATE, [_REQ_SIZE_OVER, KM_DEST_ABR_MLKEM_MSG]),
            (
                "generate_dest",
                KM_CMD_KEY_GENERATE,
                [GEN_KEY_WORDS[0] - 1, KM_DEST_ABR_MLKEM_MSG | _ARG_RESERVED],
            ),
        )
        # firmware.adoc "0x22 - CMD_KEY_GENERATE" states RC_INVALID_ARG with the
        # index of the invalid payload word: 0 for REQ_SIZE, 1 for DEST_VALID.
        graded_arg = {"generate_size": 0, "generate_dest": 1}
        for case, cmd, payload in cases:
            if case in graded_arg:
                # The graded frames require a RETURN_ARG on the wire: a missing
                # one would read as 0, which is the golden of generate_size.
                seq = await self.km.send_command(cmd, payload)
                rc, arg = await self.km.recv_resp_cmd(cmd, seq, require_arg=True)
                await self.km.check_outbound_empty(f"POST-RAW-0x{cmd:02x}")
            else:
                rc, arg = await self.km.send_raw_expect_rc(cmd, payload)
            if case not in graded_arg:
                self.logger.info(
                    "OBS-CMD-ARG-EDGE LOG cmd=0x%02x case=%s code=%d arg=0x%08x",
                    cmd,
                    case,
                    rc,
                    arg,
                )
                continue
            exp_arg = graded_arg[case]
            assert rc == KM_RC_INVALID_ARG and arg == exp_arg, (
                f"CHK-GEN-ARG FAIL: case={case} code={rc} arg=0x{arg:08x}, expected "
                f"code={KM_RC_INVALID_ARG} (RC_INVALID_ARG) arg=0x{exp_arg:08x}"
            )
            self.logger.info("CHK-GEN-ARG PASS: case=%s code=%d arg=0x%08x", case, rc, arg)
        await self._check_alive("post-arg-edge")

    async def _check_alive(self, tag: str) -> None:
        """CHK-ALIVE: the KM is still in its loop and has not latched a fault.

        Both halves matter. While a recoverable fault is pending the KM rejects
        every key command with RC_FAILURE before it ever looks at the
        arguments -- the same code CHK-DEST and CHK-CLOSED assert -- so a
        refusal checker that ran against a faulted KM would pass without the
        policy it names being exercised at all. CMD_STAT stays on the
        allowlist through a fault, so its return code alone cannot see this;
        its return argument carries the recoverable-error bit that can.
        """
        rc, arg = await self.km.stat()
        assert rc == KM_RC_SUCCESS, (
            f"CHK-ALIVE FAIL [{tag}]: CMD_STAT returned rc={rc} after a rejected "
            "command -- the KM did not stay in its command loop"
        )
        assert (arg & 0x1) == 0, (
            f"CHK-ALIVE FAIL [{tag}]: CMD_STAT reports a latched recoverable error "
            f"(arg=0x{arg:08x}). Every key command is refused RC_FAILURE in that "
            "state, so the refusal checkers around here prove nothing"
        )
        self.logger.info("CHK-ALIVE PASS [%s]: CMD_STAT rc=0 and no latched recoverable error", tag)

    async def _release_ready(self, name: str, tag: str) -> None:
        """Release a parked sideload target and wait until it is accepting again.

        A key-bus write to an engine that is still running its post-reset secure
        wipe is refused for that reason, which is the same RC_FAILURE the
        destination-policy checkers expect. Every engine whose driver exposes a
        readiness poll gets one; AES needs none (it is never parked here) and the
        remaining ABR/pool dests have no idle surface on this path.
        """
        await self.swrst.release(name)
        if name == "otbn":
            from seq_lib.sep_otbn_seq import SepOtbn

            await SepOtbn(self).wait_idle(tag)
        elif name == "hmac":
            from seq_lib.sep_hmac_seq import SepHmac

            await SepHmac(self).wait_idle(tag)
        elif name == "kmac":
            from seq_lib.sep_kmac_seq import SepKmac

            await SepKmac(self).wait_idle(tag)

    async def _transfer_seeded_dest(self, handle: int, cfg: SepKmCommandSetCfg) -> None:
        """CHK-XFER-DEST: transfer the loaded handle to the seed-selected dest."""
        dest = cfg.xfer_dest
        name = DEST_NAME[dest]
        extra = dest != KM_DEST_AES
        if extra:
            await self._release_ready(name, "xfer-dest-release")
        rc, arg = await self.km.key_transfer(handle=handle, dest=dest)
        if extra:
            await self.swrst.park(name)
        assert rc == KM_RC_SUCCESS, (
            f"CHK-XFER-DEST FAIL: CMD_KEY_TRANSFER dest=0x{dest:02x} ({name}) rc={rc}"
        )
        assert (arg & 0xFF) == handle and ((arg >> 8) & 0xFF) == dest, (
            f"CHK-XFER-DEST FAIL: RETURN_ARG 0x{arg:08x} does not echo handle "
            f"0x{handle:02x} and dest 0x{dest:02x}"
        )
        self.logger.info(
            "CHK-XFER-DEST PASS: dest=0x%02x (%s) rc=0, load_dest=0x%02x",
            dest,
            name,
            cfg.load_dest,
        )
