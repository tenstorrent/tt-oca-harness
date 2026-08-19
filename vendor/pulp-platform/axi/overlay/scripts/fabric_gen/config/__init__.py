# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Configuration module for fabric generator."""
from .schema import (
    FabricConfig,
    ProtocolDef,
    ProtocolType,
    PROTOCOL_HIERARCHY,
    InputPort,
    OutputPort,
    AddressRange,
    FabricSettings,
)
from .parser import load_config, validate_config

__all__ = [
    'FabricConfig',
    'FabricSettings',
    'ProtocolDef',
    'ProtocolType',
    'PROTOCOL_HIERARCHY',
    'InputPort',
    'OutputPort',
    'AddressRange',
    'load_config',
    'validate_config',
]
