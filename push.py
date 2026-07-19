# -*- coding: utf-8 -*-
import os
import json
import time
import requests
import feedparser
import whisper
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

# 环境变量
WECHAT_APPID = os.environ['WECHAT_APPID']
WECHAT_APPSECRET = os.environ['WECHAT_APPSECRET']
WECHAT_OPENID = os.environ['WECHAT_OPENID']
RSS_URL = os.environ['RSS_URL']
DASHSCOPE_API_KEY = os.environ.get('DASHSCOPE_API_KEY', '')

# ========== 微信接口 ==========
def get_wechat_token():
    url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={WECHAT_APPID}&secret={WECHAT_APPSECRET}"
    return requests.get(url).json().get("access_token")

def upload_image(image_path, token):
    """上传图片素材，返回 media_id"""
    url = f"https://api.weixin.qq.com/cgi-bin/media/upload?access_token={token}&type=image"
    with open(image_path, 'rb') as f:
        resp = requests.post(url, files={"media": f}).json()
    if "media_id" in resp:
        return resp["media_id"]
    else:
        raise Exception(f"图片上传失败: {resp}")

def send_image_message(media_id, token):
    """发送图片消息"""
    url = f"https://api.weixin.qq.com/cgi-bin/message/custom/send?access_token={token}"
    data = {
        "touser": WECHAT_OPENID,
        "msgtype": "image",
        "image": {"media_id": media_id}
    }
    resp = requests.post(url, data=json.dumps(data, ensure_ascii=False).encode('utf-8'),
                         headers={"Content-Type": "application/json"}).json()
    print("图片推送响应:", resp)
    return resp.get("errcode") == 0

# ========== 播客获取与转写 ==========
def get_latest_episode():
    headers = {'User-Agent': 'Mozilla/5.0'}
    resp = requests.get(RSS_URL, headers=headers, timeout=30)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    if not feed.entries:
        raise Exception("RSS 无内容")
    latest = feed.entries[0]
    audio_url = None
    for enc in latest.enclosures:
        if 'audio' in enc.type or enc.href.endswith(('.m4a','.mp3')):
            audio_url = enc.href
            break
    return latest.title, audio_url, latest.link

def download_audio(url, path="episode.m4a"):
    r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, stream=True)
    r.raise_for_status()
    with open(path, 'wb') as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)
    return path

def transcribe_audio(path):
    model = whisper.load_model("small")
    return model.transcribe(path, language="zh")["text"]

# ========== AI 结构化摘要 ==========
def get_structured_summary(raw_text, title):
    if not DASHSCOPE_API_KEY or len(DASHSCOPE_API_KEY) < 10:
        print("未配置 DashScope API Key，返回原文。")
        return raw_text

    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
        "Content-Type": "application/json"
    }

    prompt = f"""你是专业播客编辑。将以下无标点、未分段的转录稿整理为结构化摘要。

播客标题：{title}

要求：
1. 添加正确标点符号。
2. 结构化为两部分：
   【今日新闻速览】：每条新闻用5W要素简要列出（要素缺失则跳过）。
   【深度解读】：先点明核心论点，再用3-5个要点概括论证过程。
3. 直接输出最终结果，不加任何解释。

转录稿：
{raw_text}"""

    data = {
        "model": "qwen-plus",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 3000
    }

    try:
        resp = requests.post(url, headers=headers, json=data, timeout=90)
        result = resp.json()
        if "choices" in result:
            return result["choices"][0]["message"]["content"]
        else:
            print(f"AI 错误: {result}")
            return raw_text
    except Exception as e:
        print(f"AI 异常: {e}")
        return raw_text

# ========== 文字转图片 ==========
def text_to_image(text, title, date_str, link, output_path="summary.png"):
    """将结构化摘要渲染为图片，返回图片路径"""
    # 图片尺寸与背景
    width = 800
    bg_color = (255, 255, 255)
    img = Image.new('RGB', (width, 100), bg_color)
    draw = ImageDraw.Draw(img)

    # 加载中文字体
    try:
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 32)
        font_body = ImageFont.truetype("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 20)
    except:
        # 备用字体
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)
        font_body = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)

    # 准备头部信息
    header = f"{title} | {date_str}"
    # 先计算所有文本高度以确定图片总高度
    # 由于中文字体较复杂，我们用一种简单方法：逐行绘制并动态扩展图片
    # 这里采用先计算预估高度，再创建足够大的画布

    # 分行函数
    def wrap_text(text, font, max_width):
        lines = []
        for paragraph in text.split('\n'):
            if not paragraph:
                lines.append('')
                continue
            # 单段内按字符处理
            line = ""
            for char in paragraph:
                test_line = line + char
                bbox = draw.textbbox((0,0), test_line, font=font)
                if bbox[2] - bbox[0] > max_width:
                    lines.append(line)
                    line = char
                else:
                    line = test_line
            if line:
                lines.append(line)
        return lines

    # 布局参数
    left_margin = 40
    top_margin = 40
    line_spacing = 8
    max_text_width = width - 2 * left_margin

    # 准备各部分文字
    # 标题
    title_lines = wrap_text(header, font_title, max_text_width)
    # 正文
    body_lines = []
    # 分割出正文各部分，保持空行
    for section in text.split('\n'):
        if section.strip() == '':
            body_lines.append('')
        else:
            body_lines.extend(wrap_text(section, font_body, max_text_width))

    # 计算总高度
    title_height = len(title_lines) * (font_title.size + line_spacing)
    body_height = len(body_lines) * (font_body.size + line_spacing)
    total_height = top_margin + title_height + 20 + body_height + top_margin + 30  # 留白

    # 创建正确高度的图片
    img = Image.new('RGB', (width, total_height), bg_color)
    draw = ImageDraw.Draw(img)

    # 绘制标题
    y = top_margin
    for line in title_lines:
        draw.text((left_margin, y), line, fill=(0,0,0), font=font_title)
        y += font_title.size + line_spacing

    # 分隔线
    y += 10
    draw.line([(left_margin, y), (width - left_margin, y)], fill=(200,200,200), width=2)
    y += 15

    # 绘制正文
    for line in body_lines:
        if line == '':
            y += font_body.size + line_spacing
            continue
        draw.text((left_margin, y), line, fill=(50,50,50), font=font_body)
        y += font_body.size + line_spacing

    img.save(output_path)
    return output_path

# ========== 主流程 ==========
try:
    print("1. 获取最新节目...")
    title, audio_url, link = get_latest_episode()
    print(f"标题: {title}")

    print("2. 下载音频...")
    audio_path = download_audio(audio_url)

    print("3. 转写...")
    raw_text = transcribe_audio(audio_path)
    print(f"转写字数: {len(raw_text)}")

    print("4. AI 生成结构化摘要...")
    structured = get_structured_summary(raw_text, title)

    # 如果 AI 返回空或失败，回退到原文
    if not structured or len(structured) < 10:
        structured = raw_text

    # 准备日期字符串
    date_str = datetime.now().strftime('%Y年%m月%d日')

    print("5. 生成图片...")
    img_path = text_to_image(structured, title, date_str, link)

    print("6. 推送图片...")
    token = get_wechat_token()
    media_id = upload_image(img_path, token)
    send_image_message(media_id, token)

    print("全部完成！")

except Exception as e:
    import traceback
    traceback.print_exc()
    # 尝试发送文本错误消息
    try:
        token = get_wechat_token()
        url = f"https://api.weixin.qq.com/cgi-bin/message/custom/send?access_token={token}"
        data = {"touser": WECHAT_OPENID, "msgtype": "text", "text": {"content": f"❌ 处理失败：{str(e)}"}}
        requests.post(url, json=data, headers={"Content-Type": "application/json"})
    except:
        pass
