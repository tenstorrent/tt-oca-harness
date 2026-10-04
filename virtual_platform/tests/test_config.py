# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import pytest
from sepvp.config import SimConfig

pytestmark = pytest.mark.hostonly


def test_init_writes_render_as_one_ordered_string_override():
    cfg = SimConfig(
        name="ordered_deposits",
        elf="firmware.elf",
        init_writes=[
            (0xC0030000, 0x00000297),
            (0x10802038, 0xC0030000),
        ],
    )

    assert cfg.init_write_overrides() == [
        (
            "string",
            "och_sep_ss1.init_writes",
            "0xc0030000=0x00000297,0x10802038=0xc0030000",
        )
    ]
    assert cfg.overrides()[-1] == cfg.init_write_overrides()[0]


@pytest.mark.parametrize("address", [-4, 3, 0x1_0000_0000])
def test_init_writes_reject_invalid_address(address):
    with pytest.raises(ValueError, match="init_writes address"):
        SimConfig(
            name="bad_address",
            elf="firmware.elf",
            init_writes=[(address, 0)],
        )


@pytest.mark.parametrize("value", [-1, 0x1_0000_0000])
def test_init_writes_reject_out_of_range_value(value):
    with pytest.raises(ValueError, match="init_writes value"):
        SimConfig(
            name="bad_value",
            elf="firmware.elf",
            init_writes=[(0xC0030000, value)],
        )


def test_smc_sram_offset_defaults_to_the_model_default():
    config = SimConfig(name="smc", elf="x.elf", smc_sram_image="bundle.bin")
    assert config.smc_sram_offset is None


@pytest.mark.parametrize("offset", [-4, 0x100000, 0x2002])
def test_smc_sram_offset_must_be_an_aligned_window_offset(offset):
    with pytest.raises(ValueError):
        SimConfig(name="smc", elf="x.elf", smc_sram_image="b.bin", smc_sram_offset=offset)


def test_smc_sram_image_needs_a_boot_that_reads_the_smc_window():
    with pytest.raises(ValueError, match="never looks at it"):
        SimConfig(name="smc", elf="x.elf", boot="primary", smc_sram_image="b.bin")
