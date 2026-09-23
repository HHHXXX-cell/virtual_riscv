//=============================================================================
// vr1_smoke_test.sv — VR1 冒烟用例骨架（D-7 平台骨架片）
// 基点：uvm_test（uvm_component 派生链）；本片只做 uvm_info 与 phase 收放。
// 选择方式：+UVM_TESTNAME=vr1_smoke_test（见 run_cmd/vr1_flow.do）。
//=============================================================================
`ifndef VR1_SMOKE_TEST_SV
`define VR1_SMOKE_TEST_SV

class vr1_smoke_test extends uvm_test;
  `uvm_component_utils(vr1_smoke_test)

  function new(string name = "vr1_smoke_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    `uvm_info("VR1_SMOKE", "vr1_smoke_test: build_phase 到达（平台骨架占位，无 DUT、无激励）", UVM_LOW)
  endfunction

  virtual task run_phase(uvm_phase phase);
    phase.raise_objection(this);
    `uvm_info("VR1_SMOKE", "vr1_smoke_test: run_phase 占位执行（无 DUT；判据未触及）", UVM_LOW)
    phase.drop_objection(this);
  endtask
endclass

`endif
