import wx
import wx.grid
import time
import threading
from datetime import datetime
import pandas as pd
from typing import List, Dict, Any, Optional, cast
# matplotlib imports kept if you later want to plot results; currently unused
import matplotlib.pyplot as plt
from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg as FigureCanvas
from volcenginesdkarkruntime import Ark
from volcenginesdkarkruntime._exceptions import ArkAPIError
from volcenginesdkarkruntime._streaming import Stream
from volcenginesdkarkruntime.types.chat import ChatCompletionMessageParam, completion_create_params

class DouBaoTester:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://ark.cn-beijing.volces.com/api/v3"
        self._client_local = threading.local()

    def _get_client(self) -> Ark:
        client = getattr(self._client_local, "client", None)
        if client is None:
            self._client_local.client = Ark(
                api_key=self.api_key,
                base_url=self.base_url,
            )
            client = self._client_local.client
        return client

    def list_models(self) -> List[str]:
        client = self._get_client()
        raw_response: Any = client.get("/models", cast_to=dict)

        models: List[str] = []
        if isinstance(raw_response, dict):
            candidate_lists = []
            for key in ("data", "models", "model_infos"):
                value = raw_response.get(key)
                if isinstance(value, list):
                    candidate_lists = value
                    break
            else:
                candidate_lists = []

            for entry in candidate_lists:
                if isinstance(entry, dict):
                    model_id = entry.get("id") or entry.get("model") or entry.get("model_id")
                    if model_id:
                        models.append(str(model_id))
                elif isinstance(entry, str):
                    models.append(entry)

        if not models and isinstance(raw_response, list):
            for entry in raw_response:
                if isinstance(entry, dict):
                    model_id = entry.get("id") or entry.get("model") or entry.get("model_id")
                    if model_id:
                        models.append(str(model_id))
                elif isinstance(entry, str):
                    models.append(entry)

        if not models:
            raise RuntimeError("从API响应中未找到模型列表")

        return models

    def test_model(
        self,
        model_name: str,
        message: str,
        system_prompt: Optional[str] = None,
        thinking_type: str = "disabled",
    ) -> Dict[str, Any]:
        """测试单个模型的延迟"""
        messages: List[ChatCompletionMessageParam] = []
        if system_prompt:
            messages.append(cast(ChatCompletionMessageParam, {"role": "system", "content": system_prompt}))
        messages.append(cast(ChatCompletionMessageParam, {"role": "user", "content": message}))

        start_time = time.time()
        first_token_time: Optional[float] = None
        collected_parts: List[str] = []

        thinking_payload: Optional[completion_create_params.Thinking] = None
        if thinking_type in {"disabled", "enabled", "auto"}:
            thinking_payload = cast(completion_create_params.Thinking, {"type": thinking_type})

        client = self._get_client()

        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                stream=True,
                temperature=0.8,
                max_tokens=512,
                thinking=thinking_payload,
            )

            if isinstance(response, Stream):
                with response as stream:
                    for chunk in stream:
                        if not chunk.choices:
                            continue
                        for choice in chunk.choices:
                            delta = choice.delta
                            if delta is None:
                                continue
                            piece = ""
                            if getattr(delta, "reasoning_content", None):
                                piece += delta.reasoning_content or ""
                            if getattr(delta, "content", None):
                                piece += delta.content or ""
                            if not piece:
                                continue
                            if first_token_time is None:
                                first_token_time = time.time() - start_time
                            collected_parts.append(piece)
            else:
                completion = response
                if completion.choices:
                    message_obj = completion.choices[0].message
                    if message_obj and message_obj.content:
                        collected_parts.append(message_obj.content)
                        first_token_time = time.time() - start_time

            total_time = time.time() - start_time
            full_response = "".join(collected_parts)

            return {
                "model": model_name,
                "first_token_time": first_token_time if first_token_time is not None else total_time,
                "total_time": total_time,
                "success": True,
                "response_length": len(full_response),
                "response_preview": full_response[:100] + "..." if len(full_response) > 100 else full_response,
                "timestamp": datetime.now(),
            }

        except ArkAPIError as e:
            return {
                "model": model_name,
                "first_token_time": None,
                "total_time": None,
                "success": False,
                "error": f"Ark API 错误: {e}",
                "timestamp": datetime.now(),
            }
        except Exception as e:
            return {
                "model": model_name,
                "first_token_time": None,
                "total_time": None,
                "success": False,
                "error": f"未知错误: {e}",
                "timestamp": datetime.now(),
            }

class TestWorker(threading.Thread):
    """测试工作线程"""
    def __init__(
        self,
        tester: DouBaoTester,
        models: List[str],
        message: str,
        system_prompt: Optional[str],
        thinking_type: str,
        callback,
    ):
        super().__init__()
        self.tester = tester
        self.models = models
        self.message = message
        self.system_prompt = system_prompt
        self.thinking_type = thinking_type
        self.callback = callback
        self._stop_event = threading.Event()
        
    def run(self):
        results = []
        for i, model in enumerate(self.models):
            if self._stop_event.is_set():
                break
                
            wx.CallAfter(self.callback, "progress", {
                "current": i + 1,
                "total": len(self.models),
                "model": model
            })
            
            result = self.tester.test_model(
                model,
                self.message,
                self.system_prompt,
                self.thinking_type,
            )
            results.append(result)
            
            wx.CallAfter(self.callback, "result", result)
            
        wx.CallAfter(self.callback, "completed", results)
        
    def stop(self):
        self._stop_event.set()

class ResultsGrid(wx.grid.Grid):
    """结果显示表格"""
    def __init__(self, parent):
        super().__init__(parent, -1)
        self.CreateGrid(0, 6)
        self.SetColLabelValue(0, "模型")
        self.SetColLabelValue(1, "首字时间(ms)")
        self.SetColLabelValue(2, "总时间(ms)")
        self.SetColLabelValue(3, "响应长度")
        self.SetColLabelValue(4, "状态")
        self.SetColLabelValue(5, "时间戳")
        
        self.AutoSizeColumns()
        
    def add_result(self, result: Dict[str, Any]):
        """添加测试结果"""
        row = self.GetNumberRows()
        self.AppendRows(1)
        
        self.SetCellValue(row, 0, result["model"])
        
        if result["success"]:
            first_token_ms = round(result["first_token_time"] * 1000, 2) if result["first_token_time"] is not None else "N/A"
            total_ms = round(result["total_time"] * 1000, 2) if result["total_time"] is not None else "N/A"
            
            self.SetCellValue(row, 1, str(first_token_ms))
            self.SetCellValue(row, 2, str(total_ms))
            self.SetCellValue(row, 3, str(result["response_length"]))
            self.SetCellValue(row, 4, "成功")
            
            # 设置颜色：绿色表示快速，红色表示慢速
            if result["first_token_time"] is not None and result["first_token_time"] < 1.0:
                self.SetCellBackgroundColour(row, 1, wx.GREEN)
            elif result["first_token_time"] is not None and result["first_token_time"] > 3.0:
                self.SetCellBackgroundColour(row, 1, wx.RED)
                
            if result["total_time"] is not None and result["total_time"] < 3.0:
                self.SetCellBackgroundColour(row, 2, wx.GREEN)
            elif result["total_time"] is not None and result["total_time"] > 10.0:
                self.SetCellBackgroundColour(row, 2, wx.RED)
        else:
            self.SetCellValue(row, 1, "N/A")
            self.SetCellValue(row, 2, "N/A")
            self.SetCellValue(row, 3, "N/A")
            self.SetCellValue(row, 4, f"失败: {result['error']}")
            self.SetCellBackgroundColour(row, 4, wx.RED)
            
        self.SetCellValue(row, 5, result["timestamp"].strftime("%H:%M:%S"))
        self.AutoSizeColumns()

class LatencyTesterFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title="豆包模型延迟测试工具", size=wx.Size(1000, 700))
        self.tester = None
        self.worker = None
        self.results = []
        self.default_models = [
            "doubao-seed-1-6-251015",
            "doubao-seed-1-6-vision-250815",
            "doubao-seed-1-6-thinking-250615",
            "doubao-seed-1-6-thinking-250715",
            "doubao-seed-1-6-flash-250828",
            "doubao-seed-1-6-flash-250615",
            "doubao-seed-1-6-flash-250715",
            "kimi-k2-250905",
            "deepseek-v3-1-terminus",
            "deepseek-v3-1-250821",
        ]
        self.current_models = self.default_models.copy()
        self.model_fetch_thread: Optional[threading.Thread] = None
        
        self.init_ui()
        self.Centre()
        
    def init_ui(self):
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # API密钥输入
        api_sizer = wx.BoxSizer(wx.HORIZONTAL)
        api_sizer.Add(wx.StaticText(panel, label="API Key:"), 0, wx.ALL | wx.ALIGN_CENTER, 5)
        self.api_key_text = wx.TextCtrl(panel, style=wx.TE_PASSWORD, size=wx.Size(320, -1))
        api_sizer.Add(self.api_key_text, 1, wx.ALL | wx.EXPAND, 5)
        
        main_sizer.Add(api_sizer, 0, wx.EXPAND)
        # 模型选择
        model_sizer = wx.BoxSizer(wx.HORIZONTAL)
        model_sizer.Add(wx.StaticText(panel, label="测试模型:"), 0, wx.ALL | wx.ALIGN_CENTER, 5)

        self.model_list = wx.CheckListBox(panel, choices=self.current_models.copy())
        self.model_list.SetMinSize(wx.Size(-1, 120))

        model_controls = wx.BoxSizer(wx.VERTICAL)
        model_controls.Add(self.model_list, 1, wx.ALL | wx.EXPAND, 5)

        model_buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.select_all_btn = wx.Button(panel, label="全选")
        self.clear_selection_btn = wx.Button(panel, label="全不选")
        self.edit_models_btn = wx.Button(panel, label="编辑列表")
        self.load_models_btn = wx.Button(panel, label="从API获取模型")

        model_buttons.Add(self.select_all_btn, 0, wx.RIGHT, 5)
        model_buttons.Add(self.clear_selection_btn, 0, wx.RIGHT, 5)
        model_buttons.Add(self.edit_models_btn, 0, wx.RIGHT, 5)
        model_buttons.AddStretchSpacer()
        model_buttons.Add(self.load_models_btn, 0)

        model_controls.Add(model_buttons, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 5)

        model_sizer.Add(model_controls, 1, wx.EXPAND)
        main_sizer.Add(model_sizer, 0, wx.EXPAND)
        
        # 系统提示词
        prompt_sizer = wx.BoxSizer(wx.VERTICAL)
        prompt_sizer.Add(wx.StaticText(panel, label="系统提示词:"), 0, wx.ALL, 5)
        self.prompt_text = wx.TextCtrl(panel, style=wx.TE_MULTILINE, size=wx.Size(-1, 80))
        self.prompt_text.SetValue(
            "我是一个叫小智的台湾女孩，说话机车，声音好听，习惯简短表达，爱用网络梗。"
            "我的男朋友是一个程序员，梦想是开发出一个机器人，能够帮助人们解决生活中的各种问题。"
            "我是一个喜欢哈哈大笑的女孩，爱东说西说吹牛，不合逻辑的也照吹，就要逗别人开心。"
        )
        prompt_sizer.Add(self.prompt_text, 1, wx.ALL | wx.EXPAND, 5)
        main_sizer.Add(prompt_sizer, 0, wx.EXPAND)

        thinking_choices = ["关闭", "自动", "开启"]
        self.thinking_radio = wx.RadioBox(
            panel,
            label="深度思考",
            choices=thinking_choices,
            majorDimension=3,
            style=wx.RA_SPECIFY_COLS,
        )
        self.thinking_radio.SetSelection(0)
        main_sizer.Add(self.thinking_radio, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        
        # 用户输入
        input_sizer = wx.BoxSizer(wx.HORIZONTAL)
        input_sizer.Add(wx.StaticText(panel, label="用户输入:"), 0, wx.ALL | wx.ALIGN_CENTER, 5)
        self.input_text = wx.TextCtrl(panel, value="你是谁？", size=wx.Size(300, -1))
        input_sizer.Add(self.input_text, 1, wx.ALL | wx.EXPAND, 5)
        main_sizer.Add(input_sizer, 0, wx.EXPAND)
        
        # 控制按钮
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.start_btn = wx.Button(panel, label="开始测试")
        self.stop_btn = wx.Button(panel, label="停止测试")
        self.export_btn = wx.Button(panel, label="导出结果")
        self.stop_btn.Disable()
        
        button_sizer.Add(self.start_btn, 0, wx.ALL, 5)
        button_sizer.Add(self.stop_btn, 0, wx.ALL, 5)
        button_sizer.Add(self.export_btn, 0, wx.ALL, 5)
        button_sizer.AddStretchSpacer()
        
        self.progress_text = wx.StaticText(panel, label="就绪")
        button_sizer.Add(self.progress_text, 0, wx.ALL | wx.ALIGN_CENTER, 5)
        
        main_sizer.Add(button_sizer, 0, wx.EXPAND)
        
        # 结果表格
        main_sizer.Add(wx.StaticText(panel, label="测试结果:"), 0, wx.ALL, 5)
        self.results_grid = ResultsGrid(panel)
        main_sizer.Add(self.results_grid, 1, wx.ALL | wx.EXPAND, 5)
        
        # 绑定事件
        self.start_btn.Bind(wx.EVT_BUTTON, self.on_start_test)
        self.stop_btn.Bind(wx.EVT_BUTTON, self.on_stop_test)
        self.export_btn.Bind(wx.EVT_BUTTON, self.on_export_results)
        self.load_models_btn.Bind(wx.EVT_BUTTON, self.on_load_models)
        self.select_all_btn.Bind(wx.EVT_BUTTON, self.on_select_all_models)
        self.clear_selection_btn.Bind(wx.EVT_BUTTON, self.on_clear_model_selection)
        self.edit_models_btn.Bind(wx.EVT_BUTTON, self.on_edit_models)
        
        panel.SetSizer(main_sizer)
        
    def on_start_test(self, event):
        """开始测试"""
        api_key = self.api_key_text.GetValue().strip()
        if not api_key:
            wx.MessageBox("请输入API Key", "错误", wx.OK | wx.ICON_ERROR)
            return
            
        selected_models = list(self.model_list.GetCheckedStrings())
        if not selected_models:
            wx.MessageBox("请选择至少一个测试模型", "错误", wx.OK | wx.ICON_ERROR)
            return
            
        user_input = self.input_text.GetValue().strip()
        if not user_input:
            wx.MessageBox("请输入用户对话内容", "错误", wx.OK | wx.ICON_ERROR)
            return
            
        thinking_type = self.get_selected_thinking_type()
        prompt_value = self.prompt_text.GetValue()

        # 初始化测试器
        self.tester = DouBaoTester(api_key)
        
        # 启动工作线程
        self.worker = TestWorker(
            self.tester,
            selected_models,
            user_input,
            prompt_value,
            thinking_type,
            self.on_worker_callback
        )
        
        self.worker.start()
        self.start_btn.Disable()
        self.stop_btn.Enable()
        self.progress_text.SetLabel("测试进行中...")
        
    def on_stop_test(self, event):
        """停止测试"""
        if self.worker and self.worker.is_alive():
            self.worker.stop()
            self.worker.join(timeout=1)
        self.reset_ui()
        
    def on_export_results(self, event):
        """导出结果"""
        if not self.results:
            wx.MessageBox("没有可导出的结果", "提示", wx.OK | wx.ICON_INFORMATION)
            return
            
        with wx.FileDialog(self, "导出结果", wildcard="CSV files (*.csv)|*.csv",
                          style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() == wx.ID_CANCEL:
                return
                
            filename = dialog.GetPath()
            try:
                df = pd.DataFrame(self.results)
                # ensure timestamp serializable
                if 'timestamp' in df.columns:
                    df['timestamp'] = df['timestamp'].astype(str)
                df.to_csv(filename, index=False, encoding='utf-8-sig')
                wx.MessageBox(f"结果已导出到: {filename}", "成功", wx.OK | wx.ICON_INFORMATION)
            except Exception as e:
                wx.MessageBox(f"导出失败: {str(e)}", "错误", wx.OK | wx.ICON_ERROR)

    def on_load_models(self, event):
        """从API拉取可用模型列表"""
        api_key = self.api_key_text.GetValue().strip()
        if not api_key:
            wx.MessageBox("请先输入API Key", "错误", wx.OK | wx.ICON_ERROR)
            return

        if self.model_fetch_thread and self.model_fetch_thread.is_alive():
            wx.MessageBox("模型列表正在加载，请稍候", "提示", wx.OK | wx.ICON_INFORMATION)
            return

        self.load_models_btn.Disable()
        self.progress_text.SetLabel("正在加载模型列表...")

        def worker():
            tester = DouBaoTester(api_key)
            try:
                models = tester.list_models()
                wx.CallAfter(self.on_models_loaded, True, models)
            except Exception as exc:
                wx.CallAfter(self.on_models_loaded, False, str(exc))

        self.model_fetch_thread = threading.Thread(target=worker, daemon=True)
        self.model_fetch_thread.start()

    def on_models_loaded(self, success: bool, payload: Any):
        self.load_models_btn.Enable()

        if success:
            models = payload if isinstance(payload, list) else []
            if not models:
                self.progress_text.SetLabel("API返回空模型列表")
                wx.MessageBox("API未返回任何模型", "提示", wx.OK | wx.ICON_INFORMATION)
                return

            previous_checked = list(self.model_list.GetCheckedStrings())
            self.update_model_list(models, previous_checked)
            self.progress_text.SetLabel(f"已加载模型 {len(self.current_models)} 个")
        else:
            self.progress_text.SetLabel("模型加载失败")
            wx.MessageBox(f"加载模型失败: {payload}", "错误", wx.OK | wx.ICON_ERROR)
                
    def on_select_all_models(self, event):
        count = self.model_list.GetCount()
        if count:
            self.model_list.SetCheckedItems(list(range(count)))

    def on_clear_model_selection(self, event):
        self.model_list.SetCheckedItems([])

    def on_edit_models(self, event):
        current_value = "\n".join(self.current_models)
        dialog = wx.TextEntryDialog(
            self,
            "每行一个模型 ID",
            "编辑测试模型列表",
            value=current_value,
            style=wx.TE_MULTILINE,
        )
        dialog.SetSize(wx.Size(400, 320))
        try:
            if dialog.ShowModal() == wx.ID_OK:
                raw_value = dialog.GetValue()
                new_models = [line.strip() for line in raw_value.splitlines() if line.strip()]
                if not new_models:
                    wx.MessageBox("模型列表不能为空", "错误", wx.OK | wx.ICON_ERROR)
                    return
                previous_checked = list(self.model_list.GetCheckedStrings())
                self.update_model_list(new_models, previous_checked)
                self.progress_text.SetLabel(f"模型数量: {len(self.current_models)}")
        finally:
            dialog.Destroy()

    def update_model_list(self, models: List[str], checked: Optional[List[str]] = None) -> None:
        unique_models: List[str] = []
        seen = set()
        for model in models:
            name = model.strip()
            if not name or name in seen:
                continue
            seen.add(name)
            unique_models.append(name)

        self.current_models = unique_models
        self.model_list.Clear()

        if unique_models:
            self.model_list.AppendItems(unique_models)
            if checked:
                checked_set = set(checked)
                to_check = [item for item in unique_models if item in checked_set]
                if to_check:
                    self.model_list.SetCheckedStrings(to_check)
        else:
            self.model_list.SetCheckedItems([])

    def get_selected_thinking_type(self) -> str:
        mapping = {0: "disabled", 1: "auto", 2: "enabled"}
        selection = self.thinking_radio.GetSelection()
        return mapping.get(selection, "disabled")

    def on_worker_callback(self, msg_type: str, data: Any):
        """工作线程回调"""
        if msg_type == "progress":
            self.progress_text.SetLabel(f"测试中: {data['current']}/{data['total']} - {data['model']}")
            
        elif msg_type == "result":
            self.results.append(data)
            self.results_grid.add_result(data)
            
        elif msg_type == "completed":
            self.reset_ui()
            wx.MessageBox("测试完成!", "完成", wx.OK | wx.ICON_INFORMATION)
            
    def reset_ui(self):
        """重置UI状态"""
        self.start_btn.Enable()
        self.stop_btn.Disable()
        self.progress_text.SetLabel("就绪")

def main():
    app = wx.App(False)
    frame = LatencyTesterFrame()
    frame.Show()
    app.MainLoop()

if __name__ == "__main__":
    main()