//=============================================================================
// filelist/tb.f — VR1 UVM 平台编译单元清单（D-7 平台骨架片）
// 路径一律相对仓库根（vlog 从仓库根调用；见 run_cmd/vr1_flow.do）
// 分层（本表为编译单元层；环境/用例在 pkg 层内聚合）：
//   单元1  vr1_pkg.sv     —— UVM 包（`include 聚合 agent/scoreboard/env/smoke_test）
//   单元2  vr1_if.sv      —— DUT↔TB 接口骨架（spec/01 §3 接口族占位）
//   单元3  vr1_top_tb.sv  —— 顶层 tb（时钟/复位 + run_test）
// 注意：本表**不含 rtl/**（RTL 尚未存在；接入时另加 filelist/rtl.f）
//=============================================================================
+incdir+tb/vr1_uvm

tb/vr1_uvm/vr1_pkg.sv
tb/vr1_uvm/vr1_if.sv
tb/vr1_uvm/vr1_top_tb.sv
