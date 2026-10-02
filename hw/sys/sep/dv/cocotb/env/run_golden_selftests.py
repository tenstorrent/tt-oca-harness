# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Run every SEP and entropy-source DV model self-test.

Each ``env/sep_*_golden.py`` carries a standalone self-test (a KAT / NIST / FIPS /
RFC vector check, or hand-computed reference vectors) in its ``__main__`` block.
``env/sep_efuse_default_shadow.py`` follows the same pattern: its ``__main__``
block fails when the committed expected-shadow file differs from a fresh copy.
Those guard against transcription errors in the golden, but ``__main__`` blocks
only run when the file is executed directly -- so without a driver they are never
enforced in CI. This runner executes each golden as a subprocess and asserts a
clean exit, so a broken golden fails a single fast CI step instead of silently
shipping and corrupting a downstream KAT compare.

Usage (no simulator needed):
    python3 cocotb/env/run_golden_selftests.py
Exit code 0 = all goldens self-tested clean; nonzero = at least one failed.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_MODELS = _HERE.parents[5] / "hw" / "ip" / "entropy_source" / "dv" / "cocotb" / "models"

# The goldens with an executable self-test (KAT/NIST/FIPS/RFC or hand vectors).
_GOLDENS = (
    _HERE / "sep_aes_golden.py",
    _HERE / "sep_hmac_golden.py",
    _HERE / "sep_ctr_drbg_golden.py",
    _MODELS / "entropy_conditioning_model.py",
    _MODELS / "entropy_decorrelator_model.py",
    _MODELS / "entropy_noise_model.py",
    _HERE / "sep_entropy_golden.py",
    _HERE / "sep_lcc_golden.py",
    _HERE / "sep_crc_golden.py",
    _HERE / "sep_oca_console.py",
    _HERE.parent / "tests" / "rom_fw" / "sep_measurement_golden.py",
    # Freshness of the committed expected shadow the SV-UVM sense test loads.
    _HERE / "sep_efuse_default_shadow.py",
)


def main() -> int:
    failures = []
    python_path = [str(_MODELS.parent), str(_HERE)]
    if current := os.environ.get("PYTHONPATH"):
        python_path.append(current)
    child_env = {**os.environ, "PYTHONPATH": ":".join(python_path)}
    for path in _GOLDENS:
        name = path.name
        if not path.is_file():
            print(f"[MISS] {name}: file not found", file=sys.stderr)
            failures.append(name)
            continue
        proc = subprocess.run(
            [sys.executable, str(path)],
            capture_output=True,
            text=True,
            cwd=str(_HERE),
            env=child_env,
        )
        status = "PASS" if proc.returncode == 0 else "FAIL"
        print(f"[{status}] {name}")
        if proc.returncode != 0:
            sys.stderr.write(proc.stdout)
            sys.stderr.write(proc.stderr)
            failures.append(name)

    if failures:
        print(
            f"\n{len(failures)} golden self-test(s) FAILED: {', '.join(failures)}", file=sys.stderr
        )
        return 1
    print(f"\nAll {len(_GOLDENS)} golden self-tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
