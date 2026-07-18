# -*- coding: utf-8 -*-
import os
import json
import requests
import feedparser
from datetime import datetime

# 从 GitHub Secrets 读取配置
WECHAT_APPID = os.environ['WECHAT_APPID']
WECHAT_APPSECRET = os.environ['WECHAT_APPSECRET']
WECHAT_OPENID = os.environ['WECHAT_OPENID']
RSS_URL = os.environ['RSS_URL']

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
    resp = requests.post(
        url,
        data=json.dumps(data, ensure_ascii=False).encode('utf-8'),
        headers={'Content-Type': 'application/json; charset=utf-8'}
    ).json()
    print(resp)
    if resp.get("errcode") == 0:
        print("推送成功")
    else:
        print(f"推送失败: {resp}")

def get_latest_episode():
    """从 RSS 获取最新一期播客信息"""
    feed = feedparser.parse(RSS_URL)
    if not feed.entries:
        raise Exception("RSS 中没有找到任何节目")
    latest = feed.entries[0]
    title = latest.title
    link = latest.link
    # 查找音频链接（通常位于 enclosures 或 links 中）
    audio_url = None
    for enclosure in latest.enclosures:
        if 'audio' in enclosure.type:
            audio_url = enclosure.href
            break
    if not audio_url:
        # 备用：从 links 中寻找
        for link_item in latest.links:
            if 'audio' in link_item.type:
                audio_url = link_item.href
                break
    return title, audio_url, link

# 主流程
try:
    title, audio_url, episode_link = get_latest_episode()
    summary = f"""
📻 声动早咖啡 | {datetime.now().strftime('%Y年%m月%d日')}

✅ 最新一期已找到：
🎙️ 标题：{title}
🔗 节目链接：{episode_link}
🎧 音频链接：{audio_url if audio_url else '未找到'}

（下一步将自动转写此音频并生成摘要）
"""
    send_wechat_message(summary.strip())
except Exception as e:
    send_wechat_message(f"❌ 获取播客信息失败：{str(e)}")
