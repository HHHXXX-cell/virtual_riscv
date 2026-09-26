/***************************************************************
 * sw/tests/direct/dec_probe.S — VR1 定向用例（覆盖缺口补激励）：**保留编码/未激励面探针**
 *
 * 为什么写它（逐条对上未命中项；证据＝`doc/verify/07-m3cov_r2.txt` §B 的
 * `vcover report -details -code sbcef -zeros` 逐行未命中清单，本件头逐条列出 RTL 行号）：
 *   本用例只做一件事：把"**当前实现里已写、但 53 条既有激励从未走到**"的判决面走一遍。
 *   逐条（源行号均在 `rtl/vr1/**`，可核）：
 *     A 组 · `vr1_decode` 的**保留编码 ⇒ illegal** 分支（22 条 `.word`：A1~A22）：
 *       · OPIMM f3=001(SLLI) funct6≠0            → 源 319/323 + 343(All-False)
 *       · OPIMM f3=101(SRLI/SRAI) funct6∉{0,16}  → 源 328/331/334
 *       · OPIMM32 f3=001(SLLIW) bit25=1          → 源 361/365 + 384(All-False)
 *       · OPIMM32 f3=101(SRLIW/SRAIW) bit26=1    → 源 370/373/376 + 384
 *       · OPIMM32 f3=010（保留 funct3）           → 源 380
 *       · OP32 f3=010（保留功能的 funct3）        → 源 411 + 415(All-False)
 *       · OP32 f3=000/001/101 且 funct7=0x02     → 源 398/400、403/404、407/409
 *       · OP   funct7=0x02                       → 源 444/476
 *       · OP   funct7=0x20 且 f3=001（SUB 组非法）→ 源 461/463/465 + 470(All-False)
 *       · BRANCH f3=010（保留）                   → 源 494 + 499(All-False)
 *       · LOAD   f3=111（保留）                   → 源 557 + 563
 *       · STORE  f3=100（保留）                   → 源 581 + 586
 *       · MISC   f3=010（保留）                   → 源 603（并用 FENCE/FENCE.I 命中 600/601/602）
 *       · SYSTEM f3=100（保留）                   → 源 632 + 618
 *       · SYSTEM f3=000 且 funct7≠MRET（保留）    → 源 613/615
 *       · **JALR f3≠000（保留）【本轮补 A19/A20】** → 源 516 的条件 + 523/526 的 else 支
 *       · **MRET 且 rs1≠0／rd≠0（保留字段）【本轮补 A21/A22】** → 源 613 的 `(rs1 == 5'd0)`
 *         ／`(rd == 5'd0)` 两个条件项（此前该两条件项的"假"侧无激励）
 *       合：`vr1_decode` 的 Branches 未命中 31/137 中的绝大多数 ＋ Conditions 未命中 19/34 中的 17 条
 *       （唯一不补：源 338 `OPIMM default`——8 个 funct3 已被 8 个 case 项**穷尽**，结构性不可达；
 *        源 436/441 的 MULDIV default／清理支另见下"组 3/4/5 裁决"＝RTL 实现子集，非保留编码）。
 *     B 组 · `FENCE`/`FENCE.I`（MISC-MEM 面此前**整族未激励**）：源 600（opcode case 项 13/14）、
 *       601/602、`vr1_exu_int` 213（default：非 ALU 成员）、`vr1_core` 774 的 `is_fence_q`。
 *     C 组 · `vr1_exu_int` 的 M 扩展边界（源 197/201/203/204/205/208/213）：除零、有符号溢出、
 *       正常除/余三条支路各走一次（此前 M 面**只被激励过 1 次且恰为除零**，故 `(ss2==0)_0` 未命中）。
 *     D 组 · `vr1_csr` 的**写面**（源 240/241/245/246 的 case 项、171/213 的条件）：mstatus/misa/
 *       mcause/mtval 各写一次（`dir_csr` 只读不写 ⇒ 写 case 的 5 项里 4 项此前未命中）。
 *     E 组 · `vr1_csr` 180 的 `mpp_eff == 2'b10`（保留值回退 M）：写 mstatus.MPP=2'b10 后执行
 *       **独立 MRET**（源 180 的 `_1` 行；spec/10 与 ISS `_xret` 同口径回退，见下"等价性"）。
 *
 * 双向过滤（**本用例的全部编码都逐一核过 RTL 与 ISS 两侧同为非法**，否则会把"两侧口径差"
 *   伪装成激励缺口）：
 *   · 用 `.word` 写**保留编码**：RTL 侧 `vr1_decode` 的对应 else/default 分支判 illegal；
 *     ISS 侧同一条编码亦判 illegal（`iss/vriss/machine.py` 行 341/361/366/382/399/487/526/538
 *     ＋ 行 275(BRANCH f3=2·3)/286(LOAD f3=7)/296(STORE f3≥4)/317(MISC f3∉{0,1})）。
 *   · **仍然排除**（ISS 照规范合法执行 ⇒ 会真出 mismatch；但**不是**"ISS 错"，
 *     而是 RTL 首版实现子集，见下"组 3/4/5 裁决"）：
 *     MULDIV 的 f3∈{001,010,011}（MULH/MULHSU/MULHU）、OP32 funct7=0x01（MULW/DIVW/…）、
 *     SYSTEM f3=011／110／111（CSRRC/CSRRSI/CSRRCI）、SYSTEM funct7=0x08（SRET/WFI）。
 *     它们**不在本件内**，另立列缺条目（`doc/verify/02` §7 的 CC-4／CC-15 行）。
 *
 * 组 3/4/5 裁决（ISS-128 对账的第二半；**本件只登记，不改 ISS**）：上列"仍然排除"的编码
 *   **不是保留编码**，而是 `doc/spec/02` §9.1.6／§9.1.7 的**在册合法成员**
 *   （0x201–0x203／0x210／0x290–0x293／0x302–0x305；RISC-V 亦定义为 M 扩展与 Zicsr 指令：
 *   提取件行 5455–5469、5591）⇒ ISS 侧照规范执行**是对的**；差异源是 RTL 首版只实现 57 条
 *   （`vr1_decode.sv` 头 53–63 行自述"§9.1 其余 30 个成员＝G1-F 后才入面的合法 RV64 指令"）。
 *   把 ISS 收窄成 illegal ＝与 §9.1 成员表相抵 ＋ 抹掉 DUT 真实缺口（红线 R6/R8 精神）
 *   ⇒ **不收窄**；归属＝G1-F／T-2／T-3 实现面增量批（与 `doc/verify/02` §7 同）。
 *
 * ★ 本轮新增四条（A19~A22）的依据＝**ISS-128 消解**（2026-09-26 心跳第 15 轮）：原先把
 *   "JALR f3≠0" 与 "MRET rs1/rd≠0" 列为"两侧口径差"（ISS 缺检查 ⇒ 补激励必 mismatch）——
 *   现按规范裁决为**真保留编码**（JALR 只定义 f3=000：提取件行 2686–2698 编码表逐字段值；
 *   MRET 的 rs1／rd 固定 00000：行 55952–55964；保留译码 UNSPECIFIED／平台可选非法化：
 *   行 2026–2029，本项目平台选择＝RES 一律非法化，`doc/spec/02` §9.3 依据句），**ISS 侧已补齐
 *   检查**（`iss/vriss/machine.py` 的 JALR f3 守卫与 MRET 保留字段守卫；同族先例＝ISS-063 的
 *   SLLI/SRLI funct6 保留位）⇒ 两侧现在同判 illegal，故这四条**可以**进本件（同受 `m2-rv64ui`
 *   的 ISS↔RTL 逐条比对，不放宽）。实跑落盘＝`iss/tests/probes/rr_probe16_iss128_reserved.py`
 *   ＋`rr_out16.txt`；语义回归钉住项＝`iss/tests/test_isa_semantics.py:t_iss128_reserved`。
 *
 * 等价性（为什么 ISS↔RTL 逐条比对仍成立）：
 *   · trap 语义两侧同口径：`mepc ← 故障指令 pc`、`mtval ← 原始 32 bit 指令字`、`mcause ← 2`
 *     （RTL：`vr1_core` 789 行的 `pend_tval_q <= is_none_q ? {8'b0, head.raw32}` ／
 *      `vr1_rob` 272 行的 `tval_q <= {8'b0, alloc_i.raw32}`；ISS：`_take_trap` 的
 *      `MTVAL=u64(tval)` 且非法指令的 tval＝`instr`）。
 *   · "跳过非法指令"＝`mepc += 4` 后 `mret`（handler 逐条用 4 B 定长编码；无 C 扩展 ⇒ 定长 4 B）。
 *   · 该 handler 形态与 `m_smoke`（M1 判据 `rtl-vs-iss` 的激励、30 条 0 mismatch）**同构**，
 *     故 `mret`/`mepc` 写读/csr 写侧 trace 语义已被判过，本件不引入新机制。
 *   · E 组的 MPP=2'b10 写：RTL `MSTATUS_WMASK` 含 MPP（保留 2'b10 ⇒ `mpp_eff` 回退 M）；
 *     ISS `csr_write(MSTATUS)` 用 WMASK_S（不含 MPP ⇒ 该位不动）。两侧**存储值**可能不同，
 *     但本件**不读回 mstatus**，且 trace 列 `csr` 取的是**写前旧值/写后新值**（两侧均为未掩码的
 *     `wdata`）⇒ 等价性不受影响；`mret` 后两侧均落回 M 态继续执行。
 *
 * 判据纪律（红线 R6/R8）：本件**不产任何通过结论**；它与 rv64ui 同为 `MANIFEST.tests` 成员
 *   ⇒ 逐条走 `m2-rv64ui` 的 ISS ＋ RTL ＋ `trace_compare` 三面（列 pc,binary,gpr,csr，不放宽）。
 *   **不进**回归面清单（`run_cmd/rv64ui_testlist.txt` 不含本件）⇒ 回归"同配置"签名不变；
 *   本件只加入覆盖率批清单（`run_cmd/cover_m3_testlist.txt`）。
 *
 * 依据：`doc/verify/07-m3cov_r2.txt`（逐行未命中清单）；`rtl/vr1/ctrl/vr1_decode.sv`（保留编码段
 *   逐行注释）；`doc/spec/02` §9.3（保留编码规则）／§9.1.4（f3=111 载入、f3≥100 存储非法）；
 *   `iss/vriss/machine.py`（ISS 侧同口径的可核实现）；`doc/spec/10` §2/§4.1（trap 进场与 mtval）。
 ***************************************************************/
#include "riscv_test.h"

RVTEST_RV64U
RVTEST_CODE_BEGIN

        /* ---- 安装本用例自己的"跳过非法指令"trap handler（覆盖 env 的 trap_vector 委派面）---- */
        lui     t0, %hi(trap_skip)
        addi    t0, t0, %lo(trap_skip)
        csrw    mtvec, t0

        /* ================= A 组：保留编码 ⇒ illegal（逐条核过两侧）================= */
        /* A1  OPIMM f3=001(SLLI) funct6=000001 —— 保留（RTL 319/323/343；ISS 行 341）*/
        .word   0x04001013
        /* A2  OPIMM f3=101(SRLI/SRAI) funct6=000010 —— 保留（RTL 328/331/334）*/
        .word   0x08005013
        /* A3  OPIMM32 f3=001(SLLIW) imm[5]=1 —— 保留（RTL 361/365/384）*/
        .word   0x0200101B
        /* A4  OPIMM32 f3=101(SRLIW/SRAIW) funct6=000001 —— 保留（RTL 370/373/376/384）*/
        .word   0x0400501B
        /* A5  OPIMM32 f3=010 —— 保留 funct3（RTL 380）*/
        .word   0x0000201B
        /* A6  OP32 f3=010 —— 保留 funct3（RTL 411/415）*/
        .word   0x0000203B
        /* A7  OP32 f3=000 funct7=0000010 —— 保留 funct7（RTL 398/400）*/
        .word   0x0400003B
        /* A8  OP32 f3=001 funct7=0000010 —— 保留 funct7（RTL 403/404）*/
        .word   0x0400103B
        /* A9  OP32 f3=101 funct7=0000010 —— 保留 funct7（RTL 407/409）*/
        .word   0x0400503B
        /* A10 OP   funct7=0000010 —— 保留 funct7（RTL 444/476）*/
        .word   0x04000033
        /* A11 OP   funct7=0100000 且 f3=001 —— SUB 组内的保留 funct3（RTL 461/463/465/470）*/
        .word   0x40001033
        /* A12 BRANCH f3=010 —— 保留（RTL 494/499；ISS 行 275）*/
        .word   0x00002063
        /* A13 LOAD f3=111 —— 保留（RTL 557/563；ISS 行 286）*/
        .word   0x00007003
        /* A14 STORE f3=100 —— 保留（RTL 581/586；ISS 行 296）*/
        .word   0x00004023
        /* A15 MISC-MEM f3=010 —— 保留（RTL 603；ISS 行 317）*/
        .word   0x0000200F
        /* A16 SYSTEM f3=100 —— 保留（RTL 632/618；ISS 行 487）*/
        .word   0x00004073
        /* A17 SYSTEM f3=000 funct7=0000001 —— 保留（RTL 613/615；ISS 行 538）*/
        .word   0x02000073
        /* A18 SYSTEM f3=000 funct7=0011000（＝MRET 的 f7）但 rs2=0 —— 保留（RTL 613 的
           `(rs2 == RS2_MRET)` 项 + 615；ISS 行 527-538：low5≠2 ⇒ 落 ILLEGAL）。
           注：f7=MRET 且 rs1/rd≠0 的两条**本轮已补为 A21/A22**（ISS 侧检查已补齐，
           见本件头"★ 本轮新增四条"）*/
        .word   0x30000073
        /* A19 JALR f3=001 —— 保留 funct3（RTL 516 条件 + 523/526 else 支；ISS 侧 _exec 的
           JALR f3 守卫；位型 rd=x0/rs1=x0/imm=0 ⇒ 只判 funct3 面）*/
        .word   0x00001067
        /* A20 JALR f3=111 —— 保留 funct3（同 A19，取该字段的另一端值）*/
        .word   0x00007067
        /* A21 SYSTEM f7=MRET 且 rs1=1 —— 保留字段（RTL 613 的 `(rs1 == 5'd0)` 项；ISS 侧
           `_sys_op` 的 MRET 保留字段守卫）*/
        .word   0x30208073
        /* A22 SYSTEM f7=MRET 且 rd=1 —— 保留字段（RTL 613 的 `(rd == 5'd0)` 项；同守卫）*/
        .word   0x302000F3

        /* ================= B 组：FENCE / FENCE.I（MISC-MEM 整族此前未激励）================= */
        .word   0x0ff0000f              /* fence iorw,iorw（RTL 600/601；ISS 行 319）*/
        .word   0x0000100f              /* fence.i（RTL 602；ISS 行 319）*/

        /* ================= C 组：M 扩展边界（除零 / 有符号溢出 / 正常）================= */
        li      t2, 0                   /* 除数 0 */
        li      t3, 7
        li      t4, 1
        slli    t5, t4, 63              /* INT64_MIN = 1<<63（shift 面已在 57 条内）*/
        sub     t6, t2, t4              /* -1 */
        div     t4, t3, t2              /* 除零 → 商 = 全 1（RTL 197/199）*/
        rem     t4, t3, t2              /* 除零 → 余 = 被除数（RTL 197/200）*/
        div     t4, t5, t6              /* 有符号溢出 → 商 = 被除数（RTL 201/203）*/
        rem     t4, t5, t6              /* 有符号溢出 → 余 = 0（RTL 201/204）*/
        li      t4, 3                   /* 除数重设 3（上一行的结果 t4 已被覆写，不得复用为除数）*/
        div     t4, t3, t4              /* 正常除 7/3（RTL 205/208 的 `(isop==DIV)_1`）*/
        li      t4, 3
        rem     t4, t3, t4              /* 正常余 7%3（RTL 205/208 的 `(isop==DIV)_0`）*/
        mul     t4, t3, t3              /* MUL 顺带走一次（RTL 187）*/

        /* ================= D 组：CSR 写面（dir_csr 只读不写 ⇒ 写 case 4 项未命中）================= */
        li      t2, 1
        csrw    misa, t2                /* RTL 241（只读常量，写忽略）*/
        csrw    mcause, t2              /* RTL 245 */
        csrw    mtval, t2               /* RTL 246 */
        li      t2, 0x1000              /* MPP = 2'b10（保留值）*/
        csrw    mstatus, t2             /* RTL 240 + 171/213 的掩码面 */

        /* ================= E 组：MPP=2'b10 保留值 + 独立 MRET（RTL 180 的 `_1` 行）================= */
        lui     t3, %hi(mret_back)
        addi    t3, t3, %lo(mret_back)
        csrw    mepc, t3                /* 返回点（避免依赖 env 的 trap_vector）*/
        mret                            /* MPP=2'b10 ⇒ `mpp_eff` 回退 M（spec/10；ISS `_xret` 同口径）*/
mret_back:

        RVTEST_PASS                     /* tohost <- 1（riscv-tests PASS 语义，停机判据）*/
RVTEST_CODE_END

        /* ---- 跳过非法指令的 trap handler：mcause（不判类型，本用例只喂 illegal）→ mepc += 4 → mret ---- */
trap_skip:
        csrr    t0, mcause              /* 读面：rd=t0、rs1=x0 ⇒ 不写 CSR（spec/10 §4.1 CSRRS 语义）*/
        csrr    t1, mepc
        addi    t1, t1, 4               /* 4 B 定长（无 C 扩展）⇒ 跳过故障指令*/
        csrw    mepc, t1                /* CSRRW 恒写（spec/01 §3.19；rd=x0 ⇒ 无 GPR 写回）*/
        mret

RVTEST_DATA_BEGIN
RVTEST_DATA_END
