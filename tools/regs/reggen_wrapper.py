#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Copyright lowRISC contributors (OpenTitan project).
# Licensed under the Apache License, Version 2.0, see LICENSE for details.
# SPDX-License-Identifier: Apache-2.0
"""Minimal wrapper for OpenTitan reggen.

This intentionally exposes only the HJSON-to-SystemRDL path needed by OCAH.
The OpenTitan reggen modules themselves are vendored under
vendor/lowRISC/opentitan/upstream/util.
"""

from __future__ import annotations

import argparse
import logging as log
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _add_vendored_reggen_to_path() -> None:
    ot_util = _repo_root() / "vendor" / "lowRISC" / "opentitan" / "upstream" / "util"
    sys.path.insert(0, str(ot_util))


def _parse_params(raw: str) -> list[tuple[str, str]]:
    params: list[tuple[str, str]] = []
    for idx, raw_param in enumerate(raw.split(";") if raw else []):
        tokens = raw_param.split("=")
        if len(tokens) != 2:
            raise ValueError(
                f"Entry {idx} in parameter defaults is {raw_param!r}, "
                "which is not of the form param=value."
            )
        params.append((tokens[0], tokens[1]))
    return params


def main() -> int:
    _add_vendored_reggen_to_path()

    from reggen.ip_block import IpBlock
    from reggen.systemrdl_exporter import SystemrdlExporter

    parser = argparse.ArgumentParser(
        prog="reggen_wrapper.py",
        description="Export an OpenTitan HJSON register description to SystemRDL.",
    )
    parser.add_argument("input", type=argparse.FileType("r"), help="Input HJSON file")
    parser.add_argument(
        "--systemrdl",
        action="store_true",
        help="Export SystemRDL. This is the only supported output format.",
    )
    parser.add_argument(
        "-o",
        "--outfile",
        type=argparse.FileType("w"),
        default=sys.stdout,
        help="Output file. Defaults to stdout.",
    )
    parser.add_argument(
        "-p",
        "--param",
        default="",
        help="Parameter overrides as ParamA=ValA;ParamB=ValB.",
    )
    parser.add_argument(
        "-n",
        "--node",
        default="",
        help="Regblock node to export. Defaults to all nodes.",
    )
    parser.add_argument(
        "--name",
        default="",
        help="Override the top addrmap name (e.g. export dma.hjson as 'secure_dma'). "
        "Defaults to the hjson 'name' field.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-q", "--quiet", action="store_true")

    args = parser.parse_args()
    if not args.systemrdl:
        parser.error("Only --systemrdl is supported")

    log_format = "%(filename)s:%(lineno)d: %(levelname)s: %(message)s"
    if args.verbose:
        log.basicConfig(format=log_format, level=log.DEBUG)
    elif args.quiet:
        log.basicConfig(format=log_format, level=log.ERROR)
    else:
        log.basicConfig(format=log_format)

    params = _parse_params(args.param)
    try:
        block = IpBlock.from_text(args.input.read(), params, args.input.name, args.node)
    except ValueError as err:
        log.error(str(err))
        return 1

    # Vendored IPs whose TT name differs from the upstream hjson name (e.g.
    # dma -> secure_dma, spi_host -> spi_controller): override the top addrmap
    # name so the emitted RDL matches the committed/included block name.
    if args.name:
        block.name = args.name

    return SystemrdlExporter(block).export(args.outfile)


if __name__ == "__main__":
    raise SystemExit(main())
