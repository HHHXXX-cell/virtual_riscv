// ==========================================================================
// tb/unit/m1_e2e_tb.sv — M1 端到端冒烟：`vr1_core` ＋ 内存桩 ＋ `rt_t` 写出器
//                        （跑真镜像 `sim/image/m_smoke.hex` 的 30 条退休，产 RTL 侧 CSV）
//
// 它是什么：
//   · 例化 **DUT（`vr1_core`，G1-I 冻结端口面）＋ 内存桩 ＋ `tb/unit/rt_t_trace_writer.sv`**；
//   · 一份镜像喂两边：`$readmemh` 载 `sim/image/m_smoke.hex`（**字地址**口径：`@00000400`
//     = 字节基址 0x1000），取指窗与数据访存都从同一份数组取；
//   · **数据窗预载（`+DATA=<file>`）**——2026-09-26 心跳第 6 轮加（`doc/process/ledger.json`
//     ISS-126 机制件，用于 `rv64ui-p-lw/p-sw` 这类 `.data` 非全 0 的测试「可判」）：
//     文件为 `$readmemh` **字地址**形式、地址**相对 `DRAM_BASE`**（`@00000000` = 数据窗首字），
//     由 `sw/tests/build_rv64ui.py` 从**同一份 ELF** 的 `.tohost`/`.data` 段机械派生
//     （`<name>.data.hex`；窗口/条数/md5 记 `sim/image/rv64ui/MANIFEST.json`）。
//     不给 `+DATA=` ⇒ 数据窗恒零填充（与首版口径逐字相同，既有 smoke 行为不变）。
//     **本件只是机制**：等价性（数据窗＝镜像数据段）仍由 MANIFEST 的 md5／窗口与
//     `flow.py check-one m2-rv64ui` 的判据面核，本 TB 不产任何"通过"结论（红线 R6/R8）。
//   · 产出 RTL 侧 trace CSV（`+RT_T_CSV=` 指定路径），供
//     `python iss/tools/trace_compare.py sim/golden/iss_smoke.csv <rtl_side.csv>` 比对；
//   · 停机判据 = 写出器对 `tohost`（0x4000_0010）store 的 `mem_v && mem_wr && mem_addr` 判定
//     （riscv-tests 语义；`mem_wdata==1` ⇒ PASS），watchdog = 2,000,000 拍（红线 R9）。
//
// 内存桩口径（**首版无 L1I/L1D、无 LQ/SQ**，清单 §1.2 第 2 条 ＋ 计划 §2.3 简化 #3）：
//   · 取指：`imem_req_ready=1`；对每次请求锁存"VA[39:5] 对齐的 32 B 窗"，并在 DUT 就绪时
//     （`imem_rsp_ready`）给出 `icache_rsp_t`（`win` ＋ `win_base_pc`；`seq`/`err*` 恒 0）；
//     **保持到被接受**（DUT 冲刷后重请求会覆盖内容 ⇒ 不出现"旧窗喂新请求"）。
//   · 访存：load 请求 ⇒ 回 `dcache_rsp_t.data` ＝ **`va[2:0]` 所在 8 B 对齐双字**（64 bit；
//     宽度截取/lane 选择/符号扩展由 DUT 的 `vr1_lsu` 完成）；**store 请求不回响应**（首版 store
//     完成判据＝请求被接受，见 `rtl/vr1/lsu/vr1_lsu.sv` 文件头）；store 的**数据不经 `mem_req_t`**
//     （§3.13 无数据成员）⇒ 本 TB 在 `rt_o` 的**提交拍**观测 `mem_wr/mem_addr/mem_wdata/mem_size`
//     后按 **字节使能**（`n = 1<<mem_size` 个字节、自 `mem_addr` 起）写入内存桩（＝「SQ 持有数据
//     ＋ 提交后写」的等价物，与计划 §2.3 简化 #3 同口径）。
//     **M3-(d)（2026-09-26 心跳第 10 轮）**：本段两处口径为"LOAD/STORE 全族可判"而扩展——
//     ① 载入响应由"单个 32 bit 字"改回**双字窗口**（既有 `LW/SW` 逐值等价，见 `data_dword` 注）；
//     ② store 落盘由"整 32 bit 字覆盖"改为**字节使能**（子宽度 `SB/SH/SD` 不再误伤邻字节）。
//     两处均只动**桩**、不动判据面（`flow.py check-one m2-rv64ui` 判据② 的 `DRAM_BASE`/
//     `DMEM_WORDS` 字面量与窗口算术一字未改 ⇒ `tb_data_window_consts` 对账仍过）。
//   · 越界/未装载地址：读回 0（不产 fault；PMA/总线错误面不在首版，清单 §1.2 第 1 条）。
//     （数据窗**窗内**未预载的字＝0：与镜像"该处无内容"同义；**窗外**的读恒 0、写丢弃。）
//
// 它不是什么（边界，红线 R6/R8）：
//   · **不是**判据本体：本文件是阶段证据的产出口；M1 的 exit 判据是 `rtl-compile` 与
//     `rtl-vs-iss`（后者由 `script/flow.py` 按 `sim/golden/iss_smoke.csv` 与 RTL 侧 CSV 比对）；
//   · 不放宽任何比对列（`trace_compare.py` 默认 `pc,binary,gpr,csr`）；不产假 trace：
//     写出器只在 `rt_valid` × `rt_t.valid` 双真时落行（`tb/unit/rt_t_trace_writer.sv` 口径）。
//
// 注（日志编码）：所有 `$display` 一律 **ASCII**——ModelSim 控制台把非 ASCII 替换为 `?`（实测）。
//
// 跑法（沙箱独占，红线 R10；路径全绝对、cwd＝沙箱）：
//   cd /d sim\run_m1_e2e
//   vlib work
//   vlog -64 -sv -work work +incdir+<仓库根>/rtl/vr1/include <rtl.f 的单元> <本文件> <写出器>
//   vopt -64 work.m1_e2e_tb -o e2e_opt
//   vsim -64 -c -do "run -all; quit -f" e2e_opt +IMAGE=<仓库根>/sim/image/m_smoke.hex +RT_T_CSV=<绝对路径>
//                                        [ +DATA=<仓库根>/sim/image/rv64ui/<name>.data.hex ]  ← 数据窗预载（可选）
//                                       [ +RESET_INJECT=<cycle>[,<cycle>...] ]               ← 受控复位注入（可选；
//                                        机制与通道口径见本文件 rst_inject_ctrl 段：仅覆盖率批 rst_* 用例）
//
// 依据：doc/spec/01 §3.13/§3.16/§3.21；doc/spec/00 §4.1（`RESET_PC`/`FETCH_BYTES`）；
//       doc/design/M1-实现计划.md §4.1/§4.2/§4.3；iss/tests/test_smoke.py（TOHOST=0x4000_0010）。
// ==========================================================================
`ifndef M1_E2E_TB_SV
`define M1_E2E_TB_SV

module m1_e2e_tb;
  import vr1_pkg::*;

  localparam int unsigned SLOTS  = FETCH_BYTES / 2;        // 16 个 16 bit 候选槽
  localparam logic [39:0] TOHOST = 40'h00_4000_0010;       // riscv-tests 停机地址

  // -----------------------------------------------------------------------
  // 时钟/复位（单时钟域；异步复位、测试序列里同步释放）
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
  // **受控复位注入机制件**（R0 2026-09-26 三项裁定①＝`doc/verify/02` §6 NU-2 受控通道）
  //   plusarg `+RESET_INJECT=<cycle>[,<cycle>...]`：跑到第 N 拍（posedge 计数，见下方 cyc 口径）
  //   把 `rst_n` 拉低 `RST_INJ_LEN` 拍再释放；多个注入点逗号分隔、按序生效。
  //   · **不给 plusarg ⇒ 本 initial 在 `$value$plusargs` 处返回、不再驱动任何信号**，
  //     `rst_n` 仍由上方原 initial 独立驱动 ⇒ 现行为逐字保持（M1/M2 判据与既有用例零影响）；
  //   · 服务对象＝**仅覆盖率批**的 `rst_*` 用例（`run_cmd/cover_m3_testlist.txt`）：命中
  //     `cg_lsu_fsm.cp_trans` 的 `t_req_idle`/`t_rsp_idle`（该两迁移只有复位边能产生——
  //     `rtl/vr1/lsu/vr1_lsu.sv` 的 FSM：L_REQ 只进 L_DONE/L_RSP、L_RSP 只进 L_DONE）；
  //     **不进回归、不进 `m2-rv64ui`**（复位注入使 trace 出现"重启后第二段"，与 ISS 单段
  //     golden 构造性不可比 ⇒ 通道口径见 `sw/tests/build_rv64ui.py` COV_ONLY 段与
  //     `run_cmd/cover_rv1.py`；bin 不删、判定阈值不改，红线 R7）；
  //   · 证据行（判定批 fail-closed 检查项）：每次注入打印 `[rst_inj] ASSERT/RELEASE ...`；
  //   · 调试 plusarg `+RST_INJ_TRACE`（**判定批不带**，无判据）：逐拍打印 `cyc/lsu_state`，
  //     供"定注入拍"探针用（LSU 编码 0=IDLE 1=REQ 2=RSP 3=DONE，与 `vr1_lsu.sv` 的
  //     `lsu_state_e` 声明序同源）。打印一律 ASCII（ModelSim 控制台把非 ASCII 换 `?`）。
  // -----------------------------------------------------------------------
  localparam int unsigned RST_INJ_LEN = 3;    // 每次注入拉低的拍数（"若干拍"取 3）

  initial begin : rst_inject_ctrl
    string        inj_spec;
    int unsigned  inj_q[$];
    int unsigned  cyc, val, i, k;
    byte          ch;
    if ($value$plusargs("RESET_INJECT=%s", inj_spec)) begin
      val = 0;
      for (i = 0; i < inj_spec.len(); i++) begin
        ch = inj_spec[i];
        if (ch >= "0" && ch <= "9") val = val * 10 + (ch - "0");
        else if (ch == ",") begin inj_q.push_back(val); val = 0; end
      end
      inj_q.push_back(val);
      cyc = 0;
      for (k = 0; k < inj_q.size(); k++) begin
        while (cyc < inj_q[k]) begin @(posedge clk); cyc = cyc + 1; end
        // 拉低/释放都放在 posedge 后 2 ns（周期中段）：**避开 posedge active region 的竞争**——
        // 若与沿同区赋值，采样块 `if (rst_n)` 与 DUT 时钟分支/异步复位的 NBA 会同拍互抢
        //（实测：同区赋值时 covergroup 的迁移 bin 稳定 ZERO——最后一次采样没吃到 REQ/RSP 态）。
        // 中段注入 ⇒ 当沿采样已落地（读到 REQ/RSP），异步复位在其后 2 ns 生效，逐拍确定。
        #2;
        rst_n = 1'b0;
        $display("[rst_inj] ASSERT rst_n=0 at cyc=%0d len=%0d (NU-2 controlled channel)", cyc, RST_INJ_LEN);
        repeat (RST_INJ_LEN) begin @(posedge clk); cyc = cyc + 1; end
        #2;
        rst_n = 1'b1;
        $display("[rst_inj] RELEASE rst_n=1 at cyc=%0d", cyc);
      end
    end
  end

  initial begin : rst_inj_trace
    int unsigned tc;
    if ($test$plusargs("RST_INJ_TRACE")) begin
      tc = 0;
      forever begin
        @(posedge clk);
        tc = tc + 1;
        $display("[rst_inj] trace cyc=%0d lsu=%0d (0=IDLE 1=REQ 2=RSP 3=DONE)", tc, u_dut.u_lsu.state_q);
      end
    end
  end

  // -----------------------------------------------------------------------
  // DUT（顶层端口面）
  // -----------------------------------------------------------------------
  logic        imem_req_valid, imem_req_ready, imem_rsp_valid, imem_rsp_ready;
  mem_req_t    imem_req;
  icache_rsp_t imem_rsp;
  logic        dmem_req_valid, dmem_req_ready, dmem_rsp_valid, dmem_rsp_ready;
  mem_req_t    dmem_req;
  dcache_rsp_t dmem_rsp;
  logic        commit_valid, rt_valid, csr_wr_valid;
  rt_t         rt;

  vr1_core u_dut (
    .clk             (clk),
    .rst_n           (rst_n),
    .imem_req_valid  (imem_req_valid),
    .imem_req        (imem_req),
    .imem_req_ready  (imem_req_ready),
    .imem_rsp_valid  (imem_rsp_valid),
    .imem_rsp        (imem_rsp),
    .imem_rsp_ready  (imem_rsp_ready),
    .dmem_req_valid  (dmem_req_valid),
    .dmem_req        (dmem_req),
    .dmem_req_ready  (dmem_req_ready),
    .dmem_rsp_valid  (dmem_rsp_valid),
    .dmem_rsp        (dmem_rsp),
    .dmem_rsp_ready  (dmem_rsp_ready),
    .commit_valid    (commit_valid),
    .rt_valid_o      (rt_valid),
    .rt_o            (rt),
    .rt_ready        (1'b1),                     // 写出器零延迟（不接反压；见写出器文件头）
    .csr_wr_valid    (csr_wr_valid)
  );

  // -----------------------------------------------------------------------
  // 镜像与内存桩（字寻址；`$readmemh` 的 `@00000400` 即字地址 0x400 = 字节 0x1000）
  // -----------------------------------------------------------------------
  // 取指窗：词寻址 4096 项（覆盖字节 0x0000~0x3FFF；`@00000400` ⇒ 字节 0x1000 起）
  localparam int unsigned FMEM_WORDS = 4096;
  // 数据窗：仅覆盖 smoke 程序实际用到的 DRAM 首 1 KB（桩；越窗读 0、写丢弃——TB 边界声明）
  localparam logic [39:0] DRAM_BASE  = 40'h00_4000_0000;
  localparam int unsigned DMEM_WORDS = 256;

  logic [31:0] fmem [0:FMEM_WORDS-1];
  logic [31:0] dmemw [0:DMEM_WORDS-1];
  // `+DATA=` 预载源（**相对 `DRAM_BASE` 的字地址**口径；见文件头）。模型＝「预载 ⊕ 已提交写」：
  //   · `dpre`   —— 由 `initial` 装载的镜像数据段值（窗内未装载字＝0，与"镜像该处无内容"同义）；
  //   · `dmemw`  —— 本 TB 数据窗的**写面**（store 提交时写，见提交拍观测段），只在 `always_ff` 里驱动；
  //   · `dmem_wr_q[k]` —— 该字是否**已被程序写过**：写过 ⇒ 读 `dmemw`（写覆盖预载），否则读 `dpre`。
  // 为什么不是"复位后把 dpre 拷进 dmemw"：`dmemw` 由 `always_ff` 驱动，ModelSim 的 vlog-7061
  // （always_ff 变量不得被其他进程驱动）会直接报错 ⇒ 改用"读侧选择"，**单驱动纪律不变**、语义等价。
  logic [31:0] dpre [0:DMEM_WORDS-1];
  logic        dmem_wr_q [0:DMEM_WORDS-1];
  logic        dpre_en;

  string img_path, csv_path, data_path;

  function automatic logic [31:0] fetch_word(input logic [39:0] byte_addr);
    fetch_word = (byte_addr[39:14] == 26'd0) ? fmem[byte_addr[13:2]] : 32'd0;
  endfunction

  function automatic logic [15:0] mem_half(input logic [39:0] byte_addr);
    logic [31:0] w;
    w = fetch_word(byte_addr);
    mem_half = byte_addr[1] ? w[31:16] : w[15:0];
  endfunction

  function automatic logic [31:0] data_word(input logic [39:0] byte_addr);
    logic [39:0] off;
    off = byte_addr - DRAM_BASE;
    if ((byte_addr >= DRAM_BASE) && (off[39:10] == 30'd0))
      // 已提交写优先（写覆盖预载）；否则＝镜像数据段值（无 `+DATA=` 时 `dpre` 恒 0 ⇒ 首版零填充口径）
      data_word = dmem_wr_q[off[9:2]] ? dmemw[off[9:2]] : dpre[off[9:2]];
    else
      data_word = 32'd0;
  endfunction

  // ---- 载入响应：`va[2:0]` 所在 **8 B 对齐双字**的 64 bit（M3-(d)：2026-09-26 心跳第 10 轮）----
  //   为什么不是"只回 `va[2:0]` 所在 32 bit 字"：载入族含 **LD（8 B）**，且字节/半字载入需要
  //   `va[2:0]` 的 lane 选择；本桩把"双字对齐窗"整块回给 DUT，**lane 选择与符号扩展由
  //   `rtl/vr1/lsu/vr1_lsu.sv` 按 `size`/`addr[2:0]`/`sext` 完成**（职责单一：桩不做语义）。
  //   对既有 `LW/SW` 口径**逐值等价**：`addr[2]=0` 时低 32 bit 即原 `data_word(va)`。
  function automatic logic [63:0] data_dword(input logic [39:0] byte_addr);
    logic [39:0] base;
    base = {byte_addr[39:3], 3'b0};
    data_dword = {data_word(base + 40'd4), data_word(base)};
  endfunction

  initial begin
    if (!$value$plusargs("IMAGE=%s", img_path)) img_path = "sim/image/m_smoke.hex";
    if (!$value$plusargs("RT_T_CSV=%s", csv_path)) csv_path = "sim/run_m1_e2e/rtl_side.csv";
    for (int unsigned k = 0; k < FMEM_WORDS; k++) fmem[k] = 32'hFFFF_FFFF;   // 未装载区＝填充字
    $readmemh(img_path, fmem);
    $display("[m1_e2e] image=%s (readmemh word-address form; MANIFEST base_word=0x400 base_byte=0x1000)",
             img_path);
    // ---- 数据窗预载源（`+DATA=`；`dpre` 只在本 initial 驱动 ⇒ 与 `always_ff` 无多驱动冲突）----
    for (int unsigned k = 0; k < DMEM_WORDS; k++) dpre[k] = 32'd0;
    dpre_en = 1'b0;
    if ($value$plusargs("DATA=%s", data_path)) begin
      $readmemh(data_path, dpre);
      dpre_en = 1'b1;
      $display("[m1_e2e] data=%s (readmemh word-address form; base=0x%010x words=%0d)",
               data_path, DRAM_BASE, DMEM_WORDS);
      $display("[m1_e2e] data window preloaded: %0d words from %s (DRAM_BASE=0x%010x)",
               DMEM_WORDS, data_path, DRAM_BASE);
    end
  end

  // ---- 取指桩：请求 → 锁存窗 → 保持到被接受（DUT 冲刷后重请求会覆盖）----
  logic         i_rsp_v_q;
  logic [255:0] i_win_q;
  logic [39:0]  i_base_q;
  int unsigned  n_i_req;

  // -----------------------------------------------------------------------
  // **定向背压激励：握手等待态**（2026-09-26 心跳第 12 轮；M3-(b) 补缺 bin）
  //   目的（逐条对缺 bin；证据＝`doc/verify/07-m2cov_r2.txt` §A 的 ZERO 清单）：
  //     · `cg_fetch.cp_req_hs` 的 `idle`(00) 与 `req_wait`(10) 两 bin 为 **ZERO**——此前
  //       `imem_req_ready` 恒 1 ⇒ 取指握手面只有 `req_bite`(11) 一态（「请求未被立即接受」的
  //       时序从未出现）；
  //     · `cg_fetch.cp_rsp_hs` 的 `rsp_wait`(10) 同理（`imem_rsp_ready` 是 DUT 输出＝
  //       `state_q == F_WAIT`，`rtl/vr1/frontend/vr1_ifetch.sv:122`）。
  //   机制（**只改 TB 桩**：不动 DUT、不动冻结端口面、不动覆盖模型与任何判据）：
  //     每笔请求**至少等一拍才被接受**（→ `req_wait`：valid=1 ∧ ready=0），
  //     接受后**冷却一拍**（→ `idle`：valid=0 ∧ ready=0）；两次延迟都落在 `ready` 侧。
  //   为什么对 DUT **语义零影响**（可核）：两侧 RTL 的推进都按 `… && ready` 门控——
  //     `vr1_ifetch.sv:118` 的 `issue = req_vld && imem_req_ready_i`（`req_vld` 由 `state_q`
  //     与队头导出，未接受即保持不变）；`vr1_lsu.sv:265` 的 `if (dmem_req_ready_i)`。
  //     ⇒ 未接受 ⇒ **不推进状态、不产生副作用**；本桩也只在握手拍锁存窗内容（同原口径）。
  //   `rsp_wait` 由此"顺带"命中：冲刷（`flush_i ⇒ F_IDLE`）与重请求之间，本桩仍持有上一窗的
  //     `i_rsp_v_q` ⇒ 出现「rsp_valid=1 ∧ rsp_ready=0」的拍——**不是**把响应提前给，也不改协议。
  //   口径（可复现/可审计）：**恒开**（无 plusarg —— `run_cmd/cover_rv1.py` 的 vsim 命令行不带
  //     额外 plusarg，见其 `sim_command_template`；恒开使 M1/M2 判据与覆盖率批**同一激励面**，
  //     不存在"只有覆盖率批才开"的暗门）；等待/冷却拍数＝常量 1。
  // -----------------------------------------------------------------------
  localparam int unsigned HS_WAIT = 1;      // 每笔请求的最少等待拍（1 ⇒ 恰好造出握手等待态）
  logic i_req_seen_q, i_req_cool_q;         // 取指请求：已见一拍 ／ 接受后冷却
  logic d_req_seen_q, d_req_cool_q;         // 访存请求：同上（同一口径）

  assign imem_req_ready = !((imem_req_valid && !i_req_seen_q) || i_req_cool_q);
  assign dmem_req_ready = !((dmem_req_valid && !d_req_seen_q) || d_req_cool_q);

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      i_req_seen_q <= 1'b0;
      i_req_cool_q <= 1'b0;
      d_req_seen_q <= 1'b0;
      d_req_cool_q <= 1'b0;
    end else begin
      i_req_seen_q <= imem_req_valid && !i_req_cool_q;   // 请求在且未冷却 ⇒ "已见"
      i_req_cool_q <= imem_req_valid && i_req_seen_q;    // 本拍被接受（seen=1 ⇒ ready=1）⇒ 下拍冷却
      d_req_seen_q <= dmem_req_valid && !d_req_cool_q;
      d_req_cool_q <= dmem_req_valid && d_req_seen_q;
    end
  end

  always_comb begin
    imem_rsp             = '0;
    imem_rsp_valid       = i_rsp_v_q;
    imem_rsp.valid       = i_rsp_v_q;
    imem_rsp.win         = i_win_q;
    imem_rsp.win_base_pc = i_base_q;
    imem_rsp.seq         = 12'd0;                // 无 μop 序号（IF 请求非 μop，见 M03 文件头）
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      i_rsp_v_q <= 1'b0;
      i_win_q   <= 256'd0;
      i_base_q  <= 40'd0;
      n_i_req   <= 0;
    end else begin
      if (imem_req_valid && imem_req_ready) begin
        i_base_q <= {imem_req.va[39:5], 5'b0};    // §3.16 BLK-08：窗基址 = VA[39:5] 补 0
        for (int unsigned j = 0; j < SLOTS; j++)
          i_win_q[16*j +: 16] <= mem_half({imem_req.va[39:5], 5'b0} + 40'(2*j));
        i_rsp_v_q <= 1'b1;
        n_i_req   <= n_i_req + 1;
      end else if (i_rsp_v_q && imem_rsp_ready) begin
        i_rsp_v_q <= 1'b0;                        // 被接受即撤（响应为"保持到接受"语义）
      end
    end
  end

  // ---- 访存桩：load 回数据；store 不回响应（数据由提交拍观测写入，见文件头）----
  //   注：`dmem_req_ready` 的握手等待态由本文件顶部的**定向背压激励**段产生（恒开；见那段注释）。
  logic        d_rsp_v_q;
  logic [63:0] d_rsp_data_q;
  int unsigned n_ld, n_st;

  always_comb begin
    dmem_rsp          = '0;
    dmem_rsp_valid    = d_rsp_v_q;
    dmem_rsp.valid    = d_rsp_v_q;
    dmem_rsp.data     = d_rsp_data_q;
    dmem_rsp.rd_paddr = 6'd0;                     // 无 PRF（首版恒等映射）
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      d_rsp_v_q    <= 1'b0;
      d_rsp_data_q <= 64'd0;
      n_ld         <= 0;
      n_st         <= 0;
    end else begin
      if (dmem_req_valid && dmem_req_ready) begin
        if (dmem_req.kind == 2'b01) begin
          n_st <= n_st + 1;                       // store：仅计数（数据在提交拍写入，见下）
        end else begin
          d_rsp_data_q <= data_dword(dmem_req.va);
          d_rsp_v_q    <= 1'b1;
          n_ld         <= n_ld + 1;
        end
      end else if (d_rsp_v_q && dmem_rsp_ready) begin
        d_rsp_v_q <= 1'b0;
      end
    end
  end

  // ---- 提交拍观测（§3.21②）：store 数据落地 + 证据行 ----
  //   注：写数据窗用**阻塞赋值**（ModelSim 2020.4 不支持对关联/数组元素的非阻塞赋值）；
  //   store 提交与 load 请求在本设计**构造上互斥**（单条在飞）⇒ 无同拍写读竞争。
  //   `dmem_wr_q[]` = 「该字已被程序写过」位图（置位后读侧走 `dmemw`、盖住 `+DATA=` 预载值）。
  //   **字节使能（M3-(d)：2026-09-26 心跳第 10 轮）**：按 `rt.mem_size`（＝`dm`：00 B／01 H／
  //   10 W／11 D）与 `rt.mem_addr[2:0]` 把 `rt.mem_wdata` 的**低 n 字节**写到 `addr` 起的
  //   n 个字节（littl-endian；`n = 1 << size`），**逐字节**更新、不动同字内其余 lane ——
  //   这是 `SB/SH/SD` 与 `SW` 同口径的构造性保证（此前恒按整 32 bit 字覆盖 ⇒ 子宽度 store
  //   会误伤邻字节）。数据面 `rt.mem_wdata` 为 **未移位**的 rs2（与 ISS `rec.mem_wdata` 同口径），
  //   移位量在本桩内按 `addr[2:0]` 施加（DUT 侧 `vr1_lsu` 不做 lane 预移位，见其文件头 ⑤）。
  int unsigned n_ret, n_exc, n_store_commit;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      n_ret          <= 0;
      n_exc          <= 0;
      n_store_commit <= 0;
      for (int unsigned k = 0; k < DMEM_WORDS; k++) begin
        dmemw[k]    = 32'd0;                    // 数据窗写面清零（TB 桩）
        dmem_wr_q[k] = 1'b0;                    // 写位图清零（预载值在 `dpre`，不在此清零）
      end
    end else if (rt_valid && rt.valid) begin
      n_ret <= n_ret + 1;
      if (rt.exc_v) n_exc <= n_exc + 1;
      if (rt.mem_v && rt.mem_wr) begin
        logic [39:0]    saddr;
        logic [39:0]    soff;
        logic [2:0]     blane;
        logic [31:0]    wtmp;
        int unsigned    nbytes;
        n_store_commit <= n_store_commit + 1;
        // 提交后写（一期禁投机 store 写；SQ 的角色由本桩承担，见文件头）
        nbytes = 1 << rt.mem_size;              // `dm` → 字节数：00→1、01→2、10→4、11→8
        for (int unsigned i = 0; i < 8; i++) begin
          if (i < nbytes) begin
            saddr = rt.mem_addr + 40'(i);
            soff  = saddr - DRAM_BASE;
            if ((saddr >= DRAM_BASE) && (soff[39:10] == 30'd0)) begin
              // **首次写该字时先把预载值搬进写面**（读侧按**字**在 `dpre`/`dmemw` 之间切换，见
              //   `data_word`）：不做这一步，子宽度 store（SB/SH）只会写进 1~2 个字节，同字内
              //   **其余未写字节会由 `dmemw` 的初值 0** 顶掉预载值 ⇒ 「镜像 ⊕ 已提交写」被破坏
              //   （2026-09-26 心跳第 10 轮实测踩到：sb/sh 在第 4 号用例的 `lh` 上首个分歧，
              //   pc=0000123c/00001244）。搬入是**语义补齐**而非放宽：真实内存＝镜像先行、
              //   提交写按字节叠加。
              if (!dmem_wr_q[soff[9:2]]) dmemw[soff[9:2]] = dpre[soff[9:2]];
              blane = saddr[1:0];
              wtmp  = dmemw[soff[9:2]];
              wtmp[8*blane +: 8]   = rt.mem_wdata[8*i +: 8];
              dmemw[soff[9:2]]     = wtmp;
              dmem_wr_q[soff[9:2]] = 1'b1;
            end
          end
        end
      end
      $display("[m1_e2e] retire#%0d pc=%010x bin=%08x rd=%0d wb=%0b data=%016x csr=%03x/%016x wr=%0b exc=%0b c=%0d mem_v=%0b wr=%0b a=%010x wd=%016x",
               n_ret, rt.pc, rt.instr, rt.rd_idx, rt.rd_wb_en, rt.rd_data,
               rt.csr_addr, rt.csr_new, rt.csr_wr_en, rt.exc_v, rt.exc_cause,
               rt.mem_v, rt.mem_wr, rt.mem_addr, rt.mem_wdata);
    end
  end

  // -----------------------------------------------------------------------
  // `rt_t` 写出器（TB 侧件；逐成员接线，端口见其文件头）
  // -----------------------------------------------------------------------
  rt_t_trace_writer #(
    .MAX_CYCLES   (2_000_000),                    // 红线 R9：功能比对类 watchdog
    .TOHOST_ADDR  (TOHOST)
  ) u_writer (
    .clk         (clk),
    .rst_n       (rst_n),
    .rt_valid    (rt_valid),
    .rt_t_valid  (rt.valid),
    .pc          (rt.pc),
    .instr       (rt.instr),
    .is_c        (rt.is_c),
    .rd_idx      (rt.rd_idx),
    .rd_wb_en    (rt.rd_wb_en),
    .rd_data     (rt.rd_data),
    .priv        (rt.priv),
    .csr_addr    (rt.csr_addr),
    .csr_old     (rt.csr_old),
    .csr_new     (rt.csr_new),
    .csr_wr_en   (rt.csr_wr_en),
    .exc_v       (rt.exc_v),
    .exc_cause   (rt.exc_cause),
    .is_intr     (rt.is_intr),
    .mispred     (rt.mispred),
    .is_br       (rt.is_br),
    .mem_v       (rt.mem_v),
    .mem_addr    (rt.mem_addr),
    .mem_wdata   (rt.mem_wdata),
    .mem_rdata   (rt.mem_rdata),
    .mem_size    (rt.mem_size),
    .mem_wr      (rt.mem_wr),
    .seq         (rt.seq),
    .cycle       (rt.cycle)
  );

  // -----------------------------------------------------------------------
  // 首批功能覆盖模型 ＋ SVA 断言（`tb/unit/m1_e2e_cov.sv`；TB 侧**纯监视器**）
  //   落点说明与"为什么不 bind"见该文件头（**判据本体一字未动**）；本处只做接线：
  //   · DUT **冻结端口**直接接（`rt_valid_o`/`rt_o`/`commit_valid`/取指与访存握手面）；
  //   · `[内部采样口]` 用**本 TB 既有的层次化探针写法**（`+DBG` 段同款）接入 DUT 内部信号
  //     —— `spec/11` §2 要求的"TB 从采样口构造"声明落在该文件的端口注释与下表：
  //       `lsu_state` = `u_dut.u_lsu.state_q` ｜ `lsu_fault` = `u_dut.u_lsu.fault_q`
  //       `disp_fire` = `u_dut.disp_fire`     ｜ `disp_is_mem` = `u_dut.is_mem_q`
  //   · 本模块**无输出**（不驱动 DUT）⇒ 不改任何既有行为（红线 R6：不碰判据）。
  // -----------------------------------------------------------------------
  m1_e2e_cov #(
    .TOHOST_ADDR (TOHOST)
  ) u_cov (
    .clk            (clk),
    .rst_n          (rst_n),
    .rt_valid       (rt_valid),
    .rt             (rt),
    .commit_valid   (commit_valid),
    .imem_req_valid (imem_req_valid),
    .imem_req       (imem_req),
    .imem_req_ready (imem_req_ready),
    .imem_rsp_valid (imem_rsp_valid),
    .imem_rsp_ready (imem_rsp_ready),
    .dmem_req_valid (dmem_req_valid),
    .dmem_req       (dmem_req),
    .dmem_rsp_valid (dmem_rsp_valid),
    .dmem_rsp_ready (dmem_rsp_ready),
    .lsu_state      (u_dut.u_lsu.state_q),
    .lsu_fault      (u_dut.u_lsu.fault_q),
    .disp_fire      (u_dut.disp_fire),
    .disp_is_mem    (u_dut.is_mem_q)
  );

  // -----------------------------------------------------------------------
  // 调试探针（`+DBG` 开启；冲刷后 50 拍逐拍打印前端/后端握手面）——**无判据**，仅供归因
  // -----------------------------------------------------------------------
  int unsigned dbg_win;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      dbg_win <= 0;
    end else begin
      if (u_dut.flush_all) dbg_win <= 50;
      else if (dbg_win != 0) dbg_win <= dbg_win - 1;
      if ((dbg_win != 0) && $test$plusargs("DBG"))
        $display("[dbg] flush=%b redir=%010x ftq_vld=%b ftq_pop=%b ibuf_vld=%b if_st=%0d req_vld=%b ireq_v=%b irsp_v=%b irsp_rdy=%b bp_next=%010x dec_rdy=%b rbuf=%0d wb=%b commit=%b",
                 u_dut.flush_all, u_dut.redirect_pc, u_dut.ftq_head_vld, u_dut.ftq_pop,
                 u_dut.ibuf_win_vld, u_dut.u_ifetch.state_q, u_dut.u_ifetch.req_vld,
                 u_dut.imem_req_valid, u_dut.imem_rsp_valid, u_dut.imem_rsp_ready,
                 u_dut.u_bp.next_pc_q, u_dut.dec_ready, u_dut.rbuf_cnt,
                 u_dut.wb_vld, u_dut.rob_commit_vld);
    end
  end

  // -----------------------------------------------------------------------
  // 收尾：一行汇总（**无判据**；比对归 `trace_compare.py`／`flow.py check-one rtl-vs-iss`）
  // -----------------------------------------------------------------------
  final begin
    $display("[m1_e2e] SUMMARY retired=%0d exc=%0d store_commit=%0d imem_req=%0d dmem_ld=%0d dmem_st=%0d data_pre=%0b",
             n_ret, n_exc, n_store_commit, n_i_req, n_ld, n_st, dpre_en);
  end

endmodule

`endif // M1_E2E_TB_SV
