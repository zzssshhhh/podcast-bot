# -*- coding: utf-8 -*-
import os
import json
import requests
import feedparser
import whisper
from datetime import datetime

# 环境变量
WECHAT_APPID = os.environ['WECHAT_APPID']
WECHAT_APPSECRET = os.environ['WECHAT_APPSECRET']
WECHAT_OPENID = os.environ['WECHAT_OPENID']
DASHSCOPE_API_KEY = os.environ.get('DASHSCOPE_API_KEY', '')
FEISHU_APP_ID = os.environ.get('FEISHU_APP_ID', '')
FEISHU_APP_SECRET = os.environ.get('FEISHU_APP_SECRET', '')
FEISHU_ADMIN_PHONE = os.environ.get('FEISHU_ADMIN_PHONE', '')  # 你的手机号
SUBSCRIPTIONS_FILE = 'subscriptions.json'
PROCESSED_FILE = 'processed.json'

# ================= 微信 =================
def get_wechat_token():
    url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={WECHAT_APPID}&secret={WECHAT_APPSECRET}"
    return requests.get(url).json().get("access_token")

def send_wechat_text(text):
    token = get_wechat_token()
    url = f"https://api.weixin.qq.com/cgi-bin/message/custom/send?access_token={token}"
    data = {"touser": WECHAT_OPENID, "msgtype": "text", "text": {"content": text}}
    resp = requests.post(url, json=data, headers={"Content-Type": "application/json"}).json()
    print("微信通知:", resp)
    return resp.get("errcode") == 0

# ================= 飞书 =================
def get_feishu_token():
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    payload = {"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET}
    resp = requests.post(url, json=payload).json()
    return resp.get("tenant_access_token")

def get_open_id_by_phone(phone, token):
    """通过手机号获取用户 Open ID"""
    url = f"https://open.feishu.cn/open-apis/contact/v3/users/batch_get_id?user_id_type=open_id"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"mobiles": [phone]}
    resp = requests.post(url, headers=headers, json=payload).json()
    print("获取 Open ID 响应:", resp)
    if resp.get("code") == 0 and resp["data"].get("user_list"):
        return resp["data"]["user_list"][0]["user_id"]
    return None

def add_doc_manager(doc_id, phone, token):
    """将手机号用户添加为文档管理员"""
    open_id = get_open_id_by_phone(phone, token)
    if not open_id:
        print(f"未找到手机号 {phone} 对应的用户，无法添加权限。")
        return False

    url = f"https://open.feishu.cn/open-apis/drive/v1/permissions/{doc_id}/members?type=docx"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "member_type": "openid",
        "member_id": open_id,
        "perm": "full_access"  # 可管理
    }
    resp = requests.post(url, headers=headers, json=payload).json()
    print(f"给文档 {doc_id} 添加管理员响应:", resp)
    if resp.get("code") == 0:
        print(f"已成功为 {phone} 添加文档管理权限。")
        return True
    else:
        # 如果已经添加过，可能报错，忽略
        if resp.get("code") == 1411015:  # 权限已存在
            print("权限已存在，跳过。")
            return True
        print(f"添加权限失败: {resp}")
        return False

def ensure_all_docs_permission(subs, phone):
    """确保所有现有文档都已添加管理员权限"""
    if not phone or not subs:
        return
    token = get_feishu_token()
    if not token:
        return
    for sub in subs:
        doc_id = sub.get('feishu_doc_id')
        if doc_id:
            print(f"正在确保文档 {doc_id} 的权限...")
            add_doc_manager(doc_id, phone, token)

def create_feishu_doc(title):
    if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
        return None
    token = get_feishu_token()
    if not token:
        return None
    url = "https://open.feishu.cn/open-apis/docx/v1/documents"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"title": title}
    resp = requests.post(url, headers=headers, json=payload).json()
    print("创建文档:", resp)
    if resp.get("code") == 0:
        doc_id = resp["data"]["document"]["document_id"]
        # 创建后自动添加管理员权限
        if FEISHU_ADMIN_PHONE:
            add_doc_manager(doc_id, FEISHU_ADMIN_PHONE, token)
        return doc_id
    return None

def append_to_feishu_doc(doc_id, content):
    if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
        return False
    token = get_feishu_token()
    if not token:
        return False

    blocks = []
    for line in content.split('\n'):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith('## '):
            block_type = 4
            text_content = stripped[3:]
        elif stripped.startswith('▎'):
            block_type = 5
            text_content = stripped
        elif stripped == '---':
            blocks.append({
                "block_type": 2,
                "text": {"elements": [{"text_run": {"content": ""}}], "style": {}}
            })
            continue
        else:
            block_type = 2
            text_content = stripped

        blocks.append({
            "block_type": block_type,
            "text": {
                "elements": [{"text_run": {"content": text_content}}],
                "style": {}
            }
        })

    if not blocks:
        return False

    batch_size = 50
    success = True
    for i in range(0, len(blocks), batch_size):
        batch = blocks[i:i + batch_size]
        url = f"https://open.feishu.cn/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {"children": batch, "index": -1}
        try:
            resp = requests.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                result = resp.json()
                code = result.get("code")
                print(f"飞书写入第{i//batch_size + 1}批: code={code}")
                if code != 0:
                    print(f"失败详情: {result}")
                    success = False
            else:
                print(f"飞书HTTP错误: {resp.status_code}, {resp.text[:300]}")
                success = False
        except Exception as e:
            print(f"飞书异常: {e}")
            success = False
    return success

# ================= 订阅与去重管理 =================
def init_subscriptions():
    if not os.path.exists(SUBSCRIPTIONS_FILE):
        with open(SUBSCRIPTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump([], f)
    with open(SUBSCRIPTIONS_FILE, 'r', encoding='utf-8') as f:
        subs = json.load(f)

    updated = False
    for sub in subs:
        if not sub.get('feishu_doc_id'):
            doc_name = f"《{sub['name']}》· 摘要存档"
            doc_id = create_feishu_doc(doc_name)
            if doc_id:
                sub['feishu_doc_id'] = doc_id
                updated = True
                print(f"已为 {sub['name']} 创建文档: {doc_id}")

    if updated:
        with open(SUBSCRIPTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(subs, f, ensure_ascii=False, indent=2)
        git_commit(SUBSCRIPTIONS_FILE, "auto: update feishu doc ids")

    return subs

def load_processed():
    if not os.path.exists(PROCESSED_FILE):
        return {}
    with open(PROCESSED_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_processed(data):
    with open(PROCESSED_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    git_commit(PROCESSED_FILE, "auto: update processed guids")

def git_commit(file_path, message):
    if os.environ.get('GITHUB_ACTIONS'):
        os.system('git config user.name "github-actions"')
        os.system('git config user.email "actions@github.com"')
        os.system(f'git add {file_path}')
        os.system(f'git commit -m "{message}"')
        os.system('git push')

# ================= 播客处理 =================
def get_latest_episode(rss_url):
    headers = {'User-Agent': 'Mozilla/5.0'}
    resp = requests.get(rss_url, headers=headers, timeout=30)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    if not feed.entries:
        return None, None, None, None
    latest = feed.entries[0]
    audio_url = None
    for enc in latest.enclosures:
        if 'audio' in enc.type or enc.href.endswith(('.m4a','.mp3')):
            audio_url = enc.href
            break
    guid = latest.get('id') or latest.get('link') or latest.title
    return latest.title, audio_url, latest.link, guid

def download_audio(url, path):
    r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, stream=True)
    r.raise_for_status()
    with open(path, 'wb') as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)
    return path

def transcribe_audio(path):
    print("加载 Whisper medium 模型...")
    model = whisper.load_model("medium")
    print("开始转写...")
    result = model.transcribe(path, language="zh")
    return result["text"]

def summarize_detailed(raw_text, title):
    if not DASHSCOPE_API_KEY or len(DASHSCOPE_API_KEY) < 10:
        return raw_text
    max_chars = 8000
    chunks = [raw_text[i:i+max_chars] for i in range(0, len(raw_text), max_chars)]
    final_summary = []
    for idx, chunk in enumerate(chunks):
        print(f"总结第 {idx+1}/{len(chunks)} 段...")
        summary = _call_dashscope(chunk, title, idx+1, len(chunks))
        final_summary.append(summary)
    if len(final_summary) == 1:
        return final_summary[0]
    merged_prompt = f"""以下是一期播客各部分的分段总结，请整合为一篇连贯完整的详细论证复述稿，不遗漏逻辑步骤。

播客标题：{title}
{chr(10).join([f'第{i+1}部分：{s}' for i, s in enumerate(final_summary)])}

要求：按论证顺序，合并重复，保持详细度，直接输出最终总结。"""
    return _call_dashscope(merged_prompt, title, 0, 0)

def _call_dashscope(text, title, part_num, total_parts):
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
    system_prompt = """你是科技财经播客编辑。任务：
1. 完整复述论证过程，不遗漏核心观点和逻辑步骤。
2. 忽略闲聊、玩笑、重复强调的内容，只保留实质性讨论。
3. 多人协同论证则合并为流畅叙述；观点冲突或补充则区分不同说话者。
4. 用 "▎" 开头加小标题（8字内）划分板块，自然段落，正确标点。
5. 直接输出总结正文。"""
    user_prompt = f"""播客标题：{title}
{ '第' + str(part_num) + '部分/' + str(total_parts) + '部分：' if total_parts > 1 else '' }
{text}"""
    data = {
        "model": "qwen-plus",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": 3000,
        "temperature": 0.3
    }
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=120)
        result = resp.json()
        if "choices" in result:
            return result["choices"][0]["message"]["content"]
        else:
            print(f"AI 错误: {result}")
            return text
    except Exception as e:
        print(f"AI 异常: {e}")
        return text

def process_podcast(name, rss_url, doc_id, processed_db):
    print(f"\n=== 处理 {name} ===")
    title, audio_url, link, guid = get_latest_episode(rss_url)
    if not title:
        print(f"{name} RSS 无条目，跳过。")
        return False, processed_db

    last_guid = processed_db.get(name)
    if last_guid and last_guid == guid:
        print(f"{name} 已处理过 (guid: {guid})，跳过。")
        return False, processed_db

    print(f"标题: {title}")
    safe_name = name.replace(' ', '_')
    audio_path = f"{safe_name}_episode.m4a"
    download_audio(audio_url, audio_path)
    raw_text = transcribe_audio(audio_path)
    print(f"转写字数: {len(raw_text)}")
    structured = summarize_detailed(raw_text, title)
    if not structured or len(structured) < 10:
        structured = raw_text
    date_str = datetime.now().strftime('%Y年%m月%d日')
    full_text = f"## {date_str}：{title}\n\n{structured}\n\n---\n"

    if doc_id:
        success = append_to_feishu_doc(doc_id, full_text)
        if success:
            print(f"{name} 已写入飞书。")
            processed_db[name] = guid
            return True, processed_db
        else:
            print(f"{name} 飞书写入失败。")
            processed_db[name] = guid
            return False, processed_db
    else:
        print(f"{name} 无飞书文档 ID。")
        processed_db[name] = guid
        return False, processed_db

# ================= 主入口 =================
def main():
    subscriptions = init_subscriptions()

    # 确保所有现有文档都已添加你为管理员（每次运行都会检查，但权限存在时会跳过）
    if FEISHU_ADMIN_PHONE:
        ensure_all_docs_permission(subscriptions, FEISHU_ADMIN_PHONE)

    processed_db = load_processed()

    updated = []
    for sub in subscriptions:
        name = sub['name']
        success, processed_db = process_podcast(
            name, sub['rss'], sub.get('feishu_doc_id', ''), processed_db
        )
        if success:
            updated.append(name)

    save_processed(processed_db)

    if updated:
        msg = f"📻 今日有 {len(updated)} 档播客更新，摘要已存入飞书：\n" + '、'.join(updated)
    else:
        msg = "今日无播客更新。"
    send_wechat_text(msg)

if __name__ == '__main__':
    main()
