#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import argparse
import sys

import pyslang

parser = argparse.ArgumentParser(description="Lint a SystemVerilog file using pyslang")
parser.add_argument("file", help="SystemVerilog source file to lint")
args = parser.parse_args()

tree = pyslang.SyntaxTree.fromFile(args.file)
compilation = pyslang.Compilation()
compilation.addSyntaxTree(tree)

diags = compilation.getAllDiagnostics()
if diags:
    for d in diags:
        print(d)
    sys.exit(1)
else:
    print(f"{args.file}: OK")
    sys.exit(0)
