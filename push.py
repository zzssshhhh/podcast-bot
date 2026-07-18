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
    # 增加 User-Agent 防止被拒
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; PodcastBot/1.0)'}
    
    # 先用 requests 下载 RSS 内容，再用 feedparser 解析（更可靠）
    resp = requests.get(RSS_URL, headers=headers, timeout=30)
    resp.raise_for_status()
    
    feed = feedparser.parse(resp.content)
    
    if not feed.entries:
        raise Exception("RSS 中没有找到任何节目，可能链接需要更新")
    
    latest = feed.entries[0]
    title = latest.title
    link = latest.link
    
    # 查找音频链接
    audio_url = None
    for enclosure in latest.enclosures:
        if 'audio' in enclosure.type or enclosure.href.endswith('.m4a') or enclosure.href.endswith('.mp3'):
            audio_url = enclosure.href
            break
    
    if not audio_url:
        # 备用：从 links 中找音频
        for link_item in latest.links:
            href = link_item.get('href', '')
            if '.m4a' in href or '.mp3' in href:
                audio_url = href
                break
    
    if not audio_url:
        # 最后备用：从 description 中找
        import re
        match = re.search(r'https?://[^\s<>"]+\.(?:m4a|mp3)', latest.description)
        if match:
            audio_url = match.group(0)
    
    return title, audio_url, link

# 主流程
try:
    print("开始获取 RSS...")
    title, audio_url, episode_link = get_latest_episode()
    print(f"标题: {title}")
    print(f"音频链接: {audio_url}")
    print(f"节目链接: {episode_link}")
    
    if not audio_url:
        send_wechat_message(f"⚠️ 找到节目「{title}」，但未提取到音频链接，请检查 RSS 结构。")
    else:
        summary = f"""
📻 声动早咖啡 | {datetime.now().strftime('%Y年%m月%d日')}

✅ 最新一期已找到：
🎙️ 标题：{title}
🔗 节目链接：{episode_link}
🎧 音频链接：{audio_url}

（下一步将自动转写此音频并生成摘要）
"""
        send_wechat_message(summary.strip())

except Exception as e:
    import traceback
    print("❌ 发生异常：")
    traceback.print_exc()
    send_wechat_message(f"❌ 获取播客信息失败：{str(e)}")
