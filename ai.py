"""
ai.py — AI and Risk Engine for Dishii
Uses Anthropic API via Vertex AI (AnthropicVertex).
Also contains the traffic light classification engine.
"""
import os
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# ── Anthropic client (Vertex AI) ─────────────────────────────
_client = None

def get_ai_client():
    global _client
    if _client is not None:
        return _client
    try:
        from anthropic import AnthropicVertex
        project_id = os.getenv("GCP_PROJECT_ID", "")
        region     = os.getenv("GCP_REGION", "us-east5")
        if not project_id:
            logger.warning("GCP_PROJECT_ID not set — AI briefings will use fallback")
            return None
        _client = AnthropicVertex(project_id=project_id, region=region)
        return _client
    except ImportError:
        logger.warning("anthropic[vertex] not installed — run: pip install anthropic[vertex]")
        return None
    except Exception as e:
        logger.error(f"AnthropicVertex init failed: {e}")
        return None


# ════════════════════════════════════════════════════════════════
# TRAFFIC LIGHT RISK ENGINE
# Your exact spec, implemented correctly
# ════════════════════════════════════════════════════════════════

# Category-specific shelf life caps (days)
SHELF_LIFE = {
    "fresh_produce": 7,
    "fresh_meat":    4,
    "dairy":         14,
    "dry_goods":     365
}

# Category-specific expiry thresholds
# (critical_days, high_days) — days to expiry
CAT_THRESHOLDS = {
    "fresh_produce": (3,  7),
    "fresh_meat":    (2,  4),
    "dairy":         (5, 10),
    "dry_goods":     (7, 14)   # overridden by user settings for dry goods
}

PRODUCE_KW = {"tomato","onion","spinach","kale","cabbage","carrot","banana","apple",
               "avocado","mango","pineapple","watermelon","ginger","garlic","lettuce",
               "broccoli","pepper","cucumber","potato","sukuma","dhania","courgette"}
MEAT_KW    = {"beef","chicken","sausage","minced","meat","pork","lamb","goat",
               "steak","breast","fillet","bacon","ham","fish","tilapia","salmon"}
DAIRY_KW   = {"milk","yogurt","yoghurt","cheese","butter","cream","ghee","mala","curd"}

def detect_category(name: str) -> str:
    n = (name or "").lower()
    if any(k in n for k in PRODUCE_KW): return "fresh_produce"
    if any(k in n for k in MEAT_KW):    return "fresh_meat"
    if any(k in n for k in DAIRY_KW):   return "dairy"
    return "dry_goods"

def fix_expiry(val, category: str):
    """Cap expiry dates to category shelf life max."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    today = datetime.now().date()
    try:
        d = pd.to_datetime(val, errors="coerce")
        if pd.isna(d):
            return None
        d = d.date()
        max_days = SHELF_LIFE.get(category, 365)
        if (d - today).days > max_days:
            return today + timedelta(days=max_days)
        return d
    except Exception:
        return None

def days_until(dt) -> Optional[int]:
    if dt is None or (hasattr(dt, "isnull") and pd.isnull(dt)):
        return None
    try:
        today = datetime.now().date()
        d = dt.date() if hasattr(dt, "date") else dt
        return (d - today).days
    except Exception:
        return None

def classify_item(row: dict, red_threshold: int = 30, amber_threshold: int = 60,
                  stock_warn: int = 14) -> dict:
    """
    Classify a single inventory item using the traffic light system.
    Returns classification fields to be stored in inventory_items.

    Priority hierarchy (highest wins):
    1. CRITICAL — expired, waste > 0, stockout risk (stock_days <= 3), expiring <= 7 days
    2. HIGH     — low stock (stock_days <= 7), expiring <= 14 days
    3. MEDIUM   — overstocked, slow-moving, expiring 14-30 days
    4. LOW      — healthy
    """
    cat         = row.get("category", "dry_goods")
    stock       = float(row.get("current_stock", 0) or 0)
    sales_rate  = max(float(row.get("daily_sales_rate", 0) or 0), 0.001)
    selling_p   = float(row.get("selling_price", 0) or 0)
    dte         = row.get("days_to_expiry")  # int or None

    # Stock coverage in days
    cover = stock / sales_rate if sales_rate > 0 else 999
    expiry_wall = max(dte, 0) if dte is not None else 999
    stock_days  = min(cover, expiry_wall) if dte is not None else cover

    # Waste calculation
    max_sellable = sales_rate * max(dte, 0) if dte is not None else stock
    waste_units  = max(0, stock - max_sellable)
    waste_value  = waste_units * selling_p
    inv_value    = stock * selling_p
    is_expired   = (dte is not None and dte < 0)

    # Discount recommendation
    discount = 0
    if dte is not None and dte > 0:
        if dte <= 2:  discount = 75
        elif dte <= 4: discount = 65
        elif dte <= 7: discount = 50
    if is_expired:
        discount = 100

    recovery = min(stock, max_sellable) * selling_p * (1 - discount / 100)
    if is_expired:
        recovery = 0

    # ── Category thresholds ──────────────────────────────────
    crit_exp, high_exp = CAT_THRESHOLDS.get(cat, (7, 14))

    # ── Classification logic (exact spec) ────────────────────
    severity  = "LOW"
    risk_type = "HEALTHY"
    risk_score = 0
    reasons = []

    # CRITICAL conditions
    if is_expired:
        severity = "CRITICAL"; risk_type = "WASTE"
        reasons.append("Expired — remove from shelf")
        risk_score = 100

    elif waste_units > 0:
        severity = "CRITICAL"; risk_type = "WASTE"
        reasons.append(f"{int(waste_units)} units will expire unsold")
        risk_score = 95

    elif stock_days <= 3 and stock > 0:
        severity = "CRITICAL"; risk_type = "STOCKOUT"
        reasons.append(f"Stockout risk — only {int(stock_days)} days left")
        risk_score = 90

    elif dte is not None and 0 < dte <= crit_exp:
        severity = "CRITICAL"; risk_type = "WASTE"
        reasons.append(f"Expiring in {dte} days")
        risk_score = 85

    # HIGH conditions
    elif stock_days <= 7 and stock > 0:
        severity = "HIGH"; risk_type = "STOCKOUT"
        reasons.append(f"Low stock — {int(stock_days)} days left")
        risk_score = 70

    elif dte is not None and crit_exp < dte <= high_exp:
        severity = "HIGH"; risk_type = "WASTE"
        reasons.append(f"Expiring in {dte} days")
        risk_score = 65

    # MEDIUM conditions
    elif stock_days > 60:
        severity = "MEDIUM"; risk_type = "OVERSTOCK"
        reasons.append(f"Overstocked — {int(stock_days)} days of cover")
        risk_score = 40

    elif sales_rate < 0.5 and stock > 0:
        severity = "MEDIUM"; risk_type = "OVERSTOCK"
        reasons.append("Slow-moving product")
        risk_score = 35

    elif dte is not None and high_exp < dte <= amber_threshold:
        severity = "MEDIUM"; risk_type = "WASTE"
        reasons.append(f"Expiring in {dte} days")
        risk_score = 30

    # LOW — healthy
    else:
        severity = "LOW"; risk_type = "HEALTHY"
        reasons.append("Healthy — normal operations")
        risk_score = 0

    # Traffic light mapping
    tl_map = {
        "CRITICAL": ("🔴", "#dc2626"),
        "HIGH":     ("🟠", "#f59e0b"),
        "MEDIUM":   ("🟡", "#eab308"),
        "LOW":      ("🟢", "#10b981")
    }
    traffic_light, risk_color = tl_map.get(severity, ("🟢", "#10b981"))

    # Order required
    order_required = risk_type == "STOCKOUT" and not is_expired
    stock_action = "✅ ADEQUATE"
    if is_expired:
        stock_action = "❌ EXPIRED — Remove immediately"
    elif risk_type == "WASTE" and waste_units > 0:
        stock_action = f"⛔ DO NOT ORDER — {int(waste_units)} units will rot"
    elif severity == "CRITICAL" and order_required:
        stock_action = f"🛒 ORDER NOW — {int(stock_days)} days left"
    elif severity == "HIGH" and order_required:
        stock_action = f"📦 ORDER SOON — {int(stock_days)} days left"
    elif risk_type == "OVERSTOCK":
        stock_action = "⏸️ PAUSE ORDERS — Overstocked"

    return {
        "stock_days":       round(stock_days, 1),
        "waste_units":      round(waste_units, 1),
        "waste_value":      round(waste_value, 2),
        "inventory_value":  round(inv_value, 2),
        "recovery_value":   round(recovery, 2),
        "discount_percent": discount,
        "traffic_light":    traffic_light,
        "severity_level":   severity,
        "risk_type":        risk_type,
        "risk_score":       risk_score,
        "risk_reason":      "; ".join(reasons),
        "risk_color":       risk_color,
        "order_required":   order_required,
        "stock_action":     stock_action,
        "is_expired":       is_expired,
        "show_in_priority": severity in ("CRITICAL", "HIGH"),
        "updated_at":       datetime.now().isoformat()
    }


def classify_dataframe(df: pd.DataFrame,
                        red_threshold: int = 30,
                        amber_threshold: int = 60,
                        stock_warn: int = 14) -> pd.DataFrame:
    """Apply traffic light classification to entire DataFrame."""
    df = df.copy()
    results = [
        classify_item(row.to_dict(), red_threshold, amber_threshold, stock_warn)
        for _, row in df.iterrows()
    ]
    results_df = pd.DataFrame(results)
    for col in results_df.columns:
        df[col] = results_df[col].values
    return df


def build_summary(df: pd.DataFrame) -> dict:
    """Build upload summary from classified DataFrame."""
    total_inv   = float(df.get("inventory_value", pd.Series([0])).sum()) if "inventory_value" in df.columns else 0
    total_waste = float(df.get("waste_value",     pd.Series([0])).sum()) if "waste_value"     in df.columns else 0
    health = max(0, min(100, int(100 - (total_waste / max(total_inv, 1)) * 100)))
    return {
        "total":       len(df),
        "critical":    int((df.get("severity_level","") == "CRITICAL").sum()),
        "high":        int((df.get("severity_level","") == "HIGH").sum()),
        "medium":      int((df.get("severity_level","") == "MEDIUM").sum()),
        "low":         int((df.get("severity_level","") == "LOW").sum()),
        "total_value": round(total_inv, 2),
        "waste_value": round(total_waste, 2),
        "health_score":health
    }


# ════════════════════════════════════════════════════════════════
# AI BRIEFING
# ════════════════════════════════════════════════════════════════

def generate_briefing(store_name: str, summary: dict, critical_items: list) -> str:
    """
    Generate operational briefing using Claude via Vertex AI.
    Falls back to a rule-based briefing if AI is unavailable.
    """
    client = get_ai_client()
    if client is None:
        return _rule_based_briefing(store_name, summary, critical_items)

    items_text = "\n".join([
        f"  - {i.get('product_name','?')} "
        f"[{i.get('severity_level','?')} / {i.get('risk_type','?')}]: "
        f"{i.get('risk_reason','')}"
        for i in critical_items[:8]
    ]) or "  None"

    prompt = f"""You are Dishii AI, the autonomous operations intelligence for {store_name}.

Inventory snapshot:
- Total SKUs: {summary['total']}
- 🔴 CRITICAL: {summary['critical']}
- 🟠 HIGH: {summary['high']}
- 🟡 MEDIUM: {summary['medium']}
- 🟢 LOW/HEALTHY: {summary['low']}
- Inventory value: KES {summary['total_value']:,.0f}
- Waste risk: KES {summary['waste_value']:,.0f}
- Health score: {summary['health_score']}%

Critical items:
{items_text}

Write a 4-section operational briefing. Be specific about product names. Under 180 words.

Format exactly as:
🚨 IMMEDIATE (2 actions for next 2 hours)
💰 FINANCIAL RISK (what happens if no action, in KES)
🛒 ORDER NOW (which products, from which suppliers)
📅 WATCH TODAY (2 items to monitor)"""

    try:
        response = client.messages.create(
            model=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6"),
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text
    except Exception as e:
        logger.error(f"AI briefing failed: {e}")
        return _rule_based_briefing(store_name, summary, critical_items)


def _rule_based_briefing(store_name: str, summary: dict, critical_items: list) -> str:
    """Fallback briefing when AI is unavailable."""
    crit = [i for i in critical_items if i.get("severity_level") == "CRITICAL"]
    high = [i for i in critical_items if i.get("severity_level") == "HIGH"]

    imm1 = f"Remove {crit[0]['product_name']} — {crit[0]['risk_reason']}" if crit else "Check fresh produce for expiry"
    imm2 = f"Order {high[0]['product_name']} — {high[0]['risk_reason']}" if high else "Review dairy stock levels"

    return (
        f"🚨 IMMEDIATE\n{imm1}\n{imm2}\n\n"
        f"💰 FINANCIAL RISK\n"
        f"KES {summary['waste_value']:,.0f} at risk if no action. "
        f"{summary['critical']} critical items need attention today.\n\n"
        f"🛒 ORDER NOW\n"
        + (", ".join([i['product_name'] for i in critical_items[:3]]) or "All levels healthy") + "\n\n"
        f"📅 WATCH TODAY\nMonitor fresh produce and dairy expiry dates."
    )


# ════════════════════════════════════════════════════════════════
# COLUMN NORMALIZATION
# ════════════════════════════════════════════════════════════════

COLUMN_MAP = {
    "product_name":    ["product_name","product","item","name","description","sku_name","item_name","item description"],
    "expiry_date":     ["expiry_date","expiry","best_before","expiration_date","exp_date","use_by","expiration"],
    "current_stock":   ["current_stock","stock","quantity","qty","inventory","units","on_hand","balance","stock_on_hand"],
    "daily_sales_rate":["daily_sales_rate","daily_sales","sales_rate","velocity","avg_daily_sales","movement","avg_sales","sold_per_day"],
    "supplier":        ["supplier","vendor","supplier_name","vendor_name","source"],
    "selling_price":   ["selling_price","price","retail_price","unit_price","cost","sale_price"],
    "supplier_phone":  ["supplier_phone","supplier_whatsapp","supplier_contact","phone","tel"],
    "supplier_email":  ["supplier_email","email"],
    "cost_price":      ["cost_price","cost","purchase_price","buy_price"]
}

def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize column names and fill defaults."""
    df = df.copy()
    df.columns = df.columns.str.lower().str.strip().str.replace(r"\s+", "_", regex=True)

    for target, candidates in COLUMN_MAP.items():
        if target not in df.columns:
            for c in candidates:
                if c in df.columns:
                    df[target] = df[c]
                    break

    # Defaults
    if "product_name"    not in df.columns: df["product_name"]    = [f"Item {i+1}" for i in range(len(df))]
    if "selling_price"   not in df.columns: df["selling_price"]   = 100.0
    if "current_stock"   not in df.columns: df["current_stock"]   = 0.0
    if "daily_sales_rate"not in df.columns: df["daily_sales_rate"]= 1.0
    if "cost_price"      not in df.columns: df["cost_price"]      = 0.0

    for col, default in [("selling_price", 100.0), ("current_stock", 0.0),
                          ("daily_sales_rate", 1.0), ("cost_price", 0.0)]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(default)

    return df


def process_upload(df: pd.DataFrame, store_id: str, upload_id: str,
                   red_threshold: int = 30, amber_threshold: int = 60,
                   stock_warn: int = 14) -> Tuple[pd.DataFrame, dict]:
    """
    Full pipeline: normalize → categorize → fix expiry → classify.
    Returns (processed_df, summary).
    """
    df = normalize_dataframe(df)
    df["category"]      = df["product_name"].apply(detect_category)
    df["expiry_date"]   = df.apply(lambda r: fix_expiry(r.get("expiry_date"), r["category"]), axis=1)
    df["expiry_date"]   = pd.to_datetime(df["expiry_date"], errors="coerce")
    df["days_to_expiry"]= df["expiry_date"].apply(days_until)
    df = classify_dataframe(df, red_threshold, amber_threshold, stock_warn)

    # Add IDs for DB insert
    df["store_id"]  = store_id
    df["upload_id"] = upload_id

    summary = build_summary(df)
    return df, summary


def df_to_db_rows(df: pd.DataFrame) -> list:
    """
    Convert processed DataFrame to list of dicts ready for Supabase insert.
    Only includes columns that exist in the inventory_items table.
    """
    DB_COLS = [
        "store_id", "upload_id", "product_name", "category",
        "supplier", "supplier_phone", "supplier_email",
        "selling_price", "cost_price", "current_stock", "daily_sales_rate",
        "expiry_date", "days_to_expiry", "stock_days",
        "waste_units", "waste_value", "inventory_value", "recovery_value",
        "discount_percent", "traffic_light", "severity_level", "risk_type",
        "risk_score", "risk_reason", "risk_color",
        "order_required", "stock_action", "is_expired", "show_in_priority"
    ]
    rows = []
    for _, row in df.iterrows():
        r = {}
        for col in DB_COLS:
            val = row.get(col)
            if col == "expiry_date":
                if pd.notna(val) and val is not None:
                    try:
                        r[col] = str(val.date()) if hasattr(val, "date") else str(val)
                    except Exception:
                        r[col] = None
                else:
                    r[col] = None
            elif isinstance(val, (np.integer, np.int64)):
                r[col] = int(val)
            elif isinstance(val, (np.floating, np.float64)):
                r[col] = float(val) if not np.isnan(val) else 0.0
            elif isinstance(val, (bool, np.bool_)):
                r[col] = bool(val)
            elif val is None or (isinstance(val, float) and np.isnan(val)):
                r[col] = None
            else:
                r[col] = str(val)[:500] if col in ("risk_reason", "stock_action") else val
        rows.append(r)
    return rows
