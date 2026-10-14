# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Address decode of SMC_EFUSE_MAP: layout, read widths and the past-extent responder.

Sources: smc_efuse_map.rdl (address map), smc.rdl (smc_efuse_map ocah_past_extent_resp).

The image is written into the run directory during ``build_phase``: 256 pairwise-distinct
words, LOCKS 0x40000000_00000000, every other field a distinct-word pattern.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import cocotb
import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_efuse_image_pattern_test_seq import load_image
from seq_lib.smc_efuse_map_layout_decode_test_seq import (
    smc_efuse_map_layout_decode_test_seq,
)
from smc_base_test import smc_base_test

_EFUSE_DIR = Path(__file__).resolve().parents[2] / "efuse_preload"
_LOCKS_VALUE = 0x4000_0000_0000_0000


def _marker(n: int) -> int:
    """Word n of the marker image: non-zero and distinct for every n in 2..255."""
    return 0x5A5A0000 | (n << 8) | (0xA5 ^ n)


def _field(first: int, count: int) -> int:
    return sum(_marker(first + k) << (32 * k) for k in range(count))


_CONFIG_TEMPLATE = """\
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

[LOCKS]
    write_locked = "False"
    read_locked = "False"
    [LOCKS.fields.lock_entries]
    value = 0x{locks:016x}

[JTAG_PUBLIC_IDENTITY]
    write_locked = "False"
    read_locked = "False"
    [JTAG_PUBLIC_IDENTITY.fields.value]
    value = 0x{jpi:x}

[I2C_I3C_ID]
    write_locked = "False"
    read_locked = "False"
    [I2C_I3C_ID.fields.interface_id]
    value = 0x{i2c:x}

[SMC_CONFIG]
    write_locked = "False"
    read_locked = "False"
    [SMC_CONFIG.fields.smc_config]
    value = 0x{cfg:x}

[OCCP_TRANSPORT_TIMEOUT]
    write_locked = "False"
    read_locked = "False"
    [OCCP_TRANSPORT_TIMEOUT.fields.transport_timeout]
    value = 0x{occp:x}

[SPARE]
    write_locked = "False"
    read_locked = "False"
    [SPARE.fields.spare_data]
    value = 0x{spare:x}
"""


def write_marker_image() -> Path:
    """Render the leaf's image at the path ``+smc_efuse_hex`` names."""
    plusarg = cocotb.plusargs.get("smc_efuse_hex")
    assert plusarg is not None, "the leaf's testlist entry must name +smc_efuse_hex"
    hex_path = Path(str(plusarg))
    assert not hex_path.is_absolute(), (
        f"+smc_efuse_hex={plusarg} is absolute; this leaf writes the image it senses, "
        "so the plusarg must name a file in the run directory"
    )
    hex_path = Path.cwd() / hex_path
    config = hex_path.with_suffix(".toml")
    config.write_text(
        _CONFIG_TEMPLATE.format(
            locks=_LOCKS_VALUE,
            jpi=_field(2, 8),
            i2c=_field(10, 18),
            cfg=_field(28, 2),
            occp=_field(30, 2),
            spare=_field(32, 224),
        ),
        encoding="utf-8",
    )
    cmd = [
        sys.executable,
        str(_EFUSE_DIR / "generate_efuse_preload.py"),
        str(config),
        "--output_file",
        str(hex_path),
    ]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        raise AssertionError(
            f"eFuse image generation failed:\n  {exc.cmd}\n"
            f"  stdout: {exc.stdout}\n  stderr: {exc.stderr}"
        ) from exc
    cocotb.log.info("%s", result.stdout.strip())
    return hex_path


@pyuvm.test()
class smc_efuse_map_layout_decode_test(smc_base_test):
    """Read every region, both widths and the past-extent responder against the marker image."""

    required_evidence = (
        "CHK-EMAP-LAYOUT-CFG-OCCP",
        "CHK-EMAP-LAYOUT-JPI-I2C",
        "CHK-EMAP-LAYOUT-SPARE",
        "CHK-EMAP-LAYOUT-SWEEP",
        "CHK-EMAP-PAST-NOCHANGE",
        "CHK-EMAP-PAST-READ",
        "CHK-EMAP-PAST-WRITE",
        "CHK-EMAP-WIDTH-32",
        "CHK-EMAP-WIDTH-64",
        "CHK-EMAP-WIDTH-CFG",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 12

    auto_protocol_vip = False

    run_written_file_plusargs = ("smc_efuse_hex",)

    def build_phase(self) -> None:
        super().build_phase()
        self.image = load_image(write_marker_image())

    async def run_scenario(self) -> None:
        seq = smc_efuse_map_layout_decode_test_seq("smc_efuse_map_layout_decode_test_seq")
        seq.image = self.image
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.accesses >= seq.access_floor, (
            f"{seq.accesses} SEP_IN accesses, the sequence computed a floor of {seq.access_floor}"
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.EFUSE,
            type(self).__name__,
            min_csr_accesses=seq.access_floor,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                "SMC_EFUSE_MAP layout decode, read widths and past-extent responder "
                "(eFuse bank is the DV model)"
            ),
        )
