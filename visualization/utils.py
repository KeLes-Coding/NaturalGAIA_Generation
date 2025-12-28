import os
import json
import networkx as nx

# --- 📂 路径配置 ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")


def get_available_files(subdir):
    """获取指定数据目录下的 JSON 文件列表"""
    target_path = os.path.join(DATA_DIR, subdir)
    if not os.path.exists(target_path):
        return []
    return sorted([f for f in os.listdir(target_path) if f.endswith(".json")])


def load_json_file(subdir, filename):
    """安全加载 JSON"""
    path = os.path.join(DATA_DIR, subdir, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {path}: {e}")
        return None


def load_graph_data(filename):
    """加载并转换 NetworkX 图对象"""
    json_data = load_json_file("graphs", filename)
    if not json_data:
        return None
    try:
        # --- 修复点：移除 edges="edges"，让 NetworkX 自动检测 (通常默认为 "links") ---
        # 如果新版 NetworkX 默认 links 但文件是 edges，可以尝试两种方式
        try:
            return nx.node_link_graph(json_data)
        except:
            # 兼容旧格式或特定参数
            return nx.node_link_graph(json_data, edges="edges")
    except Exception as e:
        print(f"Graph load error: {e}")
        return None
