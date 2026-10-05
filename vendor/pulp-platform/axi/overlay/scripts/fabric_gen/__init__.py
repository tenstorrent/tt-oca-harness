# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
AXI Fabric Generator

A YAML-driven generator for AXI-based interconnect fabrics with automatic
protocol conversion chain insertion.

Key Design Principle:
  Width conversion BEFORE protocol downgrade to preserve AXI size field semantics.

  For AXI -> APB conversion:
    1. AXI 64-bit -> AXI 32-bit     (axi_dw_converter)
    2. AXI 32-bit -> AXI-Lite 32-bit (axi_to_axi_lite)
    3. AXI-Lite 32-bit -> APB 32-bit (axi_lite_to_apb)

Usage:
    from fabric_gen import load_config, FabricRenderer

    config = load_config("fabric.yaml")
    renderer = FabricRenderer(config)
    renderer.write_output("output/")
"""

__version__ = "0.1.0"

# Public API
from .config import load_config, validate_config, FabricConfig, ProtocolType
from .generator import FabricRenderer

__all__ = [
    'load_config',
    'validate_config',
    'FabricConfig',
    'FabricRenderer',
    'ProtocolType',
]
