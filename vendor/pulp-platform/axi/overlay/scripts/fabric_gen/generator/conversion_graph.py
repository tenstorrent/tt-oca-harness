# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
Conversion graph algorithm for generating protocol/width conversion chains.

CRITICAL DESIGN PRINCIPLE:
  Width conversion MUST happen BEFORE protocol downgrade to preserve AXI size field semantics.

  Correct order for AXI 64-bit -> APB 32-bit:
    1. AXI 64-bit -> AXI 32-bit     (axi_dw_converter)
    2. AXI 32-bit -> AXI-Lite 32-bit (axi_to_axi_lite)
    3. AXI-Lite 32-bit -> APB 32-bit (axi_lite_to_apb)

  WRONG order:
    AXI -> AXI-Lite -> downsize (loses size field semantics!)
"""
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple

from ..config.schema import FabricConfig, OutputPort, ProtocolType
from ..model.protocol import Protocol
from ..model.conversion import ConversionChain, ConversionStep, ConversionType


@dataclass
class PortState:
    """Current state during conversion chain generation."""
    protocol: Protocol
    signal_name: str


class ConversionGraphGenerator:
    """
    Generates optimal conversion chains between input and output ports.

    The key invariant maintained is:
      WIDTH CONVERSION BEFORE PROTOCOL DOWNGRADE

    This ensures that the AXI size field is used correctly during downsizing.
    """

    def __init__(self, config: FabricConfig):
        self.config = config
        self._step_counter: Dict[str, int] = {}

    def generate_output_chain(self, output: OutputPort) -> Optional[ConversionChain]:
        """
        Generate the conversion chain needed for an output port.

        This generates the chain from xbar output protocol to the target output protocol,
        following the critical width-before-protocol rule.

        Args:
            output: Output port definition

        Returns:
            ConversionChain or None if no conversion needed
        """
        # Determine xbar output protocol
        xbar_protocol = self._get_xbar_output_protocol()
        target_protocol = self._get_output_protocol(output)

        # Check if conversion needed
        if self._protocols_equal(xbar_protocol, target_protocol):
            return None

        chain = ConversionChain(
            input_name=f"xbar_out_{output.name}",
            output_name=output.name,
        )

        current = PortState(
            protocol=xbar_protocol.copy(),
            signal_name=f"xbar_out_{output.name}",
        )

        # Generate conversion steps following the critical invariant
        steps = self._generate_conversion_steps(current.protocol, target_protocol, output.name)

        for step_type, step_input, step_output, in_proto, out_proto in steps:
            step = ConversionStep(
                conversion_type=step_type,
                input_signal=step_input,
                output_signal=step_output,
                input_protocol=in_proto,
                output_protocol=out_proto,
                instance_name=self._next_instance_name(step_type, output.name),
                params=self._get_step_params(step_type, output),
            )
            chain.add_step(step)

        return chain

    def _generate_conversion_steps(
        self,
        current: Protocol,
        target: Protocol,
        output_name: str
    ) -> List[Tuple[ConversionType, str, str, Protocol, Protocol]]:
        """
        Generate the sequence of conversion steps.

        CRITICAL: This method implements the width-before-protocol rule.

        Returns:
            List of (type, input_signal, output_signal, input_protocol, output_protocol) tuples
        """
        steps = []
        step_idx = 0

        def signal_name(idx: int) -> str:
            if idx == 0:
                return f"xbar_out_{output_name}"
            return f"{output_name}_stage{idx}"

        # Check if we need protocol downgrade
        needs_protocol_downgrade = current.hierarchy_level > target.hierarchy_level

        # STEP 1: Width conversion BEFORE protocol downgrade (CRITICAL!)
        if needs_protocol_downgrade and current.protocol_type == ProtocolType.AXI4:
            # If going to AXI-Lite or APB, match width while still in AXI domain
            if current.data_width != target.data_width:
                next_proto = current.copy(data_width=target.data_width)
                steps.append((
                    ConversionType.AXI_DW,
                    signal_name(step_idx),
                    signal_name(step_idx + 1),
                    current,
                    next_proto,
                ))
                current = next_proto
                step_idx += 1

        # STEP 2: Protocol conversion AXI -> AXI-Lite
        if current.protocol_type == ProtocolType.AXI4 and target.protocol_type in (ProtocolType.AXI4_LITE, ProtocolType.APB4):
            next_proto = Protocol(
                protocol_type=ProtocolType.AXI4_LITE,
                data_width=current.data_width,
                addr_width=current.addr_width,
                id_width=0,
                user_width=0,
            )
            steps.append((
                ConversionType.AXI_TO_AXI_LITE,
                signal_name(step_idx),
                signal_name(step_idx + 1),
                current,
                next_proto,
            ))
            current = next_proto
            step_idx += 1

        # STEP 3: AXI-Lite width conversion (if going to APB with different width)
        if current.protocol_type == ProtocolType.AXI4_LITE and target.protocol_type == ProtocolType.APB4:
            if current.data_width != target.data_width:
                next_proto = current.copy(data_width=target.data_width)
                steps.append((
                    ConversionType.AXI_LITE_DW,
                    signal_name(step_idx),
                    signal_name(step_idx + 1),
                    current,
                    next_proto,
                ))
                current = next_proto
                step_idx += 1

        # STEP 4: AXI-Lite -> APB conversion
        if current.protocol_type == ProtocolType.AXI4_LITE and target.protocol_type == ProtocolType.APB4:
            steps.append((
                ConversionType.AXI_LITE_TO_APB,
                signal_name(step_idx),
                output_name,  # Final output
                current,
                target,
            ))
            step_idx += 1

        # STEP 5: AXI-only width conversion (no protocol change)
        if current.protocol_type == ProtocolType.AXI4 and target.protocol_type == ProtocolType.AXI4:
            if current.data_width != target.data_width:
                steps.append((
                    ConversionType.AXI_DW,
                    signal_name(step_idx),
                    output_name,  # Final output
                    current,
                    target,
                ))
                step_idx += 1

        # STEP 6: AXI-Lite only width conversion (no protocol change)
        if current.protocol_type == ProtocolType.AXI4_LITE and target.protocol_type == ProtocolType.AXI4_LITE:
            if current.data_width != target.data_width:
                steps.append((
                    ConversionType.AXI_LITE_DW,
                    signal_name(step_idx),
                    output_name,  # Final output
                    current,
                    target,
                ))
                step_idx += 1

        # Fix final output signal name if we haven't set it
        if steps and steps[-1][2] != output_name:
            last = steps[-1]
            steps[-1] = (last[0], last[1], output_name, last[3], last[4])

        return steps

    def _get_xbar_output_protocol(self) -> Protocol:
        """Get the protocol at the crossbar output ports."""
        # Determine xbar data width (max of all inputs)
        xbar_data_width = max(
            self.config.get_input_protocol(inp).data_width
            for inp in self.config.inputs
        )

        # Determine xbar address width (max of all inputs)
        xbar_addr_width = max(
            self.config.get_input_protocol(inp).addr_width
            for inp in self.config.inputs
        )

        # Output ID width is extended by crossbar
        xbar_output_id_width = self.config.get_xbar_output_id_width()

        # User width from config
        user_width = max(
            (self.config.get_input_protocol(inp).user_width or 0)
            for inp in self.config.inputs
        )

        if self.config.fabric.xbar_protocol == 'axi':
            return Protocol(
                protocol_type=ProtocolType.AXI4,
                data_width=xbar_data_width,
                addr_width=xbar_addr_width,
                id_width=xbar_output_id_width,
                user_width=user_width,
                max_read_txns=self.config.fabric.max_outstanding_txns,
                max_write_txns=self.config.fabric.max_outstanding_txns,
            )
        else:
            return Protocol(
                protocol_type=ProtocolType.AXI4_LITE,
                data_width=xbar_data_width,
                addr_width=xbar_addr_width,
                id_width=0,
                user_width=0,
            )

    def _get_output_protocol(self, output: OutputPort) -> Protocol:
        """Get the target protocol for an output port.

        For AXI4 outputs, id_width is derived from crossbar output ID width
        (max input ID + clog2(num_inputs)).
        """
        proto_def = self.config.get_output_protocol(output)

        # For AXI4 outputs, use crossbar output ID width
        if proto_def.protocol == ProtocolType.AXI4:
            id_width = self.config.get_xbar_output_id_width()
        else:
            id_width = 0  # AXI-Lite and APB don't have ID

        return Protocol(
            protocol_type=proto_def.protocol,
            data_width=proto_def.data_width,
            addr_width=proto_def.addr_width,
            id_width=id_width,
            user_width=proto_def.user_width or 0,
            max_read_txns=proto_def.max_read_txns or 8,
            max_write_txns=proto_def.max_write_txns or 8,
        )

    def _protocols_equal(self, a: Protocol, b: Protocol) -> bool:
        """Check if two protocols are equivalent (no conversion needed)."""
        return (a.protocol_type, a.data_width, a.addr_width) == (b.protocol_type, b.data_width, b.addr_width)

    TYPE_ABBREV = {
        ConversionType.AXI_DW: "dw",
        ConversionType.AXI_TO_AXI_LITE: "a2l",
        ConversionType.AXI_LITE_DW: "ldw",
        ConversionType.AXI_LITE_TO_APB: "l2apb",
        ConversionType.PASSTHROUGH: "pt",
    }

    def _next_instance_name(self, conv_type: ConversionType, output_name: str) -> str:
        """Generate a unique instance name. Step indices reset per output chain."""
        n = self._step_counter.get(output_name, 0) + 1
        self._step_counter[output_name] = n
        abbrev = self.TYPE_ABBREV.get(conv_type, "conv")
        return f"u_{output_name}_{abbrev}_{n}"

    def _get_step_params(self, conv_type: ConversionType, output: OutputPort) -> Dict:
        """Get additional parameters for a conversion step."""
        if conv_type == ConversionType.AXI_TO_AXI_LITE:
            return {'fall_through': False}

        if conv_type == ConversionType.AXI_LITE_TO_APB:
            enable_pipeline = output.pipeline_stages > 0
            return {
                'pipeline_request': enable_pipeline,
                'pipeline_response': enable_pipeline,
                'address_ranges': output.address_range,
                'base_addr_param': self.config.base_addr_param,
            }

        return {}


def generate_fabric_chains(config: FabricConfig) -> Dict[str, ConversionChain]:
    """
    Convenience function to generate all conversion chains for a fabric.

    Args:
        config: Validated fabric configuration

    Returns:
        Dictionary mapping output names to their conversion chains
    """
    generator = ConversionGraphGenerator(config)
    output_chains = {}

    for output in config.outputs:
        chain = generator.generate_output_chain(output)
        if chain:
            output_chains[output.name] = chain

    return output_chains
