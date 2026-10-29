# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The Boot ROM reports its version string and self-hash on a cold boot, graded against a
golden hash computed from the ROM image the simulation loaded.

rom.adoc, Boot Measurement:

* SEP-ROM-ATT-020: "The ROM shall report its version string and self-hash at every boot
  ([S05]): the full value through the debug console, and a machine-readable prefix (first 16
  bits × 2) as `INFO_EXT` status words following `SEP_MSG_ROM_HASH` on the status channel."
* SEP-ROM-ATT-010 (the hash definition): "The ROM image shall embed the SHA-256 hash of its
  own code region, computed and inserted at build time (`tools/insert-rom-sha256.py`; the hash
  covers the `.text` + `.metadata` bytes — `[ROM base, __metadata_end)` — and the result is
  stored as an 80-byte ASCII string in `.rodata`, outside the hashed region, so there is no
  circular dependency)."

The golden is SHA-256 over `[ROM base, __metadata_end)` of the `+sep_boot_rom_hex` image,
with nothing masked, since the embedded string lies outside that region.
The prefix is the first 32 digest bits as two 16-bit `INFO_EXT` payloads. The spec does not
define their order; this test reads it as most significant 16 bits first.
`SEP_MSG_ROM_HASH` must be an INFO word: tbl:status_types makes INFO the stage-progress type,
and tbl:stage_trace lists ROM_HASH as a progress code without a DEBUG or WARN mark.
The expected version string is `BL0_VERSION` of the image's build (`bl0_version.h`).
The status channel graded is `cold_scratch[1]`; the ring is not graded. The debug console
exists only in debug builds, so the console checks need a build that has one.
Only one cold boot is graded, and the run ends at [S06]: a warm boot, a later boot and
the ATT-010 embedding itself are not graded.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import cocotb
import pyuvm
from env.sep_rom_observer import load_rom_syms
from rom_fw.sep_rom_observe_base import ROM_BASE, sep_rom_observe_base
from sep_reg_meta import sym

_ROM_SIZE = sym("SEP_BOOT_ROM_MEM_SIZE")
_VMEM_ARG = "sep_boot_rom_hex"
_HEX64 = re.compile(r"[0-9a-fA-F]{64}")
_VERSION_DEF = re.compile(r'#define\s+BL0_VERSION\s+"([^"]*)"')
# STATUS_ENCODE(type, 1 = BL0, code); codes from hw/sys/sep/doc/gen/status_values.adoc.
_BL0 = 1
_TYPE_INFO = 0x01
_TYPE_INFO_EXT = 0x81
_MSG_ROM_HASH = 0x131
_STATUS_START_MAIN = 0x8001_0057
_STATUS_S06 = 0x8001_020C
_MIN_FETCH_PCS = 64


def _status(kind: int, value: int) -> int:
    return (kind << 24) | (_BL0 << 16) | (value & 0xFFFF)


def _hex(v: int | None) -> str:
    return "none" if v is None else f"0x{v:08x}"


def _rom_image(path: Path) -> bytes:
    """Bytes of a 64-bit-word $readmemh image, word 0 at the ROM base."""
    image = bytearray()
    for tok in path.read_text().split():
        if tok.startswith("@"):
            at = int(tok[1:], 16) * 8
            if at < len(image):
                raise ValueError(
                    f"{path}: address {tok} goes backwards; rebuild the boot_rom image"
                )
            image.extend(bytes(at - len(image)))
        else:
            image.extend(int(tok, 16).to_bytes(8, "little"))
    return bytes(image)


def _version(path: Path) -> str:
    m = _VERSION_DEF.search(path.read_text())
    if m is None:
        raise ValueError(f"{path} defines no BL0_VERSION string; rebuild the boot_rom firmware")
    return m.group(1)


def _collapse(words: list[int]) -> list[int]:
    """The observer records a status only on change, so equal neighbours show as one word."""
    return [w for i, w in enumerate(words) if i == 0 or w != words[i - 1]]


@pyuvm.test()
class sep_rom_version_hash_report_test(sep_rom_observe_base):
    required_evidence = (
        "CHK-CONSOLE-VERSION",
        "CHK-CONSOLE-HASH",
        "CHK-STATUS-HASH-PREFIX",
        "CHK-REPORT-AT-S05",
    )
    max_run_cycles = 1_500_000

    def done(self, obs) -> bool:
        return obs.status_t(_STATUS_S06) is not None or obs.verdict_pass() is not None

    def grade(self, obs, chk) -> None:
        vmem = Path(cocotb.plusargs[_VMEM_ARG])
        image = _rom_image(vmem)
        syms = load_rom_syms(vmem.with_name("boot_rom.sym"))
        version = _version(vmem.with_name("bl0_version.h"))
        end = syms["__metadata_end"] - ROM_BASE
        field = syms["g_rom_sha256_str"] - ROM_BASE
        ver_at = syms["g_rom_version"] - ROM_BASE

        # Every recorded fetch from the Boot ROM must match the image that is hashed.
        fetched = {
            r.pc: r.insn
            for r in obs.first + obs.retires + obs.pre_mret
            if ROM_BASE <= r.pc < ROM_BASE + len(image) - 3 and not (r.exc or r.interrupt)
        }
        diff = [
            f"{_hex(pc)}:{_hex(insn)}!={_hex(want)}"
            for pc, insn in sorted(fetched.items())
            if insn != (want := int.from_bytes(image[pc - ROM_BASE : pc - ROM_BASE + 4], "little"))
        ]
        chk.ctrl(
            "LOADED-IMAGE",
            len(fetched) >= _MIN_FETCH_PCS and not diff,
            vmem=str(vmem),
            pcs=len(fetched),
            lowest=_hex(min(fetched, default=None)),
            highest=_hex(max(fetched, default=None)),
            mismatches=diff[:8],
        )
        chk.ctrl(
            "HASH-REGION",
            0 < end <= len(image) <= _ROM_SIZE and field >= end,
            region_end=_hex(ROM_BASE + end),
            image_bytes=len(image),
            hash_field=_hex(ROM_BASE + field),
        )
        # The symbol listing and bl0_version.h belong to the build that wrote this image.
        embedded_version = image[ver_at : ver_at + len(version)].decode("ascii", "replace")
        chk.ctrl(
            "BUILD-MATCHES-IMAGE", bool(version) and embedded_version == version, version=version
        )
        golden = hashlib.sha256(image[:end]).hexdigest()
        chk.obs(
            "EMBEDDED-HASH",
            embedded=image[field : field + 80].rstrip(b"\0").decode("ascii", "replace"),
            golden=golden,
        )

        chk.ctrl("CONSOLE-LIVE", bool(obs.console), lines=len(obs.console))
        ver_line = next(((t, ln) for t, ln in obs.console if version and version in ln), None)
        chk.ok("CONSOLE-VERSION", ver_line is not None, version=version)
        hash_lines = [(t, m.group(0).lower()) for t, ln in obs.console for m in _HEX64.finditer(ln)]
        hash_line = next(((t, h) for t, h in hash_lines if h == golden), None)
        chk.ok(
            "CONSOLE-HASH",
            hash_line is not None,
            golden=golden,
            console_hex64=[h for _, h in hash_lines],
        )

        words = obs.statuses()
        head = _status(_TYPE_INFO, _MSG_ROM_HASH)
        prefix = [_status(_TYPE_INFO_EXT, int(golden[i : i + 4], 16)) for i in (0, 4)]
        want = _collapse(prefix)
        i = words.index(head) if head in words else -1
        got = words[i + 1 : i + 1 + len(want)] if i >= 0 else []
        chk.ok(
            "STATUS-HASH-PREFIX",
            i >= 0 and got == want,
            rom_hash=_hex(head),
            expected=[_hex(w) for w in want],
            following=[_hex(w) for w in words[i + 1 : i + 4]] if i >= 0 else [],
        )

        t_main = obs.status_t(_STATUS_START_MAIN)
        t_hash = obs.status_t(head)
        t_s06 = obs.status_t(_STATUS_S06)
        reports = [t_hash, ver_line[0] if ver_line else None, hash_line[0] if hash_line else None]
        chk.ok(
            "REPORT-AT-S05",
            None not in (t_main, t_s06, *reports) and all(t_main < t < t_s06 for t in reports),
            start_main_ps=t_main if t_main is not None else -1,
            rom_hash_ps=t_hash if t_hash is not None else -1,
            version_line_ps=reports[1] if reports[1] is not None else -1,
            hash_line_ps=reports[2] if reports[2] is not None else -1,
            s06_ps=t_s06 if t_s06 is not None else -1,
        )
