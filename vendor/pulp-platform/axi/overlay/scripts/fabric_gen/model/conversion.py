# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Conversion chain model for protocol/width conversions."""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Any, Optional, Tuple

from .protocol import Protocol


def render_addr_range_exprs(
    ar,
    addr_width: int,
    base_addr_param: Optional[str] = None,
) -> Tuple[str, str]:
    """Render (start_addr, end_addr) SystemVerilog expressions for an
    AddressRange rule.

    Honours `base_expr` / `end_expr` verbatim overrides on the range. Otherwise
    emits sized hex literals; when `tile_relative` is set and `base_addr_param`
    is provided, the literals are prefixed with that parameter so rules shift
    to absolute addresses at elaboration. `end_addr` is one bit wider than
    `start_addr` to allow representing addresses just past the address space.
    """
    def _literal(value: int, width: int) -> str:
        if ar.tile_relative and base_addr_param:
            if value == 0:
                return base_addr_param
            return f"{base_addr_param} + {width}'h{value:x}"
        return f"{width}'h{value:x}"

    start = ar.base_expr or _literal(ar.base, addr_width)
    end = ar.end_expr or _literal(ar.base + ar.size, addr_width + 1)
    return start, end


class ConversionType(str, Enum):
    """Types of conversions supported."""
    AXI_DW = "axi_dw_converter"
    AXI_TO_AXI_LITE = "axi_to_axi_lite"
    AXI_LITE_TO_AXI = "axi_lite_to_axi"
    AXI_LITE_DW = "axi_lite_dw_converter"
    AXI_LITE_TO_APB = "axi_lite_to_apb"
    PASSTHROUGH = "passthrough"


@dataclass
class ConversionStep:
    """Single conversion step in a chain."""
    conversion_type: ConversionType
    input_signal: str
    output_signal: str
    input_protocol: Protocol
    output_protocol: Protocol
    instance_name: str
    params: Dict[str, Any] = field(default_factory=dict)

    RENDER_DISPATCH = {
        ConversionType.PASSTHROUGH: '_render_passthrough',
        ConversionType.AXI_DW: '_render_axi_dw_converter',
        ConversionType.AXI_TO_AXI_LITE: '_render_axi_to_axi_lite',
        ConversionType.AXI_LITE_TO_AXI: '_render_axi_lite_to_axi',
        ConversionType.AXI_LITE_DW: '_render_axi_lite_dw_converter',
        ConversionType.AXI_LITE_TO_APB: '_render_axi_lite_to_apb',
    }

    def render_instance(self) -> str:
        """Render SystemVerilog module instantiation."""
        method_name = self.RENDER_DISPATCH.get(self.conversion_type)
        if method_name is None:
            raise ValueError(f"Unknown conversion type: {self.conversion_type}")
        return getattr(self, method_name)()

    def _render_passthrough(self) -> str:
        """Render passthrough assignment."""
        return f"""\
  // Passthrough: {self.input_signal} -> {self.output_signal}
  assign {self.output_signal}_req = {self.input_signal}_req;
  assign {self.input_signal}_resp = {self.output_signal}_resp;
"""

    def _render_axi_dw_converter(self) -> str:
        """Render axi_dw_converter instantiation.

        The axi_dw_converter has a single set of shared channel types
        (aw_chan_t, b_chan_t, ar_chan_t) used by both slave and master sides.
        Internally, the upsizer/downsizer's axi_demux operates on the
        master-side req/resp types, so these shared channel types MUST match
        the master-side (output) types to avoid width mismatches.
        """
        inp = self.input_protocol
        out = self.output_protocol
        return f"""\
  // AXI Data Width Converter: {inp.data_width}-bit -> {out.data_width}-bit
  axi_dw_converter #(
    .AxiMaxReads         ({inp.max_read_txns}),
    .AxiSlvPortDataWidth ({inp.data_width}),
    .AxiMstPortDataWidth ({out.data_width}),
    .AxiAddrWidth        ({out.addr_width}),
    .AxiIdWidth          ({out.id_width}),
    .aw_chan_t           ({self.output_signal}_aw_chan_t),
    .mst_w_chan_t        ({self.output_signal}_w_chan_t),
    .slv_w_chan_t        ({self.input_signal}_w_chan_t),
    .b_chan_t            ({self.output_signal}_b_chan_t),
    .ar_chan_t           ({self.output_signal}_ar_chan_t),
    .mst_r_chan_t        ({self.output_signal}_r_chan_t),
    .slv_r_chan_t        ({self.input_signal}_r_chan_t),
    .axi_mst_req_t       ({self.output_signal}_req_t),
    .axi_mst_resp_t      ({self.output_signal}_resp_t),
    .axi_slv_req_t       ({self.input_signal}_req_t),
    .axi_slv_resp_t      ({self.input_signal}_resp_t)
  ) {self.instance_name} (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .slv_req_i  ({self.input_signal}_req),
    .slv_resp_o ({self.input_signal}_resp),
    .mst_req_o  ({self.output_signal}_req),
    .mst_resp_i ({self.output_signal}_resp)
  );
"""

    def _render_axi_to_axi_lite(self) -> str:
        """Render axi_to_axi_lite instantiation."""
        inp = self.input_protocol
        fall_through = self.params.get('fall_through', False)
        return f"""\
  // AXI to AXI-Lite Protocol Converter
  axi_to_axi_lite #(
    .AxiAddrWidth    ({inp.addr_width}),
    .AxiDataWidth    ({inp.data_width}),
    .AxiIdWidth      ({inp.id_width}),
    .AxiUserWidth    ({inp.user_width}),
    .AxiMaxWriteTxns ({inp.max_write_txns}),
    .AxiMaxReadTxns  ({inp.max_read_txns}),
    .FallThrough     (1'b{1 if fall_through else 0}),
    .full_req_t      ({self.input_signal}_req_t),
    .full_resp_t     ({self.input_signal}_resp_t),
    .lite_req_t      ({self.output_signal}_req_t),
    .lite_resp_t     ({self.output_signal}_resp_t)
  ) {self.instance_name} (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .test_i     (1'b0),
    .slv_req_i  ({self.input_signal}_req),
    .slv_resp_o ({self.input_signal}_resp),
    .mst_req_o  ({self.output_signal}_req),
    .mst_resp_i ({self.output_signal}_resp)
  );
"""

    def _render_axi_lite_to_axi(self) -> str:
        """Render axi_lite_to_axi instantiation."""
        inp = self.input_protocol
        return f"""\
  // AXI-Lite to AXI Protocol Converter
  axi_lite_to_axi #(
    .AxiDataWidth ({inp.data_width}),
    .req_lite_t   ({self.input_signal}_req_t),
    .resp_lite_t  ({self.input_signal}_resp_t),
    .axi_req_t    ({self.output_signal}_req_t),
    .axi_resp_t   ({self.output_signal}_resp_t)
  ) {self.instance_name} (
    .slv_req_lite_i  ({self.input_signal}_req),
    .slv_resp_lite_o ({self.input_signal}_resp),
    .slv_aw_cache_i  (axi_pkg::CACHE_BUFFERABLE | axi_pkg::CACHE_MODIFIABLE),
    .slv_ar_cache_i  (axi_pkg::CACHE_BUFFERABLE | axi_pkg::CACHE_MODIFIABLE),
    .mst_req_o       ({self.output_signal}_req),
    .mst_resp_i      ({self.output_signal}_resp)
  );
"""

    def _render_axi_lite_dw_converter(self) -> str:
        """Render axi_lite_dw_converter instantiation."""
        inp = self.input_protocol
        out = self.output_protocol
        return f"""\
  // AXI-Lite Data Width Converter: {inp.data_width}-bit -> {out.data_width}-bit
  axi_lite_dw_converter #(
    .AxiAddrWidth        ({inp.addr_width}),
    .AxiSlvPortDataWidth ({inp.data_width}),
    .AxiMstPortDataWidth ({out.data_width}),
    .axi_lite_slv_req_t  ({self.input_signal}_req_t),
    .axi_lite_slv_resp_t ({self.input_signal}_resp_t),
    .axi_lite_mst_req_t  ({self.output_signal}_req_t),
    .axi_lite_mst_resp_t ({self.output_signal}_resp_t)
  ) {self.instance_name} (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .slv_req_i  ({self.input_signal}_req),
    .slv_resp_o ({self.input_signal}_resp),
    .mst_req_o  ({self.output_signal}_req),
    .mst_resp_i ({self.output_signal}_resp)
  );
"""

    def _render_axi_lite_to_apb(self) -> str:
        """Render axi_lite_to_apb instantiation."""
        inp = self.input_protocol
        pipeline_req = self.params.get('pipeline_request', False)
        pipeline_resp = self.params.get('pipeline_response', False)
        address_ranges = self.params.get('address_ranges', {})
        base_addr = self.params.get('base_addr_param')
        # Convert snake_case to CamelCase for localparam name
        camel_name = ''.join(word.capitalize() for word in self.output_signal.split('_'))
        addr_map_name = f"{camel_name}ApbAddrMap"

        num_apb_slaves = len(address_ranges)
        num_rules = num_apb_slaves

        # Build address map entries. AXI-Lite-side addr_width is used for
        # decode/map to avoid truncating high bits.
        map_entries = []
        range_names = list(address_ranges.keys())
        for idx, (range_name, ar) in enumerate(address_ranges.items()):
            start_expr, end_expr = render_addr_range_exprs(ar, inp.addr_width, base_addr)
            map_entries.append(
                f"    // {range_name}: 0x{ar.base:08x} - 0x{ar.end:08x} -> slave[{idx}]"
                f"\n    '{{idx: {idx}, start_addr: {start_expr}, "
                f"end_addr: {end_expr}}}"
            )

        map_content = ',\n'.join(map_entries)

        # For multiple APB slaves, generate array and wire to named outputs
        if num_apb_slaves > 1:
            # Generate wiring from array to named output ports
            wire_assignments = []
            for idx, range_name in enumerate(range_names):
                port_name = f"{self.output_signal}_{range_name}"
                wire_assignments.append(
                    f"  assign {port_name}_req_o = {self.output_signal}_req[{idx}];\n"
                    f"  assign {self.output_signal}_resp[{idx}] = {port_name}_resp_i;"
                )
            wire_content = '\n'.join(wire_assignments)

            return f"""\
  // AXI-Lite to APB Bridge ({num_apb_slaves} APB slaves)
  localparam apb_addr_rule_t [{num_rules - 1}:0] {addr_map_name} = '{{
{map_content}
  }};

  // APB slave array signals
  {self.output_signal}_req_t  [{num_apb_slaves - 1}:0] {self.output_signal}_req;
  {self.output_signal}_resp_t [{num_apb_slaves - 1}:0] {self.output_signal}_resp;

  axi_lite_to_apb #(
    .NoApbSlaves      ({num_apb_slaves}),
    .NoRules          ({num_rules}),
    .AddrWidth        ({inp.addr_width}),
    .DataWidth        ({inp.data_width}),
    .PipelineRequest  (1'b{1 if pipeline_req else 0}),
    .PipelineResponse (1'b{1 if pipeline_resp else 0}),
    .axi_lite_req_t   ({self.input_signal}_req_t),
    .axi_lite_resp_t  ({self.input_signal}_resp_t),
    .apb_req_t        ({self.output_signal}_req_t),
    .apb_resp_t       ({self.output_signal}_resp_t),
    .rule_t           (apb_addr_rule_t)
  ) {self.instance_name} (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),
    .axi_lite_req_i  ({self.input_signal}_req),
    .axi_lite_resp_o ({self.input_signal}_resp),
    .apb_req_o       ({self.output_signal}_req),
    .apb_resp_i      ({self.output_signal}_resp),
    .addr_map_i      ({addr_map_name})
  );

  // Wire APB array to named output ports
{wire_content}
"""
        else:
            # Single APB slave - keep simple wiring
            return f"""\
  // AXI-Lite to APB Bridge (1 APB slave)
  localparam apb_addr_rule_t [{num_rules - 1}:0] {addr_map_name} = '{{
{map_content}
  }};

  axi_lite_to_apb #(
    .NoApbSlaves      ({num_apb_slaves}),
    .NoRules          ({num_rules}),
    .AddrWidth        ({inp.addr_width}),
    .DataWidth        ({inp.data_width}),
    .PipelineRequest  (1'b{1 if pipeline_req else 0}),
    .PipelineResponse (1'b{1 if pipeline_resp else 0}),
    .axi_lite_req_t   ({self.input_signal}_req_t),
    .axi_lite_resp_t  ({self.input_signal}_resp_t),
    .apb_req_t        ({self.output_signal}_req_t),
    .apb_resp_t       ({self.output_signal}_resp_t),
    .rule_t           (apb_addr_rule_t)
  ) {self.instance_name} (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),
    .axi_lite_req_i  ({self.input_signal}_req),
    .axi_lite_resp_o ({self.input_signal}_resp),
    .apb_req_o       ({self.output_signal}_req),
    .apb_resp_i      ({self.output_signal}_resp),
    .addr_map_i      ({addr_map_name})
  );
"""


@dataclass
class ConversionChain:
    """Complete conversion chain from one port to another."""
    input_name: str
    output_name: str
    steps: List[ConversionStep] = field(default_factory=list)

    def add_step(self, step: ConversionStep) -> None:
        """Add a conversion step to the chain."""
        self.steps.append(step)

    @property
    def is_empty(self) -> bool:
        """Return True if chain has no steps (direct connection)."""
        return not self.steps

    @property
    def final_signal(self) -> str:
        """Return the final signal name in the chain."""
        if self.steps:
            return self.steps[-1].output_signal
        return self.input_name

    def render_all_instances(self) -> str:
        """Render all conversion instances in the chain."""
        return "\n".join(step.render_instance() for step in self.steps)

    def render_signal_declarations(self) -> str:
        """Render signal wire declarations for all intermediate signals."""
        lines = []
        seen = set()
        for step in self.steps:
            # Input signal (first step connects to xbar)
            if step.input_signal not in seen:
                lines.append(f"  {step.input_signal}_req_t  {step.input_signal}_req;")
                lines.append(f"  {step.input_signal}_resp_t {step.input_signal}_resp;")
                seen.add(step.input_signal)
            # Output signal: skip for multi-slave APB — the bridge declares its own array
            if step.output_signal not in seen:
                is_multi_slave_apb = (
                    step.conversion_type == ConversionType.AXI_LITE_TO_APB
                    and len(step.params.get('address_ranges', {})) > 1
                )
                if not is_multi_slave_apb:
                    lines.append(f"  {step.output_signal}_req_t  {step.output_signal}_req;")
                    lines.append(f"  {step.output_signal}_resp_t {step.output_signal}_resp;")
                seen.add(step.output_signal)
        return "\n".join(lines)

    def render_xbar_connection(self, xbar_index: int) -> str:
        """Render the assignment connecting crossbar output to chain input."""
        if not self.steps:
            return ""
        first_input = self.steps[0].input_signal
        return f"""\
  assign {first_input}_req = xbar_mst_req[{xbar_index}];
  assign xbar_mst_resp[{xbar_index}] = {first_input}_resp;"""

    def render_output_connection(self, output_name: str) -> str:
        """Render the assignment connecting chain output to module port."""
        if not self.steps:
            return ""
        last_output = self.steps[-1].output_signal
        return f"""\
  assign {output_name}_req_o = {last_output}_req;
  assign {last_output}_resp = {output_name}_resp_i;"""

    def render_typedefs(self) -> str:
        """Render all required typedefs for this chain."""
        typedefs = []
        seen_signals = set()

        for step in self.steps:
            # Input signal typedefs
            if step.input_signal not in seen_signals:
                typedefs.append(step.input_protocol.render_axi_channel_typedefs(step.input_signal))
                seen_signals.add(step.input_signal)

            # Output signal typedefs
            if step.output_signal not in seen_signals:
                typedefs.append(step.output_protocol.render_axi_channel_typedefs(step.output_signal))
                seen_signals.add(step.output_signal)

        return "\n\n".join(typedefs)
