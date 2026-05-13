import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, date
from google import genai
from supabase import create_client
import os
from dotenv import load_dotenv
import io
import base64

load_dotenv()

# Configuration
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Initialize clients
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
client = genai.Client(api_key=GEMINI_API_KEY)

# Page setup
st.set_page_config(
    page_title="Dishii — Food Operations Intelligence",
    page_icon="📊",
    layout="wide"
)

# Simple clean header
logo_path = "assets/dishii-logo.png"
if os.path.exists(logo_path):
    col1, col2 = st.columns([1, 8])
    with col1:
        st.image(logo_path, width=45)
    with col2:
        st.markdown("## Dishii")
        st.caption("Food Operations Intelligence")
else:
    st.title("Dishii")
    st.caption("Food Operations Intelligence")

st.divider()
st.markdown("**Upload any inventory file. AI analyzes it instantly.**")

# Sidebar
with st.sidebar:
    st.header("Settings")
    business_name = st.text_input("Business Name", placeholder="e.g. 99 Mart Westlands")
    red_threshold = st.number_input("Red Alert (days to expiry)", value=60, min_value=1)
    amber_threshold = st.number_input("Amber Alert (days to expiry)", value=120, min_value=1)
    stock_warning_days = st.number_input("Stock Warning (days remaining)", value=14, min_value=1)
    st.divider()
    st.markdown("### Upload Inventory File")
    uploaded_file = st.file_uploader(
        "Excel or CSV accepted",
        type=["xlsx", "csv", "xls"],
        help="Any format. System auto-detects columns."
    )

# Helper functions
def days_to_expiry(expiry_date):
    if pd.isna(expiry_date):
        return None
    try:
        if isinstance(expiry_date, str):
            expiry_date = pd.to_datetime(expiry_date)
        today = datetime.now().date()
        if hasattr(expiry_date, 'date'):
            expiry = expiry_date.date()
        else:
            expiry = expiry_date
        return (expiry - today).days
    except Exception as e:
        return None

def get_traffic_light(days):
    if days is None:
        return "⚪", "No expiry date", "Verify date manually", "unknown"
    if days < 0:
        return "🔴", "Expired", "Remove from shelf immediately", "critical"
    if days <= red_threshold:
        return "🔴", f"Urgent - {days} days left", "Discount 20-30%, push to front", "critical"
    if days <= amber_threshold:
        return "🟠", f"Monitor - {days} days left", "Feature in promotions, suggest at checkout", "high"
    return "🟢", f"Safe - {days} days left", "Normal stock rotation", "low"

def get_stock_status(stock, daily_sales):
    try:
        stock = float(stock) if not pd.isna(stock) else 0
        daily_sales = float(daily_sales) if not pd.isna(daily_sales) else 0
    except:
        return "Cannot calculate", False, "unknown"

    if stock <= 0:
        return "OUT OF STOCK - Order immediately", True, "critical"
    if daily_sales <= 0:
        return "No sales data - review manually", False, "unknown"

    days_left = stock / daily_sales
    if days_left <= stock_warning_days:
        return f"ORDER NOW - Only {int(days_left)} days stock left", True, "high"
    if days_left > 90:
        return f"PAUSE ORDERS - {int(days_left)} days overstocked", False, "low"
    return f"NORMAL - {int(days_left)} days stock remaining", False, "medium"

def normalize_columns(df):
    df.columns = df.columns.str.lower().str.strip().str.replace(" ", "_")
    mappings = {
        "product_name": ["product_name", "product", "item", "name", "item_name", "description", "sku_name"],
        "expiry_date": ["expiry_date", "expiry", "best_before", "expiration_date", "exp_date", "use_by"],
        "current_stock": ["current_stock", "stock", "quantity", "qty", "inventory", "units", "on_hand"],
        "daily_sales_rate": ["daily_sales_rate", "daily_sales", "sales_rate", "avg_daily_sales", "velocity", "avg_sales"],
        "supplier": ["supplier", "vendor", "supplier_name", "vendor_name", "source"],
        "cost": ["cost", "unit_cost", "price", "purchase_price", "buying_price"],
        "unit": ["unit", "uom", "unit_of_measure", "measurement"]
    }
    for target, options in mappings.items():
        if target not in df.columns:
            for col in options:
                if col in df.columns:
                    df[target] = df[col]
                    break
    if "product_name" not in df.columns:
        df["product_name"] = [f"Item {i+1}" for i in range(len(df))]
    for col in ["expiry_date", "current_stock", "daily_sales_rate", "supplier", "cost", "unit"]:
        if col not in df.columns:
            df[col] = None
    return df

def get_ai_analysis(summary_data):
    prompt = f"""
You are a food operations intelligence system analyzing inventory data for an African food business.

Here is the current inventory summary:
- Total products: {summary_data['total']}
- Urgent expiry alerts (red): {summary_data['red']}
- Monitor items (amber): {summary_data['amber']}
- Safe items (green): {summary_data['green']}
- Items requiring immediate orders: {summary_data['orders']}
- Critical items (expired or out of stock): {summary_data['critical']}

Top urgent items: {summary_data['urgent_items'][:5]}

Provide a concise operations briefing in 4 sections:
1. IMMEDIATE ACTIONS (what to do today)
2. FINANCIAL RISK (estimated loss if nothing is done)
3. PROCUREMENT RECOMMENDATIONS (what to order and from whom)
4. WEEKLY OUTLOOK (what to watch this week)

Be specific, practical, and direct. Write for a food business owner in Kenya.
Keep total response under 300 words.
"""
    try:
        response = client.models.generate_content(
            model="models/gemini-2.0-flash",
            contents=prompt
        )
        return response.text
    except Exception as e:
        return f"AI analysis unavailable: {str(e)}"

def save_to_supabase(df, business, filename, summary):
    try:
        upload_data = {
            "business_name": business or "Unknown",
            "file_name": filename,
            "total_items": summary["total"],
            "red_count": summary["red"],
            "amber_count": summary["amber"],
            "green_count": summary["green"],
            "orders_required": summary["orders"]
        }
        result = supabase.table("inventory_uploads").insert(upload_data).execute()
        upload_id = result.data[0]["id"]

        items_to_insert = []
        for _, row in df.iterrows():
            items_to_insert.append({
                "upload_id": upload_id,
                "product_name": str(row.get("product_name", "Unknown")),
                "expiry_date": str(row.get("expiry_date", "")) if not pd.isna(row.get("expiry_date", "")) else None,
                "days_to_expiry": int(row["days_to_expiry"]) if row.get("days_to_expiry") is not None else None,
                "current_stock": float(row["current_stock"]) if not pd.isna(row.get("current_stock", float("nan"))) else None,
                "daily_sales_rate": float(row["daily_sales_rate"]) if not pd.isna(row.get("daily_sales_rate", float("nan"))) else None,
                "supplier": str(row.get("supplier", "")) if not pd.isna(row.get("supplier", "")) else None,
                "cost": float(row["cost"]) if not pd.isna(row.get("cost", float("nan"))) else None,
                "traffic_light": row.get("traffic_light", ""),
                "traffic_status": row.get("traffic_status", ""),
                "stock_action": row.get("stock_action", ""),
                "order_required": bool(row.get("order_required", False)),
                "priority": row.get("priority", "low")
            })

        if items_to_insert:
            supabase.table("inventory_items").insert(items_to_insert).execute()
        return True
    except Exception as e:
        st.warning(f"Could not save to database: {str(e)}")
        return False

# Main app logic
if uploaded_file:
    with st.spinner("Reading and analyzing your file..."):
        try:
            if uploaded_file.name.endswith(".csv"):
                df = pd.read_csv(uploaded_file)
            else:
                df = pd.read_excel(uploaded_file)

            df = normalize_columns(df)
            df["expiry_date"] = pd.to_datetime(df["expiry_date"], errors="coerce")
            df["days_to_expiry"] = df["expiry_date"].apply(days_to_expiry)

            traffic_results = df["days_to_expiry"].apply(lambda d: get_traffic_light(d))
            df["traffic_light"] = [r[0] for r in traffic_results]
            df["traffic_status"] = [r[1] for r in traffic_results]
            df["expiry_action"] = [r[2] for r in traffic_results]
            df["priority"] = [r[3] for r in traffic_results]

            stock_results = df.apply(
                lambda row: get_stock_status(
                    row.get("current_stock"),
                    row.get("daily_sales_rate")
                ), axis=1
            )
            df["stock_action"] = [r[0] for r in stock_results]
            df["order_required"] = [r[1] for r in stock_results]
            df["stock_priority"] = [r[2] for r in stock_results]

            summary = {
                "total": len(df),
                "red": len(df[df["traffic_light"] == "🔴"]),
                "amber": len(df[df["traffic_light"] == "🟠"]),
                "green": len(df[df["traffic_light"] == "🟢"]),
                "orders": len(df[df["order_required"] == True]),
                "critical": len(df[df["priority"] == "critical"]),
                "urgent_items": df[df["priority"] == "critical"]["product_name"].tolist()
            }

            save_to_supabase(df, business_name, uploaded_file.name, summary)

        except Exception as e:
            st.error(f"Error reading file: {e}")
            st.stop()

    st.success(f"Analyzed {len(df)} products from {uploaded_file.name}")

    # KPI Row
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Total Products", summary["total"])
    with col2:
        st.metric("Red (Urgent)", summary["red"])
    with col3:
        st.metric("Amber (Monitor)", summary["amber"])
    with col4:
        st.metric("Green (Safe)", summary["green"])
    with col5:
        st.metric("Orders Needed", summary["orders"])

    st.divider()

    # AI Analysis
    with st.spinner("Generating AI operations briefing..."):
        ai_analysis = get_ai_analysis(summary)

    st.subheader("AI Operations Briefing")
    st.markdown(ai_analysis)

    st.divider()

    # ============================================
    # CHART 1: EXPIRY RISK (Traffic Light System)
    # ============================================
    st.subheader("Chart 1: Expiry Risk Distribution")
    st.caption("Based on product expiry dates - Shows how close products are to expiring")
    
    # Create expiry distribution data
    expiry_data = []
    if summary['red'] > 0:
        expiry_data.append({'Status': '🔴 Red (Urgent - expiring soon)', 'Count': summary['red'], 'Color': '#dc2626', 'Description': 'Expiring within 60 days'})
    if summary['amber'] > 0:
        expiry_data.append({'Status': '🟠 Amber (Monitor - medium risk)', 'Count': summary['amber'], 'Color': '#f59e0b', 'Description': 'Expiring within 60-120 days'})
    if summary['green'] > 0:
        expiry_data.append({'Status': '🟢 Green (Safe - low risk)', 'Count': summary['green'], 'Color': '#10b981', 'Description': 'Expiring beyond 120 days'})
    
    if expiry_data:
        expiry_df = pd.DataFrame(expiry_data)
        fig1 = px.pie(
            expiry_df,
            names='Status',
            values='Count',
            color='Status',
            color_discrete_map={
                '🔴 Red (Urgent - expiring soon)': '#dc2626',
                '🟠 Amber (Monitor - medium risk)': '#f59e0b',
                '🟢 Green (Safe - low risk)': '#10b981'
            },
            hole=0.3
        )
        fig1.update_layout(height=450, showlegend=True, title="Expiry Risk by Product Count")
        fig1.update_traces(textposition='inside', textinfo='percent+label')
        st.plotly_chart(fig1, use_container_width=True)
        
        # Add explanation
        st.caption("💡 **What this means:** Products marked Red need immediate attention. Amber should be monitored weekly. Green are safe.")
    else:
        st.info("No expiry data available")

    st.divider()

    # ============================================
    # CHART 2: STOCK ACTION (Procurement Needs)
    # ============================================
    st.subheader("Chart 2: Stock Action Required")
    st.caption("Based on current inventory levels and sales velocity - Shows what needs reordering")
    
    order_count = summary['orders']
    stock_ok_count = summary['total'] - order_count
    
    stock_data = []
    if order_count > 0:
        stock_data.append({'Action': '🛒 Order Required - Low Stock', 'Count': order_count, 'Color': '#dc2626', 'Description': 'Products that need reordering now'})
    if stock_ok_count > 0:
        stock_data.append({'Action': '✅ Stock OK - Adequate Inventory', 'Count': stock_ok_count, 'Color': '#10b981', 'Description': 'Products with healthy stock levels'})
    
    if stock_data:
        stock_df = pd.DataFrame(stock_data)
        fig2 = px.bar(
            stock_df,
            x='Action',
            y='Count',
            color='Action',
            color_discrete_map={
                '🛒 Order Required - Low Stock': '#dc2626',
                '✅ Stock OK - Adequate Inventory': '#10b981'
            },
            text='Count',
            title="Procurement Priority by Product Count"
        )
        fig2.update_layout(height=450, showlegend=False)
        fig2.update_traces(textposition="outside")
        st.plotly_chart(fig2, use_container_width=True)
        
        # Add explanation
        st.caption("💡 **What this means:** Order Required products should be purchased from suppliers immediately.")
    else:
        st.info("No stock data available")

    st.divider()

    # Urgent items table
    urgent_df = df[
        (df["traffic_light"] == "🔴") |
        (df["order_required"] == True) |
        (df["priority"] == "critical")
    ].copy()

    if len(urgent_df) > 0:
        st.subheader(f"Urgent Actions — {len(urgent_df)} items need attention")
        display_cols = ["product_name", "traffic_light", "traffic_status", "stock_action", "supplier"]
        display_cols = [c for c in display_cols if c in urgent_df.columns]
        st.dataframe(urgent_df[display_cols], use_container_width=True, height=300)

    st.divider()

    # Order recommendations
    orders_df = df[df["order_required"] == True].copy()
    if len(orders_df) > 0:
        st.subheader(f"Procurement Recommendations — {len(orders_df)} items to order")
        for _, row in orders_df.head(10).iterrows():
            supplier = row.get("supplier", "Unknown supplier")
            if pd.isna(supplier) or supplier == "":
                supplier = "Unknown supplier"
            st.markdown(
                f"**{row['product_name']}** — {row['stock_action']} — Supplier: `{supplier}`"
            )

    st.divider()

    # Full table
    with st.expander("View Complete Inventory Table"):
        st.dataframe(df, use_container_width=True, height=400)

    # Download report
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        if len(urgent_df) > 0:
            urgent_df.to_excel(writer, sheet_name="Urgent Actions", index=False)
        if len(orders_df) > 0:
            orders_df.to_excel(writer, sheet_name="Orders Required", index=False)
        df.to_excel(writer, sheet_name="Full Inventory", index=False)

    st.download_button(
        label="Download Full Report (Excel)",
        data=output.getvalue(),
        file_name=f"dishii_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

else:
    st.info("Upload an Excel or CSV file from the sidebar to begin.")

    st.subheader("What This System Does")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("""
        **Expiry Intelligence**
        - Red: urgent action needed
        - Amber: monitor closely
        - Green: safe
        """)
    with col2:
        st.markdown("""
        **Stock Intelligence**
        - Detects stockouts
        - Identifies overstocking
        - Triggers reorder alerts
        """)
    with col3:
        st.markdown("""
        **AI Briefing**
        - Immediate actions
        - Financial risk estimate
        - Procurement recommendations
        """)

    st.subheader("Accepted Excel Format")
    sample = pd.DataFrame({
        "product_name": ["Tomatoes", "Milk 500ml", "Chicken Breast", "Rice 2kg"],
        "expiry_date": ["2026-06-01", "2026-05-20", "2026-05-16", "2026-12-31"],
        "current_stock": [50, 200, 30, 500],
        "daily_sales_rate": [5, 20, 8, 10],
        "supplier": ["Fresh Farms", "Daima", "Kenchic", "Afia Rice"],
        "cost": [120, 65, 350, 180]
    })
    st.dataframe(sample, use_container_width=True)
    st.caption("Column names are flexible. System auto-detects variations.")

st.divider()
st.caption("Dishii — Food Operations Intelligence | Built for African food businesses | AI-powered by Google Gemini")