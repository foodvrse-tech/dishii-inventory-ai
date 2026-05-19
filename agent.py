"""
agent.py — Dishii Autonomous Agent
Runs every 30 minutes via GitHub Actions.
For each store:
  1. Fetch latest inventory from DB
  2. Reclassify all items (traffic lights recalculated)
  3. Send WhatsApp alerts for CRITICAL/HIGH items
  4. Create procurement requests for stockout items
  5. Send hourly briefing (on the hour only)
  6. Log the run
"""
import os
import sys
import time
import logging
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

import db
import whatsapp as wa
from ai import generate_briefing, classify_item


def should_send_briefing() -> bool:
    """Send briefing once per hour: only when minutes < 35 (cron runs at :00 and :30)."""
    return datetime.now().minute < 35


def process_store(store: dict) -> dict:
    """
    Run full analysis for one store.
    Returns stats dict.
    """
    store_id   = store["id"]
    store_name = store["name"]
    stats      = {"alerts": 0, "procurement": 0, "errors": 0}

    logger.info(f"Processing store: {store_name} ({store_id})")

    # Get managers — if none, skip
    phones = db.get_manager_phones(store_id)
    if not phones:
        logger.warning(f"{store_name}: no active managers, skipping")
        return stats

    # Get latest inventory
    items = db.get_latest_inventory(store_id)
    if not items:
        logger.info(f"{store_name}: no inventory loaded yet")
        return stats

    logger.info(f"{store_name}: {len(items)} items found")

    # Reclassify items (days_to_expiry changes every day)
    critical_items = []
    order_items    = []

    for item in items:
        # Recalculate days_to_expiry from today
        from ai import days_until
        import pandas as pd
        dte = days_until(pd.to_datetime(item.get("expiry_date"), errors="coerce"))
        item["days_to_expiry"] = dte

        classification = classify_item(item)

        # Update in DB
        try:
            db.get_db().table("inventory_items").update({
                "days_to_expiry":  dte,
                "stock_days":      classification["stock_days"],
                "waste_units":     classification["waste_units"],
                "waste_value":     classification["waste_value"],
                "inventory_value": classification["inventory_value"],
                "traffic_light":   classification["traffic_light"],
                "severity_level":  classification["severity_level"],
                "risk_type":       classification["risk_type"],
                "risk_score":      classification["risk_score"],
                "risk_reason":     classification["risk_reason"],
                "risk_color":      classification["risk_color"],
                "order_required":  classification["order_required"],
                "stock_action":    classification["stock_action"],
                "is_expired":      classification["is_expired"],
                "show_in_priority":classification["show_in_priority"],
                "updated_at":      datetime.now().isoformat()
            }).eq("id", item["id"]).execute()
        except Exception as e:
            logger.error(f"DB update failed for {item.get('product_name')}: {e}")
            stats["errors"] += 1

        if classification["severity_level"] in ("CRITICAL", "HIGH"):
            item.update(classification)
            critical_items.append(item)

        if classification["order_required"]:
            item.update(classification)
            order_items.append(item)

    logger.info(f"{store_name}: {len(critical_items)} critical, {len(order_items)} need orders")

    # Send stock alerts (max 5 per run to avoid spam)
    for item in critical_items[:5]:
        msg = wa.msg_stock_alert(
            store_name   = store_name,
            product      = item["product_name"],
            risk         = item["severity_level"],
            stock        = int(item.get("current_stock", 0)),
            stock_days   = int(item.get("stock_days", 0)),
            reason       = item.get("risk_reason", "")
        )
        sent = wa.send_to_all(phones, msg)
        if sent > 0:
            stats["alerts"] += sent
            db.log_whatsapp(
                store_id   = store_id,
                direction  = "outbound",
                phone      = ",".join(phones),
                message    = msg,
                msg_type   = "alert"
            )

    # Create procurement requests for order items (max 5 per run)
    existing_pending = {
        r["product_name"] for r in db.get_pending_procurement(store_id)
    }
    for item in order_items[:5]:
        if item["product_name"] in existing_pending:
            continue  # already has a pending request

        daily_rate    = float(item.get("daily_sales_rate", 1) or 1)
        suggested_qty = max(1, int(daily_rate * 14))  # 2-week supply

        req_id = db.create_procurement_request(store_id, item, suggested_qty)
        if req_id:
            stats["procurement"] += 1
            msg = wa.msg_procurement_request(
                store_name = store_name,
                product    = item["product_name"],
                qty        = suggested_qty,
                supplier   = item.get("supplier", "Unknown"),
                value      = suggested_qty * float(item.get("selling_price", 0)),
                request_id = req_id,
                urgency    = item["severity_level"]
            )
            sent = wa.send_to_all(phones, msg)
            if sent > 0:
                db.log_whatsapp(
                    store_id        = store_id,
                    direction       = "outbound",
                    phone           = ",".join(phones),
                    message         = msg,
                    msg_type        = "procurement",
                    procurement_id  = req_id
                )

    # Hourly briefing (only at top of hour)
    if should_send_briefing():
        logger.info(f"{store_name}: sending hourly briefing")
        summary = {
            "total":       len(items),
            "critical":    len([i for i in items if i.get("severity_level") == "CRITICAL"]),
            "high":        len([i for i in items if i.get("severity_level") == "HIGH"]),
            "medium":      len([i for i in items if i.get("severity_level") == "MEDIUM"]),
            "low":         len([i for i in items if i.get("severity_level") == "LOW"]),
            "total_value": sum(float(i.get("inventory_value", 0)) for i in items),
            "waste_value": sum(float(i.get("waste_value", 0)) for i in items),
            "health_score":100
        }
        # Recalculate health
        if summary["total_value"] > 0:
            summary["health_score"] = max(0, min(100, int(
                100 - (summary["waste_value"] / summary["total_value"]) * 100
            )))

        briefing = generate_briefing(store_name, summary, critical_items)
        briefing_msg = wa.msg_hourly_briefing(store_name, briefing, summary)
        sent = wa.send_to_all(phones, briefing_msg)
        if sent > 0:
            stats["alerts"] += sent
            db.log_whatsapp(
                store_id  = store_id,
                direction = "outbound",
                phone     = ",".join(phones),
                message   = briefing_msg,
                msg_type  = "briefing"
            )

    logger.info(f"{store_name}: done — alerts={stats['alerts']}, procurement={stats['procurement']}")
    return stats


def run():
    start = time.time()
    logger.info("═══ Dishii Agent starting ═══")

    # Check WhatsApp
    status = wa.get_connection_status()
    logger.info(f"WhatsApp status: {status}")

    if status != "open":
        logger.warning("WhatsApp not connected — alerts will not be delivered")

    # Get all active stores
    stores = db.get_all_stores()
    logger.info(f"Found {len(stores)} active stores")

    if not stores:
        logger.info("No stores found — nothing to do")
        db.log_agent_run("scheduled", 0, 0, 0, 0, time.time() - start)
        return

    total_alerts      = 0
    total_procurement = 0
    total_items       = 0
    errors            = []

    for store in stores:
        try:
            stats = process_store(store)
            total_alerts      += stats["alerts"]
            total_procurement += stats["procurement"]
            if stats["errors"] > 0:
                errors.append(f"{store['name']}: {stats['errors']} errors")
        except Exception as e:
            err_msg = f"{store['name']}: {str(e)}"
            logger.error(f"Store failed: {err_msg}")
            errors.append(err_msg)

    duration = time.time() - start
    error_str = "; ".join(errors) if errors else ""

    db.log_agent_run(
        run_type           = "scheduled",
        stores_checked     = len(stores),
        alerts_sent        = total_alerts,
        procurement_created= total_procurement,
        items_processed    = total_items,
        duration           = duration,
        errors             = error_str
    )

    logger.info(
        f"═══ Done in {duration:.1f}s — "
        f"stores={len(stores)}, alerts={total_alerts}, "
        f"procurement={total_procurement}, errors={len(errors)} ═══"
    )


if __name__ == "__main__":
    run()