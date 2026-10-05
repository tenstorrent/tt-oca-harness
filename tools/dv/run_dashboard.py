#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Entry point for static DV/FV dashboard utilities."""

from dashboard.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
