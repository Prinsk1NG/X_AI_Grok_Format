# -*- coding: utf-8 -*-
"""
grok_auto_task.py  v8.5 (硅谷100人：多号无限接力版 + 专家模式直驱 + xAI排版)
Architecture: Playwright(Grok Web Multi-Account) -> JSONL -> xAI SDK -> Feishu/WeChat
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

# -- 全局超时设置 ---------------------------------------------------
_START_TIME      = time.time()
PHASE1_DEADLINE  = 40 * 60   # 第一阶段最多 40 分钟
GLOBAL_DEADLINE  = 85 * 60   # 全局最多 85 分钟

# -- 100 硅谷 AI 核心账号 --------------------------------------------------------------
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

# ==============================================================================
# 🕸️ 网页版 Grok 自动化：多号接力与会话管理
# ==============================================================================
def get_available_cookies():
    """获取所有配置的 Grok Cookie 账号"""
    configs = []
    keys = ["SUPER_GROK_COOKIES"] + [f"SUPER_GROK_COOKIES_{i}" for i in range(2, 6)]
    for key in keys:
        val = os.getenv(key, "").strip()
        if val:
            configs.append({"env_key": key, "value": val})
    return configs

def create_browser_context(browser, cookie_config):
    """根据指定的 Cookie 创建独立的浏览器上下文"""
    ctx = browser.new_context(
        viewport={"width": 1280, "height": 800}, 
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36", 
        locale="zh-CN"
    )
    try:
        cookies = json.loads(cookie_config["value"])
        formatted = []
        for c in cookies:
            cookie = {"name": c.get("name", ""), "value": c.get("value", ""), "domain": c.get("domain", ".grok.com"), "path": c.get("path", "/")}
            if "httpOnly" in c: cookie["httpOnly"] = c["httpOnly"]
            if "secure" in c: cookie["secure"] = c["secure"]
            ss = c.get("sameSite", "")
            if ss in ("Strict", "Lax", "None"): cookie["sameSite"] = ss
            formatted.append(cookie)
        ctx.add_cookies(formatted)
        print(f"[Session] OK Loaded account via {cookie_config['env_key']}", flush=True)
    except Exception as e:
        print(f"[Session] ERROR Cookie injection failed for {cookie_config['env_key']}: {e}", flush=True)
    return ctx

def save_and_renew_session(context, env_key):
    """自动将刷新后的 Cookie 存回指定的 GitHub Secret"""
    if not PAT_FOR_SECRETS or not GITHUB_REPOSITORY:
        return
    try:
        from nacl import encoding, public as nacl_public
        
        # 直接从 Playwright 提取最新 Cookie 并序列化为 JSON
        cookies = context.cookies()
        state_str = json.dumps(cookies)

        repo_name = GITHUB_REPOSITORY.strip().strip("/")
        headers = {
            "Authorization": f"Bearer {PAT_FOR_SECRETS.strip()}", 
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        
        key_url = f"https://api.github.com/repos/{repo_name}/actions/secrets/public-key"
        key_resp = requests.get(key_url, headers=headers, timeout=30)
        
        if key_resp.status_code != 200:
            print(f"[Session] WARNING: 无法获取公钥，无法续期 {env_key}。请检查 PAT 是否有 'repo' 权限。", flush=True)
            return
            
        key_data = key_resp.json()
        pub_key = nacl_public.PublicKey(key_data["key"].encode(), encoding.Base64Encoder())
        sealed  = nacl_public.SealedBox(pub_key).encrypt(state_str.encode())
        enc_b64 = base64.b64encode(sealed).decode()

        put_url = f"https://api.github.com/repos/{repo_name}/actions/secrets/{env_key}"
        payload = {"encrypted_value": enc_b64, "key_id": key_data["key_id"]}
        
        put_resp = requests.put(put_url, headers=headers, json=payload, timeout=30)
        
        if put_resp.status_code in [201, 204]:
            print(f"[Session] OK GitHub Secret {env_key} auto-renewed", flush=True)
        else:
            print(f"[Session] ERROR: 更新 Secret 失败，状态码: {put_resp.status_code}", flush=True)
            
    except Exception as e:
        print(f"[Session] ERROR Secret renewal failed: {e}", flush=True)

def select_expert_mode(page):
    """智能寻找并开启专家模式"""
    print("\n[Model] Switching to Expert Mode (专家模式)...", flush=True)
    try:
        page.evaluate("""() => {
            const btns = Array.from(document.querySelectorAll('button'));
            const modelBtn = btns.find(b => b.innerText && (b.innerText.includes('自动模式') || b.innerText.includes('Auto') || b.innerText.includes('快速模式') || b.innerText.includes('Fast') || b.innerText.includes('专家模式') || b.innerText.includes('Expert')));
            if (modelBtn) modelBtn.click();
        }""")
        time.sleep(1)
        page.evaluate("""() => {
            const opts = Array.from(document.querySelectorAll('div, button, [role="menuitem"], [role="option"]'));
            const expertOpt = opts.find(o => o.innerText && (o.innerText.includes('专家模式') || o.innerText.includes('Expert') || o.innerText.includes('Thinks hard')));
            if (expertOpt) expertOpt.click();
        }""")
        time.sleep(0.5)
        page.keyboard.press("Escape")
        print("[Model] OK Expert Mode selected", flush=True)
    except Exception as e:
        print(f"[Model] Warning: Failed to select Expert mode: {e}", flush=True)

def _is_login_page(url: str) -> bool:
    lower = url.lower()
    return any(kw in lower for kw in ("sign", "login", "oauth", "x.com/i/flow"))

def open_grok_page(context, env_key):
    page = context.new_page()
    try:
        page.goto("https://grok.com", wait_until="domcontentloaded", timeout=60000)
        time.sleep(5) 
        
        Path("data").mkdir(exist_ok=True)
        page.screenshot(path=f"data/debug_01_homepage_{env_key}.png")
        
        if _is_login_page(page.url):
            print(f"ERROR: Account {env_key} is NOT logged in (Cookie expired).", flush=True)
            page.close()
            return None
            
        select_expert_mode(page)
        return page
    except Exception as e:
        try: page.close()
        except: pass
        return None

def send_prompt(page, prompt_text, label):
    """精准暴力输入，规避 React 拦截"""
    try:
        time.sleep(2) 
        page.screenshot(path=f"data/debug_{label}_before_input.png")
        
        injected = page.evaluate("""(text) => {
            const el = document.querySelector('.ProseMirror[contenteditable="true"]');
            if (el) {
                el.focus();
                document.execCommand('insertText', false, text);
                return true;
            }
            return false;
        }""", prompt_text)
        
        if not injected:
             print(f"[{label}] Warning: ProseMirror not found, trying blind clipboard paste...", flush=True)
             for _ in range(3):
                 page.keyboard.press("Tab")
                 time.sleep(0.1)
             page.evaluate("""(text) => {
                 const ta = document.createElement('textarea');
                 ta.id = 'hacker_clipboard'; ta.value = text;
                 ta.style.position = 'absolute'; ta.style.top = '-9999px';
                 document.body.appendChild(ta);
                 ta.select();
             }""", prompt_text)
             page.keyboard.press("Control+c")
             time.sleep(0.5)
             page.keyboard.press("Control+v")
             time.sleep(1)
             page.evaluate("() => { const ta = document.getElementById('hacker_clipboard'); if(ta) ta.remove(); }")

        page.keyboard.press("Enter")
        time.sleep(1)
        
        page.evaluate("""() => { 
            const btns = Array.from(document.querySelectorAll('button'));
            const sendBtn = btns.find(b => {
                const aria = b.getAttribute('aria-label');
                return aria && (aria.includes('Send') || aria.includes('Submit') || aria.includes('Grok'));
            });
            if (sendBtn && !sendBtn.disabled) sendBtn.click();
        }""")
             
        print(f"[{label}] OK Prompt Sent", flush=True)
    except Exception as e:
        print(f"[{label}] WARNING Prompt issue: {e}", flush=True)
    time.sleep(5)

def wait_and_extract(page, label, interval=3, stable_rounds=4, max_wait=120, extend_if_growing=False, min_len=80):
    last_len, stable, elapsed, last_text = -1, 0, 0, ""
    while elapsed < max_wait:
        time.sleep(interval)
        elapsed += interval
        try: 
            text = page.evaluate("""() => { 
                const msgs = Array.from(document.querySelectorAll('.prose, .markdown, [data-testid="assistant-message"]'));
                const ai_msgs = msgs.filter(m => !m.innerText.includes('You are an X/Twitter data collection tool'));
                if (ai_msgs.length === 0) return "";
                return ai_msgs[ai_msgs.length - 1].innerText; 
            }""")
        except: 
            return last_text.strip()
            
        last_text = text
        cur_len = len(text.strip())
        
        if cur_len == last_len and cur_len >= min_len and "{" in text and "}" in text:
            stable += 1
            if stable >= stable_rounds: return text.strip()
        else:
            stable = 0
            last_len = cur_len
            
    page.screenshot(path=f"data/debug_{label}_timeout.png")
    return last_text.strip()

def parse_jsonlines(text: str) -> list:
    results = []
    text = re.sub(r'^`{3}(?:jsonl|json)?\n', '', text, flags=re.MULTILINE)
    text = re.sub(r'^`{3}\n?', '', text, flags=re.MULTILINE)
    for line in text.splitlines():
        line = line.strip()
        if not line or not line.startswith('{') or not line.endswith('}'): continue
        try: results.append(json.loads(line))
        except: continue
    return results

# ==============================================================================
# 🤖 抓取策略 Prompts 
# ==============================================================================
def build_phase1_prompt(accounts: list) -> str:
    rounds = [accounts[i:i+3] for i in range(0, len(accounts), 3)]
    rounds_text = "\n".join(f"Round {i+1}: {' | '.join(r)}" for i, r in enumerate(rounds))
    return (
        "You are an X/Twitter data collection tool. Search the following accounts and output pure JSON Lines format.\n\n"
        "[Search Rules]\n"
        "1. Search each account individually: x_keyword_search query=from:AccountName, mode=Latest, limit=10\n"
        "2. Execute in parallel rounds (3 accounts per round)\n"
        "3. Output newest 3 posts + 1 metadata row per account\n\n"
        f"[Account List]\n{rounds_text}\n\n"
        "[Output Format (JSON Lines ONLY)]\n"
        '  Post: {"a":"AccountName","l":likes,"t":"MMDD","s":"English summary","tag":"raw"}\n'
        '  Meta: {"a":"AccountName","type":"meta","total":count,"max_l":max_likes,"latest":"MMDD"}\n'
    )

def build_phase2_s_prompt(accounts: list) -> str:
    rounds = [accounts[i:i+3] for i in range(0, len(accounts), 3)]
    rounds_text = "\n".join(f"Round {i+1}: {' | '.join(r)}" for i, r in enumerate(rounds))
    return (
        "You are an X/Twitter data collection tool. Deep-collect S-tier accounts, output pure JSON Lines.\n\n"
        "1. x_keyword_search query=from:AccountName, mode=Latest, limit=10\n"
        "2. Output all 10 posts\n"
        f"[S-tier Accounts]\n{rounds_text}\n\n"
        "[Output Format (JSON Lines ONLY)]\n"
        '  Normal: {"a":"Name","l":likes,"t":"MMDD","s":"English summary","tag":"raw"}\n'
        '  Quote:  {"a":"Name","l":likes,"t":"MMDD","s":"summary","qt":"@orig: summary","tag":"raw"}\n'
    )

def build_phase2_a_prompt(accounts: list) -> str:
    rounds = [accounts[i:i+3] for i in range(0, len(accounts), 3)]
    rounds_text = "\n".join(f"Round {i+1}: {' | '.join(r)}" for i, r in enumerate(rounds))
    return (
        "You are an X/Twitter data collection tool. Collect A-tier accounts, output pure JSON Lines.\n\n"
        "1. x_keyword_search query=from:AccountName, mode=Latest, limit=5\n"
        "2. Output up to 5 posts\n"
        f"[A-tier Accounts]\n{rounds_text}\n\n"
        "[Output Format (JSON Lines ONLY)]\n"
        '  Normal: {"a":"Name","l":likes,"t":"MMDD","s":"summary","tag":"raw"}\n'
        '  Quote:  {"a":"Name","l":likes,"t":"MMDD","s":"summary","qt":"@orig: summary","tag":"raw"}\n'
    )

def run_grok_batch_with_relay(browser, cookie_configs, accounts: list, prompt_builder, label: str):
    """🚨 核心接力引擎：如果当前账号被限流，自动切换下一个账号！"""
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
            print(f"[{label}] ❌ 账号 {env_key} 登录失效，切换下一个...", flush=True)
            context.close()
            _current_cookie_idx = (_current_cookie_idx + 1) % len(cookie_configs)
            attempts += 1
            continue
            
        try:
            prompt = prompt_builder(accounts)
            send_prompt(page, prompt, label)
            
            print(f"[{label}] 等待 60s 让 Grok 搜索...", flush=True)
            time.sleep(60)
            raw_text = wait_and_extract(page, label, interval=5, stable_rounds=5, max_wait=420, extend_if_growing=True, min_len=50)
            results = parse_jsonlines(raw_text)
            
            if len(results) > 0:
                print(f"[{label}] ✅ 成功抓取 {len(results)} 条数据！", flush=True)
                save_and_renew_session(context, env_key)
                page.close()
                context.close()
                return results
            else:
                print(f"[{label}] ⚠️ 账号 {env_key} 被限流或报错 (返回 0 条 JSON)。", flush=True)
                print(f"[{label}] 🤖 Grok 的遗言: {raw_text[:300]}...", flush=True)
                
                # 保存一下被限流的账号状态，然后关闭
                save_and_renew_session(context, env_key)
                page.close()
                context.close()
                
                # 切换下一个号
                _current_cookie_idx = (_current_cookie_idx + 1) % len(cookie_configs)
                attempts += 1
                print(f"[{label}] 🔄 正在无缝切换到备用账号...", flush=True)
                
        except Exception as e:
            print(f"[{label}] 💥 运行崩溃: {e}", flush=True)
            try: page.close(); context.close()
            except: pass
            _current_cookie_idx = (_current_cookie_idx + 1) % len(cookie_configs)
            attempts += 1

    print(f"[{label}] 💀 灾难：所有配置的 Grok 账号均已耗尽或被限流！", flush=True)
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
# 🚀 第二阶段：纯 XML 提示词与 xAI 提纯 
# ==============================================================================
def _build_xml_prompt(combined_jsonl: str, today_str: str) -> str:
    return f"""
你是一位顶级的 AI 行业一级市场投资分析师。
分析过去24小时内科技大佬的推文和全球热点，提炼出有投资和实操价值的洞察，用犀利、专业的中文进行总结。

【重要纪律】
1. 禁止输出任何 Markdown 排版符号（如 #, *, >, -）。
2. 只允许输出纯文本内容，并严格按照以下 XML 标签结构填入信息。不要缺漏闭合标签。
3. Title（头衔/身份）绝对不要翻译，保持纯英文。
4. 🚨【翻译铁律】所有的 <TWEET> 标签内容，【必须以中文为主体】！绝对禁止直接复制粘贴纯英文段落！为了保留内行风味，你可以不翻译特定的英文黑话、梗或专有名词（如 "poached", "R-rated" 等），但句子的骨架和整体含义必须翻译为流畅的中文！

【输出结构规范】
<REPORT>
  <COVER title="5-10字中文爆款标题" prompt="100字英文图生图提示词，赛博朋克风" insight="30字内核心洞察，中文"/>
  <PULSE>用一句话总结今日最核心的 1-2 个行业动态信号。</PULSE>
  
  <THEMES>
    <THEME type="shift" emoji="⚔️">
      <TITLE>主题标题：副标题 (请挖掘 3-5 个独立话题)</TITLE>
      <NARRATIVE>一句话核心判断（直接输出观点文本，不要带前缀）</NARRATIVE>
      <TWEET account="X账号名" role="英文身份标签">以中文为主翻译原文观点，可夹杂少量英文黑话</TWEET>
      <TWEET account="..." role="...">...</TWEET>
      <CONSENSUS>核心共识的纯文本描述（直接输出观点，不要带前缀）</CONSENSUS>
      <DIVERGENCE>最大分歧的纯文本描述（直接输出观点，不要带前缀）</DIVERGENCE>
    </THEME>

    <THEME type="new" emoji="🌱">
      <TITLE>主题标题：副标题 (请挖掘 3-5 个独立话题)</TITLE>
      <NARRATIVE>一句话新趋势定义（直接输出观点文本，不要带前缀）</NARRATIVE>
      <TWEET account="X账号名" role="英文身份标签">以中文为主翻译原文观点，可夹杂少量英文黑话</TWEET>
      <TWEET account="..." role="...">...</TWEET>
      <OUTLOOK>对该新叙事的深度解读与未来展望</OUTLOOK>
      <OPPORTUNITY>可能带来的机会</OPPORTUNITY>
      <RISK>警惕的陷阱或风险</RISK>
    </THEME>
  </THEMES>

  <INVESTMENT_RADAR>
    <ITEM category="投融资快讯">具体的融资额与领投机构等。</ITEM>
    <ITEM category="VC views">顶级机构投资风向警示等。</ITEM>
  </INVESTMENT_RADAR>

  <RISK_CHINA_VIEW>
    <ITEM category="中国 AI 评价">对中国大模型的技术评价等。</ITEM>
    <ITEM category="地缘与监管">出口、合规、版权风险等。</ITEM>
  </RISK_CHINA_VIEW>

  <TOP_PICKS>
    <TWEET account="..." role="...">【严禁纯英文】流畅中文精译，保留关键英文梗增强表现力</TWEET>
  </TOP_PICKS>
</REPORT>

# 原始数据输入 (JSONL):
{combined_jsonl}
# 日期: {today_str}
"""

def llm_call_xai(combined_jsonl: str, today_str: str) -> str:
    api_key = XAI_API_KEY.strip()
    if not api_key: 
        print("[LLM/xAI] Error: XAI_API_KEY is missing!")
        return ""
    
    max_data_chars = 100000 
    data = combined_jsonl[:max_data_chars] if len(combined_jsonl) > max_data_chars else combined_jsonl
    prompt = _build_xml_prompt(data, today_str)
    
    model_name = "grok-4.20-beta-latest-non-reasoning" 
    client = Client(api_key=api_key)
    print(f"\n[LLM/xAI] Requesting {model_name} via Official xai-sdk...", flush=True)
    
    for attempt in range(1, 4):
        try:
            chat = client.chat.create(model=model_name)
            chat.append(system("You are a professional analytical bot. You strictly output in XML format as instructed. Do not ignore the translation rules."))
            chat.append(user(prompt))
            result = chat.sample().content.strip()
            print(f"[LLM/xAI] OK Response received ({len(result)} chars)", flush=True)
            return result
        except Exception as e: 
            print(f"[LLM/xAI] attempt {attempt} failed: {e}")
            time.sleep(2 ** attempt)
    return ""

def parse_llm_xml(xml_text: str) -> dict:
    data = {"cover": {"title": "", "prompt": "", "insight": ""}, "pulse": "", "themes": [], "investment_radar": [], "risk_china_view": [], "top_picks": []}
    if not xml_text: return data

    cover_match = re.search(r'<COVER\s+title=[\'"“”](.*?)[\'"“”]\s+prompt=[\'"“”](.*?)[\'"“”]\s+insight=[\'"“”](.*?)[\'"“”]\s*/?>', xml_text, re.IGNORECASE | re.DOTALL)
    if not cover_match: cover_match = re.search(r'<COVER\s+title="(.*?)"\s+prompt="(.*?)"\s+insight="(.*?)"\s*/?>', xml_text, re.IGNORECASE | re.DOTALL)
    if cover_match: data["cover"] = {"title": cover_match.group(1).strip(), "prompt": cover_match.group(2).strip(), "insight": cover_match.group(3).strip()}
        
    pulse_match = re.search(r'<PULSE>(.*?)</PULSE>', xml_text, re.IGNORECASE | re.DOTALL)
    if pulse_match: data["pulse"] = pulse_match.group(1).strip()
        
    for theme_match in re.finditer(r'<THEME([^>]*)>(.*?)</THEME>', xml_text, re.IGNORECASE | re.DOTALL):
        attrs = theme_match.group(1)
        theme_body = theme_match.group(2)
        type_m = re.search(r'type\s*=\s*[\'"“”](.*?)[\'"“”]', attrs, re.IGNORECASE)
        emoji_m = re.search(r'emoji\s*=\s*[\'"“”](.*?)[\'"“”]', attrs, re.IGNORECASE)
        theme_type = type_m.group(1).strip().lower() if type_m else "shift"
        emoji = emoji_m.group(1).strip() if emoji_m else "🔥"
        
        t_tag = re.search(r'<TITLE>(.*?)</TITLE>', theme_body, re.IGNORECASE | re.DOTALL)
        theme_title = t_tag.group(1).strip() if t_tag else "未命名主题"
        
        narrative_match = re.search(r'<NARRATIVE>(.*?)</NARRATIVE>', theme_body, re.IGNORECASE | re.DOTALL)
        narrative = narrative_match.group(1).strip() if narrative_match else ""
        
        tweets = []
        for t_match in re.finditer(r'<TWEET\s+account=[\'"“”](.*?)[\'"“”]\s+role=[\'"“”](.*?)[\'"“”]>(.*?)</TWEET>', theme_body, re.IGNORECASE | re.DOTALL):
            tweets.append({"account": t_match.group(1).strip(), "role": t_match.group(2).strip(), "content": t_match.group(3).strip()})
        if not tweets:
            for t_match in re.finditer(r'<TWEET\s+account="(.*?)"\s+role="(.*?)">(.*?)</TWEET>', theme_body, re.IGNORECASE | re.DOTALL):
                tweets.append({"account": t_match.group(1).strip(), "role": t_match.group(2).strip(), "content": t_match.group(3).strip()})
        
        con_match = re.search(r'<CONSENSUS>(.*?)</CONSENSUS>', theme_body, re.IGNORECASE | re.DOTALL)
        consensus = con_match.group(1).strip() if con_match else ""
        div_match = re.search(r'<DIVERGENCE>(.*?)</DIVERGENCE>', theme_body, re.IGNORECASE | re.DOTALL)
        divergence = div_match.group(1).strip() if div_match else ""
        
        out_match = re.search(r'<OUTLOOK>(.*?)</OUTLOOK>', theme_body, re.IGNORECASE | re.DOTALL)
        outlook = out_match.group(1).strip() if out_match else ""
        opp_match = re.search(r'<OPPORTUNITY>(.*?)</OPPORTUNITY>', theme_body, re.IGNORECASE | re.DOTALL)
        opportunity = opp_match.group(1).strip() if opp_match else ""
        risk_match = re.search(r'<RISK>(.*?)</RISK>', theme_body, re.IGNORECASE | re.DOTALL)
        risk = risk_match.group(1).strip() if risk_match else ""
        
        data["themes"].append({
            "type": theme_type, "emoji": emoji, "title": theme_title, "narrative": narrative, "tweets": tweets,
            "consensus": consensus, "divergence": divergence, "outlook": outlook, "opportunity": opportunity, "risk": risk
        })
        
    def extract_items(tag_name, target_list):
        block_match = re.search(rf'<{tag_name}>(.*?)</{tag_name}>', xml_text, re.IGNORECASE | re.DOTALL)
        if block_match:
            for item in re.finditer(r'<ITEM\s+category=[\'"“”](.*?)[\'"“”]>(.*?)</ITEM>', block_match.group(1), re.IGNORECASE | re.DOTALL):
                target_list.append({"category": item.group(1).strip(), "content": item.group(2).strip()})

    extract_items("INVESTMENT_RADAR", data["investment_radar"])
    extract_items("RISK_CHINA_VIEW", data["risk_china_view"])

    picks_match = re.search(r'<TOP_PICKS>(.*?)</TOP_PICKS>', xml_text, re.IGNORECASE | re.DOTALL)
    if picks_match:
        for t_match in re.finditer(r'<TWEET\s+account=[\'"“”](.*?)[\'"“”]\s+role=[\'"“”](.*?)[\'"“”]>(.*?)</TWEET>', picks_match.group(1), re.IGNORECASE | re.DOTALL):
            data["top_picks"].append({"account": t_match.group(1).strip(), "role": t_match.group(2).strip(), "content": t_match.group(3).strip()})
            
    return data

# ==============================================================================
# 🚀 第三阶段：结构化渲染引擎 (双模态自适应)
# ==============================================================================
def render_feishu_card(parsed_data: dict, today_str: str):
    webhooks = get_feishu_webhooks()
    if not webhooks or not parsed_data.get("pulse"): return

    elements = []
    elements.append({"tag": "markdown", "content": f"**▌ ⚡️ 今日看板 (The Pulse)**\n<font color='grey'>{parsed_data['pulse']}</font>"})
    elements.append({"tag": "hr"})

    if parsed_data["themes"]:
        elements.append({"tag": "markdown", "content": "**▌ 🧠 深度叙事追踪**"})
        for idx, theme in enumerate(parsed_data["themes"]):
            theme_md = f"**{theme['emoji']} {theme['title']}**\n"
            prefix = "🔭 新叙事观察" if theme.get("type") == "new" else "💡 叙事转向"
            theme_md += f"<font color='grey'>{prefix}：{theme['narrative']}</font>\n"
            
            for t in theme["tweets"]:
                theme_md += f"🗣️ **@{t['account']} | {t['role']}**\n<font color='grey'>“{t['content']}”</font>\n"
            
            if theme.get("type") == "new":
                if theme.get("outlook"): theme_md += f"<font color='blue'>**🔮 解读与展望：**</font> {theme['outlook']}\n"
                if theme.get("opportunity"): theme_md += f"<font color='green'>**🎯 潜在机会：**</font> {theme['opportunity']}\n"
                if theme.get("risk"): theme_md += f"<font color='red'>**⚠️ 潜在风险：**</font> {theme['risk']}\n"
            else:
                if theme.get("consensus"): theme_md += f"<font color='red'>**🔥 核心共识：**</font> {theme['consensus']}\n"
                if theme.get("divergence"): theme_md += f"<font color='red'>**⚔️ 最大分歧：**</font> {theme['divergence']}\n"
            
            elements.append({"tag": "markdown", "content": theme_md.strip()})
            if idx < len(parsed_data["themes"]) - 1: elements.append({"tag": "hr"})
        elements.append({"tag": "hr"})

    def add_list_section(title, icon, items):
        if not items: return
        content = f"**▌ {icon} {title}**\n\n"
        for item in items: content += f"👉 **{item['category']}**：<font color='grey'>{item['content']}</font>\n"
        elements.append({"tag": "markdown", "content": content.strip()})
        elements.append({"tag": "hr"})

    add_list_section("资本与估值雷达 (Investment Radar)", "💰", parsed_data["investment_radar"])
    add_list_section("风险与中国视角 (Risk & China View)", "📊", parsed_data["risk_china_view"])

    if parsed_data["top_picks"]:
        picks_md = "**▌ 📣 今日精选推文 (Top 5 Picks)**\n"
        for t in parsed_data["top_picks"]:
            picks_md += f"\n🗣️ **@{t['account']} | {t['role']}**\n<font color='grey'>\"{t['content']}\"</font>\n"
        elements.append({"tag": "markdown", "content": picks_md.strip()})

    card_payload = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True, "enable_forward": True},
            "header": {"title": {"content": f"昨晚硅谷在聊啥 | {today_str}", "tag": "plain_text"}, "template": "blue"},
            "elements": elements + [{"tag": "note", "elements": [{"tag": "plain_text", "content": "Powered by Grok Web Scraper + xAI SDK"}]}]
        }
    }

    for url in webhooks:
        try: requests.post(url, json=card_payload, timeout=20)
        except: pass

def render_wechat_html(parsed_data: dict, cover_url: str = "") -> str:
    html_lines = []
    if cover_url: html_lines.append(f'<p style="text-align:center;margin:0 0 16px 0;"><img src="{cover_url}" style="max-width:100%;border-radius:8px;" /></p>')
    if parsed_data["cover"].get("insight"):
        html_lines.append(f'<div style="border-radius:8px;background:#FFF7E6;padding:12px 14px;margin:0 0 20px 0;color:#d97706;"><div style="font-weight:bold;margin-bottom:6px;">💡 Insight | 昨晚硅谷在聊啥？</div><div>{parsed_data["cover"]["insight"]}</div></div>')

    def make_h3(title): return f'<h3 style="margin:24px 0 12px 0;font-size:18px;border-left:4px solid #4A90E2;padding-left:10px;color:#2c3e50;font-weight:bold;">{title}</h3>'
    def make_quote(content): return f'<div style="background:#f8f9fa;border-left:4px solid #8c98a4;padding:10px 14px;color:#555;font-size:15px;border-radius:0 4px 4px 0;margin:6px 0 10px 0;line-height:1.6;">{content}</div>'

    html_lines.append(make_h3("⚡️ 今日看板 (The Pulse)"))
    html_lines.append(make_quote(parsed_data.get('pulse', '')))

    if parsed_data["themes"]:
        html_lines.append(make_h3("🧠 深度叙事追踪"))
        for idx, theme in enumerate(parsed_data["themes"]):
            html_lines.append(f'<p style="font-weight:bold;font-size:16px;color:#1e293b;margin:16px 0 8px 0;">{theme["emoji"]} {theme["title"]}</p>')
            
            if theme.get("type") == "new":
                html_lines.append(f'<div style="background:#f4f8fb; padding:10px 12px; border-radius:6px; margin:0 0 8px 0; font-size:14px; color:#2c3e50;"><strong>🔭 新叙事观察：</strong>{theme["narrative"]}</div>')
            else:
                html_lines.append(f'<div style="background:#f4f8fb; padding:10px 12px; border-radius:6px; margin:0 0 8px 0; font-size:14px; color:#2c3e50;"><strong>💡 叙事转向：</strong>{theme["narrative"]}</div>')
                
            for t in theme["tweets"]:
                html_lines.append(f'<p style="margin:8px 0 2px 0;font-size:14px;font-weight:bold;color:#2c3e50;">🗣️ @{t["account"]} <span style="color:#94a3b8;font-weight:normal;">| {t["role"]}</span></p>')
                html_lines.append(make_quote(f'"{t["content"]}"'))
            
            if theme.get("type") == "new":
                if theme.get("outlook"): html_lines.append(f'<p style="margin:6px 0; font-size:15px; line-height:1.6; background:#eef2ff; padding: 8px 12px; border-radius: 4px;"><strong style="color:#4f46e5;">🔮 解读与展望：</strong>{theme["outlook"]}</p>')
                if theme.get("opportunity"): html_lines.append(f'<p style="margin:6px 0; font-size:15px; line-height:1.6; background:#f0fdf4; padding: 8px 12px; border-radius: 4px;"><strong style="color:#16a34a;">🎯 潜在机会：</strong>{theme["opportunity"]}</p>')
                if theme.get("risk"): html_lines.append(f'<p style="margin:6px 0; font-size:15px; line-height:1.6; background:#fef2f2; padding: 8px 12px; border-radius: 4px;"><strong style="color:#dc2626;">⚠️ 潜在风险：</strong>{theme["risk"]}</p>')
            else:
                if theme.get("consensus"): html_lines.append(f'<p style="margin:6px 0; font-size:15px; line-height:1.6; background:#fff5f5; padding: 8px 12px; border-radius: 4px;"><strong style="color:#d35400;">🔥 核心共识：</strong>{theme["consensus"]}</p>')
                if theme.get("divergence"): html_lines.append(f'<p style="margin:6px 0; font-size:15px; line-height:1.6; background:#fff5f5; padding: 8px 12px; border-radius: 4px;"><strong style="color:#d35400;">⚔️ 最大分歧：</strong>{theme["divergence"]}</p>')
            
            if idx < len(parsed_data["themes"]) - 1: html_lines.append('<hr style="border:none;border-top:1px dashed #cbd5e1;margin:24px 0;"/>')

    def make_list_section(title, items):
        if not items: return
        html_lines.append(make_h3(title))
        for item in items: html_lines.append(f'<p style="margin:10px 0;font-size:15px;line-height:1.6;">👉 <strong style="color:#2c3e50;">{item["category"]}：</strong><span style="color:#333;">{item["content"]}</span></p>')

    make_list_section("💰 资本与估值雷达 (Investment Radar)", parsed_data["investment_radar"])
    make_list_section("📊 风险与中国视角 (Risk & China View)", parsed_data["risk_china_view"])

    if parsed_data["top_picks"]:
        html_lines.append(make_h3("📣 今日精选推文 (Top 5 Picks)"))
        for t in parsed_data["top_picks"]:
             html_lines.append(f'<p style="margin:12px 0 4px 0;font-size:14px;font-weight:bold;color:#2c3e50;">🗣️ @{t["account"]} <span style="color:#94a3b8;font-weight:normal;">| {t["role"]}</span></p>')
             html_lines.append(make_quote(f'"{t["content"]}"'))

    return "<br/>".join(html_lines)

def generate_cover_image(prompt):
    if not SF_API_KEY or not prompt: return ""
    try:
        resp = requests.post(URL_SF_IMAGE, headers={"Authorization": f"Bearer {SF_API_KEY}", "Content-Type": "application/json"}, json={"model": "black-forest-labs/FLUX.1-schnell", "prompt": prompt, "n": 1, "image_size": "1024x576"}, timeout=60)
        if resp.status_code == 200: return resp.json().get("images", [{}])[0].get("url") or resp.json().get("data", [{}])[0].get("url")
    except: return ""

def upload_to_imgbb_via_url(sf_url):
    if not IMGBB_API_KEY or not sf_url: return sf_url 
    try:
        img_resp = requests.get(sf_url, timeout=30)
        img_b64 = base64.b64encode(img_resp.content).decode("utf-8")
        upload_resp = requests.post(URL_IMGBB, data={"key": IMGBB_API_KEY, "image": img_b64}, timeout=45)
        if upload_resp.status_code == 200: return upload_resp.json()["data"]["url"]
    except: return sf_url

def push_to_jijyun(html_content, title, cover_url=""):
    if not JIJYUN_WEBHOOK_URL: return
    try: requests.post(JIJYUN_WEBHOOK_URL, json={"title": title, "author": "Prinski", "html_content": html_content, "cover_jpg": cover_url}, timeout=30)
    except: pass

def save_daily_data(today_str: str, post_objects: list, report_text: str):
    data_dir = Path(f"data/{today_str}")
    data_dir.mkdir(parents=True, exist_ok=True)
    combined_txt = "\n".join(json.dumps(obj, ensure_ascii=False) for obj in post_objects)
    (data_dir / "combined.txt").write_text(combined_txt, encoding="utf-8")
    if report_text: (data_dir / "daily_report.txt").write_text(report_text, encoding="utf-8")


# 🚨 全局记录当前使用的 Cookie 序号
_current_cookie_idx = 0

# ==============================================================================
# 🚀 主程序入口
# ==============================================================================
def main():
    global _current_cookie_idx
    print("=" * 60, flush=True)
    mode_str = "测试模式(1个Batch-6人)" if TEST_MODE else "全量模式"
    print(f"昨晚硅谷在聊啥 v8.5 (无限接力版 + 专家模式直驱 + xAI提纯 - {mode_str})", flush=True)
    print("=" * 60, flush=True)

    today_str, _ = get_dates()
    Path("data").mkdir(exist_ok=True)
    check_cookie_expiry()
    
    # 🚨 1. 装载所有的 Cookie 配置 (支持 SUPER_GROK_COOKIES 到 SUPER_GROK_COOKIES_5)
    cookie_configs = get_available_cookies()
    if not cookie_configs:
        print("💥 致命错误：未找到任何 SUPER_GROK_COOKIES 环境变量！", flush=True)
        return
    print(f"🔑 成功装载 {len(cookie_configs)} 个 Grok 账号，准备开启无限接力抓取！", flush=True)

    selected_accounts = ALL_ACCOUNTS[:6] if TEST_MODE else ALL_ACCOUNTS
    meta_results, phase1_posts, phase2_posts = {}, {}, {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--disable-blink-features=AutomationControlled", "--window-size=1280,800"]
        )

        # --- Phase 1: 扫描 ---
        BATCH_SIZE = 20
        for batch_num, batch_start in enumerate(range(0, len(selected_accounts), BATCH_SIZE), start=1):
            if TEST_MODE and batch_num > 1: break
            if time.time() - _START_TIME > PHASE1_DEADLINE: break
            
            batch = selected_accounts[batch_start:batch_start + BATCH_SIZE]
            label = f"Phase1-Batch{batch_num}"
            
            # 🚨 核心逻辑：利用多个账号轮流尝试，直到成功或全部耗尽
            results = run_grok_batch_with_relay(browser, cookie_configs, batch, build_phase1_prompt, label)
            
            for obj in results:
                account = obj.get("a", "").lstrip("@")
                if not account: continue
                if obj.get("type") == "meta": meta_results[account] = obj
                else: phase1_posts.setdefault(account, []).append(obj)

        classification = classify_accounts(meta_results)
        s_accounts = [a for a, t in classification.items() if t == "S"]
        a_accounts = [a for a, t in classification.items() if t == "A"]
        
        # --- Phase 2: S 级深挖 ---
        if s_accounts and time.time() - _START_TIME < GLOBAL_DEADLINE:
            s_results = run_grok_batch_with_relay(browser, cookie_configs, s_accounts, build_phase2_s_prompt, "Phase2-S")
            for obj in s_results:
                if obj.get("type") != "meta": phase2_posts.setdefault(obj.get("a", "").lstrip("@"), []).append(obj)

        # --- Phase 2: A 级深挖 ---
        if a_accounts and time.time() - _START_TIME < GLOBAL_DEADLINE:
            a_results = run_grok_batch_with_relay(browser, cookie_configs, a_accounts, build_phase2_a_prompt, "Phase2-A")
            for obj in a_results:
                if obj.get("type") != "meta": phase2_posts.setdefault(obj.get("a", "").lstrip("@"), []).append(obj)

        browser.close()

    # 组装 JSONL 喂给 xAI SDK
    all_posts_flat = []
    for acc in s_accounts + a_accounts:
        all_posts_flat.extend(phase2_posts.get(acc) or phase1_posts.get(acc) or [])
    for acc in [a for a, t in classification.items() if t == "B"]:
        all_posts_flat.extend(phase1_posts.get(acc) or [])

    combined_jsonl = "\n".join(json.dumps(obj, ensure_ascii=False) for obj in all_posts_flat if obj.get("type") != "meta")
    print(f"\n[Data] Ready for xAI SDK: {len(all_posts_flat)} posts.")

    if combined_jsonl.strip():
        xml_result = llm_call_xai(combined_jsonl, today_str)
        if xml_result:
            print("\n[Parser] Parsing XML to structured data...", flush=True)
            parsed_data = parse_llm_xml(xml_result)
            
            cover_url = ""
            if parsed_data["cover"]["prompt"]:
                sf_url = generate_cover_image(parsed_data["cover"]["prompt"])
                cover_url = upload_to_imgbb_via_url(sf_url) if sf_url else ""
            
            render_feishu_card(parsed_data, today_str)
            
            if JIJYUN_WEBHOOK_URL:
                html_content = render_wechat_html(parsed_data, cover_url)
                wechat_title = parsed_data["cover"]["title"] or f"昨晚硅谷在聊啥 | {today_str}"
                push_to_jijyun(html_content, title=wechat_title, cover_url=cover_url)
                
            save_daily_data(today_str, all_posts_flat, xml_result)
            
            print("\n🎉 V8.5 运行完毕！", flush=True)
        else:
            print("❌ LLM 处理失败，任务终止。")

if __name__ == "__main__":
    main()
