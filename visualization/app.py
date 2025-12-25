import streamlit as st
import json
import os
import networkx as nx
import pandas as pd
from streamlit_agraph import agraph, Node, Edge, Config
import textwrap

# ---------------------------------------------------------
# 1. 工程配置与 CSS 注入 (Academic Dark Theme)
# ---------------------------------------------------------
st.set_page_config(
    page_title="NaturalGAIA Workbench",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# 强制深色学术风格 CSS
st.markdown(
    """
<style>
    /* 全局背景修正 */
    .stApp {
        background-color: #0d1117; /* GitHub Dark Dimmed */
        color: #c9d1d9;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    }
    
    /* 隐藏顶部烦人的 Header */
    header[data-testid="stHeader"] {
        background-color: #0d1117;
    }

    /* 侧边栏样式 */
    section[data-testid="stSidebar"] {
        background-color: #161b22;
        border-right: 1px solid #30363d;
    }

    /* 卡片容器 */
    .card-container {
        background-color: #161b22;
        border: 1px solid #30363d;
        border-radius: 6px;
        padding: 20px;
        margin-bottom: 15px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.3);
    }
    
    /* 表格样式修正 - 移除多余的拖动感 */
    div[data-testid="stDataFrame"] {
        border: 1px solid #30363d;
        border-radius: 6px;
    }

    /* --- Vertical Timeline CSS (修复版) --- */
    .timeline {
        position: relative;
        max-width: 100%;
        padding: 10px 0;
        font-family: 'Segoe UI', sans-serif;
    }
    .timeline::after {
        content: '';
        position: absolute;
        width: 2px;
        background-color: #30363d;
        top: 5px;
        bottom: 0;
        left: 19px;
        margin-left: -1px;
    }
    .timeline-item {
        padding: 0 0 20px 45px;
        position: relative;
    }
    .timeline-icon {
        position: absolute;
        left: 0;
        top: 0;
        width: 38px;
        height: 38px;
        border-radius: 50%;
        background-color: #0d1117;
        border: 2px solid #58a6ff;
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 2;
        font-size: 16px;
        box-shadow: 0 0 0 4px #0d1117; /* 伪造边距 */
    }
    .timeline-content {
        padding: 12px 16px;
        background-color: #161b22;
        border: 1px solid #30363d;
        border-radius: 6px;
        transition: all 0.2s ease;
    }
    .timeline-content:hover {
        border-color: #58a6ff;
        transform: translateX(2px);
    }
    .step-tag {
        font-size: 0.7rem;
        font-weight: 600;
        color: #8b949e;
        text-transform: uppercase;
        margin-bottom: 4px;
        letter-spacing: 0.5px;
    }
    .step-title {
        font-size: 1rem;
        font-weight: 600;
        color: #e6edf3;
        margin-bottom: 2px;
    }
    .step-desc {
        font-size: 0.85rem;
        color: #8b949e;
    }
    
    /* 胶囊标签 */
    .capsule {
        display: inline-block;
        padding: 1px 6px;
        border-radius: 10px;
        font-size: 0.7rem;
        margin-left: 8px;
        border: 1px solid;
    }

</style>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------
# 2. 数据与常量
# ---------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

# 学术哑光配色 (Matte Academic) - 不再刺眼
COLORS = {
    "Red": "#ff7b72",  # 柔和红
    "Blue": "#58a6ff",  # GitHub 蓝
    "Yellow": "#d29922",  # 柔和黄
    "Grey": "#8b949e",  # 灰
    "Border": "#30363d",
    "Bg": "#0d1117",
}

# 领域图标映射
DOMAIN_MAP = {
    "Multimedia": {"color": "#7ee787", "icon": "🎵"},  # Green
    "GeoTravel": {"color": "#58a6ff", "icon": "🌍"},  # Blue
    "Knowledge": {"color": "#d29922", "icon": "📚"},  # Yellow
    "Personal": {"color": "#ff7b72", "icon": "👤"},  # Red
    "Unknown": {"color": "#8b949e", "icon": "❓"},
}


def load_json(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []


def get_files(subdir):
    target = os.path.join(DATA_DIR, subdir)
    if not os.path.exists(target):
        return []
    return sorted([f for f in os.listdir(target) if f.endswith(".json")])


# ---------------------------------------------------------
# 3. 核心组件: 修复版 Timeline
# ---------------------------------------------------------
def render_timeline(steps):
    """
    使用 textwrap.dedent 修复缩进导致的 Markdown 代码块渲染问题。
    HTML 结构扁平化，防止样式错乱。
    """
    if not steps:
        return ""

    html_parts = ['<div class="timeline">']

    # 1. 起点
    start_label = steps[0]["from"]
    html_parts.append(
        textwrap.dedent(
            f"""
        <div class="timeline-item">
            <div class="timeline-icon" style="border-color: {COLORS['Yellow']}; color: {COLORS['Yellow']};">🚀</div>
            <div class="timeline-content">
                <div class="step-tag">INITIAL ENTITY</div>
                <div class="step-title">{start_label}</div>
            </div>
        </div>
    """
        )
    )

    # 2. 步骤循环
    for step in steps:
        d_info = DOMAIN_MAP.get(step.get("domain", "Unknown"), DOMAIN_MAP["Unknown"])
        c_hex = d_info["color"]
        icon = d_info["icon"]
        app = step.get("app", "App")
        tool = step.get("tool_name", step.get("tool", "tool"))
        target = step.get("to", "Unknown")
        idx = step.get("step_idx", "#")

        # 注意：这里不仅去了缩进，还把 color 写在 inline style 里确保优先级
        item_html = textwrap.dedent(
            f"""
        <div class="timeline-item">
            <div class="timeline-icon" style="border-color: {c_hex}; color: {c_hex};">{icon}</div>
            <div class="timeline-content">
                <div class="step-tag">
                    STEP {idx}
                    <span class="capsule" style="color:{c_hex}; border-color:{c_hex}40;">{app}</span>
                </div>
                <div class="step-title">Find: {target}</div>
                <div class="step-desc">Tool: {tool}</div>
            </div>
        </div>
        """
        )
        html_parts.append(item_html)

    html_parts.append("</div>")
    return "\n".join(html_parts)


# ---------------------------------------------------------
# 4. 视图: Task Inspector (稳定版)
# ---------------------------------------------------------
def render_task_inspector():
    # 顶部文件选择栏
    task_files = get_files("tasks")
    if not task_files:
        st.error("Data directory empty.")
        return

    c_sel, c_search = st.columns([2, 4])
    with c_sel:
        selected_file = st.selectbox(
            "Select Dataset", task_files, label_visibility="collapsed"
        )
    with c_search:
        search_query = st.text_input(
            "Search Tasks...",
            placeholder="Filter by ID or Entity name",
            label_visibility="collapsed",
        )

    data = load_json(os.path.join(DATA_DIR, "tasks", selected_file))

    # 搜索过滤
    filtered = (
        [t for t in data if search_query.lower() in json.dumps(t).lower()]
        if search_query
        else data
    )

    if not filtered:
        st.info("No matching tasks.")
        return

    # --- 左右布局 (Fixed Ratio 避免乱飞) ---
    col_left, col_right = st.columns([1.2, 2.0], gap="medium")

    with col_left:
        st.markdown(f"**Tasks List ({len(filtered)})**")

        df_list = []
        for t in filtered:
            df_list.append(
                {
                    "Index": filtered.index(t),  # Local index for display
                    "ID": t["task_id"].split("_")[-1],
                    "Start": t["input_prompt_skeleton"]["start"],
                    "Target": t["input_prompt_skeleton"]["end"],
                    "_raw_obj": t,  # Hidden object storage
                }
            )

        df = pd.DataFrame(df_list)

        # 使用 st.dataframe 的单选模式
        selection = st.dataframe(
            df[["ID", "Start", "Target"]],  # Only show relevant cols
            use_container_width=True,
            hide_index=True,
            selection_mode="single-row",
            on_select="rerun",
            height=650,
        )

        # 获取选中项
        rows = selection.selection.get("rows", [])
        selected_idx = rows[0] if rows else 0
        task = df.iloc[selected_idx]["_raw_obj"]

    # 右侧详情
    with col_right:
        # Header
        st.markdown(
            f"""
        <div class="card-container" style="border-left: 4px solid {COLORS['Blue']};">
            <h3 style="margin:0; color:{COLORS['Blue']}">{task['task_id']}</h3>
            <div style="margin-top:5px; color:{COLORS['Grey']}; font-size:0.9em;">
                Complexity: <b>{task['meta'].get('complexity_score')}</b> &nbsp;|&nbsp; 
                Path Length: <b>{len(task['ground_truth']['path'])}</b>
            </div>
        </div>
        """,
            unsafe_allow_html=True,
        )

        # Tabs for better organization
        tab_q, tab_logic, tab_json = st.tabs(
            ["🗣️ Query & Answer", "⛓️ Logic Chain", "📄 Raw Data"]
        )

        with tab_q:
            st.markdown("#### Natural Query")
            q = task.get("refined_query")
            if q:
                st.info(q)
            else:
                st.warning("Query not refined.")

            st.markdown("#### Ground Truth Answer")
            st.success(f"**{task['ground_truth']['final_answer']}**")

        with tab_logic:
            # 这里调用修复后的 render_timeline
            st.markdown(
                render_timeline(task["ground_truth"]["path"]), unsafe_allow_html=True
            )

        with tab_json:
            st.json(task)


# ---------------------------------------------------------
# 5. 视图: Graph Explorer (防抖动 + 学术配色)
# ---------------------------------------------------------
def render_graph_explorer():
    graph_files = get_files("graphs")

    # 控制栏放置在顶部，减少页面宽度挤压
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        selected_graph = st.selectbox(
            "Graph File", graph_files, label_visibility="collapsed"
        )
    with c2:
        max_nodes = st.slider("Node Limit", 20, 300, 80, label_visibility="collapsed")
    with c3:
        st.caption("👈 Select File & Limit")

    file_path = os.path.join(DATA_DIR, "graphs", selected_graph)
    try:
        nx_data = load_json(file_path)
        G = nx.node_link_graph(nx_data, edges="edges")
    except:
        st.error("Invalid Graph file.")
        return

    # 数据准备
    subgraph_nodes = list(G.nodes)[:max_nodes]
    subG = G.subgraph(subgraph_nodes)
    degrees = dict(subG.degree())
    max_deg = max(degrees.values()) if degrees else 1

    nodes = []
    edges = []

    # --- 配色逻辑修正 ---
    # 使用透明度来增加层次感
    for n_id in subgraph_nodes:
        lbl = G.nodes[n_id].get("label", n_id)
        deg = degrees.get(n_id, 0)
        norm = deg / max_deg

        # 大小：线性增加
        size = 15 + (norm * 30)

        # 颜色：根据 Degree 分级，而不是连续渐变，视觉更清晰
        if norm > 0.4:
            color = COLORS["Red"]  # Hub
        elif norm > 0.1:
            color = COLORS["Yellow"]  # Connector
        else:
            color = COLORS["Blue"]  # Leaf

        nodes.append(
            Node(
                id=n_id,
                label=lbl,
                size=size,
                color=color,
                font={"color": "#c9d1d9", "size": 14, "face": "arial"},
                title=f"{lbl} (Deg: {deg})",  # Tooltip
            )
        )

    for u, v, d in subG.edges(data=True):
        edges.append(
            Edge(
                source=u,
                target=v,
                color="#30363d",  # 极淡的边，防止喧宾夺主
                width=1.0,
                # label=d.get("app","") # 故意隐藏 Label，太乱了
            )
        )

    # --- 关键：Physics 配置防抖动 ---
    config = Config(
        width="100%",
        height=700,
        directed=True,
        physics=True,  # 开启物理
        hierarchical=False,
        # 物理引擎参数微调：增加阻尼，减少抖动
        interaction={"hover": True, "zoomView": True},
        physicsOptions={
            "barnesHut": {
                "gravitationalConstant": -3000,
                "centralGravity": 0.3,
                "springLength": 95,
                "springConstant": 0.04,
                "damping": 0.09,
                "avoidOverlap": 0.1,
            },
            "stabilization": {
                "enabled": True,
                "iterations": 1000,  # 预计算 1000 次再显示，防止一开始乱飞
            },
        },
        background_color="#0d1117",
    )

    c_main, c_info = st.columns([3, 1])

    with c_main:
        # 使用 key 避免不必要的重绘
        return_value = agraph(nodes=nodes, edges=edges, config=config)

    with c_info:
        st.markdown("### Node Inspector")
        if return_value:
            n_data = G.nodes.get(return_value, {})
            st.markdown(
                f"""
            <div class="card-container">
                <h4 style="color:{COLORS['Blue']}; margin:0;">{n_data.get('label', return_value)}</h4>
                <div style="font-size:0.8em; color:{COLORS['Grey']}; margin-bottom:10px;">ID: {return_value}</div>
                <div><b>Degree:</b> {degrees.get(return_value, 'N/A')}</div>
            </div>
            """,
                unsafe_allow_html=True,
            )

            # 显示邻居
            neighbors = list(G.successors(return_value))
            if neighbors:
                st.markdown("**Connected To:**")
                for n in neighbors[:8]:
                    n_lbl = G.nodes[n].get("label", n)
                    st.code(f"→ {n_lbl}")

        else:
            st.info("Click node to inspect.")
            st.markdown("#### Legend")
            st.markdown(
                f"""
            <div style="font-size:0.9em; line-height:2;">
                <span style="color:{COLORS['Red']}">●</span> <b>Hub Node</b> (High Connectivity)<br>
                <span style="color:{COLORS['Yellow']}">●</span> <b>Bridge Node</b> (Medium)<br>
                <span style="color:{COLORS['Blue']}">●</span> <b>Leaf Node</b> (Low)<br>
                <span style="color:#30363d">―</span> <b>Relationship</b> (Hidden Label)
            </div>
            """,
                unsafe_allow_html=True,
            )


# ---------------------------------------------------------
# 6. 主程序
# ---------------------------------------------------------
def main():
    tab1, tab2 = st.tabs(["📋 Task Analysis", "🕸️ Graph Exploration"])
    with tab1:
        render_task_inspector()
    with tab2:
        render_graph_explorer()


if __name__ == "__main__":
    main()
