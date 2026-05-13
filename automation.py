# automation.py - Daily automation script (NO PAID SERVICES)
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from supabase import create_client
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Free Gmail SMTP settings (use your Gmail)
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS", "yourbusiness@gmail.com")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "your_app_password")  # Gmail app password
REPORT_EMAIL = os.getenv("REPORT_EMAIL", "manager@yourbusiness.com")

def days_to_expiry(expiry_date):
    if not expiry_date:
        return None
    try:
        today = datetime.now().date()
        if isinstance(expiry_date, str):
            expiry_date = pd.to_datetime(expiry_date).date()
        return (expiry_date - today).days
    except:
        return None

def send_email_report(subject, body, to_email=REPORT_EMAIL):
    """Send free email via Gmail SMTP"""
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = to_email
        msg['Subject'] = subject
        
        msg.attach(MIMEText(body, 'html'))
        
        # Connect to Gmail SMTP (free)
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        
        print(f"Email sent to {to_email}")
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False

def generate_daily_report(critical_items, monitor_items, orders_needed):
    """Generate HTML report for email"""
    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; }}
            .critical {{ color: #dc2626; }}
            .monitor {{ color: #f59e0b; }}
            .healthy {{ color: #10b981; }}
            table {{ border-collapse: collapse; width: 100%; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background-color: #f2f2f2; }}
        </style>
    </head>
    <body>
        <h2>Dishii Daily Inventory Report</h2>
        <p><strong>Date:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
        
        <h3>Summary</h3>
        <ul>
            <li class="critical">Critical Items: {len(critical_items)}</li>
            <li class="monitor">Monitor Items: {len(monitor_items)}</li>
            <li>Orders Needed: {len(orders_needed)}</li>
        </ul>
        
        <h3>Critical Items (Action Required)</h3>
        <table>
            <tr><th>Product</th><th>Expiry</th><th>Stock</th></tr>
            {''.join([f"<tr><td>{i.get('product_name')}</td><td>{i.get('expiry_date')}</td><td>{i.get('current_stock')}</td></tr>" for i in critical_items[:10]])}
        </table>
        
        <h3>Orders to Place</h3>
        <table>
            <tr><th>Product</th><th>Supplier</th><th>Suggested Qty</th></tr>
            {''.join([f"<tr><td>{o.get('product_name')}</td><td>{o.get('supplier')}</td><td>{o.get('suggested_order', 100)}</td></tr>" for o in orders_needed[:10]])}
        </table>
        
        <p><small>Dishii AI - Food Operations Intelligence</small></p>
    </body>
    </html>
    """
    return html

def update_traffic_lights_daily():
    """Run daily to update traffic lights based on current date"""
    items = supabase.table("inventory_items").select("*").execute()
    updated_count = 0
    
    for item in items.data:
        days_left = days_to_expiry(item.get("expiry_date"))
        
        if days_left is None:
            status = "Unknown"
        elif days_left < 0:
            status = "Expired"
        elif days_left <= 14:
            status = "Critical"
        elif days_left <= 30:
            status = "Monitor"
        else:
            status = "Healthy"
        
        supabase.table("inventory_items").update({
            "days_to_expiry": days_left,
            "traffic_light": status,
            "updated_at": datetime.now().isoformat()
        }).eq("id", item["id"]).execute()
        updated_count += 1
    
    return updated_count

def check_auto_order():
    """Check for critical stock that needs reordering"""
    items = supabase.table("inventory_items").select("*").execute()
    
    orders_needed = []
    for item in items.data:
        stock = item.get("current_stock", 0)
        sales = item.get("daily_sales_rate", 1)
        if sales <= 0:
            sales = 1
        
        days_left = stock / sales
        if days_left <= 14 and stock > 0:
            orders_needed.append({
                "product_name": item.get("product_name"),
                "supplier": item.get("supplier", "Unknown"),
                "current_stock": stock,
                "suggested_order": int(sales * 14),
                "id": item.get("id")
            })
    
    return orders_needed

def run_daily_automation():
    """Main automation function - runs daily"""
    print(f"🤖 Dishii Automation running at {datetime.now()}")
    
    # 1. Update traffic lights
    updated = update_traffic_lights_daily()
    print(f"✅ Updated {updated} inventory items")
    
    # 2. Get critical and monitor items
    critical_items = supabase.table("inventory_items").select("*").eq("traffic_light", "Critical").execute()
    monitor_items = supabase.table("inventory_items").select("*").eq("traffic_light", "Monitor").execute()
    
    # 3. Check orders needed
    orders_needed = check_auto_order()
    print(f"📦 {len(orders_needed)} items need reordering")
    
    # 4. Save orders to database
    for order in orders_needed:
        supabase.table("procurement_recommendations").insert({
            "product_name": order["product_name"],
            "supplier": order["supplier"],
            "current_stock": order["current_stock"],
            "recommended_order_quantity": order["suggested_order"],
            "status": "pending",
            "created_at": datetime.now().isoformat()
        }).execute()
    
    # 5. Send email report (free via Gmail)
    if critical_items.data or orders_needed:
        html_report = generate_daily_report(
            critical_items.data, 
            monitor_items.data, 
            orders_needed
        )
        send_email_report(
            f"Dishii Report - {datetime.now().strftime('%Y-%m-%d')}",
            html_report
        )
        print("📧 Email report sent")
    
    print("✅ Automation complete!")
    
    return {
        "updated": updated,
        "critical": len(critical_items.data),
        "monitor": len(monitor_items.data),
        "orders": len(orders_needed)
    }

if __name__ == "__main__":
    run_daily_automation()