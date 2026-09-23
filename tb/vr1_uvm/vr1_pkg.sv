//=============================================================================
// vr1_pkg.sv — VR1 UVM 平台包（D-7 骨架片）
// 聚合顺序：uvm 宏 → agent → scoreboard → env → smoke_test（类间引用按此序满足）
// 本片为最小可编译集；接口冻结（Review G1）后按需扩展 cfg/typedef 面。
//=============================================================================
`ifndef VR1_PKG_SV
`define VR1_PKG_SV

package vr1_pkg;
  import uvm_pkg::*;
  `include "uvm_macros.svh"

  `include "vr1_agent.sv"
  `include "vr1_scoreboard.sv"
  `include "vr1_env.sv"
  `include "vr1_smoke_test.sv"
endpackage

`endif
