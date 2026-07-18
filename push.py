import os
import requests
from datetime import datetime

# 从 GitHub Secrets 读取配置
WECHAT_APPID = os.environ['WECHAT_APPID']
WECHAT_APPSECRET = os.environ['WECHAT_APPSECRET']
WECHAT_OPENID = os.environ['WECHAT_OPENID']

def get_wechat_token():
    url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={WECHAT_APPID}&secret={WECHAT_APPSECRET}"
    resp = requests.get(url).json()
    return resp.get("access_token")

def send_wechat_message(content):
    token = get_wechat_token()
    url = f"https://api.weixin.qq.com/cgi-bin/message/custom/send?access_token={token}"
    data = {
        "touser": WECHAT_OPENID,
        "msgtype": "text",
        "text": {"content": content}
    }
    resp = requests.post(url, json=data).json()
    print(resp)
    if resp.get("errcode") == 0:
        print("推送成功")
    else:
        print(f"推送失败: {resp}")

# 模拟摘要内容（稍后替换成真实逻辑）
summary = f"""
📻 声动早咖啡 | {datetime.now().strftime('%Y年%m月%d日')}

【今日新闻速览】
• OpenAI 发布 GPT-5，推理与多模态能力显著提升
• 特斯拉 Cybertruck 交付量同比增长 20%
• 字节跳动剪映上线 AI 视频生成功能

【深度解读：AI 搜索能否取代传统搜索？】
▸ 核心变化：从“给出链接”转向“直接生成答案”
▸ 技术路线一：基于传统搜索索引 + 大模型总结（微软 Bing）
▸ 技术路线二：自建索引的纯 AI 搜索（Perplexity）
▸ 主要挑战：准确性与实时信息更新的平衡
▸ 趋势判断：短期难完全取代，但正在快速蚕食市场份额
"""

send_wechat_message(summary.strip())
