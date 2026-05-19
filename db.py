"""
db.py — All Supabase operations for Dishii
Nothing touches Supabase except through this file.
"""
import os
import re
import hashlib
import logging
from datetime import datetime
from typing import Optional, List, Dict, Tuple
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# ── Client ────────────────────────────────────────────────────
_supabase: Optional[Client] = None

def get_db() -> Client:
    global _supabase
    if _supabase is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        if not url or not key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in .env")
        _supabase = create_client(url, key)
    return _supabase


# ════════════════════════════════════════════════════════════════
# STORES
# ════════════════════════════════════════════════════════════════

def get_all_stores() -> List[Dict]:
    """Return all active stores."""
    try:
        r = get_db().table("stores").select("*").eq("is_active", True).order("name").execute()
        return r.data or []
    except Exception as e:
        logger.error(f"get_all_stores: {e}")
        return []

def get_store_by_id(store_id: str) -> Optional[Dict]:
    try:
        r = get_db().table("stores").select("*").eq("id", store_id).single().execute()
        return r.data
    except Exception as e:
        logger.error(f"get_store_by_id: {e}")
        return None

def create_store(name: str, location: str = "", store_type: str = "supermarket") -> Optional[Dict]:
    """Create a new store. Returns the created store dict."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")
    # Ensure slug uniqueness
    existing = get_db().table("stores").select("id").eq("slug", slug).execute()
    if existing.data:
        slug = f"{slug}-{datetime.now().strftime('%H%M%S')}"
    try:
        r = get_db().table("stores").insert({
            "name": name.strip(),
            "slug": slug,
            "location": location.strip(),
            "store_type": store_type,
            "is_active": True
        }).execute()
        return r.data[0] if r.data else None
    except Exception as e:
        logger.error(f"create_store: {e}")
        return None


# ════════════════════════════════════════════════════════════════
# STORE MANAGERS
# ════════════════════════════════════════════════════════════════

def get_managers(store_id: str) -> List[Dict]:
    """Get all active managers for a store."""
    try:
        r = get_db().table("store_managers") \
            .select("*") \
            .eq("store_id", store_id) \
            .eq("is_active", True) \
            .execute()
        return r.data or []
    except Exception as e:
        logger.error(f"get_managers: {e}")
        return []

def get_manager_phones(store_id: str) -> List[str]:
    """Get just the phone numbers for a store's managers."""
    return [m["phone"] for m in get_managers(store_id) if m.get("phone")]

def add_manager(store_id: str, name: str, phone: str, role: str = "manager") -> Optional[Dict]:
    """Add a manager to a store."""
    clean_phone = phone.replace("+", "").replace(" ", "").replace("-", "")
    try:
        r = get_db().table("store_managers").insert({
            "store_id": store_id,
            "name": name.strip(),
            "phone": clean_phone,
            "role": role,
            "is_active": True
        }).execute()
        return r.data[0] if r.data else None
    except Exception as e:
        logger.error(f"add_manager: {e}")
        return None

def remove_manager(manager_id: str) -> bool:
    """Soft-delete a manager (set is_active = false)."""
    try:
        get_db().table("store_managers") \
            .update({"is_active": False}) \
            .eq("id", manager_id) \
            .execute()
        return True
    except Exception as e:
        logger.error(f"remove_manager: {e}")
        return False


# ════════════════════════════════════════════════════════════════
# UPLOADS + DEDUPLICATION
# ════════════════════════════════════════════════════════════════

def file_hash(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()

def is_already_processed(fhash: str) -> bool:
    try:
        r = get_db().table("inventory_uploads").select("id").eq("file_hash", fhash).execute()
        return len(r.data) > 0
    except Exception:
        return False

def create_upload_record(store_id: str, file_name: str, fhash: str) -> Optional[str]:
    """Create upload record. Returns upload_id."""
    try:
        r = get_db().table("inventory_uploads").insert({
            "store_id": store_id,
            "file_name": file_name,
            "file_hash": fhash,
            "uploaded_at": datetime.now().isoformat()
        }).execute()
        return r.data[0]["id"] if r.data else None
    except Exception as e:
        logger.error(f"create_upload_record: {e}")
        return None

def update_upload_summary(upload_id: str, summary: Dict) -> None:
    try:
        get_db().table("inventory_uploads").update({
            "total_items":    summary.get("total", 0),
            "critical_count": summary.get("critical", 0),
            "high_count":     summary.get("high", 0),
            "medium_count":   summary.get("medium", 0),
            "low_count":      summary.get("low", 0),
            "total_value":    summary.get("total_value", 0),
            "waste_value":    summary.get("waste_value", 0),
            "health_score":   summary.get("health_score", 0),
        }).eq("id", upload_id).execute()
    except Exception as e:
        logger.error(f"update_upload_summary: {e}")


# ════════════════════════════════════════════════════════════════
# INVENTORY ITEMS
# ════════════════════════════════════════════════════════════════

def insert_inventory_items(rows: List[Dict]) -> bool:
    """Batch insert inventory rows (100 at a time)."""
    if not rows:
        return True
    try:
        for i in range(0, len(rows), 100):
            get_db().table("inventory_items").insert(rows[i:i+100]).execute()
        return True
    except Exception as e:
        logger.error(f"insert_inventory_items: {e}")
        return False

def get_latest_inventory(store_id: str) -> List[Dict]:
    """
    Get the most recent inventory items for a store,
    sorted by risk_score descending (highest risk first).
    """
    try:
        # Get latest upload for this store
        upload_r = get_db().table("inventory_uploads") \
            .select("id") \
            .eq("store_id", store_id) \
            .order("uploaded_at", desc=True) \
            .limit(1) \
            .execute()

        if not upload_r.data:
            return []

        upload_id = upload_r.data[0]["id"]

        items_r = get_db().table("inventory_items") \
            .select("*") \
            .eq("upload_id", upload_id) \
            .order("risk_score", desc=True) \
            .execute()

        return items_r.data or []
    except Exception as e:
        logger.error(f"get_latest_inventory: {e}")
        return []

def get_critical_items(store_id: str) -> List[Dict]:
    """Items that need WhatsApp alerts (CRITICAL or HIGH)."""
    try:
        upload_r = get_db().table("inventory_uploads") \
            .select("id") \
            .eq("store_id", store_id) \
            .order("uploaded_at", desc=True) \
            .limit(1) \
            .execute()
        if not upload_r.data:
            return []
        upload_id = upload_r.data[0]["id"]

        r = get_db().table("inventory_items") \
            .select("*") \
            .eq("upload_id", upload_id) \
            .in_("severity_level", ["CRITICAL", "HIGH"]) \
            .order("risk_score", desc=True) \
            .execute()
        return r.data or []
    except Exception as e:
        logger.error(f"get_critical_items: {e}")
        return []

def get_order_required_items(store_id: str) -> List[Dict]:
    """Items where order_required = true."""
    try:
        upload_r = get_db().table("inventory_uploads") \
            .select("id") \
            .eq("store_id", store_id) \
            .order("uploaded_at", desc=True) \
            .limit(1) \
            .execute()
        if not upload_r.data:
            return []
        upload_id = upload_r.data[0]["id"]

        r = get_db().table("inventory_items") \
            .select("*") \
            .eq("upload_id", upload_id) \
            .eq("order_required", True) \
            .order("risk_score", desc=True) \
            .execute()
        return r.data or []
    except Exception as e:
        logger.error(f"get_order_required_items: {e}")
        return []


# ════════════════════════════════════════════════════════════════
# PROCUREMENT REQUESTS
# ════════════════════════════════════════════════════════════════

def create_procurement_request(store_id: str, item: Dict, suggested_qty: int) -> Optional[str]:
    """Create a procurement request. Returns request_id."""
    unit_price  = float(item.get("selling_price", 0))
    total_value = unit_price * suggested_qty
    try:
        r = get_db().table("procurement_requests").insert({
            "store_id":       store_id,
            "upload_id":      item.get("upload_id"),
            "item_id":        item.get("id"),
            "product_name":   item.get("product_name", "Unknown"),
            "supplier":       item.get("supplier", "Unknown"),
            "supplier_phone": item.get("supplier_phone", ""),
            "suggested_qty":  suggested_qty,
            "unit_price":     unit_price,
            "total_value":    total_value,
            "urgency":        item.get("severity_level", "HIGH"),
            "status":         "awaiting_manager",
        }).execute()
        return r.data[0]["id"] if r.data else None
    except Exception as e:
        logger.error(f"create_procurement_request: {e}")
        return None

def get_pending_procurement(store_id: str) -> List[Dict]:
    try:
        r = get_db().table("procurement_requests") \
            .select("*") \
            .eq("store_id", store_id) \
            .in_("status", ["awaiting_manager", "pending"]) \
            .order("created_at", desc=True) \
            .execute()
        return r.data or []
    except Exception as e:
        logger.error(f"get_pending_procurement: {e}")
        return []

def get_all_procurement(store_id: str, limit: int = 50) -> List[Dict]:
    try:
        r = get_db().table("procurement_requests") \
            .select("*") \
            .eq("store_id", store_id) \
            .order("created_at", desc=True) \
            .limit(limit) \
            .execute()
        return r.data or []
    except Exception as e:
        logger.error(f"get_all_procurement: {e}")
        return []

def approve_procurement(request_id: str, manager_phone: str) -> bool:
    try:
        get_db().table("procurement_requests").update({
            "status":           "approved",
            "manager_response": "YES",
            "manager_phone":    manager_phone,
            "responded_at":     datetime.now().isoformat()
        }).eq("id", request_id).execute()
        return True
    except Exception as e:
        logger.error(f"approve_procurement: {e}")
        return False

def reject_procurement(request_id: str, manager_phone: str) -> bool:
    try:
        get_db().table("procurement_requests").update({
            "status":           "rejected",
            "manager_response": "NO",
            "manager_phone":    manager_phone,
            "responded_at":     datetime.now().isoformat()
        }).eq("id", request_id).execute()
        return True
    except Exception as e:
        logger.error(f"reject_procurement: {e}")
        return False

def mark_supplier_notified(request_id: str) -> bool:
    try:
        get_db().table("procurement_requests").update({
            "status":                "supplier_notified",
            "supplier_notified_at":  datetime.now().isoformat()
        }).eq("id", request_id).execute()
        return True
    except Exception as e:
        logger.error(f"mark_supplier_notified: {e}")
        return False


# ════════════════════════════════════════════════════════════════
# WHATSAPP LOGS
# ════════════════════════════════════════════════════════════════

def log_whatsapp(store_id: Optional[str], direction: str, phone: str,
                 message: str, msg_type: str = "text",
                 procurement_id: Optional[str] = None,
                 status: str = "sent") -> None:
    try:
        row = {
            "store_id":     store_id,
            "direction":    direction,
            "message_text": message[:2000],
            "message_type": msg_type,
            "status":       status,
            "sent_at":      datetime.now().isoformat()
        }
        if direction == "outbound":
            row["to_phone"] = phone
        else:
            row["from_phone"] = phone
        if procurement_id:
            row["related_procurement_id"] = procurement_id
        get_db().table("whatsapp_logs").insert(row).execute()
    except Exception as e:
        logger.error(f"log_whatsapp: {e}")

def get_whatsapp_logs(store_id: str, limit: int = 50) -> List[Dict]:
    try:
        r = get_db().table("whatsapp_logs") \
            .select("*") \
            .eq("store_id", store_id) \
            .order("sent_at", desc=True) \
            .limit(limit) \
            .execute()
        return r.data or []
    except Exception as e:
        logger.error(f"get_whatsapp_logs: {e}")
        return []


# ════════════════════════════════════════════════════════════════
# AGENT RUNS
# ════════════════════════════════════════════════════════════════

def log_agent_run(run_type: str, stores_checked: int, alerts_sent: int,
                  procurement_created: int, items_processed: int,
                  duration: float, errors: str = "") -> None:
    try:
        get_db().table("agent_runs").insert({
            "run_type":           run_type,
            "stores_checked":     stores_checked,
            "alerts_sent":        alerts_sent,
            "procurement_created":procurement_created,
            "items_processed":    items_processed,
            "duration_seconds":   round(duration, 2),
            "errors":             errors[:1000] if errors else None,
            "ran_at":             datetime.now().isoformat()
        }).execute()
    except Exception as e:
        logger.error(f"log_agent_run: {e}")

def get_last_agent_run() -> Optional[Dict]:
    try:
        r = get_db().table("agent_runs") \
            .select("*") \
            .order("ran_at", desc=True) \
            .limit(1) \
            .execute()
        return r.data[0] if r.data else None
    except Exception:
        return None