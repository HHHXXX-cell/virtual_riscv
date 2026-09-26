// ==========================================================================
// vr1_params.svh — 由 doc/spec/00 §4 参数总表生成（全项目数值唯一权威源）
// DO NOT EDIT BY HAND. 改数值请改 spec/00 §4，再跑：python script/flow.py params
// 生成时间 2026-09-25 22:27 ／ 源文件 md5 87463dd86a8154ddb2feef5eb2249a80
// 覆盖对账：表体 118 行 = parameter 101 条 + 非数值登记 17 条 + 未解析 0 条
// 单位口径：spec/00 §4 的「数字＋单位」单元格（如 `32 KB`／`64 B`）**数值照取、不换算**，
//   单位随行以 `// 单位：<U>` 落盘（绝不静默吞掉；清单见 `flow.py check-one params-units`，只报告不判定）。
// G1 冻结后本文件由 rtl/vr1/include/vr1_pkg.sv 包裹（spec/00 §4 命名约定）
// ==========================================================================
`ifndef VR1_PARAMS_SVH
`define VR1_PARAMS_SVH

// ---- 4.1 ----
parameter int unsigned XLEN = 64; // spec/00 4.1 L117
parameter int unsigned VA_BITS = 39; // spec/00 4.1 L118
parameter int unsigned VA_STORE_W = 40; // spec/00 4.1 L119
parameter int unsigned PA_BITS = 44; // spec/00 4.1 L120
parameter int unsigned ALEN = 44; // spec/00 4.1 L121
parameter logic [43:0] RESET_PC = 44'h0000_1000; // spec/00 4.1 L122
parameter int unsigned FETCH_BYTES = 32; // spec/00 4.1 L123
// ---- 4.2 ----
parameter int unsigned BP_STAGES = 3; // spec/00 4.2 L129
parameter int unsigned IF_STAGES = 3; // spec/00 4.2 L130
parameter int unsigned FTQ_ENTRIES = 16; // spec/00 4.2 L131
parameter int unsigned IBUF_ENTRIES = 16; // spec/00 4.2 L132
parameter int unsigned L1BTB_ENTRIES = 64; // spec/00 4.2 L133
//   原文：64，直接映射
parameter int unsigned L2BTB_ENTRIES = 1024; // spec/00 4.2 L134
//   原文：1024，4 路（256 set）
parameter int unsigned TAGE_BASE_ENTRIES = 1024; // spec/00 4.2 L135
//   原文：1024，无标签，2bit ctr
parameter int unsigned TAGE_TABLES = 4; // spec/00 4.2 L136
parameter int unsigned TAGE_HIST_LEN[4] = '{8, 16, 32, 64}; // spec/00 4.2 L137
//   原文：8, 16, 32, 64
parameter int unsigned TAGE_ENTRIES_EA = 2048; // spec/00 4.2 L138
//   原文：2048，4 路（512 set）
parameter int unsigned TAGE_TAG_W = 11; // spec/00 4.2 L139
parameter int unsigned TAGE_CTR_W = 3; // spec/00 4.2 L140
parameter int unsigned TAGE_USEFUL_W = 2; // spec/00 4.2 L141
parameter int unsigned GHR_BITS = 128; // spec/00 4.2 L142
parameter int unsigned SC_ENTRIES = 256; // spec/00 4.2 L143
parameter int unsigned SC_INPUTS = 24; // spec/00 4.2 L144
parameter int unsigned SC_WEIGHT_W = 8; // spec/00 4.2 L145
parameter int unsigned ITTAGE_TABLES = 2; // spec/00 4.2 L146
parameter int unsigned ITTAGE_HIST_LEN[2] = '{6, 14}; // spec/00 4.2 L147
//   原文：6, 14
parameter int unsigned ITTAGE_ENTRIES_EA = 512; // spec/00 4.2 L148
//   原文：512，4 路
parameter int unsigned ITTAGE_TARGET_W = 40; // spec/00 4.2 L149
parameter int unsigned RAS_ENTRIES = 32; // spec/00 4.2 L150
parameter int unsigned SARAS_FIX_QUEUE = 8; // spec/00 4.2 L151
parameter int unsigned BP_ALT_HIST = 1; // spec/00 4.2 L152
parameter int unsigned IUM_EN = 1; // spec/00 4.2 L153
// ---- 4.3 ----
parameter int unsigned DECODE_WIDTH = 4; // spec/00 4.3 L162
parameter int unsigned C_EXPAND_STAGES = 1; // spec/00 4.3 L163
parameter int unsigned UOP_MAX_SPLIT = 2; // spec/00 4.3 L164
parameter int unsigned RAT_ENTRIES = 32; // spec/00 4.3 L165
parameter int unsigned RAT_IDX_W = 5; // spec/00 4.3 L166
parameter int unsigned PRF_INT_ENTRIES = 64; // spec/00 4.3 L167
parameter int unsigned PADDR_W = 6; // spec/00 4.3 L168
parameter int unsigned PRF_STATE_BITS = 2; // spec/00 4.3 L169
parameter int unsigned PRF_RD_PORTS = 16; // spec/00 4.3 L170
parameter int unsigned PRF_WR_PORTS = 6; // spec/00 4.3 L171
parameter int unsigned CHECKPOINT_COPIES = 4; // spec/00 4.3 L172
parameter int unsigned ROLLBACK_RATE = 8; // spec/00 4.3 L173
parameter int unsigned SAME_GROUP_BYPASS_DEPTH = 4; // spec/00 4.3 L174
parameter int unsigned HIST_DEPTH = 33; // spec/00 4.3 L175
//   原文：33（ADR-S2，2026-09-23）
parameter int unsigned ROLLBACK_MAX = 33; // spec/00 4.3 L176
//   原文：33（ADR-S2，2026-09-23）
// ---- 4.4 ----
parameter int unsigned ISSUE_WIDTH = 6; // spec/00 4.4 L191
parameter int unsigned IQ_INT_ENTRIES = 24; // spec/00 4.4 L192
parameter int unsigned IQ_MEM_ENTRIES = 20; // spec/00 4.4 L193
parameter int unsigned IQ_BR_ENTRIES = 20; // spec/00 4.4 L194
parameter int unsigned IQ_TAG_W = 12; // spec/00 4.4 L195
parameter int unsigned WAKE_BCAST_PORTS = 6; // spec/00 4.4 L196
// [非数值·登记] OPND_READ_POLICY = 后读 // spec/00 4.4 L197（编码由归属篇定义，不在此处臆造）
parameter int unsigned ALU_NUM = 3; // spec/00 4.4 L198
parameter int unsigned BRU_NUM = 1; // spec/00 4.4 L199
parameter int unsigned SHIFT_NUM = 1; // spec/00 4.4 L200
parameter int unsigned MUL_NUM = 1; // spec/00 4.4 L201
//   原文：1 / 3
parameter int unsigned MUL_LAT = 3; // spec/00 4.4 L201
//   原文：1 / 3
parameter int unsigned DIV_NUM = 1; // spec/00 4.4 L202
//   原文：1 / 35
parameter int unsigned DIV_LAT = 35; // spec/00 4.4 L202
//   原文：1 / 35
parameter int unsigned AGU_NUM = 2; // spec/00 4.4 L203
parameter int unsigned BYPASS_CLUSTERS = 2; // spec/00 4.4 L204
parameter int unsigned N_EU_TOTAL = 9; // spec/00 4.4 L205
// ---- 4.5 ----
parameter int unsigned ROB_ENTRIES = 128; // spec/00 4.5 L215
parameter int unsigned ROB_PTR_W = 8; // spec/00 4.5 L216
parameter int unsigned ROB_STORES_RESULT = 0; // spec/00 4.5 L217
parameter int unsigned ROB_NEAR_FULL = 120; // spec/00 4.5 L218
parameter int unsigned COMMIT_WIDTH = 4; // spec/00 4.5 L219
parameter int unsigned EXC_PENDING_AT_COMMIT = 1; // spec/00 4.5 L220
// [非数值·登记] BR_FLUSH_MODE = 尾指针回退 // spec/00 4.5 L221（编码由归属篇定义，不在此处臆造）
// ---- 4.6 ----
parameter int unsigned LQ_ENTRIES = 48; // spec/00 4.6 L227
parameter int unsigned SQ_ENTRIES = 32; // spec/00 4.6 L228
parameter int unsigned SWCP_ENTRIES = 4; // spec/00 4.6 L229
parameter int unsigned LD_PIPE = 2; // spec/00 4.6 L230
//   原文：2 / 1
parameter int unsigned STD_PIPE = 1; // spec/00 4.6 L230
//   原文：2 / 1
parameter int unsigned FWD_MAX_SOURCES = 2; // spec/00 4.6 L231
parameter int unsigned FWD_CMP_BITS = 44; // spec/00 4.6 L232
parameter int unsigned L1I_SIZE = 32; // spec/00 4.6 L233
//   原文：32 KB / 32 KB
//   单位：KB（数值照取、**未换算**；消费者须按 KB 解释本值）
parameter int unsigned L1D_SIZE = 32; // spec/00 4.6 L233
//   原文：32 KB / 32 KB
//   单位：KB（数值照取、**未换算**；消费者须按 KB 解释本值）
parameter int unsigned L1_WAYS = 8; // spec/00 4.6 L234
//   原文：8 / 64 B
parameter int unsigned L1_LINE = 64; // spec/00 4.6 L234
//   原文：8 / 64 B
//   单位：B（数值照取、**未换算**；消费者须按 B 解释本值）
parameter int unsigned L1_SETS = 64; // spec/00 4.6 L235
parameter int unsigned L2_SIZE = 256; // spec/00 4.6 L236
//   原文：256 KB / 16 / 64 B
//   单位：KB（数值照取、**未换算**；消费者须按 KB 解释本值）
parameter int unsigned L2_WAYS = 16; // spec/00 4.6 L236
//   原文：256 KB / 16 / 64 B
parameter int unsigned L2_LINE = 64; // spec/00 4.6 L236
//   原文：256 KB / 16 / 64 B
//   单位：B（数值照取、**未换算**；消费者须按 B 解释本值）
parameter int unsigned MSHR_ENTRIES = 8; // spec/00 4.6 L237
// [非数值·登记] CACHE_REPLACE = PLRU // spec/00 4.6 L238（编码由归属篇定义，不在此处臆造）
// [非数值·登记] L1D_POLICY = WB + write-allocate // spec/00 4.6 L239（编码由归属篇定义，不在此处臆造）
parameter int unsigned PREFETCH_EN = 0; // spec/00 4.6 L240
parameter int unsigned L1I_TLB = 16; // spec/00 4.6 L241
//   原文：16 全相联 / 16 全相联
parameter int unsigned L1D_TLB = 16; // spec/00 4.6 L241
//   原文：16 全相联 / 16 全相联
parameter int unsigned L2_TLB = 64; // spec/00 4.6 L242
//   原文：64，4 路（16 set）
parameter int unsigned PTW_ENGINES = 1; // spec/00 4.6 L243
// [非数值·登记] AD_BITS_POLICY = 硬件置 A/D // spec/00 4.6 L244（编码由归属篇定义，不在此处臆造）
parameter int unsigned ASID_BITS_IMPL = 9; // spec/00 4.6 L245
parameter int unsigned PMP_ENTRIES = 8; // spec/00 4.6 L246
parameter int unsigned PMP_GRAIN = 4; // spec/00 4.6 L247
//   原文：4 B（G=0）
//   单位：B（数值照取、**未换算**；消费者须按 B 解释本值）
// [非数值·登记] SFENCE_GRANULARITY = 全刷 / 按 ASID / 按 (ASID,VA) // spec/00 4.6 L248（编码由归属篇定义，不在此处臆造）
// ---- 4.7 ----
// [非数值·登记] CORE_BUS = OBI 风格内部总线 // spec/00 4.7 L254（编码由归属篇定义，不在此处臆造）
// [非数值·登记] EXT_BUS = AXI4，128 bit data / 44 bit addr / ID 4 bit // spec/00 4.7 L255（编码由归属篇定义，不在此处臆造）
parameter int unsigned AXI_OUTSTANDING = 4; // spec/00 4.7 L256
//   原文：2R + 2W
//   推导：计数项求和 2 + 2 = 4
//   口径：原文 `2R + 2W` 为**分方向计数项**，本行只有求和后的单一数值 4；
//        若下游需按方向/通道分别记账（ADR-P-2 §4），须拆参——本行口径待 ADR-P-2 §4 下游义务 O-1/O-2/O-3 落 `spec/00` §4 与 `spec/06`／`spec/09`（本生成件暂不拆）。
// [非数值·登记] MMIO_BURST = len=0（单拍传输），size=2..8 B // spec/00 4.7 L257（编码由归属篇定义，不在此处臆造）
parameter int unsigned MISALIGNED_EN = 0; // spec/00 4.7 L258
parameter int unsigned CLINT = 1; // spec/00 4.7 L259
//   原文：1 hart：mtimecmp×1、msip×1、mtime
// [非数值·登记] PLIC = PLIC-lite：8 source，3 bit per-source 优先级 + 3 bit threshold，claim/complete // spec/00 4.7 L260（编码由归属篇定义，不在此处臆造）
// [非数值·登记] INTR_PRIORITY = MEI > MSI > MTI > SEI > SSI > STI > LCOFI // spec/00 4.7 L261（编码由归属篇定义，不在此处臆造）
parameter int unsigned NMI_EN = 0; // spec/00 4.7 L262
// [非数值·登记] COUNTERS = mcycle、minstret、time（读外部 mtime） // spec/00 4.7 L263（编码由归属篇定义，不在此处臆造）
// [非数值·登记] CSR_TRAP_SET = mstatus/misa/medeleg/mideleg/mie/mtvec/mscratch/mepc/mcause/mtval/mip/mhartid/mvendorid/marchid/mimpid/mcounteren/mcountinhibit + S 侧 sstatus/stvec/sie/sscratch/sepc/scause/stval/sip/scounteren/satp // spec/00 4.7 L264（编码由归属篇定义，不在此处臆造）
// [非数值·登记] MTVEC_MODES = Direct + Vectored // spec/00 4.7 L265（编码由归属篇定义，不在此处臆造）
parameter logic [63:0] MISA_VALUE = 64'h8000_0000_0014_1105; // spec/00 4.7 L266
//   原文：0x8000_0000_0014_1105
parameter int unsigned CSR_ID_VALUES = 0; // spec/00 4.7 L267
// [非数值·登记] PMP_A_MODES = OFF + NA4 + NAPOT（无 TOR） // spec/00 4.7 L268（编码由归属篇定义，不在此处臆造）
// [非数值·登记] DECODE_SUPPORT = 仅 EBREAK→breakpoint 异常 // spec/00 4.7 L269（编码由归属篇定义，不在此处臆造）
parameter int unsigned CLK_DOMAINS = 1; // spec/00 4.7 L270
// [非数值·登记] RESET_SCHEME = 异步复位、同步释放 // spec/00 4.7 L271（编码由归属篇定义，不在此处臆造）
parameter int unsigned GATE_CLOCK_EN = 0; // spec/00 4.7 L272
//   原文：0（一期）

`endif // VR1_PARAMS_SVH
