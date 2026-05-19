"""
Dishii v7.0 - Demo-Ready Production Platform
Multi-store · Multi-manager · WhatsApp automation · Claude AI briefings
POS simulation · Autonomous supplier procurement
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
from supabase import create_client
import os, io, base64, re, hashlib, json, logging, requests, uuid, time
from dotenv import load_dotenv
from typing import Dict, Tuple, Optional, List
import warnings
warnings.filterwarnings("ignore")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
load_dotenv()

# ─── CONFIG ────────────────────────────────────────────────────────────────────
SUPABASE_URL       = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY       = os.getenv("SUPABASE_KEY", "")
ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "")   # Primary AI
GEMINI_API_KEY     = os.getenv("GEMINI_API_KEY", "")       # Fallback AI
EVOLUTION_URL      = os.getenv("EVOLUTION_URL", "").rstrip("/")
EVOLUTION_KEY      = os.getenv("EVOLUTION_KEY", "")
EVOLUTION_INSTANCE = os.getenv("EVOLUTION_INSTANCE", "dishii")
N8N_WEBHOOK        = os.getenv("N8N_WEBHOOK", "")

# ─── INIT CLIENTS ──────────────────────────────────────────────────────────────
if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("❌ Missing Supabase credentials. Check your .env file.")
    st.stop()

try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error(f"❌ Supabase init failed: {e}")
    st.stop()

# ─── PAGE CONFIG ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Dishii | Autonomous Food Operations",
    page_icon="🍔",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .main .block-container{padding-top:0.5rem !important;padding-bottom:1rem !important;max-width:1400px}
    [data-testid="stSidebar"]{background:#0f172a;border-right:1px solid #1e293b;min-width:290px}
    #MainMenu{visibility:visible!important}footer{visibility:hidden}

    .hero{background:linear-gradient(135deg,#0f172a,#1e293b);padding:1.25rem 1.75rem;border-radius:16px;margin-bottom:1rem;border:1px solid #334155}
    .hero-title{font-size:1.6rem;font-weight:700;background:linear-gradient(135deg,#10b981,#34d399);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
    .hero-sub{font-size:0.85rem;color:#94a3b8;margin-top:2px}

    .kpi{padding:1rem;border-radius:12px;background:#1e293b;border:1px solid #334155;text-align:center;transition:all .2s}
    .kpi:hover{border-color:#10b981;transform:translateY(-2px)}
    .kpi-label{font-size:0.7rem;color:#64748b;text-transform:uppercase;letter-spacing:.5px}
    .kpi-value{font-size:1.6rem;font-weight:700;color:#f1f5f9;margin:2px 0}
    .kpi-sub{font-size:0.65rem;color:#475569}

    .card{background:#1e293b;border-radius:12px;padding:.8rem 1rem;margin-bottom:.6rem;border-left:4px solid;transition:all .2s}
    .card:hover{background:#263344;transform:translateX(3px)}
    .card-title{font-size:.9rem;font-weight:600;color:#f1f5f9;margin-bottom:2px}
    .card-sub{font-size:.68rem;color:#94a3b8;margin-bottom:4px}
    .card-meta{font-size:.65rem;color:#475569}

    .store-badge{display:inline-block;padding:2px 8px;border-radius:20px;font-size:.65rem;font-weight:600;background:#1e293b;border:1px solid #334155;color:#94a3b8;margin-right:4px}
    .wa-badge{background:#0d3d26;border-color:#10b981;color:#34d399}
    .ai-badge{background:#1e1b4b;border-color:#6366f1;color:#a5b4fc}

    .stTabs [data-baseweb="tab-list"]{gap:.4rem;background:#1e293b;padding:.4rem;border-radius:10px;margin-bottom:.8rem}
    .stTabs [data-baseweb="tab"]{border-radius:7px;padding:.4rem .9rem;font-weight:500;font-size:.85rem}
    .stTabs [aria-selected="true"]{background:#10b981;color:#fff}
    .stProgress>div>div{background:#10b981}
    div[data-testid="stMetricValue"]{font-size:1.3rem;font-weight:700}

    .pos-item{background:#1e293b;border-radius:8px;padding:.6rem .8rem;margin-bottom:.4rem;display:flex;justify-content:space-between;align-items:center;border:1px solid #334155}
    .supplier-msg{background:#0d1f0d;border:1px solid #166534;border-radius:10px;padding:.8rem 1rem;margin-bottom:.5rem;font-size:.8rem;color:#86efac;font-family:monospace}
</style>
""", unsafe_allow_html=True)

# ─── SESSION STATE ─────────────────────────────────────────────────────────────
DEFAULTS = {
    "current_store_id": None,
    "current_store": None,
    "current_df": None,
    "current_summary": None,
    "pos_cart": {},
    "upload_hash": None,
    "briefing_cache": {},
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ══════════════════════════════════════════════════════════════════════════════
# WHATSAPP — Evolution API
# ══════════════════════════════════════════════════════════════════════════════

def _wa_headers() -> dict:
    return {"Content-Type": "application/json", "apikey": EVOLUTION_KEY}

@st.cache_data(ttl=30)
def wa_connected() -> bool:
    if not EVOLUTION_URL or not EVOLUTION_KEY:
        return False
    try:
        r = requests.get(
            f"{EVOLUTION_URL}/instance/connectionState/{EVOLUTION_INSTANCE}",
            headers={"apikey": EVOLUTION_KEY}, timeout=5
        )
        return r.status_code == 200 and r.json().get("instance", {}).get("state") == "open"
    except Exception:
        return False

def wa_send(phone: str, text: str) -> bool:
    """Send WhatsApp message. Returns True on success."""
    if not wa_connected():
        logger.warning(f"[WA SKIPPED — not connected] → {phone}: {text[:60]}")
        return False
    try:
        clean = re.sub(r"[^\d]", "", phone)
        r = requests.post(
            f"{EVOLUTION_URL}/message/sendText/{EVOLUTION_INSTANCE}",
            headers=_wa_headers(),
            json={"number": clean, "text": text},
            timeout=15
        )
        ok = r.status_code in (200, 201)
        if not ok:
            logger.error(f"WA send failed {r.status_code}: {r.text[:200]}")
        return ok
    except Exception as e:
        logger.error(f"WA send error: {e}")
        return False

def wa_send_to_managers(store: dict, message: str) -> int:
    """Send to all managers of a store. Returns count sent."""
    phones = _get_manager_phones(store)
    sent = 0
    for phone in phones:
        if wa_send(phone, message):
            sent += 1
            time.sleep(0.5)  # avoid rate limiting
    return sent

def _get_manager_phones(store: dict) -> List[str]:
    """Extract all non-empty manager phone numbers from store record."""
    phones = []
    for i in range(1, 5):
        p = store.get(f"manager_{i}_phone", "")
        if p and str(p).strip():
            phones.append(str(p).strip())
    return phones

# ══════════════════════════════════════════════════════════════════════════════
# AI — Claude primary, Gemini fallback
# ══════════════════════════════════════════════════════════════════════════════

def ai_briefing(summary: dict, store_name: str) -> str:
    """Generate operational briefing. Claude first, Gemini fallback."""
    prompt = f"""You are Dishii AI — autonomous operations intelligence for food retail.

Store: {store_name}
Time: {datetime.now().strftime('%d %b %Y %H:%M')}

Inventory snapshot:
- Total SKUs: {summary['total']}
- CRITICAL 🔴: {summary['red']} (act today)
- HIGH 🟠: {summary['amber']} (act this week)  
- HEALTHY 🟢: {summary['green']}
- Orders needed: {summary['orders']}
- Inventory value: KES {summary.get('total_value',0):,.0f}
- Waste risk: KES {summary.get('projected_waste',0):,.0f}
- Recovery potential: KES {summary.get('recovery_value',0):,.0f}
- Health score: {summary.get('health_score',0)}%

Write a sharp 4-section briefing (max 180 words total):
1. 🚨 TODAY'S PRIORITIES — top 3 actions right now
2. 💰 FINANCIAL RISK — KES at stake if ignored
3. 🛒 PROCUREMENT — what to order, from whom, how much
4. 📅 WATCH LIST — what to monitor this week

Be specific, use numbers, be direct. No fluff."""

    # Try Claude first
    if ANTHROPIC_API_KEY:
        try:
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 400,
                    "messages": [{"role": "user", "content": prompt}]
                },
                timeout=20
            )
            if r.status_code == 200:
                return r.json()["content"][0]["text"]
        except Exception as e:
            logger.error(f"Claude AI error: {e}")

    # Gemini fallback
    if GEMINI_API_KEY:
        try:
            from google import genai
            client = genai.Client(api_key=GEMINI_API_KEY)
            resp = client.models.generate_content(
                model="models/gemini-2.0-flash", contents=prompt
            )
            return resp.text
        except Exception as e:
            logger.error(f"Gemini fallback error: {e}")

    return (
        f"⚠️ AI briefing unavailable.\n\n"
        f"Manual summary: {summary['red']} critical items, "
        f"{summary['orders']} orders needed, "
        f"KES {summary.get('projected_waste',0):,.0f} waste risk.\n\n"
        f"Add ANTHROPIC_API_KEY to .env for AI briefings."
    )

def ai_supplier_message(product: str, qty: int, supplier: str,
                         store_name: str, urgency: str) -> str:
    """Generate a professional supplier procurement request."""
    prompt = f"""Write a brief, professional WhatsApp procurement request.

From: {store_name} (via Dishii automated procurement)
To: {supplier}
Product: {product}
Quantity needed: {qty} units
Urgency: {urgency}

Write as a friendly but professional order request. Under 100 words.
Include: what we need, quantity, that we need delivery ASAP for urgent or within 3 days for standard.
End with: "Please confirm availability and delivery time."
No emojis except one at the start."""

    if ANTHROPIC_API_KEY:
        try:
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 200,
                    "messages": [{"role": "user", "content": prompt}]
                },
                timeout=15
            )
            if r.status_code == 200:
                return r.json()["content"][0]["text"]
        except Exception:
            pass

    # Fallback template
    urgency_line = "ASAP — critical stock level" if urgency == "URGENT" else "within 3 days"
    return (
        f"📦 Procurement request from {store_name}\n\n"
        f"Hi {supplier},\n\n"
        f"We need to restock {product}.\n"
        f"Quantity: {qty} units\n"
        f"Required: {urgency_line}\n\n"
        f"Please confirm availability and delivery time.\n\n"
        f"— {store_name} via Dishii"
    )

# ══════════════════════════════════════════════════════════════════════════════
# DATABASE — Store & inventory operations
# ══════════════════════════════════════════════════════════════════════════════

def db_get_stores() -> List[dict]:
    try:
        r = supabase.table("businesses").select("*").eq("is_active", True)\
            .order("business_name").execute()
        return r.data or []
    except Exception as e:
        logger.error(f"db_get_stores: {e}")
        return []

def db_save_store(data: dict) -> Optional[dict]:
    try:
        slug = re.sub(r"[^a-z0-9]+", "-", data["business_name"].lower()).strip("-")
        # Check existing
        ex