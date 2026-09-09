# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Interactive (non-pytest) entry point: ``python -m sepvp.cli``.

Build a :class:`~sepvp.config.SimConfig` from friendly flags, launch sep-vp, stream its
decoded stdout, and exit non-zero on a production ERROR (or, with ``--until``, on failing
to reach a status before the timeout). sep-vp never self-terminates, so without ``--until``
the run streams until ``--timeout`` and then stops cleanly.
"""

import argparse
import logging
import sys
from pathlib import Path

import pexpect

from sepvp.config import SimConfig
from sepvp.harness import SEP_STATUS_ERROR_RE, HarnessError
from sepvp.sepvp_harness import SepVpHarness

# VP-decoded firmware pass/fail markers (SEP firmware-test mailbox magic).
FW_PASS = r"\[VP\] SIMULATION OF THE TEST PASSED"
FW_FAIL = r"\[VP\] SIMULATION OF THE TEST FAILED"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m sepvp.cli",
        description="Run a SEP firmware ELF on the sep-vp virtual platform.",
    )
    p.add_argument("--bin", required=True, metavar="ELF", help="firmware ELF to run")
    p.add_argument("--name", help="run name (working dir under logs/sepvp/); default from ELF")
    p.add_argument("--spi", metavar="FLASH.bin", help="prebuilt raw SPI flash image")
    p.add_argument(
        "--otp", metavar="FUSES", help="fuse-map: YAML (VP-native) or RTL eFuse-config .toml"
    )
    # straps
    p.add_argument(
        "--boot",
        choices=["primary", "secondary"],
        default="secondary",
        help="boot mode (primary = SPI boot; secondary = wait for SMC). Default: secondary",
    )
    p.add_argument("--recovery", action="store_true", help="boot_recovery strap (implies primary)")
    p.add_argument(
        "--rotate-update", action="store_true", help="use the rotated (backup) manifest slot"
    )
    p.add_argument("--bl0-pll-clk", action="store_true", help="init PLL from fuses (vs refclk)")
    p.add_argument(
        "--status-report-disable",
        action="store_true",
        help="set the status_report_disable strap (also suppresses SEP_STATUS)",
    )
    # channels
    p.add_argument(
        "--no-sep-status",
        dest="sep_status",
        action="store_false",
        help="disable the [SEP_STATUS] production-status decoder",
    )
    p.add_argument(
        "--no-sim-out",
        dest="sim_out",
        action="store_false",
        help="disable the [SIM_OUT] debug console",
    )
    # run control
    p.add_argument(
        "--until",
        metavar="SEP_MSG_NAME",
        help="run until this SEP_STATUS message appears (success); else fail on timeout",
    )
    p.add_argument("--timeout", type=int, default=120, help="seconds to run (default 120)")
    p.add_argument(
        "--ini-only", action="store_true", help="print the generated overlay ini and exit"
    )
    # platform overrides
    p.add_argument("--sep-vp-bin", help="path to the sep-vp executable")
    p.add_argument("--base-ini", help="base accellera_config.ini to @include")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return p


def config_from_args(args) -> SimConfig:
    name = args.name or Path(args.bin).stem
    return SimConfig(
        name=name,
        elf=args.bin,
        flash_image=args.spi,
        otp=args.otp,
        boot=args.boot,
        recovery=args.recovery,
        rotate_update=args.rotate_update,
        bl0_pll_clk=args.bl0_pll_clk,
        status_report_disable=args.status_report_disable,
        sim_out=args.sim_out,
        sep_status=args.sep_status,
        boot_timeout=args.timeout,
    )


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    cfg = config_from_args(args)
    harness = SepVpHarness(
        cfg,
        sep_vp_bin=args.sep_vp_bin,
        base_ini=args.base_ini,
        stream=True,
    )

    if args.ini_only:
        sys.stdout.write(harness.render_ini())
        return 0

    print(f"[sepvp] {cfg}", file=sys.stderr)
    print(f"[sepvp] run dir: {harness.run_dir}", file=sys.stderr)
    try:
        harness.spawn()
    except HarnessError as e:
        print(f"[sepvp] ERROR: {e}", file=sys.stderr)
        return 2

    rc = 0
    try:
        if args.until:
            harness.expect_status(args.until, timeout=cfg.boot_timeout)
            print(f"\n[sepvp] reached {args.until} — success", file=sys.stderr)
        else:
            # Watch for a production ERROR, the VP test PASS/FAIL markers, EOF, or timeout.
            idx = harness.child.expect(
                [SEP_STATUS_ERROR_RE, FW_FAIL, FW_PASS, pexpect.EOF, pexpect.TIMEOUT],
                timeout=cfg.boot_timeout,
            )
            if idx == 0:
                print(f"\n[sepvp] saw production ERROR: {harness.child.after!r}", file=sys.stderr)
                rc = 2
            elif idx == 1:
                print("\n[sepvp] test FAILED ([VP] SIMULATION OF THE TEST FAILED)", file=sys.stderr)
                rc = 2
            elif idx == 2:
                print("\n[sepvp] test PASSED ([VP] SIMULATION OF THE TEST PASSED)", file=sys.stderr)
            elif idx == 3:
                print("\n[sepvp] sep-vp exited (EOF)", file=sys.stderr)
            else:
                print(f"\n[sepvp] timeout after {cfg.boot_timeout}s — stopping VP", file=sys.stderr)
    except HarnessError as e:
        print(f"\n[sepvp] {e}", file=sys.stderr)
        rc = 2
    finally:
        harness.close()
        print(f"[sepvp] log: {harness.log_path}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
