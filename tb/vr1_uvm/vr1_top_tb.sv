//=============================================================================
// vr1_top_tb.sv — VR1 UVM 顶层 tb（D-7 平台骨架片）
// 组成：时钟/复位占位生成 + vr1_if 占位例化 + run_test()
// 状态：DUT（vr1_core）尚未存在（rtl/vr1/core/vr1_core.sv 未建）——
//       本片**不例化 DUT**、不接 filelist/rtl.f；RTL 落地后按 Review G1
//       记录接入（届时补 DUT 例化与接口连接）。
// 判据口径（AGENTS.md §3.1 / ADR-5）：仿真退出码不作判据；
//       判据＝产物证据行（vlog `-- Compiling` 计数 + 段末 `** Error` 行）
//       或 UVM 报告 / 断言 / 覆盖率命中至少其一（红线 R8）。
//=============================================================================
`timescale 1ns/1ps

module vr1_top_tb;
  import uvm_pkg::*;
  import vr1_pkg::*;

  // ---- 时钟/复位（占位：10 ns 周期；频率/复位协议待 spec 冻结后回填）----
  logic clk;
  logic rst_n;

  initial begin
    clk = 1'b0;
    forever #5 clk = ~clk;   // 100 MHz 占位
  end

  initial begin
    rst_n = 1'b0;
    repeat (10) @(posedge clk);
    rst_n = 1'b1;            // 复位释放占位（真复位协议随接口冻结回填）
  end

  // ---- 接口占位例化（仅连接时钟/复位；信号均未驱动）----
  vr1_if u_vr1_if (
    .clk   (clk),
    .rst_n (rst_n)
  );

  // ---- DUT 例化占位：Review G1 接口冻结后接入 vr1_core（当前无 RTL）----

  // ---- UVM 启动（用例由 +UVM_TESTNAME=vr1_smoke_test 选择，见 run_cmd/vr1_flow.do）----
  initial begin
    run_test();
  end
endmodule
