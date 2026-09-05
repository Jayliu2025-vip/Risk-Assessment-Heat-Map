# 2026-09-05 桌面打包与内存优化记录

本轮增加 GLM、Kimi 通用 API 预设，并在保持本地 OCR、PDF/DOCX 识别和人工复核流程的前提下，缩减桌面分发体积与主进程的专用提交内存。旧安装包、旧程序目录保留，新产物放在独立的 `size-20260905` 目录。

## 结果

单位均为 MiB（1 MiB = 1,048,576 字节）。内存测试使用本机、独立临时状态目录和 `--synthetic-smoke`；只处理仓库的虚构报告，通过本机模拟服务验证识别与工作簿写入，不使用真实报告、API 密钥或付费接口。

| 指标 | 原有分发版本 | 本轮候选版本 | 变化 |
|---|---:|---:|---|
| 安装包 | 119.46 | 103.06 | 减少约 13.7% |
| 解压后程序目录 | 293.90 | 247.34 | 减少约 15.8% |
| 合成识别主进程：采样专用提交内存峰值 | 755.01 | 363.99 | 减少约 51.8% |
| 合成识别主进程：物理内存峰值 | 434.98 | 432.57 | 基本不变 |

上述内存指标来自单次对比，Windows `GetProcessMemoryInfo` 每 30 ms 采样。专用提交内存取采样最大值，物理内存峰值使用系统记录的 `PeakWorkingSetSize`；采样可能漏掉短时提交峰值。测试未启动 WebView2 界面，不代表打开软件后的全部进程树内存，也不是大型真实报告的峰值保证。运行时间不用于本轮性能结论。

## 已实施

- 服务商选项新增 GLM（智谱开放平台）和 Kimi，自动填写地址、默认模型及官方密钥指南，保持图片发送默认关闭。GLM 支持 `/api/paas/v4`，Kimi/GLM 官方接口使用服务商默认采样参数，避免强制 `temperature=0`。
- 在桌面入口导入 NumPy 之前，将 `OPENBLAS_NUM_THREADS` 默认设为 `1`。项目的 Excel 与风险评估流程不需要按 CPU 数量分配大量 BLAS 线程缓冲区；明确设置过该环境变量的用户或管理员仍保留其设置。
- 从 PyInstaller 分发中排除桌面页面不用的 Matplotlib，以及约 29.45 MiB 的 OpenCV FFmpeg 视频解码 DLL。保留 OpenCV 图像处理、OCR 模型、PDF 引擎和原有经过审计的 CPython/Tcl 运行库。
- Inno Setup 增加 `DistRoot` 编译参数，允许从单独的候选程序目录生成安装包，方便与旧版本并存比较。

没有更换 OCR 模型或降低页面渲染清晰度。没有移除本地 OCR，也没有以云端识别替代离线能力。

## 验证

- 专用 Python 3.13.14 环境：`python -m unittest discover -s tests -q`，260 项通过。
- Playwright：`npx playwright test tests/e2e --workers=1`，13 项通过。
- 候选程序：`--synthetic-smoke` 通过，覆盖本地 OCR、模拟模型和版本化工作簿输出。
- 分发来源审计：`PACKAGED_DISTRIBUTION_AUDIT_OK detected=44 locked=58`。
- 打包后的 HTML、JavaScript、CSS 与工作区源文件 SHA-256 一致。
- Inno Setup 编译成功；`git diff --check` 通过。

本记录对应最初的优化候选包。后续 `v1.2.1` 另行修正安装版本号、快捷方式位置和旧依赖清理，并完成了当前主机的安装、升级与卸载验收，见[发行说明](releases/v1.2.1.md)和[验收证据](releases/v1.2.1-acceptance.json)。最初候选包的哈希与后续正式安装包不同；无 Python 干净电脑验证仍未覆盖。

## 产物与复现

- 候选程序目录：`dist/size-20260905/RiskAssessmentHeatMap/`
- 候选安装包：`installer-output/size-20260905/RiskAssessmentHeatMap-Setup-20260905-optimized.exe`
- 安装包 SHA-256：`E2063CF106B7795988F57B671D74E25FD736F1DB755B6AB6DAC2F6E6FF63C033`
- 对比旧安装包 SHA-256：`BE9673322FB6AADA0BF5DA0E4398FB477E8DDB58AC1DAA407233CABFDCB55BFF`

候选构建使用项目规定的精简 `PATH`，仅含专用 Python、基础 Python、其 `DLLs` 目录与 Windows 系统目录。PyInstaller 参数为 `--workpath build/size-clean-20260905 --distpath dist/size-20260905 --noconfirm`，编译输入为 `packaging/risk_heatmap_desktop.spec`。随后执行 `tools/export_third_party_licenses.py` 的 `--audit-analysis`、`--audit-collect` 和 `--dist-root` 校验。

Inno Setup 从 `packaging/RiskAssessmentHeatMap.iss` 编译，`/DDistRoot` 指向候选程序绝对路径，`/O` 指向候选安装包输出目录，`/F` 使用带日期的独立文件名。没有改变压缩算法，仍使用 LZMA2 和实心压缩。

## 后续建议

继续使用 PyInstaller `onedir` + Inno Setup。改成 `onefile` 不会消除 Python、OCR 和图像处理依赖，还会增加启动时的临时解包；更换打包器不能保证降低运行内存。

若下一轮优先降低任务管理器中的实际物理内存，应先测量 WebView2 与 OCR 各阶段的完整进程树，再评估将 OCR 放入按需启动、处理完退出的子进程。这样有利于识别完成后回收内存，但不保证降低识别期间的系统总峰值。更轻的 OCR 模型或较低图像分辨率必须先验证中文扫描件识别质量；本轮没有采用这些会影响结果质量的方案。

参考：[PyInstaller 运行方式](https://pyinstaller.org/en/stable/operating-mode.html)、[OpenBLAS 线程设置](https://github.com/OpenMathLib/OpenBLAS#setting-the-number-of-threads-using-environment-variables)、[Inno Setup 压缩说明](https://jrsoftware.org/ishelp/topic_setup_compression.htm)。
