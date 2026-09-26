// ==========================================================================
// vr1_types.svh — 由 doc/spec/01 §3 接口 struct 表生成（字段名/位宽唯一权威源）
// DO NOT EDIT BY HAND. 改字段请改 spec/01 §3，再跑：python script/flow.py types
// 生成时间 2026-09-25 22:45 ／ 源文件 md5 887c82c2274a9c35d8d592af0ee2158e
// 覆盖对账：28 个 struct / 327 个源成员行 = 298 个标量行 + 29 个非标量行
//   非标量行按 doc/decisions/if_split.json（ADR-P-2 切分表）展开为**真实字段声明**；
//   切分表查不到的源行**只登记、不猜测**（fail-closed），由判据 types-coverage 逐行复核。
// 源行可核：每个字段行带 `// src: L<行号> <成员列原文>`；同一源行的字段共享同一标记（＝1 个行组）。
// 打包顺序：ADR-P-1（RD 自决 2026-09-25）——表中自上而下 = MSB→LSB。
//   spec/01 全篇未规定打包顺序（实测无 MSB/LSB/位序 表述）；本约定为**自决项**，
//   已进 G1 评审 list 供人确认；回退点＝改 PACK_ORDER_MSB_FIRST 后重生成。
// 解析复用 script/width_check.py 的 parse()/member_width()（不另写解析器）；
// 切分复用 doc/decisions/if_split.json（ADR-P-2；自检器 doc/decisions/check_if_split.py）。
// ==========================================================================
`ifndef VR1_TYPES_SVH
`define VR1_TYPES_SVH

// ---- spec/01 §3 L113 `ftq_req_t`（合计 143 bit，声明 143）----
typedef struct packed {
  logic [0:0] valid;  // src: L117 valid
  logic [39:0] pc;  // src: L118 pc
  logic [4:0] nib;  // src: L119 nib
  logic [0:0] br_vld;  // src: L120 br_vld
  logic [1:0] br_type;  // src: L121 br_type
  logic [0:0] taken;  // src: L122 taken
  logic [39:0] target;  // src: L123 target
  logic [1:0] ras_op;  // src: L124 ras_op
  logic [39:0] ras_top;  // src: L125 ras_top
  logic [1:0] pred_conf;  // src: L126 pred_conf
  logic [7:0] bp_upd_id;  // src: L127 bp_upd_id
  logic [0:0] bad_va;  // src: L128 bad_va
} ftq_req_t;
localparam int unsigned FTQ_REQ_T_W = 143;

// ---- spec/01 §3 L134 `ftq_entry_t`（合计 145 bit，声明 145）----
typedef struct packed {
  logic [0:0] valid;  // src: L140 = ftq_req_t（全字段复用） ｜ R2 展开
  logic [39:0] pc;  // src: L140 = ftq_req_t（全字段复用） ｜ R2 展开
  logic [4:0] nib;  // src: L140 = ftq_req_t（全字段复用） ｜ R2 展开
  logic [0:0] br_vld;  // src: L140 = ftq_req_t（全字段复用） ｜ R2 展开
  logic [1:0] br_type;  // src: L140 = ftq_req_t（全字段复用） ｜ R2 展开
  logic [0:0] taken;  // src: L140 = ftq_req_t（全字段复用） ｜ R2 展开
  logic [39:0] target;  // src: L140 = ftq_req_t（全字段复用） ｜ R2 展开
  logic [1:0] ras_op;  // src: L140 = ftq_req_t（全字段复用） ｜ R2 展开
  logic [39:0] ras_top;  // src: L140 = ftq_req_t（全字段复用） ｜ R2 展开
  logic [1:0] pred_conf;  // src: L140 = ftq_req_t（全字段复用） ｜ R2 展开
  logic [7:0] bp_upd_id;  // src: L140 = ftq_req_t（全字段复用） ｜ R2 展开
  logic [0:0] bad_va;  // src: L140 = ftq_req_t（全字段复用） ｜ R2 展开
  logic [0:0] icache_ready;  // src: L141 icache_ready
  logic [0:0] ptw_req;  // src: L142 ptw_req
} ftq_entry_t;
localparam int unsigned FTQ_ENTRY_T_W = 145;

// ---- spec/01 §3 L146 `fetch_raw_t`（合计 92 bit，声明 92）----
typedef struct packed {
  logic [0:0] valid;  // src: L150 valid
  logic [39:0] pc;  // src: L151 pc
  logic [31:0] raw32;  // src: L152 raw32
  logic [0:0] is_c;  // src: L153 is_c
  logic [7:0] bp_upd_id;  // src: L154 bp_upd_id
  logic [4:0] ftq_id;  // src: L155 ftq_id
  logic [0:0] err;  // src: L156 err
  logic [3:0] err_code;  // src: L157 err_code
} fetch_raw_t;
localparam int unsigned FETCH_RAW_T_W = 92;

// ---- spec/01 §3 L165 `uop_t`（合计 239 bit，声明 239）----
typedef struct packed {
  logic [0:0] valid;  // src: L169 valid
  logic [39:0] pc;  // src: L170 pc
  logic [31:0] raw32;  // src: L171 raw32
  logic [0:0] is_c;  // src: L172 is_c
  logic [9:0] isop;  // src: L173 isop
  logic [2:0] cls;  // src: L174 cls
  logic [0:0] rs1_en;  // src: L175 rs1_en/rs2_en ｜ R1 展开
  logic [0:0] rs2_en;  // src: L175 rs1_en/rs2_en ｜ R1 展开
  logic [4:0] rs1;  // src: L176 rs1/rs2 ｜ R1 展开
  logic [4:0] rs2;  // src: L176 rs1/rs2 ｜ R1 展开
  logic [0:0] rd_en;  // src: L177 rd_en
  logic [4:0] rd;  // src: L178 rd
  logic [1:0] dst_kind;  // src: L179 dst_kind
  logic [43:0] imm;  // src: L180 imm
  logic [1:0] imm_kind;  // src: L181 imm_kind
  logic [1:0] src_sel;  // src: L182 src_sel
  logic [1:0] dm;  // src: L183 dm
  logic [0:0] sext;  // src: L184 sext
  logic [0:0] is_w;  // src: L185 is_w
  logic [0:0] aq;  // src: L186 aq/rl ｜ R1 展开
  logic [0:0] rl;  // src: L186 aq/rl ｜ R1 展开
  logic [3:0] fm;  // src: L187 fm
  logic [11:0] csr_addr;  // src: L188 csr_addr
  logic [1:0] csr_wr_type;  // src: L189 csr_wr_type
  logic [0:0] pred_taken;  // src: L190 pred_taken
  logic [39:0] pred_target;  // src: L191 pred_target
  logic [7:0] bp_upd_id;  // src: L192 bp_upd_id
  logic [4:0] ftq_id;  // src: L193 ftq_id
  logic [0:0] pre_exc;  // src: L194 pre_exc
  logic [3:0] pre_exc_code;  // src: L195 pre_exc_code
  logic [0:0] bad_va;  // src: L196 bad_va
} uop_t;
localparam int unsigned UOP_T_W = 239;

// ---- spec/01 §3 L203 `rmap_uop_t`（合计 327 bit，声明 327）----
typedef struct packed {
  logic [0:0] valid;  // src: L209 = uop_t（全字段复用） ｜ R2 展开
  logic [39:0] pc;  // src: L209 = uop_t（全字段复用） ｜ R2 展开
  logic [31:0] raw32;  // src: L209 = uop_t（全字段复用） ｜ R2 展开
  logic [0:0] is_c;  // src: L209 = uop_t（全字段复用） ｜ R2 展开
  logic [9:0] isop;  // src: L209 = uop_t（全字段复用） ｜ R2 展开
  logic [2:0] cls;  // src: L209 = uop_t（全字段复用） ｜ R2 展开
  logic [0:0] rs1_en;  // src: L209 = uop_t（全字段复用） ｜ R2 展开
  logic [0:0] rs2_en;  // src: L209 = uop_t（全字段复用） ｜ R2 展开
  logic [0:0] rd_en;  // src: L209 = uop_t（全字段复用） ｜ R2 展开
  logic [4:0] rd;  // src: L209 = uop_t（全字段复用） ｜ R2 展开
  logic [1:0] dst_kind;  // src: L209 = uop_t（全字段复用） ｜ R2 展开
  logic [43:0] imm;  // src: L209 = uop_t（全字段复用） ｜ R2 展开
  logic [1:0] imm_kind;  // src: L209 = uop_t（全字段复用） ｜ R2 展开
  logic [1:0] src_sel;  // src: L209 = uop_t（全字段复用） ｜ R2 展开
  logic [1:0] dm;  // src: L209 = uop_t（全字段复用） ｜ R2 展开
  logic [0:0] sext;  // src: L209 = uop_t（全字段复用） ｜ R2 展开
  logic [0:0] is_w;  // src: L209 = uop_t（全字段复用） ｜ R2 展开
  logic [0:0] aq;  // src: L209 = uop_t（全字段复用） ｜ R2 展开
  logic [0:0] rl;  // src: L209 = uop_t（全字段复用） ｜ R2 展开
  logic [3:0] fm;  // src: L209 = uop_t（全字段复用） ｜ R2 展开
  logic [11:0] csr_addr;  // src: L209 = uop_t（全字段复用） ｜ R2 展开
  logic [1:0] csr_wr_type;  // src: L209 = uop_t（全字段复用） ｜ R2 展开
  logic [0:0] pred_taken;  // src: L209 = uop_t（全字段复用） ｜ R2 展开
  logic [39:0] pred_target;  // src: L209 = uop_t（全字段复用） ｜ R2 展开
  logic [7:0] bp_upd_id;  // src: L209 = uop_t（全字段复用） ｜ R2 展开
  logic [4:0] ftq_id;  // src: L209 = uop_t（全字段复用） ｜ R2 展开
  logic [0:0] pre_exc;  // src: L209 = uop_t（全字段复用） ｜ R2 展开
  logic [3:0] pre_exc_code;  // src: L209 = uop_t（全字段复用） ｜ R2 展开
  logic [0:0] bad_va;  // src: L209 = uop_t（全字段复用） ｜ R2 展开
  logic [5:0] psrc1;  // src: L210 rs1/rs2（架构号 5+5）→ psrc1/psrc2（paddr_t 6+6） ｜ R1 展开（替换 rs1/rs2）
  logic [5:0] psrc2;  // src: L210 rs1/rs2（架构号 5+5）→ psrc1/psrc2（paddr_t 6+6） ｜ R1 展开（替换 rs1/rs2）
  logic [4:0] rs1_arch;  // src: L211 新增 rs1_arch ｜ R3 展开
  logic [5:0] rd_paddr;  // src: L212 新增 rd_paddr ｜ R3 展开
  logic [5:0] rd_old_paddr;  // src: L213 新增 rd_old_paddr ｜ R3 展开
  logic [0:0] rd_is_new;  // src: L214 新增 rd_is_new ｜ R3 展开
  logic [1:0] ckpt_id;  // src: L215 新增 ckpt_id ｜ R3 展开
  logic [0:0] is_br;  // src: L216 新增 is_br ｜ R3 展开
  logic [0:0] needs_ckpt;  // src: L217 新增 needs_ckpt ｜ R3 展开
  logic [63:0] rs1_val;  // src: L218 新增 rs1_val ｜ R3 展开
} rmap_uop_t;
localparam int unsigned RMAP_UOP_T_W = 327;

// ---- spec/01 §3 L224 `rob_alloc_t`（合计 148 bit，声明 148）----
typedef struct packed {
  logic [0:0] valid;  // src: L228 valid
  logic [7:0] slot;  // src: L229 slot
  logic [39:0] pc;  // src: L230 pc
  logic [31:0] raw32;  // src: L231 raw32
  logic [6:0] type_f;  // src: L232 type[6:0] ｜ R4 展开（改名 type→type_f：SV 保留字（IEEE 1800 Annex B）；沿 flow.py 既有约定加 _f 后缀）
  logic [1:0] dst_kind;  // src: L233 dst_kind
  logic [4:0] rd_arch;  // src: L234 rd_arch
  logic [5:0] rd_paddr;  // src: L235 rd_paddr
  logic [5:0] rd_old_paddr;  // src: L236 rd_old_paddr
  logic [1:0] ckpt_id;  // src: L237 ckpt_id
  logic [1:0] priv;  // src: L238 priv
  logic [0:0] lq_v;  // src: L239 lq_v
  logic [5:0] lq_id;  // src: L240 lq_id
  logic [0:0] sq_v;  // src: L241 sq_v
  logic [4:0] sq_id;  // src: L242 sq_id
  logic [4:0] pre_exc;  // src: L243 pre_exc
  logic [11:0] seq;  // src: L244 seq
  logic [0:0] grp_last;  // src: L245 grp_last
  logic [0:0] needs_ckpt;  // src: L246 needs_ckpt
  logic [4:0] ftq_id;  // src: L247 ftq_id
} rob_alloc_t;
localparam int unsigned ROB_ALLOC_T_W = 148;

// ---- spec/01 §3 L252 `rob_entry_t`（合计 143 bit，声明 143）----
typedef struct packed {
  logic [0:0] v;  // src: L258 v
  logic [39:0] pc;  // src: L259 pc
  logic [31:0] raw32;  // src: L260 raw32
  logic [1:0] priv;  // src: L261 priv
  logic [6:0] type_f;  // src: L262 type[6:0] ｜ R4 展开（改名 type→type_f：SV 保留字（IEEE 1800 Annex B）；沿 flow.py 既有约定加 _f 后缀）
  logic [0:0] finish;  // src: L263 finish
  logic [0:0] exc_v;  // src: L264 exc_v
  logic [3:0] exc_code;  // src: L265 exc_code
  logic [0:0] is_intr;  // src: L266 is_intr
  logic [1:0] dst_kind;  // src: L267 dst_kind
  logic [4:0] rd_arch;  // src: L268 rd_arch
  logic [5:0] rd_paddr;  // src: L269 rd_paddr
  logic [5:0] rd_old_paddr;  // src: L270 rd_old_paddr
  logic [1:0] ckpt_id;  // src: L271 ckpt_id
  logic [0:0] lq_v;  // src: L272 lq_v/lq_id ｜ R1 展开
  logic [5:0] lq_id;  // src: L272 lq_v/lq_id ｜ R1 展开
  logic [0:0] sq_v;  // src: L273 sq_v/sq_id ｜ R1 展开
  logic [4:0] sq_id;  // src: L273 sq_v/sq_id ｜ R1 展开
  logic [0:0] mem_done;  // src: L274 mem_done
  logic [0:0] fdirty;  // src: L275 fdirty
  logic [0:0] needs_ckpt;  // src: L276 needs_ckpt
  logic [4:0] ftq_id;  // src: L277 ftq_id
  logic [11:0] seq;  // src: L278 seq
} rob_entry_t;
localparam int unsigned ROB_ENTRY_T_W = 143;

// ---- spec/01 §3 L285 `iq_wr_t`（合计 247 bit，声明 247）----
typedef struct packed {
  logic [0:0] valid;  // src: L291 valid
  logic [1:0] grp;  // src: L292 grp[1:0] ｜ R4 展开
  logic [4:0] iq_slot;  // src: L293 iq_slot
  logic [9:0] isop;  // src: L294 isop
  logic [2:0] cls;  // src: L295 cls
  logic [5:0] psrc1;  // src: L296 psrc1
  logic [5:0] psrc2;  // src: L297 psrc2
  logic [5:0] rd_paddr;  // src: L298 rd_paddr
  logic [0:0] rd_en;  // src: L299 rd_en
  logic [1:0] dst_kind;  // src: L300 dst_kind
  logic [43:0] imm;  // src: L301 imm
  logic [1:0] imm_kind;  // src: L302 imm_kind
  logic [39:0] pc;  // src: L303 pc
  logic [1:0] src_sel;  // src: L304 src_sel
  logic [1:0] dm;  // src: L305 dm
  logic [0:0] sext;  // src: L306 sext
  logic [0:0] is_w;  // src: L307 is_w
  logic [0:0] aq;  // src: L308 aq/rl ｜ R1 展开
  logic [0:0] rl;  // src: L308 aq/rl ｜ R1 展开
  logic [11:0] csr_addr;  // src: L309 csr_addr
  logic [1:0] csr_wr_type;  // src: L310 csr_wr_type
  logic [7:0] rob_id;  // src: L311 rob_id
  logic [11:0] seq;  // src: L312 seq
  logic [0:0] pred_taken;  // src: L313 pred_taken
  logic [39:0] pred_target;  // src: L314 pred_target
  logic [7:0] bp_upd_id;  // src: L315 bp_upd_id
  logic [1:0] ckpt_id;  // src: L316 ckpt_id
  logic [4:0] ftq_id;  // src: L317 ftq_id
  logic [5:0] lq_id;  // src: L318 lq_id
  logic [4:0] sq_id;  // src: L319 sq_id
  logic [4:0] rs1_arch;  // src: L320 rs1_arch
  logic [4:0] rd_arch;  // src: L321 rd_arch
} iq_wr_t;
localparam int unsigned IQ_WR_T_W = 247;

// ---- spec/01 §3 L327 `iq_entry_t`（合计 27 bit，声明 27）----
typedef struct packed {
  logic [0:0] v;  // src: L331 v
  logic [0:0] rdy1;  // src: L332 rdy1/rdy2 ｜ R1 展开
  logic [0:0] rdy2;  // src: L332 rdy1/rdy2 ｜ R1 展开
  logic [5:0] psrc1;  // src: L333 psrc1
  logic [5:0] psrc2;  // src: L334 psrc2
  logic [11:0] age;  // src: L335 age
} iq_entry_t;
localparam int unsigned IQ_ENTRY_T_W = 27;

// ---- spec/01 §3 L347 `wb_t`（合计 80 bit，声明 80）----
typedef struct packed {
  logic [0:0] valid;  // src: L353 valid
  logic [5:0] paddr;  // src: L354 paddr
  logic [63:0] data;  // src: L355 data
  logic [7:0] rob_id;  // src: L356 rob_id
  logic [0:0] src_kind;  // src: L357 src_kind
} wb_t;
localparam int unsigned WB_T_W = 80;

// ---- spec/01 §3 L361 `disp_x_t`（合计 338 bit，声明 338）----
typedef struct packed {
  logic [0:0] valid;  // src: L365 valid
  logic [3:0] eu_id;  // src: L366 eu_id
  logic [9:0] isop;  // src: L367 isop
  logic [63:0] rs1_val;  // src: L368 rs1_val/rs2_val ｜ R1 展开
  logic [63:0] rs2_val;  // src: L368 rs1_val/rs2_val ｜ R1 展开
  logic [43:0] imm;  // src: L369 imm
  logic [39:0] pc;  // src: L370 pc
  logic [7:0] rob_id;  // src: L371 rob_id
  logic [5:0] rd_paddr;  // src: L372 rd_paddr
  logic [1:0] dm;  // src: L373 dm/sext/is_w/aq/rl ｜ R1 展开
  logic [0:0] sext;  // src: L373 dm/sext/is_w/aq/rl ｜ R1 展开
  logic [0:0] is_w;  // src: L373 dm/sext/is_w/aq/rl ｜ R1 展开
  logic [0:0] aq;  // src: L373 dm/sext/is_w/aq/rl ｜ R1 展开
  logic [0:0] rl;  // src: L373 dm/sext/is_w/aq/rl ｜ R1 展开
  logic [11:0] csr_addr;  // src: L374 csr_addr/csr_wr_type ｜ R1 展开
  logic [1:0] csr_wr_type;  // src: L374 csr_addr/csr_wr_type ｜ R1 展开
  logic [5:0] lq_id;  // src: L375 lq_id/sq_id ｜ R1 展开
  logic [4:0] sq_id;  // src: L375 lq_id/sq_id ｜ R1 展开
  logic [0:0] pred_taken;  // src: L376 pred_taken
  logic [39:0] pred_target;  // src: L377 pred_target
  logic [7:0] bp_upd_id;  // src: L378 bp_upd_id
  logic [1:0] ckpt_id;  // src: L379 ckpt_id
  logic [4:0] ftq_id;  // src: L380 ftq_id
  logic [4:0] rs1_arch;  // src: L381 rs1_arch
  logic [4:0] rd_arch;  // src: L382 rd_arch
} disp_x_t;
localparam int unsigned DISP_X_T_W = 338;

// ---- spec/01 §3 L387 `br_resolve_t`（合计 149 bit，声明 149）----
typedef struct packed {
  logic [0:0] valid;  // src: L391 valid
  logic [7:0] rob_id;  // src: L392 rob_id
  logic [39:0] pc;  // src: L393 pc
  logic [0:0] taken_real;  // src: L394 taken_real
  logic [39:0] target_real;  // src: L395 target_real
  logic [0:0] mispred;  // src: L396 mispred
  logic [0:0] bad_va;  // src: L397 bad_va
  logic [0:0] is_jalr_ret;  // src: L398 is_jalr_ret
  logic [0:0] pred_taken;  // src: L399 pred_taken/pred_target ｜ R1 展开
  logic [39:0] pred_target;  // src: L399 pred_taken/pred_target ｜ R1 展开
  logic [7:0] bp_upd_id;  // src: L400 bp_upd_id
  logic [1:0] ckpt_id;  // src: L401 ckpt_id
  logic [4:0] ftq_id;  // src: L402 ftq_id
} br_resolve_t;
localparam int unsigned BR_RESOLVE_T_W = 149;

// ---- spec/01 §3 L406 `mem_req_t`（合计 143 bit，声明 143）----
typedef struct packed {
  logic [0:0] valid;  // src: L410 valid
  logic [1:0] kind;  // src: L411 kind
  logic [39:0] va;  // src: L412 va
  logic [43:0] pa;  // src: L413 pa
  logic [1:0] size;  // src: L414 size
  logic [3:0] amo_op;  // src: L415 amo_op
  logic [0:0] sign_ext;  // src: L416 sign_ext
  logic [7:0] rob_id;  // src: L417 rob_id
  logic [5:0] rd_paddr;  // src: L418 rd_paddr
  logic [5:0] lq_id;  // src: L419 lq_id/sq_id ｜ R1 展开
  logic [4:0] sq_id;  // src: L419 lq_id/sq_id ｜ R1 展开
  logic [1:0] priv;  // src: L420 priv
  logic [0:0] is_fetch;  // src: L421 is_fetch
  logic [5:0] ifetch_offset;  // src: L422 ifetch_offset
  logic [2:0] req_id;  // src: L423 req_id
  logic [11:0] seq;  // src: L424 seq
} mem_req_t;
localparam int unsigned MEM_REQ_T_W = 143;

// ---- spec/01 §3 L431 `mmu_transl_req_t`（合计 66 bit，声明 66）----
typedef struct packed {
  logic [0:0] valid;  // src: L435 valid
  logic [39:0] va;  // src: L436 va
  logic [1:0] kind;  // src: L437 kind
  logic [1:0] priv;  // src: L438 priv
  logic [1:0] rw;  // src: L439 rw
  logic [4:0] ftq_id;  // src: L440 ftq_id
  logic [5:0] lqid;  // src: L441 lqid
  logic [7:0] robid;  // src: L442 robid
} mmu_transl_req_t;
localparam int unsigned MMU_TRANSL_REQ_T_W = 66;

// ---- spec/01 §3 L446 `mmu_transl_rsp_t`（合计 78 bit，声明 78）----
typedef struct packed {
  logic [0:0] valid;  // src: L450 valid
  logic [43:0] pa;  // src: L451 pa
  logic [2:0] super_f;  // src: L452 super ｜ 原名 super（SV 保留字，加 _f 后缀；G1 可改）
  logic [3:0] pma;  // src: L453 pma
  logic [1:0] fault;  // src: L454 fault
  logic [3:0] code;  // src: L455 code
  logic [0:0] tlb_hit;  // src: L456 tlb_hit
  logic [4:0] ftq_id;  // src: L457 ftq_id
  logic [5:0] lqid;  // src: L458 lqid
  logic [7:0] robid;  // src: L459 robid
} mmu_transl_rsp_t;
localparam int unsigned MMU_TRANSL_RSP_T_W = 78;

// ---- spec/01 §3 L465 `miss_req_t`（合计 63 bit，声明 63）----
typedef struct packed {
  logic [0:0] valid;  // src: L469 valid
  logic [43:0] pa;  // src: L470 pa
  logic [3:0] way;  // src: L471 way
  logic [5:0] set;  // src: L472 set
  logic [0:0] is_write;  // src: L473 is_write
  logic [1:0] order;  // src: L474 order
  logic [1:0] kind;  // src: L475 kind
  logic [2:0] req_id;  // src: L476 req_id
} miss_req_t;
localparam int unsigned MISS_REQ_T_W = 63;

// ---- spec/01 §3 L480 `fill_t`（合计 139 bit，声明 139）----
typedef struct packed {
  logic [0:0] valid;  // src: L484 valid
  logic [43:0] pa;  // src: L485 pa
  logic [3:0] way;  // src: L486 way
  logic [7:0] set;  // src: L487 set
  logic [0:0] victim_dirty;  // src: L488 victim_dirty
  logic [63:0] victim;  // src: L489 victim
  logic [1:0] sel;  // src: L490 sel
  logic [2:0] req_id;  // src: L491 req_id
  logic [11:0] seq;  // src: L492 seq
} fill_t;
localparam int unsigned FILL_T_W = 139;

// ---- spec/01 §3 L496 `mshr_wake_t`（合计 9 bit，声明 9）----
typedef struct packed {
  logic [0:0] valid;  // src: L500 valid
  logic [2:0] idx;  // src: L501 idx
  logic [0:0] ok;  // src: L502 ok
  logic [3:0] code;  // src: L503 code
} mshr_wake_t;
localparam int unsigned MSHR_WAKE_T_W = 9;

// ---- spec/01 §3 L511 `icache_rsp_t`（合计 322 bit，声明 322）----
typedef struct packed {
  logic [0:0] valid;  // src: L515 valid
  logic [0:0] err;  // src: L516 err
  logic [3:0] code;  // src: L517 code
  logic [255:0] win;  // src: L518 win
  logic [11:0] seq;  // src: L519 seq
  logic [39:0] win_base_pc;  // src: L520 win_base_pc
  logic [3:0] err_pos;  // src: L521 err_pos
  logic [3:0] err_code;  // src: L522 err_code
} icache_rsp_t;
localparam int unsigned ICACHE_RSP_T_W = 322;

// ---- spec/01 §3 L529 `dcache_rsp_t`（合计 87 bit，声明 87）----
typedef struct packed {
  logic [0:0] valid;  // src: L533 valid
  logic [63:0] data;  // src: L534 data
  logic [5:0] rd_paddr;  // src: L535 rd_paddr
  logic [7:0] robid;  // src: L536 robid
  logic [1:0] fwd_hit;  // src: L537 fwd_hit
  logic [5:0] fwd_src;  // src: L538 fwd_src
} dcache_rsp_t;
localparam int unsigned DCACHE_RSP_T_W = 87;

// ---- spec/01 §3 L542 `commit_t`（合计 355 bit，声明 355）----
typedef struct packed {
  logic [0:0] valid;  // src: L546 valid
  logic [0:0] rd_en;  // src: L547 rd_en
  logic [5:0] rd_paddr;  // src: L548 rd_paddr
  logic [5:0] rd_old_paddr;  // src: L549 rd_old_paddr
  logic [0:0] lq_dealloc;  // src: L550 lq_dealloc/lq_id ｜ R1 展开
  logic [5:0] lq_id;  // src: L550 lq_dealloc/lq_id ｜ R1 展开
  logic [0:0] sq_dealloc;  // src: L551 sq_dealloc/sq_id ｜ R1 展开
  logic [4:0] sq_id;  // src: L551 sq_dealloc/sq_id ｜ R1 展开
  logic [0:0] csr_vld;  // src: L552 csr_vld
  logic [80:0] csr_wr;  // src: L553 csr_wr
  logic [0:0] exc_vld;  // src: L554 exc_vld
  logic [176:0] exc_pkt;  // src: L555 exc_pkt
  logic [0:0] ret_vld;  // src: L556 ret_vld
  logic [48:0] ret_pkt;  // src: L557 ret_pkt
  logic [0:0] wfi_vld;  // src: L558 wfi_vld
  logic [11:0] seq;  // src: L559 seq
  logic [4:0] ftq_id;  // src: L560 ftq_id
} commit_t;
localparam int unsigned COMMIT_T_W = 355;

// ---- spec/01 §3 L569 `excp_t`（合计 177 bit，声明 177）----
typedef struct packed {
  logic [0:0] vld;  // src: L573 vld
  logic [3:0] cause;  // src: L574 cause
  logic [0:0] is_intr;  // src: L575 is_intr
  logic [39:0] epc;  // src: L576 epc
  logic [39:0] tval;  // src: L577 tval
  logic [1:0] from;  // src: L578 from
  logic [1:0] to;  // src: L579 to
  logic [0:0] deleg;  // src: L580 deleg
  logic [5:0] vec_off;  // src: L581 vec_off
  logic [31:0] instr;  // src: L582 instr
  logic [0:0] is_c;  // src: L583 is_c
  logic [0:0] sbe;  // src: L584 sbe
  logic [0:0] cle;  // src: L585 cle
  logic [0:0] svae;  // src: L586 svae
  logic [0:0] va_bad;  // src: L587 va_bad
  logic [0:0] mprv_at_trigger;  // src: L588 mprv_at_trigger
  logic [1:0] mpp_at_trigger;  // src: L589 mpp_at_trigger
  logic [39:0] spep;  // src: L590 spep
} excp_t;
localparam int unsigned EXCP_T_W = 177;

// ---- spec/01 §3 L597 `ret_ctrl_t`（合计 49 bit，声明 49）----
typedef struct packed {
  logic [0:0] vld;  // src: L601 vld
  logic [39:0] epc;  // src: L602 epc
  logic [1:0] pp;  // src: L603 pp
  logic [0:0] pie;  // src: L604 pie
  logic [0:0] ie;  // src: L605 ie
  logic [0:0] mprv_clr;  // src: L606 mprv_clr
  logic [1:0] mode;  // src: L607 mode
  logic [0:0] is_sret;  // src: L608 is_sret
} ret_ctrl_t;
localparam int unsigned RET_CTRL_T_W = 49;

// ---- spec/01 §3 L632 `csr_wr_t`（合计 81 bit，声明 81）----
typedef struct packed {
  logic [0:0] vld;  // src: L636 vld
  logic [11:0] addr;  // src: L637 addr
  logic [1:0] op;  // src: L638 op
  logic [1:0] wdata_sel;  // src: L639 wdata_sel
  logic [63:0] wdata;  // src: L640 wdata
} csr_wr_t;
localparam int unsigned CSR_WR_T_W = 81;

// ---- spec/01 §3 L648 `csrq_entry_t`（合计 152 bit，声明 152）----
typedef struct packed {
  logic [7:0] rob_id;  // src: L652 rob_id
  logic [11:0] addr;  // src: L653 addr
  logic [1:0] op;  // src: L654 op
  logic [1:0] wdata_sel;  // src: L655 wdata_sel
  logic [63:0] src_val;  // src: L656 src_val
  logic [63:0] old_val;  // src: L657 old_val
} csrq_entry_t;
localparam int unsigned CSRQ_ENTRY_T_W = 152;

// ---- spec/01 §3 L676 `x_complete_t`（合计 79 bit，声明 79）----
typedef struct packed {
  logic [0:0] vld;  // src: L680 vld
  logic [7:0] robid;  // src: L681 robid
  logic [5:0] paddr;  // src: L682 paddr
  logic [63:0] data;  // src: L683 data
} x_complete_t;
localparam int unsigned X_COMPLETE_T_W = 79;

// ---- spec/01 §3 L689 `ls_complete_t`（合计 21 bit，声明 21）----
typedef struct packed {
  logic [0:0] vld;  // src: L693 vld
  logic [7:0] robid;  // src: L694 robid
  logic [1:0] fault;  // src: L695 fault
  logic [3:0] code;  // src: L696 code
  logic [5:0] lqid;  // src: L697 lqid
} ls_complete_t;
localparam int unsigned LS_COMPLETE_T_W = 21;

// ---- spec/01 §3 L706 `rt_t`（合计 543 bit，声明 543）----
typedef struct packed {
  logic [0:0] valid;  // src: L712 valid
  logic [39:0] pc;  // src: L713 pc
  logic [31:0] instr;  // src: L714 instr
  logic [0:0] is_c;  // src: L715 is_c
  logic [4:0] rd_idx;  // src: L716 rd_idx
  logic [0:0] rd_wb_en;  // src: L717 rd_wb_en
  logic [63:0] rd_data;  // src: L718 rd_data
  logic [1:0] priv;  // src: L719 priv
  logic [11:0] csr_addr;  // src: L720 csr_addr
  logic [63:0] csr_old;  // src: L721 csr_old
  logic [63:0] csr_new;  // src: L722 csr_new
  logic [0:0] csr_wr_en;  // src: L723 csr_wr_en
  logic [0:0] exc_v;  // src: L724 exc_v
  logic [3:0] exc_cause;  // src: L725 exc_cause
  logic [0:0] is_intr;  // src: L726 is_intr
  logic [0:0] mispred;  // src: L727 mispred
  logic [0:0] is_br;  // src: L728 is_br
  logic [0:0] mem_v;  // src: L729 mem_v
  logic [39:0] mem_addr;  // src: L730 mem_addr
  logic [63:0] mem_wdata;  // src: L731 mem_wdata
  logic [63:0] mem_rdata;  // src: L732 mem_rdata
  logic [1:0] mem_size;  // src: L733 mem_size
  logic [0:0] mem_wr;  // src: L734 mem_wr
  logic [11:0] seq;  // src: L735 seq
  logic [63:0] cycle;  // src: L736 cycle
} rt_t;
localparam int unsigned RT_T_W = 543;

// ---- 未展开行清单（以下行不属任何 struct 块；由 flow.py 的 types-coverage 判据复核）----
// 切分表（if_split.json）无对应行的非标量源行在此登记（fail-closed；当前应为 0 条）。
//   （空：全部非标量源行均已按 ADR-P-2 切分表展开为真实字段）

`endif // VR1_TYPES_SVH
