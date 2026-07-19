# -*- coding: utf-8 -*-
import os
import json
import time
import requests
import feedparser
import whisper
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

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
    url = f"https://api.weixin.qq.com/cgi-bin/media/upload?access_token={token}&type=image"
    with open(image_path, 'rb') as f:
        resp = requests.post(url, files={"media": f}).json()
    if "media_id" in resp:
        return resp["media_id"]
    else:
        raise Exception(f"图片上传失败: {resp}")

def send_image_message(media_id, token):
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

    prompt = f"""你是一位专业的商业科技播客编辑。请将以下无标点、未分段的转录稿整理为一篇流畅易读的摘要。

播客标题：{title}

写作要求：
1. 全文分成两大部分，分别冠以标题：【今日新闻速览】和【深度解读】。
2. 【今日新闻速览】：每条新闻用 "▎" 开头，后跟该新闻的简短标题（10字以内），换行后再用1-2个自然段落叙述该新闻。新闻之间空一行。格式如下：
   ▎OpenAI 发布 GPT-5
   该公司今日凌晨正式发布了新一代大模型，推理能力大幅提升……
3. 【深度解读】：用 "▎" 开头，后跟本期核心话题的简短标题，换行后先用一两句话点明核心，再分段展开3-5个论述要点（每个要点写为完整、通顺的段落）。
4. 全文务必添加正确的标点符号，让文章读起来像专业新闻简报。
5. 直接输出最终结果，不要加任何解释性文字。

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

# ========== 文字转图片（支持分层加粗） ==========
def text_to_image(text, title, date_str, link, output_path="summary.png"):
    width = 800
    bg_color = (255, 255, 255)
    left_margin = 40
    top_margin = 40
    line_spacing = 8
    max_text_width = width - 2 * left_margin

    try:
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 32)
        font_subtitle = ImageFont.truetype("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 24)  # 用于 ▎ 行
        font_body = ImageFont.truetype("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 20)
    except:
        font_title = ImageFont.truetype("/usr/share/fonts/dejavu/DejaVuSans.ttf", 32)
        font_subtitle = ImageFont.truetype("/usr/share/fonts/dejavu/DejaVuSans.ttf", 24)
        font_body = ImageFont.truetype("/usr/share/fonts/dejavu/DejaVuSans.ttf", 20)

    # 预备绘图以计算尺寸
    temp_img = Image.new('RGB', (width, 100), bg_color)
    draw = ImageDraw.Draw(temp_img)

    def wrap_text(text, font, max_width):
        lines = []
        for paragraph in text.split('\n'):
            if not paragraph:
                lines.append('')
                continue
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

    # 准备所有行，每条行附带其使用的字体和颜色
    # 结构：[(text, font, color), ...]
    all_lines = []

    # 先加头部
    header = f"{title} | {date_str}"
    all_lines.append((header, font_title, (0,0,0)))
    all_lines.append(('', font_body, (0,0,0)))  # 空行

    # 分隔线标记（后面实际画线）
    all_lines.append(('---', font_body, (0,0,0)))

    # 解析正文，识别 ▎ 行
    for section in text.split('\n'):
        stripped = section.strip()
        if not stripped:
            all_lines.append(('', font_body, (0,0,0)))
            continue

        if stripped.startswith('▎'):
            # 重点标题行：加粗字体、深色
            all_lines.append((stripped, font_subtitle, (0,0,0)))
        elif stripped.startswith('【'):
            # 大标题行（如【今日新闻速览】）
            all_lines.append((stripped, font_title, (0,0,0)))
        else:
            # 正文行：正常字体、深灰色
            # 先拆分成多行以适应宽度
            body_lines = wrap_text(stripped, font_body, max_text_width)
            for bl in body_lines:
                all_lines.append((bl, font_body, (60,60,60)))

    # 计算总高度
    total_height = top_margin
    for line_text, font, color in all_lines:
        if line_text == '---':
            total_height += 20  # 分隔线高度
            continue
        if not line_text:
            total_height += font_body.size + line_spacing
            continue
        bbox = draw.textbbox((0,0), line_text, font=font)
        total_height += (bbox[3] - bbox[1]) + line_spacing
    total_height += top_margin

    # 正式创建图片并绘制
    img = Image.new('RGB', (width, total_height), bg_color)
    draw = ImageDraw.Draw(img)

    y = top_margin
    for line_text, font, color in all_lines:
        if line_text == '---':
            # 画分隔线
            y += 5
            draw.line([(left_margin, y), (width - left_margin, y)], fill=(200,200,200), width=2)
            y += 15
            continue
        if not line_text:
            y += font_body.size + line_spacing
            continue
        draw.text((left_margin, y), line_text, fill=color, font=font)
        bbox = draw.textbbox((0,0), line_text, font=font)
        y += (bbox[3] - bbox[1]) + line_spacing

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

    print("4. AI 生成分层摘要...")
    structured = get_structured_summary(raw_text, title)

    if not structured or len(structured) < 10:
        structured = raw_text

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
    try:
        token = get_wechat_token()
        url = f"https://api.weixin.qq.com/cgi-bin/message/custom/send?access_token={token}"
        data = {"touser": WECHAT_OPENID, "msgtype": "text", "text": {"content": f"❌ 处理失败：{str(e)}"}}
        requests.post(url, json=data, headers={"Content-Type": "application/json"})
    except:
        pass
