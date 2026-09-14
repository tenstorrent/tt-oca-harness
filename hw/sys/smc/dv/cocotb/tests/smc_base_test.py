# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared PyUVM base test for SMC OSS (`--dut smc`).

Builds `SmcEnv`, runs power-good + cold-reset bring-up, and delegates scenario
work to `run_scenario()`.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles
from pyuvm import ConfigDB, uvm_test

_COCOTB_ROOT = Path(__file__).resolve().parents[1]
_OSS_HW_ROOT = Path(__file__).resolve().parents[5]
for _path in (_COCOTB_ROOT, _OSS_HW_ROOT / "common" / "dv" / "vip"):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.insert(0, _path_str)

from env.smc_env import SmcEnv
from env.smc_env_cfg import SYS_OUT_AXI_GEOMETRY, SYS_OUT_MEM_SIZE, SmcEnvCfg
from env.smc_probe_liveness import reset_probe_ledger, watch_probe_liveness
from env.smc_protocol_vip_item import SmcProtocolVipItem, SmcProtocolVipKind
from env.smc_virt_console import VirtConsole
from ocah_axi_vip import OcahAxiSlaveAgent
from seq_lib._one_shot import _OneShot

# Test-class-name -> protocol VIP kind for the auto-record at the end of
# run_phase. A test may instead set the ``protocol_vip_kind`` class attribute
# (see smc_base_test.run_phase), which keeps the kind next to the test; a typo
# in this map silently skips the auto-record.
_PROTOCOL_VIP_TESTS = {
    "smc_i2c_master_target_test": SmcProtocolVipKind.I2C,
    "smc_i2c_p1_rdwr_protocol_test": SmcProtocolVipKind.I2C,
    "smc_i2c_error_fifo_depth_test": SmcProtocolVipKind.I2C,
    "smc_smbus_pmbus_test": SmcProtocolVipKind.I2C,
    "smc_smbus_hostnotify_test": SmcProtocolVipKind.I2C,
    "smc_i3c_to_fabric_test": SmcProtocolVipKind.I3C,
    "smc_ijtag_basic_test": SmcProtocolVipKind.JTAG,
    "smc_efuse_jtag_lc_negative_test": SmcProtocolVipKind.JTAG,
    "smc_efuse_jtag_lc_access_matrix_test": SmcProtocolVipKind.JTAG,
    "smc_jtag_reset_proxy_test": SmcProtocolVipKind.JTAG,
    "smc_input_output_fabric_wr_rd_test": SmcProtocolVipKind.OUTPUT_FABRIC,
    "smc_output_filter_remap_security_test": SmcProtocolVipKind.OUTPUT_FABRIC,
    "smc_output_fabric_wr_rd_responder_test": SmcProtocolVipKind.OUTPUT_FABRIC,
    "smc_output_fabric_slverr_inject_test": SmcProtocolVipKind.OUTPUT_FABRIC,
    "smc_mailbox_irq_test": SmcProtocolVipKind.MAILBOX,
    "smc_mailbox_data_error_test": SmcProtocolVipKind.MAILBOX,
    "smc_mailbox_event_irq_test": SmcProtocolVipKind.MAILBOX,
    "smc_efuse_otp_clock_test": SmcProtocolVipKind.EFUSE,
    "smc_efuse_otp_clock_config_depth_test": SmcProtocolVipKind.EFUSE,
    "smc_efuse_permission_boundary_test": SmcProtocolVipKind.EFUSE,
    "smc_efuse_chip_config_read_test": SmcProtocolVipKind.EFUSE,
    "smc_static_cg_sanity_test": SmcProtocolVipKind.CLOCK,
    "smc_gpio_irq_active_test": SmcProtocolVipKind.GPIO_IRQ,
    "smc_uart_spi_log_engine_test": SmcProtocolVipKind.UART_LOG,
    "smc_uart_log_engine_reg_rw_test": SmcProtocolVipKind.UART_LOG,
    "smc_uart_log_engine_error_boundary_test": SmcProtocolVipKind.UART_LOG,
    "smc_uart_loopback_test": SmcProtocolVipKind.UART_LOG,
    "smc_spi_pad_bfm_test": SmcProtocolVipKind.UART_LOG,
    "smc_sideband_protocol_smoke_test": SmcProtocolVipKind.SIDEBAND,
    "smc_octs_dual_sync_test": SmcProtocolVipKind.SIDEBAND,
    "smc_octs_sanity_test": SmcProtocolVipKind.SIDEBAND,
    "smc_avsbus_sanity_test": SmcProtocolVipKind.SIDEBAND,
    "smc_avsbus_status_depth_test": SmcProtocolVipKind.SIDEBAND,
    "smc_avsbus_clock_config_proxy_test": SmcProtocolVipKind.SIDEBAND,
    "smc_zeroer_dma_timeout_test": SmcProtocolVipKind.ZEROER_DMA,
    "smc_zeroer_sanity_test": SmcProtocolVipKind.ZEROER_DMA,
    "smc_dma_sanity_test": SmcProtocolVipKind.ZEROER_DMA,
    "smc_ecc_dfd_dbs_sanity_test": SmcProtocolVipKind.DIAGNOSTIC,
    "smc_dfd_sanity_test": SmcProtocolVipKind.DIAGNOSTIC,
    "smc_cpu_ecc_lint_pint_depth_test": SmcProtocolVipKind.DIAGNOSTIC,
    "smc_dbs_idle_test": SmcProtocolVipKind.DIAGNOSTIC,
    "smc_cpu_to_sep_axi_test": SmcProtocolVipKind.CPU,
    "smc_cpu_sanity_test": SmcProtocolVipKind.CPU,
    "smc_cpu_firmware_boot_test": SmcProtocolVipKind.CPU,
    "smc_occp_sanity_secure_error_test": SmcProtocolVipKind.CPU,
    "smc_efuse_otp_burn_shadow_test": SmcProtocolVipKind.EFUSE,
    "smc_ecc_fault_inject_test": SmcProtocolVipKind.DIAGNOSTIC,
    "smc_cpu_ctrl_map_depth_test": SmcProtocolVipKind.CPU,
    "smc_cpu_ctrl_scratch_window_test": SmcProtocolVipKind.CPU,
    "smc_mailbox_inbound_test": SmcProtocolVipKind.MAILBOX,
    "smc_i2c_multi_instance_test": SmcProtocolVipKind.I2C,
    "smc_efuse_map_read_test": SmcProtocolVipKind.EFUSE,
    "smc_efuse_shim_ctrl_test": SmcProtocolVipKind.EFUSE,
    "smc_gpio_ctrl_full_sweep_test": SmcProtocolVipKind.GPIO_IRQ,
    "smc_telemetry_receiver_csr_test": SmcProtocolVipKind.SIDEBAND,
    "smc_remap_cla_test": SmcProtocolVipKind.OUTPUT_FABRIC,
    "smc_mailbox_multi_instance_test": SmcProtocolVipKind.MAILBOX,
    "smc_filter_multi_entry_test": SmcProtocolVipKind.OUTPUT_FABRIC,
    "smc_gpio_intf_full_sweep_test": SmcProtocolVipKind.GPIO_IRQ,
    "smc_mailbox_field_sweep_test": SmcProtocolVipKind.MAILBOX,
    "smc_filter_field_sweep_test": SmcProtocolVipKind.OUTPUT_FABRIC,
    "smc_xvisor_remap_test": SmcProtocolVipKind.OUTPUT_FABRIC,
    "smc_cluster_beu_test": SmcProtocolVipKind.CPU,
}


# ==================================================== build-model identity ====
# `[BUILD-MODEL-IDENTITY]`. The SMC sim stage runs with `do_build: False` and
# reuses a prebuilt model out of the SHARED path hw/sys/smc/dv/build/cocotb/<tool>
# (`<tool>/<target>/coverage` for a `--cov` VCS run; run_dv.py exports that leaf
# as OCAH_SIM_BUILD_DIR), so the run's own hdl_compile log records only
# "Nothing to be done for 'default'"
# and the kept log cannot say what RTL it simulated. The build directory is
# overwritten in place by the next `--rebuild`, so an identity recovered by hand
# afterwards is unverifiable.
#
# So the identity is recorded from the cocotb side, into the kept log, at
# start-of-simulation: the sha256 of the simulated model artifact, of the resolved
# elaboration-dependency list, and of the compile filelist the build consumed. If
# any of it cannot be determined the test FAILS -- a placeholder would be worse
# than nothing, because it would make an un-attributable run look attributed.
_MODEL_ROOT_REL = Path("hw") / "sys" / "smc" / "dv" / "build" / "cocotb"
_COMPILE_FLIST_REL = Path("hw") / "sys" / "smc" / "dv" / "build" / "smc_dut_compile.f"

# tool -> (model artifact, resolved-compile-input list) relative to the leaf
# elaboration directory `_model_build_dir` returns. The model artifact is the
# thing the simulator actually ran. VCS writes `simv` in that leaf
# (`<tool>/<target>` or `<tool>/<target>/coverage`); the `default/` segment
# belongs in the directory, not in this relative path.
_MODEL_ARTIFACTS: dict[str, tuple[str, str | None]] = {
    "verilator": ("smc_uvm_top", "Vtop__ver.d"),
    "vcs": ("simv", None),
    "xcelium": ("xrun_snapshot", "xrun_build.log"),
}

# A simulator reports the name of its executable, which is not always the tool
# key above: Xcelium runs as `xmsim`. Map the reported names onto keys instead of
# loosening the substring match below, so a simulator nobody has registered still
# fails rather than resolving to whichever key happens to share a few letters.
_SIM_NAME_ALIASES: dict[str, str] = {
    "xmsim": "xcelium",
    "ncsim": "xcelium",
}

_MODEL_IDENTITY_DONE: list[str] = []


def _repo_root() -> Path:
    root = os.environ.get("OCH_ROOT")
    if root:
        return Path(root)
    return Path(__file__).resolve().parents[6]


def _sim_tool() -> str:
    """Simulator key for :data:`_MODEL_ARTIFACTS`, from the live simulator."""
    name = (getattr(cocotb, "SIM_NAME", "") or "").strip().lower()
    assert name, (
        "[BUILD-MODEL-IDENTITY] cocotb.SIM_NAME is empty: the run cannot name "
        "the simulator it is executing in, so it cannot name the model either"
    )
    for alias, tool in _SIM_NAME_ALIASES.items():
        if alias in name:
            return tool
    for tool in _MODEL_ARTIFACTS:
        if tool in name:
            return tool
    raise AssertionError(
        f"[BUILD-MODEL-IDENTITY] simulator {name!r} has no entry in "
        f"_MODEL_ARTIFACTS ({sorted(_MODEL_ARTIFACTS)}), so this run cannot "
        f"state which elaborated model it simulated. Add the tool's model "
        f"artifact rather than letting the kept log stay silent."
    )


def _digest(path: Path) -> tuple[str, int]:
    """(sha256, size) of a file, or a metadata fingerprint of a directory.

    A directory-shaped model (xcelium snapshot) is fingerprinted from the sorted
    (relative path, size) list of its files -- content-hashing a whole snapshot
    tree every test is not worth the runtime, and the fingerprint still changes
    whenever the snapshot is rebuilt.
    """
    digest = hashlib.sha256()
    if path.is_dir():
        total = 0
        entries = sorted(p for p in path.rglob("*") if p.is_file())
        assert entries, (
            f"[BUILD-MODEL-IDENTITY] {path} is an empty directory: there is no "
            f"model artifact to fingerprint"
        )
        for entry in entries:
            size = entry.stat().st_size
            total += size
            digest.update(str(entry.relative_to(path)).encode())
            digest.update(str(size).encode())
        return digest.hexdigest(), total
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _mtime_utc(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _model_build_dir(root: Path, tool: str) -> Path:
    """Return the leaf directory the simulated model was elaborated into.

    run_dv.py exports that leaf as OCAH_SIM_BUILD_DIR, including
    `<tool>/<target>/coverage` on a `--cov` VCS run. Without it, VCS falls
    back to the non-coverage default leaf under the shared cocotb build tree;
    other tools use the tool directory itself.
    """
    exported = os.environ.get("OCAH_SIM_BUILD_DIR")
    if exported:
        return Path(exported)
    base = root / _MODEL_ROOT_REL / tool
    if tool == "vcs":
        return base / "default"
    return base


def _require(path: Path, what: str) -> Path:
    assert path.exists(), (
        f"[BUILD-MODEL-IDENTITY] {what} not found at {path}: this run cannot "
        f"state which elaborated model it simulated. Failing loudly instead of "
        f"logging a placeholder -- a kept log that names no model cannot support "
        f"any claim about the RTL that was in the DUT."
    )
    return path


def log_build_model_identity() -> str:
    """Log (once per process) the identity of the model this run simulated.

    Returns the emitted line. Raises with a diagnostic if the identity cannot be
    determined; there is no placeholder branch.
    """
    if _MODEL_IDENTITY_DONE:
        return _MODEL_IDENTITY_DONE[0]
    root = _repo_root()
    tool = _sim_tool()
    model_rel, deps_rel = _MODEL_ARTIFACTS[tool]
    build_dir = _require(_model_build_dir(root, tool), f"{tool} build directory")
    model = _require(build_dir / model_rel, f"{tool} elaborated model artifact")
    model_sha, model_size = _digest(model)
    flist = _require(root / _COMPILE_FLIST_REL, "resolved compile filelist")
    flist_sha, _flist_size = _digest(flist)
    # Line count only, as a coarse change tell. The authoritative resolved-input
    # identity is `deps_sha256` (the elaboration dependency list): this filelist
    # is mostly `-f` includes, so its own line count says little.
    flist_lines = len(flist.read_text(encoding="utf-8", errors="replace").splitlines())
    deps_part = "deps=none"
    if deps_rel is not None:
        deps = _require(build_dir / deps_rel, f"{tool} elaboration input list")
        deps_sha, _deps_size = _digest(deps)
        deps_part = (
            f"deps={deps.relative_to(root)} deps_sha256={deps_sha} deps_mtime={_mtime_utc(deps)}"
        )
    line = (
        "CHK-BUILD-MODEL-IDENTITY: this run simulated "
        f"tool={tool} sim={getattr(cocotb, 'SIM_NAME', '?')} "
        f"version={getattr(cocotb, 'SIM_VERSION', '?')} "
        f"model={model.relative_to(root)} model_sha256={model_sha} "
        f"model_bytes={model_size} model_mtime={_mtime_utc(model)} "
        f"{deps_part} "
        f"flist={flist.relative_to(root)} flist_sha256={flist_sha} "
        f"flist_lines={flist_lines} flist_mtime={_mtime_utc(flist)} "
        f"seed={os.environ.get('RANDOM_SEED', 'unset')}"
    )
    cocotb.log.info(line)
    _MODEL_IDENTITY_DONE.append(line)
    return line


class _EvidenceRecorder:
    """Collect the named evidence a run emits, by watching every log record.

    Sequences report each graded contract as a ``CHK-<ID>: ...`` line. Most log
    it through ``cocotb.log``; tests and env components log through their pyuvm
    logger, which does not propagate to the root handler, so a filter on any one
    logger would miss part of the run. The log-record factory sees every record
    regardless of logger, so that is where the IDs are read. Reading them from
    the records keeps the log line the single source of the ID -- a separate
    registration call could drift from what the log actually carries.

    Only a token at the start of the message counts: prose that mentions a
    check ("... the byte verdict is CHK-I2C-...") is not an emission.
    """

    _CHK = re.compile(r"^\s*(CHK-[A-Za-z0-9][A-Za-z0-9_-]*)\b")

    # Emitted by smc_base_test on every run, before the scenario: the model
    # identity line and the probe positive controls ``run_phase`` executes.
    # Counted in ``observed`` but excluded from ``own``, so a leaf cannot satisfy
    # the gate on bring-up alone.
    BASE_IDS = frozenset({"CHK-BUILD-MODEL-IDENTITY"})
    BASE_PREFIXES = ("CHK-PROBE-",)

    # Leaves that emit no CHK-* line of their own, with the channel each one
    # grades through instead. Every entry is a LOGGING gap, not a verification
    # gap: each grades through sequence-level asserts, the scoreboard's
    # ``expected=`` compares, or a protocol-VIP record with a stimulus floor,
    # and none is a clean exit that checks nothing. Naming them is what lets the
    # gate below be unconditional for every other leaf.
    #
    # owner: SMC DV. opened: 2026-09-13, from the leaves that emitted no token
    # of their own at introduction. review_date: NO_OWN_EVIDENCE_REVIEW_DATE.
    # Closes when empty. Keys must stay inside NO_OWN_EVIDENCE_CEILING (the
    # set at introduction); a new name fails the run. To remove an entry, make
    # the check that already runs log a ``CHK-<ID>:`` line where it happens --
    # in the sequence, not here.
    NO_OWN_EVIDENCE = {
        # Scoreboard protocol-VIP record with a stimulus floor, plus expected=
        # compares on every CSR read the sequence issues.
        "smc_dma_sanity_test": "protocol-VIP floor and scoreboard compares",
        "smc_filter_field_sweep_test": "protocol-VIP floor and scoreboard compares",
        "smc_gpio_ctrl_full_sweep_test": "protocol-VIP floor and scoreboard compares",
        "smc_gpio_intf_full_sweep_test": "protocol-VIP floor and scoreboard compares",
        "smc_i2c_multi_instance_test": "protocol-VIP floor and scoreboard compares",
        "smc_mailbox_inbound_test": "protocol-VIP floor and scoreboard compares",
        "smc_mailbox_multi_instance_test": "protocol-VIP floor and scoreboard compares",
        "smc_occp_sanity_secure_error_test": "protocol-VIP floor and sequence asserts",
        "smc_register_boundary_depth_test": "protocol-VIP floor and scoreboard compares",
        "smc_register_sanity_test": "protocol-VIP floor and scoreboard compares",
        "smc_spi_pad_bfm_test": "protocol-VIP floor and sequence asserts",
        "smc_uart_loopback_test": "protocol-VIP floor and sequence asserts",
        "smc_xvisor_remap_test": "protocol-VIP floor and scoreboard compares",
        # Asserts in the sequence the leaf starts; the log line carries no ID.
        "smc_flr_sanity_test": "sequence asserts, unlabelled",
        "smc_gpio_irq_type_matrix_test": "sequence asserts, unlabelled",
        "smc_gpio_output_driveback_test": "sequence asserts, unlabelled",
        "smc_smbus_alert_ara_test": "in-leaf asserts on sequence flags, unlabelled",
        # Asserts in the leaf on the scoreboard's memory-model compare counters.
        "smc_output_fabric_slverr_inject_test": "in-leaf asserts, unlabelled",
        "smc_output_fabric_wr_rd_responder_test": "in-leaf asserts, unlabelled",
        # Sequence asserts; the protocol-VIP record it books is an activity
        # stamp (csr_accesses=0, auto_evidence=True) and is not evidence.
        "smc_octs_dual_sync_test": "sequence asserts, unlabelled",
    }

    # Past this date, ``_finalize_evidence`` warns on every run while the set is
    # non-empty. Move it only after re-reading each entry that remains.
    NO_OWN_EVIDENCE_REVIEW_DATE = "2026-10-15"

    # Set at introduction. ``NO_OWN_EVIDENCE`` may lose keys, never gain them.
    NO_OWN_EVIDENCE_CEILING = frozenset(
        {
            "smc_dma_sanity_test",
            "smc_filter_field_sweep_test",
            "smc_flr_sanity_test",
            "smc_gpio_ctrl_full_sweep_test",
            "smc_gpio_intf_full_sweep_test",
            "smc_gpio_irq_type_matrix_test",
            "smc_gpio_output_driveback_test",
            "smc_i2c_multi_instance_test",
            "smc_mailbox_inbound_test",
            "smc_mailbox_multi_instance_test",
            "smc_occp_sanity_secure_error_test",
            "smc_octs_dual_sync_test",
            "smc_output_fabric_slverr_inject_test",
            "smc_output_fabric_wr_rd_responder_test",
            "smc_register_boundary_depth_test",
            "smc_register_sanity_test",
            "smc_smbus_alert_ara_test",
            "smc_spi_pad_bfm_test",
            "smc_uart_loopback_test",
            "smc_xvisor_remap_test",
        }
    )

    def __init__(self) -> None:
        self.seen: set[str] = set()
        self._previous_factory = logging.getLogRecordFactory()

    def install(self) -> None:
        logging.setLogRecordFactory(self._factory)

    def _factory(self, *args, **kwargs) -> logging.LogRecord:
        record = self._previous_factory(*args, **kwargs)
        try:
            message = record.getMessage()
        except Exception:  # a broken format string is the caller's failure, not ours
            return record
        match = self._CHK.match(message)
        if match:
            self.seen.add(match.group(1))
        return record

    @classmethod
    def is_base(cls, check_id: str) -> bool:
        return check_id in cls.BASE_IDS or check_id.startswith(cls.BASE_PREFIXES)


class smc_base_test(uvm_test):
    """Shared SMC OSS test: env build, clock/reset bring-up, scenario hook.

    A concrete test may set the class attribute ``protocol_vip_kind`` (a
    ``SmcProtocolVipKind``) to auto-stamp a protocol VIP activity record after
    ``run_scenario``; this is preferred over adding the test to the
    ``_PROTOCOL_VIP_TESTS`` map below. Set ``auto_protocol_vip = False`` to skip.

    The auto stamp is an *activity record*, never protocol evidence: it carries
    only the SYS-AXI transaction count the scoreboard measured and is booked in
    the scoreboard's separate ``protocol_vip_auto`` bin. A scenario that wants a
    real protocol VIP record sets ``auto_protocol_vip = False`` and calls
    ``record_protocol_vip(..., csr_accesses=<measured>,
    min_csr_accesses=<stimulus floor>, details=<scenario specific>)``.
    ``min_csr_accesses`` is **mandatory** on that path -- see
    :meth:`record_protocol_vip`.

    A test whose proof path contains an idle-zero compare on a ``tb_top``
    observability probe declares the matching positive control(s) in
    ``probe_positive_controls``; ``run_phase`` runs them before
    ``run_scenario`` so the scoreboard's idle legs in this test are backed by a
    same-run observation of the same probe at 1
    (``[NEGATIVE-NEEDS-POSITIVE-CONTROL]``). Legal names are the keys of
    ``seq_lib.smc_probe_positive_control.PROBE_CONTROLS``.
    """

    # Optional per-test override; None => fall back to the name map.
    protocol_vip_kind = None

    # Probe positive controls to run before run_scenario (see class docstring).
    probe_positive_controls: tuple[str, ...] = ()

    # Evidence gate. A clean exit is not a pass: a scenario whose stimulus
    # stopped reaching the DUT compares nothing, asserts nothing, and returns
    # normally. Every graded contract is reported as a ``CHK-<ID>:`` line, so
    # the base class counts what this run actually emitted and fails a silent
    # one (see ``_finalize_evidence``).
    #
    #   required_evidence -- IDs this test must emit. Missing any one fails.
    #   min_evidence      -- fewest distinct IDs of the test's OWN (lines the
    #                        base class emits do not count). 0 disables it.
    required_evidence: tuple[str, ...] = ()
    min_evidence = 0

    @staticmethod
    def random_seed() -> int:
        return int(os.environ.get("RANDOM_SEED", "1"), 0)

    def build_phase(self) -> None:
        self._evidence = _EvidenceRecorder()
        self._evidence.install()
        self.cfg = SmcEnvCfg("cfg")
        self.cfg.randomize_timing(self.random_seed())
        self.logger.info(
            "SMC timing: ref=%dns smc=%dns periph=%dns (seed=%d)",
            self.cfg.ref_clk_period_ns,
            self.cfg.smc_clk_period_ns,
            self.cfg.periph_clk_period_ns,
            self.random_seed(),
        )
        ConfigDB().set(None, "*", "cfg", self.cfg)
        self.env = SmcEnv("env", self)

    async def start_seq(self, seq, sequencer=None) -> None:
        seq.cfg = self.env.cfg
        seq.env = self.env
        if sequencer is None:
            sequencer = self.env.i2c_agent.sequencer
        await seq.start(sequencer)

    async def record_protocol_vip(
        self,
        kind: SmcProtocolVipKind,
        scenario: str,
        *,
        csr_accesses: int = 0,
        timeouts: int | None = None,
        proxy: bool = True,
        details: str = "",
        expected_bytes: bytes | None = None,
        observed_bytes: bytes | None = None,
        min_csr_accesses: int | None = None,
        fabric_accesses: int | None = None,
        min_fabric_accesses: int = 0,
        fabric_access_label: str = "",
        fabric_bus: str = "JTAG AXI",
        auto_evidence: bool = False,
    ) -> None:
        """Record a protocol VIP evidence item.

        ``min_csr_accesses`` turns ``csr_accesses`` from a printed statistic
        into a fail-capable floor: pass the number of CSR accesses the
        scenario's stimulus must have issued and the scoreboard fails the record
        when the measured count falls short.

        It is **mandatory** for a scenario-recorded item (``auto_evidence`` left
        False). Without a floor every assert the scoreboard applies to the
        record reduces to a constant (``N >= 0``), yet the item is still logged
        as "protocol VIP check #k", books a ``protocol_vip`` coverage bin, and
        can single-handedly satisfy ``check_phase``'s minimum-activity gate --
        i.e. a record that cannot fail presented as a check
        (``[NO-ALWAYS-PASS-CHECKER]`` / ``[NO-ZERO-ACTIVITY-PASS]``). Omitting
        it raises here, and the scoreboard refuses the item independently.

        The floor must be an independent constant written out at the call site,
        **not** read back from the sequence's own counter: a floor that shrinks
        with the sequence cannot catch a sequence that silently stops short.

        Non-CSR fabric traffic (JTAG-AXI writes and reads, output-fabric beats)
        is reported separately from ``csr_accesses`` so it is never mislabelled
        as CSR traffic, with its own ``min_fabric_accesses`` floor and a
        ``fabric_access_label`` naming what it is. **The observed count is
        measured here, not passed in**: it is read from the scoreboard's per-bus
        tally for ``fabric_bus`` (``SmcScoreboard.axi_accesses_by_bus``, stamped
        by the driver that completed each access). A call site that passes the
        floor constant as its own observation makes the scoreboard's
        ``fabric_accesses >= min_fabric_accesses`` assert a constant relation
        (``C >= C``) while the kept log advertises a measured-vs-minimum compare
        (``[NO-ALWAYS-PASS-CHECKER]``); measuring it here means no call site can
        reintroduce that shape.

        ``fabric_accesses`` is consequently an *optional exact expectation*, not
        the observation: when given, the measured count must equal it exactly, so
        a literal ``fabric_accesses=4`` at a call site becomes a real
        expectation-vs-measurement compare instead of a tautology.

        ``timeouts`` defaults to **None** = "not measured on this path" and
        prints as ``n/a``. Printing 0 for an unmeasured counter manufactures a
        clean-looking statistic and makes the scoreboard's
        ``timeouts <= csr_accesses`` relation a second constant, so a literal 0
        must be passed explicitly and only by a path that really measured zero
        timeouts (``[EXACT-EXPECTATION]``).
        """
        if auto_evidence:
            # An auto stamp is booked in the scoreboard's activity bin, never as
            # a check, so it carries no floor by construction.
            assert min_csr_accesses is None, (
                "auto_evidence records are activity stamps and must not carry min_csr_accesses"
            )
            min_csr_accesses = 0
        else:
            assert min_csr_accesses is not None, (
                f"record_protocol_vip({kind.value}, {scenario!r}): a "
                f"scenario-recorded protocol VIP item needs an explicit "
                f"min_csr_accesses. Without a floor every assert on the record "
                f"reduces to a constant while the item is still logged and "
                f"counted as a protocol VIP *check* ([NO-ALWAYS-PASS-CHECKER]). "
                f"Pass the CSR-access floor this scenario's stimulus must "
                f"issue, or set auto_evidence=True to book it as an activity "
                f"stamp instead."
            )
            assert min_csr_accesses > 0 or expected_bytes is not None, (
                f"record_protocol_vip({kind.value}, {scenario!r}): "
                f"min_csr_accesses=0 is only legal together with a byte golden "
                f"(expected_bytes), which is then what makes the record "
                f"fail-capable. A scenario with neither CSR-access floor nor "
                f"golden has nothing on the record that can fail and must be "
                f"booked with auto_evidence=True instead."
            )
        assert min_fabric_accesses >= 0, "fabric access floor must be non-negative"
        assert not (min_fabric_accesses and not fabric_access_label), (
            "min_fabric_accesses needs fabric_access_label naming the traffic"
        )
        # MEASURE the fabric-access count here (see docstring): the observed
        # left-hand side of the scoreboard's floor assert must come from what the
        # DUT completed, never from the same constant as the floor.
        measured_fabric = self.env.scoreboard.axi_accesses_by_bus.get(fabric_bus, 0)
        if auto_evidence and not fabric_access_label:
            # An activity stamp makes no fabric claim; leave the field out of the
            # record rather than printing an unlabelled count beside min=0.
            measured_fabric = 0
        if min_fabric_accesses or fabric_accesses is not None:
            known_buses = sorted(self.env.scoreboard.axi_accesses_by_bus)
            assert fabric_bus in self.env.scoreboard.axi_accesses_by_bus, (
                f"record_protocol_vip({kind.value}, {scenario!r}): "
                f"fabric_bus={fabric_bus!r} completed no AXI access in this run "
                f"(buses seen: {known_buses or 'none'}). A fabric floor cannot be "
                f"checked against a port the scoreboard never observed."
            )
        if fabric_accesses is not None:
            assert measured_fabric == fabric_accesses, (
                f"record_protocol_vip({kind.value}, {scenario!r}): the scenario "
                f"declared {fabric_accesses} {fabric_access_label or 'fabric'} "
                f"access(es) but the scoreboard measured {measured_fabric} "
                f"completed access(es) on {fabric_bus}. `fabric_accesses` is an "
                f"exact expectation checked against the measurement, not the "
                f"observation itself."
            )
        item = SmcProtocolVipItem(f"{kind.value}_{scenario}")
        item.kind = kind
        item.scenario = scenario
        item.proxy = proxy
        item.csr_accesses = csr_accesses
        item.timeouts = timeouts
        item.details = details
        item.expected_bytes = expected_bytes
        item.observed_bytes = observed_bytes
        item.min_csr_accesses = min_csr_accesses
        item.fabric_accesses = measured_fabric
        item.min_fabric_accesses = min_fabric_accesses
        item.fabric_access_label = fabric_access_label
        item.fabric_access_source = f"measured: SmcScoreboard.axi_accesses_by_bus[{fabric_bus!r}]"
        item.auto_evidence = auto_evidence
        await _OneShot(item, "protocol_vip_os").start(self.env.protocol_vip_agent.sequencer)

    async def _bring_up(self) -> None:
        dut = cocotb.top
        self.logger.info("Bringing up SMC clocks and cold reset")
        # Run-scoped probe-liveness ledger. The watcher is passive (reads only)
        # and records which tb_top observability probes this run's DUT actually
        # drove to 1; SmcScoreboard consults it to decide whether an idle-zero
        # leg is a real compare or an OBSERVED-ONLY diagnostic
        # ([NEGATIVE-NEEDS-POSITIVE-CONTROL]). It exits as soon as every watched
        # probe has been credited.
        reset_probe_ledger()
        dut.powergood_i.value = 0
        dut.rst_cold_ni.value = 0
        if hasattr(dut, "tb_i2c0_scl_ext_low"):
            dut.tb_i2c0_scl_ext_low.value = 0
        if hasattr(dut, "tb_i2c0_sda_ext_low"):
            dut.tb_i2c0_sda_ext_low.value = 0
        if hasattr(dut, "tb_i3c0_scl_ext_low"):
            dut.tb_i3c0_scl_ext_low.value = 0
        if hasattr(dut, "tb_i3c0_sda_ext_low"):
            dut.tb_i3c0_sda_ext_low.value = 0
        # DFT test_en defaults deasserted (functional mode).
        if hasattr(dut, "tb_test_en_i"):
            dut.tb_test_en_i.value = 0
        for name in (
            "tb_zeroer_state_inject_en",
            "tb_efuse_program_state_inject_en",
            "tb_efuse_read_state_inject_en",
        ):
            if hasattr(dut, name):
                getattr(dut, name).value = 0
        for name in (
            "tb_zeroer_state_inject",
            "tb_efuse_program_state_inject",
            "tb_efuse_read_state_inject",
            "tb_efuse_read_error_inject",
        ):
            if hasattr(dut, name):
                getattr(dut, name).value = 0
        if hasattr(dut, "tb_cpu_jtag_tck"):
            dut.tb_cpu_jtag_tck.value = 0
            dut.tb_cpu_jtag_tms.value = 1
            dut.tb_cpu_jtag_tdi.value = 0
            dut.tb_cpu_jtag_reset.value = 1
        if hasattr(dut, "tb_sep_mailbox_interrupts"):
            dut.tb_sep_mailbox_interrupts.value = 0
        if hasattr(dut, "tb_gpio_ext_drive_en"):
            dut.tb_gpio_ext_drive_en.value = 0
            dut.tb_gpio_ext_drive_value.value = 0
        if hasattr(dut, "tb_boot_stall_jtag_ovrd_i"):
            dut.tb_boot_stall_jtag_ovrd_i.value = 0
            dut.tb_boot_stall_jtag_val_i.value = 0
        if hasattr(dut, "tb_sep_wdt_reset_n"):
            dut.tb_sep_wdt_reset_n.value = 1
        if hasattr(dut, "tb_ndmreset_request"):
            dut.tb_ndmreset_request.value = 0
        if hasattr(dut, "tb_cfg_flr_pf_active"):
            dut.tb_cfg_flr_pf_active.value = 0
        if hasattr(dut, "tb_temp_interrupt_i"):
            dut.tb_temp_interrupt_i.value = 0
        if hasattr(dut, "tb_ext_interrupt_0_i"):
            dut.tb_ext_interrupt_0_i.value = 0
        if hasattr(dut, "tb_captured_straps"):
            dut.tb_captured_straps.value = 0
        if hasattr(dut, "tb_ss_reset_complete"):
            dut.tb_ss_reset_complete.value = 0xFFFFFFFF
        if hasattr(dut, "tb_jtag_reset_ctrl"):
            dut.tb_jtag_reset_ctrl.value = 0
        if hasattr(dut, "tb_sep_axi_r_hold"):
            dut.tb_sep_axi_r_hold.value = 0
        if hasattr(dut, "tb_sys_axi_r_hold"):
            dut.tb_sys_axi_r_hold.value = 0
        if hasattr(dut, "tb_output_axi_resp_hold"):
            dut.tb_output_axi_resp_hold.value = 0
        if hasattr(dut, "tb_mem_repair_abort"):
            dut.tb_mem_repair_abort.value = 0
        if hasattr(dut, "tb_mbist_abort"):
            dut.tb_mbist_abort.value = 0
        if hasattr(dut, "tb_uart0_rx_ext_drive"):
            dut.tb_uart0_rx_ext_drive.value = 1  # UART idle-high
        # Product lc_state_i idle = complementary TEST_DEV ({~0, 0} = 0xF0).
        if hasattr(dut, "tb_lc_state"):
            dut.tb_lc_state.value = 0xF0
        # SPI octal pads (U2-1): idle-safe — enable off, CS deasserted, OE/IE
        # negated high (pads not driving). OcahSpiFlash adapter is U2-2.
        if hasattr(dut, "tb_spi_enable"):
            dut.tb_spi_enable.value = 0
            dut.tb_spi_clk.value = 0
            dut.tb_spi_txd.value = 0
            dut.tb_spi_cs_n.value = 1
            dut.tb_spi_cs_oe_n.value = 1
            dut.tb_spi_cs_ie_n.value = 1
            dut.tb_spi_clk_ie_n.value = 1
            dut.tb_spi_clk_oe_n.value = 1
            dut.tb_spi_dqs_ie_n.value = 1
            dut.tb_spi_dqs_oe_n.value = 1
            dut.tb_spi_dq_ie_n.value = 0xFF
            dut.tb_spi_dq_oe_n.value = 0xFF
            if hasattr(dut, "tb_spi_miso_ext"):
                dut.tb_spi_miso_ext.value = 0
        # Telemetry ATB receiver 0 (U4-6): idle quiet, AFREADY high.
        if hasattr(dut, "tb_telemetry0_atvalid"):
            dut.tb_telemetry0_atdata.value = 0
            dut.tb_telemetry0_atid.value = 0
            dut.tb_telemetry0_atvalid.value = 0
            dut.tb_telemetry0_afready.value = 1
        # AVSBus sdata (pad 51): idle-high (pull-up / no ACK).
        if hasattr(dut, "tb_avs_sdata_ext"):
            dut.tb_avs_sdata_ext.value = 1
        # OCTS dual-chiplet: default PRIMARY; secondary pad inject idle-low.
        if hasattr(dut, "tb_chiplet_is_primary"):
            dut.tb_chiplet_is_primary.value = 1
        if hasattr(dut, "tb_octs_sync_load_ext"):
            dut.tb_octs_sync_load_ext.value = 0
        if hasattr(dut, "tb_octs_cnt_credit_ext"):
            dut.tb_octs_cnt_credit_ext.value = 0
        # Cool reset starts deasserted (released) so the cool-domain logic
        # does not block the cold-reset bring-up. Tests can drive it low via
        # the reset agent COOL_RST_LO op.
        dut.rst_cool_ni.value = 1
        cocotb.start_soon(watch_probe_liveness(dut))
        # Firmware virtual console (scratch 2); decoded lines go to the log as
        # they complete.
        self.virt_console = VirtConsole(dut.tb_cpu_scratch2, "smc-fw")
        cocotb.start_soon(self.virt_console.run())
        # The SYS_OUT responder exists before the first clock edge so the
        # boundary's READY signals are driven from time zero. It follows the
        # SMC primary reset: a cool reset drops the outstanding responses
        # instead of returning them into the reset CPU cluster.
        self.cfg.sys_out_mem = OcahAxiSlaveAgent(
            SYS_OUT_AXI_GEOMETRY.bus(dut.u_output_axi_if),
            dut.clk_smc_i,
            dut.rst_primary_smc_clk_no,
            reset_active_level=False,
            size=SYS_OUT_MEM_SIZE,
            name="smc_sys_out",
        ).sequence
        cocotb.start_soon(Clock(dut.clk_ref_i, self.cfg.ref_clk_period_ns, units="ns").start())
        cocotb.start_soon(Clock(dut.clk_smc_i, self.cfg.smc_clk_period_ns, units="ns").start())
        cocotb.start_soon(
            Clock(dut.clk_periph_i, self.cfg.periph_clk_period_ns, units="ns").start()
        )

        await ClockCycles(dut.clk_ref_i, 10)
        self.logger.info("Asserting powergood")
        dut.powergood_i.value = 1
        await ClockCycles(dut.clk_ref_i, 10)
        self.logger.info("Releasing cold reset")
        dut.rst_cold_ni.value = 1
        # Completion gate = the observed reset chain releasing, not a delay.
        released_at = await self._await_cold_reset_release()
        # Post-release quiet margin: the handshake above is the gate, this is
        # the remainder of the same window, and downstream tests' timing depends
        # on its length. Tests needing the warm/fuse domain wait on it explicitly
        # via smc_base_test_seq.wait_fuse_sense_done.
        remaining = self.cfg.post_reset_settle_cycles - released_at
        if remaining > 0:
            await ClockCycles(dut.clk_ref_i, remaining)
        self.cfg.reset_done.set()

    # Top-level reset observables whose release ends cold bring-up.
    _COLD_RELEASE_PROBES = (
        "powergood_stable_o",
        "rst_cold_stable_ref_clk_no",
        "rst_primary_ref_clk_no",
        "rst_primary_smc_clk_no",
    )

    async def _await_cold_reset_release(self) -> int:
        """Bounded wait until the cold reset chain is observed released.

        Bring-up is not gated by a bare
        ``ClockCycles(clk_ref_i, post_reset_settle_cycles)``: a magic count
        passes on luck of sim timing and silently lets every later SAMPLE run
        against a still-asserted reset chain ([NO-BLIND-DELAY-SYNC]). Expiry
        here is a testcase failure with last-state diagnostics
        ([TIMEOUT-MUST-FAIL]). Returns the number of ``clk_ref_i`` cycles waited.
        """
        dut = cocotb.top
        bound = max(self.cfg.post_reset_settle_cycles, 2000)
        for cycle in range(bound + 1):
            vals = [getattr(dut, p).value for p in self._COLD_RELEASE_PROBES]
            if all(v.is_resolvable and int(v) == 1 for v in vals):
                self.logger.info(
                    "Cold reset chain released %d clk_ref_i cycles after rst_cold_ni=1 (%s)",
                    cycle,
                    ", ".join(f"{p}={int(v)}" for p, v in zip(self._COLD_RELEASE_PROBES, vals)),
                )
                return cycle
            await ClockCycles(dut.clk_ref_i, 1)
        last = ", ".join(f"{p}={getattr(dut, p).value}" for p in self._COLD_RELEASE_PROBES)
        raise AssertionError(
            f"cold reset chain not released within {bound} clk_ref_i cycles of "
            f"rst_cold_ni=1; last observed {last}"
        )

    async def run_scenario(self) -> None:
        raise NotImplementedError

    async def run_probe_positive_controls(self) -> None:
        """Run this test's declared probe positive controls (see class doc).

        Each control drives real frontdoor stimulus, requires the probe to be
        observed at 1 inside a bounded window (expiry = failure), restores idle
        and requires the probe back at 0. It runs before ``run_scenario`` so
        every idle-zero leg the scenario books already has its liveness credit.
        The controls dispatch no agent SAMPLE items, so per-type scoreboard
        counter gates in the scenarios are unaffected.
        """
        if not self.probe_positive_controls:
            return
        from seq_lib.smc_probe_positive_control import SmcProbePositiveControlSeq

        seq = SmcProbePositiveControlSeq("probe_positive_control_seq", self.probe_positive_controls)
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)

    async def run_phase(self) -> None:
        self.raise_objection()
        # First line of every kept log's run phase: what RTL this run simulated
        # ([BUILD-MODEL-IDENTITY]). Raises rather than logging a placeholder.
        log_build_model_identity()
        await self._bring_up()
        try:
            await self.run_probe_positive_controls()
            await self.run_scenario()
        except Exception:  # noqa: BLE001 -- re-raised once the CPU state is in the log
            self.virt_console.flush()
            self.env.cpu_trace_mon.dump_diagnostics(logging.ERROR)
            raise
        test_name = type(self).__name__
        # Prefer the per-test class attribute; fall back to the name map.
        kind = self.protocol_vip_kind or _PROTOCOL_VIP_TESTS.get(test_name)
        if getattr(self, "auto_protocol_vip", True) and kind is not None:
            # Auto stamp, NOT evidence of protocol behaviour. It carries only
            # measured numbers (the SYS-AXI transaction count the scoreboard
            # observed), declares `auto_evidence=True` so the scoreboard books
            # it as an activity stamp in its own coverage bin rather than a
            # check, and reports timeouts as "not measured". A stamp with a
            # canned count could not fail ([NO-ALWAYS-PASS-CHECKER]).
            #
            # A scenario that wants a real protocol VIP record sets
            # `auto_protocol_vip = False` and calls record_protocol_vip() with
            # its own measured counts plus `min_csr_accesses=<stimulus floor>`.
            observed_sys_axi = self.env.scoreboard.sys_axi_checks_seen
            await self.record_protocol_vip(
                kind,
                test_name,
                csr_accesses=observed_sys_axi,
                timeouts=None,
                auto_evidence=True,
                details=(
                    f"auto activity stamp: {observed_sys_axi} SYS-AXI "
                    "transactions observed by the scoreboard during this "
                    "scenario; no protocol-level assertion performed here"
                ),
            )
        self._finalize_evidence()
        self.drop_objection()

    def _finalize_evidence(self) -> None:
        """Report the evidence this run produced, and grade it.

        Runs only after run_scenario() returns normally. A test that already
        failed raised, and this must not turn that into a different complaint.

        ``own`` excludes the lines smc_base_test emits itself (the model
        identity line and the probe positive controls), so the gate grades what
        the leaf proved rather than what bring-up logged.
        """
        recorder = getattr(self, "_evidence", None)
        seen = sorted(recorder.seen) if recorder else []
        own = [check_id for check_id in seen if not _EvidenceRecorder.is_base(check_id)]
        required = tuple(self.required_evidence)
        missing = [check_id for check_id in required if check_id not in seen]
        test_name = type(self).__name__
        extra = set(_EvidenceRecorder.NO_OWN_EVIDENCE) - _EvidenceRecorder.NO_OWN_EVIDENCE_CEILING
        if extra:
            raise AssertionError(
                "NO_OWN_EVIDENCE grew: "
                + ", ".join(sorted(extra))
                + " -- this list may only shrink"
            )
        review_date = date.fromisoformat(_EvidenceRecorder.NO_OWN_EVIDENCE_REVIEW_DATE)
        if _EvidenceRecorder.NO_OWN_EVIDENCE and datetime.now(tz=timezone.utc).date() > review_date:
            self.logger.warning(
                "NO_OWN_EVIDENCE review date %s has passed with %d leaves still exempt; "
                "re-read each entry, then close it or move the date",
                review_date,
                len(_EvidenceRecorder.NO_OWN_EVIDENCE),
            )

        self.logger.info(
            "EVIDENCE_SUMMARY test=%s observed=%d own=%d required=%d missing=%d ids=%s",
            test_name,
            len(seen),
            len(own),
            len(required),
            len(missing),
            ",".join(seen) or "-",
        )

        problems: list[str] = []
        if not own and test_name not in _EvidenceRecorder.NO_OWN_EVIDENCE:
            problems.append(
                "no CHK-* line of its own -- a run that grades nothing cannot be a "
                "pass. If this leaf's checks live in its sequence, log them there; "
                "if it genuinely checks nothing, that is the finding"
            )
        if self.min_evidence and len(own) < self.min_evidence:
            problems.append(
                f"{len(own)} distinct CHK-* line(s) of its own, "
                f"expected at least {self.min_evidence}"
            )
        if missing:
            problems.append("never emitted: " + ", ".join(missing))
        if problems:
            raise AssertionError(
                f"EVIDENCE FAIL {test_name}: "
                + "; ".join(problems)
                + " -- the run exited cleanly without grading what it claims to grade"
            )
