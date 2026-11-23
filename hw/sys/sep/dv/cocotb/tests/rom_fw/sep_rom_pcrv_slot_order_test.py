# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""BL0 enrolls PCRV slot 0 after the ROM self-hash recompute, then slot 1 (index and order only).

rom.adoc, Boot Measurement:

    [SEP-ROM-ATT-050] BL0's two measurements occupy separate slots, which are the intended
    future PCRV indices: slot 0 = ROM identity, slot 1 = boot configuration/state — so
    verifiers can distinguish "same ROM" from "same boot configuration".

    [SEP-ROM-ATT-060] Before enrollment, the ROM shall *verify* its embedded self-hash by
    recomputing SHA-256 over the hashed ROM region and comparing against the embedded value;
    a mismatch is fatal (`ROM_ERR_ROM_HASH_MISMATCH`, `0xF005`). The verified hash is enrolled
    into slot 0 and recorded raw in `bl0_state.rom_hash`. This runs after the crypto self-test
    ([S14]) and `bl0_state` initialization ([S10]).

    [SEP-ROM-ATT-030] After the manifest has fully validated and the demotion decision has
    been applied — and before the fuse-secret locks and hand-off — the ROM shall compose the
    boot-state record below, enroll it into slot 1, and store the raw record in
    `bl0_state.meas_boot_record` for BL1. An enrollment failure is fatal
    (`ROM_ERR_MEASUREMENT_FAILED`, `0xF006`).

    Each enrollment emits `SEP_MSG_RECORD_MEASUREMENT` followed by an `INFO_EXT` word
    carrying the slot index.

    [SEP-ROM-ATT-010] (the hashed region) ... the hash covers the `.text` + `.metadata`
    bytes — `[ROM base, __metadata_end)` ...

rom.adoc, cold-boot stages: "[S14] crypto self-test |SHA-256 of `"abc"` computed on the HMAC
block and compared against the NIST reference digest." tbl:stage_trace gives [S14] only the
start code `CRYPTO_INIT_CHECK`, so the end of [S14] is taken from the bus: the first time all
eight SHA-256 `DIGEST` words of the HMAC block have been read after that code.

An enrollment is the RECORD_MEASUREMENT status word on `cold_scratch[1]` and the INFO_EXT
word after it; its time is that of the RECORD_MEASUREMENT record. Between the two only
`STATUS_REPORTING_INVALID` is skipped: SEP-ROM-STAT-010 has the producer report it on the
scratch channel on an invalid ring, and the default DV ring is invalid.

* CHK-SEPARATE-SLOTS: exactly two enrollments, carrying slot 0 and slot 1 (ATT-050, slot
  index only).
* CHK-SLOT0-AFTER-VERIFY: every byte of `[ROM base, __metadata_end)` is read on the LSU ROM
  port before the store of the slot-0 word (ATT-060).
* CHK-VERIFY-AFTER-S14-S10: that complete read starts after the end of [S14] above and after
  the first `BL0_STATE_INIT` word (ATT-060).
* CHK-SLOT0-BEFORE-SLOT1: the slot-0 enrollment precedes the slot-1 enrollment, the order of
  fig:measurement_compose and of the stages [S17] < [S27] (boot flow figures, stage table).
* CHK-SLOT1-AFTER-VALIDATION: `MANIFEST_VALIDATED` < slot-1 enrollment < hand-off `mret`
  (the undisputed part of ATT-030).
* CHK-MEAS-GOLDEN (inherited): the slot-1 soft-PCR value, read back by BL1 from `bl0_state` and
  printed as `BL0S_BOOT_PCR=`, equals the Python golden.

ATT-050 is covered partially: slot index and order only. Not graded: the slot-0 value (ROM
identity) and `bl0_state.rom_hash`, which need BL1 to print `soft_pcr[0]`; the compare against
the embedded value and the 0xF005 / 0xF006 paths; the timing of the soft-PCR memory writes
(the order graded is that of the status words); "the demotion decision has been applied";
"before the fuse-secret locks", which the boot flow figure and stage table contradict
(OBS-SLOT1-VS-LOCK only); `bl0_state.meas_boot_record`.
The leaf runs `sep_boot_measurement_golden_test` (LC=PROD, secure boot) and keeps its checks.
"""

from __future__ import annotations

from pathlib import Path

import cocotb
import pyuvm
from env.sep_chk_log import SepChkLog
from env.sep_fabric_tap import SepFabricTap
from env.sep_rom_observer import STORE_LAG_MAX_CYCLES, SepRomObserver, load_rom_syms
from rom_fw.sep_boot_measurement_golden_test import sep_boot_measurement_golden_test as _Base
from rom_fw.sep_rom_observe_base import ROM_BASE
from sep_reg_meta import sym

_ROM_SIZE = sym("SEP_BOOT_ROM_MEM_SIZE")
_VMEM_ARG = "sep_boot_rom_hex"
_SHA256_DIGEST = frozenset(sym(f"HMAC_DIGEST_{i}__REG_ADDR") for i in range(8))
# STATUS_ENCODE(type, 1 = BL0, code); codes from hw/sys/sep/doc/gen/status_values.adoc.
_INFO, _DEBUG, _ERROR, _INFO_EXT = 0x01, 0x80, 0x0F, 0x81


def _status(kind: int, code: int) -> int:
    return (kind << 24) | (1 << 16) | code


_RECORD_MEASUREMENT = _status(_INFO, 0x0051)
_CRYPTO_INIT_CHECK = _status(_DEBUG, 0x0204)
_BL0_STATE_INIT = _status(_DEBUG, 0x0209)
_MANIFEST_VALIDATED = _status(_INFO, 0x0053)
_FUSE_SECRETS_LOCK = _status(_INFO, 0x021B)
# On an invalid status ring the producer reports this word on the scratch channel per insert.
_RING_INVALID = _status(_ERROR, 0x0079)


def _ps(t: float | None) -> int:
    return -1 if t is None else int(t)


def _enrollments(status: list[tuple[int, int]]) -> list[tuple[int, int | None, list[str]]]:
    """(time, slot or None, following words) of each RECORD_MEASUREMENT record."""
    out = []
    for i, (t, w) in enumerate(status):
        if w != _RECORD_MEASUREMENT:
            continue
        rest = [v for _, v in status[i + 1 : i + 5]]
        nxt = next((v for v in rest if v != _RING_INVALID), None)
        slot = nxt & 0xFFFF if nxt is not None and nxt >> 16 == (_INFO_EXT << 8 | 1) else None
        out.append((t, slot, [f"0x{v:08x}" for v in rest]))
    return out


def _digest_read_t(xbar_ar: list, after: int) -> int | None:
    """Time by which every SHA-256 DIGEST word has been read after ``after``."""
    left = set(_SHA256_DIGEST)
    for b in xbar_ar:
        if b.t_ps > after and b.addr in left:
            left.discard(b.addr)
            if not left:
                return int(b.t_ps)
    return None


@pyuvm.test()
class sep_rom_pcrv_slot_order_test(_Base):
    required_evidence = (
        "CHK-SEPARATE-SLOTS",
        "CHK-SLOT0-AFTER-VERIFY",
        "CHK-VERIFY-AFTER-S14-S10",
        "CHK-SLOT0-BEFORE-SLOT1",
        "CHK-SLOT1-AFTER-VALIDATION",
        "CHK-MEAS-GOLDEN",
    )

    async def run_scenario(self) -> None:
        self.chk = SepChkLog(self, self.get_type_name(), self.random_seed())
        lsu = SepFabricTap("PR-LSU-ROM").start()
        xbar = SepFabricTap("PR-LSU-XBAR").start()
        obs = SepRomObserver(self, keep=lambda _insn: False, tracker=False).start()
        await super().run_scenario()
        await obs.stop()
        await lsu.stop()
        await xbar.stop()
        self._grade(obs, lsu, xbar)
        self.chk.finish()

    def _grade(self, obs: SepRomObserver, lsu: SepFabricTap, xbar: SepFabricTap) -> None:
        chk = self.chk
        syms = load_rom_syms(Path(cocotb.plusargs[_VMEM_ARG]).with_name("boot_rom.sym"))
        end = syms["__metadata_end"]
        chk.ctrl(
            "HASH-REGION",
            ROM_BASE < end <= ROM_BASE + _ROM_SIZE,
            region=f"0x{ROM_BASE:08x}..0x{end:08x}",
        )

        enr = _enrollments(obs.status)
        slots = [s for _, s, _ in enr]
        for t, s, rest in enr:
            chk.obs("ENROLL-WORDS", t_ps=t, slot=-1 if s is None else s, following=rest)
        chk.ok("SEPARATE-SLOTS", slots == [0, 1] or slots == [1, 0], slots=slots)
        t0 = next((t for t, s, _ in enr if s == 0), None)
        t1 = next((t for t, s, _ in enr if s == 1), None)
        chk.ok(
            "SLOT0-BEFORE-SLOT1",
            None not in (t0, t1) and t0 < t1,
            slot0_ps=_ps(t0),
            slot1_ps=_ps(t1),
        )

        clk_ps = (
            (obs.first[-1].t_ps - obs.first[0].t_ps) // (obs.first[-1].cycle - obs.first[0].cycle)
            if len(obs.first) > 1
            else 0
        )
        ar = [b for b in lsu.beats if b.ch == "ar"]
        unknown = sum(1 for b in ar if None in (b.addr, b.len, b.size))
        in_region = [b for b in ar if b.addr is not None and ROM_BASE <= b.addr < end]
        chk.ctrl(
            "LSU-ROM-LIVE",
            bool(in_region) and not unknown and clk_ps > 0,
            ar=len(ar),
            in_region=len(in_region),
            unknown=unknown,
            clk_ps=clk_ps,
        )

        # Latest start of a read of the whole region that completes before the slot-0 store.
        start = None
        if t0 is not None and clk_ps > 0:
            # The status store retires up to STORE_LAG_MAX_CYCLES clk before its record.
            limit = t0 - STORE_LAG_MAX_CYCLES * clk_ps
            seen = bytearray(end - ROM_BASE)
            left = len(seen)
            for b in reversed(ar):
                if b.t_ps >= limit or None in (b.addr, b.len, b.size):
                    continue
                lo = b.addr & ~((1 << b.size) - 1)
                for a in range(max(lo, ROM_BASE), min(lo + ((b.len + 1) << b.size), end)):
                    if not seen[a - ROM_BASE]:
                        seen[a - ROM_BASE] = 1
                        left -= 1
                if left == 0:
                    start = b.t_ps
                    break
            chk.ok(
                "SLOT0-AFTER-VERIFY",
                start is not None,
                read_start_ps=_ps(start),
                limit_ps=limit,
                slot0_ps=t0,
                region_bytes=len(seen),
                unread_bytes=left,
            )
        else:
            chk.ok("SLOT0-AFTER-VERIFY", False, slot0_ps=_ps(t0), clk_ps=clk_ps)
        chk.obs(
            "REGION-READS-BEFORE-VERIFY",
            beats=sum(1 for b in in_region if start is not None and b.t_ps < start),
            read_start_ps=_ps(start),
        )

        t_s14 = obs.status_t(_CRYPTO_INIT_CHECK)
        xbar_ar = [b for b in xbar.beats if b.ch == "ar"]
        t_s14_end = _digest_read_t(xbar_ar, t_s14) if t_s14 is not None else None
        chk.ctrl(
            "S14-DIGEST-READ",
            t_s14_end is not None,
            crypto_init_check_ps=_ps(t_s14),
            digest_read_ps=_ps(t_s14_end),
            xbar_ar=len(xbar_ar),
        )
        nxt = next(((t, w) for t, w in obs.status if t_s14 is not None and t > t_s14), None)
        chk.obs(
            "AFTER-CRYPTO-INIT-CHECK",
            next_word="none" if nxt is None else f"0x{nxt[1]:08x}",
            next_ps=_ps(nxt and nxt[0]),
        )
        t_s10 = obs.status_t(_BL0_STATE_INIT)
        chk.ok(
            "VERIFY-AFTER-S14-S10",
            None not in (start, t_s14_end, t_s10) and max(t_s14_end, t_s10) < start,
            s14_end_ps=_ps(t_s14_end),
            bl0_state_init_ps=_ps(t_s10),
            read_start_ps=_ps(start),
        )

        t_valid = obs.status_t(_MANIFEST_VALIDATED)
        mret = obs.pre_mret[-1].t_ps if obs.pre_mret else None
        chk.ok(
            "SLOT1-AFTER-VALIDATION",
            None not in (t_valid, t1, mret) and t_valid < t1 < mret,
            manifest_validated_ps=_ps(t_valid),
            slot1_ps=_ps(t1),
            mret_ps=_ps(mret),
        )
        # Not graded: ATT-030 and the boot flow figure / stage table disagree on this order.
        chk.obs(
            "SLOT1-VS-LOCK",
            slot1_ps=_ps(t1),
            fuse_secrets_lock_ps=_ps(obs.status_t(_FUSE_SECRETS_LOCK)),
            spec_conflict="ATT-030 text vs boot-flow figure",
        )
        chk.obs(
            "CONSOLE-ORDER",
            rom_hash_verified_ps=_ps(obs.line_t("ROM_HASH_VERIFIED")),
            meas_boot_state_ok_ps=_ps(obs.line_t("MEAS_BOOT_STATE_OK")),
        )
