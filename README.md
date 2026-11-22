# 金融新闻雷达

基于 AkShare、DeepSeek、SQLite 和 Streamlit 的金融新闻分析应用。把新闻拆解为事件事实、可能影响路径和待核实事项，辅助读者快速了解新闻内容。

## 在线访问

部署在 Streamlit Community Cloud 上，打开链接即可使用，无需安装环境。

## 本地运行

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env    # 填入 DEEPSEEK_API_KEY
streamlit run app.py
```

不配置密钥时仍可查看仓库内的演示数据，抓取新闻和 AI 分析会提示失败原因。

## 功能概览

- 四个主视图：今日简报、新闻流、跟踪复盘、数据概览
- 最多关注 10 只 A 股，RSS/Atom 支持国内媒体预设来源与自定义地址
- 按代码、来源、时间、情绪、影响分数、关键词筛选，结果可导出 CSV
- 个股时间线、多来源同日报道聚合、跨新闻的后续观察事项跟踪
- 事件类型与影响范围分布、按来源的入库与分析完成度统计
- AI 分析包含情绪方向、1–5 影响分数、事件类型、影响路径、置信度与待核实事项；分数不代表股价涨跌
- 保留来源、发布时间与原文链接，便于回查

## 说明

部署平台使用临时文件系统，SQLite 数据可能在重新部署后重置；仓库内的演示库随代码快照提供。抓取与 AI 分析依赖外部服务，不是实时行情终端，也不提供投资建议。
