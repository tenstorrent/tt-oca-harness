# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

from pathlib import Path

import pytest
from sepvp import fuses, paths
from sepvp.cli import build_parser
from sepvp.config import SMC_SRAM_SIZE_BYTES, SimConfig
from sepvp.harness import HarnessError
from sepvp.sepvp_harness import SepVpHarness

pytestmark = pytest.mark.hostonly
pytest_plugins = ["pytester"]

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


# --------------------------------------------------------------------------- #
# OTP fuse source selection
# --------------------------------------------------------------------------- #
PRELOAD_KEY = "och_sep_ss1.sep_efuse.fuse_preload_file"
LC_CTRL_KEY = "och_sep_ss1.lc_ctrl.lc_state"
PRELOAD_LINE = f"{PRELOAD_KEY} : ../preload/default_efuse.preload\n"
PROD_TOML = (
    paths.OCAH_ROOT / "hw/sys/sep/dv/tb/efuse_preloads/efuse_configurations/sep_efuse_lc_prod.toml"
)
PROD_YAML = Path(__file__).parent / "fuse_maps" / "prod_secure.yaml"
OTP_FORMATS = {"toml": PROD_TOML, "yaml": PROD_YAML}


def _two_file_harness(tmp_path, top_extra="", efuse_body=PRELOAD_LINE, **config_args):
    """The pinned model's layout: only the included efuse_vp.ini names the preload."""
    base = tmp_path / "accellera_config.ini"
    base.write_text(f"@include efuse_vp.ini\n{BASE_INI}{top_extra}")
    (tmp_path / "efuse_vp.ini").write_text(f"[string]\n{efuse_body}")
    config = SimConfig(name="unit", elf=tmp_path / "boot_rom.elf", **config_args)
    return SepVpHarness(
        config, run_root=tmp_path / "logs", base_ini=base, sep_vp_bin=tmp_path / "sep-vp"
    )


def _active(text, key):
    return [line for line in text.splitlines() if line.strip().startswith(key)]


@pytest.mark.parametrize("base_target_exists", [False, True], ids=["absent", "present"])
def test_toml_otp_stages_the_complete_rtl_image(tmp_path, base_target_exists):
    if base_target_exists:
        target = tmp_path / "logs" / "preload" / "default_efuse.preload"
        target.parent.mkdir(parents=True)
        target.write_text("0\n" * 8192)
    h = _two_file_harness(tmp_path, otp=PROD_TOML)
    h._prepare_run_dir()
    staged = h.run_dir / "data" / "efuse.hex"
    assert staged.read_text().splitlines() == [
        f"{word:08x}" for word in fuses.load_toml_image(PROD_TOML).words
    ]
    assert not _active((h.run_dir / "efuse_vp.ini").read_text(), PRELOAD_KEY)
    overlay = h.overlay_path.read_text()
    assert _active(overlay, PRELOAD_KEY) == [f"{PRELOAD_KEY} : {staged.resolve()}"]
    assert not [
        line for line in _active(overlay, "och_sep_ss1.sep_efuse.") if PRELOAD_KEY not in line
    ]
    assert not _active(overlay, LC_CTRL_KEY)


@pytest.mark.parametrize("base_target_exists", [False, True], ids=["absent", "present"])
def test_yaml_otp_disables_the_base_preload(tmp_path, base_target_exists):
    if base_target_exists:
        target = tmp_path / "logs" / "preload" / "default_efuse.preload"
        target.parent.mkdir(parents=True)
        target.write_text("0\n" * 8192)
    h = _two_file_harness(tmp_path, otp=PROD_YAML)
    h._prepare_run_dir()
    assert not _active((h.run_dir / "efuse_vp.ini").read_text(), PRELOAD_KEY)
    overlay = h.overlay_path.read_text()
    assert not _active(overlay, PRELOAD_KEY)
    assert _value(overlay, "och_sep_ss1.sep_efuse.lc_state") == "1"
    assert not _active(overlay, LC_CTRL_KEY)
    assert not (h.run_dir / "data" / "efuse.hex").exists()


@pytest.mark.parametrize("otp", OTP_FORMATS.values(), ids=OTP_FORMATS.keys())
def test_preload_after_a_blank_line_is_disabled(tmp_path, otp):
    h = _two_file_harness(tmp_path, efuse_body=f"\n\n{PRELOAD_LINE}", otp=otp)
    h._prepare_run_dir()
    assert not _active((h.run_dir / "efuse_vp.ini").read_text(), PRELOAD_KEY)


@pytest.mark.parametrize("otp", OTP_FORMATS.values(), ids=OTP_FORMATS.keys())
@pytest.mark.parametrize(
    "top_extra, efuse_body",
    [("", ""), (f"[string]\n{PRELOAD_LINE}", PRELOAD_LINE)],
    ids=["none", "two"],
)
def test_otp_requires_exactly_one_base_preload(tmp_path, otp, top_extra, efuse_body):
    h = _two_file_harness(tmp_path, top_extra=top_extra, efuse_body=efuse_body, otp=otp)
    with pytest.raises(HarnessError, match="exactly one active"):
        h._prepare_run_dir()


@pytest.mark.parametrize("otp", OTP_FORMATS.values(), ids=OTP_FORMATS.keys())
def test_extra_ini_cannot_replace_the_selected_fuse_source(tmp_path, otp):
    with pytest.raises(ValueError, match="reserved while otp is set"):
        SimConfig(name="t", elf="x.elf", otp=otp, extra_ini=[("string", PRELOAD_KEY, "x.hex")])


@pytest.mark.parametrize("otp", [PROD_TOML, PROD_YAML, None], ids=["toml", "yaml", "none"])
def test_extra_ini_cannot_drive_the_lifecycle_controller(otp):
    with pytest.raises(ValueError, match="derives lc_ctrl.lc_state from the eFuse"):
        SimConfig(name="t", elf="x.elf", otp=otp, extra_ini=[("int", LC_CTRL_KEY, 1)])


@pytest.mark.parametrize("otp", [PROD_TOML, None], ids=["toml", "none"])
@pytest.mark.parametrize(
    "key",
    [
        f" {LC_CTRL_KEY}",
        f"{PRELOAD_KEY} ",
        f"{PRELOAD_KEY}:/abs/other.hex #",
        f"{LC_CTRL_KEY}:6",
        "instance_prefix",
        "fuse_preload_file",
    ],
    ids=["leading", "trailing", "preload-colon", "lc_ctrl-colon", "instance_prefix", "short-key"],
)
def test_extra_ini_keys_must_be_canonical(key, otp):
    with pytest.raises(ValueError, match="is not canonical"):
        SimConfig(name="t", elf="x.elf", otp=otp, extra_ini=[("string", key, "1")])


@pytest.mark.parametrize(
    "reserved", [f"{PRELOAD_KEY} : x.hex", f"{LC_CTRL_KEY} : 1"], ids=["preload", "lc_ctrl"]
)
@pytest.mark.parametrize("newline", ["\n", "\r", "\r\n"], ids=["lf", "cr", "crlf"])
@pytest.mark.parametrize("position", ["key", "value"])
@pytest.mark.parametrize("otp", [PROD_TOML, None], ids=["toml", "none"])
def test_extra_ini_rejects_line_injection(reserved, newline, position, otp):
    key, value = "och_sep_ss1.init_writes", "0x10802038=0x00000000"
    if position == "key":
        key = f"{key}{newline}{reserved}"
    else:
        value = f"{value}{newline}{reserved}"
    with pytest.raises(ValueError, match="extra_ini keys and values may not contain CR or LF"):
        SimConfig(name="t", elf="x.elf", otp=otp, extra_ini=[("string", key, value)])
