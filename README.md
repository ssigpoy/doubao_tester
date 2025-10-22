# doubao_latency_tester

豆包模型延迟测试工具

一个用于测量并对比“豆包”模型（DouBao）响应延迟的桌面 GUI 工具。基于 wxPython 提供简单的界面，可以对多个模型发起请求并记录首字/总耗时、响应长度与状态，支持导出 CSV 结果。

## 主要特性

- 支持批量测试多个模型的首字时间（TTFB-like）与总耗时
- 实时显示进度与每个模型的结果
- 支持自定义 system prompt 与用户输入
- 导出结果为 CSV 以便后续分析

## 要求

- Python 3.8+
- 依赖见项目 `pyproject.toml`：wxPython、requests、volcengine、pandas、matplotlib

## 安装（推荐）

在 Windows PowerShell 下，建议使用虚拟环境：

```powershell
# 在项目根目录执行
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
# 使用 pyproject.toml 安装依赖并把本包安装为可执行脚本
python -m pip install .
```

如果你想本地可编辑安装（开发模式）：

```powershell
python -m pip install -e .
```

注意：Windows 上安装 `wxPython` 有时需要匹配系统与 Python 版本的 wheel。如果 pip 直接安装出错，请参考官方 wxPython 安装说明下载对应 wheel 后再本地安装。

## 运行

有两种常见运行方式：

1. 直接用 Python 运行源码（适合还未安装包时）

```powershell
# 激活虚拟环境后
python main.py
```

2. 安装为命令行脚本后使用 entry point（pyproject 中定义了 `doubao_tester` 脚本）

```powershell
# 安装后
doubao_tester
```

运行后会打开一个 GUI 窗口：

- 在 "API 密钥" 输入框填入你的 API Key（必须）
- 勾选要测试的模型（至少一个）
- 可在 "系统提示词" (System prompt) 填写上下文提示
- 在 "用户输入" 填写要发送给模型的内容
- 点击 “开始测试” 开始批量测延迟，完成后可导出 CSV

## 使用示例

- 测试单个模型并导出结果：运行 GUI，输入 API Key、选择模型、输入对话，开始测试，点击导出结果并保存为 CSV。

## 导出结果

测试完成后，点击界面上的 “导出结果”，选择保存路径，程序将以 UTF-8 带 BOM（utf-8-sig）格式保存 CSV，方便在 Excel 中直接打开。

## 常见问题

- 无法安装 wxPython：请确认 Python 版本与 wxPython wheel 匹配；可以先升级 pip，再尝试单独安装合适版本的 wxPython。
- 请求超时或网络错误：检查 API Key 与网络连接，py 文件中对请求使用了 stream 模式与超时设置，可根据需要调整代码中的 timeout 值。

## 开发者说明

- 入口实现位于项目源码（本仓库）中的 `main.py`，主函数名为 `main()`，pyproject 中也配置了 `doubao_tester = doubao_tester.main:main` 作为 entry point（根据安装方式可能需调整包结构以匹配）。
- 代码使用 requests 的流式响应解析 SSE 风格的数据块，记录首字时间与总时间。

## 贡献

欢迎提交 issue 或 PR。提交变更前请确保：

- 新增代码遵循项目的编码风格
- 重要改动提供简短说明与复现步骤

## 许可

本仓库未在 pyproject 中指定开源许可证。若需要开源发布，请添加 LICENSE 文件并在 pyproject 中声明许可条款。

---

如果你希望我把 README 翻译为英文、补充更详细的开发文档（例如如何运行单元测试、添加 CI、或修正 entry point 与包结构），告诉我我会继续完善。