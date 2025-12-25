import streamlit as st

# --- 🎨 配色方案 (Professional Dark) ---
COLORS = {
    "Background": "#0E1117",
    "Text": "#E6E6E6",
    "CardBg": "#161B22",
    "Border": "#30363D",
    # 语义色 - 更加柔和的莫兰迪色系/Material Design
    "Multimedia": "#4FC3F7",  # Light Blue
    "GeoTravel": "#81C784",  # Light Green
    "Knowledge": "#BA68C8",  # Light Purple
    "Personal": "#FF8A65",  # Deep Orange
    "Default": "#90A4AE",  # Blue Grey
    "Hub": "#FFD54F",  # Amber
    "Highlight": "#2979FF",  # Bright Blue for active elements
}


def inject_custom_css():
    st.markdown(
        f"""
    <style>
        /* 全局背景 */
        .stApp {{
            background-color: {COLORS['Background']};
            color: {COLORS['Text']};
        }}

        /* 去除 Streamlit 顶部 Padding，让空间利用率更高 */
        .block-container {{
            padding-top: 2rem;
        }}

        /* 侧边栏 */
        section[data-testid="stSidebar"] {{
            background-color: #0d1117;
            border-right: 1px solid {COLORS['Border']};
        }}

        /* 玻璃质感卡片 */
        .glass-card {{
            background-color: {COLORS['CardBg']};
            border: 1px solid {COLORS['Border']};
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 15px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.2);
        }}
        
        /* 关键：修复 HTML Timeline 的样式 */
        .step-container {{
            display: flex;
            align-items: flex-start;
            position: relative;
            padding-bottom: 25px;
            border-left: 2px solid {COLORS['Border']};
            margin-left: 10px;
            padding-left: 20px;
        }}
        .step-container:last-child {{
            border-left: 2px solid transparent;
        }}
        .step-icon {{
            position: absolute;
            left: -11px;
            top: 0;
            width: 20px;
            height: 20px;
            border-radius: 50%;
            background: {COLORS['Background']};
            border: 2px solid;
            box-shadow: 0 0 5px rgba(0,0,0,0.5);
            z-index: 10;
        }}
        .step-content {{
            background: #1F242C;
            padding: 12px 16px;
            border-radius: 8px;
            width: 100%;
            border: 1px solid {COLORS['Border']};
        }}
        .step-tag {{
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            opacity: 0.9;
            margin-bottom: 4px;
            font-weight: bold;
        }}
        .step-title {{
            font-size: 1.1rem;
            font-weight: 600;
            color: #fff;
        }}
        .app-badge {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 0.7em;
            margin-left: 8px;
            background: rgba(255,255,255,0.1);
            border: 1px solid rgba(255,255,255,0.2);
        }}
    </style>
    """,
        unsafe_allow_html=True,
    )


def get_domain_color(domain):
    return COLORS.get(domain, COLORS["Default"])
