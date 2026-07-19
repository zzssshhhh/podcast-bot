# -*- coding: utf-8 -*-
import os
import json
import time
import requests
import feedparser
import whisper
from datetime import datetime

WECHAT_APPID = os.environ['WECHAT_APPID']
WECHAT_APPSECRET = os.environ['WECHAT_APPSECRET']
WECHAT_OPENID = os.environ['WECHAT_OPENID']
RSS_URL = os.environ['RSS_URL']
DASHSCOPE_API_KEY = os.environ.get('ALI_ACCESS_KEY_ID', '')

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
    if len(content_bytes) <= MAX_CONTENT_BYTES:
        return send_single_message(content)
    chunks = []
    start = 0
    while start < len(content_bytes):
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
    headers = {'User-Agent': 'Mozilla/5.0'}
    resp = requests.get(RSS_URL, headers=headers, timeout=30)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    if not feed.entries:
        raise Exception("RSS 中无节目")
    latest = feed.entries[0]
    audio_url = None
    for enc in latest.enclosures:
        if 'audio' in enc.type or enc.href.endswith(('.m4a', '.mp3')):
            audio_url = enc.href
            break
    return latest.title, audio_url, latest.link

def download_audio(url, save_path="episode.m4a"):
    r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, stream=True)
    r.raise_for_status()
    with open(save_path, 'wb') as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)
    return save_path

def transcribe_audio(file_path):
    model = whisper.load_model("small")
    return model.transcribe(file_path, language="zh")["text"]

# ==================== AI 结构化摘要 ====================
def generate_structured_summary(raw_text, title):
    print(f"DashScope Key 长度: {len(DASHSCOPE_API_KEY)}, 前4位: {DASHSCOPE_API_KEY[:4] if DASHSCOPE_API_KEY else '无'}")
    if not DASHSCOPE_API_KEY or len(DASHSCOPE_API_KEY) < 10:
        print("未配置有效的 DashScope API Key，返回原文。")
        return raw_text

    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
        "Content-Type": "application/json"
    }

    prompt = f"""你是一位专业的播客摘要编辑。请将以下无标点、未分段的播客转录稿，整理成适合阅读的结构化摘要。

播客标题：{title}

整理要求：
1. 添加正确的标点符号。
2. 按照节目结构分为两大部分：
   【今日新闻速览】：用列表列出每条新闻的5W（何人、何事、何时、何地、为何），如果某些要素缺失则不写。
   【深度解读】：提炼出核心论点，然后用3-5个要点概括论证过程。
3. 直接输出最终结果，不要加任何解释性文字。

转录稿如下：
{raw_text}"""

    data = {
        "model": "qwen-plus",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 3000
    }

    try:
        resp = requests.post(url, headers=headers, json=data, timeout=90)
        print(f"AI 响应状态码: {resp.status_code}")
        result = resp.json()
        if "choices" in result:
            content = result["choices"][0]["message"]["content"]
            print(f"AI 返回内容长度: {len(content)}")
            return content
        else:
            print(f"AI 调用异常: {result}")
            return raw_text
    except Exception as e:
        print(f"AI 请求失败: {e}")
        return raw_text

# ==================== 主流程 ====================
try:
    print("1. 获取最新节目...")
    title, audio_url, link = get_latest_episode()
    print(f"标题: {title}")

    print("2. 下载音频...")
    audio_file = download_audio(audio_url)

    print("3. 语音转文字...")
    raw_transcript = transcribe_audio(audio_file)
    print(f"转写字数: {len(raw_transcript)}")

    print("4. AI 生成结构化摘要...")
    summary = generate_structured_summary(raw_transcript, title)

    full_msg = f"""📻 {title} | {datetime.now().strftime('%Y年%m月%d日')}

🔗 {link}

{summary}"""

    print("5. 推送...")
    send_long_message(full_msg.strip())

except Exception as e:
    import traceback
    traceback.print_exc()
    send_single_message(f"❌ 处理失败：{str(e)}")
