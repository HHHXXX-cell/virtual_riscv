//=============================================================================
// vr1_agent.sv — VR1 UVM agent 骨架（D-7 平台骨架片·占位）
// 基点：uvm_agent（uvm_component 派生链）；本片 build/connect 为空实现。
// 后续接入点：virtual vr1_if 句柄、driver/monitor/sequencer（待接口冻结）。
//=============================================================================
`ifndef VR1_AGENT_SV
`define VR1_AGENT_SV

class vr1_agent extends uvm_agent;
  `uvm_component_utils(vr1_agent)

  function new(string name = "vr1_agent", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    // D-7 占位：不创建子组件（无 DUT、接口未冻结）
  endfunction

  virtual function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    // D-7 占位：无连接
  endfunction
endclass

`endif
