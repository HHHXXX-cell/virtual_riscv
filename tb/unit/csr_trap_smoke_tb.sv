// ==========================================================================
// tb/unit/csr_trap_smoke_tb.sv — M17 `vr1_csr` ＋ M18 `vr1_trap` 定向单元冒烟（M1-S3b）
//
// 它是什么：直连 `vr1_csr`（读口/写口/trap 进场/`MRET` 返回）与 `vr1_trap`（`excp_t` 组装 ＋
//   `mtvec` 重定向），逐案喂端口、查**状态变化与输出值**；每案一行证据，末行 `PASS`/`FAIL`。
// 覆盖（口径逐条对 `spec/10` §2/§4.1 与 `spec/01` §3.18/§3.19）：
//   · `mtvec`/`mscratch` 读写往返；`CSRRW` 型（`op=RW`）恒写；
//   · `CSRRS` 型（`op=RS`）**源为 0 ⇒ 不写**（`spec/02` §4.1 AN-07；`csr_wr_en_o=0`）、源非 0 ⇒ 写；
//   · `misa` 只读常量（写忽略）；未实现地址读 0（TODO(G1-F)）；
//   · trap 进场：`mepc←epc`、`mcause←{intr,cause}`、`mtval←tval`、`MPIE←MIE`、`MIE←0`、`MPP←前级`；
//   · `MRET`：`MIE←MPIE`、`MPIE←1`、`MPP←U`、`MPP≠M` ⇒ 清 `MPRV`（ISS-064）；
//   · `vr1_trap`：Direct ⇒ 目标 = `mtvec` 基址；Vectored ＋ 中断 ⇒ 基址 + 4×cause；`flush_all` 同拍。
// 边界（红线 R6/R8）：**不是** M1 判据本体；未实现面（全表/WARL 掩码/S 态委托）在该两模块文件头
//   逐条 TODO(G1-F)，本冒烟不为其产假期望。
// 依据：doc/spec/10 §2/§4.1/§4.3；doc/spec/01 §3.18/§3.19/§3.21；doc/spec/02 §4.3。
// ==========================================================================
`ifndef CSR_TRAP_SMOKE_TB_SV
`define CSR_TRAP_SMOKE_TB_SV

module csr_trap_smoke_tb;
  import vr1_pkg::*;

  localparam logic [11:0] A_MSTATUS = 12'h300, A_MISA = 12'h301, A_MTVEC = 12'h305,
                          A_MSCRATCH = 12'h340, A_MEPC = 12'h341, A_MCAUSE = 12'h342,
                          A_MTVAL = 12'h343;
  localparam logic [1:0] OP_RW = 2'b00, OP_RS = 2'b01;
  localparam logic [63:0] MSTATUS_WMASK = 64'h0000_0000_007E_19AA;   // spec/10 §4.1 最小集

  logic clk = 1'b0, rst_n = 1'b0;
  always #5 clk = ~clk;
  initial begin
    rst_n = 1'b0;
    repeat (4) @(posedge clk);
    rst_n = 1'b1;
  end

  logic [11:0] rd_addr;
  logic [63:0] rd_data;
  csr_wr_t     wr;
  logic [63:0] csr_new;
  logic        wr_en;
  logic        excp_commit;
  logic [39:0] excp_epc, excp_tval;
  logic [3:0]  excp_cause;
  logic        excp_is_intr;
  logic [1:0]  excp_from;
  logic        ret_commit;
  ret_ctrl_t   ret;
  logic [63:0] mtvec_o, mepc_o, mcause_o, mtval_o, mscratch_o, mstatus_o;
  excp_t       excp;
  logic        redirect_vld;
  logic [39:0] redirect_pc;
  logic        flush_all;
  logic [63:0] mstatus_i;

  vr1_csr u_csr (
    .clk (clk), .rst_n (rst_n),
    .csr_addr_i (rd_addr), .csr_rdata_o (rd_data),
    .csr_wr_i (wr), .csr_new_o (csr_new), .csr_wr_en_o (wr_en),
    .excp_commit_i (excp_commit), .excp_epc_i (excp_epc), .excp_cause_i (excp_cause),
    .excp_is_intr_i (excp_is_intr), .excp_tval_i (excp_tval), .excp_from_i (excp_from),
    .ret_commit_i (ret_commit), .ret_o (ret),
    .mtvec_o (mtvec_o), .mepc_o (mepc_o), .mcause_o (mcause_o), .mtval_o (mtval_o),
    .mscratch_o (mscratch_o), .mstatus_o (mstatus_o)
  );

  vr1_trap u_trap (
    .clk (clk), .rst_n (rst_n),
    .exc_vld_i (excp_commit), .exc_code_i (excp_cause), .exc_is_intr_i (excp_is_intr),
    .exc_pc_i (excp_epc), .exc_instr_i (32'hDEAD_BEEF), .exc_priv_i (excp_from),
    .exc_tval_i (excp_tval), .mtvec_i (mtvec_o), .mstatus_i (mstatus_o),
    .ret_i (ret), .excp_o (excp),
    .redirect_vld_o (redirect_vld), .redirect_pc_o (redirect_pc), .flush_all_o (flush_all)
  );

  int unsigned n_fail, n_case;

  task automatic chk64(input string name, input logic [63:0] got, input logic [63:0] exp);
    n_case = n_case + 1;
    if (got !== exp) begin
      n_fail = n_fail + 1;
      $display("[csr_smoke] FAIL case=%s got=%016x exp=%016x", name, got, exp);
    end else begin
      $display("[csr_smoke] case=%s got=%016x exp=%016x ok=1", name, got, exp);
    end
  endtask

  task automatic chk1(input string name, input logic got, input logic exp);
    n_case = n_case + 1;
    if (got !== exp) begin
      n_fail = n_fail + 1;
      $display("[csr_smoke] FAIL case=%s got=%b exp=%b", name, got, exp);
    end else begin
      $display("[csr_smoke] case=%s got=%b exp=%b ok=1", name, got, exp);
    end
  endtask

  // 提交拍 CSR 写（**低电平驱动** ：避开与 always_ff 的采样沿竞争 —— 实测同沿驱动会丢写）
  task automatic do_wr(input logic [11:0] addr, input logic [1:0] op, input logic [63:0] val,
                       input bit chk_new, input logic [63:0] exp_new,
                       input bit chk_en, input logic exp_en);
    @(posedge clk);
    #1;                                        // 沿后（NBA 落定）驱动 ⇒ 整个下一周期稳定
    wr = '0;
    wr.vld = 1'b1; wr.addr = addr; wr.op = op; wr.wdata = val;
    rd_addr = addr;
    #1;                                        // 组合值稳定后核
    if (chk_new) chk64("csr_new", csr_new, exp_new);
    if (chk_en)  chk1("csr_wr_en", wr_en, exp_en);
    if ($test$plusargs("DBG"))
      $display("[dbg] t=%0t do_wr addr=%03x wr_writes=%b mtvec_q=%016x mstatus_q=%016x mscratch_q=%016x",
               $time, addr, u_csr.wr_writes, u_csr.mtvec_q, u_csr.mstatus_q, u_csr.mscratch_q);
    @(posedge clk);                            // 写拍（vld 跨该沿稳定）
    #1;
    wr.vld = 1'b0;
    if ($test$plusargs("DBG"))
      $display("[dbg] t=%0t after_wr mtvec_q=%016x mstatus_q=%016x mscratch_q=%016x",
               $time, u_csr.mtvec_q, u_csr.mstatus_q, u_csr.mscratch_q);
  endtask

  task automatic rd_chk(input string name, input logic [11:0] addr, input logic [63:0] exp);
    @(posedge clk);
    #1;
    rd_addr = addr;
    #1;
    if ($test$plusargs("DBG"))
      $display("[dbg] t=%0t rd name=%s addr=%03x port=%016x fn=%016x",
               $time, name, addr, rd_data, u_csr.csr_rd(addr));
    chk64(name, rd_data, exp);
  endtask

  initial begin
    n_fail = 0; n_case = 0;
    wr = '0; rd_addr = 12'd0; excp_commit = 1'b0; ret_commit = 1'b0;
    excp_epc = 40'd0; excp_tval = 40'd0; excp_cause = 4'd0; excp_is_intr = 1'b0;
    excp_from = 2'b11;
    wait (rst_n === 1'b1);
    repeat (2) @(posedge clk);

    // ---- 复位值（六件全 0，`spec/10` §4.1）----
    rd_chk("rst_mtvec", A_MTVEC, 64'd0);
    rd_chk("rst_mstatus", A_MSTATUS, 64'd0);
    rd_chk("misa_ro_const", A_MISA, MISA_VALUE);
    rd_chk("rst_mepc", A_MEPC, 64'd0);

    // ---- RW 型写（mtvec ← 0x1100；`csr_new_o` 取写后新值）----
    do_wr(A_MTVEC, OP_RW, 64'h1100, 1'b1, 64'h1100, 1'b1, 1'b1);
    rd_chk("mtvec_rdback", A_MTVEC, 64'h1100);

    // ---- RS 型：源为 0 ⇒ 不写（AN-07）；源非 0 ⇒ 写 ----
    do_wr(A_MSCRATCH, OP_RS, 64'd0, 1'b1, 64'd0, 1'b1, 1'b0);
    rd_chk("mscratch_still_0", A_MSCRATCH, 64'd0);
    do_wr(A_MSCRATCH, OP_RW, 64'd5, 1'b1, 64'd5, 1'b1, 1'b1);
    rd_chk("mscratch_rdback_5", A_MSCRATCH, 64'd5);
    do_wr(A_MSCRATCH, OP_RS, 64'd0, 1'b0, 64'd0, 1'b1, 1'b0);   // 纯读（x0 源）⇒ 不写
    rd_chk("mscratch_rs0_keep_5", A_MSCRATCH, 64'd5);

    // ---- `misa` 只读：写忽略 ----
    do_wr(A_MISA, OP_RW, 64'hFFFF_FFFF_FFFF_FFFF, 1'b0, 64'd0, 1'b0, 1'b0);
    rd_chk("misa_write_ignored", A_MISA, MISA_VALUE);

    // ---- trap 进场 6 动作（`spec/10` §2）----
    do_wr(A_MSTATUS, OP_RW, 64'h20008, 1'b0, 64'd0, 1'b0, 1'b0);  // MIE(bit3)=1、MPRV(bit17)=1
    rd_chk("mstatus_before_trap", A_MSTATUS, 64'h20008);
    @(posedge clk);
    #1;
    excp_epc = 40'h1048; excp_cause = 4'd6; excp_tval = 40'h4000_0001;
    excp_is_intr = 1'b0; excp_from = 2'b11; excp_commit = 1'b1;
    @(posedge clk); #1; excp_commit = 1'b0;
    rd_chk("trap_mepc", A_MEPC, 64'h1048);
    rd_chk("trap_mcause", A_MCAUSE, 64'h6);
    rd_chk("trap_mtval", A_MTVAL, 64'h4000_0001);
    // MPIE ← MIE(=1) ⇒ bit7=1；MIE ← 0 ⇒ bit3=0；MPP ← 前级 M ⇒ bit12:11=11；MPRV 保留
    rd_chk("trap_mstatus", A_MSTATUS, 64'h21880);

    // ---- `MRET` 返回（`spec/10` §2；MPP=M ⇒ **不**清 MPRV，锚 ISS-064）----
    @(posedge clk);
    #1;
    ret_commit = 1'b1;
    #1;
    chk64("ret_epc", {24'd0, ret.epc}, 64'h1048);
    chk64("ret_mode", {62'd0, ret.mode}, 64'd3);        // MPP=3 ⇒ 返回 M
    chk1("ret_mprv_clr", ret.mprv_clr, 1'b0);           // MPP=M ⇒ 不清 MPRV
    chk1("ret_vld", ret.vld, 1'b1);
    @(posedge clk); #1; ret_commit = 1'b0;
    // MIE ← MPIE(=1) ⇒ bit3=1；MPIE ← 1；MPP ← U(0)；MPRV 保留（MPP=M）
    rd_chk("mret_mstatus", A_MSTATUS, 64'h20088);

    // ---- `vr1_trap`：Direct 目标 = mtvec 基址（`MODE=0`）----
    @(posedge clk);
    #1;
    excp_cause = 4'd6; excp_is_intr = 1'b0; excp_commit = 1'b1;
    #1;
    chk1("trap_redirect_vld", redirect_vld, 1'b1);
    chk64("trap_redirect_direct", {24'd0, redirect_pc}, 64'h1100);
    chk1("trap_flush_pulse", flush_all, 1'b1);
    chk1("excp_vld", excp.vld, 1'b1);
    chk64("excp_epc", {24'd0, excp.epc}, 64'h1048);
    chk64("excp_cause", {60'd0, excp.cause}, 64'd6);
    chk64("excp_tval", {24'd0, excp.tval}, 64'h4000_0001);
    chk64("excp_to", {62'd0, excp.to}, 64'd3);
    @(posedge clk); #1; excp_commit = 1'b0;

    // ---- `vr1_trap`：Vectored ＋ 中断 ⇒ 基址 + 4×cause ----
    do_wr(A_MTVEC, OP_RW, 64'h1001, 1'b0, 64'd0, 1'b0, 1'b0);   // MODE=1、BASE=0x1000
    @(posedge clk);
    #1;
    excp_cause = 4'd7; excp_is_intr = 1'b1; excp_commit = 1'b1;
    #1;
    chk64("trap_redirect_vectored", {24'd0, redirect_pc}, 64'h101C);   // 0x1000 + 4*7
    chk64("excp_vec_off", {58'd0, excp.vec_off}, 64'd28);
    @(posedge clk); #1; excp_commit = 1'b0;

    // ---- 未实现地址：读 0（TODO(G1-F)）----
    rd_chk("unimpl_read0", 12'hF11, 64'd0);

    repeat (2) @(posedge clk);
    $display("[csr_smoke] cases=%0d n_fail=%0d", n_case, n_fail);
    if (n_fail == 0) $display("[csr_smoke] PASS: M17 CSR R/W + trap entry + MRET + M18 redirect all ok");
    else             $display("[csr_smoke] FAIL: %0d item(s)", n_fail);
    $finish;
  end

  int unsigned cycles;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) cycles <= 0;
    else begin
      cycles <= cycles + 1;
      if (cycles > 20000) begin
        $display("[csr_smoke] ABORT: exceeded bound 20000 cycles (cases=%0d) => FAIL", n_case);
        $finish;
      end
    end
  end

endmodule

`endif // CSR_TRAP_SMOKE_TB_SV
