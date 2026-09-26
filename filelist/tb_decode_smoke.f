//=============================================================================
// filelist/tb_decode_smoke.f — M1-S2 译码冒烟的 **TB 侧**编译单元清单
//   （**必须与 filelist/rtl.f 同批编译**，且必须排在 rtl.f 的单元之后）
// 路径一律相对仓库根（vlog 从仓库根调用）
// 分层（本表＝本冒烟的 TB 侧单元；**DUT 侧单元一律取自 filelist/rtl.f，不在本表重复列举**）：
//   单元1  tb/unit/decode_unit_smoke_tb.sv   —— 件 1：直连 vr1_decode 的单元冒烟（反压面）
//   单元2  tb/unit/decode_stream_smoke_tb.sv —— 件 2：经 vr1_core 全前端喂真镜像的流冒烟
// （两件原同处 `decode_smoke_tb.sv` 一个文件；一个文件含两个顶层模块会让「`-- Compiling`
//   计数 == 清单条目数」的不变式失效 ⇒ 2026-09-26 按模块边界拆成两个单模块文件，内容逐字未改）
// 判据（script/flow.py 的 rtl-decode-win）：
//   同批 vlog 的 `-- Compiling` 计数 == filelist/rtl.f 条目数 + 本表条目数，且 vlog/vopt/vsim
//   逐段 `Errors: 0` ＋ 证据行（逐条 uop pc/raw32/isop、反压不丢不重、非法路径行数、一窗一 drain）。
// 为什么不入 filelist/rtl.f：`rtl.f` 表头明写「本表**不含 tb/**」（域分离），且 `rtl-compile` 的
//   不变式是「计数 == rtl.f 条目数」——把 TB 件塞进去会同时破坏不变式与域分离。
// 为什么不入 filelist/tb_unit.f（DUT 无关的 TB 单元件清单）：本件例化 `vr1_core`/`vr1_decode`，
//   **单独编译不成单元**，只能与 rtl.f 同批编。
// 注意：沙箱独占见 AGENTS.md §5 规则 10；新增单元件时按序追加，且保持 `+incdir+` 行在前。
//=============================================================================
+incdir+rtl/vr1/include

tb/unit/decode_unit_smoke_tb.sv
tb/unit/decode_stream_smoke_tb.sv
