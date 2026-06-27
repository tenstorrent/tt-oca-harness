# iDMA Wrapper

This component is TT/OCA-owned integration RTL around the vendored PULP iDMA
core. It is not upstream iDMA source.

The RTL in `rtl/` adapts the vendored iDMA blocks to the SMC data accelerator:

- `idma_wrapper.sv` wires the SMC AXI control/master interfaces, clock gating,
  busy/interrupt behavior, and wrapper-level type setup.
- `idma_frontend_wrapper.sv` converts the AXI-Lite control path to the register
  interface and instantiates the generated iDMA frontend/register block
  (`idma_reg64_2d`) plus the iDMA midend.
- `idma_request_manager_wrapper.sv` arbitrates frontend requests to backend
  workers.
- `idma_backend_wrapper.sv` instantiates the vendored iDMA AXI backend and adapts
  its read/write channels to the SMC AXI master path.

The RDL under `vendor/pulp-platform/idma/overlay/rdl/` feeds the SMC top-level
address map, software headers, and documentation (generated outputs land under
`data/registers/`). The RTL CSR implementation compiled by the wrapper comes
from the generated iDMA bundle in
`vendor/pulp-platform/idma/overlay/target/rtl/idma_generated.sv`.

The corresponding iDMA-generated HJSON (`idma_reg64_2d.hjson`) is not currently
accepted by the OpenTitan `regtool --systemrdl` flow used for OpenTitan IPs
without a schema adapter (`clock_primary`/`reset_primary` vs `clocking`, missing
OpenTitan-specific keys such as `cip_id`). Keep the overlay RDL until that
conversion path is explicitly added and validated.
