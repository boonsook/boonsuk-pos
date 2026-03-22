import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import json
import hashlib
import hmac
import os
from supabase import create_client, Client
import barcode as bc
from barcode.writer import ImageWriter
from io import BytesIO
import io
import openpyxl
from PIL import Image
import time
from abc import ABC
from streamlit.components.v1 import html as st_html

st.set_page_config(
    page_title="ร้านบุญสุขอิเล็กทรอนิกส์ - POS",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ============================================================================
# CONSTANTS & CONFIGURATION
# ============================================================================

STORE_NAME = "ร้านบุญสุขอิเล็กทรอนิกส์"
STORE_PHONE = "086-261-3829"
STORE_ADDRESS = "87 ม.12 ต.คาละแมะ อ.ศีขรภูมิ จ.สุรินทร์ 32110"
TAX_ID = "3320800011106"

POS_CATEGORIES = [
    "เครื่องใช้ไฟฟ้า",
    "เครื่องซักผ้า",
    "ตู้เย็น",
    "ทีวี",
    "พัดลม",
    "หม้อหุงข้าว",
    "เครื่องทำน้ำอุ่น",
    "อะไหล่แอร์",
    "อุปกรณ์ไฟฟ้า",
    "กล้องวงจรปิด",
    "เครื่องปรับอากาศ",
    "อุปกรณ์ดาวเทียม",
    "อื่นๆ"
]

PAYMENT_METHODS = ["เงินสด", "โอนเงิน", "บัตรเครดิต"]

# ============================================================================
# USERS & AUTHENTICATION
# ============================================================================

USERS = {
    "admin": os.getenv("ADMIN_PASSWORD_HASH", hashlib.sha256("boonsuk_2024".encode()).hexdigest()),
    "staff": os.getenv("STAFF_PASSWORD_HASH", hashlib.sha256("staff_1234".encode()).hexdigest()),
}

SESSION_SECRET_KEY = os.getenv("SESSION_SECRET_KEY", "")
if not SESSION_SECRET_KEY:
    import secrets as _sec
    SESSION_SECRET_KEY = _sec.token_hex(32)

def _run_js(js_code: str):
    st_html(f"<script>{js_code}</script>", height=0)

def _encode_session(data: dict) -> str:
    import base64
    payload = json.dumps(data, ensure_ascii=True, separators=(',', ':'))
    sig = hmac.new(SESSION_SECRET_KEY.encode(), payload.encode(), hashlib.sha256).digest()
    combined = payload.encode() + b'.' + sig
    return base64.urlsafe_b64encode(combined).decode().rstrip('=')

def _decode_session(token: str) -> dict:
    import base64
    try:
        token = str(token).strip()
        pad = 4 - len(token) % 4
        if pad != 4:
            token += "=" * pad
        combined = base64.urlsafe_b64decode(token.encode())
        sep = combined.rfind(b'.')
        if sep < 0:
            return {}
        payload, sig = combined[:sep], combined[sep+1:]
        expected = hmac.new(SESSION_SECRET_KEY.encode(), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            return {}
        return json.loads(payload.decode())
    except Exception:
        return {}

def check_login():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
        st.session_state.username = ""
        st.session_state.role = ""
        st.session_state.full_name = ""

    # Handle logout
    if st.query_params.get("logout", "") == "1":
        st.session_state.logged_in = False
        st.session_state.username = ""
        st.session_state.role = ""
        st.session_state.full_name = ""
        st.session_state.page = "home"
        try: del st.query_params["s"]
        except: pass
        return

    if st.session_state.logged_in:
        return

    # Restore from URL token
    token = str(st.query_params.get("s", "")).strip()
    if token:
        data = _decode_session(token)
        if data and isinstance(data, dict):
            exp = data.get("exp", 0)
            if isinstance(exp, (int, float)) and exp > time.time():
                st.session_state.logged_in = True
                st.session_state.username = str(data.get("u", ""))
                st.session_state.role = str(data.get("r", ""))
                st.session_state.full_name = str(data.get("n", ""))
                return

def _save_session():
    data = {
        "u": st.session_state.get("username", ""),
        "r": st.session_state.get("role", ""),
        "n": st.session_state.get("full_name", ""),
        "exp": time.time() + (30 * 24 * 3600),
    }
    token = _encode_session(data)
    old_token = str(st.query_params.get("s", "")).strip()
    if old_token != token:
        st.query_params["s"] = token
    _run_js(f'''
        try {{ parent.localStorage.setItem("pos_token","{token}"); }} catch(e) {{}}
        try {{ localStorage.setItem("pos_token","{token}"); }} catch(e) {{}}
    ''')

def login_page():
    _is_logout = st.query_params.get("logout", "") == "1"
    if not _is_logout:
        _run_js('''
            try {
                var t = null;
                try { t = parent.localStorage.getItem("pos_token"); } catch(e) {}
                if(!t) { try { t = localStorage.getItem("pos_token"); } catch(e) {} }
                if(t && t.length > 10) {
                    var loc = (parent && parent.location) ? parent.location : window.location;
                    var u = new URL(loc.href);
                    if(!u.searchParams.has("s") && !u.searchParams.has("logout")) {
                        u.searchParams.set("s", t);
                        loc.replace(u.toString());
                    }
                }
            } catch(e) {}
        ''')
    else:
        _run_js('''
            try { parent.localStorage.removeItem("pos_token"); } catch(e) {}
            try { localStorage.removeItem("pos_token"); } catch(e) {}
        ''')
        try: del st.query_params["logout"]
        except: pass

    st.markdown("""
    <style>
    [data-testid="stSidebar"] { display: none !important; }
    .main .block-container { padding: 1rem !important; max-width: 100% !important; }
    </style>
    """, unsafe_allow_html=True)

    st.markdown(f"""
    <div style="max-width:440px; margin:40px auto 0; background:#fff; border-radius:20px;
        box-shadow:0 4px 24px rgba(0,0,0,0.08); padding:32px; text-align:center;
        border-top:5px solid #2563eb;">
        <div style="font-size:48px; margin-bottom:8px;">🛒</div>
        <h2 style="margin:0; font-size:22px; color:#1e3a5f; font-weight:800;">{STORE_NAME}</h2>
        <p style="color:#64748b; font-size:13px; margin:4px 0 0;">ระบบ POS ขายสินค้า</p>
        <hr style="border:none; border-top:1px solid #e2e8f0; margin:20px 0;">
    </div>
    """, unsafe_allow_html=True)

    col_space1, col_form, col_space2 = st.columns([1, 2, 1])
    with col_form:
        st.markdown("#### 🔐 เข้าสู่ระบบ")
        username = st.text_input("👤 ชื่อผู้ใช้", placeholder="admin หรือ staff", key="lg_user")
        password = st.text_input("🔑 รหัสผ่าน", type="password", key="lg_pw")
        if st.button("🚀 เข้าสู่ระบบ", use_container_width=True, type="primary", key="lg_btn"):
            pw_hash = hashlib.sha256(password.encode()).hexdigest()
            if username in USERS and USERS[username] == pw_hash:
                role = "admin" if username == "admin" else "staff"
                st.session_state.logged_in = True
                st.session_state.username = username
                st.session_state.role = role
                st.session_state.full_name = "ผู้ดูแลระบบ" if role == "admin" else "พนักงาน"
                st.session_state.page = "home"
                _save_session()
                st.rerun()
            else:
                st.error("❌ ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")

        st.markdown(f"""
        <div style="text-align:center; margin-top:24px; padding-top:16px;
            border-top:1px solid #e2e8f0;">
            <p style="font-size:10px; color:#94a3b8; margin:0;">
                {STORE_NAME} • ☎ {STORE_PHONE}
            </p>
        </div>
        """, unsafe_allow_html=True)

# ============================================================================
# SUPABASE CONNECTION
# ============================================================================

@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets.get("SUPABASE_URL", "")
    key = st.secrets.get("SUPABASE_KEY", "")
    return create_client(url, key)

supabase = init_supabase()

# ============================================================================
# TABLE INITIALIZATION
# ============================================================================

def initialize_tables():
    """Initialize required tables if they don't exist"""
    try:
        # Try to create pos_products table
        try:
            supabase.table("pos_products").select("id").limit(1).execute()
        except:
            pass

        # Try to create pos_sales table
        try:
            supabase.table("pos_sales").select("id").limit(1).execute()
        except:
            pass

        # Try to create pos_customers table
        try:
            supabase.table("pos_customers").select("id").limit(1).execute()
        except:
            pass

    except Exception as e:
        st.error(f"ข้อผิดพลาดในการเตรียมฐานข้อมูล: {str(e)}")

initialize_tables()

# ============================================================================
# CUSTOM CSS STYLING
# ============================================================================

def load_custom_css():
    css = """
    <style>
    /* Main theme colors */
    :root {
        --primary-blue: #1e3a5f;
        --primary-blue-light: #2563eb;
        --accent-blue: #3b82f6;
        --light-bg: #f8fafc;
        --card-shadow: 0 1px 3px rgba(0, 0, 0, 0.12);
    }

    /* Hide sidebar completely */
    [data-testid="stSidebar"] { display: none !important; }

    /* Main content */
    .main {
        background-color: #f0f4f8;
    }

    /* ============ MENU GRID (เหมือนแอปแอร์) ============ */
    .pos-menu-grid [data-testid="stHorizontalBlock"] {
        display: grid !important;
        grid-template-columns: repeat(3, 1fr) !important;
        gap: 10px !important;
        width: 100% !important;
    }
    @media (max-width: 480px) {
        .pos-menu-grid [data-testid="stHorizontalBlock"] {
            grid-template-columns: repeat(3, 1fr) !important;
            gap: 8px !important;
        }
        .pos-menu-grid [data-testid="stHorizontalBlock"] button[kind="secondary"] {
            min-height: 75px !important;
            font-size: 28px !important;
            border-radius: 14px !important;
        }
    }
    .pos-menu-grid [data-testid="stHorizontalBlock"] > [data-testid="column"] {
        width: auto !important; min-width: 0 !important;
        max-width: none !important; flex: none !important;
        padding: 0 !important;
    }
    .pos-menu-grid [data-testid="stHorizontalBlock"] button[kind="secondary"] {
        width: 100% !important;
        min-height: 90px !important;
        border-radius: 18px !important;
        border: 1px solid rgba(0,0,0,0.04) !important;
        background: white !important;
        box-shadow: 0 2px 12px rgba(0,0,0,0.06) !important;
        font-size: 36px !important;
        padding: 12px 4px 6px !important;
        line-height: 1 !important;
        transition: all 0.15s ease !important;
    }
    .pos-menu-grid [data-testid="stHorizontalBlock"] button[kind="secondary"]:hover {
        transform: translateY(-2px) !important;
        box-shadow: 0 6px 24px rgba(0,0,0,0.12) !important;
    }
    .pos-menu-grid [data-testid="stHorizontalBlock"] button[kind="secondary"]:active {
        transform: scale(0.96) !important;
    }
    .pos-menu-label {
        text-align: center;
        font-size: 13px;
        font-weight: 700;
        color: #1e293b;
        margin: 2px 0 10px;
        line-height: 1.25;
    }
    .pos-menu-label-logout { color: #dc2626 !important; }

    /* Header gradient */
    .header-gradient {
        background: linear-gradient(135deg, #1e3a5f 0%, #2563eb 100%);
        color: white;
        padding: 2rem;
        border-radius: 0;
        margin: -1rem -1rem 2rem -1rem;
        text-align: center;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }

    .header-gradient h1 {
        margin: 0;
        font-size: 2rem;
        font-weight: 700;
    }

    .header-gradient p {
        margin: 0.5rem 0 0 0;
        font-size: 0.9rem;
        opacity: 0.9;
    }

    /* Stat cards */
    .stat-card {
        background: white;
        border-radius: 16px;
        padding: 1.5rem;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.12);
        border-left: 4px solid #2563eb;
    }

    .stat-card h3 {
        margin: 0 0 0.5rem 0;
        font-size: 0.9rem;
        color: #64748b;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }

    .stat-card .number {
        font-size: 2rem;
        font-weight: 700;
        color: #1e3a5f;
        margin: 0;
    }

    .stat-card.primary { border-left-color: #2563eb; }
    .stat-card.success { border-left-color: #10b981; }
    .stat-card.warning { border-left-color: #f59e0b; }
    .stat-card.danger { border-left-color: #ef4444; }

    /* Cards */
    .card {
        background: white;
        border-radius: 12px;
        padding: 1.5rem;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.12);
    }

    .card h2 {
        margin-top: 0;
        color: #1e3a5f;
        font-size: 1.5rem;
    }

    /* Buttons */
    .stButton > button {
        border-radius: 8px;
        font-weight: 600;
        padding: 0.75rem 1.5rem;
        border: none;
        transition: all 0.3s ease;
    }

    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    }

    /* Tables */
    .stDataFrame {
        border-radius: 12px;
        overflow: hidden;
    }

    /* Input styling */
    .stTextInput input,
    .stNumberInput input,
    .stSelectbox select {
        border-radius: 8px;
        border: 1px solid #e2e8f0;
    }

    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 0.5rem;
        border-bottom: 2px solid #e2e8f0;
    }

    .stTabs [aria-selected="true"] {
        border-bottom: 3px solid #2563eb;
        color: #2563eb;
    }

    /* Cart styling */
    .cart-item {
        background: white;
        padding: 1rem;
        border-radius: 8px;
        margin-bottom: 0.5rem;
        border-left: 3px solid #2563eb;
    }

    /* Receipt */
    .receipt {
        background: white;
        padding: 2rem;
        border-radius: 12px;
        font-family: 'Courier New', monospace;
        text-align: center;
        max-width: 400px;
        margin: 0 auto;
    }

    .receipt-header {
        border-bottom: 2px dashed #000;
        padding-bottom: 1rem;
        margin-bottom: 1rem;
    }

    .receipt-items {
        border-bottom: 2px dashed #000;
        padding: 1rem 0;
        margin: 1rem 0;
        text-align: left;
    }

    .receipt-item {
        display: flex;
        justify-content: space-between;
        font-size: 0.85rem;
        margin-bottom: 0.5rem;
    }

    .receipt-total {
        font-size: 1.2rem;
        font-weight: bold;
        margin: 1rem 0;
    }

    /* Mobile responsive */
    @media (max-width: 768px) {
        .header-gradient {
            padding: 1rem;
            margin: -1rem -1rem 1rem -1rem;
        }

        .header-gradient h1 {
            font-size: 1.5rem;
        }

        .stat-card {
            margin-bottom: 1rem;
        }
    }

    /* Scrollbar styling */
    ::-webkit-scrollbar {
        width: 8px;
        height: 8px;
    }

    ::-webkit-scrollbar-track {
        background: #f1f5f9;
    }

    ::-webkit-scrollbar-thumb {
        background: #cbd5e1;
        border-radius: 4px;
    }

    ::-webkit-scrollbar-thumb:hover {
        background: #94a3b8;
    }
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def generate_barcode_image(barcode_value: str) -> Image.Image:
    """Generate barcode image from value"""
    try:
        barcode_format = bc.get_barcode_class('code128')
        barcode_instance = barcode_format(barcode_value, writer=ImageWriter())
        buffer = BytesIO()
        barcode_instance.write(buffer, options={'module_height': 15, 'module_width': 0.5})
        buffer.seek(0)
        return Image.open(buffer)
    except:
        return None

def generate_sale_number() -> str:
    """Generate unique sale number: POS-YYYYMMDD-XXXX"""
    date_str = datetime.now().strftime("%Y%m%d")
    try:
        result = supabase.table("pos_sales").select("id").execute()
        count = len(result.data) if result.data else 0
        seq_num = str(count + 1).zfill(4)
        return f"POS-{date_str}-{seq_num}"
    except:
        return f"POS-{date_str}-0001"

def generate_unique_barcode() -> str:
    """Generate unique product barcode: BS-XXXXXX"""
    try:
        result = supabase.table("pos_products").select("id").execute()
        count = len(result.data) if result.data else 0
        num = str(count + 1).zfill(6)
        return f"BS-{num}"
    except:
        return "BS-000001"

@st.cache_data(ttl=30)
def fetch_products():
    """Fetch all products from database"""
    try:
        result = supabase.table("pos_products").select("*").order("created_at", desc=True).execute()
        return result.data if result.data else []
    except Exception as e:
        st.error(f"ข้อผิดพลาดในการดึงข้อมูลสินค้า: {str(e)}")
        return []

@st.cache_data(ttl=30)
def fetch_sales():
    """Fetch all sales from database"""
    try:
        result = supabase.table("pos_sales").select("*").order("created_at", desc=True).execute()
        return result.data if result.data else []
    except Exception as e:
        st.error(f"ข้อผิดพลาดในการดึงข้อมูลการขาย: {str(e)}")
        return []

@st.cache_data(ttl=60)
def fetch_customers():
    """Fetch all customers from database"""
    try:
        result = supabase.table("pos_customers").select("*").order("created_at", desc=True).execute()
        return result.data if result.data else []
    except Exception as e:
        st.error(f"ข้อผิดพลาดในการดึงข้อมูลลูกค้า: {str(e)}")
        return []

def clear_cache():
    """Clear all cached data"""
    st.cache_data.clear()

def format_currency(value: float) -> str:
    """Format number as Thai currency"""
    return f"฿{value:,.2f}"

def parse_thai_float(value):
    """Parse float value handling Thai format"""
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0

# ============================================================================
# SESSION STATE INITIALIZATION
# ============================================================================

if "page" not in st.session_state:
    st.session_state.page = "home"

if "cart" not in st.session_state:
    st.session_state.cart = []

if "camera_enabled" not in st.session_state:
    st.session_state.camera_enabled = False

if "selected_customer" not in st.session_state:
    st.session_state.selected_customer = None

# ============================================================================
# DASHBOARD PAGE
# ============================================================================

def page_dashboard():
    """Dashboard with KPIs and charts"""

    # Header
    st.markdown("""
    <div class="header-gradient">
        <h1>📊 แดชบอร์ด</h1>
        <p>ยินดีต้อนรับเข้าสู่ร้านบุญสุขอิเล็กทรอนิกส์</p>
    </div>
    """, unsafe_allow_html=True)

    # Get current date info
    today = datetime.now().date()
    month_start = datetime(today.year, today.month, 1).date()

    sales_data = fetch_sales()
    products_data = fetch_products()

    # Calculate stats
    today_sales = [s for s in sales_data if datetime.fromisoformat(s["created_at"][:10]).date() == today]
    month_sales = [s for s in sales_data if datetime.fromisoformat(s["created_at"][:10]).date() >= month_start]

    today_total = sum(float(s.get("total", 0)) for s in today_sales)
    month_total = sum(float(s.get("total", 0)) for s in month_sales)
    total_products = len(products_data)
    low_stock = len([p for p in products_data if int(p.get("stock_qty", 0)) < 10])

    # Stat Cards
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown(f"""
        <div class="stat-card primary">
            <h3>ยอดขายวันนี้</h3>
            <p class="number">{format_currency(today_total)}</p>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown(f"""
        <div class="stat-card success">
            <h3>ยอดขายเดือนนี้</h3>
            <p class="number">{format_currency(month_total)}</p>
        </div>
        """, unsafe_allow_html=True)

    with col3:
        st.markdown(f"""
        <div class="stat-card warning">
            <h3>จำนวนสินค้า</h3>
            <p class="number">{total_products}</p>
        </div>
        """, unsafe_allow_html=True)

    with col4:
        st.markdown(f"""
        <div class="stat-card danger">
            <h3>สินค้าใกล้หมด</h3>
            <p class="number">{low_stock}</p>
        </div>
        """, unsafe_allow_html=True)

    # Charts
    col1, col2 = st.columns(2)

    # Daily sales chart
    with col1:
        st.markdown("<div class='card'><h2>ยอดขายรายวัน (30 วันที่ผ่านมา)</h2>", unsafe_allow_html=True)

        last_30_days = [today - timedelta(days=i) for i in range(29, -1, -1)]
        daily_data = []

        for day in last_30_days:
            day_sales = [s for s in sales_data if datetime.fromisoformat(s["created_at"][:10]).date() == day]
            day_total = sum(float(s.get("total", 0)) for s in day_sales)
            daily_data.append({"date": day.strftime("%d/%m"), "total": day_total})

        if daily_data:
            df_daily = pd.DataFrame(daily_data)
            fig = px.bar(df_daily, x="date", y="total",
                        title=None,
                        labels={"date": "วันที่", "total": "ยอดขาย (บาท)"},
                        color_discrete_sequence=["#2563eb"])
            fig.update_layout(xaxis_tickangle=-45, height=300, margin=dict(b=50))
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("</div>", unsafe_allow_html=True)

    # Top products pie chart
    with col2:
        st.markdown("<div class='card'><h2>สินค้าขายดี Top 10</h2>", unsafe_allow_html=True)

        product_sales = {}
        for sale in sales_data:
            try:
                items = json.loads(sale.get("items_json", "[]"))
                for item in items:
                    product_name = item.get("name", "ไม่ระบุ")
                    qty = int(item.get("qty", 0))
                    product_sales[product_name] = product_sales.get(product_name, 0) + qty
            except:
                pass

        if product_sales:
            top_products = sorted(product_sales.items(), key=lambda x: x[1], reverse=True)[:10]
            names = [p[0][:15] for p in top_products]
            quantities = [p[1] for p in top_products]

            fig = px.pie(values=quantities, names=names,
                        title=None,
                        color_discrete_sequence=px.colors.sequential.Blues_r)
            fig.update_layout(height=300)
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("</div>", unsafe_allow_html=True)

    # Recent sales
    st.markdown("<div class='card'><h2>การขายล่าสุด</h2>", unsafe_allow_html=True)

    if sales_data:
        recent_sales = sales_data[:10]
        sales_display = []

        for sale in recent_sales:
            try:
                items = json.loads(sale.get("items_json", "[]"))
                item_count = len(items)
                sales_display.append({
                    "เลขที่ใบเสร็จ": sale.get("sale_no", "-"),
                    "วันที่": sale.get("created_at", "")[:10],
                    "จำนวนสินค้า": item_count,
                    "ยอดรวม": format_currency(float(sale.get("total", 0))),
                    "วิธีชำระ": sale.get("payment_method", "-"),
                    "แคชเชียร์": sale.get("cashier", "-")
                })
            except:
                pass

        st.dataframe(pd.DataFrame(sales_display), use_container_width=True, hide_index=True)
    else:
        st.info("ยังไม่มีการขายในระบบ")

    st.markdown("</div>", unsafe_allow_html=True)

# ============================================================================
# POS - POINT OF SALE PAGE
# ============================================================================

def page_pos():
    """POS - Checkout and sales"""

    st.markdown("""
    <div class="header-gradient">
        <h1>🛒 ระบบขายสินค้า</h1>
        <p>สแกนหรือค้นหาสินค้าเพื่อเพิ่มลงตะกร้า</p>
    </div>
    """, unsafe_allow_html=True)

    col_main, col_cart = st.columns([2, 1])

    with col_main:
        st.markdown("<div class='card'>", unsafe_allow_html=True)

        # Search & Filter
        col_search, col_filter = st.columns([2, 1])
        with col_search:
            search_term = st.text_input("🔍 ค้นหาสินค้า (ชื่อ/บาร์โค้ด)", key="pos_search")
        with col_filter:
            selected_category = st.selectbox("หมวดหมู่", ["ทั้งหมด"] + POS_CATEGORIES, key="pos_category")

        products = fetch_products()

        # Filter products
        filtered_products = products
        if search_term:
            search_lower = search_term.lower()
            filtered_products = [p for p in filtered_products
                               if search_lower in p.get("name", "").lower()
                               or search_lower in p.get("barcode", "").lower()]

        if selected_category != "ทั้งหมด":
            filtered_products = [p for p in filtered_products if p.get("category") == selected_category]

        # Product grid
        if filtered_products:
            cols = st.columns(3)
            for idx, product in enumerate(filtered_products):
                with cols[idx % 3]:
                    st.markdown(f"""
                    <div class="card" style="height: 100%;">
                        <h4 style="margin-top: 0;">{product.get('name', 'ไม่ระบุ')}</h4>
                        <p><strong>บาร์โค้ด:</strong> {product.get('barcode', '-')}</p>
                        <p><strong>ราคา:</strong> {format_currency(float(product.get('price', 0)))}</p>
                        <p><strong>คงเหลือ:</strong> {product.get('stock_qty', 0)} {product.get('unit', 'หน่วย')}</p>
                    </div>
                    """, unsafe_allow_html=True)

                    if st.button("เพิ่มลงตะกร้า", key=f"add_{product['id']}", use_container_width=True):
                        # Add to cart
                        existing = next((item for item in st.session_state.cart if item["id"] == product["id"]), None)
                        if existing:
                            existing["qty"] += 1
                        else:
                            st.session_state.cart.append({
                                "id": product["id"],
                                "barcode": product.get("barcode", ""),
                                "name": product.get("name", ""),
                                "price": float(product.get("price", 0)),
                                "qty": 1,
                                "unit": product.get("unit", "หน่วย")
                            })
                        st.success(f"เพิ่ม {product.get('name', '')} ลงตะกร้าแล้ว")
                        time.sleep(0.5)
                        st.rerun()
        else:
            st.info("ไม่พบสินค้า")

        st.markdown("</div>", unsafe_allow_html=True)

    # Shopping Cart Sidebar
    with col_cart:
        st.markdown("<div class='card'><h2>ตะกร้าสินค้า</h2>", unsafe_allow_html=True)

        if st.session_state.cart:
            # Cart items
            for idx, item in enumerate(st.session_state.cart):
                st.markdown(f"""
                <div class="cart-item">
                    <strong>{item['name']}</strong><br>
                    {format_currency(item['price'])} x {item['qty']}
                </div>
                """, unsafe_allow_html=True)

                col_qty, col_del = st.columns([3, 1])
                with col_qty:
                    new_qty = st.number_input(f"จำนวน", value=item["qty"], min_value=1,
                                            key=f"qty_{idx}", label_visibility="collapsed")
                    if new_qty != item["qty"]:
                        st.session_state.cart[idx]["qty"] = new_qty
                        st.rerun()

                with col_del:
                    if st.button("🗑️", key=f"del_{idx}"):
                        st.session_state.cart.pop(idx)
                        st.rerun()

            # Calculate totals
            subtotal = sum(item["price"] * item["qty"] for item in st.session_state.cart)

            st.divider()

            discount = st.number_input("ส่วนลด (บาท)", min_value=0.0, value=0.0, step=100.0)
            total = subtotal - discount

            st.markdown(f"""
            <div style="background: #f0f9ff; padding: 1rem; border-radius: 8px; margin: 1rem 0;">
                <p style="margin: 0.5rem 0;">ยอดรวม: <strong>{format_currency(subtotal)}</strong></p>
                <p style="margin: 0.5rem 0;">ส่วนลด: <strong>{format_currency(discount)}</strong></p>
                <p style="margin: 0.5rem 0; font-size: 1.2rem; color: #2563eb;">
                    รวมทั้งสิ้น: <strong>{format_currency(total)}</strong>
                </p>
            </div>
            """, unsafe_allow_html=True)

            # Payment method
            payment_method = st.selectbox("วิธีชำระเงิน", PAYMENT_METHODS)

            # Cash amount (for cash payment)
            if payment_method == "เงินสด":
                cash_amount = st.number_input("จำนวนเงินสดที่รับ", min_value=total, value=total, step=100.0)
                change = cash_amount - total
                st.info(f"เงินทอน: {format_currency(change)}")

            # Cashier name
            cashier_name = st.text_input("ชื่อแคชเชียร์", value="Admin")

            # Customer selection
            customers = fetch_customers()
            customer_names = ["ลูกค้าทั่วไป"] + [c.get("name", "") for c in customers]
            selected_customer = st.selectbox("ลูกค้า", customer_names)

            if st.button("✅ ชำระเงิน", use_container_width=True, type="primary"):
                # Save sale
                try:
                    items_json = json.dumps([{
                        "id": item["id"],
                        "barcode": item["barcode"],
                        "name": item["name"],
                        "price": item["price"],
                        "qty": item["qty"],
                        "unit": item["unit"],
                        "subtotal": item["price"] * item["qty"]
                    } for item in st.session_state.cart])

                    sale_data = {
                        "sale_no": generate_sale_number(),
                        "items_json": items_json,
                        "subtotal": subtotal,
                        "discount": discount,
                        "total": total,
                        "payment_method": payment_method,
                        "cashier": cashier_name,
                        "customer_name": selected_customer,
                        "created_at": datetime.now().isoformat()
                    }

                    result = supabase.table("pos_sales").insert(sale_data).execute()

                    # Update stock
                    for item in st.session_state.cart:
                        product = next((p for p in fetch_products() if p["id"] == item["id"]), None)
                        if product:
                            new_stock = int(product.get("stock_qty", 0)) - item["qty"]
                            supabase.table("pos_products").update({
                                "stock_qty": max(0, new_stock)
                            }).eq("id", item["id"]).execute()

                    # Clear cache and cart
                    clear_cache()
                    st.session_state.cart = []

                    # Show receipt
                    st.success("✅ บันทึกการขายสำเร็จ!")

                    # Show receipt modal
                    st.markdown("<div class='receipt'>", unsafe_allow_html=True)
                    st.markdown(f"""
                    <div class="receipt-header">
                        <h2 style="margin: 0;">{STORE_NAME}</h2>
                        <p style="margin: 0.25rem 0; font-size: 0.9rem;">โทร. {STORE_PHONE}</p>
                        <p style="margin: 0.25rem 0; font-size: 0.85rem;">{STORE_ADDRESS}</p>
                        <p style="margin: 0.25rem 0; font-size: 0.85rem;">เลขประจำตัวผู้เสียภาษี: {TAX_ID}</p>
                    </div>
                    """, unsafe_allow_html=True)

                    st.markdown(f"""
                    <p style="font-size: 0.9rem; margin: 0.5rem 0;">
                        <strong>เลขที่ใบเสร็จ:</strong> {sale_data['sale_no']}<br>
                        <strong>วันที่:</strong> {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}<br>
                        <strong>แคชเชียร์:</strong> {cashier_name}
                    </p>
                    """, unsafe_allow_html=True)

                    st.markdown("<div class='receipt-items'>", unsafe_allow_html=True)
                    for item in st.session_state.cart:
                        st.markdown(f"""
                        <div class="receipt-item">
                            <span>{item['name']}</span>
                            <span>{format_currency(item['price'] * item['qty'])}</span>
                        </div>
                        """, unsafe_allow_html=True)
                    st.markdown("</div>", unsafe_allow_html=True)

                    st.markdown(f"""
                    <div class="receipt-total">
                        {format_currency(total)}
                    </div>
                    """, unsafe_allow_html=True)

                    if payment_method == "เงินสด" and 'cash_amount' in locals():
                        st.markdown(f"""
                        <p style="font-size: 0.9rem;">
                            เงินสด: {format_currency(cash_amount)}<br>
                            เงินทอน: {format_currency(change)}
                        </p>
                        """, unsafe_allow_html=True)

                    st.markdown("""
                    <p style="font-size: 0.85rem; margin-top: 1rem;">
                        ขอบคุณที่ใช้บริการ<br>
                        <em>Thank you for your purchase</em>
                    </p>
                    """, unsafe_allow_html=True)

                    st.markdown("</div>", unsafe_allow_html=True)

                    # Print button
                    col1, col2 = st.columns(2)
                    with col1:
                        st.button("🖨️ พิมพ์ใบเสร็จ", use_container_width=True)
                    with col2:
                        if st.button("➕ ขายต่อ", use_container_width=True):
                            st.rerun()

                    time.sleep(2)
                    st.rerun()

                except Exception as e:
                    st.error(f"ข้อผิดพลาด: {str(e)}")

        else:
            st.info("ตะกร้างานว่าง")

        st.markdown("</div>", unsafe_allow_html=True)

# ============================================================================
# PRODUCT MANAGEMENT PAGE
# ============================================================================

def page_product_management():
    """Product management with multiple tabs"""

    st.markdown("""
    <div class="header-gradient">
        <h1>📦 จัดการสินค้า</h1>
        <p>บริหารจัดการสินค้าในระบบ</p>
    </div>
    """, unsafe_allow_html=True)

    tab1, tab2, tab3, tab4 = st.tabs(["👀 ดูสินค้า", "➕ เพิ่มสินค้า", "📥 นำเข้า Excel", "🏷️ ปริ้นบาร์โค้ด"])

    # TAB 1: View Products
    with tab1:
        st.markdown("<div class='card'>", unsafe_allow_html=True)

        col_search, col_category = st.columns([2, 1])
        with col_search:
            search = st.text_input("🔍 ค้นหาสินค้า", key="product_search")
        with col_category:
            category_filter = st.selectbox("หมวดหมู่", ["ทั้งหมด"] + POS_CATEGORIES, key="product_category")

        products = fetch_products()

        # Filter
        if search:
            products = [p for p in products if search.lower() in p.get("name", "").lower()
                       or search.lower() in p.get("barcode", "").lower()]
        if category_filter != "ทั้งหมด":
            products = [p for p in products if p.get("category") == category_filter]

        if products:
            product_display = []
            for p in products:
                product_display.append({
                    "บาร์โค้ด": p.get("barcode", "-"),
                    "ชื่อสินค้า": p.get("name", "-"),
                    "หมวดหมู่": p.get("category", "-"),
                    "ราคาขาย": format_currency(float(p.get("price", 0))),
                    "ต้นทุน": format_currency(float(p.get("cost", 0))),
                    "คงเหลือ": f"{p.get('stock_qty', 0)} {p.get('unit', 'หน่วย')}"
                })

            st.dataframe(pd.DataFrame(product_display), use_container_width=True, hide_index=True)
        else:
            st.info("ไม่พบสินค้า")

        st.markdown("</div>", unsafe_allow_html=True)

    # TAB 2: Add Product
    with tab2:
        st.markdown("<div class='card'>", unsafe_allow_html=True)

        col1, col2 = st.columns(2)

        with col1:
            product_name = st.text_input("ชื่อสินค้า *")
            category = st.selectbox("หมวดหมู่ *", POS_CATEGORIES, key="add_category")
            price = st.number_input("ราคาขาย (บาท) *", min_value=0.0, step=100.0)

        with col2:
            barcode = st.text_input("บาร์โค้ด (ถ้าเว้นไว้จะสร้างอัตโนมัติ)", value="")
            cost = st.number_input("ต้นทุน (บาท) *", min_value=0.0, step=100.0)
            unit = st.text_input("หน่วย", value="ชิ้น")

        stock_qty = st.number_input("จำนวนคงเหลือ *", min_value=0, step=1)

        # Generate barcode if empty
        if not barcode:
            barcode = generate_unique_barcode()

        # Show barcode preview
        if barcode:
            col_preview, col_empty = st.columns([1, 2])
            with col_preview:
                try:
                    barcode_img = generate_barcode_image(barcode)
                    if barcode_img:
                        st.image(barcode_img, caption=barcode, use_container_width=True)
                except:
                    st.info("ไม่สามารถสร้างรูปบาร์โค้ดได้")

        if st.button("💾 บันทึกสินค้า", use_container_width=True, type="primary"):
            if product_name and category and price > 0 and cost >= 0 and stock_qty >= 0:
                try:
                    product_data = {
                        "barcode": barcode,
                        "name": product_name,
                        "category": category,
                        "price": price,
                        "cost": cost,
                        "stock_qty": stock_qty,
                        "unit": unit,
                        "created_at": datetime.now().isoformat()
                    }

                    supabase.table("pos_products").insert(product_data).execute()
                    clear_cache()
                    st.success(f"✅ บันทึก {product_name} สำเร็จ!")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"ข้อผิดพลาด: {str(e)}")
            else:
                st.warning("⚠️ กรุณากรอกข้อมูลที่จำเป็นให้ครบถ้วน")

        st.markdown("</div>", unsafe_allow_html=True)

    # TAB 3: Import Excel
    with tab3:
        st.markdown("<div class='card'>", unsafe_allow_html=True)

        uploaded_file = st.file_uploader("📤 อัพโหลด Excel/CSV", type=["xlsx", "xls", "csv"])

        if uploaded_file:
            try:
                if uploaded_file.type == "text/csv":
                    df = pd.read_csv(uploaded_file)
                else:
                    df = pd.read_excel(uploaded_file)

                st.info(f"อ่านได้ {len(df)} แถว")

                # Auto-map Thai column names
                column_mapping = {}
                thai_to_english = {
                    "ชื่อสินค้า": "name",
                    "ชื่อ": "name",
                    "สินค้า": "name",
                    "Produce Name": "name",
                    "บาโค้ด": "barcode",
                    "บาร์โค้ด": "barcode",
                    "ราคาขาย": "price",
                    "ราคา": "price",
                    "ต้นทุน": "cost",
                    "ทุน": "cost",
                    "จำนวน": "stock_qty",
                    "สต๊อก": "stock_qty",
                    "คงเหลือ": "stock_qty",
                    "หมวดหมู่": "category",
                    "ประเภท": "category",
                    "หน่วย": "unit"
                }

                for col in df.columns:
                    for thai, eng in thai_to_english.items():
                        if col.strip() == thai or col.strip() == thai.strip():
                            column_mapping[col] = eng
                            break

                # Rename columns
                df_processed = df.rename(columns=column_mapping)

                # Auto-generate barcode if missing
                if "barcode" not in df_processed.columns:
                    df_processed["barcode"] = [generate_unique_barcode() for _ in range(len(df_processed))]
                else:
                    df_processed["barcode"] = df_processed["barcode"].fillna("")
                    for i, bc_val in enumerate(df_processed["barcode"]):
                        if not bc_val or bc_val == "":
                            df_processed.at[i, "barcode"] = generate_unique_barcode()

                # Fill defaults
                df_processed["category"] = df_processed.get("category", "อื่นๆ")
                df_processed["unit"] = df_processed.get("unit", "ชิ้น")
                df_processed["created_at"] = datetime.now().isoformat()

                st.write("ตัวอย่างข้อมูล:")
                st.dataframe(df_processed.head(), use_container_width=True)

                if st.button("✅ นำเข้าข้อมูล", use_container_width=True, type="primary"):
                    try:
                        products_to_insert = []
                        for _, row in df_processed.iterrows():
                            products_to_insert.append({
                                "barcode": str(row.get("barcode", "")),
                                "name": str(row.get("name", "ไม่ระบุ")),
                                "category": str(row.get("category", "อื่นๆ")),
                                "price": float(row.get("price", 0)),
                                "cost": float(row.get("cost", 0)),
                                "stock_qty": int(row.get("stock_qty", 0)),
                                "unit": str(row.get("unit", "ชิ้น")),
                                "created_at": datetime.now().isoformat()
                            })

                        supabase.table("pos_products").insert(products_to_insert).execute()
                        clear_cache()
                        st.success(f"✅ นำเข้า {len(products_to_insert)} สินค้าสำเร็จ!")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"ข้อผิดพลาด: {str(e)}")

            except Exception as e:
                st.error(f"ข้อผิดพลาดในการอ่านไฟล์: {str(e)}")

        st.markdown("</div>", unsafe_allow_html=True)

    # TAB 4: Print Barcodes
    with tab4:
        st.markdown("<div class='card'>", unsafe_allow_html=True)

        products = fetch_products()
        product_options = {p.get("name", ""): p["id"] for p in products}

        selected_products = st.multiselect("เลือกสินค้าเพื่อปริ้นบาร์โค้ด", list(product_options.keys()))

        if selected_products:
            col1, col2 = st.columns(2)
            with col1:
                label_size = st.selectbox("ขนาดป้าย", ["50x30mm", "40x25mm", "70x40mm"])
            with col2:
                copies = st.number_input("จำนวนชุดที่ต้องพิมพ์", min_value=1, value=1)

            if st.button("🖨️ ปริ้นบาร์โค้ด", use_container_width=True, type="primary"):
                html_content = "<html><head><meta charset='utf-8'></head><body>"

                for product_name in selected_products:
                    product_id = product_options[product_name]
                    product = next((p for p in products if p["id"] == product_id), None)

                    if product:
                        barcode = product.get("barcode", "")
                        try:
                            barcode_img = generate_barcode_image(barcode)
                            if barcode_img:
                                img_buffer = BytesIO()
                                barcode_img.save(img_buffer, format="PNG")
                                img_buffer.seek(0)

                                for _ in range(copies):
                                    html_content += f"""
                                    <div style="margin: 10px; text-align: center;">
                                        <img src="data:image/png;base64,{img_buffer.getvalue()}" width="150">
                                        <p>{product.get('name', '')}</p>
                                        <p style="font-weight: bold;">{format_currency(float(product.get('price', 0)))}</p>
                                    </div>
                                    """
                        except:
                            pass

                html_content += "</body></html>"

                st.success("✅ พร้อมพิมพ์")
                st.info("ใช้ Ctrl+P หรือ Cmd+P เพื่อพิมพ์")

        st.markdown("</div>", unsafe_allow_html=True)

# ============================================================================
# SALES HISTORY PAGE
# ============================================================================

def page_sales_history():
    """Sales history and reports"""

    st.markdown("""
    <div class="header-gradient">
        <h1>📋 ประวัติการขาย</h1>
        <p>ดูประวัติการขายและรายงานการชำระเงิน</p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<div class='card'>", unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)
    with col1:
        start_date = st.date_input("ตั้งแต่วันที่", value=datetime.now().date() - timedelta(days=30))
    with col2:
        end_date = st.date_input("ถึงวันที่", value=datetime.now().date())
    with col3:
        search_sale = st.text_input("ค้นหาเลขที่ใบเสร็จ")

    sales_data = fetch_sales()

    # Filter by date
    filtered_sales = [s for s in sales_data
                     if datetime.fromisoformat(s["created_at"][:10]).date() >= start_date
                     and datetime.fromisoformat(s["created_at"][:10]).date() <= end_date]

    # Filter by search
    if search_sale:
        filtered_sales = [s for s in filtered_sales if search_sale in s.get("sale_no", "")]

    if filtered_sales:
        sales_display = []
        for sale in filtered_sales:
            try:
                items = json.loads(sale.get("items_json", "[]"))
                sales_display.append({
                    "เลขที่ใบเสร็จ": sale.get("sale_no", "-"),
                    "วันที่": sale.get("created_at", "")[:10],
                    "เวลา": sale.get("created_at", "")[11:19],
                    "จำนวนสินค้า": len(items),
                    "ยอดรวม": format_currency(float(sale.get("total", 0))),
                    "วิธีชำระ": sale.get("payment_method", "-"),
                    "แคชเชียร์": sale.get("cashier", "-")
                })
            except:
                pass

        st.dataframe(pd.DataFrame(sales_display), use_container_width=True, hide_index=True)

        # Stats
        st.divider()
        col1, col2, col3, col4 = st.columns(4)

        total_sales_count = len(filtered_sales)
        total_revenue = sum(float(s.get("total", 0)) for s in filtered_sales)
        total_discount = sum(float(s.get("discount", 0)) for s in filtered_sales)
        total_items = sum(len(json.loads(s.get("items_json", "[]"))) for s in filtered_sales)

        with col1:
            st.metric("จำนวนใบเสร็จ", total_sales_count)
        with col2:
            st.metric("ยอดขายรวม", format_currency(total_revenue))
        with col3:
            st.metric("ส่วนลดรวม", format_currency(total_discount))
        with col4:
            st.metric("จำนวนสินค้าขาย", total_items)
    else:
        st.info("ไม่พบข้อมูลการขายในช่วงเวลาที่เลือก")

    st.markdown("</div>", unsafe_allow_html=True)

# ============================================================================
# CUSTOMER PAGE
# ============================================================================

def page_customers():
    """Customer management"""

    st.markdown("""
    <div class="header-gradient">
        <h1>👥 ลูกค้า</h1>
        <p>บริหารจัดการข้อมูลลูกค้า</p>
    </div>
    """, unsafe_allow_html=True)

    tab1, tab2 = st.tabs(["📋 รายชื่อลูกค้า", "➕ เพิ่มลูกค้า"])

    with tab1:
        st.markdown("<div class='card'>", unsafe_allow_html=True)

        search = st.text_input("🔍 ค้นหาลูกค้า")

        customers = fetch_customers()

        if search:
            customers = [c for c in customers if search.lower() in c.get("name", "").lower()
                        or search.lower() in c.get("phone", "").lower()]

        if customers:
            customer_display = []
            for c in customers:
                customer_display.append({
                    "ชื่อ": c.get("name", "-"),
                    "เบอร์โทร": c.get("phone", "-"),
                    "อีเมล": c.get("email", "-"),
                    "ที่อยู่": c.get("address", "-"),
                    "หมายเหตุ": c.get("notes", "-")[:30]
                })

            st.dataframe(pd.DataFrame(customer_display), use_container_width=True, hide_index=True)
        else:
            st.info("ไม่พบลูกค้า")

        st.markdown("</div>", unsafe_allow_html=True)

    with tab2:
        st.markdown("<div class='card'>", unsafe_allow_html=True)

        col1, col2 = st.columns(2)
        with col1:
            cust_name = st.text_input("ชื่อลูกค้า *")
            cust_phone = st.text_input("เบอร์โทร")
        with col2:
            cust_email = st.text_input("อีเมล")
            cust_address = st.text_input("ที่อยู่")

        cust_notes = st.text_area("หมายเหตุ")

        if st.button("💾 บันทึกลูกค้า", use_container_width=True, type="primary"):
            if cust_name:
                try:
                    customer_data = {
                        "name": cust_name,
                        "phone": cust_phone,
                        "email": cust_email,
                        "address": cust_address,
                        "notes": cust_notes,
                        "created_at": datetime.now().isoformat()
                    }

                    supabase.table("pos_customers").insert(customer_data).execute()
                    clear_cache()
                    st.success(f"✅ บันทึก {cust_name} สำเร็จ!")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"ข้อผิดพลาด: {str(e)}")
            else:
                st.warning("⚠️ กรุณากรอกชื่อลูกค้า")

        st.markdown("</div>", unsafe_allow_html=True)

# ============================================================================
# REPORTS PAGE
# ============================================================================

def page_reports():
    """Comprehensive reporting"""

    st.markdown("""
    <div class="header-gradient">
        <h1>📈 รายงาน</h1>
        <p>วิเคราะห์ข้อมูลการขายและสินค้า</p>
    </div>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    with col1:
        report_start = st.date_input("ตั้งแต่วันที่", value=datetime.now().date() - timedelta(days=30), key="report_start")
    with col2:
        report_end = st.date_input("ถึงวันที่", value=datetime.now().date(), key="report_end")

    tab1, tab2, tab3, tab4 = st.tabs(["💰 กำไร-ขาดทุน", "🏆 สินค้าขายดี", "📊 สรุปรายเดือน", "📉 สต๊อกต่ำ"])

    sales_data = fetch_sales()
    products_data = fetch_products()

    # Filter by date
    filtered_sales = [s for s in sales_data
                     if datetime.fromisoformat(s["created_at"][:10]).date() >= report_start
                     and datetime.fromisoformat(s["created_at"][:10]).date() <= report_end]

    # TAB 1: Profit & Loss
    with tab1:
        st.markdown("<div class='card'>", unsafe_allow_html=True)

        total_revenue = sum(float(s.get("total", 0)) for s in filtered_sales)

        total_cost = 0
        for sale in filtered_sales:
            try:
                items = json.loads(sale.get("items_json", "[]"))
                for item in items:
                    product = next((p for p in products_data if p.get("barcode") == item.get("barcode")), None)
                    if product:
                        cost = float(product.get("cost", 0))
                        qty = int(item.get("qty", 0))
                        total_cost += cost * qty
            except:
                pass

        profit = total_revenue - total_cost
        profit_margin = (profit / total_revenue * 100) if total_revenue > 0 else 0

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("รายได้รวม", format_currency(total_revenue))
        with col2:
            st.metric("ต้นทุนรวม", format_currency(total_cost))
        with col3:
            st.metric("กำไร/ขาดทุน", format_currency(profit), delta=f"{profit_margin:.1f}%")

        st.divider()
        st.subheader("วิเคราะห์รายวัน")

        daily_data = []
        for day in pd.date_range(report_start, report_end, freq='D'):
            day_sales = [s for s in filtered_sales if datetime.fromisoformat(s["created_at"][:10]).date() == day.date()]
            day_revenue = sum(float(s.get("total", 0)) for s in day_sales)
            day_cost = 0

            for sale in day_sales:
                try:
                    items = json.loads(sale.get("items_json", "[]"))
                    for item in items:
                        product = next((p for p in products_data if p.get("barcode") == item.get("barcode")), None)
                        if product:
                            cost = float(product.get("cost", 0))
                            qty = int(item.get("qty", 0))
                            day_cost += cost * qty
                except:
                    pass

            daily_data.append({
                "date": day.strftime("%d/%m"),
                "revenue": day_revenue,
                "cost": day_cost,
                "profit": day_revenue - day_cost
            })

        if daily_data:
            df_daily = pd.DataFrame(daily_data)
            fig = go.Figure()
            fig.add_trace(go.Bar(x=df_daily['date'], y=df_daily['revenue'], name='รายได้'))
            fig.add_trace(go.Bar(x=df_daily['date'], y=df_daily['cost'], name='ต้นทุน'))
            fig.add_trace(go.Scatter(x=df_daily['date'], y=df_daily['profit'], name='กำไร',
                                    yaxis='y2', line=dict(color='green', width=3)))
            fig.update_layout(
                yaxis=dict(title='บาท'),
                yaxis2=dict(title='กำไร (บาท)', overlaying='y', side='right'),
                hovermode='x unified',
                height=400
            )
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("</div>", unsafe_allow_html=True)

    # TAB 2: Top Products
    with tab2:
        st.markdown("<div class='card'>", unsafe_allow_html=True)

        product_sales = {}
        product_profit = {}

        for sale in filtered_sales:
            try:
                items = json.loads(sale.get("items_json", "[]"))
                for item in items:
                    product_name = item.get("name", "ไม่ระบุ")
                    qty = int(item.get("qty", 0))
                    price = float(item.get("price", 0))

                    product_sales[product_name] = product_sales.get(product_name, 0) + qty

                    product = next((p for p in products_data if p.get("barcode") == item.get("barcode")), None)
                    if product:
                        cost = float(product.get("cost", 0))
                        profit_per_item = (price - cost) * qty
                        product_profit[product_name] = product_profit.get(product_name, 0) + profit_per_item
            except:
                pass

        if product_sales:
            top_products = sorted(product_sales.items(), key=lambda x: x[1], reverse=True)[:10]
            names = [p[0][:20] for p in top_products]
            quantities = [p[1] for p in top_products]
            profits = [product_profit.get(p[0], 0) for p in top_products]

            fig = go.Figure()
            fig.add_trace(go.Bar(x=names, y=quantities, name='จำนวนขาย', yaxis='y'))
            fig.add_trace(go.Scatter(x=names, y=profits, name='กำไร', yaxis='y2',
                                    line=dict(color='green', width=3)))
            fig.update_layout(
                yaxis=dict(title='จำนวน'),
                yaxis2=dict(title='กำไร', overlaying='y', side='right'),
                height=400
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("ไม่มีข้อมูลการขาย")

        st.markdown("</div>", unsafe_allow_html=True)

    # TAB 3: Monthly Summary
    with tab3:
        st.markdown("<div class='card'>", unsafe_allow_html=True)

        # Get all sales for last 12 months
        all_sales = fetch_sales()

        monthly_data = {}
        for sale in all_sales:
            try:
                sale_date = datetime.fromisoformat(sale["created_at"][:10])
                month_key = sale_date.strftime("%Y-%m")
                total = float(sale.get("total", 0))

                if month_key not in monthly_data:
                    monthly_data[month_key] = 0
                monthly_data[month_key] += total
            except:
                pass

        if monthly_data:
            months = sorted(monthly_data.keys())
            revenues = [monthly_data[m] for m in months]

            fig = px.bar(x=months, y=revenues, labels={'x': 'เดือน', 'y': 'ยอดขาย (บาท)'},
                        title=None, color_discrete_sequence=['#2563eb'])
            fig.update_layout(height=400, xaxis_tickangle=-45)
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("</div>", unsafe_allow_html=True)

    # TAB 4: Low Stock
    with tab4:
        st.markdown("<div class='card'>", unsafe_allow_html=True)

        low_stock = [p for p in products_data if int(p.get("stock_qty", 0)) < 20]

        if low_stock:
            low_stock_display = []
            for p in low_stock:
                low_stock_display.append({
                    "บาร์โค้ด": p.get("barcode", "-"),
                    "ชื่อสินค้า": p.get("name", "-"),
                    "คงเหลือ": f"{p.get('stock_qty', 0)} {p.get('unit', 'หน่วย')}",
                    "ราคา": format_currency(float(p.get("price", 0)))
                })

            st.dataframe(pd.DataFrame(low_stock_display), use_container_width=True, hide_index=True)

            # Chart
            st.subheader("สินค้าใกล้หมดตามหมวดหมู่")

            category_low_stock = {}
            for p in low_stock:
                cat = p.get("category", "อื่นๆ")
                category_low_stock[cat] = category_low_stock.get(cat, 0) + 1

            if category_low_stock:
                fig = px.pie(values=list(category_low_stock.values()),
                            names=list(category_low_stock.keys()),
                            title=None)
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.success("✅ สินค้าทั้งหมดมีจำนวนเพียงพอ")

        st.markdown("</div>", unsafe_allow_html=True)

# ============================================================================
# BACK TO HOME BUTTON
# ============================================================================

def back_home():
    """แสดงปุ่มกลับหน้าหลัก"""
    if st.button("🏠 กลับหน้าหลัก", type="secondary"):
        st.session_state.page = "home"
        st.rerun()

# ============================================================================
# HOME PAGE — GRID MENU
# ============================================================================

def page_home():
    # Header with user info
    _role = st.session_state.get("role", "")
    _uname = st.session_state.get("username", "")
    _role_badge = "👑 ผู้ดูแลระบบ" if _role == "admin" else "👔 พนักงาน"
    st.markdown(f"""
    <div style="background: linear-gradient(135deg, #1e3a5f 0%, #2563eb 100%);
        color: white; padding: 1.5rem; border-radius: 16px; margin-bottom: 1.5rem; text-align: center;">
        <h1 style="margin: 0; font-size: 1.6rem;">🏪 {STORE_NAME}</h1>
        <p style="margin: 0.3rem 0 0; font-size: 0.9rem; opacity: 0.9;">ระบบ POS ขายสินค้า | {STORE_PHONE}</p>
        <p style="margin: 0.5rem 0 0; font-size: 0.8rem; opacity: 0.85;
            background: rgba(255,255,255,0.15); display: inline-block;
            padding: 3px 14px; border-radius: 20px;">{_role_badge} ({_uname})</p>
    </div>
    """, unsafe_allow_html=True)

    # Stat cards
    try:
        df_products = load_products()
        df_sales = load_sales()
        today = datetime.now().strftime("%Y-%m-%d")
        today_sales = 0
        month_sales = 0
        low_stock = 0
        if not df_sales.empty and "created_at" in df_sales.columns:
            df_sales["_date"] = pd.to_datetime(df_sales["created_at"], errors="coerce").dt.strftime("%Y-%m-%d")
            df_sales["_month"] = pd.to_datetime(df_sales["created_at"], errors="coerce").dt.to_period("M").astype(str)
            this_month = datetime.now().strftime("%Y-%m")
            today_sales = df_sales[df_sales["_date"] == today]["total"].sum()
            month_sales = df_sales[df_sales["_month"] == this_month]["total"].sum()
        if not df_products.empty and "stock_qty" in df_products.columns:
            low_stock = int((df_products["stock_qty"].fillna(0).astype(int) < 5).sum())
        n_products = len(df_products)
    except:
        today_sales = 0; month_sales = 0; n_products = 0; low_stock = 0

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"""<div style="background:white; border-radius:14px; padding:14px; border-left:4px solid #2563eb;
            box-shadow:0 1px 4px rgba(0,0,0,0.08); margin-bottom:10px;">
            <p style="margin:0; font-size:12px; color:#64748b; font-weight:600;">💰 ยอดขายวันนี้</p>
            <p style="margin:4px 0 0; font-size:22px; font-weight:800; color:#1e3a5f;">฿{today_sales:,.0f}</p>
        </div>""", unsafe_allow_html=True)
    with c2:
        st.markdown(f"""<div style="background:white; border-radius:14px; padding:14px; border-left:4px solid #10b981;
            box-shadow:0 1px 4px rgba(0,0,0,0.08); margin-bottom:10px;">
            <p style="margin:0; font-size:12px; color:#64748b; font-weight:600;">📊 ยอดขายเดือนนี้</p>
            <p style="margin:4px 0 0; font-size:22px; font-weight:800; color:#047857;">฿{month_sales:,.0f}</p>
        </div>""", unsafe_allow_html=True)
    c3, c4 = st.columns(2)
    with c3:
        st.markdown(f"""<div style="background:white; border-radius:14px; padding:14px; border-left:4px solid #f59e0b;
            box-shadow:0 1px 4px rgba(0,0,0,0.08); margin-bottom:10px;">
            <p style="margin:0; font-size:12px; color:#64748b; font-weight:600;">📦 สินค้าทั้งหมด</p>
            <p style="margin:4px 0 0; font-size:22px; font-weight:800; color:#92400e;">{n_products} รายการ</p>
        </div>""", unsafe_allow_html=True)
    with c4:
        st.markdown(f"""<div style="background:white; border-radius:14px; padding:14px; border-left:4px solid #ef4444;
            box-shadow:0 1px 4px rgba(0,0,0,0.08); margin-bottom:10px;">
            <p style="margin:0; font-size:12px; color:#64748b; font-weight:600;">⚠️ สินค้าใกล้หมด</p>
            <p style="margin:4px 0 0; font-size:22px; font-weight:800; color:#dc2626;">{low_stock} รายการ</p>
        </div>""", unsafe_allow_html=True)

    # Menu Grid
    st.markdown('<p style="font-size:14px; font-weight:700; color:#475569; margin:16px 0 10px; letter-spacing:0.3px;">📱 เมนูหลัก</p>', unsafe_allow_html=True)

    menu_items = [
        ("🛒", "POS ขาย", "pos"),
        ("📦", "จัดการสินค้า", "products"),
        ("📊", "แดชบอร์ด", "dashboard"),
        ("📋", "ประวัติขาย", "sales"),
        ("👥", "ลูกค้า", "customers"),
        ("📈", "รายงาน", "reports"),
        ("🚪", "ออกจากระบบ", "__LOGOUT__"),
    ]

    # Pad to multiple of 3
    _padded = list(menu_items)
    while len(_padded) % 3 != 0:
        _padded.append(None)

    st.markdown('<div class="pos-menu-grid">', unsafe_allow_html=True)
    for _rs in range(0, len(_padded), 3):
        _cols = st.columns(3)
        for _ci, _col in zip(range(3), _cols):
            _itm = _padded[_rs + _ci]
            with _col:
                if _itm is None:
                    st.empty()
                else:
                    _em, _lb, _key = _itm
                    _is_logout = (_key == "__LOGOUT__")
                    if st.button(_em, key=f"menu_{_key}", use_container_width=True):
                        if _is_logout:
                            st.session_state.logged_in = False
                            st.session_state.username = ""
                            st.session_state.role = ""
                            st.session_state.full_name = ""
                            st.session_state.page = "home"
                            try: del st.query_params["s"]
                            except: pass
                            _run_js('try{parent.localStorage.removeItem("pos_token")}catch(e){} try{localStorage.removeItem("pos_token")}catch(e){}')
                            st.rerun()
                        else:
                            st.session_state.page = _key
                            st.rerun()
                    _label_cls = "pos-menu-label" + (" pos-menu-label-logout" if _is_logout else "")
                    st.markdown(f'<p class="{_label_cls}">{_lb}</p>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    # Footer
    st.markdown(f"""<div style="text-align:center; margin-top:20px; padding:10px 0;
        border-top:1px solid #e2e8f0;">
        <p style="font-size:10px; color:#94a3b8; margin:0;">
            {STORE_NAME} • ☎ {STORE_PHONE} • POS v1.0
        </p>
        <p style="font-size:9px; color:#cbd5e1; margin:2px 0 0;">{STORE_ADDRESS}</p>
    </div>""", unsafe_allow_html=True)

# ============================================================================
# PAGE ROUTING (with login check)
# ============================================================================

check_login()

if not st.session_state.get("logged_in", False):
    login_page()
else:
    load_custom_css()
    if st.session_state.page == "home":
        page_home()
    elif st.session_state.page == "dashboard":
        back_home()
        page_dashboard()
    elif st.session_state.page == "pos":
        back_home()
        page_pos()
    elif st.session_state.page == "products":
        back_home()
        page_product_management()
    elif st.session_state.page == "sales":
        back_home()
        page_sales_history()
    elif st.session_state.page == "customers":
        back_home()
        page_customers()
    elif st.session_state.page == "reports":
        back_home()
        page_reports()
