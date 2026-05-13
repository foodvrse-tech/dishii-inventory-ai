# config.py - Enterprise Configuration
import streamlit as st
from supabase import create_client
from datetime import datetime, date
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import io
import json
from typing import Dict, List, Tuple, Optional

# ============================================
# SUPABASE CONFIGURATION
# ============================================
SUPABASE_URL = "https://tznihubrulrjuxtetvzi.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InR6bmlodWJydWxyanV4dGV0dnppIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzg2Njc0ODMsImV4cCI6MjA5NDI0MzQ4M30.9JqeGvgcCPsaE3IEfwrDfLug1zNROUrjV_B92w7NJjc"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ============================================
# ENTERPRISE DISCOUNT RULES
# ============================================
DISCOUNT_RULES = {
    (180, 999): 0,      # >180 days: no discount
    (120, 180): 5,      # 120-180 days: 5% off
    (90, 120): 10,      # 90-120 days: 10% off
    (60, 90): 15,       # 60-90 days: 15% off
    (45, 60): 20,       # 45-60 days: 20% off
    (30, 45): 30,       # 30-45 days: 30% off
    (14, 30): 40,       # 14-30 days: 40% off
    (7, 14): 50,        # 7-14 days: 50% off
    (0, 7): 65,         # <7 days: 65% off
    (-999, 0): 80       # Expired: 80% off clearance
}

# ============================================
# PRODUCT CATEGORIES WITH BEHAVIORS
# ============================================
CATEGORY_RULES = {
    "dairy": {"urgency_multiplier": 1.5, "return_policy": "supplier", "auto_markdown": True},
    "bakery": {"urgency_multiplier": 2.0, "return_policy": "internal_repurpose", "auto_markdown": True},
    "produce": {"urgency_multiplier": 1.3, "return_policy": "discount", "auto_markdown": True},
    "frozen": {"urgency_multiplier": 0.7, "return_policy": "none", "auto_markdown": False},
    "beverages": {"urgency_multiplier": 0.5, "return_policy": "supplier", "auto_markdown": False},
    "dry_goods": {"urgency_multiplier": 0.3, "return_policy": "none", "auto_markdown": False},
    "meat": {"urgency_multiplier": 1.8, "return_policy": "supplier", "auto_markdown": True},
    "deli": {"urgency_multiplier": 1.6, "return_policy": "internal_repurpose", "auto_markdown": True}
}

# ============================================
# DEFAULT THRESHOLDS
# ============================================
DEFAULT_THRESHOLDS = {
    "red_days": 60,
    "amber_days": 120,
    "stock_warning_days": 14,
    "critical_stock_days": 7,
    "auto_markdown_enabled": True,
    "auto_supplier_notification_enabled": True,
    "auto_reordering_enabled": False,
    "markdown_threshold_days": 14,
    "expiry_alert_days": 30
}

# ============================================
# HELPER FUNCTIONS
# ============================================

def days_to_expiry(expiry_date):
    """Calculate days until expiry with timezone handling"""
    if pd.isna(expiry_date) or expiry_date is None:
        return None
    try:
        today = datetime.now().date()
        if isinstance(expiry_date, str):
            expiry_date = pd.to_datetime(expiry_date)
        if hasattr(expiry_date, 'date'):
            expiry = expiry_date.date()
        else:
            expiry = expiry_date
        return (expiry - today).days
    except:
        return None

def get_discount_percentage(days_left, category=None):
    """Calculate recommended discount based on days to expiry and category"""
    base_discount = 0
    for (min_days, max_days), discount in DISCOUNT_RULES.items():
        if days_left is not None and min_days <= days_left < max_days:
            base_discount = discount
            break
    
    # Apply category multiplier if applicable
    if category and category in CATEGORY_RULES:
        multiplier = CATEGORY_RULES[category].get("urgency_multiplier", 1.0)
        # Only increase discount for urgent categories
        if days_left and days_left < 30:
            base_discount = min(base_discount * multiplier, 85)
    
    return int(base_discount)

def get_traffic_light(days_left, category=None):
    """Enhanced traffic light with category awareness"""
    if days_left is None:
        return "⚪", "No Expiry Data", "#9ca3af", "unknown"
    
    # Apply category multiplier for urgency
    multiplier = 1.0
    if category and category in CATEGORY_RULES:
        multiplier = CATEGORY_RULES[category].get("urgency_multiplier", 1.0)
        adjusted_days = days_left / multiplier
    else:
        adjusted_days = days_left
    
    if days_left < 0:
        return "⬛", "EXPIRED - Action Required", "#1f2937", "critical"
    elif adjusted_days <= 7:
        return "🔴", f"CRITICAL - {days_left} days left", "#dc2626", "critical"
    elif adjusted_days <= 14:
        return "🔴", f"URGENT - {days_left} days left", "#ef4444", "high"
    elif adjusted_days <= 30:
        return "🟠", f"WARNING - {days_left} days left", "#f59e0b", "high"
    elif adjusted_days <= 60:
        return "🟡", f"MONITOR - {days_left} days left", "#eab308", "medium"
    else:
        return "🟢", f"HEALTHY - {days_left} days left", "#10b981", "low"

def get_stock_status(current_stock, daily_sales_rate):
    """Enhanced stock status with predictions"""
    try:
        stock = float(current_stock) if not pd.isna(current_stock) else 0
        sales = float(daily_sales_rate) if not pd.isna(daily_sales_rate) else 0.001
    except:
        return "⚠️ Data Error", 0, "unknown", "#9ca3af", 0
    
    if sales <= 0:
        sales = 0.001
    
    days_remaining = stock / sales
    
    if stock <= 0:
        return "❌ OUT OF STOCK - Order Now", 0, "critical", "#dc2626", 0
    elif days_remaining <= 3:
        return "🚨 CRITICAL - Order Immediately", days_remaining, "critical", "#dc2626", days_remaining
    elif days_remaining <= 7:
        return "⚠️ URGENT - Order Within 48 Hours", days_remaining, "high", "#ef4444", days_remaining
    elif days_remaining <= 14:
        return "📦 LOW STOCK - Reorder Soon", days_remaining, "high", "#f59e0b", days_remaining
    elif days_remaining <= 30:
        return "✅ ADEQUATE - Monitor Weekly", days_remaining, "medium", "#eab308", days_remaining
    elif days_remaining > 90:
        return "⏸️ OVERSTOCK - Halt Purchasing", days_remaining, "low", "#3b82f6", days_remaining
    else:
        return "✅ HEALTHY - Normal Operations", days_remaining, "low", "#10b981", days_remaining

def get_recovery_action(days_left, category, supplier=None):
    """Determine appropriate recovery workflow"""
    if days_left is None or days_left > 14:
        return None, "No action needed"
    
    if days_left < 0:
        return "disposal", "Product expired - initiate disposal"
    
    if category and category in CATEGORY_RULES:
        policy = CATEGORY_RULES[category].get("return_policy", "discount")
        if policy == "supplier" and supplier:
            return "return_to_supplier", f"Contact {supplier} for return/credit"
        elif policy == "internal_repurpose":
            return "internal_repurpose", "Move to deli/bakery for repurposing"
    
    if days_left <= 3:
        return "clearance", "Deep discount clearance - 75%+ off"
    elif days_left <= 7:
        return "discount", "Aggressive discount - 50-65% off"
    elif days_left <= 14:
        return "promotion", "Bundle promotion - Buy one get one"
    
    return "discount", "Standard markdown recommended"

def calculate_inventory_health(df):
    """Calculate overall inventory health score"""
    if df.empty:
        return 0
    
    # Weighted factors
    expiry_score = 0
    stock_score = 0
    
    # Expiry health
    red_count = len(df[df['traffic_light'] == '🔴'])
    amber_count = len(df[df['traffic_light'] == '🟠'])
    green_count = len(df[df['traffic_light'] == '🟢'])
    total = len(df)
    
    if total > 0:
        expiry_score = (green_count * 100 + amber_count * 50 + red_count * 0) / total
    
    # Stock health
    if 'order_required' in df.columns:
        order_count = len(df[df['order_required'] == True])
        stock_score = ((total - order_count) * 100) / total
    
    return int((expiry_score * 0.6 + stock_score * 0.4))

def normalize_columns(df):
    """Enhanced column auto-detection"""
    df.columns = df.columns.str.lower().str.strip().str.replace(" ", "_")
    
    mappings = {
        "product_name": ["product_name", "product", "item", "name", "item_name", "description", "sku_name"],
        "expiry_date": ["expiry_date", "expiry", "best_before", "expiration_date", "exp_date", "use_by"],
        "current_stock": ["current_stock", "stock", "quantity", "qty", "inventory", "units", "on_hand"],
        "daily_sales_rate": ["daily_sales_rate", "daily_sales", "sales_rate", "avg_daily_sales", "velocity", "avg_sales"],
        "supplier": ["supplier", "vendor", "supplier_name", "vendor_name", "source"],
        "cost_price": ["cost", "cost_price", "unit_cost", "purchase_price", "buying_price"],
        "selling_price": ["selling_price", "price", "retail_price", "sale_price"],
        "category": ["category", "product_category", "type", "department"],
        "unit": ["unit", "uom", "unit_of_measure", "measurement"],
        "sku": ["sku", "upc", "barcode", "product_code"]
    }
    
    for target, options in mappings.items():
        if target not in df.columns:
            for col in options:
                if col in df.columns:
                    df[target] = df[col]
                    break
    
    # Default values
    if "product_name" not in df.columns:
        df["product_name"] = [f"Item {i+1}" for i in range(len(df))]
    
    for col in ["expiry_date", "current_stock", "daily_sales_rate", "supplier", "cost_price", "selling_price", "category", "unit", "sku"]:
        if col not in df.columns:
            df[col] = None
    
    # Convert numeric columns
    df["current_stock"] = pd.to_numeric(df["current_stock"], errors="coerce").fillna(0)
    
    if "daily_sales_rate" in df.columns:
        df["daily_sales_rate"] = pd.to_numeric(df["daily_sales_rate"], errors="coerce").fillna(1)
    else:
        df["daily_sales_rate"] = 1
    
    if "cost_price" in df.columns:
        df["cost_price"] = pd.to_numeric(df["cost_price"], errors="coerce").fillna(0)
    else:
        df["cost_price"] = 0
    
    if "selling_price" in df.columns:
        df["selling_price"] = pd.to_numeric(df["selling_price"], errors="coerce").fillna(df["cost_price"] * 1.3)
    else:
        df["selling_price"] = df["cost_price"] * 1.3
    
    # Auto-detect category if not present
    if "category" in df.columns:
        df["category"] = df["category"].fillna("dry_goods")
    else:
        df["category"] = "dry_goods"
    
    return df