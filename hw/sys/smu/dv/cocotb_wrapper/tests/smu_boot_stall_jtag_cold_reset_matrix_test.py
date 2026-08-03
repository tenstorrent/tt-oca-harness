# SPDX-License-Identifier: Apache-2.0
"""Wrapper shim: load bare `smu_boot_stall_jtag_cold_reset_matrix_test` against real RTL; re-export @pyuvm.test."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_BARE_ROOT = Path(__file__).resolve().parents[2] / "cocotb"
_BARE_TESTS = _BARE_ROOT / "tests"
# Shim-local only: do not put bare env/seq_lib on the global wrapper PYTHONPATH.
for _p in (_BARE_TESTS, _BARE_ROOT, _BARE_ROOT / "seq_lib", _BARE_ROOT / "env"):
    _s = str(_p)
    if _s in sys.path:
        sys.path.remove(_s)
    sys.path.insert(0, _s)

# Drop any already-imported wrapper packages that share bare names.
for _name in list(sys.modules):
    if _name == "smu_base_test" or _name == "env" or _name.startswith("env.") \
            or _name == "seq_lib" or _name.startswith("seq_lib."):
        sys.modules.pop(_name, None)

_BARE_FILE = _BARE_TESTS / "smu_boot_stall_jtag_cold_reset_matrix_test.py"
_spec = importlib.util.spec_from_file_location("bare_smu_boot_stall_jtag_cold_reset_matrix_test", _BARE_FILE)
if _spec is None or _spec.loader is None:
    raise ImportError(f"cannot load bare test {_BARE_FILE}")
_mod = importlib.util.module_from_spec(_spec)
sys.modules["bare_smu_boot_stall_jtag_cold_reset_matrix_test"] = _mod
_spec.loader.exec_module(_mod)

# @pyuvm.test() registers cocotb Test as __ClassName on the bare module.
_g = globals()
_g["smu_boot_stall_jtag_cold_reset_matrix_test"] = getattr(_mod, "smu_boot_stall_jtag_cold_reset_matrix_test")
_pyuvm_test_attr = "__smu_boot_stall_jtag_cold_reset_matrix_test"
if not hasattr(_mod, _pyuvm_test_attr):
    raise ImportError(
        f"bare_smu_boot_stall_jtag_cold_reset_matrix_test missing {_pyuvm_test_attr} (pyuvm/@cocotb.test registration failed)"
    )
_g[_pyuvm_test_attr] = getattr(_mod, _pyuvm_test_attr)
