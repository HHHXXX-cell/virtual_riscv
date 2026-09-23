//=============================================================================
// vr1_scoreboard.sv — VR1 UVM scoreboard 骨架（D-7 平台骨架片·占位）
// 基点：uvm_scoreboard（uvm_component 派生链）；本片 build/connect 为空实现。
// 后续接入点：ISS-vs-RTL 逐指令 trace 比对列（比对口径须先经评审，规则 14）。
//=============================================================================
`ifndef VR1_SCOREBOARD_SV
`define VR1_SCOREBOARD_SV

class vr1_scoreboard extends uvm_scoreboard;
  `uvm_component_utils(vr1_scoreboard)

  function new(string name = "vr1_scoreboard", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    // D-7 占位：无 TLM 端口、无比对逻辑
  endfunction

  virtual function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    // D-7 占位：无连接
  endfunction
endclass

`endif
