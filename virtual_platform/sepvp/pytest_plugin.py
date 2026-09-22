# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Shared pytest plugin for the sep-vp harness suites.

This module is the single home for the harness framework — the CLI options, the
firmware-build helpers, the run fixtures, and the marker registrations — so that it
lives with the rest of the runner logic inside the ``sepvp`` package. The test suites
(everything under ``virtual_platform/tests/``) load it via
``pytest_plugins = ["sepvp.pytest_plugin"]`` from the thin bootstrap conftest at
``virtual_platform/conftest.py``.

Options (mirroring the example bootcode harness where it makes sense):
  --vp-bin PATH        sep-vp executable (default: the in-tree build)
  --vp-timeout N       default per-run boot timeout in seconds (default 120)
  --no-build           do not (re)build firmware; use whatever ELF already exists
  --build-type T       'test' (DEBUG: SIM_OUT on) or 'release' (default test)
  --stream             tee sep-vp stdout to the console live
  --riscv-toolchain P  RISC-V toolchain prefix dir (for firmware builds)

Fixtures:
  vp                   factory: vp(SimConfig) -> SepVpHarness (auto-closed on teardown)
  bootcode_elf         builds the boot ROM OT variant (unless --no-build); returns boot_rom.elf
  fw_test_builder      factory: build a hw/sys/sep/dv/fw test and return its ELF
  build_type           the resolved --build-type
"""

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from sepvp import paths
from sepvp.config import SimConfig
from sepvp.sepvp_harness import SepVpHarness

_MARKERS = [
    "bootcode: bootcode (boot_rom.elf) on sep-vp via the SEP_STATUS production path.",
    "spi_mux: SPI mux register RW + flash-loader checks on sep-vp.",
    "spi_dma: SPI-controller -> secure-DMA RX streaming integration checks on sep-vp.",
    "fw_sep: hw/sys/sep/dv/fw test compatibility runs (printf markers).",
    "needs_debug: requires a DEBUG firmware build (SIM_OUT); skipped on --build-type=release.",
    "long: a test that takes a long time to run.",
    "slow: a slow simulation case.",
    "release: only meaningful on a release firmware build.",
    "skip_release: skip on a release firmware build.",
]


def pytest_addoption(parser):
    g = parser.getgroup("sepvp", "SEP virtual-platform harness")
    g.addoption("--vp-bin", default=None, help="path to the sep-vp executable")
    g.addoption("--vp-timeout", type=int, default=120, help="default per-run boot timeout (s)")
    g.addoption(
        "--no-build",
        dest="build",
        action="store_false",
        default=True,
        help="do not rebuild firmware before running",
    )
    g.addoption(
        "--build-type",
        choices=["test", "release"],
        default="test",
        help="firmware build type: test (DEBUG/SIM_OUT) or release",
    )
    g.addoption("--stream", action="store_true", help="tee sep-vp stdout to the console")
    g.addoption(
        "--riscv-toolchain",
        default=paths.default_riscv_toolchain(),
        help="RISC-V toolchain prefix dir (its bin/ is prepended to PATH for firmware "
        "builds; default: $RISCV_TOOLCHAIN, empty = use PATH as-is)",
    )


def pytest_configure(config):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    for marker in _MARKERS:
        config.addinivalue_line("markers", marker)


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    """On a release build, deselect SIM_OUT-dependent (needs_debug) tests (mirrors example)."""
    if config.getoption("--build-type") != "release":
        return
    deselected, remaining = [], []
    for item in items:
        (deselected if item.get_closest_marker("needs_debug") else remaining).append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = remaining
        logging.info("Deselected %d needs_debug tests on a release build", len(deselected))


# --- firmware build helpers ----------------------------------------------------
def _fw_env(config):
    """Environment for a firmware make: venv python + RISC-V toolchain on PATH."""
    env = dict(os.environ)
    # The bootrom's OTBN codegen (generate_otbn_c.py) invokes a bare `python3`; make sure that
    # resolves to the venv interpreter running pytest (which carries pyelftools & the other deps),
    # not the shared system python3.
    venv_bin = Path(sys.executable).parent
    env["PATH"] = f"{venv_bin}{os.pathsep}{env.get('PATH', '')}"
    # A container build runs python from the image instead: only the uv-bundled one
    # carries the vp group, and the bare one sends uv at this venv and strips it.
    env["OCAH_IMAGE_WITH_UV"] = "true"
    tc = config.getoption("--riscv-toolchain")
    if tc and (Path(tc) / "bin").is_dir():
        env["PATH"] = f"{Path(tc) / 'bin'}{os.pathsep}{env.get('PATH', '')}"
    return env


_NATIVE_TOOLCHAIN_OK = None


def _native_fw_toolchain(env):
    """True when the toolchain on PATH can compile against picolibc (cached).

    The ROM and DV-engine builds need riscv64-unknown-elf-gcc WITH picolibc,
    which the ocah-toolchain container provides (tools/docker/README.md); bare
    riscv-gnu-toolchain installs typically lack it."""
    global _NATIVE_TOOLCHAIN_OK
    if _NATIVE_TOOLCHAIN_OK is None:
        try:
            r = subprocess.run(
                [
                    "riscv64-unknown-elf-gcc",
                    "--specs=picolibc.specs",
                    "-x",
                    "c",
                    "-c",
                    "-",
                    "-o",
                    os.devnull,
                ],
                input="int main(void){return 0;}",
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            _NATIVE_TOOLCHAIN_OK = r.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            _NATIVE_TOOLCHAIN_OK = False
    return _NATIVE_TOOLCHAIN_OK


def _make(config, *make_args, cwd, container_ok=True):
    """Run a firmware make, routing through the ocah-toolchain container
    (scripts/docker-run.sh run-here; set OCAH_TOOLCHAIN_ROOTFS for the
    engine-less bwrap path) when the native toolchain lacks picolibc.

    container_ok=False keeps the make native — needed for the uv-based pack
    targets, which the container does not carry uv for."""
    env = _fw_env(config)
    if container_ok and not _native_fw_toolchain(env):
        argv = [str(paths.OCAH_ROOT / "scripts" / "docker-run.sh"), "run-here", "make", *make_args]
    else:
        # PYTHON and OTBN_PYTHON default to a `uv run` on the repo-root project, which
        # re-resolves .venv to its default groups and drops the vp group this process needs.
        argv = ["make", *make_args, f"PYTHON={sys.executable}", f"OTBN_PYTHON={sys.executable}"]
    return subprocess.run(argv, cwd=str(cwd), env=env, capture_output=True, text=True)


@pytest.fixture(scope="session")
def build_type(request):
    return request.config.getoption("--build-type")


@pytest.fixture(scope="session")
def bootcode_elf(request):
    """Build (unless --no-build) and return the OpenTitan boot ROM (build_ot/boot_rom.elf).

    The SEP VP models the OpenTitan SPI host only, so all VP bootcode tests use the
    OpenTitan controller build (the bootrom Makefile's ot-toolchain-images target);
    the default Cadence build is not runnable on the VP (its xSPI controller is not
    modeled). The named variant target is used instead of `all` because oca-images
    needs uv + the tt-oca-manifest submodule, which the ELF does not."""
    if request.config.getoption("build"):
        res = _make(
            request.config,
            "-C",
            str(paths.BOOTCODE_DIR),
            "ot-toolchain-images",
            cwd=paths.OCAH_ROOT,
        )
        if res.returncode != 0:
            pytest.fail(f"bootcode build failed:\n{res.stdout[-2000:]}\n{res.stderr[-2000:]}")
    if not paths.BOOTCODE_ELF.is_file():
        pytest.skip(f"boot_rom.elf not present ({paths.BOOTCODE_ELF}); build it or drop --no-build")
    return paths.BOOTCODE_ELF


@pytest.fixture(scope="session")
def oca_images(request):
    """Build (unless --no-build) the three OCA boot images and return their paths.

    Returns a dict keyed "unsigned" / "signed" / "encrypted" / "otp_key" /
    "smc_bundle". One fixture rather
    than three because they come from a single make target and share every
    prerequisite, so splitting them would just triple the build check.

    container_ok=False because the pack step
    is Python and wants uv, which the toolchain container does not carry. The BL1
    payload it packs needs a host RISC-V toolchain -- without one this skips
    rather than fails, which is a coverage hole worth knowing about.
    """
    imgs = {
        "unsigned": paths.OCA_NS_IMAGE,
        "signed": paths.OCA_SEC_IMAGE,
        "encrypted": paths.OCA_ENC_IMAGE,
        # Signed with the same dev0 key, but public_key_select_classic names an
        # OTP anchor (CHIPLET_PUBK_HASH0) instead of a ROM digest slot.
        "otp_key": paths.OCA_OTP_IMAGE,
        # Bare bundle for the SMC-SRAM path, not a combined SPI image.
        "smc_bundle": paths.OCA_SMC_BUNDLE,
        # Manifest bound to a chiplet identity via usage_constraints.
        "identity": paths.OCA_ID_IMAGE,
        "pqc": paths.OCA_PQC_IMAGE,
        "ecdsa": paths.OCA_ECDSA_IMAGE,
        "der": paths.OCA_DER_IMAGE,
        "aes128": paths.OCA_AES128_IMAGE,
        "sip_key": paths.OCA_SIP_KEY_IMAGE,
        "multi": paths.OCA_MULTI_IMAGE,
        "no_bl1": paths.OCA_NO_BL1_IMAGE,
        # ROM key slots 1-5, each signed by its own key (slot 0 is "signed").
        # Flat entries rather than a nested slot->path dict so the existence check
        # below still sees every path; tests/bootcode/test_bootcode_oca_rom_keys.py
        # rebuilds the slot map from these.
        **{f"rom_key{n}": paths.OCA_ROM_KEY_IMAGES[n] for n in range(1, 6)},
    }
    if request.config.getoption("build"):
        res = _make(
            request.config,
            "-C",
            str(paths.BOOTCODE_DIR),
            "oca-images",
            cwd=paths.OCAH_ROOT,
            container_ok=False,
        )
        if res.returncode != 0:
            pytest.skip(
                "oca-images build failed (tt-oca-manifest submodule initialized? "
                "uv and a RISC-V toolchain on PATH?):\n"
                f"{res.stdout[-1500:]}\n{res.stderr[-1500:]}"
            )
    missing = [str(p) for p in imgs.values() if not p.is_file()]
    if missing:
        pytest.skip(f"OCA images not present: {', '.join(missing)}; build them or drop --no-build")
    return imgs


@pytest.fixture
def fw_test_builder(request):
    """Return build(name) -> ELF path for a hw/sys/sep/dv/fw test (skips on build failure).

    Tests are built by the shared DV firmware engine at the repo root
    (`make ocah-dv-fw-tests TARGET=sep TEST=<name>`), which drops
    build/tests/<name>/<name>.tcm.elf (default link mode)."""

    def _build(name):
        test_dir = paths.FW_TESTS_DIR / name
        if not test_dir.is_dir():
            pytest.skip(f"hw/sys/sep/dv/fw/tests/{name} not found")
        if request.config.getoption("build"):
            res = _make(
                request.config,
                "-C",
                str(paths.OCAH_ROOT),
                "ocah-dv-fw-tests",
                "TARGET=sep",
                f"TEST={name}",
                cwd=paths.OCAH_ROOT,
            )
            if res.returncode != 0:
                pytest.skip(f"dv fw test {name} build failed:\n{res.stderr[-1500:]}")
        elf = paths.fw_test_elf(name)
        if not elf.is_file():
            pytest.skip(f"{elf.name} not present after build")
        return elf

    return _build


@pytest.fixture
def vp(request):
    """Factory: vp(SimConfig) -> a SepVpHarness wired with the session options.

    All harnesses created in a test are closed (VP terminated) at teardown, even on failure.
    """
    created = []

    def _make_harness(config: SimConfig) -> SepVpHarness:
        h = SepVpHarness(
            config,
            sep_vp_bin=request.config.getoption("--vp-bin"),
            stream=request.config.getoption("--stream"),
        )
        created.append(h)
        return h

    yield _make_harness
    for h in created:
        h.close()
