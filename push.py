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

# 微信客服消息单条文本最大字节数（留一点余量，设为2000字节）
MAX_CONTENT_BYTES = 2000

def get_wechat_token():
    url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={WECHAT_APPID}&secret={WECHAT_APPSECRET}"
    resp = requests.get(url).json()
    return resp.get("access_token")

def send_single_message(content):
    """发送单条消息，返回是否成功"""
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
        print("单条推送成功")
        return True
    else:
        print(f"单条推送失败: {resp}")
        return False

def send_long_message(content):
    """将长文本按字节拆分，分多条发送"""
    # 先将字符串转为 UTF-8 字节
    content_bytes = content.encode('utf-8')
    total_len = len(content_bytes)
    print(f"消息总字节数: {total_len}")

    if total_len <= MAX_CONTENT_BYTES:
        # 没超限，直接发送
        return send_single_message(content)

    # 拆分成多段，每段不超过 MAX_CONTENT_BYTES 字节
    chunks = []
    start = 0
    while start < total_len:
        end = start + MAX_CONTENT_BYTES
        # 避免切断中文字符：找到该段末尾最后一个合法的 UTF-8 字符边界
        chunk_bytes = content_bytes[start:end]
        # 尝试解码，如果失败说明截断了多字节字符，需要向前回退
        while True:
            try:
                chunk_text = chunk_bytes.decode('utf-8')
                break
            except UnicodeDecodeError:
                # 截断了，将 end 减1
                end -= 1
                chunk_bytes = content_bytes[start:end]
        chunks.append(chunk_text)
        start = end

    print(f"拆分为 {len(chunks)} 条消息发送")
    success = True
    for i, chunk in enumerate(chunks):
        # 可选：标记第几条，但不做强制
        # chunk = f"({i+1}/{len(chunks)})\n{chunk}"
        if not send_single_message(chunk):
            success = False
        # 短暂间隔，避免请求过快
        time.sleep(0.5)
    return success

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
    model = whisper.load_model("small")
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

    # 构建完整的推送内容（可以加上标题和链接）
    full_message = f"""📻 {title} | {datetime.now().strftime('%Y年%m月%d日')}

🔗 {episode_link}

📝 【文字稿】
{transcript}

（AI结构化摘要功能将在下一步实现）"""

    print("4. 推送消息到微信...")
    send_long_message(full_message.strip())

except Exception as e:
    import traceback
    traceback.print_exc()
    send_single_message(f"❌ 处理失败：{str(e)}")

   
