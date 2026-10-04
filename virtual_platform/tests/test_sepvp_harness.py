# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import pytest
from sepvp.cli import build_parser
from sepvp.config import SMC_SRAM_SIZE_BYTES, SimConfig
from sepvp.harness import HarnessError
from sepvp.sepvp_harness import SepVpHarness

pytestmark = pytest.mark.hostonly

BASE_INI = "och_sep_ss1.spiPreload : flash.spi_preload\n"


def _harness(tmp_path, **config_args):
    base = tmp_path / "accellera_config.ini"
    base.write_text(BASE_INI)
    config = SimConfig(name="unit", elf=tmp_path / "boot_rom.elf", **config_args)
    return SepVpHarness(
        config, run_root=tmp_path / "logs", base_ini=base, sep_vp_bin=tmp_path / "sep-vp"
    )


def _value(ini, key):
    hits = [line.split(":", 1)[1].strip() for line in ini.splitlines() if key in line]
    return hits[-1] if hits else None


def test_iss_trace_is_discarded_by_default(tmp_path):
    assert _value(_harness(tmp_path).render_ini(), "och_sep_ss1.traceFile") == "/dev/null"


def test_iss_trace_writes_into_the_run_dir_when_enabled(tmp_path):
    h = _harness(tmp_path, iss_trace=True)
    assert _value(h.render_ini(), "och_sep_ss1.traceFile") == str(
        (h.run_dir / "veer_trace.log").resolve()
    )


def test_smc_image_is_staged_into_the_run_dir(tmp_path):
    image = tmp_path / "bundle.bin"
    image.write_bytes(b"OCAC" + bytes(60))
    h = _harness(tmp_path, smc_sram_image=image)
    h._prepare_run_dir()
    staged = h.run_dir / "data" / "smc_sram_image.bin"
    assert staged.read_bytes() == image.read_bytes()
    ini = h.overlay_path.read_text()
    assert _value(ini, "och_sep_ss1.smcSramBackdoorFile") == str(staged.resolve())
    assert _value(ini, "och_sep_ss1.smcSramBackdoorOffset") is None


def test_smc_offset_override_is_rendered_only_when_set(tmp_path):
    image = tmp_path / "bundle.bin"
    image.write_bytes(bytes(64))
    h = _harness(tmp_path, smc_sram_image=image, smc_sram_offset=0x3000)
    assert _value(h.render_ini(), "och_sep_ss1.smcSramBackdoorOffset") == str(0x3000)


def test_smc_image_past_the_window_is_refused(tmp_path):
    image = tmp_path / "big.bin"
    image.write_bytes(bytes(SMC_SRAM_SIZE_BYTES - 0x2000 + 4))
    with pytest.raises(HarnessError, match="runs past the 1 MiB window"):
        _harness(tmp_path, smc_sram_image=image)._prepare_run_dir()


def test_init_writes_reach_the_overlay(tmp_path):
    h = _harness(tmp_path, init_writes=[(0x10802038, 0xC0030000)])
    assert _value(h.render_ini(), "och_sep_ss1.init_writes") == "0x10802038=0xc0030000"


def test_cli_turns_the_trace_on_only_when_asked():
    assert build_parser().parse_args(["--bin", "x.elf"]).iss_trace is False
    assert build_parser().parse_args(["--bin", "x.elf", "--iss-trace"]).iss_trace is True


def test_vp_fixture_turns_the_trace_on_from_the_command_line(pytester):
    pytester.makeconftest('pytest_plugins = ["sepvp.pytest_plugin"]')
    pytester.makepyfile(
        """
        from sepvp.config import SimConfig

        def test_on(vp):
            assert vp(SimConfig(name="t", elf="x.elf")).config.iss_trace is True
        """
    )
    pytester.runpytest("--iss-trace").assert_outcomes(passed=1)
