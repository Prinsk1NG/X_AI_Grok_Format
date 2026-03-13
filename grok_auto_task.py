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

        # 🚨 修复 422 报错：必须加上 X-GitHub-Api-Version
        headers = {
            "Authorization": f"Bearer {PAT_FOR_SECRETS}", 
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        key_resp = requests.get(f"https://api.github.com/repos/{GITHUB_REPOSITORY}/actions/secrets/public-key", headers=headers, timeout=30)
        key_resp.raise_for_status()
        key_data = key_resp.json()

        pub_key = nacl_public.PublicKey(key_data["key"].encode(), encoding.Base64Encoder())
        sealed  = nacl_public.SealedBox(pub_key).encrypt(state_str.encode())
        enc_b64 = base64.b64encode(sealed).decode()

        put_resp = requests.put(
            f"https://api.github.com/repos/{GITHUB_REPOSITORY}/actions/secrets/SUPER_GROK_COOKIES",
            headers=headers, json={"encrypted_value": enc_b64, "key_id": key_data["key_id"]}, timeout=30
        )
        put_resp.raise_for_status()
        print("[Session] OK GitHub Secret SUPER_GROK_COOKIES auto-renewed", flush=True)
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
        time.sleep(3)
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
    page.wait_for_selector("div[contenteditable='true'], textarea", timeout=30000)
    ok = page.evaluate("""(text) => { const el = document.querySelector("div[contenteditable='true']") || document.querySelector("textarea"); if (!el) return false; el.focus(); document.execCommand('selectAll', false, null); document.execCommand('delete', false, null); document.execCommand('insertText', false, text); return el.textContent.length > 0 || el.value?.length > 0; }""", prompt_text)
    if not ok:
        inp = page.query_selector("div[contenteditable='true'], textarea")
        if inp:
            inp.click()
            page.keyboard.press("Control+a")
            page.keyboard.press("Backspace")
            for i in range(0, len(prompt_text), 500):
                page.keyboard.type(prompt_text[i:i+500])
                time.sleep(0.2)
    time.sleep(1.5)
    try:
        send_btn = page.wait_for_selector("button[aria-label='Submit']:not([disabled]), button[aria-label='Send message']:not([disabled]), button[type='submit']:not([disabled])", timeout=30000, state="visible")
        send_btn.click()
    except Exception as e:
        page.evaluate("""() => { const btn = document.query_selector("button[type='submit']") || document.query_selector("button[aria-label='Submit']") || document.query_selector("button[aria-label='Send message']"); if (btn) btn.click(); }""")
    print(f"[{label}] OK Prompt Sent", flush=True)
    time.sleep(5)

def wait_and_extract(page, label, interval=3, stable_rounds=4, max_wait=120, extend_if_growing=False, min_len=80):
    last_len, stable, elapsed, last_text = -1, 0, 0, ""
    while elapsed < max_wait:
        time.sleep(interval)
        elapsed += interval
        try: text = page.evaluate("""() => { const msgs = document.querySelectorAll('[data-testid="message"], .message-bubble, .response-content'); return msgs.length ? msgs[msgs.length - 1].innerText : ""; }""")
        except: return last_text.strip()
        last_text = text
        cur_len = len(text.strip())
        if cur_len == last_len and cur_len >= min_len:
            stable += 1
            if stable >= stable_rounds: return text.strip()
        else:
            stable = 0
            last_len = cur_len
    return last_text.strip()

def parse_jsonlines(text: str) -> list:
    results = []
    # 去除可能存在的 markdown 包装块
    text = re.sub(r'^
