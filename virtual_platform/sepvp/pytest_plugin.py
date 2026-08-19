"""Shared pytest plugin for the sep-vp harness suites.

This module is the single home for the harness framework — the CLI options, the
firmware-build helpers, the run fixtures, and the marker registrations — so that it
lives with the rest of the runner logic inside the ``sepvp`` package. The test suites
(everything under ``virtual_platform/tests/``) load it via
``pytest_plugins = ["sepvp.pytest_plugin"]`` from the thin bootstrap conftest at
``virtual_platform/conftest.py``.

Options (mirroring the example bootcode harness where it makes sense):
  --vp-bin PATH        sep-vp executable (default: the in-tree build)
  --gcc-toolset NAME   gcc-toolset providing the C++ runtime (default gcc-toolset-11)
  --vp-timeout N       default per-run boot timeout in seconds (default 120)
  --no-build           do not (re)build firmware; use whatever ELF already exists
  --build-type T       'test' (DEBUG: SIM_OUT on) or 'release' (default test)
  --stream             tee sep-vp stdout to the console live
  --riscv-toolchain P  RISC-V toolchain prefix dir (for firmware builds)

Fixtures:
  vp                   factory: vp(SimConfig) -> SepVpHarness (auto-closed on teardown)
  bootcode_elf         builds the boot ROM OT variant (unless --no-build); returns boot_rom.elf
  secure_boot_preload  generates build/secure_boot.spi_preload (unless --no-build)
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
    g.addoption("--gcc-toolset", default="gcc-toolset-11", help="gcc-toolset for the C++ runtime")
    g.addoption("--vp-timeout", type=int, default=120, help="default per-run boot timeout (s)")
    g.addoption("--no-build", dest="build", action="store_false", default=True,
                help="do not rebuild firmware before running")
    g.addoption("--build-type", choices=["test", "release"], default="test",
                help="firmware build type: test (DEBUG/SIM_OUT) or release")
    g.addoption("--stream", action="store_true", help="tee sep-vp stdout to the console")
    g.addoption("--riscv-toolchain", default=str(paths.DEFAULT_RISCV_TOOLCHAIN),
                help="RISC-V toolchain dir (its bin/ is prepended to PATH for firmware builds)")


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
    tc_bin = Path(config.getoption("--riscv-toolchain")) / "bin"
    if tc_bin.is_dir():
        env["PATH"] = f"{tc_bin}{os.pathsep}{env.get('PATH', '')}"
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
                ["riscv64-unknown-elf-gcc", "--specs=picolibc.specs",
                 "-x", "c", "-c", "-", "-o", os.devnull],
                input="int main(void){return 0;}", env=env,
                capture_output=True, text=True, timeout=60,
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
    argv = ["make", *make_args]
    if container_ok and not _native_fw_toolchain(env):
        argv = [str(paths.OCAH_ROOT / "scripts" / "docker-run.sh"),
                "run-here", "make", *make_args]
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
    modeled). The named variant target is used instead of `all` because pack-images
    needs uv + the tt-boot-manifest submodule, which the ELF does not."""
    if request.config.getoption("build"):
        res = _make(request.config, "-C", str(paths.BOOTCODE_DIR),
                    "ot-toolchain-images", cwd=paths.OCAH_ROOT)
        if res.returncode != 0:
            pytest.fail(f"bootcode build failed:\n{res.stdout[-2000:]}\n{res.stderr[-2000:]}")
    if not paths.BOOTCODE_ELF.is_file():
        pytest.skip(f"boot_rom.elf not present ({paths.BOOTCODE_ELF}); build it or drop --no-build")
    return paths.BOOTCODE_ELF


@pytest.fixture(scope="session")
def secure_boot_preload(request):
    """Generate (unless --no-build) and return the signed SPI image the OT-negative
    suite tampers with: build/secure_boot.spi_preload.

    Unlike the old repo's checked-in prebuilt, this is generated by the bootrom's
    secure_boot_spi target, which needs uv on PATH and the tt-boot-manifest
    submodule initialized (git submodule update --init
    hw/sys/sep/bootrom/prod/tools/tt-boot-manifest)."""
    if request.config.getoption("build"):
        res = _make(request.config, "-C", str(paths.BOOTCODE_DIR),
                    "secure_boot_spi", cwd=paths.OCAH_ROOT, container_ok=False)
        if res.returncode != 0:
            pytest.skip(
                "secure_boot_spi build failed (tt-boot-manifest submodule initialized? "
                f"uv on PATH?):\n{res.stdout[-1500:]}\n{res.stderr[-1500:]}")
    if not paths.SECURE_BOOT_PRELOAD.is_file():
        pytest.skip(f"{paths.SECURE_BOOT_PRELOAD} not present; build it or drop --no-build")
    return paths.SECURE_BOOT_PRELOAD


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
            res = _make(request.config, "-C", str(paths.OCAH_ROOT),
                        "ocah-dv-fw-tests", "TARGET=sep", f"TEST={name}",
                        cwd=paths.OCAH_ROOT)
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
            gcc_toolset=request.config.getoption("--gcc-toolset"),
            stream=request.config.getoption("--stream"),
        )
        created.append(h)
        return h

    yield _make_harness
    for h in created:
        h.close()
