# -*- coding: utf-8 -*-
"""
grok_auto_task.py  v8.8 (终极防封：无限接力 + 专家模式 + 彻底的自然语言伪装)
"""

import os
import re
import json
import time
import base64
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from requests.exceptions import ConnectionError, Timeout
from playwright.sync_api import sync_playwright

# 🚨 引入官方 xAI SDK
from xai_sdk import Client
from xai_sdk.chat import user, system

# -- 环境变量 -----------------------------------------------------
JIJYUN_WEBHOOK_URL  = os.getenv("JIJYUN_WEBHOOK_URL", "")
SF_API_KEY          = os.getenv("SF_API_KEY", "")
XAI_API_KEY         = os.getenv("XAI_API_KEY", "")    
IMGBB_API_KEY       = os.getenv("IMGBB_API_KEY", "") 

PAT_FOR_SECRETS     = os.getenv("PAT_FOR_SECRETS", "")
GITHUB_REPOSITORY   = os.getenv("GITHUB_REPOSITORY", "")

TEST_MODE = os.getenv("TEST_MODE_ENV", "false").lower() == "true"

_START_TIME      = time.time()
PHASE1_DEADLINE  = 40 * 60   
GLOBAL_DEADLINE  = 85 * 60   

ALL_ACCOUNTS = [
    "elonmusk", "sama", "karpathy", "demishassabis", "darioamodei",
    "OpenAI", "AnthropicAI", "GoogleDeepMind", "xAI", "AIatMeta",
    "GoogleAI", "MSFTResearch", "IlyaSutskever", "gregbrockman",
    "GaryMarcus", "rowancheung", "clmcleod", "bindureddy",
    "dotey", "oran_ge", "vista8", "imxiaohu", "Sxsyer",
    "K_O_D_A_D_A", "tualatrix", "linyunqiu", "garywong", "web3buidl",
    "AI_Era", "AIGC_News", "jiangjiang", "hw_star", "mranti", "nishuang",
    "a16z", "ycombinator", "lightspeedvp", "sequoia", "foundersfund",
    "eladgil", "pmarca", "bchesky", "chamath", "paulg",
    "TheInformation", "TechCrunch", "verge", "WIRED", "Scobleizer", "bentossell",
    "HuggingFace", "MistralAI", "Perplexity_AI", "GroqInc", "Cohere",
    "TogetherCompute", "runwayml", "Midjourney", "StabilityAI", "Scale_AI",
    "CerebrasSystems", "tenstorrent", "weights_biases", "langchainai", "llama_index",
    "supabase", "vllm_project", "huggingface_hub",
    "nvidia", "AMD", "Intel", "SKhynix", "tsmc",
    "magicleap", "NathieVR", "PalmerLuckey", "ID_AA_Carmack", "boz",
    "rabovitz", "htcvive", "XREAL_Global", "RayBan", "MetaQuestVR", "PatrickMoorhead",
    "jeffdean", "chrmanning", "hardmaru", "goodfellow_ian", "feifeili",
    "_akhaliq", "promptengineer", "AI_News_Tech", "siliconvalley", "aithread",
    "aibreakdown", "aiexplained", "aipubcast", "lexfridman", "hubermanlab", "swyx",
]

def get_feishu_webhooks() -> list:
    urls = []
    for suffix in ["", "_1", "_2", "_3"]:
        url = os.getenv(f"FEISHU_WEBHOOK_URL{suffix}", "")
        if url: urls.append(url)
    return urls

def get_dates() -> tuple:
    tz = timezone(timedelta(hours=8))
    today = datetime.now(tz)
    yesterday = today - timedelta(days=1)
    return today.strftime("%Y-%m-%d"), yesterday.strftime("%Y-%m-%d")

def get_available_cookies():
    configs = []
    keys = ["SUPER_GROK_COOKIES"] + [f"SUPER_GROK_COOKIES_{i}" for i in range(2, 6)]
    for key in keys:
        val = os.getenv(key, "").strip()
        if val: configs.append({"env_key": key, "value": val})
    return configs

def check_cookie_expiry(cookie_configs):
    for cfg in cookie_configs:
        try:
            data = json.loads(cfg["value"])
            if not isinstance(data, list): continue
            watched_names = {"sso", "auth_token", "ct0"}
            for c in data:
                cname = c.get("name", "")
                if cname in watched_names and c.get("expirationDate"):
                    exp = datetime.fromtimestamp(c["expirationDate"], tz=timezone.utc)
                    days_left = (exp - datetime.now(timezone.utc)).days
                    if days_left <= 5:
                        print(f"[Cookie] Warning: 账号 {cfg['env_key']} 中的核心 Cookie 将在 {days_left} 天后过期！", flush=True)
        except: pass

def create_browser_context(browser, cookie_config):
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36", locale="zh-CN")
    try:
        cookies = json.loads(cookie_config["value"])
        formatted = [{"name": c.get("name", ""), "value": c.get("value", ""), "domain": c.get("domain", ".grok.com"), "path": c.get("path", "/")} for c in cookies]
        ctx.add_cookies(formatted)
        print(f"[Session] OK Loaded {cookie_config['env_key']}", flush=True)
    except: pass
    return ctx

def save_and_renew_session(context, env_key):
    if not PAT_FOR_SECRETS or not GITHUB_REPOSITORY: return
    try:
        from nacl import encoding, public as nacl_public
        cookies = context.cookies()
        state_str = json.dumps(cookies)
        repo_name = GITHUB_REPOSITORY.strip().strip("/")
        headers = {"Authorization": f"Bearer {PAT_FOR_SECRETS.strip()}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        key_url = f"https://api.github.com/repos/{repo_name}/actions/secrets/public-key"
        key_resp = requests.get(key_url, headers=headers, timeout=30)
        if key_resp.status_code != 200: return
        key_data = key_resp.json()
        pub_key = nacl_public.PublicKey(key_data["key"].encode(), encoding.Base64Encoder())
        sealed  = nacl_public.SealedBox(pub_key).encrypt(state_str.encode())
        enc_b64 = base64.b64encode(sealed).decode()
        put_url = f"https://api.github.com/repos/{repo_name}/actions/secrets/{env_key}"
        requests.put(put_url, headers=headers, json={"encrypted_value": enc_b64, "key_id": key_data["key_id"]}, timeout=30)
    except: pass

def select_expert_mode(page):
    print("\n[Model] Switching to Expert Mode...", flush=True)
    try:
        page.evaluate("() => { const btns = Array.from(document.querySelectorAll('button')); const modelBtn = btns.find(b => b.innerText && (b.innerText.includes('Auto') || b.innerText.includes('Fast') || b.innerText.includes('Expert') || b.innerText.includes('模式'))); if (modelBtn) modelBtn.click(); }")
        time.sleep(1)
        page.evaluate("() => { const opts = Array.from(document.querySelectorAll('div, button, [role=\"menuitem\"]')); const expertOpt = opts.find(o => o.innerText && (o.innerText.includes('Expert') || o.innerText.includes('专家') || o.innerText.includes('Thinks hard'))); if (expertOpt) expertOpt.click(); }")
        time.sleep(0.5)
        page.keyboard.press("Escape")
    except: pass

def _is_login_page(url: str) -> bool:
    return any(kw in url.lower() for kw in ("sign", "login", "oauth", "x.com/i/flow"))

def open_grok_page(context, env_key):
    page = context.new_page()
    try:
        page.goto("https://grok.com", wait_until="domcontentloaded", timeout=60000)
        time.sleep(5) 
        if _is_login_page(page.url): return None
        select_expert_mode(page)
        return page
    except: return None

def send_prompt(page, prompt_text, label):
    """底层注入，防拦截"""
    try:
        time.sleep(2) 
        page.evaluate("""(text) => {
            const ta = document.createElement('textarea');
            ta.id = 'hacker_clipboard'; ta.value = text;
            ta.style.position = 'absolute'; ta.style.top = '-9999px';
            document.body.appendChild(ta);
            ta.select();
        }""", prompt_text)
        page.keyboard.press("Control+c")
        time.sleep(0.5)
        
        page.evaluate("""() => {
            const el = document.querySelector('.ProseMirror') || document.querySelector("textarea") || document.querySelector("div[contenteditable='true']");
            if(el) el.focus();
        }""")
        
        page.keyboard.press("Control+v")
        time.sleep(1)
        page.evaluate("() => { const ta = document.getElementById('hacker_clipboard'); if(ta) ta.remove(); }")
        page.keyboard.press("Enter")
        time.sleep(1)
        page.evaluate("() => { const btns = Array.from(document.querySelectorAll('button')); const sendBtn = btns.find(b => b.getAttribute('aria-label') && b.getAttribute('aria-label').includes('Send')); if (sendBtn) sendBtn.click(); }")
        print(f"[{label}] OK Prompt Sent (Forced)", flush=True)
    except: pass

def wait_and_extract(page, label, interval=3, stable_rounds=4, max_wait=120, min_len=40):
    last_len, stable, elapsed, last_text = -1, 0, 0, ""
    while elapsed < max_wait:
        time.sleep(interval)
        elapsed += interval
        try: 
            text = page.evaluate("""() => { 
                const msgs = Array.from(document.querySelectorAll('.prose, .markdown, [data-testid="assistant-message"]'));
                const ai_msgs = msgs.filter(m => !m.innerText.includes('Please act as my research assistant'));
                if (ai_msgs.length === 0) return "";
                return ai_msgs[ai_msgs.length - 1].innerText; 
            }""")
        except: return last_text.strip()
        last_text = text
        cur_len = len(text.strip())
        
        if cur_len == last_len and cur_len >= min_len:
            stable += 1
            if stable >= stable_rounds: return text.strip()
        else:
            stable = 0
            last_len = cur_len
            
    page.screenshot(path=f"data/debug_{label}_timeout.png")
    return last_text.strip()

# ==============================================================================
# 🚨 V8.8 核心：伪装成人类助理的自然语言提示词（彻底放弃JSON防封号）
# ==============================================================================
def parse_nlp_to_jsonl(text: str) -> list:
    """把大模型生成的半结构化自然文本解析为标准数据"""
    results = []
    
    post_pattern = re.compile(r'@([a-zA-Z0-9_]+)\s*\|\|\s*(\d+)\s*\|\|\s*(\d{4})\s*\|\|\s*(.*?)(?=\n@|\nMETA|\n$)', re.IGNORECASE | re.DOTALL)
    for match in post_pattern.finditer(text):
        results.append({
            "a": match.group(1).strip(),
            "l": int(match.group(2).strip()),
            "t": match.group(3).strip(),
            "s": match.group(4).strip().replace('\n', ' '),
            "tag": "raw"
        })
        
    meta_pattern = re.compile(r'META:\s*@([a-zA-Z0-9_]+)\s*\|\|\s*(\d+)\s*\|\|\s*(\d+)\s*\|\|\s*([0-9NAa-zA-Z]+)', re.IGNORECASE)
    for match in meta_pattern.finditer(text):
        results.append({
            "a": match.group(1).strip(),
            "type": "meta",
            "total": int(match.group(2).strip()),
            "max_l": int(match.group(3).strip()),
            "latest": match.group(4).strip()
        })
        
    return results

def build_phase1_prompt(accounts: list) -> str:
    rounds = [accounts[i:i+3] for i in range(0, len(accounts), 3)]
    rounds_text = "\n".join(f"Round {i+1}: {' | '.join(r)}" for i, r in enumerate(rounds))
    return (
        "Please act as my research assistant. Search the following Twitter users one by one and format the output like a simple text list, NOT code, NOT json.\n\n"
        "Here is what you need to do:\n"
        "1. Find their latest tweets.\n"
        "2. For each user, give me their 3 newest tweets in this exact text format:\n"
        "@AccountName || LikesCount || MMDD || English summary of the tweet\n"
        "3. After their tweets, add ONE line about their activity level in this exact format:\n"
        "META: @AccountName || TotalPostsCount || MaxLikesCount || LatestPostMMDD\n\n"
        f"The users are:\n{rounds_text}\n\n"
        "Just output the formatted text lines. Do not wrap in markdown code blocks."
    )

def build_phase2_s_prompt(accounts: list) -> str:
    rounds_text = "\n".join(f"Round 1: {' | '.join(accounts)}")
    return (
        "Please act as my research assistant. Summarize recent high-quality tweets from these specific users. Format the output like a simple text list, NOT code, NOT json.\n\n"
        "Here is what you need to do:\n"
        "1. Search to find their latest tweets.\n"
        "2. For each user, give me up to 10 newest tweets in this exact text format:\n"
        "@AccountName || LikesCount || MMDD || English summary of the tweet\n\n"
        f"The users are:\n{rounds_text}\n\n"
        "Just output the formatted text lines. Do not wrap in markdown code blocks."
    )

def build_phase2_a_prompt(accounts: list) -> str:
    return build_phase2_s_prompt(accounts)

def run_grok_batch_with_relay(browser, cookie_configs, accounts: list, prompt_builder, label: str):
    if not accounts: return []
    global _current_cookie_idx
    attempts = 0
    max_attempts = len(cookie_configs)
    
    while attempts < max_attempts:
        cfg = cookie_configs[_current_cookie_idx]
        env_key = cfg["env_key"]
        
        print(f"\n[{label}] 🟢 启动抓取 (使用账号: {env_key})...", flush=True)
        context = create_browser_context(browser, cfg)
        page = open_grok_page(context, env_key)
        
        if not page:
            print(f"[{label}] ❌ 账号失效，切换下一个...", flush=True)
            context.close()
            _current_cookie_idx = (_current_cookie_idx + 1) % len(cookie_configs)
            attempts += 1
            continue
            
        try:
            prompt = prompt_builder(accounts)
            send_prompt(page, prompt, label)
            
            print(f"[{label}] 等待 Grok 处理...", flush=True)
            raw_text = wait_and_extract(page, label, interval=5, stable_rounds=4, max_wait=300, min_len=40)
            
            results = parse_nlp_to_jsonl(raw_text)
            
            if len(results) > 0:
                print(f"[{label}] ✅ 成功提取 {len(results)} 条记录！", flush=True)
                page.close(); context.close()
                return results
            else:
                print(f"[{label}] ⚠️ 提取到 0 条记录。可能遭遇风控或限流。", flush=True)
                page.close(); context.close()
                _current_cookie_idx = (_current_cookie_idx + 1) % len(cookie_configs)
                attempts += 1
                
        except Exception as e:
            print(f"[{label}] 💥 崩溃: {e}", flush=True)
            try: page.close(); context.close()
            except: pass
            _current_cookie_idx = (_current_cookie_idx + 1) % len(cookie_configs)
            attempts += 1

    print(f"[{label}] 💀 所有 Grok 账号均告失败！", flush=True)
    return []

def classify_accounts(meta_results: dict) -> dict:
    tz = timezone(timedelta(hours=8))
    today = datetime.now(tz)
    classification = {}
    for account, meta in meta_results.items():
        total, max_l, latest = meta.get("total", 0), meta.get("max_l", 0), meta.get("latest", "NA")
        if total == 0 or latest == "NA":
            classification[account] = "inactive"
            continue
        try:
            mm, dd = int(latest[:2]), int(latest[2:])
            latest_date = today.replace(month=mm, day=dd)
            if latest_date > today: latest_date = latest_date.replace(year=today.year - 1)
            days_since = (today - latest_date).days
        except: days_since = 999
        if days_since > 30: classification[account] = "inactive"
        elif max_l > 3000 and days_since <= 7: classification[account] = "S"
        elif max_l > 800 and days_since <= 14: classification[account] = "A"
        else: classification[account] = "B"
    return classification

# ==============================================================================
# 🚀 xAI 排版与渲染
# ==============================================================================
def _build_xml_prompt(combined_jsonl: str, today_str: str) -> str:
    return f"""
你是一位顶级的 AI 行业一级市场投资分析师。
分析过去24小时内科技大佬的推文和全球热点，提炼出有投资和实操价值的洞察，用犀利、专业的中文进行总结。

【重要纪律】
1. 只允许输出纯文本内容，并严格按照以下 XML 标签结构填入信息。不要缺漏闭合标签。
2. 🚨所有的 <TWEET> 标签内容，【必须以中文为主体】翻译！

【输出结构规范】
<REPORT>
  <COVER title="5-10字中文标题" prompt="100字英文图生图提示词" insight="30字内核心洞察，中文"/>
  <PULSE>一句话总结核心动态。</PULSE>
  <THEMES>
    <THEME type="shift" emoji="⚔️">
      <TITLE>主题标题：副标题</TITLE>
      <NARRATIVE>一句话核心判断</NARRATIVE>
      <TWEET account="X账号名" role="英文身份标签">中文翻译原文观点</TWEET>
      <CONSENSUS>核心共识</CONSENSUS>
      <DIVERGENCE>最大分歧</DIVERGENCE>
    </THEME>
  </THEMES>
  <INVESTMENT_RADAR>
    <ITEM category="类别">内容</ITEM>
  </INVESTMENT_RADAR>
</REPORT>

# 原始数据 (纯文本列表):
{combined_jsonl}
# 日期: {today_str}
"""

def llm_call_xai(combined_jsonl: str, today_str: str) -> str:
    api_key = XAI_API_KEY.strip()
    if not api_key: return ""
    data = combined_jsonl[:100000]
    prompt = _build_xml_prompt(data, today_str)
    client = Client(api_key=api_key)
    print(f"\n[LLM/xAI] Requesting via Official xai-sdk...", flush=True)
    for attempt in range(1, 4):
        try:
            chat = client.chat.create(model="grok-4.20-beta-latest-non-reasoning")
            chat.append(system("You are a professional analytical bot. You strictly output in XML."))
            chat.append(user(prompt))
            return chat.sample().content.strip()
        except: time.sleep(2 ** attempt)
    return ""

def parse_llm_xml(xml_text: str) -> dict:
    data = {"cover": {"title": "", "prompt": "", "insight": ""}, "pulse": "", "themes": [], "investment_radar": [], "risk_china_view": [], "top_picks": []}
    if not xml_text: return data
    cover_match = re.search(r'<COVER\s+title=[\'"“”](.*?)[\'"“”]\s+prompt=[\'"“”](.*?)[\'"“”]\s+insight=[\'"“”](.*?)[\'"“”]\s*/?>', xml_text, re.IGNORECASE | re.DOTALL)
    if cover_match: data["cover"] = {"title": cover_match.group(1).strip(), "prompt": cover_match.group(2).strip(), "insight": cover_match.group(3).strip()}
    pulse_match = re.search(r'<PULSE>(.*?)</PULSE>', xml_text, re.IGNORECASE | re.DOTALL)
    if pulse_match: data["pulse"] = pulse_match.group(1).strip()
    for theme_match in re.finditer(r'<THEME([^>]*)>(.*?)</THEME>', xml_text, re.IGNORECASE | re.DOTALL):
        attrs, theme_body = theme_match.group(1), theme_match.group(2)
        emoji_m = re.search(r'emoji\s*=\s*[\'"“”](.*?)[\'"“”]', attrs, re.IGNORECASE)
        t_tag = re.search(r'<TITLE>(.*?)</TITLE>', theme_body, re.IGNORECASE | re.DOTALL)
        narrative_match = re.search(r'<NARRATIVE>(.*?)</NARRATIVE>', theme_body, re.IGNORECASE | re.DOTALL)
        tweets = [{"account": t.group(1).strip(), "role": t.group(2).strip(), "content": t.group(3).strip()} for t in re.finditer(r'<TWEET\s+account=[\'"“”](.*?)[\'"“”]\s+role=[\'"“”](.*?)[\'"“”]>(.*?)</TWEET>', theme_body, re.IGNORECASE | re.DOTALL)]
        data["themes"].append({"emoji": emoji_m.group(1).strip() if emoji_m else "🔥", "title": t_tag.group(1).strip() if t_tag else "", "narrative": narrative_match.group(1).strip() if narrative_match else "", "tweets": tweets})
    return data

def render_feishu_card(parsed_data: dict, today_str: str):
    webhooks = get_feishu_webhooks()
    if not webhooks or not parsed_data.get("pulse"): return
    elements = [{"tag": "markdown", "content": f"**⚡️ {parsed_data['pulse']}**\n---\n"}]
    for theme in parsed_data["themes"]:
        md = f"**{theme['emoji']} {theme['title']}**\n<font color='grey'>{theme['narrative']}</font>\n"
        for t in theme["tweets"]: md += f"🗣️ **@{t['account']}**\n<font color='grey'>“{t['content']}”</font>\n"
        elements.append({"tag": "markdown", "content": md.strip()})
        elements.append({"tag": "hr"})
    card_payload = {"msg_type": "interactive", "card": {"config": {"wide_screen_mode": True}, "header": {"title": {"content": f"硅谷科技雷达 | {today_str}", "tag": "plain_text"}, "template": "blue"}, "elements": elements}}
    for url in webhooks:
        try: requests.post(url, json=card_payload, timeout=20)
        except: pass

def push_to_jijyun(html_content, title, cover_url=""):
    if not JIJYUN_WEBHOOK_URL: return
    try: requests.post(JIJYUN_WEBHOOK_URL, json={"title": title, "author": "Prinski", "html_content": html_content, "cover_jpg": cover_url}, timeout=30)
    except: pass

_current_cookie_idx = 0

def main():
    global _current_cookie_idx
    print("=" * 60, flush=True)
    mode_str = "测试模式(6人)" if TEST_MODE else "全量模式"
    print(f"硅谷百人雷达 v8.8 (自然语言防封版 - {mode_str})", flush=True)
    print("=" * 60, flush=True)

    today_str, _ = get_dates()
    Path("data").mkdir(exist_ok=True)
    
    cookie_configs = get_available_cookies()
    if not cookie_configs:
        print("💥 致命错误：未找到任何 Cookie！", flush=True)
        return
    
    selected_accounts = ALL_ACCOUNTS[:6] if TEST_MODE else ALL_ACCOUNTS
    meta_results, phase1_posts, phase2_posts = {}, {}, {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-blink-features=AutomationControlled"])
        
        BATCH_SIZE = 10
        for batch_num, batch_start in enumerate(range(0, len(selected_accounts), BATCH_SIZE), start=1):
            if TEST_MODE and batch_num > 1: break
            batch = selected_accounts[batch_start:batch_start + BATCH_SIZE]
            label = f"Phase1-Batch{batch_num}"
            results = run_grok_batch_with_relay(browser, cookie_configs, batch, build_phase1_prompt, label)
            for obj in results:
                acc = obj.get("a", "")
                if obj.get("type") == "meta": meta_results[acc] = obj
                else: phase1_posts.setdefault(acc, []).append(obj)

        classification = classify_accounts(meta_results)
        s_accounts = [a for a, t in classification.items() if t == "S"]
        
        if s_accounts:
            s_results = run_grok_batch_with_relay(browser, cookie_configs, s_accounts, build_phase2_s_prompt, "Phase2-S")
            for obj in s_results:
                if obj.get("type") != "meta": phase2_posts.setdefault(obj.get("a", ""), []).append(obj)

        browser.close()

    all_posts_flat = []
    for acc in list(phase1_posts.keys()) + list(phase2_posts.keys()):
        all_posts_flat.extend(phase2_posts.get(acc) or phase1_posts.get(acc) or [])

    combined_jsonl = "\n".join(json.dumps(obj, ensure_ascii=False) for obj in all_posts_flat)
    print(f"\n[Data] Ready for xAI: {len(all_posts_flat)} posts.")

    if combined_jsonl.strip():
        xml_result = llm_call_xai(combined_jsonl, today_str)
        if xml_result:
            parsed = parse_llm_xml(xml_result)
            render_feishu_card(parsed, today_str)
            print("\n🎉 V8.8 运行完毕！", flush=True)
        else:
            print("❌ LLM 处理失败。")

if __name__ == "__main__":
    main()
