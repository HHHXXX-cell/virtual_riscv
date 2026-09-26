// ==========================================================================
// rtl/vr1/include/vr1_pkg.sv — VR1 参数/类型包（本包**只包裹**，不含新内容）
//
// 依据：
//   · doc/spec/00 §4 L109：参数「命名与 rtl/vr1/include/vr1_pkg.sv 的 parameter 一一对应」
//     ⇒ 本包是全项目参数名的 SV 侧唯一载体；
//   · doc/spec/00 §4 表头（本生成件自述）：「G1 冻结后本文件由 rtl/vr1/include/vr1_pkg.sv 包裹（命名约定）」；
//   · doc/spec/01 §3：28 个接口 struct（成员级位域唯一权威源）；
//   · doc/decisions/G1-I-最小冻结清单.md §2.1（23 型）/ §2.5（参数集）：G1-I 冻结面。
//
// 组成 = `include 两个**生成件**（不是复制！）：
//   · `vr1_params.svh` ← `python script/flow.py params`（源＝doc/spec/00 §4）
//   · `vr1_types.svh`  ← `python script/flow.py types` （源＝doc/spec/01 §3）
// 生成件**禁手改**（两件头部均写「DO NOT EDIT BY HAND」）；改值/改字段一律改 spec 后重跑生成器。
//
// 禁（清单 §1.3）：不得在本文件手抄/复制生成件内容；不得新增、改名或自造任何接口类型。
// 编译顺序：本单元必须先于任何 `import vr1_pkg::*` 的模块（见 filelist/rtl.f 的表头注释）。
// 冻结状态：G1-I 已签（R0 2026-09-25；`state/freeze.json` rtl_write_authorized=true）⇒ rtl/ 进实现期。
// ==========================================================================
`ifndef VR1_PKG_SV
`define VR1_PKG_SV

package vr1_pkg;
  // 参数件先于类型件（类型件成员位宽为字面量，不引用参数；顺序仅为可读性）
  `include "vr1_params.svh"
  `include "vr1_types.svh"
endpackage

`endif // VR1_PKG_SV
