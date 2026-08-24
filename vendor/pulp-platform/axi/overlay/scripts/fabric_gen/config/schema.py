# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Pydantic models for fabric generator YAML schema validation."""
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class ProtocolType(str, Enum):
    """Supported protocol types."""
    AXI4 = "AXI4"
    AXI4_LITE = "AXI4_LITE"
    APB4 = "APB4"


# Protocol hierarchy: higher number = more capable
PROTOCOL_HIERARCHY = {
    ProtocolType.AXI4: 3,
    ProtocolType.AXI4_LITE: 2,
    ProtocolType.APB4: 1,
}


class ProtocolDef(BaseModel):
    """Protocol definition with bus parameters."""
    protocol: ProtocolType
    data_width: int = Field(ge=8, le=1024)
    addr_width: int = Field(ge=12, le=64)
    id_width: Optional[int] = Field(default=None, ge=1, le=32)
    user_width: Optional[int] = Field(default=1, ge=0, le=32)
    max_read_txns: Optional[int] = Field(default=8, ge=1, le=256)
    max_write_txns: Optional[int] = Field(default=8, ge=1, le=256)

    @field_validator('data_width')
    @classmethod
    def validate_data_width(cls, v: int) -> int:
        """Ensure data width is a power of 2."""
        if v & (v - 1) != 0:
            raise ValueError(f"data_width must be power of 2, got {v}")
        return v



RESERVED_SV_KEYWORDS = frozenset({
    # Port direction / signal types
    'input', 'output', 'inout', 'wire', 'reg', 'logic', 'tri',
    # Module structure
    'module', 'endmodule', 'package', 'endpackage', 'interface', 'endinterface',
    'program', 'endprogram', 'class', 'endclass',
    # Data declarations
    'parameter', 'localparam', 'typedef', 'struct', 'union', 'enum', 'packed',
    'integer', 'int', 'bit', 'byte', 'shortint', 'longint', 'real', 'realtime',
    'time', 'string', 'void',
    # Procedural blocks
    'always', 'always_comb', 'always_ff', 'always_latch', 'initial', 'final',
    'begin', 'end', 'fork', 'join', 'join_any', 'join_none',
    # Continuous assignment
    'assign', 'force', 'release',
    # Generate
    'generate', 'endgenerate', 'genvar',
    # Control flow
    'if', 'else', 'case', 'casex', 'casez', 'endcase', 'for', 'foreach',
    'while', 'do', 'repeat', 'forever', 'break', 'continue', 'return',
    # Instantiation / hierarchy
    'function', 'endfunction', 'task', 'endtask',
    # System tasks / keywords
    'import', 'export', 'automatic', 'static', 'virtual', 'local', 'protected',
    'default', 'this', 'super', 'null',
})


def validate_sv_identifier(v: str) -> str:
    """Ensure name is a valid SystemVerilog identifier."""
    if v.lower() in RESERVED_SV_KEYWORDS:
        raise ValueError(f"'{v}' is a reserved SystemVerilog keyword")
    return v


class AddressRange(BaseModel):
    """Address range definition for output ports."""
    name: str = Field(default="", description="Semantic name for this address range")
    base: int = Field(default=0, ge=0, description="Base address (literal). Ignored if base_expr is set.")
    size: int = Field(default=0, ge=0, description="Size in bytes (literal). Ignored if end_expr is set; "
                                                   "required > 0 when end_expr is not set.")
    # Optional parameter-expression overrides for generating parameterized address maps.
    # When set, the literal SV expression is emitted verbatim in the AddrMap rule
    # instead of the numeric base/size. This lets a range depend on module parameters.
    base_expr: Optional[str] = Field(default=None, description="SV expression for start_addr (overrides base)")
    end_expr: Optional[str] = Field(default=None, description="SV expression for end_addr (overrides base+size)")
    target_slave: Optional[str] = Field(default=None, description="SV expression for idx override")
    tile_relative: bool = Field(default=False,
                                description="When true and no base_expr/end_expr, shift base/end by FabricConfig.base_addr_param at emission")

    @model_validator(mode='after')
    def validate_size_or_end_expr(self) -> 'AddressRange':
        """Require size > 0 unless end_expr is provided."""
        if self.size <= 0 and not self.end_expr:
            raise ValueError("size must be > 0 unless end_expr is set")
        return self

    @property
    def end(self) -> int:
        """Return the end address (exclusive). Only meaningful when base_expr/end_expr are absent."""
        return self.base + self.size

    def overlaps(self, other: 'AddressRange') -> bool:
        """Check if this range overlaps with another (literal ranges only)."""
        if self.base_expr or self.end_expr or other.base_expr or other.end_expr:
            return False
        return self.base < other.end and other.base < self.end


class FabricSettings(BaseModel):
    """Global fabric settings."""
    xbar_protocol: str = Field(default="axi", pattern=r"^(axi|axi_lite)$")
    max_outstanding_txns: int = Field(default=8, ge=1, le=256)
    pipeline_stages: int = Field(default=1, ge=0, le=4)
    fall_through: bool = Field(default=False)
    atop: bool = Field(default=False, description="Enable atomic operations")


class InputPort(BaseModel):
    """Input port (manager/initiator) definition."""
    name: str = Field(min_length=1, pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    protocol: str = Field(description="Reference to protocols dict")
    id_width: Optional[int] = Field(default=None, ge=1, le=32)
    paths: Optional[List[int]] = Field(default=None, description="Output indices this input can reach")

    _validate_name = field_validator('name')(validate_sv_identifier)


class OutputPort(BaseModel):
    """Output port (subordinate/target) definition."""
    name: str = Field(min_length=1, pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    protocol: str = Field(description="Reference to protocols dict")
    address_range: Dict[str, AddressRange] = Field(min_length=1)
    pipeline_stages: int = Field(default=0, ge=0, le=4)

    _validate_name = field_validator('name')(validate_sv_identifier)


class ParameterDef(BaseModel):
    """Module-level SystemVerilog parameter to emit on the generated fabric module."""
    name: str = Field(min_length=1, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    type: str = Field(default="logic [55:0]", description="SV type of the parameter")
    default: str = Field(default="'0", description="SV default value expression")

    _validate_name = field_validator('name')(validate_sv_identifier)


class FabricConfig(BaseModel):
    """Top-level fabric configuration."""
    name: str = Field(min_length=1, pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    description: Optional[str] = Field(default="")
    fabric: FabricSettings = Field(default_factory=FabricSettings)
    protocols: Dict[str, ProtocolDef]
    inputs: List[InputPort]
    outputs: List[OutputPort]
    connectivity: Optional[Dict[str, List[str]]] = Field(default=None)
    # Optional module-level parameters to emit on the generated fabric module.
    # Used to parameterize the AddrMap (e.g. a tile base address).
    parameters: List[ParameterDef] = Field(default_factory=list,
                                           description="Extra module-level parameters to emit")
    base_addr_param: Optional[str] = Field(default=None,
                                           description="Name of a parameter used to shift tile_relative ranges at emission")

    @model_validator(mode='after')
    def validate_protocol_references(self) -> 'FabricConfig':
        """Validate that all protocol references exist."""
        for inp in self.inputs:
            if inp.protocol not in self.protocols:
                raise ValueError(f"Input '{inp.name}' references undefined protocol '{inp.protocol}'")
        for out in self.outputs:
            if out.protocol not in self.protocols:
                raise ValueError(f"Output '{out.name}' references undefined protocol '{out.protocol}'")
        return self

    @model_validator(mode='after')
    def validate_connectivity(self) -> 'FabricConfig':
        """Validate connectivity matrix references and coverage."""
        if self.connectivity:
            input_names = {inp.name for inp in self.inputs}
            output_names = {out.name for out in self.outputs}

            # Check all referenced names exist
            for inp_name, out_list in self.connectivity.items():
                if inp_name not in input_names:
                    raise ValueError(f"Connectivity references undefined input '{inp_name}'")
                for out_name in out_list:
                    if out_name not in output_names:
                        raise ValueError(f"Connectivity references undefined output '{out_name}'")

            # Check all inputs have connectivity defined
            missing_inputs = input_names - set(self.connectivity.keys())
            if missing_inputs:
                raise ValueError(
                    f"Inputs missing from connectivity: {', '.join(sorted(missing_inputs))}. "
                    f"All inputs must have at least one output connection."
                )

            # Check no input has empty connectivity
            for inp_name, out_list in self.connectivity.items():
                if not out_list:
                    raise ValueError(
                        f"Input '{inp_name}' has empty connectivity list. "
                        f"All inputs must connect to at least one output."
                    )
        return self

    @model_validator(mode='after')
    def validate_address_ranges_no_overlap(self) -> 'FabricConfig':
        """Check for overlapping address ranges between outputs.

        Ranges with parameterized base_expr/end_expr overrides are skipped
        (their values are only known at SV elaboration time).
        """
        all_ranges: List[tuple] = []
        for out in self.outputs:
            for range_name, addr_range in out.address_range.items():
                all_ranges.append((f"{out.name}.{range_name}", addr_range))

        for i, (name1, range1) in enumerate(all_ranges):
            for name2, range2 in all_ranges[i+1:]:
                if range1.overlaps(range2):
                    raise ValueError(
                        f"Address ranges overlap: {name1} [0x{range1.base:x}-0x{range1.end:x}] "
                        f"and {name2} [0x{range2.base:x}-0x{range2.end:x}]"
                    )
        return self

    @model_validator(mode='after')
    def validate_address_ranges_fit_decode_width(self) -> 'FabricConfig':
        """Ensure all output address ranges fit in crossbar decode address width.

        Ranges with parameterized base_expr/end_expr overrides are skipped
        (their values are only known at SV elaboration time).
        """
        if not self.inputs:
            return self

        xbar_addr_width = max(self.get_input_protocol(inp).addr_width for inp in self.inputs)
        addr_limit = 1 << xbar_addr_width

        for out in self.outputs:
            for range_name, addr_range in out.address_range.items():
                if addr_range.base_expr or addr_range.end_expr:
                    continue
                if addr_range.base >= addr_limit or addr_range.end > addr_limit:
                    raise ValueError(
                        f"Address range {out.name}.{range_name} "
                        f"[0x{addr_range.base:x}-0x{addr_range.end:x}] exceeds crossbar "
                        f"decode width ({xbar_addr_width} bits)"
                    )
        return self

    @model_validator(mode='after')
    def validate_base_addr_param(self) -> 'FabricConfig':
        """If any range uses tile_relative, the fabric must declare base_addr_param."""
        for out in self.outputs:
            for range_name, ar in out.address_range.items():
                if ar.tile_relative and not self.base_addr_param:
                    raise ValueError(
                        f"{out.name}.{range_name} is tile_relative but fabric "
                        f"config has no base_addr_param declared"
                    )
        if self.base_addr_param:
            param_names = {p.name for p in self.parameters}
            if self.base_addr_param not in param_names:
                raise ValueError(
                    f"base_addr_param '{self.base_addr_param}' not found in parameters list"
                )
        return self

    def get_protocol(self, name: str) -> ProtocolDef:
        """Get a protocol definition by name."""
        return self.protocols[name]

    def get_input_protocol(self, inp: InputPort) -> ProtocolDef:
        """Get the protocol for an input port."""
        return self.protocols[inp.protocol]

    def get_output_protocol(self, out: OutputPort) -> ProtocolDef:
        """Get the protocol for an output port."""
        return self.protocols[out.protocol]

    def get_connectivity_matrix(self) -> List[List[bool]]:
        """Return the full connectivity matrix."""
        num_inputs = len(self.inputs)
        num_outputs = len(self.outputs)

        if self.connectivity:
            output_name_to_idx = {out.name: j for j, out in enumerate(self.outputs)}
            matrix = [[False] * num_outputs for _ in range(num_inputs)]
            for i, inp in enumerate(self.inputs):
                for out_name in self.connectivity.get(inp.name, []):
                    matrix[i][output_name_to_idx[out_name]] = True
            return matrix

        if self.inputs and self.inputs[0].paths is not None:
            matrix = [[False] * num_outputs for _ in range(num_inputs)]
            for i, inp in enumerate(self.inputs):
                for out_idx in (inp.paths or []):
                    if out_idx < num_outputs:
                        matrix[i][out_idx] = True
            return matrix

        return [[True] * num_outputs for _ in range(num_inputs)]

    def get_max_input_id_width(self, log_duplicates: bool = False) -> int:
        """Get maximum ID width across all inputs.

        Priority: input.id_width > protocol.id_width > 0 (fallback)

        Args:
            log_duplicates: If True, print INFO message when both input and protocol
                            specify id_width (input takes priority)
        """
        max_id = 0
        for inp in self.inputs:
            proto = self.get_input_protocol(inp)
            # Check for duplicate specification
            if log_duplicates and inp.id_width is not None and proto.id_width is not None:
                print(f"INFO: Input '{inp.name}' has id_width={inp.id_width}, "
                      f"protocol '{inp.protocol}' also has id_width={proto.id_width}. "
                      f"Using input id_width={inp.id_width}.")
            # Priority: input > protocol > 0
            id_width = inp.id_width if inp.id_width is not None else (proto.id_width or 0)
            max_id = max(max_id, id_width)
        return max_id

    def get_xbar_output_id_width(self) -> int:
        """Get the output ID width after crossbar (input ID + log2(num_inputs))."""
        import math
        max_input_id = self.get_max_input_id_width()
        num_inputs = len(self.inputs)
        id_extension = max(1, math.ceil(math.log2(num_inputs))) if num_inputs > 1 else 0
        return max_input_id + id_extension

    def get_total_address_rules(self) -> int:
        """Count total number of address rules across all outputs."""
        return sum(len(out.address_range) for out in self.outputs)
