#!/bin/bash
# Generate I3C CSR files from RDL
# Set the OCH_ROOT environment variable prior to running this script
# Usage: OCH_ROOT=/path/to/tt-oca-hw ./generate_register_files.sh

if [ -z "$OCH_ROOT" ]; then
    echo "Error: OCH_ROOT environment variable is not set"
    echo "Please set it to the tt-oca-hw root directory"
    exit 1
fi

# Directories
REGISTER_ROOT=$(pwd)
OUTPUT_DIR=$REGISTER_ROOT/../../csr

echo "Generating I3C CSR files..."
echo "OCH_ROOT: $OCH_ROOT"
echo "REGISTER_ROOT: $REGISTER_ROOT"
echo "OUTPUT_DIR: $OUTPUT_DIR"

# Create output directories
mkdir -p $OUTPUT_DIR

# Generate RTL using passthrough interface (compatible with i3c.sv)
# The passthrough interface creates s_cpuif_* signals that the i3c.sv module expects
# Use --default-reset rst to match the original I3CCSR module interface
# (The actual reset logic uses hwif_in.rst_ni; the port is just for interface compatibility)
# Use --type-style hier to match the original i3c-core type naming
echo "Generating I3CCSR RTL with passthrough interface..."
peakrdl regblock $OCH_ROOT/tools/reg_flow/regblock_udps.rdl \
    "$REGISTER_ROOT/registers.rdl" \
    -o $OUTPUT_DIR \
    --cpuif passthrough \
    --default-reset rst \
    --type-style hier \
    --module-name I3CCSR \
    --package-name I3CCSR_pkg \
    $PEAKRDL_PARAMS

if [ $? -ne 0 ]; then
    echo "Error: Failed to generate RTL"
else
    # Post-process generated SystemVerilog files
    # This converts unpacked structs to packed (required for synthesis)
    # and adds i3c_sva.svh include with assertion
    echo "Post-processing generated SystemVerilog files..."
    python3 $REGISTER_ROOT/scripts/rdl_post_process.py $OUTPUT_DIR/I3CCSR.sv
    python3 $REGISTER_ROOT/scripts/rdl_post_process.py $OUTPUT_DIR/I3CCSR_pkg.sv

    echo ""
    echo "I3C CSR generation complete!"
    echo ""
    echo "Generated files:"
    echo "  RTL:             $OUTPUT_DIR/I3CCSR.sv"
    echo "  Package:         $OUTPUT_DIR/I3CCSR_pkg.sv"
fi
