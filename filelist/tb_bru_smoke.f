//=============================================================================
// filelist/tb_bru_smoke.f — M1-S3 分支解析冒烟的 **TB 侧**编译单元清单
//   （**必须与 filelist/rtl.f 同批编译**，且必须排在 rtl.f 的单元之后）
// 路径一律相对仓库根（vlog 从仓库根调用）
// 分层（本表＝本冒烟的 TB 侧单元；**DUT 侧单元一律取自 filelist/rtl.f，不在本表重复列举**）：
//   单元1  tb/unit/bru_smoke_tb.sv —— 直连 `vr1_bru` 的定向冒烟（`disp_x_t` 6 lane → `br_resolve_t`）
// 判据（本片＝**阶段证据**；`rtl-bru-win` 判据的注册归 S3 收口批——S3 判据② 的 `gpr` 面需执行/提交面）：
//   同批 vlog 的 `-- Compiling` 计数 == filelist/rtl.f 条目数 + 本表条目数，且 vlog/vopt/vsim
//   逐段 `Errors: 0` ＋ 逐案证据行（`[bru_smoke] case=… valid=… mispred=… target=… ok=…`）＋ `PASS` 行。
// 为什么不入 filelist/rtl.f：`rtl.f` 表头明写「本表**不含 tb/**」（域分离），且 `rtl-compile` 的
//   不变式是「计数 == rtl.f 条目数」——把 TB 件塞进去会同时破坏不变式与域分离。
// 为什么不入 filelist/tb_unit.f（DUT 无关的 TB 单元件清单）：本件例化 `vr1_bru`（引用 `vr1_pkg`），
//   **单独编译不成单元**，只能与 rtl.f 同批编。
// 注意：沙箱独占见 AGENTS.md §5 规则 10；新增单元件时按序追加，且保持 `+incdir+` 行在前。
//=============================================================================
+incdir+rtl/vr1/include

tb/unit/bru_smoke_tb.sv
