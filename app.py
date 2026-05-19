"""
Dishii v8.0 — Production Dashboard
Multi-store, database-driven, real WhatsApp, real AI, traffic light system.
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import io, os, re, hashlib, logging
from datetime import datetime
from dotenv import load_dotenv
import warnings
warnings.filterwarnings("ignore")

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import db
import whatsapp as wa
from ai import (process_upload, df_to_db_rows, generate_briefing,
                build_summary, normalize_dataframe)

# ─── PAGE CONFIG ──────────────────────────────────────────────
st.set_page_config(
    page_title="Dishii | Autonomous Food Operations",
    page_icon="🍔",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─── CSS ──────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
* { font-family: 'Inter', sans-serif; }
.main .block-container { padding-top:0.5rem !important; max-width:1600px; }
[data-testid="stSidebar"] { background:#080f1a; border-right:1px solid #1e2d3d; }
footer { visibility:hidden; }

.hero { background:linear-gradient(135deg,#080f1a 0%,#0d1f35 50%,#0a1628 100%);
  padding:1.5rem 2rem; border-radius:16px; margin-bottom:1.25rem; border:1px solid #1e3a5f; }
.hero-badge { display:inline-block; background:#10b98115; border:1px solid #10b98150;
  color:#10b981; font-size:0.65rem; font-weight:600; letter-spacing:1.5px;
  text-transform:uppercase; padding:3px 10px; border-radius:20px; margin-bottom:0.5rem; }
.hero-title { font-size:1.8rem; font-weight:700; color:#f1f5f9; margin:0 0 0.2rem 0; }
.hero-title span { background:linear-gradient(135deg,#10b981,#34d399);
  -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
.hero-sub { font-size:0.85rem; color:#64748b; }

.kgrid { display:grid; grid-template-columns:repeat(4,1fr); gap:0.875rem; margin:0.75rem 0 1.25rem; }
.kpi { background:#0d1f35; border:1px solid #1e3a5f; border-radius:14px; padding:1.1rem 1.3rem; }
.kpi-label { font-size:0.68rem; font-weight:600; color:#64748b; text-transform:uppercase; letter-spacing:1px; }
.kpi-value { font-size:1.8rem; font-weight:700; margin:0.2rem 0; }
.kpi-sub { font-size:0.68rem; color:#475569; }
.kpi.red   { border-color:#dc262640; } .kpi.red   .kpi-value { color:#f87171; }
.kpi.amber { border-color:#f59e0b40; } .kpi.amber .kpi-value { color:#fbbf24; }
.kpi.green { border-color:#10b98140; } .kpi.green .kpi-value { color:#34d399; }
.kpi.blue  { border-color:#3b82f640; } .kpi.blue  .kpi-value { color:#60a5fa; }

.item-card { background:#0d1f35; border:1px solid #1e3a5f; border-radius:12px;
  padding:0.875rem 1rem; margin-bottom:0.625rem; border-left:4px solid; }
.item-card:hover { background:#122640; }
.item-title { font-size:0.9rem; font-weight:600; color:#e2e8f0; }
.item-reason { font-size:0.7rem; color:#94a3b8; margin-top:0.25rem; }
.item-meta { font-size:0.65rem; color:#475569; margin-top:0.35rem; }

.stTabs [data-baseweb="tab-list"] { background:#0d1f35; border-radius:10px; padding:4px; gap:3px; }
.stTabs [data-baseweb="tab"] { border-radius:7px; font-weight:500; color:#64748b; padding:7px 16px; }
.stTabs [aria-selected="true"] { background:#10b981 !important; color:white !important; }
.stProgress > div > div { background:#10b981; }
div[data-testid="stMetricValue"] { font-size:1.5rem; font-weight:700; color:#f1f5f9; }
</style>
""", unsafe_allow_html=True)

# ─── SYSTEM STATUS (cached, refreshes every 30s) ──────────────
@st.cache_data(ttl=30)
def get_system_status():
    return {
        "wa":  wa.get_connection_status(),
        "db":  True  # if we got here, DB works
    }

status = get_system_status()
WA_LIVE = status["wa"] == "open"

# ─── SIDEBAR ──────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="padding:0.75rem 0 0.5rem; text-align:center;">
        <div style="font-size:1.4rem; font-weight:700; color:#10b981;">🍔 Dishii</div>
        <div style="font-size:0.6rem; color:#475569; letter-spacing:1.5px; text-transform:uppercase;">
            Autonomous Food Operations
        </div>
    </div>""", unsafe_allow_html=True)

    # Status indicators
    wa_color = "#10b981" if WA_LIVE else "#f59e0b"
    wa_label = "WhatsApp: Live" if WA_LIVE else "WhatsApp: Demo mode"
    st.markdown(
        f"<div style='font-size:0.7rem; color:#64748b; line-height:2.2;'>"
        f"<span style='color:{wa_color};'>● </span>{wa_label}<br>"
        f"<span style='color:#10b981;'>● </span>Database: Connected"
        f"</div>", unsafe_allow_html=True
    )

    st.markdown("---")

    # Store selector
    stores = db.get_all_stores()
    store_map = {s["id"]: s["name"] for s in stores}

    st.markdown("### 🏪 Active Store")
    if store_map:
        selected_id = st.selectbox(
            "Store", list(store_map.keys()),
            format_func=lambda x: store_map[x],
            label_visibility="collapsed"
        )
    else:
        selected_id = None
        st.info("No stores yet — create one in the Stores tab")

    st.markdown("---")
    st.markdown("### ⚙️ Thresholds")
    red_t   = st.slider("🔴 Critical expiry (days)", 1, 30,  7)
    amber_t = st.slider("🟠 High expiry (days)",     1, 60, 14)
    stock_w = st.slider("📦 Stock warning (days)",   1, 30, 14)
    show_n  = st.slider("Priority items shown",      5, 50, 15)

    # Last agent run
    st.markdown("---")
    last_run = db.get_last_agent_run()
    if last_run:
        ran = last_run.get("ran_at", "")[:16].replace("T", " ")
        st.markdown(
            f"<div style='font-size:0.65rem; color:#475569;'>"
            f"🤖 Last agent run: {ran}<br>"
            f"Alerts: {last_run.get('alerts_sent',0)} · "
            f"Orders: {last_run.get('procurement_created',0)}"
            f"</div>", unsafe_allow_html=True
        )

# ─── MAIN TABS ────────────────────────────────────────────────
t1, t2, t3, t4, t5 = st.tabs([
    "📊 Dashboard",
    "🏪 Stores & Managers",
    "📤 Upload Inventory",
    "📦 Procurement",
    "💬 WhatsApp Log"
])

# ══════════════════════════════════════════════════════════════
# TAB 1 — DASHBOARD
# ══════════════════════════════════════════════════════════════
with t1:
    if not selected_id:
        st.markdown("""<div class="hero">
            <div class="hero-badge">Dishii v8.0</div>
            <h1 class="hero-title">Autonomous Food <span>Operations</span></h1>
            <p class="hero-sub">
                Create a store profile → Add managers → Upload inventory →
                Agent monitors and alerts automatically
            </p></div>""", unsafe_allow_html=True)

        c1, c2, c3 = st.columns(3)
        for col, num, title, sub in [
            (c1, "1", "🏪 Create Store", "Add store + manager WhatsApp numbers"),
            (c2, "2", "📤 Upload Inventory", "Excel or CSV — auto-detected"),
            (c3, "3", "🤖 Agent Activates", "Monitors every 30 min, alerts automatically"),
        ]:
            col.markdown(
                f'<div class="kpi blue"><div class="kpi-label">Step {num}</div>'
                f'<div class="kpi-value" style="font-size:1.1rem;">{title}</div>'
                f'<div class="kpi-sub">{sub}</div></div>', unsafe_allow_html=True
            )
        st.stop()

    store = db.get_store_by_id(selected_id)
    items = db.get_latest_inventory(selected_id)

    # Hero
    managers = db.get_managers(selected_id)
    st.markdown(f"""<div class="hero">
        <div class="hero-badge">{store.get('store_type','supermarket').upper()}</div>
        <h1 class="hero-title">{store['name']} <span>Intelligence</span></h1>
        <p class="hero-sub">
            📍 {store.get('location','—')} &nbsp;·&nbsp;
            👥 {len(managers)} manager{'s' if len(managers) != 1 else ''} &nbsp;·&nbsp;
            📦 {len(items)} SKUs &nbsp;·&nbsp;
            {datetime.now().strftime('%d %b %Y, %H:%M')}
        </p></div>""", unsafe_allow_html=True)

    if not items:
        st.info("📤 No inventory loaded yet. Go to the **Upload Inventory** tab.")
        st.stop()

    # Build summary from DB data
    df_live = pd.DataFrame(items)
    summary = {
        "total":       len(items),
        "critical":    sum(1 for i in items if i.get("severity_level") == "CRITICAL"),
        "high":        sum(1 for i in items if i.get("severity_level") == "HIGH"),
        "medium":      sum(1 for i in items if i.get("severity_level") == "MEDIUM"),
        "low":         sum(1 for i in items if i.get("severity_level") == "LOW"),
        "total_value": sum(float(i.get("inventory_value", 0)) for i in items),
        "waste_value": sum(float(i.get("waste_value", 0)) for i in items),
    }
    if summary["total_value"] > 0:
        summary["health_score"] = max(0, min(100, int(
            100 - (summary["waste_value"] / summary["total_value"]) * 100
        )))
    else:
        summary["health_score"] = 100

    # Health + actions row
    c_h, c_v, c_w, c_b1, c_b2 = st.columns([3, 2, 2, 1, 1])
    with c_h:
        st.progress(summary["health_score"] / 100)
        st.caption(f"Health Score: **{summary['health_score']}%**")
    with c_v:
        st.metric("Inventory Value", f"KES {summary['total_value']:,.0f}")
    with c_w:
        st.metric("Waste Risk", f"KES {summary['waste_value']:,.0f}")
    with c_b1:
        if st.button("📱 Briefing", type="primary", use_container_width=True, help="Send AI briefing to all managers"):
            with st.spinner("Generating AI briefing..."):
                critical_items = [i for i in items if i.get("severity_level") in ("CRITICAL","HIGH")]
                briefing = generate_briefing(store["name"], summary, critical_items)
            phones = db.get_manager_phones(selected_id)
            if phones:
                msg = wa.msg_hourly_briefing(store["name"], briefing, summary)
                sent = wa.send_to_all(phones, msg)
                db.log_whatsapp(selected_id, "outbound", ",".join(phones), msg, "briefing")
                st.toast(f"✅ Briefing sent to {sent} manager(s)", icon="📱")
            else:
                st.warning("No managers configured for this store")
    with c_b2:
        if st.button("🔄 Refresh", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    # KPI row
    st.markdown(f"""
    <div class="kgrid">
        <div class="kpi red">
            <div class="kpi-label">🔴 Critical</div>
            <div class="kpi-value">{summary['critical']}</div>
            <div class="kpi-sub">Act immediately</div>
        </div>
        <div class="kpi amber">
            <div class="kpi-label">🟠 High</div>
            <div class="kpi-value">{summary['high']}</div>
            <div class="kpi-sub">Address today</div>
        </div>
        <div class="kpi green">
            <div class="kpi-label">🟢 Healthy</div>
            <div class="kpi-value">{summary['low']}</div>
            <div class="kpi-sub">No action needed</div>
        </div>
        <div class="kpi blue">
            <div class="kpi-label">📦 Orders Needed</div>
            <div class="kpi-value">{sum(1 for i in items if i.get('order_required'))}</div>
            <div class="kpi-sub">Procurement required</div>
        </div>
    </div>""", unsafe_allow_html=True)

    st.markdown("---")
    da, db_, dc = st.tabs(["🎯 Priority Actions", "📊 Analytics", "📋 Full Inventory"])

    with da:
        priority = [i for i in items if i.get("show_in_priority")][:show_n]
        if priority:
            st.markdown(f"#### 🎯 {len(priority)} Items — sorted by risk score")
            for item in priority:
                color = item.get("risk_color", "#dc2626")
                tl    = item.get("traffic_light", "🔴")
                pc1, pc2 = st.columns([5, 1])
                with pc1:
                    st.markdown(
                        f'<div class="item-card" style="border-left-color:{color};">'
                        f'<div class="item-title">{tl} {item["product_name"]}</div>'
                        f'<div class="item-reason">⚠️ {item.get("risk_reason","")}</div>'
                        f'<div class="item-meta">'
                        f'Supplier: {item.get("supplier","Unknown")} &nbsp;·&nbsp; '
                        f'Stock: {int(item.get("current_stock",0))} units &nbsp;·&nbsp; '
                        f'Action: {item.get("stock_action","")}'
                        f'</div></div>', unsafe_allow_html=True
                    )
                with pc2:
                    if item.get("order_required"):
                        if st.button("📱 Alert", key=f"al_{item['id']}", use_container_width=True):
                            phones = db.get_manager_phones(selected_id)
                            if phones:
                                msg = wa.msg_stock_alert(
                                    store["name"], item["product_name"],
                                    item["severity_level"],
                                    int(item.get("current_stock",0)),
                                    int(item.get("stock_days",0)),
                                    item.get("risk_reason","")
                                )
                                wa.send_to_all(phones, msg)
                                db.log_whatsapp(selected_id, "outbound",
                                                ",".join(phones), msg, "alert")
                                st.success("✅ Sent")
                            else:
                                st.error("No managers")
        else:
            st.success("✅ All inventory is healthy — no priority actions needed.")

    with db_:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### Risk Distribution")
            rdf = pd.DataFrame([
                {"Level": "🔴 Critical", "Count": summary["critical"], "Color": "#dc2626"},
                {"Level": "🟠 High",     "Count": summary["high"],     "Color": "#f59e0b"},
                {"Level": "🟡 Medium",   "Count": summary["medium"],   "Color": "#eab308"},
                {"Level": "🟢 Low",      "Count": summary["low"],      "Color": "#10b981"},
            ])
            rdf = rdf[rdf["Count"] > 0]
            if not rdf.empty:
                fig = px.pie(rdf, names="Level", values="Count", hole=0.45,
                             color="Level",
                             color_discrete_map={
                                 "🔴 Critical":"#dc2626","🟠 High":"#f59e0b",
                                 "🟡 Medium":"#eab308","🟢 Low":"#10b981"
                             })
                fig.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                                  font=dict(color="#94a3b8"),
                                  margin=dict(l=0,r=0,t=20,b=0))
                st.plotly_chart(fig, use_container_width=True)
        with c2:
            st.markdown("#### Value vs Waste by Category")
            if items:
                df_cat = df_live.groupby("category").agg(
                    value=("inventory_value","sum"),
                    waste=("waste_value","sum")
                ).reset_index()
                if not df_cat.empty:
                    fig2 = px.bar(df_cat, x="category", y=["value","waste"],
                                  barmode="group",
                                  color_discrete_map={"value":"#3b82f6","waste":"#dc2626"})
                    fig2.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                                       font=dict(color="#94a3b8"))
                    st.plotly_chart(fig2, use_container_width=True)

    with dc:
        st.markdown("#### 📋 Full Inventory — sorted by risk score (highest first)")
        show_cols = ["product_name","category","traffic_light","severity_level",
                     "days_to_expiry","current_stock","stock_days",
                     "risk_reason","discount_percent","inventory_value","supplier"]
        show_cols = [c for c in show_cols if c in df_live.columns]
        st.dataframe(
            df_live[show_cols].sort_values("risk_score" if "risk_score" in df_live.columns else "severity_level",
                                            ascending=False).head(100),
            use_container_width=True, height=450,
            column_config={
                "inventory_value": st.column_config.NumberColumn("Value (KES)", format="KES %.0f"),
                "discount_percent":st.column_config.NumberColumn("Discount %",  format="%.0f%%"),
                "stock_days":      st.column_config.NumberColumn("Stock Days",   format="%.1f"),
                "days_to_expiry":  st.column_config.NumberColumn("Expiry (days)",format="%d"),
            }
        )
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            df_live[show_cols].to_excel(w, index=False)
        st.download_button(
            "📥 Export to Excel",
            data=buf.getvalue(),
            file_name=f"dishii_{store['name'].replace(' ','_')}_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

# ══════════════════════════════════════════════════════════════
# TAB 2 — STORES & MANAGERS
# ══════════════════════════════════════════════════════════════
with t2:
    st.markdown("### 🏪 Stores & Managers")
    st.caption("All phone numbers are saved in the database. The agent reads them automatically.")

    cf, cl = st.columns([2, 3])

    with cf:
        st.markdown("#### Create New Store")
        with st.form("new_store", clear_on_submit=True):
            s_name = st.text_input("Store Name *", placeholder="e.g. 99 Mart Westlands")
            s_loc  = st.text_input("Location",      placeholder="Westlands, Nairobi")
            s_type = st.selectbox("Type", ["supermarket","mini_mart","restaurant","distributor","pharmacy"])

            st.markdown("**Add Managers** (1 required, up to 4)")
            mgrs = []
            for i in range(1, 5):
                req = " *" if i == 1 else ""
                mc1, mc2 = st.columns(2)
                with mc1: mn = st.text_input(f"Name{req}", key=f"mn{i}", placeholder="Full name")
                with mc2: mp = st.text_input(f"Phone{req}", key=f"mp{i}", placeholder="+254720521291")
                if mn and mp:
                    mgrs.append({"name": mn, "phone": mp})

            if st.form_submit_button("💾 Save Store", type="primary", use_container_width=True):
                if not s_name:
                    st.error("Store name is required")
                elif not mgrs:
                    st.error("At least 1 manager with name and phone is required")
                else:
                    new_store = db.create_store(s_name, s_loc, s_type)
                    if new_store:
                        for m in mgrs:
                            db.add_manager(new_store["id"], m["name"], m["phone"])
                            # Send welcome message
                            wa.send(
                                m["phone"].replace("+","").replace(" ",""),
                                wa.msg_welcome(s_name, m["name"])
                            )
                        st.success(f"✅ Store '{s_name}' created with {len(mgrs)} manager(s)!")
                        st.rerun()
                    else:
                        st.error("Failed to create store — check Supabase connection")

    with cl:
        st.markdown("#### Your Stores")
        all_stores = db.get_all_stores()
        if not all_stores:
            st.info("No stores yet. Create your first store →")
        for s in all_stores:
            mgr_list = db.get_managers(s["id"])
            is_sel   = s["id"] == selected_id
            bc       = "#10b981" if is_sel else "#1e3a5f"
            mgr_text = "  &nbsp;  ".join([
                f"👤 {m['name']} (+{m['phone']})" for m in mgr_list
            ]) or "No managers"
            st.markdown(
                f'<div class="item-card" style="border-left-color:{bc};">'
                f'<div class="item-title">{"✅ " if is_sel else ""}{s["name"]}</div>'
                f'<div class="item-reason">📍 {s.get("location","—")} · {s.get("store_type","—")}</div>'
                f'<div class="item-meta">{mgr_text}</div>'
                f'</div>', unsafe_allow_html=True
            )
            # Add manager form
            with st.expander(f"➕ Add manager to {s['name']}"):
                with st.form(f"add_mgr_{s['id']}"):
                    am_name = st.text_input("Manager name",  key=f"amn_{s['id']}")
                    am_phone= st.text_input("WhatsApp phone", key=f"amp_{s['id']}", placeholder="+254720521291")
                    am_role = st.selectbox("Role", ["manager","owner","supervisor"], key=f"amr_{s['id']}")
                    if st.form_submit_button("Add Manager"):
                        if am_name and am_phone:
                            db.add_manager(s["id"], am_name, am_phone, am_role)
                            wa.send(
                                am_phone.replace("+","").replace(" ",""),
                                wa.msg_welcome(s["name"], am_name)
                            )
                            st.success(f"✅ {am_name} added")
                            st.rerun()
                        else:
                            st.error("Name and phone required")

# ══════════════════════════════════════════════════════════════
# TAB 3 — UPLOAD INVENTORY
# ══════════════════════════════════════════════════════════════
with t3:
    st.markdown("### 📤 Upload Inventory")
    st.caption("Upload an Excel or CSV. The system detects columns automatically.")

    if not stores:
        st.warning("Create a store first (Stores & Managers tab).")
    else:
        target_id = st.selectbox(
            "Upload inventory for:",
            [s["id"] for s in stores],
            format_func=lambda x: next(s["name"] for s in stores if s["id"] == x),
            key="upload_target"
        )

        # Sample format
        with st.expander("📋 See expected format"):
            st.dataframe(pd.DataFrame({
                "product_name":    ["Tomatoes","Milk 500ml","Chicken Breast","Rice 2kg","Bread"],
                "expiry_date":     ["2026-05-22","2026-05-20","2026-05-19","2026-12-31","2026-05-21"],
                "current_stock":   [50, 200, 30, 500, 80],
                "daily_sales_rate":[12, 20, 8, 10, 25],
                "supplier":        ["Fresh Farms","DairyCo","Kenchic","Rice Millers","Bakers Inn"],
                "selling_price":   [120, 65, 350, 180, 55],
                "supplier_phone":  ["254712000001","","254712000003","",""],
                "cost_price":      [80, 45, 220, 120, 35],
            }), use_container_width=True)
            st.caption("**supplier_phone** enables autonomous WhatsApp to suppliers when manager approves")

        uf = st.file_uploader("Choose file", type=["xlsx","csv","xls"])

        if uf:
            target_store = db.get_store_by_id(target_id)
            file_bytes   = uf.getvalue()
            fhash        = db.file_hash(file_bytes)
            uf.seek(0)

            if db.is_already_processed(fhash):
                st.warning("⚠️ This exact file was already uploaded. Upload a new file to update inventory.")
            else:
                with st.spinner(f"Processing {uf.name}..."):
                    try:
                        raw = (pd.read_excel(uf)
                               if not uf.name.lower().endswith(".csv")
                               else pd.read_csv(uf))

                        if raw.empty:
                            st.error("File is empty")
                            st.stop()

                        # Create upload record
                        upload_id = db.create_upload_record(target_id, uf.name, fhash)
                        if not upload_id:
                            st.error("Failed to create upload record in database")
                            st.stop()

                        # Process: normalize → categorize → classify
                        df_processed, summary = process_upload(
                            raw, target_id, upload_id, red_t, amber_t, stock_w
                        )

                        # Update summary
                        db.update_upload_summary(upload_id, summary)

                        # Save items to DB
                        rows = df_to_db_rows(df_processed)
                        saved = db.insert_inventory_items(rows)

                        if saved:
                            st.success(f"✅ {len(rows)} SKUs loaded for **{target_store['name']}**")

                            # Metrics
                            c1,c2,c3,c4 = st.columns(4)
                            c1.metric("Total SKUs",    summary["total"])
                            c2.metric("🔴 Critical",   summary["critical"])
                            c3.metric("📦 Need Orders",
                                      sum(1 for i in df_to_db_rows(df_processed) if i.get("order_required")))
                            c4.metric("Health Score",  f"{summary['health_score']}%")

                            # Automatic WhatsApp alerts to all managers
                            phones = db.get_manager_phones(target_id)
                            if phones:
                                # Generate AI briefing
                                critical_items = df_processed[
                                    df_processed["severity_level"].isin(["CRITICAL","HIGH"])
                                ].to_dict("records")

                                with st.spinner("Generating AI briefing..."):
                                    briefing = generate_briefing(
                                        target_store["name"], summary, critical_items
                                    )

                                # Send upload alert + briefing
                                alert_msg = (
                                    f"📊 *Inventory Uploaded — {target_store['name']}*\n"
                                    f"{len(rows)} SKUs · 🔴 {summary['critical']} critical · "
                                    f"Health: {summary['health_score']}%\n"
                                    f"Waste risk: KES {summary['waste_value']:,.0f}\n\n"
                                    f"{briefing}"
                                )
                                sent = wa.send_to_all(phones, alert_msg)
                                db.log_whatsapp(target_id, "outbound",
                                                ",".join(phones), alert_msg, "upload_alert")

                                st.info(f"📱 Alert + AI briefing sent to {sent} manager(s)")

                                # Create procurement requests for order items
                                order_items = df_processed[df_processed["order_required"] == True]
                                proc_count = 0
                                for _, row in order_items.head(5).iterrows():
                                    daily_r = max(float(row.get("daily_sales_rate", 1)), 0.1)
                                    qty     = max(1, int(daily_r * 14))
                                    row_dict = row.to_dict()
                                    row_dict["upload_id"] = upload_id
                                    req_id = db.create_procurement_request(target_id, row_dict, qty)
                                    if req_id:
                                        proc_count += 1
                                        value = qty * float(row.get("selling_price", 0))
                                        proc_msg = wa.msg_procurement_request(
                                            target_store["name"],
                                            row["product_name"],
                                            qty,
                                            row.get("supplier", "Unknown"),
                                            value,
                                            req_id,
                                            row.get("severity_level", "HIGH")
                                        )
                                        wa.send_to_all(phones, proc_msg)
                                        db.log_whatsapp(target_id, "outbound",
                                                        ",".join(phones), proc_msg,
                                                        "procurement", req_id)

                                if proc_count > 0:
                                    st.info(f"📦 {proc_count} procurement approval requests sent")
                            else:
                                st.warning("⚠️ No managers configured — add managers to receive alerts")
                        else:
                            st.error("Failed to save inventory items to database")

                    except Exception as e:
                        st.error(f"❌ Upload failed: {e}")
                        logger.error(f"Upload error: {e}", exc_info=True)

# ══════════════════════════════════════════════════════════════
# TAB 4 — PROCUREMENT
# ══════════════════════════════════════════════════════════════
with t4:
    st.markdown("### 📦 Procurement Workflow")
    st.caption("Approve → supplier gets a WhatsApp automatically. Reject → agent monitors and re-alerts.")

    if not selected_id:
        st.warning("Select a store in the sidebar.")
    else:
        pending   = db.get_pending_procurement(selected_id)
        all_procs = db.get_all_procurement(selected_id)

        cp, ch = st.columns([3, 2])

        with cp:
            st.markdown(f"#### Awaiting Approval ({len(pending)})")
            if not pending:
                st.success("✅ No pending approvals")
            else:
                for req in pending:
                    urgency_color = {"CRITICAL":"#dc2626","HIGH":"#f59e0b"}.get(
                        req.get("urgency","HIGH"), "#f59e0b"
                    )
                    st.markdown(
                        f'<div class="item-card" style="border-left-color:{urgency_color};">'
                        f'<div class="item-title">{req["product_name"]}</div>'
                        f'<div class="item-reason">'
                        f'Order: {req["suggested_qty"]} units · KES {req.get("total_value",0):,.0f}<br>'
                        f'Supplier: {req.get("supplier","Unknown")}'
                        f'{"  📱" if req.get("supplier_phone") else ""}'
                        f'</div>'
                        f'<div class="item-meta">Ref: {str(req["id"])[:8].upper()}</div>'
                        f'</div>', unsafe_allow_html=True
                    )
                    phones = db.get_manager_phones(selected_id)
                    ca, cr = st.columns(2)
                    with ca:
                        if st.button("✅ YES — Approve", key=f"yes_{req['id']}", type="primary", use_container_width=True):
                            mgr_phone = phones[0] if phones else ""
                            db.approve_procurement(req["id"], mgr_phone)
                            # Notify supplier if they have WhatsApp
                            if req.get("supplier_phone"):
                                sup_msg = wa.msg_supplier_order(
                                    store["name"], req["product_name"],
                                    req["suggested_qty"], req["id"]
                                )
                                wa.send(req["supplier_phone"], sup_msg)
                                db.log_whatsapp(selected_id, "outbound",
                                                req["supplier_phone"], sup_msg,
                                                "supplier_order", req["id"])
                                db.mark_supplier_notified(req["id"])
                            # Confirm to manager
                            if phones:
                                conf_msg = wa.msg_procurement_approved(
                                    req["product_name"], req["suggested_qty"],
                                    req.get("supplier","Unknown"),
                                    req.get("total_value",0), req["id"]
                                )
                                wa.send_to_all(phones, conf_msg)
                                db.log_whatsapp(selected_id,"outbound",",".join(phones),conf_msg,"procurement")
                            st.success("✅ Approved — supplier notified")
                            st.rerun()
                    with cr:
                        if st.button("❌ NO — Skip", key=f"no_{req['id']}", use_container_width=True):
                            mgr_phone = phones[0] if phones else ""
                            db.reject_procurement(req["id"], mgr_phone)
                            if phones:
                                rej_msg = wa.msg_procurement_rejected(req["product_name"], req["id"])
                                wa.send_to_all(phones, rej_msg)
                                db.log_whatsapp(selected_id,"outbound",",".join(phones),rej_msg,"procurement")
                            st.info("Order skipped")
                            st.rerun()

        with ch:
            st.markdown("#### Order History")
            if all_procs:
                for req in all_procs[:20]:
                    status_c = {"approved":"#10b981","rejected":"#ef4444",
                                "supplier_notified":"#3b82f6","awaiting_manager":"#f59e0b"
                               }.get(req.get("status",""), "#64748b")
                    st.markdown(
                        f'<div class="item-card" style="border-left-color:{status_c}; padding:0.5rem 0.75rem;">'
                        f'<div style="font-size:0.8rem; font-weight:600; color:#e2e8f0;">'
                        f'{req["product_name"]}</div>'
                        f'<div style="font-size:0.65rem; color:#64748b;">'
                        f'{req["suggested_qty"]} units · {req.get("status","?").replace("_"," ").title()}'
                        f'</div></div>', unsafe_allow_html=True
                    )
            else:
                st.info("No procurement history yet")

# ══════════════════════════════════════════════════════════════
# TAB 5 — WHATSAPP LOG
# ══════════════════════════════════════════════════════════════
with t5:
    st.markdown("### 💬 WhatsApp Log")
    wa_status = wa.get_connection_status()
    status_color = "#10b981" if wa_status == "open" else "#f59e0b"
    st.markdown(
        f'<div class="item-card" style="border-left-color:{status_color};">'
        f'<div class="item-title">WhatsApp: {wa_status.replace("_"," ").title()}</div>'
        f'<div class="item-reason">'
        f'{"✅ Connected — messages delivered to real phones" if wa_status == "open" else "⚠️ Not connected — add EVOLUTION_URL + EVOLUTION_KEY to .env and scan QR code"}'
        f'</div></div>', unsafe_allow_html=True
    )

    if selected_id:
        logs = db.get_whatsapp_logs(selected_id, limit=50)
        st.markdown(f"#### Last {len(logs)} Messages")
        for log in logs:
            direction = log.get("direction","outbound")
            phone  = log.get("to_phone","") if direction == "outbound" else log.get("from_phone","")
            mtype  = log.get("message_type","text")
            sent_at= (log.get("sent_at","")[:16]).replace("T"," ")
            color  = {"alert":"#dc2626","procurement":"#f59e0b","briefing":"#3b82f6",
                      "supplier_order":"#8b5cf6"}.get(mtype, "#475569")
            st.markdown(
                f'<div style="margin-bottom:0.6rem;">'
                f'<div style="font-size:0.62rem; color:#475569; margin-bottom:2px;">'
                f'{sent_at} · <span style="color:{color};">{mtype}</span>'
                f' · {"→" if direction=="outbound" else "←"} +{phone}</div>'
                f'<div style="background:#0d1f35; border:1px solid #1e3a5f; border-radius:8px 8px 8px 0;'
                f' padding:0.6rem 0.875rem; font-size:0.78rem; color:#cbd5e1; white-space:pre-wrap;">'
                f'{log.get("message_text","")[:300]}'
                f'{"..." if len(log.get("message_text",""))>300 else ""}'
                f'</div></div>', unsafe_allow_html=True
            )
    else:
        st.info("Select a store to see its WhatsApp log.")