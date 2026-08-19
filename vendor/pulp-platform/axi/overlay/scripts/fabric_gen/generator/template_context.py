# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Pre-computed render context for fabric Mako templates.

Each builder returns plain dataclasses / lists keyed for direct consumption by
the templates so the .mako files contain layout only, not Python logic.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..config.schema import FabricConfig, ProtocolType
from ..model.conversion import ConversionChain, render_addr_range_exprs


def format_size(size_bytes: int) -> str:
    """Convert bytes to human-readable size string."""
    if size_bytes >= 1024 ** 3:
        return f"{size_bytes // (1024 ** 3)} GB"
    if size_bytes >= 1024 ** 2:
        return f"{size_bytes // (1024 ** 2)} MB"
    if size_bytes >= 1024:
        return f"{size_bytes // 1024} KB"
    return f"{size_bytes} B"


def format_addr(addr: int, width: int = 12) -> str:
    """Format address as hex with underscores every 4 digits (e.g. 0000_5000_3000)."""
    hex_str = format(addr, f'0{width}x')
    chunks = []
    for i in range(len(hex_str), 0, -4):
        chunks.insert(0, hex_str[max(0, i - 4):i])
    return '_'.join(chunks)


# Protocol kinds exposed to templates as plain strings so the templates do not
# need to import ProtocolType.
PROTOCOL_KIND = {
    ProtocolType.AXI4: 'axi4',
    ProtocolType.AXI4_LITE: 'axi_lite',
    ProtocolType.APB4: 'apb4',
}


@dataclass
class AddrMapTable:
    border: str
    header: str
    rows: List[str]


@dataclass
class ConnMatrixTable:
    border_top: str
    border_mid: str
    border_bot: str
    header: str
    rows: List[str]


@dataclass
class OutputPortRender:
    name: str
    base_name: str
    range_name: Optional[str]
    protocol_kind: str          # 'axi4' | 'axi_lite' | 'apb4'
    protocol_value: str         # e.g. "AXI4"
    data_width: int
    is_multi_apb: bool
    is_last: bool
    port_type_prefix: str       # type prefix for req_t/resp_t


@dataclass
class AddrRuleRender:
    out_name: str
    range_name: str
    idx: str
    start: str
    end: str
    start_comment: str
    end_comment: str


@dataclass
class OutputConversion:
    name: str                   # YAML output port name
    protocol_value: str         # e.g. "AXI4"
    data_width: int
    chain: Any                  # ConversionChain or None
    needs_conversion: bool
    is_multi_apb: bool


@dataclass
class InputConversion:
    proto: Any                  # ProtocolDef
    needs_protocol_conv: bool
    needs_resize: bool
    dw_type_prefix: str         # type prefix consumed by the dw_converter (slave side)
    dw_slv_req: str             # signal name fed into dw's slv_req_i
    dw_slv_resp: str
    dw_id_width: int


@dataclass
class ProtocolTypedef:
    prefix: str
    proto: Any                  # ProtocolDef
    kind: str                   # 'axi4' | 'axi_lite' | 'apb4'
    id_width: int               # already resolved (AXI4 inputs use max_input_id_width)


@dataclass
class PkgFlags:
    has_apb: bool
    has_axi4_outputs: bool
    xbar_is_axi: bool
    xbar_user_width: int
    latency_mode: str
    atop_bit: str               # '0' or '1'
    fall_through_bit: str       # '0' or '1'


def _addr_table_data(config: FabricConfig, get_output_protocol) -> AddrMapTable:
    entries: List[Dict[str, Any]] = []
    for out in config.outputs:
        out_proto = get_output_protocol(out)
        is_multi_apb = (
            out_proto.protocol == ProtocolType.APB4 and len(out.address_range) > 1
        )
        for range_name, ar in out.address_range.items():
            display = f"{out.name}_{range_name}" if is_multi_apb else out.name
            entries.append({
                'name': display,
                'protocol': out_proto.protocol.value,
                'base': ar.base,
                'end': ar.end,
                'size_str': format_size(ar.size),
            })

    name_w = max((len(e['name']) for e in entries), default=4)
    proto_w = max((len(e['protocol']) for e in entries), default=8)
    size_w = max((len(e['size_str']) for e in entries), default=4)

    border = (
        f"+{'─' * (name_w + 2)}+{'─' * (proto_w + 2)}"
        f"+──────────────────+──────────────────+{'─' * (size_w + 2)}+"
    )
    header = (
        f"| {'Port'.ljust(name_w)} | {'Protocol'.ljust(proto_w)} "
        f"|   Base Address   |   End Address    | {'Size'.center(size_w)} |"
    )
    rows = [
        f"| {e['name'].ljust(name_w)} | {e['protocol'].ljust(proto_w)} "
        f"| 0x{format_addr(e['base'])} | 0x{format_addr(e['end'])} "
        f"| {e['size_str'].rjust(size_w)} |"
        for e in entries
    ]
    return AddrMapTable(border=border, header=header, rows=rows)


def _conn_matrix_data(config: FabricConfig, connectivity_matrix) -> ConnMatrixTable:
    col_names = [out.name for out in config.outputs]
    max_inp_name = max(len(inp.name) for inp in config.inputs)
    col_width = max(max((len(cn) for cn in col_names), default=3), 3)

    span_top = '─┬─'.join('─' * col_width for _ in col_names)
    border_top = f"+{'─' * (max_inp_name + 2)}+{span_top}─+"
    span_mid = '─┼─'.join('─' * col_width for _ in col_names)
    border_mid = f"+{'─' * (max_inp_name + 2)}+{span_mid}─+"
    span_bot = '─┴─'.join('─' * col_width for _ in col_names)
    border_bot = f"+{'─' * (max_inp_name + 2)}+{span_bot}─+"

    header = (
        f"| {'Input'.ljust(max_inp_name)} "
        f"| {' | '.join(cn.center(col_width) for cn in col_names)} |"
    )

    rows = []
    for i, inp in enumerate(config.inputs):
        cells = [
            'YES' if connectivity_matrix[i][j] else '   '
            for j in range(len(config.outputs))
        ]
        rows.append(
            f"| {inp.name.ljust(max_inp_name)} "
            f"| {' | '.join(v.center(col_width) for v in cells)} |"
        )

    return ConnMatrixTable(
        border_top=border_top,
        border_mid=border_mid,
        border_bot=border_bot,
        header=header,
        rows=rows,
    )


def _output_ports(
    config: FabricConfig,
    chains: Dict[str, ConversionChain],
    get_output_protocol,
) -> List[OutputPortRender]:
    ports: List[OutputPortRender] = []
    for out in config.outputs:
        out_proto = get_output_protocol(out)
        is_multi_apb = (
            out_proto.protocol == ProtocolType.APB4 and len(out.address_range) > 1
        )
        sub_ranges = list(out.address_range.keys()) if is_multi_apb else [None]
        is_axi4 = out_proto.protocol == ProtocolType.AXI4
        chain = chains.get(out.name)
        has_conversion = chain is not None and not chain.is_empty
        if is_axi4 and has_conversion:
            port_type_prefix = out.name
        elif is_axi4:
            port_type_prefix = 'axi_out'
        else:
            port_type_prefix = out.protocol

        for range_name in sub_ranges:
            ports.append(OutputPortRender(
                name=f"{out.name}_{range_name}" if range_name else out.name,
                base_name=out.name,
                range_name=range_name,
                protocol_kind=PROTOCOL_KIND[out_proto.protocol],
                protocol_value=out_proto.protocol.value,
                data_width=out_proto.data_width,
                is_multi_apb=is_multi_apb,
                is_last=False,
                port_type_prefix=port_type_prefix,
            ))

    if ports:
        ports[-1].is_last = True
    return ports


def _addr_rules(config: FabricConfig, xbar_addr_width: int) -> List[AddrRuleRender]:
    slave_idx = {out.name: idx for idx, out in enumerate(config.outputs)}
    base_addr = config.base_addr_param

    def fmt_idx(ar, default_idx):
        if not ar.target_slave:
            return str(default_idx)
        expr = ar.target_slave
        for name, i in slave_idx.items():
            expr = expr.replace(f"'{name}'", str(i))
        return expr

    def fmt_comment(value, expr):
        return expr if expr else f"0x{value:08x}"

    rules: List[AddrRuleRender] = []
    for idx, out in enumerate(config.outputs):
        for rn, ar in out.address_range.items():
            start_expr, end_expr = render_addr_range_exprs(ar, xbar_addr_width, base_addr)
            rules.append(AddrRuleRender(
                out_name=out.name,
                range_name=rn,
                idx=fmt_idx(ar, idx),
                start=start_expr,
                end=end_expr,
                start_comment=fmt_comment(ar.base, ar.base_expr),
                end_comment=fmt_comment(ar.base + ar.size, ar.end_expr),
            ))
    return rules


def _output_conversions(
    config: FabricConfig,
    chains: Dict[str, ConversionChain],
    get_output_protocol,
) -> List[OutputConversion]:
    out: List[OutputConversion] = []
    for o in config.outputs:
        out_proto = get_output_protocol(o)
        chain = chains.get(o.name)
        out.append(OutputConversion(
            name=o.name,
            protocol_value=out_proto.protocol.value,
            data_width=out_proto.data_width,
            chain=chain,
            needs_conversion=chain is not None and not chain.is_empty,
            is_multi_apb=(
                out_proto.protocol == ProtocolType.APB4
                and len(o.address_range) > 1
            ),
        ))
    return out


def _input_conversions(
    config: FabricConfig,
    xbar_data_width: int,
    max_input_id_width: int,
    get_input_protocol,
) -> List[InputConversion]:
    items: List[InputConversion] = []
    xbar_is_axi = config.fabric.xbar_protocol == 'axi'

    for inp in config.inputs:
        inp_proto = get_input_protocol(inp)
        is_lite = inp_proto.protocol == ProtocolType.AXI4_LITE
        needs_protocol_conv = xbar_is_axi and is_lite
        needs_resize = inp_proto.data_width != xbar_data_width

        if needs_protocol_conv and needs_resize:
            dw_type_prefix = f"{inp.name}_axi"
            dw_slv_req = f"{inp.name}_axi_req"
            dw_slv_resp = f"{inp.name}_axi_resp"
            dw_id_width = max_input_id_width
        else:
            dw_type_prefix = inp.protocol
            dw_slv_req = f"{inp.name}_req_i"
            dw_slv_resp = f"{inp.name}_resp_o"
            dw_id_width = inp.id_width or inp_proto.id_width or 4

        items.append(InputConversion(
            proto=inp_proto,
            needs_protocol_conv=needs_protocol_conv,
            needs_resize=needs_resize,
            dw_type_prefix=dw_type_prefix,
            dw_slv_req=dw_slv_req,
            dw_slv_resp=dw_slv_resp,
            dw_id_width=dw_id_width,
        ))
    return items


def _protocol_typedefs(
    config: FabricConfig,
    max_input_id_width: int,
) -> List[ProtocolTypedef]:
    """Distinct (sorted) protocols used by any port, with resolved id_width."""
    names = sorted(
        {inp.protocol for inp in config.inputs}
        | {out.protocol for out in config.outputs}
    )

    out: List[ProtocolTypedef] = []
    for prefix in names:
        proto = config.protocols[prefix]
        # AXI4 protocols used by inputs share id_width with the xbar slave port
        # so the dw_converter's shared channel types stay consistent.
        if proto.protocol == ProtocolType.AXI4:
            if max_input_id_width > 0:
                id_width = max_input_id_width
            elif proto.id_width:
                id_width = proto.id_width
            else:
                id_width = 4
        else:
            id_width = 0
        out.append(ProtocolTypedef(
            prefix=prefix,
            proto=proto,
            kind=PROTOCOL_KIND[proto.protocol],
            id_width=id_width,
        ))
    return out


def _pkg_flags(config: FabricConfig) -> PkgFlags:
    has_apb = any(
        config.protocols[out.protocol].protocol == ProtocolType.APB4
        for out in config.outputs
    )
    has_axi4_outputs = any(
        config.protocols[out.protocol].protocol == ProtocolType.AXI4
        for out in config.outputs
    )
    xbar_is_axi = config.fabric.xbar_protocol == 'axi'
    xbar_user_width = max(
        (config.protocols[inp.protocol].user_width or 1)
        for inp in config.inputs
    )
    latency_mode = (
        "CUT_ALL_PORTS" if config.fabric.pipeline_stages > 0 else "NO_LATENCY"
    )
    return PkgFlags(
        has_apb=has_apb,
        has_axi4_outputs=has_axi4_outputs,
        xbar_is_axi=xbar_is_axi,
        xbar_user_width=xbar_user_width,
        latency_mode=latency_mode,
        atop_bit='1' if config.fabric.atop else '0',
        fall_through_bit='1' if config.fabric.fall_through else '0',
    )


def build_render_context(
    config: FabricConfig,
    chains: Dict[str, ConversionChain],
    xbar_data_width: int,
    xbar_addr_width: int,
    max_input_id_width: int,
    connectivity_matrix,
) -> Dict[str, Any]:
    """Pre-compute every derived value the templates consume."""
    return {
        'addr_map_table': _addr_table_data(config, config.get_output_protocol),
        'conn_matrix_table': _conn_matrix_data(config, connectivity_matrix),
        'output_ports': _output_ports(config, chains, config.get_output_protocol),
        'addr_rules': _addr_rules(config, xbar_addr_width),
        'input_conversions': _input_conversions(
            config, xbar_data_width, max_input_id_width, config.get_input_protocol
        ),
        'output_conversions': _output_conversions(
            config, chains, config.get_output_protocol
        ),
        'protocol_typedefs': _protocol_typedefs(config, max_input_id_width),
        'pkg_flags': _pkg_flags(config),
    }
