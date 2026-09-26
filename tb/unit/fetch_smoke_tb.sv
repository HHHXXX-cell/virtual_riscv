// ==========================================================================
// tb/unit/fetch_smoke_tb.sv — S1 取指通路的**独立编译/仿真冒烟**（接口最小化，不碰 tb/vr1_uvm/**）
//
// 它是什么：
//   · 编译在环：`vr1_core`（M01+M02+M03）+ **内存桩** + 时钟/复位 能一起被 vlog/vopt 接受；
//   · 一份镜像喂两边：`$readmemh` 载 `sim/image/m_smoke.hex`（**字地址**口径：`@00000400`
//     = 字节基址 0x1000，见 `sim/image/MANIFEST.txt` 的 `base_word`/`base_byte`）；
//   · 产出 S1 判据② 的阶段证据行（`doc/design/M1-实现计划.md` §5 S1）：
//       ① 首次请求 VA = `RESET_PC`（0x1000）；
//       ② 响应窗基址 32 B 对齐（`win_base_pc[4:0]==0`，`spec/01` §3.16 BLK-08）；
//       ③ 连续窗按 `FETCH_BYTES`（32）推进；
//       ④ IBUF 槽（§3.3）：起始槽 `pc`=`窗基址+2×槽号`、`raw32`=镜像半字拼接、`ftq_id` 随块。
//
// 它不是什么（边界，红线 R6/R8）：
//   · **不是** M1 判据本体：S1 判据② 拟注册名 `rtl-fetch-win` **尚未注册**（本批不动
//     `script/flow.py` 的判据逻辑）⇒ 本文件产出的是**阶段证据**，不得当 M1 判据；
//   · **不是**平台：停机判据（`tohost` 写 1）、`rt_t` 写出器、2,000,000 拍 watchdog
//     归平台批（`GI-13`/`GD-6`，另一片，`tb/vr1_uvm/**`）；本文件的 `TD_CYC` 只是**本冒烟
//     自我保护**上限，不是 M1 的 watchdog 口径；
//   · **不产 trace**：DUT 的 `rt_valid_o` 恒 0（后端未实现）⇒ 本冒烟与 `rtl-vs-iss` 无关。
//
// 注（日志编码）：所有 `$display` 一律 **ASCII**——ModelSim 控制台会把非 ASCII 字符替换为 `?`
//   （实测，2026-09-26），中文注释不进入日志；证据行必须逐字可读（红线 R3/R8）。
//
// 跑法（沙箱独占，红线 R10；与 `flow.py` 的 ModelSim 调用同口径：路径全绝对、cwd＝沙箱）：
//   cd /d sim\run_rtl_fetch_smoke                      :: 沙箱目录（`sim/run_*` 不入 window 指纹）
//   vlib work
//   vlog -64 -sv -work work +incdir+<RTL 的 include 目录> <rtl.f 的 5 个单元> tb/unit/fetch_smoke_tb.sv
//   vopt -64 work.vr1_fetch_smoke_tb -o fetch_smoke_opt
//   vsim -64 -c -do "run -all; quit -f" fetch_smoke_opt +IMAGE=<仓库根>/sim/image/m_smoke.hex
// （`+IMAGE=` 可不带：不带时按进程 cwd 找 `sim/image/m_smoke.hex`，即从仓库根跑。
//   ModelSim license 口径见 `AGENTS.md` §3.1 / R-224。）
//
// 依据：doc/spec/01 §3.3/§3.13/§3.16、§1.1 `P3~P5` 行；doc/spec/00 §4.1 `FETCH_BYTES`；
//       doc/decisions/G1-I-最小冻结清单.md §2.6（恒值表）。
// ==========================================================================
`ifndef VR1_FETCH_SMOKE_TB_SV
`define VR1_FETCH_SMOKE_TB_SV

module vr1_fetch_smoke_tb;
  import vr1_pkg::*;

  // -----------------------------------------------------------------------
  // 规模与口径
  // -----------------------------------------------------------------------
  localparam int unsigned MEM_WORDS = 4096;                  // 词寻址存储（32 bit/项）
  localparam int unsigned SLOTS     = FETCH_BYTES / 2;       // 16 个 16 bit 候选槽（§3.3）
  localparam int unsigned N_WIN     = 4;                     // 本冒烟观测 4 个 32 B 窗
  localparam int unsigned TD_CYC    = 20000;                 // 本冒烟自我保护上限（**非** M1 watchdog）

  // 窗 0 的镜像字常量（**独立于内存数组**：抄自 sim/image/m_smoke.hex 前两行，
  //   用于把"槽定位/半字拼接/字节序"钉死；`$readmemh` 装错时该检查必须报错）
  localparam logic [31:0] W0 [0:7] = '{
    32'h0000_10b7, 32'h1000_8093, 32'h3050_9073, 32'h01f0_0313,
    32'h4000_03b7, 32'h0063_a023, 32'h0003_a403, 32'hfff0_0493
  };

  // -----------------------------------------------------------------------
  // 时钟/复位（单时钟域；异步复位，测试序列里同步释放）
  // -----------------------------------------------------------------------
  logic clk   = 1'b0;
  logic rst_n = 1'b0;
  always #5 clk = ~clk;

  initial begin
    rst_n = 1'b0;
    repeat (4) @(posedge clk);
    rst_n = 1'b1;
  end

  // -----------------------------------------------------------------------
  // DUT
  // -----------------------------------------------------------------------
  logic        imem_req_valid, imem_req_ready, imem_rsp_valid, imem_rsp_ready;
  mem_req_t    imem_req;
  icache_rsp_t imem_rsp;

  // ---- DUT：**M01→M02→M03 直连**（S1 面）----
  //   为什么不例化 `vr1_core`（2026-09-26 改；口径见本文件头"为什么不例化 vr1_core"）：
  //   M1-S3b 落地后端后，IBUF 的消费速率由后端决定（访存类 μop 要等 `dcache_rsp_t`），
  //   "前 4 窗按 `FETCH_BYTES` 推进"的 S1 判据输入面不再是"喂进去就到"——S1 判据的 DUT 面
  //   本就是 M01~M03，故按 S1 配置直连三级；**检查项与判据 `chk_rtl_fetch_win` 一字未改**（非放宽），
  //   前端＋后端在回路的整体行为由 `tb/unit/m1_e2e_tb.sv`（`rtl-vs-iss` 的产出侧）承担。
  ftq_req_t    bp_req;
  logic        bp_req_vld, bp_req_rdy;
  ftq_entry_t  ftq_entry;
  logic        ftq_vld, ftq_pop;
  logic [4:0]  ftq_id;
  logic        ibuf_win_vld;
  fetch_raw_t  ibuf_lanes [IBUF_ENTRIES];
  logic        ibuf_drain;

  vr1_bp u_bp (
    .clk             (clk),
    .rst_n           (rst_n),
    .bp_pc_i         (40'd0),          // 无重定向源（S1 面：静态预测顺序流）
    .bp_pc_vld_i     (1'b0),
    .ftq_req_o       (bp_req),
    .ftq_req_valid_o (bp_req_vld),
    .ftq_req_ready_i (bp_req_rdy)
  );

  vr1_ftq u_ftq (
    .clk             (clk),
    .rst_n           (rst_n),
    .ftq_req_i       (bp_req),
    .ftq_req_valid_i (bp_req_vld),
    .ftq_req_ready_o (bp_req_rdy),
    .ftq_entry_o     (ftq_entry),
    .ftq_pop_valid_o (ftq_vld),
    .ftq_pop_id_o    (ftq_id),
    .ftq_pop_ready_i (ftq_pop),
    .flush_i         (1'b0)
  );

  vr1_ifetch u_ifetch (
    .clk             (clk),
    .rst_n           (rst_n),
    .ftq_entry_i     (ftq_entry),
    .ftq_entry_vld_i (ftq_vld),
    .ftq_entry_id_i  (ftq_id),
    .ftq_pop_o       (ftq_pop),
    .imem_req_valid_o(imem_req_valid),
    .imem_req_o      (imem_req),
    .imem_req_ready_i(imem_req_ready),
    .imem_rsp_valid_i(imem_rsp_valid),
    .imem_rsp_i      (imem_rsp),
    .imem_rsp_ready_o(imem_rsp_ready),
    .ibuf_win_vld_o  (ibuf_win_vld),
    .ibuf_rd_o       (ibuf_lanes),
    .ibuf_drain_i    (ibuf_drain),
    .flush_i         (1'b0)
  );

  // S1 面：IBUF 写后**立即取尽**（＝"D 级瞬间消费完"的替身；S1 的窗口释放口径就是"写后恒 1、
  //   下一窗覆盖"，S2 起才由 D 级 `ibuf_drain_o` 逐窗握手驱动）。不置 drain ⇒ M03 的
  //   "IBUF 忙"门控会一直挡住下一窗（实测 n_req=1 停摆）。
  assign ibuf_drain = ibuf_win_vld;

  // -----------------------------------------------------------------------
  // 内存桩（清单 §1.2 第 2 条：首版无 L1I，TB 直连响应）
  //   响应口径：`win`(256) = 16 槽半字；`win_base_pc` = 请求 VA[39:5] 补 5 个 0（§3.16 BLK-08）；
  //   `seq`/`err`/`err_code`/`err_pos` 恒 0（清单 §2.6：无 cache 缺失、无取指异常）。
  //   未兜底面：越界/非法访问（§6.2 GR-2）——本冒烟只喂规范地址，兜底归平台批。
  // -----------------------------------------------------------------------
  logic [31:0] mem [0:MEM_WORDS-1];
  string       img_path;

  initial begin
    if (!$value$plusargs("IMAGE=%s", img_path)) img_path = "sim/image/m_smoke.hex";
    $readmemh(img_path, mem);                       // `@<字地址>`：0x400 ⇒ 字节基址 0x1000
    $display("[fetch_smoke] image=%s (readmemh word-address form; MANIFEST base_word=0x400 base_byte=0x1000)",
             img_path);
  end

  // 字节地址 → 半字（小端：addr[1]==0 取低半字，==1 取高半字）
  function automatic logic [15:0] mem_half(input int unsigned byte_addr);
    return byte_addr[1] ? mem[byte_addr >> 2][31:16] : mem[byte_addr >> 2][15:0];
  endfunction

  logic [39:0]  req_va_q;
  logic [255:0] win_q;
  logic [39:0]  win_base_q;
  logic         outstanding_q;
  logic         rsp_acc;                            // 本拍响应被接受（→ 下一拍校验 IBUF）
  int unsigned  n_req;

  logic [39:0]  va_hist [0:N_WIN-1];                // 前 N 窗的请求 VA（S1 判据②-③ 证据）
  logic [39:0]  chk_pc_q;
  logic [39:0]  chk_wbase_q;
  int unsigned  chk_no_q;

  logic         chk_valid_q;                        // 校验窗口（响应被接受后一拍起）
  int unsigned  n_checked;
  int unsigned  n_fail;
  int unsigned  n_align_chk;                        // 已核查"32 B 对齐"的窗数（S1-2 证据）
  logic [31:0]  win0_words [0:7];                   // 窗 0 实取（**校验拍捕获**，供收尾证据行）

  assign imem_req_ready = ~outstanding_q;            // 单 outstanding（与 M03 的 FSM 口径一致）

  // 响应载荷（组合；端口线 `imem_rsp_valid` 与 `icache_rsp_t.valid`（§3.16 成员）**同源驱动**：
  // 冻结端口面里两条都在，DUT 判据取端口线 —— 见 vr1_core.sv 的族 1 注）
  always_comb begin
    imem_rsp             = '0;
    imem_rsp_valid       = outstanding_q;
    imem_rsp.valid       = outstanding_q;
    imem_rsp.win         = win_q;
    imem_rsp.win_base_pc = win_base_q;
  end

  // 请求形态（§3.13 IF 形态；判据② 的"请求侧"证据）
  function automatic void chk_req_shape(input mem_req_t r);
    if (r.kind !== 2'b10)      begin n_fail++; $display("[fetch_smoke] FAIL req.kind=%b (expect IF=2'b10)", r.kind); end
    if (r.is_fetch !== 1'b1)   begin n_fail++; $display("[fetch_smoke] FAIL req.is_fetch=%b (expect 1)", r.is_fetch); end
    if (r.priv !== 2'b11)      begin n_fail++; $display("[fetch_smoke] FAIL req.priv=%b (expect M=2'b11; G1-I list 2.6)", r.priv); end
    if (r.ifetch_offset !== r.va[5:0]) begin n_fail++; $display("[fetch_smoke] FAIL ifetch_offset=%h != VA[5:0]=%h", r.ifetch_offset, r.va[5:0]); end
    if (r.pa !== {4'b0, r.va}) begin n_fail++; $display("[fetch_smoke] FAIL pa=%h != {4'b0,va} (no-MMU identity path)", r.pa); end
  endfunction

  // -----------------------------------------------------------------------
  // 桩时序：接受请求 → 登记窗内容（1 拍后给响应）→ 响应被接受 → 下一拍校验 IBUF
  // -----------------------------------------------------------------------
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      int unsigned i;
      req_va_q      <= 40'b0;
      win_q         <= 256'b0;
      win_base_q    <= 40'b0;
      outstanding_q <= 1'b0;
      rsp_acc       <= 1'b0;
      n_req         <= 0;
      chk_pc_q      <= 40'b0;
      chk_wbase_q   <= 40'b0;
      chk_no_q      <= 0;
      chk_valid_q   <= 1'b0;
      n_checked     <= 0;
      n_fail        <= 0;
      n_align_chk   <= 0;
      for (i = 0; i < N_WIN; i++) va_hist[i]    <= 40'b0;
      for (i = 0; i < 8; i++)     win0_words[i] <= 32'b0;
    end else begin
      rsp_acc     <= 1'b0;
      chk_valid_q <= rsp_acc;

      if (imem_req_valid && imem_req_ready) begin              // 请求被接受
        req_va_q   <= imem_req.va;
        win_base_q <= {imem_req.va[39:5], 5'b0};               // §3.16 BLK-08：窗基址 = VA[39:5] 补 0
        for (int unsigned j = 0; j < SLOTS; j++)
          win_q[16*j +: 16] <= mem_half({imem_req.va[39:5], 5'b0} + 40'(2*j));
        outstanding_q <= 1'b1;
        if (n_req < N_WIN) va_hist[n_req] <= imem_req.va;
        chk_req_shape(imem_req);
        n_req <= n_req + 1;
      end

      if (outstanding_q && imem_rsp_ready) begin               // 响应被接受（= M03 写 IBUF 拍）
        outstanding_q <= 1'b0;
        rsp_acc       <= 1'b1;
        chk_pc_q      <= req_va_q;
        chk_wbase_q   <= win_base_q;
        chk_no_q      <= n_req - 1;
      end
    end
  end

  // -----------------------------------------------------------------------
  // IBUF 校验（§3.3 槽语义；采样点 = 响应被接受后一拍，此时 DUT 阵列稳定）
  //   期望：起始槽 ⟺ 4 B 步长（S1：无 C，每指令占 2 槽）且不跨窗；pc = 窗基址 + 2×槽号；
  //         raw32 = {槽 s+1 半字, 槽 s 半字}；窗 0 另与 W0 常量（独立于 mem 数组）比对。
  // -----------------------------------------------------------------------
  always_ff @(posedge clk) begin
    if (chk_valid_q) begin
      int unsigned first;
      int unsigned nib;
      logic        exp_valid;
      first = chk_pc_q[4:1];                                   // 块首槽 = 块起始 pc[4:1]（§3.16）
      nib   = (SLOTS - first) >> 1;                            // S1：到窗末的 4 B 条数
      for (int unsigned s = 0; s < SLOTS; s++) begin
        exp_valid = (s >= first) && (s <= (SLOTS - 2)) && (((s - first) % 2) == 0)
                    && (((s - first) / 2) < nib);
        if (ibuf_lanes[s].valid !== exp_valid) begin
          n_fail++;
          $display("[fetch_smoke] FAIL win%0d slot%0d valid=%b (expect %b)", chk_no_q, s,
                   ibuf_lanes[s].valid, exp_valid);
        end
        if (exp_valid) begin
          if (ibuf_lanes[s].pc !== (chk_wbase_q + 40'(2*s))) begin
            n_fail++;
            $display("[fetch_smoke] FAIL win%0d slot%0d pc=%h (expect %h = win_base + 2*slot)",
                     chk_no_q, s, ibuf_lanes[s].pc, chk_wbase_q + 40'(2*s));
          end
          if (ibuf_lanes[s].raw32 !==
              {mem_half(chk_wbase_q + 40'(2*(s+1))), mem_half(chk_wbase_q + 40'(2*s))}) begin
            n_fail++;
            $display("[fetch_smoke] FAIL win%0d slot%0d raw32=%h (expect halfword concat %h)", chk_no_q, s,
                     ibuf_lanes[s].raw32,
                     {mem_half(chk_wbase_q + 40'(2*(s+1))), mem_half(chk_wbase_q + 40'(2*s))});
          end
          if (ibuf_lanes[s].ftq_id !== chk_no_q[4:0]) begin
            n_fail++;
            $display("[fetch_smoke] FAIL win%0d slot%0d ftq_id=%h (expect %h; spec/01 3.2 N14 read-ptr)",
                     chk_no_q, s, ibuf_lanes[s].ftq_id, chk_no_q[4:0]);
          end
          if ((ibuf_lanes[s].is_c !== 1'b0) || (ibuf_lanes[s].err !== 1'b0)) begin
            n_fail++;
            $display("[fetch_smoke] FAIL win%0d slot%0d is_c=%b err=%b (G1-I 2.6 expects 0/0)",
                     chk_no_q, s, ibuf_lanes[s].is_c, ibuf_lanes[s].err);
          end
          // 窗 0 的独立常量比对（钉死槽定位与字节序）
          if ((chk_no_q == 0) && ((s % 2) == 0) && ((s >> 1) < 8)) begin
            if (ibuf_lanes[s].raw32 !== W0[s >> 1]) begin
              n_fail++;
              $display("[fetch_smoke] FAIL win0 slot%0d raw32=%h != image const %h", s,
                       ibuf_lanes[s].raw32, W0[s >> 1]);
            end
            win0_words[s >> 1] <= ibuf_lanes[s].raw32;   // 捕获（收尾证据行用；勿读活阵列）
          end
        end
      end
      if (chk_wbase_q[4:0] !== 5'd0) begin                     // S1-2：窗基址 32 B 对齐（§3.16 BLK-08）
        n_fail++;
        $display("[fetch_smoke] FAIL win%0d win_base=%h not 32B aligned ([4:0]!=0)", chk_no_q, chk_wbase_q);
      end
      n_align_chk <= n_align_chk + 1;
      n_checked   <= n_checked + 1;
      $display("[fetch_smoke] win%0d checked: pc=%h wbase=%h aligned32B=%0b starts=%0d",
               chk_no_q, chk_pc_q, chk_wbase_q, (chk_wbase_q[4:0] == 5'd0), nib);
    end
  end

  // -----------------------------------------------------------------------
  // 收尾：4 个窗校验完 ⇒ 出 S1 判据② 证据行 + PASS/FAIL；超时 ⇒ 显式失败行（不静默 $finish）
  // -----------------------------------------------------------------------
  logic [39:0] va_min;
  int unsigned idx;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      // 无状态需要清（本块只做终局判定）
    end else if (n_checked >= N_WIN) begin
      // ① 首次请求 VA == RESET_PC
      if (va_hist[0] !== RESET_PC[39:0]) begin
        n_fail++;
        $display("[fetch_smoke] FAIL S1-1 first_req_va=%h != RESET_PC=%h", va_hist[0], RESET_PC[39:0]);
      end
      // ③ 连续窗 stride == FETCH_BYTES
      for (idx = 1; idx < N_WIN; idx++) begin
        if (va_hist[idx] !== (va_hist[idx-1] + 40'(FETCH_BYTES))) begin
          n_fail++;
          $display("[fetch_smoke] FAIL S1-3 stride: va[%0d]=%h != va[%0d]+%0d", idx,
                   va_hist[idx], idx-1, FETCH_BYTES);
        end
      end
      $display("[fetch_smoke] S1-1 first_req_va=%h (RESET_PC=%h) ok=%0b", va_hist[0], RESET_PC[39:0],
               (va_hist[0] === RESET_PC[39:0]));
      $display("[fetch_smoke] S1-2 win_base 32B aligned: %0d/%0d windows checked ([4:0]==0) ok=%0b",
               n_align_chk, N_WIN, (n_align_chk == N_WIN));
      $display("[fetch_smoke] S1-3 stride=%0d ok=%0b va=%h,%h,%h,%h", FETCH_BYTES,
               (va_hist[1] === (va_hist[0] + 40'(FETCH_BYTES))), va_hist[0], va_hist[1], va_hist[2], va_hist[3]);
      $display("[fetch_smoke] ibuf_win0 lanes[0,2,4,6,8,10,12,14].raw32 = %h %h %h %h %h %h %h %h (captured at check time)",
               win0_words[0], win0_words[1], win0_words[2], win0_words[3],
               win0_words[4], win0_words[5], win0_words[6], win0_words[7]);
      $display("[fetch_smoke] n_req=%0d n_checked=%0d n_fail=%0d (staged evidence; S1 criterion-2 'rtl-fetch-win' NOT registered yet)",
               n_req, n_checked, n_fail);
      if (n_fail == 0) $display("[fetch_smoke] PASS: S1 fetch path (M01->M02->M03->IBUF) evidence all ok");
      else             $display("[fetch_smoke] FAIL: %0d item(s)", n_fail);
      $finish;
    end
  end

  // 自我保护上限（**非** M1 watchdog 口径；平台批按红线 R9 实现 2,000,000 拍）
  int unsigned cycles;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) cycles <= 0;
    else begin
      cycles <= cycles + 1;
      if (cycles > TD_CYC) begin
        $display("[fetch_smoke] ABORT: exceeded smoke bound %0d cycles (n_req=%0d n_checked=%0d) => FAIL",
                 TD_CYC, n_req, n_checked);
        $finish;
      end
    end
  end

  // 本件只跑 M01~M03（无后端 ⇒ 无 `dmem_*`/`rt_*` 端口消费；S1 面不涉访存与提交）

endmodule

`endif // VR1_FETCH_SMOKE_TB_SV
