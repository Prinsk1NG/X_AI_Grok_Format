# -*- coding: utf-8 -*-
"""
grok_auto_task.py  v8.1 (硅谷 100 人：Grok Web UI 抓取 + xAI SDK XML 深度提纯)
Architecture: Playwright(Grok Web) -> JSONL -> xAI SDK (XML Prompt) -> Feishu/WeChat UI
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

GROK_COOKIES_JSON   = os.getenv("SUPER_GROK_COOKIES", "")
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
# 🕸️ 网页版 Grok 自动化会话管理 (Playwright)
# ==============================================================================
def prepare_session_file() -> bool:
    if not GROK_COOKIES_JSON:
        print("[Session] Warning: SUPER_GROK_COOKIES not configured", flush=True)
        return False
    try:
        data = json.loads(GROK_COOKIES_JSON)
        if isinstance(data, dict) and "cookies" in data:
            with open("session_state.json", "w", encoding="utf-8") as f:
                json.dump(data, f)
            print("[Session] OK Playwright storage-state format (renewed)", flush=True)
            return True
        else:
            print(f"[Session] OK Cookie-Editor array format ({len(data)} entries)", flush=True)
            return False
    except Exception as e:
        print(f"[Session] ERROR Parse failed: {e}", flush=True)
        return False

def load_raw_cookies(context):
    try:
        cookies = json.loads(GROK_COOKIES_JSON)
        formatted = []
        for c in cookies:
            cookie = {"name": c.get("name", ""), "value": c.get("value", ""), "domain": c.get("domain", ".grok.com"), "path": c.get("path", "/")}
            if "httpOnly" in c: cookie["httpOnly"] = c["httpOnly"]
            if "secure" in c: cookie["secure"] = c["secure"]
            ss = c.get("sameSite", "")
            if ss in ("Strict", "Lax", "None"): cookie["sameSite"] = ss
            formatted.append(cookie)
        context.add_cookies(formatted)
        print(f"[Session] OK Injected {len(formatted)} cookies", flush=True)
    except Exception as e:
        print(f"[Session] ERROR Cookie injection failed: {e}", flush=True)

def save_and_renew_session(context):
    try:
        context.storage_state(path="session_state.json")
        print("[Session] OK Storage state saved locally", flush=True)
    except Exception as e:
        print(f"[Session] ERROR Save storage state failed: {e}", flush=True)
        return
    
    if not PAT_FOR_SECRETS or not GITHUB_REPOSITORY:
        return

    try:
        from nacl import encoding, public as nacl_public
        with open("session_state.json", "r", encoding="utf-8") as f:
            state_str = f.read()

        # 🚨 确保 GITHUB_REPOSITORY 没有多余的空格或斜杠
        repo_name = GITHUB_REPOSITORY.strip().strip("/")
        
        headers = {
            "Authorization": f"Bearer {PAT_FOR_SECRETS.strip()}", 
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        
        # 1. 获取公钥
        key_url = f"https://api.github.com/repos/{repo_name}/actions/secrets/public-key"
        key_resp = requests.get(key_url, headers=headers, timeout=30)
        
        if key_resp.status_code != 200:
            print(f"[Session] WARNING: 无法获取公钥。状态码: {key_resp.status_code}. 请检查 PAT 是否有 'Secrets: Read and write' 权限，且仓库名 {repo_name} 是否正确。", flush=True)
            return
            
        key_data = key_resp.json()

        # 2. 加密
        pub_key = nacl_public.PublicKey(key_data["key"].encode(), encoding.Base64Encoder())
        sealed  = nacl_public.SealedBox(pub_key).encrypt(state_str.encode())
        enc_b64 = base64.b64encode(sealed).decode()

        # 3. 更新 Secret
        put_url = f"https://api.github.com/repos/{repo_name}/actions/secrets/SUPER_GROK_COOKIES"
        payload = {"encrypted_value": enc_b64, "key_id": key_data["key_id"]}
        
        put_resp = requests.put(put_url, headers=headers, json=payload, timeout=30)
        
        if put_resp.status_code == 422:
            print("[Session] ERROR: 422 错误！API 请求体无法处理。请绝对确认你的 Token 是 Fine-Grained Token，并且具备对该仓库的 'Secrets' 读写权限！", flush=True)
        elif put_resp.status_code in [201, 204]:
            print("[Session] OK GitHub Secret SUPER_GROK_COOKIES auto-renewed", flush=True)
        else:
            print(f"[Session] ERROR: 更新 Secret 失败，状态码: {put_resp.status_code}", flush=True)
            
    except Exception as e:
        print(f"[Session] ERROR Secret renewal failed: {e}", flush=True)

def check_cookie_expiry():
    if not GROK_COOKIES_JSON: return
    try:
        data = json.loads(GROK_COOKIES_JSON)
        if not isinstance(data, list): return
        watched_names = {"sso", "auth_token", "ct0"}
        for c in data:
            cname = c.get("name", "")
            if cname in watched_names and c.get("expirationDate"):
                exp = datetime.fromtimestamp(c["expirationDate"], tz=timezone.utc)
                days_left = (exp - datetime.now(timezone.utc)).days
                if days_left <= 5:
                    print(f"[Cookie] Warning: Grok Cookie '{cname}' expires in {days_left} days", flush=True)
    except: pass

def enable_grok4_beta(page):
    print("\n[Model] Trying to enable Beta Toggle...", flush=True)
    selectors = ["button:has-text('Fast')", "button:has-text('Auto')", "button:has-text('Grok')", "button[aria-label*='model' i]", "button[data-testid*='model' i]"]
    model_btn = None
    for sel in selectors:
        try:
            model_btn = page.wait_for_selector(sel, timeout=4000)
            if model_btn: break
        except: continue
    if not model_btn: return
    try:
        model_btn.click()
        time.sleep(1)
        toggle = page.wait_for_selector("button[role='switch'], input[type='checkbox']", timeout=6000)
        is_on = page.evaluate("""() => { const sw = document.querySelector("button[role='switch']"); if (sw) return sw.getAttribute('aria-checked') === 'true' || sw.getAttribute('data-state') === 'checked'; const cb = document.querySelector("input[type='checkbox']"); return cb ? cb.checked : false; }""")
        if not is_on: toggle.click()
        page.keyboard.press("Escape")
        time.sleep(0.5)
    except Exception as e: pass

def _is_login_page(url: str) -> bool:
    lower = url.lower()
    return any(kw in lower for kw in ("sign", "login", "oauth", "x.com/i/flow"))

def open_grok_page(context):
    page = context.new_page()
    try:
        page.goto("https://grok.com", wait_until="domcontentloaded", timeout=60000)
        time.sleep(5) # 给首页多点时间加载前端框架
        if _is_login_page(page.url):
            print("ERROR: Not logged in - session expired", flush=True)
            page.close()
            return None
        enable_grok4_beta(page)
        return page
    except Exception as e:
        try: page.close()
        except: pass
        return None

def send_prompt(page, prompt_text, label):
    """
    V8.3 纯正硬件级模拟：放弃一切 JS 注入，完全使用键盘交互！
    """
    try:
        time.sleep(3) # 等待页面完全稳定
        
        # 1. 尝试找到页面上的输入框，使用 Playwright 原生的 fill
        # 我们寻找各种可能作为输入框的元素，并优先点击它以获取焦点
        input_locator = page.locator("textarea, .ProseMirror, div[contenteditable='true']").last
        
        try:
            # 尝试点击它
            input_locator.click(timeout=5000)
            time.sleep(0.5)
        except:
            # 如果点不到，盲按几下 Tab 试试运气
            for _ in range(3):
                page.keyboard.press("Tab")
                time.sleep(0.1)
                
        # 2. 清空可能存在的内容
        page.keyboard.press("Control+a")
        page.keyboard.press("Backspace")
        time.sleep(0.5)
        
        # 3. 🚨 暴力打字机：利用剪贴板机制（规避 JS 注入拦截）
        # 将长文本放入页面的一个隐藏元素中，然后用 JS 选中它，执行复制，再通过键盘执行粘贴。
        page.evaluate("""(text) => {
            const ta = document.createElement('textarea');
            ta.id = 'hacker_clipboard';
            ta.value = text;
            ta.style.position = 'absolute';
            ta.style.top = '-9999px';
            document.body.appendChild(ta);
        }""", prompt_text)
        
        # 让隐藏的 textarea 获取焦点并全选
        page.evaluate("""() => {
            const ta = document.getElementById('hacker_clipboard');
            ta.select();
        }""")
        
        # 执行系统级复制
        page.keyboard.press("Control+c")
        time.sleep(0.5)
        
        # 焦点切回刚才尝试获取的真实输入框
        try:
            input_locator.click()
        except:
            pass # 如果点不到就顺其自然，希望焦点是对的
            
        # 执行系统级粘贴
        page.keyboard.press("Control+v")
        time.sleep(1)
        
        # 兜底：如果剪贴板策略失败，用真实的打字 API 强行输入（为了速度，只在失败时用）
        # 我们检查一下输入框里有没有东西
        has_content = page.evaluate("""() => {
            const el = document.activeElement;
            if (!el) return false;
            return el.value?.length > 0 || el.textContent?.length > 0;
        }""")
        
        if not has_content:
             print(f"[{label}] 剪贴板失效，启用逐字硬敲模式...", flush=True)
             page.keyboard.type(prompt_text, delay=0.5) # 极快打字
             time.sleep(1)
             
        # 清理垃圾
        page.evaluate("""() => {
            const ta = document.getElementById('hacker_clipboard');
            if(ta) ta.remove();
        }""")

        # 4. 发送！
        page.keyboard.press("Enter")
        time.sleep(1)
        
        # 发送按钮双保险
        try:
             # 尝试寻找提交按钮并强制点击
             send_btn = page.locator("button[type='submit'], button[aria-label*='Send'], button[aria-label*='Submit']").last
             send_btn.click(timeout=3000, force=True)
        except:
             pass
             
        print(f"[{label}] OK Prompt Sent (Hardware Sim)", flush=True)
    except Exception as e:
        print(f"[{label}] WARNING Prompt issue: {e}", flush=True)
    time.sleep(8) # 多等一会儿，让它飞一会

def wait_and_extract(page, label, interval=3, stable_rounds=4, max_wait=120, extend_if_growing=False, min_len=80):
    last_len, stable, elapsed, last_text = -1, 0, 0, ""
    while elapsed < max_wait:
        time.sleep(interval)
        elapsed += interval
        try: 
            text = page.evaluate("""() => { 
                // 排除用户自己发送的 prompt，只抓取 AI 返回的块
                const msgs = Array.from(document.querySelectorAll('.message, [data-testid="message"], .message-bubble, .response-content, .ProseMirror-widget'));
                // 过滤掉包含我们特征词的块
                const ai_msgs = msgs.filter(m => !m.innerText.includes('You are an X/Twitter data collection tool'));
                
                if (ai_msgs.length === 0) return "";
                return ai_msgs[ai_msgs.length - 1].innerText; 
            }""")
        except: 
            return last_text.strip()
            
        last_text = text
        cur_len = len(text.strip())
        
        # 只有抓到有效的 JSON 行格式，才认为开始稳定
        if cur_len == last_len and cur_len >= min_len and "{" in text and "}" in text:
            stable += 1
            if stable >= stable_rounds: return text.strip()
        else:
            stable = 0
            last_len = cur_len
    return last_text.strip()

# 🚨 终极修复：使用正则的 {3} 替代三个反引号，避免语法截断！
def parse_jsonlines(text: str) -> list:
    results = []
    # 去除可能存在的 markdown 包装块
    text = re.sub(r'^`{3}(?:jsonl|json)?\n', '', text, flags=re.MULTILINE)
    text = re.sub(r'^`{3}\n?', '', text, flags=re.MULTILINE)
    
    for line in text.splitlines():
        line = line.strip()
        if not line or not line.startswith('{') or not line.endswith('}'): continue
        try: results.append(json.loads(line))
        except: continue
    return results

# ==============================================================================
# 🤖 抓取策略 Prompts (完全恢复附件原始逻辑)
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

def run_grok_batch(context, accounts: list, prompt_builder, label: str) -> list:
    if not accounts: return []
    page = open_grok_page(context)
    if not page: return []
    try:
        prompt = prompt_builder(accounts)
        send_prompt(page, prompt, label)
        print(f"[{label}] Waiting 60s for Grok to start searching...", flush=True)
        time.sleep(60)
        raw_text = wait_and_extract(page, label, interval=5, stable_rounds=5, max_wait=420, extend_if_growing=True, min_len=50)
        results = parse_jsonlines(raw_text)
        
        # 🚨 透视镜：如果解析出 0 条数据，直接把原话打出来，看看 Grok 到底说了什么鬼话
        if len(results) == 0:
            print(f"\n[{label}] ⚠️ 警告：解析到 0 条 JSON！Grok 的原始回复是：\n{raw_text[:800]}...\n", flush=True)
        else:
            print(f"[{label}] OK Parsed {len(results)} JSON objects", flush=True)
            
        return results
    except Exception as e: print(f"[{label}] ERROR: {e}", flush=True); return []
    finally:
        try: page.close()
        except: pass

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

# ==============================================================================
# 🚀 主程序入口
# ==============================================================================
def main():
    print("=" * 60, flush=True)
    mode_str = "测试模式(1个Batch-6人)" if TEST_MODE else "全量模式"
    print(f"昨晚硅谷在聊啥 v8.1 (硅谷100人 Grok网页抓取 + xAI提纯 - {mode_str})", flush=True)
    print("=" * 60, flush=True)

    today_str, _ = get_dates()
    Path("data").mkdir(exist_ok=True)
    
    check_cookie_expiry()
    
    # 🚨 测试模式下：只抽前 6 个人（2轮并发），保证绝对不会触发上下文溢出！
    selected_accounts = ALL_ACCOUNTS[:6] if TEST_MODE else ALL_ACCOUNTS
    meta_results, phase1_posts, phase2_posts = {}, {}, {}
    
    is_storage_state = prepare_session_file()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--disable-blink-features=AutomationControlled", "--window-size=1280,800"]
        )
        ctx_opts = {"viewport": {"width": 1280, "height": 800}, "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36", "locale": "zh-CN"}
        if is_storage_state: ctx_opts["storage_state"] = "session_state.json"
        
        context = browser.new_context(**ctx_opts)
        if not is_storage_state: load_raw_cookies(context)

        # 验证登录
        verify_page = context.new_page()
        verify_page.goto("https://grok.com", wait_until="domcontentloaded", timeout=60000)
        time.sleep(3)
        if _is_login_page(verify_page.url):
            print("ERROR: Grok Cookie expired. Update SUPER_GROK_COOKIES.", flush=True)
            browser.close()
            return
        verify_page.close()

        # --- Phase 1: 扫描 ---
        # 🚨 降载保命：每次只派发 20 人给 Grok，防止超载回复 0 结果
        BATCH_SIZE = 20
        for batch_num, batch_start in enumerate(range(0, len(selected_accounts), BATCH_SIZE), start=1):
            if TEST_MODE and batch_num > 1: break
            if time.time() - _START_TIME > PHASE1_DEADLINE: break
            
            batch = selected_accounts[batch_start:batch_start + BATCH_SIZE]
            label = f"Phase1-Batch{batch_num}"
            results = run_grok_batch(context, batch, build_phase1_prompt, label)
            
            for obj in results:
                account = obj.get("a", "").lstrip("@")
                if not account: continue
                if obj.get("type") == "meta": meta_results[account] = obj
                else: phase1_posts.setdefault(account, []).append(obj)

        # 分层
        classification = classify_accounts(meta_results)
        s_accounts = [a for a, t in classification.items() if t == "S"]
        a_accounts = [a for a, t in classification.items() if t == "A"]
        
        # --- Phase 2: S 级深挖 ---
        if s_accounts and time.time() - _START_TIME < GLOBAL_DEADLINE:
            s_results = run_grok_batch(context, s_accounts, build_phase2_s_prompt, label="Phase2-S")
            for obj in s_results:
                if obj.get("type") != "meta": phase2_posts.setdefault(obj.get("a", "").lstrip("@"), []).append(obj)

        # --- Phase 2: A 级深挖 (上次遗漏的函数已补全) ---
        if a_accounts and time.time() - _START_TIME < GLOBAL_DEADLINE:
            a_results = run_grok_batch(context, a_accounts, build_phase2_a_prompt, label="Phase2-A")
            for obj in a_results:
                if obj.get("type") != "meta": phase2_posts.setdefault(obj.get("a", "").lstrip("@"), []).append(obj)

        save_and_renew_session(context)
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
            
            print("\n🎉 V8.1 运行完毕！", flush=True)
        else:
            print("❌ LLM 处理失败，任务终止。")

if __name__ == "__main__":
    main()
