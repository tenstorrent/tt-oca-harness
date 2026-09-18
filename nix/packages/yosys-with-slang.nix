# Include yosys-slang plugin for SystemVerilog support
{
  yosys,
  yosys-slang,
  ...
}:
yosys.withPlugins [yosys-slang]
