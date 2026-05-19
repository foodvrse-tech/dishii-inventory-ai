"""
whatsapp.py — Evolution API wrapper for Dishii
All WhatsApp operations go through this file.
"""
import os
import logging
import requests
from typing import Optional, List
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

EVOLUTION_URL      = os.getenv("EVOLUTION_URL", "").rstrip("/")
EVOLUTION_KEY      = os.getenv("EVOLUTION_KEY", "")
EVOLUTION_INSTANCE = os.getenv("EVOLUTION_INSTANCE", "dishii")

def _headers() -> dict:
    return {"Content-Type": "application/json", "apikey": EVOLUTION_KEY}


# ════════════════════════════════════════════════════════════════
# CONNECTION
# ════════════════════════════════════════════════════════════════

def is_connected() -> bool:
    """Returns True if WhatsApp instance is live."""
    if not EVOLUTION_URL or not EVOLUTION_KEY:
        return False
    try:
        r = requests.get(
            f"{EVOLUTION_URL}/instance/connectionState/{EVOLUTION_INSTANCE}",
            headers=_headers(), timeout=5
        )
        return r.status_code == 200 and r.json().get("instance", {}).get("state") == "open"
    except Exception:
        return False

def get_connection_status() -> str:
    """Returns 'open', 'connecting', or 'disconnected'."""
    if not EVOLUTION_URL or not EVOLUTION_KEY:
        return "not_configured"
    try:
        r = requests.get(
            f"{EVOLUTION_URL}/instance/connectionState/{EVOLUTION_INSTANCE}",
            headers=_headers(), timeout=5
        )
        if r.status_code == 200:
            return r.json().get("instance", {}).get("state", "unknown")
    except Exception:
        pass
    return "disconnected"


# ════════════════════════════════════════════════════════════════
# SEND
# ════════════════════════════════════════════════════════════════

def send(phone: str, text: str) -> bool:
    """
    Send a WhatsApp message to a single phone number.
    phone: digits only, e.g. 254720521291 (no + sign)
    Returns True on success.
    """
    clean = phone.replace("+", "").replace(" ", "").replace("-", "")
    if not clean:
        logger.warning("send(): empty phone number")
        return False
    if not EVOLUTION_URL or not EVOLUTION_KEY:
        logger.warning("send(): Evolution API not configured")
        return False
    try:
        r = requests.post(
            f"{EVOLUTION_URL}/message/sendText/{EVOLUTION_INSTANCE}",
            headers=_headers(),
            json={"number": clean, "text": text},
            timeout=15
        )
        success = r.status_code in (200, 201)
        if not success:
            logger.error(f"send() failed {r.status_code}: {r.text[:200]}")
        return success
    except requests.Timeout:
        logger.error(f"send() timeout for {clean}")
        return False
    except Exception as e:
        logger.error(f"send() error: {e}")
        return False

def send_to_all(phones: List[str], text: str) -> int:
    """Send same message to multiple phones. Returns count sent."""
    sent = 0
    for phone in phones:
        if send(phone, text):
            sent += 1
    return sent


# ════════════════════════════════════════════════════════════════
# MESSAGE TEMPLATES
# ════════════════════════════════════════════════════════════════

def msg_stock_alert(store_name: str, product: str, risk: str,
                    stock: int, stock_days: int, reason: str) -> str:
    emoji = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡"}.get(risk, "🟡")
    return (
        f"{emoji} *Dishii Stock Alert*\n\n"
        f"Store: *{store_name}*\n"
        f"Product: *{product}*\n"
        f"Status: {reason}\n"
        f"Stock: {stock} units ({stock_days} days left)\n\n"
        f"⚡ Action required — check dashboard."
    )

def msg_procurement_request(store_name: str, product: str, qty: int,
                             supplier: str, value: float,
                             request_id: str, urgency: str) -> str:
    emoji = "🔴" if urgency == "CRITICAL" else "🟠"
    return (
        f"{emoji} *Procurement Approval Needed*\n\n"
        f"Store: *{store_name}*\n"
        f"Product: *{product}*\n"
        f"Supplier: {supplier}\n"
        f"Quantity: *{qty} units*\n"
        f"Est. Value: KES {value:,.0f}\n\n"
        f"Reply:\n"
        f"*YES {request_id[:8]}* — to approve\n"
        f"*NO {request_id[:8]}* — to skip\n\n"
        f"_Ref: {request_id[:8]}_"
    )

def msg_procurement_approved(product: str, qty: int, supplier: str,
                              value: float, request_id: str) -> str:
    return (
        f"✅ *Order Approved*\n\n"
        f"Product: {product}\n"
        f"Quantity: {qty} units\n"
        f"Supplier: {supplier}\n"
        f"Value: KES {value:,.0f}\n"
        f"Ref: {request_id[:8]}\n\n"
        f"_Supplier has been notified._"
    )

def msg_procurement_rejected(product: str, request_id: str) -> str:
    return (
        f"❌ *Order Skipped*\n\n"
        f"Product: {product}\n"
        f"Ref: {request_id[:8]}\n\n"
        f"_I'll alert you again if stock gets critical._"
    )

def msg_supplier_order(store_name: str, product: str, qty: int,
                       request_id: str) -> str:
    return (
        f"📦 *New Order — {store_name}*\n\n"
        f"Product: *{product}*\n"
        f"Quantity: *{qty} units*\n"
        f"Ref: {request_id[:8]}\n\n"
        f"Please confirm availability and expected delivery.\n"
        f"Reply *CONFIRMED {request_id[:8]}* to acknowledge."
    )

def msg_hourly_briefing(store_name: str, briefing_text: str,
                        summary: dict) -> str:
    return (
        f"📊 *Dishii Hourly Briefing*\n"
        f"*{store_name}*\n\n"
        f"{briefing_text}\n\n"
        f"---\n"
        f"🔴 Critical: {summary.get('critical',0)}  "
        f"🟠 High: {summary.get('high',0)}  "
        f"🟢 Healthy: {summary.get('low',0)}\n"
        f"💰 Value: KES {summary.get('total_value',0):,.0f}  "
        f"⚠️ Waste: KES {summary.get('waste_value',0):,.0f}"
    )

def msg_welcome(store_name: str, manager_name: str) -> str:
    return (
        f"👋 Welcome to Dishii, *{manager_name}*!\n\n"
        f"You're now managing *{store_name}*.\n\n"
        f"You will receive:\n"
        f"• 🔴 Critical stock alerts\n"
        f"• 📊 Hourly AI briefings\n"
        f"• 📦 Procurement approvals\n\n"
        f"Reply *YES [ref]* to approve orders\n"
        f"Reply *NO [ref]* to skip orders\n\n"
        f"_Dishii — Autonomous Food Operations_"
    )


# ════════════════════════════════════════════════════════════════
# PARSE INCOMING REPLY
# ════════════════════════════════════════════════════════════════

def parse_manager_reply(text: str) -> dict:
    """
    Parse a manager's WhatsApp reply.
    Returns {"action": "YES"|"NO"|"UNKNOWN", "ref_id": "...|None"}
    Examples:
        "YES DEMO-001"  → {"action": "YES", "ref_id": "DEMO-001"}
        "NO abc12345"   → {"action": "NO",  "ref_id": "abc12345"}
        "yes"           → {"action": "YES", "ref_id": None}
        "no thanks"     → {"action": "NO",  "ref_id": None}
    """
    clean = text.strip().upper()
    parts = clean.split()
    action = "UNKNOWN"
    ref_id = None

    YES_WORDS = {"YES", "Y", "APPROVE", "OK", "SAWA", "NDIO", "1"}
    NO_WORDS  = {"NO",  "N", "REJECT",  "SKIP", "HAPANA", "0"}

    if parts:
        if parts[0] in YES_WORDS:
            action = "YES"
        elif parts[0] in NO_WORDS:
            action = "NO"
        # fallback: check if any word matches
        else:
            for word in parts:
                if word in YES_WORDS:
                    action = "YES"; break
                if word in NO_WORDS:
                    action = "NO"; break

        if len(parts) > 1:
            ref_id = parts[1]

    return {"action": action, "ref_id": ref_id}