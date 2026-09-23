//=============================================================================
// vr1_env.sv — VR1 UVM env 骨架（D-7 平台骨架片·占位）
// 基点：uvm_env（uvm_component 派生链）；本片 build/connect 为空实现。
// 后续接入点：例化 vr1_agent 与 vr1_scoreboard 并连接（接口冻结后）。
//=============================================================================
`ifndef VR1_ENV_SV
`define VR1_ENV_SV

class vr1_env extends uvm_env;
  `uvm_component_utils(vr1_env)

  function new(string name = "vr1_env", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    // D-7 占位：不创建 agent/scoreboard（无 DUT）
  endfunction

  virtual function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    // D-7 占位：无连接
  endfunction
endclass

`endif
