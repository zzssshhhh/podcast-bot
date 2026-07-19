# -*- coding: utf-8 -*-
import os
import json
import time
import requests
import feedparser
import whisper
from datetime import datetime

# 从 GitHub Secrets 读取配置
WECHAT_APPID = os.environ['WECHAT_APPID']
WECHAT_APPSECRET = os.environ['WECHAT_APPSECRET']
WECHAT_OPENID = os.environ['WECHAT_OPENID']
RSS_URL = os.environ['RSS_URL']
ALI_ACCESS_KEY_ID = os.environ.get('ALI_ACCESS_KEY_ID', '')
ALI_ACCESS_KEY_SECRET = os.environ.get('ALI_ACCESS_KEY_SECRET', '')

MAX_CONTENT_BYTES = 2000

# ==================== 微信推送 ====================
def get_wechat_token():
    url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={WECHAT_APPID}&secret={WECHAT_APPSECRET}"
    return requests.get(url).json().get("access_token")

def send_single_message(content):
    token = get_wechat_token()
    url = f"https://api.weixin.qq.com/cgi-bin/message/custom/send?access_token={token}"
    data = {"touser": WECHAT_OPENID, "msgtype": "text", "text": {"content": content}}
    resp = requests.post(url, data=json.dumps(data, ensure_ascii=False).encode('utf-8'),
                         headers={'Content-Type': 'application/json; charset=utf-8'}).json()
    print(resp)
    return resp.get("errcode") == 0

def send_long_message(content):
    content_bytes = content.encode('utf-8')
    total_len = len(content_bytes)
    if total_len <= MAX_CONTENT_BYTES:
        return send_single_message(content)
    chunks = []
    start = 0
    while start < total_len:
        end = start + MAX_CONTENT_BYTES
        chunk_bytes = content_bytes[start:end]
        while True:
            try:
                chunks.append(chunk_bytes.decode('utf-8'))
                break
            except UnicodeDecodeError:
                end -= 1
                chunk_bytes = content_bytes[start:end]
        start = end
    success = True
    for chunk in chunks:
        if not send_single_message(chunk):
            success = False
        time.sleep(0.5)
    return success

# ==================== 播客获取 ====================
def get_latest_episode():
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; PodcastBot/1.0)'}
    resp = requests.get(RSS_URL, headers=headers, timeout=30)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    if not feed.entries:
        raise Exception("RSS 中没有找到任何节目")
    latest = feed.entries[0]
    audio_url = None
    for enclosure in latest.enclosures:
        if 'audio' in enclosure.type or enclosure.href.endswith(('.m4a', '.mp3')):
            audio_url = enclosure.href
            break
    return latest.title, audio_url, latest.link

def download_audio(url, save_path="episode.m4a"):
    headers = {'User-Agent': 'Mozilla/5.0'}
    r = requests.get(url, headers=headers, stream=True)
    r.raise_for_status()
    with open(save_path, 'wb') as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
    return save_path

def transcribe_audio(file_path):
    print("正在加载 Whisper 模型...")
    model = whisper.load_model("small")
    print("开始转写...")
    return model.transcribe(file_path, language="zh")["text"]

# ==================== AI 摘要（通义千问） ====================
def get_ali_token():
    """获取阿里云通用访问令牌（用于通义千问）"""
    # 通义千问 DashScope API 直接使用 API Key 即可，不需要额外 token
    # 如果 AccessKey 是 DashScope 兼容格式，直接返回
    return ALI_ACCESS_KEY_ID

def generate_summary(raw_text, title):
    """调用通义千问，生成带标点、分段的摘要"""
    if not ALI_ACCESS_KEY_ID:
        return raw_text  # 没有配置密钥则返回原文

    api_key = ALI_ACCESS_KEY_ID
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

    prompt = f"""你是一位专业的播客编辑。请对以下播客转录稿进行处理，输出带标点、分段的文字稿。

播客标题：{title}

要求：
1. 添加适当的标点符号（句号、逗号、问号等）
2. 按新闻话题自然分段，每条新闻之间空一行
3. 保持原意，不要添加或删减内容
4. 直接输出处理后的文字，不要加任何说明

转录稿如下：
{raw_text}"""

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "qwen-plus",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4000
    }

    try:
        resp = requests.post(url, headers=headers, json=data, timeout=60)
        result = resp.json()
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"AI 摘要失败: {e}")
        return raw_text

# ==================== 主流程 ====================
try:
    print("1. 获取最新播客信息...")
    title, audio_url, link = get_latest_episode()
    print(f"标题: {title}")

    print("2. 下载音频...")
    audio_file = download_audio(audio_url)

    print("3. 语音转文字...")
    raw_transcript = transcribe_audio(audio_file)
    print(f"转写字数: {len(raw_transcript)}")

    print("4. AI 添加标点并分段...")
    formatted_text = generate_summary(raw_transcript, title)

    print("5. 推送...")
    full_message = f"""📻 {title} | {datetime.now().strftime('%Y年%m月%d日')}

🔗 {link}

{formatted_text}"""

    send_long_message(full_message.strip())

except Exception as e:
    import traceback
    traceback.print_exc()
    send_single_message(f"❌ 处理失败：{str(e)}")
