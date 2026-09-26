// tb/unit/types_pkg.sv — 接口类型单源的"编译在环"冒烟（不含任何 DUT 功能逻辑）
//
// 判据：`vlog` 报 Errors: 0，且 `-- Compiling` 计数 ≥3（类型包 + 参数包 + 接口骨架）。
//   - 生成件 rtl/vr1/include/vr1_types.svh 由 doc/spec/01 §3 struct 表机械生成（禁手改）；
//     解析复用 script/width_check.py，打包顺序见该头部的 ADR-1（自决项，已进 G1 评审 list）。
//   - 本文件同时 `include` 参数包，验证"参数 + 类型 + 接口骨架"三者能一起被工具接受——
//     这是 G1 冻结前唯一能做的、对接口定义的真实工具校验。
// 本文件不是 DUT、不进 filelist/rtl.f（冻结前 rtl/ 只允许 include/*.svh 生成件）。
package vr1_params_pkg;
  `include "vr1_params.svh"
endpackage

package vr1_types_pkg;
  `include "vr1_types.svh"
endpackage

module vr1_types_smoke;
  import vr1_params_pkg::*;
  import vr1_types_pkg::*;

  // 只为强制 elaboration 引用（避免"未使用"优化掉类型），不构造任何功能逻辑
  rt_t      rt_dbg;
  commit_t  commit_dbg;
  uop_t     uop_dbg;
  csr_wr_t  csr_wr_dbg;

  initial begin
    if (XLEN != 64)
      $fatal(1, "XLEN=%0d，期望 64", XLEN);
    if (RT_T_W <= 0)
      $fatal(1, "rt_t 宽度非法：%0d", RT_T_W);
    rt_dbg = '0;
    commit_dbg = '0;
    uop_dbg = '0;
    csr_wr_dbg = '0;
    $display("[types_smoke] rt_t=%0d commit_t=%0d uop_t=%0d csr_wr_t=%0d (params XLEN=%0d)",
             RT_T_W, COMMIT_T_W, UOP_T_W, CSR_WR_T_W, XLEN);
  end
endmodule
