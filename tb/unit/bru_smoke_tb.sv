// ==========================================================================
// tb/unit/bru_smoke_tb.sv — M1-S3 分支解析单元（M10 `vr1_bru`）的**独立冒烟**（接口最小化）
//
// 它是什么：**直连 `vr1_bru`**，按 `spec/01` §3.11 `disp_x_t`（6 lane）造定向激励，逐条核
//   `spec/01` §3.12 `br_resolve_t` 的九域与 `mispred` 定义式：
//     ① `BEQ` 不跳（`rs1_val≠rs2_val`，预测不跳）⇒ `taken_real=0`、`mispred=0`；
//     ② `BEQ` 跳（`rs1_val==rs2_val`）＋预测不跳 ⇒ `taken_real=1`、`mispred=1`、`target_real=pc+imm`；
//     ③ `BEQ` 跳 ＋ 预测跳且目标一致 ⇒ `mispred=0`（预测命中）；目标不一致 ⇒ `mispred=1`；
//     ④ `JAL`（无条件）＋预测不跳 ⇒ `taken_real=1`、`mispred=1`、目标＝`pc+imm`；
//     ⑤ 负偏移（后向分支）⇒ 目标 40 bit 域内回绕正确；
//     ⑥ 无分支 lane ⇒ **整包为 0**（`valid=0`，不携带未选 lane 载荷）；
//     ⑦ 同拍多分支 lane ⇒ 取 **lane 号最小（最老）** 一条，随流字段（`rob_id`/`pc`/`ckpt_id`/
//        `ftq_id`/`bp_upd_id`/`pred_*`）逐项来自该 lane；
//     ⑧ `bad_va` 与 `is_jalr_ret` 恒 0（清单 §2.6＋首版指令面无 JALR）；
//     ⑨ `x0` 面：`beq x0,x0,+8` 两操作数均为 0 ⇒ 相等 ⇒ 跳（§9.1.3 相等即跳）。
//
// 它不是什么（边界，红线 R6/R8）：
//   · **不是** M1 判据本体（M1 的两条 exit 是 `rtl-compile`／`rtl-vs-iss`）；S3 的判据②（RTL 侧 CSV
//     前缀比对 `pc,binary,gpr`）需执行/提交面 ⇒ 本版**不可达**，本文件产出的是**阶段证据**；
//   · **不覆盖**：`wb_t` 写回（JAL 的 link＝`pc+4`，随 WB 级＝TODO(M1-S3)）、冲刷消费与前端重定向
//     接线（TODO(M1-S3)）、`JALR` 的 `is_jalr_ret` 谓词（首版指令面无 JALR＝TODO(G1-F)）、
//     `bad_va`（无 MMU/PMA 面）；未实现项一律不查、不假设。
//
// 注（日志编码）：所有 `$display` 一律 **ASCII**——ModelSim 控制台会把非 ASCII 替换为 `?`
//   （实测），中文注释不进入日志；证据行必须逐字可读（红线 R3/R8）。
//
// 跑法（沙箱独占，红线 R10；路径全绝对、cwd＝沙箱；与 `flow.py` 的 ModelSim 调用同口径）：
//   cd /d sim\run_rtl_bru_smoke
//   vlib work
//   vlog -64 -sv -work work +incdir+<仓库根>/rtl/vr1/include <filelist/rtl.f 的单元> tb/unit/bru_smoke_tb.sv
//   vopt -64 work.bru_smoke_tb -o bru_opt && vsim -64 -c -do "run -all; quit -f" bru_opt
//
// 依据：doc/spec/01 §3.11/§3.12、§1.1 `E` 行、§5.1/§5.2（`BP1..BP3` 重定向到 `target_real`）；
//       doc/spec/02 §9.1.3（`BEQ`=0x080／`JAL`=0x0A0）、§10.2；doc/decisions/G1-I-最小冻结清单.md
//       §1.1（14 条）／§1.2 第 1/6 条／§2.6；doc/design/M1-实现计划.md §2.1 第 11 行、§2.3 简化 #1/#2。
// ==========================================================================
`ifndef VR1_BRU_SMOKE_TB_SV
`define VR1_BRU_SMOKE_TB_SV

module bru_smoke_tb;
  import vr1_pkg::*;

  localparam int unsigned TD_CYC = 2000;                 // 本冒烟自我保护上限（**非** M1 watchdog 口径）

  logic clk = 1'b0;
  logic rst_n = 1'b0;
  always #5 clk = ~clk;

  disp_x_t      lane [ISSUE_WIDTH];
  br_resolve_t  res;

  int unsigned  n_case;
  int unsigned  n_fail;

  vr1_bru u_dut (
    .clk          (clk),
    .rst_n        (rst_n),
    .disp_i       (lane),
    .br_resolve_o (res)
  );

  // isop 成员编码（spec/02 §9.1；本文件**只引用**，不另赋）
  localparam logic [9:0] ISOP_ADDI = 10'h000;
  localparam logic [9:0] ISOP_BEQ  = 10'h080;
  localparam logic [9:0] ISOP_JAL  = 10'h0A0;
  localparam logic [9:0] ISOP_LW   = 10'h102;

  // -------------------------------------------------------------------------
  // 激励构造
  // -------------------------------------------------------------------------
  task automatic clr_lanes();
    for (int unsigned k = 0; k < ISSUE_WIDTH; k++) lane[k] = '0;
  endtask

  // 造一条 lane 的载荷（只填本冒烟要核的域；未列举域保持 0＝清单 §2.6 的合法 0 值）
  task automatic set_lane(input int unsigned k, input logic [9:0] isop, input logic [63:0] rs1v,
                          input logic [63:0] rs2v, input logic [43:0] imm, input logic [39:0] pc,
                          input logic [7:0] rob, input logic [4:0] ftq, input logic [1:0] ckpt,
                          input logic [7:0] bpu, input logic pred_t, input logic [39:0] pred_tgt,
                          input logic [4:0] rs1a, input logic [4:0] rda);
    lane[k]           = '0;
    lane[k].valid     = 1'b1;
    lane[k].isop      = isop;
    lane[k].rs1_val   = rs1v;
    lane[k].rs2_val   = rs2v;
    lane[k].imm       = imm;
    lane[k].pc        = pc;
    lane[k].rob_id    = rob;
    lane[k].ftq_id    = ftq;
    lane[k].ckpt_id   = ckpt;
    lane[k].bp_upd_id = bpu;
    lane[k].pred_taken  = pred_t;
    lane[k].pred_target = pred_tgt;
    lane[k].rs1_arch    = rs1a;
    lane[k].rd_arch     = rda;
  endtask

  // -------------------------------------------------------------------------
  // 检查：逐域核对 + 打证据行（判据侧的可解析入口）
  //   `exp_all_zero=1` 时要求整包为 0（无分支 lane 的情形）
  // -------------------------------------------------------------------------
  task automatic chk(input string tag, input logic exp_v, input logic exp_tk, input logic exp_mp,
                     input logic [39:0] exp_tgt, input logic [7:0] exp_rob, input logic [4:0] exp_ftq,
                     input logic [1:0] exp_ckpt, input logic [7:0] exp_bpu,
                     input logic exp_all_zero);
    bit ok;
    ok = 1'b1;
    if (exp_all_zero) begin
      if (res !== '0) begin
        ok = 1'b0;
        $display("[bru_smoke] FAIL %s: invalid packet is not all-zero (valid=%b pc=%h)", tag, res.valid, res.pc);
      end
    end else begin
      if (res.valid !== exp_v)     begin ok = 1'b0; $display("[bru_smoke] FAIL %s: valid=%b expect %b", tag, res.valid, exp_v); end
      if (res.taken_real !== exp_tk) begin ok = 1'b0; $display("[bru_smoke] FAIL %s: taken_real=%b expect %b", tag, res.taken_real, exp_tk); end
      if (res.mispred !== exp_mp)  begin ok = 1'b0; $display("[bru_smoke] FAIL %s: mispred=%b expect %b", tag, res.mispred, exp_mp); end
      if (res.target_real !== exp_tgt) begin ok = 1'b0; $display("[bru_smoke] FAIL %s: target_real=%h expect %h", tag, res.target_real, exp_tgt); end
      if (res.rob_id !== exp_rob)  begin ok = 1'b0; $display("[bru_smoke] FAIL %s: rob_id=%h expect %h", tag, res.rob_id, exp_rob); end
      if (res.ftq_id !== exp_ftq)  begin ok = 1'b0; $display("[bru_smoke] FAIL %s: ftq_id=%h expect %h", tag, res.ftq_id, exp_ftq); end
      if (res.ckpt_id !== exp_ckpt) begin ok = 1'b0; $display("[bru_smoke] FAIL %s: ckpt_id=%h expect %h", tag, res.ckpt_id, exp_ckpt); end
      if (res.bp_upd_id !== exp_bpu) begin ok = 1'b0; $display("[bru_smoke] FAIL %s: bp_upd_id=%h expect %h", tag, res.bp_upd_id, exp_bpu); end
    end
    // 恒 0 面（清单 §2.6；每案都核）
    if (res.bad_va !== 1'b0)      begin ok = 1'b0; $display("[bru_smoke] FAIL %s: bad_va=%b expect 0", tag, res.bad_va); end
    if (res.is_jalr_ret !== 1'b0) begin ok = 1'b0; $display("[bru_smoke] FAIL %s: is_jalr_ret=%b expect 0 (no JALR in G1-I 14)", tag, res.is_jalr_ret); end
    n_case = n_case + 1;
    if (!ok) n_fail = n_fail + 1;
    // 证据行（一次判定一行；判据侧按此复核）
    $display("[bru_smoke] case=%0d name=%s valid=%b taken=%b mispred=%b target=%h rob=%h ftq=%h ckpt=%h bpu=%h ok=%b",
             n_case, tag, res.valid, res.taken_real, res.mispred, res.target_real, res.rob_id,
             res.ftq_id, res.ckpt_id, res.bp_upd_id, ok);
  endtask

  // -------------------------------------------------------------------------
  // 定向用例
  // -------------------------------------------------------------------------
  initial begin
    n_case = 0;
    n_fail = 0;
    rst_n  = 1'b0;
    clr_lanes();
    repeat (2) @(posedge clk);
    @(negedge clk); rst_n = 1'b1;

    // ---- 1. BEQ 不跳（rs1≠rs2，预测不跳）⇒ 无误预测 ----
    clr_lanes();
    set_lane(0, ISOP_BEQ, 64'd5, 64'd7, 44'd8, 40'h1030, 8'h07, 5'd2, 2'b00, 8'h00, 1'b0, 40'h0,
             5'd8, 5'd0);
    #1;
    chk("beq_not_taken", 1'b1, 1'b0, 1'b0, 40'h1038, 8'h07, 5'd2, 2'b00, 8'h00, 1'b0);

    // ---- 2. BEQ 跳（rs1==rs2）＋预测不跳 ⇒ 误预测（首版静态预测的常态）----
    clr_lanes();
    set_lane(0, ISOP_BEQ, 64'hffff_ffff_ffff_fff8, 64'hffff_ffff_ffff_fff8, 44'd8, 40'h1030,
             8'h08, 5'd2, 2'b01, 8'h11, 1'b0, 40'h0, 5'd8, 5'd0);
    #1;
    chk("beq_taken_pred_nt", 1'b1, 1'b1, 1'b1, 40'h1038, 8'h08, 5'd2, 2'b01, 8'h11, 1'b0);

    // ---- 3. BEQ 跳 ＋ 预测跳且目标一致 ⇒ 预测命中（mispred=0）----
    clr_lanes();
    set_lane(0, ISOP_BEQ, 64'd9, 64'd9, 44'd8, 40'h1030, 8'h09, 5'd3, 2'b10, 8'h22, 1'b1, 40'h1038,
             5'd9, 5'd0);
    #1;
    chk("beq_taken_pred_hit", 1'b1, 1'b1, 1'b0, 40'h1038, 8'h09, 5'd3, 2'b10, 8'h22, 1'b0);

    // ---- 4. BEQ 跳 ＋ 预测跳但目标不一致 ⇒ 误预测（§3.12 第二合取项）----
    clr_lanes();
    set_lane(0, ISOP_BEQ, 64'd9, 64'd9, 44'd8, 40'h1030, 8'h0a, 5'd3, 2'b00, 8'h00, 1'b1, 40'h1040,
             5'd9, 5'd0);
    #1;
    chk("beq_taken_pred_tgt_miss", 1'b1, 1'b1, 1'b1, 40'h1038, 8'h0a, 5'd3, 2'b00, 8'h00, 1'b0);

    // ---- 5. JAL（无条件）＋预测不跳 ⇒ 误预测；目标＝pc+imm ----
    clr_lanes();
    set_lane(0, ISOP_JAL, 64'd0, 64'd0, 44'd8, 40'h103C, 8'h0b, 5'd4, 2'b00, 8'h00, 1'b0, 40'h0,
             5'd0, 5'd16);
    #1;
    chk("jal_pred_nt", 1'b1, 1'b1, 1'b1, 40'h1044, 8'h0b, 5'd4, 2'b00, 8'h00, 1'b0);

    // ---- 6. JAL ＋ 预测跳且目标一致 ⇒ 预测命中 ----
    clr_lanes();
    set_lane(0, ISOP_JAL, 64'd0, 64'd0, 44'd8, 40'h103C, 8'h0c, 5'd4, 2'b00, 8'h00, 1'b1, 40'h1044,
             5'd0, 5'd16);
    #1;
    chk("jal_pred_hit", 1'b1, 1'b1, 1'b0, 40'h1044, 8'h0c, 5'd4, 2'b00, 8'h00, 1'b0);

    // ---- 7. 负偏移（后向分支）：目标 40 bit 域内回绕 ----
    clr_lanes();
    set_lane(0, ISOP_BEQ, 64'd3, 64'd3, 44'hffff_ffff_ff8, 40'h2000, 8'h0d, 5'd5, 2'b00, 8'h00,
             1'b0, 40'h0, 5'd9, 5'd0);
    #1;
    chk("beq_backward_neg8", 1'b1, 1'b1, 1'b1, 40'h1ff8, 8'h0d, 5'd5, 2'b00, 8'h00, 1'b0);

    // ---- 8. 无分支 lane ⇒ 整包为 0 ----
    clr_lanes();
    set_lane(0, ISOP_ADDI, 64'd1, 64'd0, 44'd4, 40'h1004, 8'h31, 5'd7, 2'b11, 8'hff, 1'b0, 40'h0,
             5'd1, 5'd1);
    set_lane(1, ISOP_LW, 64'd7, 64'd0, 44'd0, 40'h1018, 8'h32, 5'd7, 2'b00, 8'h00, 1'b0, 40'h0,
             5'd7, 5'd8);
    #1;
    chk("no_branch_lane_all_zero", 1'b0, 1'b0, 1'b0, 40'h0, 8'h0, 5'd0, 2'b00, 8'h00, 1'b1);

    // ---- 9. 同拍多分支 lane ⇒ 取最老（lane 号最小）的那条，随流字段来自该 lane ----
    clr_lanes();
    set_lane(0, ISOP_ADDI, 64'd1, 64'd0, 44'd4, 40'h1000, 8'h40, 5'd0, 2'b00, 8'h00, 1'b0, 40'h0,
             5'd1, 5'd1);
    set_lane(1, ISOP_BEQ, 64'd1, 64'd2, 44'hfff_ffff_fff8, 40'h3000, 8'h41, 5'd9, 2'b10, 8'haa,
             1'b0, 40'h0, 5'd1, 5'd0);                       // 不跳（1≠2），但仍是 lane1 被选中
    set_lane(2, ISOP_JAL, 64'd0, 64'd0, 44'd16, 40'h3010, 8'h42, 5'd10, 2'b00, 8'h00, 1'b0, 40'h0,
             5'd0, 5'd1);
    #1;
    chk("oldest_branch_lane1", 1'b1, 1'b0, 1'b0, 40'h2ff8, 8'h41, 5'd9, 2'b10, 8'haa, 1'b0);

    // ---- 10. x0 面：beq x0,x0,+8（两操作数均为 0）⇒ 相等 ⇒ 跳 ----
    clr_lanes();
    set_lane(0, ISOP_BEQ, 64'd0, 64'd0, 44'd8, 40'h1000, 8'h50, 5'd1, 2'b00, 8'h00, 1'b0, 40'h0,
             5'd0, 5'd0);
    #1;
    chk("beq_x0_eq_x0_taken", 1'b1, 1'b1, 1'b1, 40'h1008, 8'h50, 5'd1, 2'b00, 8'h00, 1'b0);

    // ---- 11. 清激励 ⇒ 整包为 0（无 lane 有效）----
    clr_lanes();
    #1;
    chk("all_lanes_invalid_all_zero", 1'b0, 1'b0, 1'b0, 40'h0, 8'h0, 5'd0, 2'b00, 8'h00, 1'b1);

    // ---- 收尾 ----
    $display("[bru_smoke] total cases=%0d n_fail=%0d", n_case, n_fail);
    if (n_fail == 0)
      $display("[bru_smoke] PASS: BRU BEQ/JAL resolve + br_resolve_t (incl. mispred formula, oldest-lane pick) all ok");
    else
      $display("[bru_smoke] FAIL: %0d item(s) over %0d cases", n_fail, n_case);
    $finish;
  end

  // 自我保护上限（**非** M1 watchdog 口径）
  int unsigned cycles;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) cycles <= 0;
    else begin
      cycles <= cycles + 1;
      if (cycles > TD_CYC) begin
        $display("[bru_smoke] ABORT: exceeded smoke bound %0d cycles => FAIL", TD_CYC);
        $finish;
      end
    end
  end

endmodule

`endif // VR1_BRU_SMOKE_TB_SV
