//=============================================================================
// filelist/tb_fetch_smoke.f — M1-S1 取指冒烟的 **TB 侧**编译单元清单
//   （**必须与 filelist/rtl.f 同批编译**，且必须排在 rtl.f 的单元之后）
// 路径一律相对仓库根（vlog 从仓库根调用）
// 分层（本表＝本冒烟的 TB 侧单元；**DUT 侧单元一律取自 filelist/rtl.f，不在本表重复列举**）：
//   单元1  tb/unit/fetch_smoke_tb.sv —— 编译/仿真冒烟 ＋ 内存桩（例化 vr1_core；产 S1 判据②证据行）
// 判据（script/flow.py 的 rtl-fetch-win）：
//   同批 vlog 的 `-- Compiling` 计数 == filelist/rtl.f 条目数 + 本表条目数，
//   且 vlog/vopt/vsim 逐段 `Errors: 0` ＋ 证据行（n_fail=0 / 窗基址 32 B 对齐 / raw32 == 镜像常量）。
// 为什么不入 filelist/rtl.f：`rtl.f` 表头明写「本表**不含 tb/**」（域分离），且 `rtl-compile` 的
//   不变式是「计数 == rtl.f 条目数」——把 TB 件塞进去会同时破坏不变式与域分离。
// 为什么不入 filelist/tb_unit.f：那份清单是 **DUT 无关**的 TB 单元件（单独编译即成立）；本件例化
//   `vr1_core`，**单独编译不成单元**，只能与 rtl.f 同批编。
// 注意：沙箱独占见 AGENTS.md §5 规则 10；新增单元件时按序追加，且保持 `+incdir+` 行在前。
//=============================================================================
+incdir+rtl/vr1/include

tb/unit/fetch_smoke_tb.sv
