# agent_automation.py - Simplified Version
import os
import sys
from datetime import datetime, date, timedelta
import pandas as pd
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

# Configuration
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

print(f"[{datetime.now()}] Starting Dishii AI Agent...")
print(f"SUPABASE_URL: {SUPABASE_URL[:30]}...")

# Initialize Supabase
try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("✅ Connected to Supabase")
except Exception as e:
    print(f"❌ Failed to connect: {e}")
    sys.exit(1)

# Configuration
RED_THRESHOLD = 60
AMBER_THRESHOLD = 120

def update_inventory_expiry():
    """Update expiry dates for all products"""
    print("\n📅 Updating inventory expiry dates...")
    
    try:
        # Get all inventory items
        items = supabase.table("inventory_items").select("*").execute()
        print(f"Found {len(items.data)} items")
        
        updated_count = 0
        for item in items.data:
            expiry_date = item.get("expiry_date")
            if expiry_date:
                try:
                    expiry = pd.to_datetime(expiry_date).date()
                    days_left = (expiry - date.today()).days
                    
                    # Determine status
                    if days_left < 0:
                        traffic_light = "🔴"
                        status = "Expired"
                    elif days_left <= RED_THRESHOLD:
                        traffic_light = "🔴"
                        status = "Critical"
                    elif days_left <= AMBER_THRESHOLD:
                        traffic_light = "🟠"
                        status = "Monitor"
                    else:
                        traffic_light = "🟢"
                        status = "Healthy"
                    
                    # Update
                    supabase.table("inventory_items").update({
                        "days_to_expiry": days_left,
                        "traffic_light": traffic_light,
                        "traffic_status": status,
                        "updated_at": datetime.now().isoformat()
                    }).eq("id", item["id"]).execute()
                    updated_count += 1
                except Exception as e:
                    print(f"Error processing {item.get('product_name')}: {e}")
        
        print(f"✅ Updated {updated_count} items")
        return updated_count
    except Exception as e:
        print(f"❌ Error updating inventory: {e}")
        return 0

def detect_critical_items():
    """Find items needing attention"""
    print("\n⚠️ Checking for critical items...")
    
    try:
        critical = supabase.table("inventory_items").select("*").eq("traffic_light", "🔴").execute()
        print(f"Found {len(critical.data)} critical items")
        
        if critical.data:
            print("\nCritical items:")
            for item in critical.data[:5]:
                print(f"  - {item['product_name']}: {item.get('days_to_expiry', 0)} days left")
        
        return critical.data
    except Exception as e:
        print(f"❌ Error detecting critical items: {e}")
        return []

def send_email_alert(critical_items):
    """Send simple email alert"""
    if not critical_items:
        return
    
    print("\n📧 Would send email alert (email not configured yet)")
    # Email sending code here (optional)
    print(f"Would alert about {len(critical_items)} items")

# Main execution
def main():
    print("=" * 50)
    print(f"🤖 DISHII AI AGENT")
    print(f"Time: {datetime.now()}")
    print("=" * 50)
    
    # Update expiry dates
    updated = update_inventory_expiry()
    
    # Detect critical items
    critical = detect_critical_items()
    
    # Send alerts (optional)
    if critical:
        send_email_alert(critical)
    
    print("\n" + "=" * 50)
    print("✅ DISHII AI AGENT COMPLETE")
    print("=" * 50)

if __name__ == "__main__":
    main()