"""Bootcode negative paths over the OpenTitan SPI controller, on sep-vp.

Boots ``boot_rom.elf`` built for the OpenTitan controller with the secure-DMA drain
(``BOOT_SPI_CONTROLLER_OT=1``, ``BOOT_OT_SPI_USE_PIO=0``) from a *crafted* SPI flash
image, and asserts the ROM's manifest reject -> rotate -> halt decision via the
production ``[SEP_STATUS]`` stream. Each case tampers the generated secure-boot
image (the ``secure_boot_preload`` fixture builds it via the bootrom's
``secure_boot_spi`` target) to drive one rejection:

  * both_bad          - primary magic corrupted, backup erased -> MANIFEST_LOAD_FAILED
                        (halt only when BOTH slots fail)
  * hash_tamper       - one byte flipped inside the hashed region -> INVALID_MANIFEST_HASH
  * payload_overlap   - payload_offset points into the manifest header -> PAYLOAD_OVERLAPS
  * payload_too_large - payload_offset+length exceeds SRAM -> (silent reject) -> halt
  * rotate_to_backup  - primary corrupted, a valid slot copied to the backup offset
                        -> rotate -> backup boots -> STARTING_BL1

No RSA re-signing is needed: the corrupt-magic / bad-payload-location cases are rejected
before the signature is used, the hash case deliberately breaks the SHA-256, and
``payload_offset`` lives outside the hashed TBS region so header edits don't disturb the
manifest hash. Runs in TEST_DEV with secure boot off (the default VP straps).

This file is deliberately scoped to the OpenTitan bootcode negative paths (``bootcode``
marker, ``test_bootcode_*`` name) so it is easy to identify and move as a unit.
Skips cleanly if the RISC-V toolchain or sep-vp is absent.
"""

import os
import struct
import subprocess
from pathlib import Path

import pytest

from sepvp import paths
from sepvp.config import SimConfig

pytestmark = pytest.mark.bootcode

TIMEOUT = 150

# Flash slot offsets (hw/sys/sep/bootrom/prod/include/manifest.h).
PRIMARY_OFFSET = 0x1000
BACKUP_OFFSET = 0x41000
SRAM_SIZE = 0x00040000

# manifest_t field byte offsets (manifest.h layout comment): magic @0, length @8,
# payload_length @600 (u64, in the hashed TBS), signature @744 (TBS end),
# manifest_hash @1128, payload_offset @1160 (i64, OUTSIDE the hashed TBS).
OFF_MAGIC = 0
OFF_PAYLOAD_LEN = 600
OFF_PAYLOAD_OFFSET = 1160
TBS_BYTE = 20  # any byte inside [0,744) that is not a header-validated field

def _preload_raw(preload: Path) -> bytes:
    """Convert a `$readmemh` preload (`@addr` + hex bytes) to a raw image."""
    data = bytearray()
    for line in preload.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("@"):
            data += bytes(int(tok, 16) for tok in line.split())
    return bytes(data)


# --- crafters: pristine raw image -> tampered image -------------------------

def _craft_both_bad(raw: bytes) -> bytes:
    b = bytearray(raw)
    b[PRIMARY_OFFSET + OFF_MAGIC] ^= 0xFF   # corrupt primary magic; backup is erased 0x00
    return bytes(b)


def _craft_hash_tamper(raw: bytes) -> bytes:
    b = bytearray(raw)
    b[PRIMARY_OFFSET + TBS_BYTE] ^= 0xFF    # flip a byte in the hashed region -> SHA mismatch
    return bytes(b)


def _craft_payload_overlap(raw: bytes) -> bytes:
    b = bytearray(raw)
    struct.pack_into("<q", b, PRIMARY_OFFSET + OFF_PAYLOAD_OFFSET, 0x100)  # into the header
    return bytes(b)


def _craft_payload_too_large(raw: bytes) -> bytes:
    b = bytearray(raw)
    struct.pack_into("<q", b, PRIMARY_OFFSET + OFF_PAYLOAD_OFFSET, 0x3F000)  # off+len > SRAM
    return bytes(b)


def _craft_rotate_to_backup(raw: bytes) -> bytes:
    b = bytearray(raw)
    poff = struct.unpack_from("<q", raw, PRIMARY_OFFSET + OFF_PAYLOAD_OFFSET)[0]
    plen = struct.unpack_from("<Q", raw, PRIMARY_OFFSET + OFF_PAYLOAD_LEN)[0]
    slot_len = poff + plen                                   # manifest header + payload span
    b[BACKUP_OFFSET:BACKUP_OFFSET + slot_len] = raw[PRIMARY_OFFSET:PRIMARY_OFFSET + slot_len]
    b[PRIMARY_OFFSET + OFF_MAGIC] ^= 0xFF                    # force a rotate to the (valid) backup
    return bytes(b)


# (name, crafter, expected SEP_MSG, status type)
CASES = [
    ("both_bad",          _craft_both_bad,          "SEP_MSG_MANIFEST_LOAD_FAILED",      "ERROR"),
    ("hash_tamper",       _craft_hash_tamper,       "SEP_MSG_INVALID_MANIFEST_HASH",     "ERROR"),
    ("payload_overlap",   _craft_payload_overlap,   "SEP_MSG_PAYLOAD_OVERLAPS_MANIFEST", "ERROR"),
    ("payload_too_large", _craft_payload_too_large, "SEP_MSG_MANIFEST_LOAD_FAILED",      "ERROR"),
    ("rotate_to_backup",  _craft_rotate_to_backup,  "SEP_MSG_STARTING_BL1",              "INFO"),
]


def _ot_env(request):
    """Toolchain bin on PATH + the gcc-toolset runtime (mirrors conftest firmware env)."""
    env = paths.vp_env(request.config.getoption("--gcc-toolset"))
    tc_bin = Path(request.config.getoption("--riscv-toolchain")) / "bin"
    if tc_bin.is_dir():
        env["PATH"] = f"{tc_bin}{os.pathsep}{env.get('PATH', '')}"
    return env


@pytest.fixture(scope="session")
def ot_bootcode_elf(request):
    """Build (unless --no-build) the OpenTitan+DMA boot ROM into build_ot/ and return it.

    Built into a separate BUILD_DIR so it coexists with the default (Cadence) build/
    without a flag-driven relink."""
    if not paths.sep_vp_bin().is_file():
        pytest.skip(f"sep-vp not built ({paths.sep_vp_bin()})")
    elf = paths.BOOTCODE_DIR / "build_ot" / "boot_rom.elf"
    if request.config.getoption("build"):
        tc = Path(request.config.getoption("--riscv-toolchain")) / "bin" / "riscv64-unknown-elf-gcc"
        if not tc.exists():
            pytest.skip(f"RISC-V toolchain not found ({tc})")
        res = subprocess.run(
            ["make", "-C", str(paths.BOOTCODE_DIR), "ot-toolchain-images"],
            cwd=str(paths.OCAH_ROOT), env=_ot_env(request), capture_output=True, text=True,
        )
        if res.returncode != 0:
            pytest.fail(f"OT bootcode build failed:\n{res.stdout[-2000:]}\n{res.stderr[-2000:]}")
    if not elf.is_file():
        pytest.skip(f"OT boot_rom.elf not present ({elf}); build it or drop --no-build")
    return elf


@pytest.mark.parametrize("name,craft,expect_msg,expect_type", CASES,
                         ids=[c[0] for c in CASES])
def test_ot_manifest_negative(vp, ot_bootcode_elf, secure_boot_preload, tmp_path,
                              name, craft, expect_msg, expect_type):
    """Craft a tampered flash image and assert the ROM's reject/rotate/halt decision."""
    img = tmp_path / f"{name}.bin"
    img.write_bytes(craft(_preload_raw(secure_boot_preload)))
    t = vp(SimConfig(name=f"ot_neg_{name}", elf=str(ot_bootcode_elf),
                     flash_image=str(img), boot="primary", boot_timeout=TIMEOUT))
    t.spawn()
    match = t.expect_status(expect_msg, type=expect_type, timeout=TIMEOUT)
    if expect_type == "ERROR":
        assert "ERROR" in match.group(0)
    t.close()
