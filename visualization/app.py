import streamlit as st
import sys
import os
import time

# --- 0. 路径补丁 ---
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)

if project_root not in sys.path:
    sys.path.append(project_root)
if current_dir not in sys.path:
    sys.path.append(current_dir)

from theme import inject_custom_css
from utils import get_available_files
from task_view import render_task_inspector
from graph_view import render_graph_explorer

try:
    from src.builder import GraphBuilder
    from src.generator import TaskGenerator

    SRC_AVAILABLE = True
except ImportError:
    SRC_AVAILABLE = False

# 1. 页面基本配置
st.set_page_config(
    page_title="NaturalGAIA Workbench",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 2. 注入全局 CSS
inject_custom_css()


# --- 🧊 冷启动功能组件 ---
def render_cold_start():
    st.markdown(
        """
    <div style="text-align: center; padding: 40px 20px;">
        <h1 style="color: #58a6ff;">🚀 Welcome to NaturalGAIA</h1>
        <p style="font-size: 1.2em; color: #8b949e;">
            It seems your workbench is empty. Let's initialize it with some data!
        </p>
    </div>
    """,
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        with st.container():
            st.markdown(
                """
                <div class="glass-card">
                    <h3>🛠️ Initialize Demo Data</h3>
                    <p style="font-size: 0.9em; color: #8b949e;">
                        This will crawl a small subgraph from Wikidata and generate logical tasks.
                    </p>
                </div>
                """,
                unsafe_allow_html=True,
            )

            with st.form("cold_start_form"):
                col_a, col_b = st.columns(2)
                with col_a:
                    seed_entity = st.text_input(
                        "Seed Entity ID",
                        "Q26876",
                        help="Wikidata ID (e.g., Q26876 for Taylor Swift)",
                    )
                    seed_label = st.text_input("Seed Label", "Taylor Swift")
                with col_b:
                    nodes_count = st.slider("Max Nodes", 20, 300, 100)
                    tasks_count = st.slider("Tasks to Generate", 1, 50, 10)

                # FIX: 替换 use_container_width=True 为 width="stretch"
                submitted = st.form_submit_button("🔥 Ignite Engine", width="stretch")

                if submitted:
                    if not SRC_AVAILABLE:
                        st.error(
                            "❌ Source code (src module) not found. Please verify directory structure."
                        )
                        return

                    progress_text = "Operation in progress. Please wait..."
                    my_bar = st.progress(0, text=progress_text)

                    try:
                        # 临时切换工作目录以确保 config 路径正确
                        original_cwd = os.getcwd()
                        os.chdir(project_root)

                        # 1. 构建图谱
                        my_bar.progress(
                            10, text="🕷️ Crawling Wikidata Knowledge Graph..."
                        )
                        config_path = os.path.join("config", "tools_config.json")

                        builder = GraphBuilder(
                            config_file=config_path, seed_val=2025, max_workers=5
                        )

                        graph_filename = f"demo_graph_{seed_entity}.json"

                        G = builder.build_subgraph_parallel(
                            seed_entity, max_nodes=nodes_count
                        )
                        if G.has_node(seed_entity):
                            G.nodes[seed_entity]["label"] = seed_label

                        builder.save_graph(G, graph_filename)
                        my_bar.progress(60, text="✅ Graph built. Generating tasks...")

                        # 2. 生成任务
                        generator = TaskGenerator(seed_val=2025)
                        tasks, path = generator.generate_tasks(
                            G, total_paths=tasks_count
                        )

                        my_bar.progress(100, text="🎉 Generation Complete!")
                        st.success(
                            f"Successfully generated {len(tasks)} tasks and a graph with {len(G.nodes)} nodes."
                        )
                        time.sleep(1)
                        st.rerun()

                    except Exception as e:
                        st.error(f"Error during generation: {e}")
                    finally:
                        os.chdir(original_cwd)


def main():
    # 检查数据是否存在
    has_tasks = len(get_available_files("tasks")) > 0
    has_graphs = len(get_available_files("graphs")) > 0
    is_empty = not (has_tasks or has_graphs)

    # --- Sidebar: 全局控制区 ---
    with st.sidebar:
        st.title("🧬 NaturalGAIA")
        st.caption("Agentic Knowledge Graph Benchmark")
        st.markdown("---")

        if is_empty:
            st.warning("⚠️ No Data Found")
            st.markdown("Please initialize the dataset using the main panel.")
            mode = "Cold Start"
        else:
            mode = st.radio("Work Mode", ["Task Analysis", "Graph Explorer"], index=0)

            st.markdown("---")

            if mode == "Task Analysis":
                files = get_available_files("tasks")
                selected_file = (
                    st.selectbox("Select Task Dataset", files) if files else None
                )
            elif mode == "Graph Explorer":
                files = get_available_files("graphs")
                selected_file = (
                    st.selectbox("Select Graph File", files) if files else None
                )

        st.markdown("---")
        st.markdown("Made with ❤️ by Sprite")

    # --- Main Canvas ---
    if is_empty:
        render_cold_start()
    elif mode == "Task Analysis":
        if "selected_file" in locals() and selected_file:
            render_task_inspector(selected_file)
        else:
            st.error("No task files available.")

    elif mode == "Graph Explorer":
        if "selected_file" in locals() and selected_file:
            render_graph_explorer(selected_file)


if __name__ == "__main__":
    main()
