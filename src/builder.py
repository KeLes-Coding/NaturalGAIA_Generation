import networkx as nx
import random
import time
import json
import os
from SPARQLWrapper import SPARQLWrapper, JSON
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
from urllib.error import URLError
from http.client import RemoteDisconnected
from src.utils import logger, load_json_config
from src.utils import logger, load_json_config, load_registry_config


class GraphBuilder:
    def __init__(
        self,
        config_file="config/app_registry.json",  # 默认值改为 registry
        seed_val=2025,
        max_workers=5,
        data_dir="data",
    ):
        self.seed_val = seed_val
        self.rng = random.Random(seed_val)
        self.max_workers = max_workers
        self.data_dir = data_dir
        os.makedirs(os.path.join(self.data_dir, "graphs"), exist_ok=True)

        # --- 核心修改：使用注册表加载器 ---
        # 自动判断是旧版单文件还是新版注册表
        if "registry" in config_file or "app_registry" in config_file:
            self.schema_config = load_registry_config(config_file)
        else:
            logger.warning(
                "Loading legacy single-file config. Recommend upgrading to app_registry.json"
            )
            self.schema_config = load_json_config(config_file)

        # 1. 解析 Schema (后续逻辑无需修改，因为 load_registry_config 保证了结构一致性)
        self.prop_to_actions = self._parse_schema_to_actions()
        self.all_props = list(self.prop_to_actions.keys())

        # 2. 提取 Config 中所有的根类 ID
        self.all_root_types = self._collect_all_root_types()

        # 3. 构造 SPARQL 子句
        # 限制查询的属性范围
        self.sparql_prop_values = (
            "VALUES ?p { " + " ".join([f"wdt:{pid}" for pid in self.all_props]) + " }"
        )
        # 限制查询的根类范围 (用于推理)
        self.sparql_type_values = (
            "VALUES ?rootType { "
            + " ".join([f"wd:{qid}" for qid in self.all_root_types])
            + " }"
        )

        logger.info(f"GraphBuilder ready. Monitoring {len(self.all_props)} properties.")
        logger.info(
            f"Type Inference enabled for {len(self.all_root_types)} Root Classes (e.g., Album, Movie, Place)."
        )

    def _collect_all_root_types(self):
        """
        扫描 Config，收集所有 type_filter 中定义的 Q-ID。
        """
        root_types = set()
        for domain, d_data in self.schema_config["domains"].items():
            for app, app_data in d_data.get("apps", {}).items():
                for ent, ent_data in app_data.get("entities", {}).items():
                    # 兼容新旧字段
                    filters = (
                        ent_data.get("type_filter")
                        or ent_data.get("target_filters")
                        or []
                    )
                    root_types.update(filters)
        return list(root_types)

    def _get_allowed_roots(self, full_key):
        """辅助方法：从 entity_type_map 获取 Q-ID 集合"""
        # 我们需要访问 _parse_schema_to_actions 里生成的 entity_type_map
        # 但那个变量是局部变量。我们需要在 __init__ 或 _parse_schema_to_actions 里把它存为 self.variable
        # 修正方案：修改 _parse_schema_to_actions 将 map 存下来。
        if hasattr(self, "entity_type_map"):
            return self.entity_type_map.get(full_key, set())
        return set()

    def _parse_schema_to_actions(self):
        """
        重写此方法以保存 entity_type_map 到 self
        """
        # 第一步：建立 实体名 -> 根类列表 的查找表
        self.entity_type_map = {}  # <--- 修改点：存为成员变量
        for domain, d_data in self.schema_config["domains"].items():
            for app_name, app_data in d_data.get("apps", {}).items():
                for ent_name, ent_data in app_data.get("entities", {}).items():
                    filters = ent_data.get("type_filter") or ent_data.get(
                        "target_filters"
                    )
                    if filters:
                        key = f"{domain}.{app_name}.{ent_name}"
                        self.entity_type_map[key] = set(filters)

        # 第二步：(保持原有的逻辑不变，只修改 map_data 的生成)
        map_data = {}
        for domain, d_data in self.schema_config["domains"].items():
            apps = d_data.get("apps", {})
            for app_name, app_data in apps.items():
                entities = app_data.get("entities", {})
                for ent_name, ent_data in entities.items():
                    actions = ent_data.get("actions", {})
                    for action_key, action_info in actions.items():
                        if "relation" not in action_info:
                            continue
                        if "target" not in action_info:
                            continue

                        raw_rel = action_info["relation"]
                        if raw_rel.startswith("reverse_"):
                            pid = raw_rel.replace("reverse_", "").split("_")[0]
                            direction = "reverse"
                        else:
                            pid = raw_rel
                            direction = "forward"

                        if pid not in map_data:
                            map_data[pid] = []

                        target_ent_type = action_info["target"]
                        target_key = f"{domain}.{app_name}.{target_ent_type}"
                        allowed_roots = self.entity_type_map.get(
                            target_key
                        )  # 使用 self

                        map_data[pid].append(
                            {
                                "domain": domain,
                                "app": app_name,
                                "source_entity_type": ent_name,
                                "target_entity_type": target_ent_type,
                                "action_key": action_key,
                                "action_desc": action_info.get("desc", ""),
                                "direction": direction,
                                "allowed_root_types": allowed_roots,
                            }
                        )
        return map_data

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((URLError, RemoteDisconnected, Exception)),
        reraise=False,
    )
    def _execute_sparql_query(self, query):
        sparql = SPARQLWrapper("https://query.wikidata.org/sparql")
        sparql.setReturnFormat(JSON)
        sparql.addCustomHttpHeader("User-Agent", f"NaturalGaia/InferenceBot")
        sparql.setTimeout(45)  # 推理查询稍慢，增加超时
        sparql.setQuery(query)
        return sparql.query().convert()

    def _fetch_node_neighbors(self, entity_id):
        valid_neighbors = []

        def run_query(direction):
            # 1. 确定方向模式
            if direction == "forward":
                # Entity -> Neighbor
                # Source 是 entity_id, Target 是 neighbor
                pattern = f"wd:{entity_id} ?p ?neighbor ."
            else:
                # Neighbor -> Entity
                # Source 是 neighbor, Target 是 entity_id (但在 Action 定义里，Source 始终是动作发起者)
                # 等等，Action 定义里的 "Source" 指的是App所在的实体。
                # 如果是 reverse 属性 (e.g. check_author, Book -> Person via P50 reverse)，
                # 意味着 Graph 里的边是 Person --P50--> Book。
                # 但 Action 是在 Book 上发起的。
                # 所以：
                # Forward Action: Source(id) --P--> Target(neighbor)
                # Reverse Action: Target(neighbor) --P--> Source(id)
                pattern = f"?neighbor ?p wd:{entity_id} ."

            # 2. 构造查询
            # 这里的关键是：我们需要同时验证 entity_id (作为 Action Source) 和 neighbor (作为 Action Target) 的类型
            # 仅当 entity_id 也是 Config 定义的 SourceRoot 时，才允许这条边。

            query = f"""
            SELECT DISTINCT ?p ?neighbor ?neighborLabel ?myType ?neighborType WHERE {{
              {self.sparql_prop_values}
              {pattern}
              FILTER(isIRI(?neighbor))
              
              # 获取当前节点(我)的类型
              wd:{entity_id} wdt:P31/wdt:P279* ?myType .
              {self.sparql_type_values.replace("?rootType", "?myType")}
              
              # 获取邻居的类型
              ?neighbor wdt:P31/wdt:P279* ?neighborType .
              {self.sparql_type_values.replace("?rootType", "?neighborType")}
              
              SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
            }} LIMIT 300
            """

            try:
                res = self._execute_sparql_query(query)
            except Exception:
                return []

            if not res:
                return []

            # 3. 结果处理
            temp_nodes = {}
            for r in res["results"]["bindings"]:
                p_id = r["p"]["value"].split("/")[-1]
                n_id = r["neighbor"]["value"].split("/")[-1]
                n_label = r.get("neighborLabel", {}).get("value", n_id)

                my_root = r.get("myType", {}).get("value", "").split("/")[-1]
                n_root = r.get("neighborType", {}).get("value", "").split("/")[-1]

                if n_id not in temp_nodes:
                    temp_nodes[n_id] = {"label": n_label, "matches": []}

                temp_nodes[n_id]["matches"].append(
                    {"p": p_id, "my_root": my_root, "n_root": n_root}
                )

            local_results = []

            # 4. 严格匹配 Config
            for n_id, data in temp_nodes.items():
                seen_actions = set()

                for match in data["matches"]:
                    p_id = match["p"]
                    my_root = match["my_root"]
                    n_root = match["n_root"]

                    if p_id not in self.prop_to_actions:
                        continue

                    for action in self.prop_to_actions[p_id]:
                        # A. 方向检查
                        if action["direction"] != direction:
                            continue

                        # B. 核心：源类型检查 (Source Type Check)
                        # Action 定义的 Source Entity (e.g. Amazon.Book) 允许哪些 Q-IDs?
                        src_key = f"{action['domain']}.{action['app']}.{action['source_entity_type']}"
                        allowed_src_roots = self.entity_type_map.get(src_key, set())
                        if my_root not in allowed_src_roots:
                            continue  # 拒绝：虽然有连线，但我(entity_id)不是这个App能操作的对象类型

                        # C. 核心：目标类型检查 (Target Type Check)
                        allowed_tgt_roots = action["allowed_root_types"]
                        if allowed_tgt_roots and n_root not in allowed_tgt_roots:
                            continue

                        # D. 添加合法边
                        uid = f"{action['app']}_{action['action_key']}"
                        if uid not in seen_actions:
                            local_results.append(
                                {
                                    "neighbor_id": n_id,
                                    "neighbor_label": data["label"],
                                    "action_metadata": action,
                                }
                            )
                            seen_actions.add(uid)
            return local_results

        valid_neighbors.extend(run_query("forward"))
        valid_neighbors.extend(run_query("reverse"))
        return entity_id, valid_neighbors

    def build_subgraph_parallel(self, start_entity_id, max_nodes=300, max_branch=3):
        logger.info(f"--- Stage 1: Building Graph (Root-Class Inference Mode) ---")
        self.rng = random.Random(self.seed_val)

        G = nx.MultiDiGraph()
        G.add_node(start_entity_id, label="StartNode", type="Generic")

        queue = [start_entity_id]
        visited_or_queued = {start_entity_id}

        pbar = tqdm(total=max_nodes, desc="Crawling")
        pbar.update(1)

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            while len(G.nodes) < max_nodes and queue:
                current_batch = []
                for _ in range(self.max_workers * 2):
                    if queue:
                        current_batch.append(queue.pop(0))
                if not current_batch:
                    break

                future_to_id = {
                    executor.submit(self._fetch_node_neighbors, eid): eid
                    for eid in current_batch
                }

                for future in as_completed(future_to_id):
                    original_id, neighbors = future.result()
                    if not neighbors:
                        continue

                    self.rng.shuffle(neighbors)
                    count = 0
                    for n in neighbors:
                        if count >= max_branch:
                            break

                        target_id = n["neighbor_id"]
                        meta = n["action_metadata"]

                        # 节点逻辑
                        if target_id not in visited_or_queued:
                            if len(G.nodes) >= max_nodes:
                                break
                            visited_or_queued.add(target_id)
                            queue.append(target_id)
                            G.add_node(target_id, label=n["neighbor_label"])
                            pbar.update(1)

                        # 边逻辑
                        if G.has_node(target_id) or target_id in visited_or_queued:
                            G.add_edge(
                                original_id,
                                target_id,
                                app=meta["app"],
                                domain=meta["domain"],
                                action_key=meta["action_key"],
                                action_desc=meta["action_desc"],
                                source_type=meta["source_entity_type"],
                                target_type=meta["target_entity_type"],
                            )
                        count += 1
        pbar.close()
        return G

    def save_graph(self, G, filename):
        path = os.path.join(self.data_dir, "graphs", filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(nx.node_link_data(G), f, ensure_ascii=False, indent=2)
        logger.info(
            f"Graph saved to {path} (Nodes: {len(G.nodes)}, Edges: {len(G.edges)})"
        )

    def load_graph(self, filename):
        path = os.path.join(self.data_dir, "graphs", filename)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return nx.node_link_graph(json.load(f))
