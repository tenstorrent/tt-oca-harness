# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""SepVpHarness — the sep-vp backend for :class:`sepvp.harness.Harness`.

Per run it:
  1. makes a clean working dir under ``logs/sepvp/<name>/`` (so logs/artifacts don't collide),
  2. stages the SPI flash image to ``<run_dir>/data/flash_memory.bin`` and names it to the
     platform via ``spiBackdoorFile``,
  3. writes an overlay ini (``@include base`` + straps + fuses + absolute targets/
     configFile),
  4. ``pexpect.spawn``s ``sep-vp overlay.ini <abs elf>`` from ``<run_dir>`` so main.cpp
     chdir()s into the run dir,
  5. drives the inherited ``expect()`` API over the platform's decoded stdout.
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

import pexpect

from sepvp import paths
from sepvp.config import SMC_SRAM_DEFAULT_OFFSET, SMC_SRAM_SIZE_BYTES
from sepvp.harness import Harness, HarnessError
from sepvp.inifile import render_overlay, stage_base_config

# Where the staged raw-binary flash image lands, relative to the run dir. Any path works
# now that `spiBackdoorFile` names it explicitly; kept for continuity with the model's tests.
_FLASH_REL = Path("data") / "flash_memory.bin"
_SMC_SRAM_REL = Path("data") / "smc_sram_image.bin"
_TRACE_REL = Path("veer_trace.log")


class _Tee:
    """A minimal write-only file-like that fans out to several streams (for logfile_read)."""

    def __init__(self, *streams):
        self._streams = [s for s in streams if s is not None]

    def write(self, data):
        for s in self._streams:
            s.write(data)
        return len(data)

    def flush(self):
        for s in self._streams:
            try:
                s.flush()
            except Exception:  # noqa: BLE001
                pass


class SepVpHarness(Harness):
    """Launch one :class:`~sepvp.config.SimConfig` on sep-vp."""

    def __init__(
        self,
        config,
        *,
        run_root: Path | None = None,
        sep_vp_bin: Path | None = None,
        base_ini: Path | None = None,
        stream: bool = False,
    ):
        super().__init__(config)
        self.sep_vp_bin = Path(sep_vp_bin) if sep_vp_bin else paths.sep_vp_bin()
        self.base_ini = Path(base_ini) if base_ini else paths.base_ini()
        self.run_root = Path(run_root) if run_root else paths.LOGS_DIR
        self.run_dir = self.run_root / config.name
        self.stream = stream
        self.log_path = self.run_dir / "sep-vp.log"
        self.overlay_path = self.run_dir / "overlay.ini"
        self._log_file = None

    # -- ini generation --------------------------------------------------------
    def _abs_path_overrides(self):
        """Absolute path overrides the base config carries relatively.

        main.cpp chdir()s to the overlay's dir, so the base's relative ``targets`` /
        ``configFile`` would otherwise resolve against the run dir.

        The SEP_MSG_* name table is deliberately absent here: since tt-oca-harness-model 4c44a0dd it is
        a *build-time* choice baked into sep_scratch_cold
        (``-DSEP_SCRATCH_COLD_STATUS_VALUES_PATH``, set by this repo's virtual_platform
        Makefile via ``STATUS_VALUES_TSV``). There is no runtime key for it, and an unknown
        CCI key is accepted as an unconsumed preset -- i.e. it would fail silently.
        """
        elf = Path(self.config.elf).resolve()

        # `spiPreload` is handled by commenting it out of the staged base config (see
        # _prepare_run_dir) rather than overridden here: the ini parser cannot represent an
        # empty string value, and only an *absent* key leaves the `spiBackdoorFile` branch
        # reachable. A run that opts in gets an absolute path instead.
        overrides = [
            ("string", "och_sep_ss1.targets", str(elf)),
            ("string", "och_sep_ss1.configFile", str(paths.VEERISS_CONFIG.resolve())),
            # The platform config ships `otbn.algorithm_type : otbn_loop`, a loop
            # benchmark with no RSA in it, so RSA-3072 signature verification can
            # never succeed under the default. Any signed manifest then fails with
            # RSA_PKCS1_FAIL, which reads as a bad image rather than a stubbed
            # accelerator.
            #
            # Set here rather than per test: the ROM links the OTBN RSA app
            # unconditionally, so no sep-vp run of this firmware ever wants the
            # loop model. A test that genuinely wants a different algorithm can
            # still override it through SimConfig.extra_ini, which composes after
            # these.
            ("string", "och_sep_ss1.otbn.algorithm_type", "rsa_3072"),
            # The base config traces every retired instruction (~862 MB per ROM boot); an empty
            # name cannot be expressed, so the trace goes to /dev/null unless iss_trace is set.
            ("string", "och_sep_ss1.traceFile", self._trace_sink()),
        ]
        if self.config.spi_preload:
            overrides.append(
                ("string", "och_sep_ss1.spiPreload", str(Path(self.config.spi_preload).resolve()))
            )
        if self.config.flash_image:
            # The raw-binary backdoor is opt-in via `spiBackdoorFile`; the platform no
            # longer falls back to an implicit data/flash_memory.bin when spiPreload is
            # absent, so the staged image has to be named explicitly or the manifest
            # reads hit erased 0xFF flash.
            overrides.append(
                (
                    "string",
                    "och_sep_ss1.spiBackdoorFile",
                    str((self.run_dir / _FLASH_REL).resolve()),
                )
            )
        if self.config.smc_sram_image:
            overrides.append(
                (
                    "string",
                    "och_sep_ss1.smcSramBackdoorFile",
                    str((self.run_dir / _SMC_SRAM_REL).resolve()),
                )
            )
            if self.config.smc_sram_offset is not None:
                overrides.append(
                    ("uint", "och_sep_ss1.smcSramBackdoorOffset", self.config.smc_sram_offset)
                )
        return overrides

    def _trace_sink(self) -> str:
        return str((self.run_dir / _TRACE_REL).resolve()) if self.config.iss_trace else "/dev/null"

    def render_ini(self) -> str:
        """The overlay ini text for this run (also used by ``--ini-only``).

        The overlay ``@include``s the base by basename; :meth:`_prepare_run_dir` stages the
        base (and its includes) into the run dir so that basename resolves.
        """
        overrides = [*self._abs_path_overrides(), *self.config.overrides()]
        return render_overlay(self.base_ini.name, overrides)

    # -- launch ----------------------------------------------------------------
    def _prepare_run_dir(self):
        if self.run_dir.exists():
            shutil.rmtree(self.run_dir)
        self.run_dir.mkdir(parents=True)
        if self.config.flash_image:
            src = Path(self.config.flash_image)
            if not src.is_file():
                raise FileNotFoundError(f"SPI flash image not found: {src}")
            dst = self.run_dir / _FLASH_REL
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        if self.config.smc_sram_image:
            src = Path(self.config.smc_sram_image)
            if not src.is_file():
                raise FileNotFoundError(f"SMC SRAM image not found: {src}")
            offset = (
                SMC_SRAM_DEFAULT_OFFSET
                if self.config.smc_sram_offset is None
                else self.config.smc_sram_offset
            )
            if offset + src.stat().st_size > SMC_SRAM_SIZE_BYTES:
                raise HarnessError(
                    f"SMC SRAM image ({src.stat().st_size} bytes) at offset 0x{offset:x} runs "
                    "past the 1 MiB window; the platform would boot from an erased window"
                )
            dst = self.run_dir / _SMC_SRAM_REL
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        # Stage the base config + its @includes so the overlay's basename @include resolves.
        stage_base_config(self.base_ini, self.run_dir)
        self._disable_base_spi_preload()
        self.overlay_path.write_text(self.render_ini())

    def _disable_base_spi_preload(self):
        """Comment out the base config's `spiPreload` in the staged copy.

        tt-oca-harness-model ships the base config with a relative `och_sep_ss1.spiPreload`.
        The platform treats *any* non-empty value as "the preload owns the flash":

            if (not spiPreloadPath.empty())        { ...$readmemh preload... }
            else if (not spiBackdoorPath.empty())  { load_memory_from_file(spiBackdoorPath); }

        So leaving it set — even pointing at a path that fails to open, as the base config's
        relative one does from a run dir — silently disables the raw-binary backdoor, and any
        staged ``flash_image`` is ignored (manifest reads then hit erased flash and fail
        ``BAD_MAGIC``). Overriding it to an empty string is not an option: the ini parser
        throws on a valueless key. Commenting the line out is what tt-oca-harness-model's own tests do
        (``NO_SPIPRELOAD_INI`` in ``sw/sep-vp-tests/Makefile.common``).

        The backdoor half is opt-in: ``spiBackdoorFile`` names the staged image explicitly
        (see :meth:`_abs_path_overrides`). Commenting out ``spiPreload`` is what makes that
        branch reachable, so both halves are still required.

        A run that genuinely wants a $readmemh preload sets ``SimConfig.spi_preload``, which
        re-adds the key with an absolute path in :meth:`_abs_path_overrides`.
        """
        staged = self.run_dir / self.base_ini.name
        text = staged.read_text()
        patched = re.sub(r"(?m)^(\s*och_sep_ss1\.spiPreload\b)", r"#\1", text)
        if patched != text:
            staged.write_text(patched)

    def _check_inputs(self):
        if not self.sep_vp_bin.is_file():
            raise HarnessError(
                f"sep-vp binary not found: {self.sep_vp_bin} (build it with `make vp`)"
            )
        elf = Path(self.config.elf)
        if not elf.is_file():
            raise HarnessError(f"ELF not found: {elf}")
        if not self.base_ini.is_file():
            raise HarnessError(f"base config ini not found: {self.base_ini}")

    def spawn(self):
        self._check_inputs()
        self._prepare_run_dir()
        elf = str(Path(self.config.elf).resolve())

        # Pass the overlay by basename so main.cpp's chdir() lands in the run dir.
        argv = ["overlay.ini", elf]
        self._log_file = open(self.log_path, "w")
        self.child = pexpect.spawn(
            str(self.sep_vp_bin),
            argv,
            cwd=str(self.run_dir),
            env=paths.vp_env(),
            encoding="utf-8",
            codec_errors="replace",
            timeout=self.config.boot_timeout,
            dimensions=(200, 400),
        )
        self.child.logfile_read = _Tee(self._log_file, sys.stdout if self.stream else None)
        return self

    def _close_log(self):
        if self._log_file is not None:
            try:
                self._log_file.flush()
                self._log_file.close()
            finally:
                self._log_file = None
