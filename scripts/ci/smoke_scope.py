#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Decide which Verilator smoke checks a pull request's diff reaches.

The sim workflow runs this from the repository root with one ``--view`` per
smoke check:

    python3 scripts/ci/smoke_scope.py --github-output --view dtp:cocotb --view dtp:uvm

A view is one DUT under one framework, as ``run_dv.py --dut --framework``. Its
inputs come from the runner: the compile filelists ``run_dv.py --stage flist``
writes for each build target, the commands a ``--dry-run`` of the ``smoke``
group prints, and the repository paths the TOML values of its DV tree name.
A view is skipped only when every changed path is provably outside those
inputs, which holds for:

* documentation, the runner's unit tests, and a vendored package's
  ``patches/``, which the vendor flow applies before any build;
* a ``.github`` file other than the sim workflow and the dv-run action;
* the UVM library, for a cocotb view;
* an HDL file that no filelist of the view compiles and that lies outside
  its include directories, or for a header, outside every directory holding
  one of its sources;
* for a view whose smoke runs no script (every command is bender, Verilator
  or the built model), a file in a DV tree that is Python, or that lies
  outside the view's own DV tree, outside ``hw/common/dv`` and outside every
  path its TOML values or smoke commands name. Naming another DUT's
  ``*_sim_cfg.toml`` names that DUT's whole DV tree.

A script can build a path to any file, so every non-HDL file in a DV tree
reaches a view whose smoke runs one, and a cocotb view always does. Every
other path reaches every view, and so does a view whose inputs cannot be
derived. ``--github-output`` prints ``smoke_skip=<JSON list of views>``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "dv"))

from diff_class import UNCLASSIFIED, changed_files, is_docs_path  # noqa: E402
from runlib.config import load_sim_cfg  # noqa: E402
from runlib.duts import resolve_dut  # noqa: E402
from runlib.models import ConfigError  # noqa: E402
from runlib.site import load_site_layer  # noqa: E402

RUN_DV = REPO_ROOT / "tools" / "dv" / "run_dv.py"
RUN_DV_ENV = {**os.environ, "OCAH_DV_SKIP_UV": "1"}
TOOL = "verilator"
SMOKE_GROUP = "smoke"

HDL_SUFFIXES = frozenset({".sv", ".svh", ".v", ".vh"})
# A header resolves against the directory of the file that includes it, so it needs
# no filelist entry or include directory to be compiled.
HEADER_SUFFIXES = frozenset({".svh", ".vh"})
UVM_LIBRARY = "vendor/accellera/uvm-core"
SHARED_DV_ROOT = "hw/common/dv"
RUNNER_INPUT_DIRS = ("tools/dv", "scripts/ci", ".github/actions/dv-run", "hw/common/dv/configs")
RUNNER_INPUT_FILES = frozenset(
    {".github/workflows/sim.yml", "Bender.yml", "Bender.lock", "pyproject.toml", "uv.lock"}
)
RUNNER_UNIT_TESTS = "tools/dv/tests"
SCRIPT_RUNNERS = frozenset({"bash", "env", "make", "sh"})
# A repository path inside a command line or a TOML string; an absolute path matches
# from its first repository-level segment.
REPO_PATH_RE = re.compile(r"(?<![\w.-])((?:hw|vendor|tools|scripts|flows)/[\w./-]*[\w-])")


@dataclass(frozen=True)
class ViewInputs:
    """What one view's smoke check reads, as repository-relative POSIX paths."""

    view: str
    framework: str
    root: str
    sources: frozenset[str]
    incdirs: frozenset[str]
    named: frozenset[str]
    runs_scripts: bool

    @property
    def source_dirs(self) -> frozenset[str]:
        return frozenset(str(PurePosixPath(source).parent) for source in self.sources)


@dataclass(frozen=True)
class Decision:
    """Whether a view's smoke check runs, and the first changed path that makes it run."""

    view: str
    run: bool
    path: str
    reason: str


def is_under(path: str, prefix: str) -> bool:
    """Return True when *path* is *prefix* or lies beneath it."""
    prefix = prefix.rstrip("/")
    return path == prefix or path.startswith(prefix + "/")


def is_dv_tree_path(path: str) -> bool:
    """Return True for a path inside a ``dv`` directory under ``hw/``."""
    parts = path.split("/")
    return parts[0] == "hw" and "dv" in parts[1:-1]


def repo_relatives(paths: Iterable[str]) -> set[str]:
    """Return the repository-relative forms of the *paths* that lie inside the repository."""
    relatives: set[str] = set()
    for path in filter(None, paths):
        try:
            relatives.add((REPO_ROOT / path).resolve().relative_to(REPO_ROOT).as_posix())
        except ValueError:
            continue
    return relatives


def named_paths(text: str) -> set[str]:
    """Return the repository paths *text* names."""
    return set(REPO_PATH_RE.findall(text))


def parse_filelist(text: str) -> tuple[set[str], set[str], list[Path]]:
    """Return the sources, include directories and included filelists one filelist names."""
    sources: set[str] = set()
    incdirs: set[str] = set()
    included: list[Path] = []
    for entry in (line.strip() for line in text.splitlines()):
        if entry.startswith("+incdir+"):
            incdirs |= repo_relatives(entry[len("+incdir+") :].split("+"))
        elif entry.startswith(("-f ", "-F ")):
            included.append(REPO_ROOT / entry[3:].strip())
        elif entry and not entry.startswith(("+", "-", "//", "#")):
            sources |= repo_relatives([entry])
    return sources, incdirs, included


def filelist_entries(filelists: Iterable[Path]) -> tuple[set[str], set[str]]:
    """Return the sources and include directories *filelists* reach through ``-f``/``-F``."""
    sources: set[str] = set()
    incdirs: set[str] = set()
    pending = list(filelists)
    seen: set[Path] = set()
    while pending:
        current = pending.pop()
        if current in seen or not current.is_file():
            continue
        seen.add(current)
        text = current.read_text(encoding="utf-8", errors="replace")
        found_sources, found_incdirs, included = parse_filelist(text)
        sources |= found_sources
        incdirs |= found_incdirs
        pending.extend(included)
    return sources, incdirs


def is_runner_input(path: str) -> bool:
    """Return True for a path every smoke check reads through the runner or its CI job."""
    return path in RUNNER_INPUT_FILES or any(is_under(path, d) for d in RUNNER_INPUT_DIRS)


def is_never_input(path: str) -> bool:
    """Return True for a path no smoke check reads."""
    parts = path.split("/")
    return (
        is_docs_path(path)
        or is_under(path, RUNNER_UNIT_TESTS)
        or (path.startswith(".github/") and not is_runner_input(path))
        or (parts[0] == "vendor" and len(parts) > 4 and parts[3] == "patches")
    )


def shared_reason(path: str) -> str | None:
    """Return why every view reads *path*, or None when the answer depends on the view."""
    if path == UNCLASSIFIED:
        return "the diff could not be listed"
    if is_never_input(path):
        return None
    if is_runner_input(path):
        return "runner or CI input"
    if (
        is_under(path, UVM_LIBRARY)
        or PurePosixPath(path).suffix in HDL_SUFFIXES
        or is_dv_tree_path(path)
    ):
        return None
    return "outside the DV trees"


def hdl_reason(inputs: ViewInputs, path: str) -> str | None:
    """Return why the view's compile reaches the HDL file *path*, or None."""
    if path in inputs.sources:
        return "compiled source"
    for incdir in sorted(inputs.incdirs):
        if is_under(path, incdir):
            return f"under include directory {incdir}"
    if (
        PurePosixPath(path).suffix in HEADER_SUFFIXES
        and str(PurePosixPath(path).parent) in inputs.source_dirs
    ):
        return "header beside a compiled source"
    return None


def dv_tree_reason(inputs: ViewInputs, path: str) -> str | None:
    """Return why the view reads the non-HDL DV-tree file *path*, or None."""
    if inputs.runs_scripts:
        return "the view's smoke runs a script, which can read any DV tree"
    if path.endswith(".py"):
        return None
    if is_under(path, inputs.root):
        return f"in the view's DV tree {inputs.root}"
    if is_under(path, SHARED_DV_ROOT):
        return f"in the shared DV tree {SHARED_DV_ROOT}"
    for named in sorted(inputs.named):
        if is_under(path, named):
            return f"under {named}, which the view names"
        if named.endswith("_sim_cfg.toml") and is_under(path, str(PurePosixPath(named).parent)):
            return f"in the DV tree of {named}, which the view names"
    return None


def view_reason(inputs: ViewInputs, path: str) -> str | None:
    """Return why *path* is an input of the view, or None when it provably is not."""
    reason = shared_reason(path)
    if reason or is_never_input(path):
        return reason
    if is_under(path, UVM_LIBRARY):
        return "UVM library" if inputs.framework == "uvm" else None
    if PurePosixPath(path).suffix in HDL_SUFFIXES:
        return hdl_reason(inputs, path)
    return dv_tree_reason(inputs, path)


def decide(inputs: ViewInputs, paths: Sequence[str]) -> Decision:
    """Return the decision for one view over the changed *paths*."""
    for path in paths:
        reason = view_reason(inputs, path)
        if reason:
            return Decision(inputs.view, True, path, reason)
    return Decision(inputs.view, False, "", "no changed path is an input")


def run_dv(args: Sequence[str]) -> str:
    """Return the standard output of one ``run_dv.py`` call made outside the uv environment."""
    proc = subprocess.run(
        [sys.executable, str(RUN_DV), *args],
        cwd=REPO_ROOT,
        env=RUN_DV_ENV,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode:
        lines = (proc.stdout + proc.stderr).strip().splitlines()
        raise ConfigError(f"run_dv.py {' '.join(args)}: {lines[-1] if lines else 'failed'}")
    return proc.stdout


def written_filelists(output: str) -> list[Path]:
    """Return the compile filelists a ``run_dv.py --dry-run`` reports it would write."""
    return [
        Path(line[len("WRITE: ") :].strip())
        for line in output.splitlines()
        if line.startswith("WRITE: ") and line.rstrip().endswith(".f")
    ]


def command_lines(output: str) -> list[str]:
    """Return the commands a ``run_dv.py --dry-run`` prints."""
    return [
        line[len("CMD  :") :].strip() for line in output.splitlines() if line.startswith("CMD  :")
    ]


def runs_script(command: str) -> bool:
    """Return True when *command* runs a script rather than bender, Verilator or a model."""
    words = command.split()
    name = PurePosixPath(words[0]).name if words else ""
    return name.startswith("python") or name in SCRIPT_RUNNERS or name.endswith((".py", ".sh"))


def command_paths(commands: Iterable[str], run_dir: Path) -> set[str]:
    """Return the repository paths *commands* name, leaving out arguments inside *run_dir*."""
    paths: set[str] = set()
    for command in commands:
        paths |= named_paths(" ".join(w for w in command.split() if str(run_dir) not in w))
    return paths


def toml_strings(value: object) -> Iterator[str]:
    """Yield every string inside a parsed TOML value."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from toml_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from toml_strings(item)


def config_paths(root: str) -> set[str]:
    """Return the repository paths the TOML values under the DV tree *root* name.

    A file that does not parse contributes every path its text names, comments included.
    """
    paths: set[str] = set()
    for toml in sorted((REPO_ROOT / root).rglob("*.toml")):
        if "build" in toml.relative_to(REPO_ROOT).parts:
            continue
        text = toml.read_text(encoding="utf-8", errors="replace")
        try:
            paths |= named_paths("\n".join(toml_strings(tomllib.loads(text))))
        except tomllib.TOMLDecodeError:
            paths |= named_paths(text)
    return paths


def target_filelist_entries(
    base: Sequence[str], target: str, scratch: Path
) -> tuple[set[str], set[str]]:
    """Generate one build target's filelists and return the sources and include directories."""
    flist = [*base, "--stage", "flist", *(["--target", target] if target else [])]
    planned = run_dv([*flist, "--dry-run", "--run-dir", str(scratch / f"plan-{target}")])
    run_dv([*flist, "--run-dir", str(scratch / f"flist-{target}")])
    return filelist_entries(written_filelists(planned))


def view_inputs(view: str) -> ViewInputs:
    """Derive one view's inputs from the runner; raises ConfigError when it cannot."""
    dut, framework = view.split(":")
    flow = resolve_dut(REPO_ROOT, dut, framework=framework, site=load_site_layer(REPO_ROOT))
    targets = sorted(load_sim_cfg(flow, REPO_ROOT).get("targets") or {}) or [""]
    base = ["--dut", dut, "--framework", framework, "--tool", TOOL]
    sources: set[str] = set()
    incdirs: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="smoke_scope_") as tmp:
        scratch = Path(tmp)
        smoke = run_dv([*base, "--items", SMOKE_GROUP, "--dry-run", "--run-dir", str(scratch)])
        for target in targets:
            found_sources, found_incdirs = target_filelist_entries(base, target, scratch)
            sources |= found_sources
            incdirs |= found_incdirs
    commands = command_lines(smoke)
    return ViewInputs(
        view=view,
        framework=framework,
        root=flow.root,
        sources=frozenset(sources),
        incdirs=frozenset(incdirs),
        named=frozenset(command_paths(commands, scratch) | config_paths(flow.root)),
        runs_scripts=any(runs_script(command) for command in commands),
    )


def decide_views(views: Iterable[str], paths: Sequence[str]) -> list[Decision]:
    """Return one decision per view; inputs are derived only when the paths need them."""
    views = list(views)
    for path in paths:
        reason = shared_reason(path)
        if reason:
            return [Decision(view, True, path, reason) for view in views]
    decisions = []
    for view in views:
        try:
            decisions.append(decide(view_inputs(view), paths))
        except (ConfigError, OSError) as exc:
            decisions.append(Decision(view, True, "", f"inputs unavailable: {exc}"))
    return decisions


def summary_table(decisions: Sequence[Decision]) -> str:
    """Return the decisions as a Markdown table."""
    rows = ["| Smoke check | Runs | First changed input | Why |", "|---|---|---|---|"]
    for decision in decisions:
        path = f"`{decision.path}`" if decision.path else ""
        runs = "yes" if decision.run else "no"
        rows.append(f"| `{decision.view}` | {runs} | {path} | {decision.reason} |")
    return "\n".join(rows) + "\n"


def self_test() -> None:
    dtp_uvm = ViewInputs(
        view="dtp:uvm",
        framework="uvm",
        root="hw/sys/dtp/dv",
        sources=frozenset({"hw/sys/dtp/rtl/dtp.sv", "hw/sys/dtp/dv/tb/tb_top.sv"}),
        incdirs=frozenset({"hw/sys/dtp/dv/uvm/env"}),
        named=frozenset({"hw/sys/sep/dv/sep_sim_cfg.toml", "hw/sys/smc/dv/assets"}),
        runs_scripts=False,
    )
    dtp_cocotb = ViewInputs(
        view="dtp:cocotb",
        framework="cocotb",
        root="hw/sys/dtp/dv",
        sources=frozenset({"hw/sys/dtp/rtl/dtp.sv", "hw/sys/dtp/dv/tb/tb_top.sv"}),
        incdirs=frozenset(),
        named=frozenset(),
        runs_scripts=True,
    )
    expectations = {
        UNCLASSIFIED: (True, True),
        "tools/dv/run_dv.py": (True, True),
        "tools/dv/doc/run-dv.adoc": (False, False),
        "tools/dv/tests/test_config.py": (False, False),
        "vendor/lowRISC/opentitan/patches/0013-prim.patch": (False, False),
        ".github/actions/dv-run/action.yml": (True, True),
        ".github/workflows/sim.yml": (True, True),
        ".github/workflows/regress.yml": (False, False),
        "hw/common/dv/configs/profiles/native.toml": (True, True),
        "hw/ip/uart/regs/uart.rdl": (True, True),
        "README.md": (False, False),
        "hw/sys/dtp/dv/docs/DTP_VPLAN.adoc": (False, False),
        "vendor/accellera/uvm-core/upstream/src/uvm_pkg.sv": (True, False),
        "hw/sys/dtp/rtl/dtp.sv": (True, True),
        "hw/sys/dtp/rtl/dtp_pkg.svh": (True, True),
        "hw/sys/dtp/rtl/dtp_unlisted.sv": (False, False),
        "hw/sys/dtp/dv/uvm/env/dtp_env.svh": (True, False),
        "hw/sys/dtp/dv/uvm/tests/dtp_new_test.svh": (False, False),
        "hw/sys/smc/rtl/smc.sv": (False, False),
        "hw/sys/dtp/dv/testlists/jtag.toml": (True, True),
        "hw/sys/dtp/dv/cocotb/tests/dtp_jtag_test.py": (False, True),
        "hw/sys/dtp/dv/fw/build_firmware.py": (False, True),
        "hw/sys/smc/dv/assets/rom.hex": (True, True),
        "hw/sys/smc/dv/assets/gen_rom.py": (False, True),
        "hw/common/dv/vip/ocah_axi_vip/cocotb/ocah_axi_driver.py": (False, True),
        "hw/common/dv/vip/ocah_axi_vip/uvm/sources.toml": (True, True),
        "hw/sys/sep/dv/testlists/system.toml": (True, True),
        "hw/sys/smc/dv/testlists/register.toml": (False, True),
        "hw/ip/entropy_source/dv/cocotb/esrc_env.py": (False, True),
    }
    for path, (uvm_runs, cocotb_runs) in expectations.items():
        assert bool(view_reason(dtp_uvm, path)) is uvm_runs, (dtp_uvm.view, path)
        assert bool(view_reason(dtp_cocotb, path)) is cocotb_runs, (dtp_cocotb.view, path)

    assert decide(dtp_uvm, ["README.md", "hw/sys/dtp/dv/uvm/env/x.svh"]) == Decision(
        "dtp:uvm",
        True,
        "hw/sys/dtp/dv/uvm/env/x.svh",
        "under include directory hw/sys/dtp/dv/uvm/env",
    )
    assert not decide(dtp_cocotb, ["hw/sys/dtp/dv/uvm/env/x.svh"]).run
    assert all(d.run for d in decide_views(["dtp:uvm", "sep:uvm"], ["tools/dv/run_dv.py"]))

    assert named_paths(
        "CMD  : python3 hw/sys/smu/dv/fw/build_firmware.py --target preloads "
        f'+km_rom_hex={REPO_ROOT}/hw/sys/sep/dv/cocotb/tests/km_rom.parhex KM_FW="hw/sys/sep/x"'
    ) == {
        "hw/sys/smu/dv/fw/build_firmware.py",
        "hw/sys/sep/dv/cocotb/tests/km_rom.parhex",
        "hw/sys/sep/x",
    }
    commands = command_lines(
        "CMD  : bender checkout\nWRITE: /run/a/x.sh\n"
        "CMD  : /run/a/Vtb +rom_hex=hw/sys/x/rom.hex\nCMD  : python3 /run/a/scripts/sim.py\n"
    )
    assert commands == [
        "bender checkout",
        "/run/a/Vtb +rom_hex=hw/sys/x/rom.hex",
        "python3 /run/a/scripts/sim.py",
    ]
    assert command_paths(commands, Path("/run/a")) == {"hw/sys/x/rom.hex"}
    assert [runs_script(command) for command in commands] == [False, False, True]
    for command in ("bash -lc 'make -C x'", "/usr/bin/python3.12 t.py", "env -u A make", "x.sh"):
        assert runs_script(command), command
    assert not runs_script("verilator --binary -f hw/sys/dtp/dv/build/uvm/dtp_uvm_compile.f")
    assert set(toml_strings({"a": ["hw/x", {"b": "y"}], "c": 3})) == {"hw/x", "y"}
    assert written_filelists("WRITE: /r/a/files.f\nWRITE: /r/a/sim.env\nCMD  : x.f\n") == [
        Path("/r/a/files.f")
    ]

    with tempfile.TemporaryDirectory() as tmp:
        nested = Path(tmp) / "bender.f"
        nested.write_text(
            f"+incdir+{REPO_ROOT}/hw/common/defs\n{REPO_ROOT}/hw/sys/dtp/rtl/dtp.sv\n"
        )
        top = Path(tmp) / "compile.f"
        top.write_text(
            f"// comment\n+incdir+hw/sys/dtp/dv/uvm/env\n+define+UVM\n-f {nested}\n"
            "hw/sys/dtp/dv/tb/tb_top.sv\n/outside/repo.sv\n"
        )
        assert filelist_entries([top]) == (
            {"hw/sys/dtp/rtl/dtp.sv", "hw/sys/dtp/dv/tb/tb_top.sv"},
            {"hw/common/defs", "hw/sys/dtp/dv/uvm/env"},
        )

    print("smoke_scope self-test ok")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--view",
        action="append",
        default=[],
        metavar="DUT:FRAMEWORK",
        help="a smoke check to decide, as run_dv.py --dut and --framework (repeatable)",
    )
    parser.add_argument(
        "--paths",
        nargs="+",
        metavar="PATH",
        help="decide for these repository-relative paths instead of the CI event's diff",
    )
    parser.add_argument(
        "--github-output",
        action="store_true",
        help="print smoke_skip=<JSON list of skipped views> for GITHUB_OUTPUT",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        metavar="FILE",
        help="append the decisions to FILE as a Markdown table",
    )
    parser.add_argument("--self-test", action="store_true", help="run the built-in checks")
    args = parser.parse_args(argv)

    if args.self_test:
        self_test()
        return 0
    if not args.view:
        parser.error("at least one --view is required")
    for view in args.view:
        if not re.fullmatch(r"[\w-]+:[\w-]+", view):
            parser.error(f"--view {view!r} is not DUT:FRAMEWORK")

    paths = args.paths or changed_files()[0] or [UNCLASSIFIED]
    decisions = decide_views(args.view, paths)
    for decision in decisions:
        verdict = f"run ({decision.path}: {decision.reason})" if decision.run else "skip"
        print(f"smoke_scope: {decision.view}: {verdict}", file=sys.stderr)
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as handle:
            handle.write("### Smoke checks this diff reaches\n\n" + summary_table(decisions))

    skipped = [decision.view for decision in decisions if not decision.run]
    if args.github_output:
        print(f"smoke_skip={json.dumps(skipped)}")
    else:
        print(summary_table(decisions), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
