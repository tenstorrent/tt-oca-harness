# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Software lock enforcement per field of SMC_EFUSE_MAP.

Sources: smc_efuse_map.rdl (LOCKS), architecture.adoc (Hardware vs. Software Locks),
smc-programming.adoc (whole-field locks), port_table.adoc (shadow_regs_o).

The image is written into the run directory during ``build_phase``: every field and LOCKS
are 0.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import cocotb
import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_efuse_image_pattern_test_seq import load_image
from seq_lib.smc_efuse_map_lock_field_enforce_test_seq import (
    smc_efuse_map_lock_field_enforce_test_seq,
)
from smc_base_test import smc_base_test

_EFUSE_DIR = Path(__file__).resolve().parents[2] / "efuse_preload"

_CONFIG_TEMPLATE = """\
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

[LOCKS]
    write_locked = "False"
    read_locked = "False"
    [LOCKS.fields.lock_entries]
    value = 0x0

[JTAG_PUBLIC_IDENTITY]
    write_locked = "False"
    read_locked = "False"
    [JTAG_PUBLIC_IDENTITY.fields.value]
    value = 0x0

[I2C_I3C_ID]
    write_locked = "False"
    read_locked = "False"
    [I2C_I3C_ID.fields.interface_id]
    value = 0x0

[SMC_CONFIG]
    write_locked = "False"
    read_locked = "False"
    [SMC_CONFIG.fields.smc_config]
    value = 0x0

[OCCP_TRANSPORT_TIMEOUT]
    write_locked = "False"
    read_locked = "False"
    [OCCP_TRANSPORT_TIMEOUT.fields.transport_timeout]
    value = 0x0

[SPARE]
    write_locked = "False"
    read_locked = "False"
    [SPARE.fields.spare_data]
    value = 0x0
"""


def write_zero_image() -> Path:
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
    config.write_text(_CONFIG_TEMPLATE, encoding="utf-8")
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
class smc_efuse_map_lock_field_enforce_test(smc_base_test):
    """Set write, read and both locks per field and check each field's enforcement."""

    required_evidence = (
        "CHK-EMAP-ENF-NEIGHBOUR",
        "CHK-EMAP-ENF-PORT",
        "CHK-EMAP-ENF-WR-SPARE",
        "CHK-EMAP-PAIR-BOTH",
        "CHK-EMAP-PAIR-RDONLY",
        "CHK-EMAP-WHOLE-I2C-RD",
        "CHK-EMAP-WHOLE-I2C-WR",
        "CHK-EMAP-WHOLE-JPI",
        "CHK-EMAP-WHOLE-SPARE",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 11

    auto_protocol_vip = False

    run_written_file_plusargs = ("smc_efuse_hex",)

    def build_phase(self) -> None:
        super().build_phase()
        self.image = load_image(write_zero_image())

    async def run_scenario(self) -> None:
        seq = smc_efuse_map_lock_field_enforce_test_seq("smc_efuse_map_lock_field_enforce_test_seq")
        seq.image = self.image
        seq.seed = self.random_seed()
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
                "SMC_EFUSE_MAP per-field write-lock, read-lock and both-lock enforcement "
                "(eFuse bank is the DV model)"
            ),
        )
