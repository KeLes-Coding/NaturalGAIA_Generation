import streamlit as st
import textwrap
from streamlit_agraph import agraph, Node, Edge, Config
from theme import COLORS, get_domain_color
from utils import load_graph_data, load_json_file, get_available_files


# --- 辅助：查找节点所在的任务 ---
@st.cache_data(ttl=600)
def find_tasks_containing_node(node_id, node_label):
    """扫描 tasks 文件夹下的所有任务，找到涉及该节点的任务"""
    related_tasks = []
    task_files = get_available_files("tasks")

    for tf in task_files:
        tasks = load_json_file("tasks", tf)
        if not tasks:
            continue

        for t in tasks:
            path_steps = t.get("ground_truth", {}).get("path", [])
            entities_in_path = set()
            for step in path_steps:
                entities_in_path.add(step.get("from"))
                entities_in_path.add(step.get("to"))

            # 模糊匹配：ID 或 Label 出现在路径中即视为相关
            if node_label in entities_in_path or node_id in str(t):
                # 判断是否润色过
                q = t.get("refined_query")
                is_refined = q is not None and len(q) > 5

                related_tasks.append(
                    {
                        "file": tf,
                        "task_id": t["task_id"],
                        "query": q if is_refined else "Raw logical path only",
                        "answer": t["ground_truth"]["final_answer"],
                        "is_refined": is_refined,
                    }
                )
    return related_tasks


def render_legend():
    """渲染颜色图例 (修复缩进导致的代码块显示问题)"""
    domains = ["Multimedia", "GeoTravel", "Knowledge", "Personal"]

    # 容器开始
    html_parts = [
        '<div style="display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 10px; padding: 8px; background: rgba(255,255,255,0.03); border-radius: 8px;">'
    ]

    # 1. 领域图例
    for d in domains:
        color = get_domain_color(d)
        # 使用 dedent 去除缩进，防止被识别为代码块
        part = textwrap.dedent(
            f"""
        <div style="display:flex; align-items:center;">
            <span style="width:10px; height:10px; background-color:{color}; border-radius:50%; display:inline-block; margin-right:6px; box-shadow: 0 0 5px {color}80;"></span>
            <span style="font-size:0.8em; color:#ccc;">{d}</span>
        </div>
        """
        ).strip()
        html_parts.append(part)

    # 2. 特殊节点图例
    part_nodes = textwrap.dedent(
        f"""
        <div style="width: 1px; height: 16px; background: #444; margin: 0 4px;"></div>
        <div style="display:flex; align-items:center;">
            <span style="width:12px; height:12px; background-color:{COLORS['Hub']}; border-radius:50%; display:inline-block; margin-right:6px; border: 1px solid #fff;"></span>
            <span style="font-size:0.8em; color:#fff; font-weight:bold;">Hub Node</span>
        </div>
        <div style="display:flex; align-items:center;">
            <span style="width:8px; height:8px; background-color:{COLORS['Default']}; border-radius:50%; display:inline-block; margin-right:6px; opacity: 0.7;"></span>
            <span style="font-size:0.8em; color:#999;">Leaf/Default</span>
        </div>
    </div>
    """
    ).strip()
    html_parts.append(part_nodes)

    st.markdown("".join(html_parts), unsafe_allow_html=True)


def render_graph_explorer(selected_file):
    if not selected_file:
        st.info("👈 Please select a graph file.")
        return

    G = load_graph_data(selected_file)
    if not G:
        st.error(f"Failed to load {selected_file}")
        return

    # --- 1. 工具栏 ---
    c1, c2, c3, c4 = st.columns([1.5, 1.5, 1, 1])
    with c1:
        max_nodes = st.slider("Max Nodes", 20, 300, 60)
    with c2:
        layout_mode = st.selectbox(
            "Layout", ["Force Directed (Free)", "Hierarchical (Tree)"], index=0
        )
    with c3:
        show_labels = st.checkbox("Show Labels", value=True)
    with c4:
        st.markdown(
            f"<div style='padding-top:15px; color:#666; font-size:0.8em; text-align:right'>Total: {len(G.nodes)} nodes</div>",
            unsafe_allow_html=True,
        )

    # --- 2. 图例 (已修复) ---
    render_legend()

    # --- 3. 图构建 ---
    subgraph_nodes = list(G.nodes)[:max_nodes]
    subG = G.subgraph(subgraph_nodes)
    degrees = dict(subG.degree())
    max_deg = max(degrees.values()) if degrees else 1

    ag_nodes = []
    ag_edges = []

    for n_id in subG.nodes:
        node_data = G.nodes[n_id]
        label = node_data.get("label", str(n_id))

        # 智能着色
        edges_connected = subG.edges(n_id, data=True)
        domains = [d.get("domain") for _, _, d in edges_connected if d.get("domain")]
        if domains:
            primary_domain = max(set(domains), key=domains.count)
            color = get_domain_color(primary_domain)
        else:
            color = COLORS["Default"]

        # Hub 高亮
        norm_deg = degrees.get(n_id, 0) / max_deg
        if norm_deg > 0.4:
            color = COLORS["Hub"]

        ag_nodes.append(
            Node(
                id=n_id,
                label=label if show_labels else "",
                size=15 + (norm_deg * 25),
                color=color,
                font={"color": "#fff", "face": "sans-serif", "size": 12},
                title=f"{label} ({n_id})\nDegree: {degrees[n_id]}",
            )
        )

    for u, v, data in subG.edges(data=True):
        ag_edges.append(
            Edge(
                source=u,
                target=v,
                color=COLORS["Border"],
                width=1.0,
                title=f"Tool: {data.get('tool_name', 'Unknown')}\nApp: {data.get('app', '')}",
            )
        )

    is_hierarchical = "Hierarchical" in layout_mode
    config = Config(
        width="100%",
        height=600,
        directed=True,
        physics=not is_hierarchical,
        hierarchical=is_hierarchical,
        interaction={"hover": True, "selectConnectedEdges": True},
        physicsOptions={
            "barnesHut": {
                "gravitationalConstant": -3000,
                "centralGravity": 0.1,
                "springLength": 150,
                "springConstant": 0.02,
                "damping": 0.3,
                "avoidOverlap": 0.5,
            }
        },
    )

    # --- 4. 渲染 (No key argument) ---
    selected_node_id = agraph(nodes=ag_nodes, edges=ag_edges, config=config)

    # --- 5. 选中详情 (增强版) ---
    st.markdown("---")

    if selected_node_id and selected_node_id in G.nodes:
        node_info = G.nodes[selected_node_id]
        node_label = node_info.get("label", selected_node_id)

        # 标题栏
        st.markdown(
            f"""
        <div style="display:flex; align-items:center; gap:10px;">
            <h3 style="margin:0;">📍 Selected: <span style='color:{COLORS['Hub']}'>{node_label}</span></h3>
            <span style='font-size:0.9em; background:#333; padding:2px 8px; border-radius:4px; color:#aaa;'>ID: {selected_node_id}</span>
        </div>
        """,
            unsafe_allow_html=True,
        )

        c_detail, c_tasks = st.columns([1, 1.8], gap="large")

        # 左侧：节点属性
        with c_detail:
            st.markdown("#### Node Info")
            st.markdown(f"**Degree:** `{degrees.get(selected_node_id, 'N/A')}`")

            st.markdown("**Neighbors:**")
            neighbors = list(G.successors(selected_node_id))
            if neighbors:
                for n in neighbors[:8]:
                    n_lbl = G.nodes[n].get("label", n)
                    st.caption(f"→ {n_lbl}")
                if len(neighbors) > 8:
                    st.caption(f"... {len(neighbors)-8} more")
            else:
                st.caption("No outgoing connections.")

        # 右侧：关联任务 (修复显示逻辑)
        with c_tasks:
            st.markdown("#### 📂 Related Tasks")
            related = find_tasks_containing_node(selected_node_id, node_label)

            if related:
                # 分组
                refined_group = [t for t in related if t["is_refined"]]
                raw_group = [t for t in related if not t["is_refined"]]

                # Tab 分组显示，或者直接上下排列
                if refined_group:
                    with st.expander(
                        f"✨ Refined Tasks ({len(refined_group)})", expanded=True
                    ):
                        for rt in refined_group:
                            st.markdown(f"**{rt['task_id']}**")
                            st.info(f"🗣️ {rt['query']}")
                            st.caption(f"✅ Ans: {rt['answer']}")
                            st.markdown("---")

                if raw_group:
                    with st.expander(
                        f"⚡ Optimized (Raw) Tasks ({len(raw_group)})", expanded=False
                    ):
                        for rt in raw_group:
                            st.markdown(f"**{rt['task_id']}**")
                            st.warning("⚠️ No natural language query generated yet.")
                            st.caption(f"✅ Ans: {rt['answer']}")
                            st.markdown("---")
            else:
                st.info("No tasks generated involving this entity yet.")

    elif selected_node_id:
        st.warning(
            f"Node {selected_node_id} selected but data not found in current subgraph."
        )
    else:
        st.info("👆 Click on a node to view details & related tasks.")
