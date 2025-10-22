import wx
import wx.grid
import requests
import json
import time
import threading
from datetime import datetime
import pandas as pd
from typing import List, Dict, Any, Optional
# matplotlib imports kept if you later want to plot results; currently unused
import matplotlib.pyplot as plt
from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg as FigureCanvas

class DouBaoTester:
    def __init__(self, api_key: str):
        self.api_key = api_key
        # 保留原始 endpoint，请确认这是火山引擎提供的正确域名/路径
        self.base_url = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
    def test_model(self, model_name: str, message: str, system_prompt: Optional[str] = None) -> Dict[str, Any]:
        """测试单个模型的延迟"""
        payload = {
            "model": model_name,
            "messages": [],
            "stream": True
        }
        
        # 添加系统提示词
        if system_prompt:
            payload["messages"].append({
                "role": "system",
                "content": system_prompt
            })
        
        # 添加用户消息
        payload["messages"].append({
            "role": "user",
            "content": message
        })
        
        start_time = time.time()
        first_token_time = None
        full_response = ""
        
        try:
            # Use connect/read timeouts tuple; stream decode_unicode for easier handling
            response = requests.post(
                self.base_url,
                headers=self.headers,
                json=payload,
                stream=True,
                timeout=(10, 60)
            )
            response.raise_for_status()
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                # if server uses SSE style with 'data: ' prefix
                if line.startswith('data: '):
                    data = line[6:]
                else:
                    data = line

                if data == '[DONE]':
                    break

                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    # skip non-json chunks
                    continue

                if 'choices' in chunk and len(chunk['choices']) > 0:
                    delta = chunk['choices'][0].get('delta', {})
                    if 'content' in delta:
                        content = delta['content']
                        if content:
                            if first_token_time is None:
                                first_token_time = time.time() - start_time
                            full_response += content
            
            total_time = time.time() - start_time
            
            return {
                "model": model_name,
                # use None check to allow 0.0 values
                "first_token_time": first_token_time if first_token_time is not None else total_time,
                "total_time": total_time,
                "success": True,
                "response_length": len(full_response),
                "timestamp": datetime.now()
            }
            
        except Exception as e:
            return {
                "model": model_name,
                "first_token_time": None,
                "total_time": None,
                "success": False,
                "error": str(e),
                "timestamp": datetime.now()
            }

class TestWorker(threading.Thread):
    """测试工作线程"""
    def __init__(self, tester: DouBaoTester, models: List[str], message: str, 
                 system_prompt: Optional[str], callback):
        super().__init__()
        self.tester = tester
        self.models = models
        self.message = message
        self.system_prompt = system_prompt
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
            
            result = self.tester.test_model(model, self.message, self.system_prompt)
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
        
        self.init_ui()
        self.Centre()
        
    def init_ui(self):
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # API密钥输入
        api_sizer = wx.BoxSizer(wx.HORIZONTAL)
        api_sizer.Add(wx.StaticText(panel, label="API密钥:"), 0, wx.ALL | wx.ALIGN_CENTER, 5)
        self.api_text = wx.TextCtrl(panel, style=wx.TE_PASSWORD, size=wx.Size(300, -1))
        api_sizer.Add(self.api_text, 1, wx.ALL | wx.EXPAND, 5)
        main_sizer.Add(api_sizer, 0, wx.EXPAND)
        
        # 模型选择
        model_sizer = wx.BoxSizer(wx.HORIZONTAL)
        model_sizer.Add(wx.StaticText(panel, label="测试模型:"), 0, wx.ALL | wx.ALIGN_CENTER, 5)
        
        self.model_list = wx.CheckListBox(panel, choices=[
            "doubao-code-245m-2409",
            "doubao-code-245m-2409-instruct",
            "doubao-code-245m-2409-online",
            "doubao-1-5-245m-2410",
            "doubao-1-5-245m-2410-instruct",
            "doubao-1-5-245m-2410-online",
            "doubao-1-5-245m-2410-vl",
            "doubao-1-5-245m-2410-vl-instruct",
            "doubao-1-5-245m-2410-vl-online",
            "doubao-1-5-245m-2410-search",
            "doubao-1-5-245m-2410-search-instruct",
            "doubao-1-5-245m-2410-search-online"
        ])
        self.model_list.SetMinSize(wx.Size(-1, 120))
        model_sizer.Add(self.model_list, 1, wx.ALL | wx.EXPAND, 5)
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
        
        panel.SetSizer(main_sizer)
        
    def on_start_test(self, event):
        """开始测试"""
        api_key = self.api_text.GetValue().strip()
        if not api_key:
            wx.MessageBox("请输入API密钥", "错误", wx.OK | wx.ICON_ERROR)
            return
            
        selected_models = self.model_list.GetCheckedStrings()
        if not selected_models:
            wx.MessageBox("请选择至少一个测试模型", "错误", wx.OK | wx.ICON_ERROR)
            return
            
        user_input = self.input_text.GetValue().strip()
        if not user_input:
            wx.MessageBox("请输入用户对话内容", "错误", wx.OK | wx.ICON_ERROR)
            return
            
        # 初始化测试器
        self.tester = DouBaoTester(api_key)
        
        # 启动工作线程
        self.worker = TestWorker(
            self.tester,
            selected_models,
            user_input,
            self.prompt_text.GetValue(),
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