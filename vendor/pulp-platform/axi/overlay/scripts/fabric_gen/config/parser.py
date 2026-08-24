# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""YAML configuration parser for fabric generator."""
import yaml
from pathlib import Path
from typing import Union
from pydantic import ValidationError

from .schema import FabricConfig, ProtocolDef, InputPort, OutputPort, AddressRange, FabricSettings, ParameterDef


def load_config(config_path: Union[str, Path]) -> FabricConfig:
    """
    Load and validate a fabric configuration from a YAML file.

    Args:
        config_path: Path to the YAML configuration file

    Returns:
        Validated FabricConfig object

    Raises:
        FileNotFoundError: If config file doesn't exist
        yaml.YAMLError: If YAML parsing fails
        ValidationError: If configuration validation fails
    """
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, 'r') as f:
        raw_config = yaml.safe_load(f)

    return parse_config(raw_config, source_file=str(config_path))


def parse_config(raw_config: dict, source_file: str = "<string>") -> FabricConfig:
    """
    Parse a raw configuration dictionary into a FabricConfig.

    Args:
        raw_config: Dictionary from YAML parsing
        source_file: Source file name for error messages

    Returns:
        Validated FabricConfig object
    """
    try:
        # Legacy format has `parameters:` as a dict (with xbar_cfg/inputs/outputs inside).
        # New format may have `parameters:` as a list of module-level SV parameters;
        # we detect legacy by checking for a dict.
        params = raw_config.get('parameters')
        if isinstance(params, dict):
            return _parse_legacy_format(params, source_file)
        return _parse_new_format(raw_config, source_file)
    except ValidationError:
        raise


def _parse_address_ranges(raw_addr_range: dict, output_name: str) -> dict:
    """Parse address ranges from dict format to AddressRange objects."""
    if not isinstance(raw_addr_range, dict):
        raise ValueError(
            f"Output '{output_name}' address_range must be a dict with named ranges, "
            f"e.g., address_range: {{ uart: {{ base: 0x1000, size: 0x100 }} }}"
        )
    parsed = {}
    for range_name, range_data in raw_addr_range.items():
        if not isinstance(range_data, dict):
            raise ValueError(
                f"Invalid address_range entry '{range_name}' in output "
                f"'{output_name}': expected dict with base/size"
            )
        parsed[range_name] = AddressRange(name=range_name, **range_data)
    return parsed


def _parse_new_format(raw: dict, source_file: str) -> FabricConfig:
    """Parse the new YAML format."""
    protocols = {name: ProtocolDef(**data) for name, data in raw.get('protocols', {}).items()}
    inputs = [InputPort(**inp_data) for inp_data in raw.get('inputs', [])]

    outputs = []
    for out_data in raw.get('outputs', []):
        if 'address_range' in out_data:
            out_data['address_range'] = _parse_address_ranges(
                out_data['address_range'],
                out_data.get('name', 'unknown')
            )
        outputs.append(OutputPort(**out_data))

    params_list = raw.get('parameters', []) or []
    parameters = [ParameterDef(**p) for p in params_list]

    return FabricConfig(
        name=raw.get('name', 'fabric'),
        description=raw.get('description', ''),
        fabric=FabricSettings(**raw.get('fabric', {})),
        protocols=protocols,
        inputs=inputs,
        outputs=outputs,
        connectivity=raw.get('connectivity'),
        parameters=parameters,
        base_addr_param=raw.get('base_addr_param'),
    )


def _parse_legacy_format(params: dict, source_file: str) -> FabricConfig:
    """Parse the legacy YAML format from smc/meta/crossbars."""
    xbar_cfg = params.get('xbar_cfg', {})

    # Determine base protocol from xbar_cfg
    protocol_str = xbar_cfg.get('protocol', 'axi')
    base_protocol = 'AXI4' if protocol_str == 'axi' else 'AXI4_LITE'

    # Create default protocol definition
    default_proto = ProtocolDef(
        protocol=base_protocol,
        data_width=xbar_cfg.get('data_width', 64),
        addr_width=xbar_cfg.get('addr_width', 32),
        id_width=xbar_cfg.get('input_id_width', 4) if base_protocol == 'AXI4' else None,
        user_width=xbar_cfg.get('user_width', 1),
        max_read_txns=xbar_cfg.get('max_mst_trans', 8),
        max_write_txns=xbar_cfg.get('max_mst_trans', 8),
    )

    protocols = {'default': default_proto}

    # Parse inputs
    inputs = []
    raw_inputs = params.get('inputs', {})
    for name, inp_data in raw_inputs.items():
        # Create protocol variant if different widths
        proto_name = 'default'
        if inp_data.get('data_width') != default_proto.data_width:
            proto_name = f"{name}_proto"
            protocols[proto_name] = ProtocolDef(
                protocol=base_protocol,
                data_width=inp_data.get('data_width', default_proto.data_width),
                addr_width=inp_data.get('addr_width', default_proto.addr_width),
                id_width=inp_data.get('id_width', default_proto.id_width),
                user_width=default_proto.user_width,
            )

        inputs.append(InputPort(
            name=name,
            protocol=proto_name,
            id_width=inp_data.get('id_width'),
            paths=inp_data.get('paths'),
        ))

    # Parse outputs
    outputs = []
    raw_outputs = params.get('outputs', {})
    for name, out_data in raw_outputs.items():
        # Create protocol variant if different widths
        proto_name = 'default'
        if out_data.get('data_width') != default_proto.data_width:
            proto_name = f"{name}_proto"
            protocols[proto_name] = ProtocolDef(
                protocol=base_protocol,
                data_width=out_data.get('data_width', default_proto.data_width),
                addr_width=out_data.get('addr_width', default_proto.addr_width),
                id_width=default_proto.id_width,
                user_width=default_proto.user_width,
            )

        # Parse address ranges - convert to dict format with auto-generated names
        address_ranges = {}
        for i, ar in enumerate(out_data.get('address_ranges', [])):
            range_name = f"range_{i}"
            address_ranges[range_name] = AddressRange(
                name=range_name,
                base=ar.get('offset', 0),
                size=ar.get('size', 0x1000),
            )

        outputs.append(OutputPort(
            name=name,
            protocol=proto_name,
            address_range=address_ranges,
            pipeline_stages=0,
        ))

    # Map flop_axi to pipeline stages
    flop_axi = xbar_cfg.get('flop_axi', 0)
    pipeline_stages = 1 if flop_axi > 0 else 0

    fabric = FabricSettings(
        xbar_protocol=protocol_str,
        max_outstanding_txns=xbar_cfg.get('max_mst_trans', 8),
        pipeline_stages=pipeline_stages,
        fall_through=False,
        atop=xbar_cfg.get('atop', False),
    )

    return FabricConfig(
        name=xbar_cfg.get('module_name', 'fabric'),
        description='',
        fabric=fabric,
        protocols=protocols,
        inputs=inputs,
        outputs=outputs,
    )


def validate_protocol_compatibility(config: FabricConfig) -> None:
    """
    Validate that input/output protocols are compatible with crossbar protocol.

    AXI-Lite crossbar does not support AXI4 ports (inputs or outputs).
    Use an AXI crossbar if you have AXI4 masters or need AXI4 outputs.

    Raises:
        ValueError: If incompatible protocol combination is detected
    """
    from .schema import ProtocolType

    xbar_is_axi = config.fabric.xbar_protocol == 'axi'

    # AXI-Lite crossbar cannot accept AXI inputs
    for inp in config.inputs:
        inp_proto = config.get_input_protocol(inp)
        if not xbar_is_axi and inp_proto.protocol == ProtocolType.AXI4:
            raise ValueError(
                f"Input '{inp.name}' uses AXI4 protocol but crossbar is AXI-Lite. "
                f"AXI inputs require xbar_protocol: 'axi'. "
                f"Either change the input to AXI-Lite or use an AXI crossbar."
            )

    # AXI-Lite crossbar cannot drive AXI outputs (no protocol upgrade)
    for out in config.outputs:
        out_proto = config.get_output_protocol(out)
        if not xbar_is_axi and out_proto.protocol == ProtocolType.AXI4:
            raise ValueError(
                f"Output '{out.name}' uses AXI4 protocol but crossbar is AXI-Lite. "
                f"AXI outputs require xbar_protocol: 'axi'. "
                f"Either change the output to AXI-Lite or use an AXI crossbar."
            )


def validate_config(config: FabricConfig) -> list:
    """
    Perform additional validation checks on the configuration.

    Returns a list of warning messages (not errors).
    """
    from .schema import ProtocolType, PROTOCOL_HIERARCHY

    validate_protocol_compatibility(config)
    max_id_width = config.get_max_input_id_width(log_duplicates=True)

    warnings = []
    xbar_data_width = max(config.get_input_protocol(inp).data_width for inp in config.inputs)
    xbar_addr_width = max(config.get_input_protocol(inp).addr_width for inp in config.inputs)
    xbar_proto_type = ProtocolType.AXI4 if config.fabric.xbar_protocol == 'axi' else ProtocolType.AXI4_LITE

    if max_id_width > 8:
        warnings.append(f"Large ID width ({max_id_width}) may impact area")

    for out in config.outputs:
        out_proto = config.get_output_protocol(out)
        if out_proto.data_width != xbar_data_width:
            warnings.append(
                f"Output '{out.name}' requires data width conversion "
                f"({xbar_data_width} -> {out_proto.data_width})"
            )
        if out_proto.protocol == ProtocolType.APB4 and out_proto.addr_width != xbar_addr_width:
            warnings.append(
                f"Output '{out.name}' APB addr_width ({out_proto.addr_width}) differs from "
                f"crossbar decode width ({xbar_addr_width}); upper address bits are dropped "
                f"when driving APB paddr."
            )
        if PROTOCOL_HIERARCHY[out_proto.protocol] < PROTOCOL_HIERARCHY[xbar_proto_type]:
            warnings.append(
                f"Output '{out.name}' requires protocol conversion "
                f"({xbar_proto_type.value} -> {out_proto.protocol.value})"
            )

    return warnings
