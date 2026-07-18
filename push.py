# -*- coding: utf-8 -*-
import os
import json
import requests
import feedparser
import whisper
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
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; PodcastBot/1.0)'}
    resp = requests.get(RSS_URL, headers=headers, timeout=30)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    
    if not feed.entries:
        raise Exception("RSS 中没有找到任何节目")
    
    latest = feed.entries[0]
    title = latest.title
    link = latest.link
    audio_url = None
    
    for enclosure in latest.enclosures:
        if 'audio' in enclosure.type or enclosure.href.endswith('.m4a') or enclosure.href.endswith('.mp3'):
            audio_url = enclosure.href
            break
    
    return title, audio_url, link

def download_audio(url, save_path="episode.m4a"):
    """下载音频文件"""
    headers = {'User-Agent': 'Mozilla/5.0'}
    r = requests.get(url, headers=headers, stream=True)
    r.raise_for_status()
    with open(save_path, 'wb') as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
    return save_path

def transcribe_audio(file_path):
    """使用 Whisper 转写音频"""
    print("正在加载 Whisper 模型...")
    model = whisper.load_model("small")  # small 模型速度快，准确度不错
    print("开始转写，请耐心等待...")
    result = model.transcribe(file_path, language="zh")
    return result["text"]

# ========== 主流程 ==========
try:
    print("1. 获取最新播客信息...")
    title, audio_url, episode_link = get_latest_episode()
    print(f"标题: {title}")
    print(f"音频: {audio_url}")

    print("2. 下载音频文件...")
    audio_file = download_audio(audio_url)

    print("3. 语音转文字...")
    transcript = transcribe_audio(audio_file)

    # 由于微信消息有长度限制，先发送前1500字
    if len(transcript) > 1500:
        transcript_preview = transcript[:1500] + "\n...（内容过长，已截断）"
    else:
        transcript_preview = transcript

    summary = f"""
📻 {title} | {datetime.now().strftime('%Y年%m月%d日')}

🔗 {episode_link}

📝 【文字稿预览】
{transcript_preview}

（AI结构化摘要功能将在下一步实现）
"""
    send_wechat_message(summary.strip())

except Exception as e:
    import traceback
    traceback.print_exc()
    send_wechat_message(f"❌ 处理失败：{str(e)}")
    
