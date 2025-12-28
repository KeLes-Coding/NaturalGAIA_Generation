import streamlit as st
import pandas as pd
import json
from theme import COLORS, get_domain_color
from utils import load_json_file


def render_timeline_modern(steps):
    """
    Generate clean HTML for the vertical timeline.
    FIX: Constructs HTML as single-line strings to prevent Markdown/Indentation errors.
    """
    if not steps:
        return "<div>No steps found</div>"

    html_parts = []

    # 1. Start Entity
    start_node = steps[0].get("from") or steps[0].get("from_label") or "Unknown Start"

    # 构建 Start Block (单行模式)
    start_block = (
        f'<div class="step-container">'
        f'<div class="step-icon" style="border-color: {COLORS["Hub"]}; box-shadow: 0 0 8px {COLORS["Hub"]};"></div>'
        f'<div class="step-content" style="border-left: 3px solid {COLORS["Hub"]}">'
        f'<div class="step-tag" style="color:{COLORS["Hub"]}">START ENTITY</div>'
        f'<div class="step-title">{start_node}</div>'
        f"</div>"
        f"</div>"
    )
    html_parts.append(start_block)

    # 2. Steps
    for step in steps:
        domain = step.get("domain", "Default")
        color = get_domain_color(domain)
        app = step.get("app", "App")
        target = step.get("to") or step.get("to_label") or "Unknown Target"
        desc = step.get("description", "No description")
        context = step.get("context", {})

        # 构建 Context HTML
        context_html = ""
        if context and isinstance(context, dict):
            # 筛选前4个关键约束显示
            items = [f"<b>{k}</b>: {v}" for k, v in list(context.items())[:4]]
            context_str = " | ".join(items)
            context_html = (
                f'<div class="step-context">🔒 Constraints: {context_str}</div>'
            )

        # 构建 Step Block (单行模式，杜绝任何换行符导致的 markdown 解析错误)
        step_idx = step.get("step_idx", "?")

        step_block = (
            f'<div class="step-container">'
            f'<div class="step-icon" style="border-color: {color};"></div>'
            f'<div class="step-content">'
            f'<div class="step-tag" style="color:{color}">'
            f"STEP {step_idx} • {domain}"
            f'<span class="app-badge" style="color:{color}; border-color:{color}">{app}</span>'
            f"</div>"
            f'<div class="step-title">Find: {target}</div>'
            f'<div class="step-desc">{desc}</div>'
            f"{context_html}"
            f"</div>"
            f"</div>"
        )
        html_parts.append(step_block)

    return "".join(html_parts)


def render_task_inspector(selected_file):
    if not selected_file:
        st.info("👈 Please select a task dataset from the sidebar.")
        return

    data = load_json_file("tasks", selected_file)
    if not data:
        st.error(f"Failed to load task data from {selected_file}.")
        return

    # --- 布局 ---
    col_list, col_detail = st.columns([1.5, 2.5], gap="large")

    with col_list:
        st.markdown("### 📋 Task List")

        # 准备数据
        df_display = []
        for i, t in enumerate(data):
            df_display.append(
                {
                    "Index": f"T-{i}",
                    "Start": t["input_prompt_skeleton"]["start"],
                    "Goal": t["input_prompt_skeleton"]["end"],
                    "_index": i,
                }
            )

        df = pd.DataFrame(df_display)

        # 搜索
        search = st.text_input(
            "🔍 Filter Tasks",
            placeholder="Search entity...",
            label_visibility="collapsed",
        )
        if search:
            mask = df.apply(lambda x: search.lower() in str(x).lower(), axis=1)
            df = df[mask]

        # 列表
        event = st.dataframe(
            df.drop(columns=["_index"]),
            use_container_width=True,
            hide_index=True,
            selection_mode="single-row",
            on_select="rerun",
            height=600,
        )

        selected_rows = event.selection.get("rows", [])
        if selected_rows:
            real_idx = df.iloc[selected_rows[0]]["_index"]
            task = data[real_idx]
        else:
            task = data[0] if data else None

    # --- 详情视图 ---
    with col_detail:
        if not task:
            return

        st.markdown(
            f"""
        <div class="glass-card">
            <h2 style="margin-top:0; color:{COLORS['Multimedia']}">{task['task_id']}</h2>
            <div style="display:flex; justify-content: space-between; color:#b0bec5; font-size:0.9em;">
                <span>🎯 <b>Target:</b> {task['input_prompt_skeleton']['end']}</span>
                <span>🔥 <b>Complexity:</b> {task['meta'].get('complexity', task['meta'].get('complexity_score', 'N/A'))}</span>
            </div>
        </div>
        """,
            unsafe_allow_html=True,
        )

        tab1, tab2, tab3 = st.tabs(["🗣️ Query", "⛓️ Logic Chain", "📄 Raw Data"])

        with tab1:
            st.markdown("##### Natural Language Query")
            q = task.get("refined_query")
            if q:
                st.info(q)
            else:
                st.warning("Query not refined yet.")

            st.markdown("##### Ground Truth Answer")
            st.success(f"**{task['ground_truth']['final_answer']}**")

        with tab2:
            st.markdown("##### Reasoning Path")
            timeline_html = render_timeline_modern(task["ground_truth"]["path"])
            st.markdown(timeline_html, unsafe_allow_html=True)

        with tab3:
            st.json(task)
