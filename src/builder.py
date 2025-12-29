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


class GraphBuilder:
    def __init__(
        self,
        config_file="config/tools_config.json",
        seed_val=2025,
        max_workers=5,
        data_dir="data",
    ):
        self.seed_val = seed_val
        self.rng = random.Random(seed_val)
        self.max_workers = max_workers
        self.data_dir = data_dir
        os.makedirs(os.path.join(self.data_dir, "graphs"), exist_ok=True)

        self.schema_config = load_json_config(config_file)

        # 1. 解析 Schema，建立 属性 -> 动作 的映射
        self.prop_to_actions = self._parse_schema_to_actions()
        self.all_props = list(self.prop_to_actions.keys())

        # 2. 提取 Config 中所有的根类 ID (Root Types)
        # 我们将在 SPARQL 中把邻居映射回这些根类，以实现子类自动兼容
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

    def _parse_schema_to_actions(self):
        """
        解析配置文件，将属性映射到动作，并记录预期的目标根类。
        """
        # 第一步：建立 实体名 -> 根类列表 的查找表
        # 格式: {"Spotify.Album": {"Q482994", "Q207628"}, ...}
        entity_type_map = {}
        for domain, d_data in self.schema_config["domains"].items():
            for app_name, app_data in d_data.get("apps", {}).items():
                for ent_name, ent_data in app_data.get("entities", {}).items():
                    filters = ent_data.get("type_filter") or ent_data.get(
                        "target_filters"
                    )
                    if filters:
                        key = f"{domain}.{app_name}.{ent_name}"
                        entity_type_map[key] = set(filters)

        # 第二步：将属性映射到 Action
        map_data = {}
        for domain, d_data in self.schema_config["domains"].items():
            apps = d_data.get("apps", {})
            for app_name, app_data in apps.items():
                entities = app_data.get("entities", {})
                for ent_name, ent_data in entities.items():
                    actions = ent_data.get("actions", {})
                    for action_key, action_info in actions.items():
                        raw_rel = action_info["relation"]

                        # 解析方向
                        if raw_rel.startswith("reverse_"):
                            pid = raw_rel.replace("reverse_", "").split("_")[0]
                            direction = "reverse"
                        else:
                            pid = raw_rel
                            direction = "forward"

                        if pid not in map_data:
                            map_data[pid] = []

                        # 获取该动作允许的目标根类
                        target_ent_type = action_info["target"]
                        target_key = f"{domain}.{app_name}.{target_ent_type}"
                        allowed_roots = entity_type_map.get(target_key)

                        map_data[pid].append(
                            {
                                "domain": domain,
                                "app": app_name,
                                "source_entity_type": ent_name,
                                "target_entity_type": target_ent_type,
                                "action_key": action_key,
                                "action_desc": action_info["desc"],
                                "direction": direction,
                                # 这里存储的是 Config 里写的“父类”
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
        """
        使用 SPARQL 属性路径 (Property Paths) 进行智能抓取。
        即：不仅看 ?neighbor 是什么类型，还看它是否属于 Config 定义的根类的子类。
        """
        valid_neighbors = []

        def run_query(direction):
            if direction == "forward":
                # Entity -> Neighbor
                # 必须过滤: Neighbor 必须是 Item (Q...)
                pattern = f"wd:{entity_id} ?p ?neighbor . FILTER(isIRI(?neighbor))"
            else:
                # Neighbor -> Entity
                pattern = f"?neighbor ?p wd:{entity_id} . FILTER(isIRI(?neighbor))"

            # --- 核心升级：推理查询 ---
            # 1. ?neighbor wdt:P31/wdt:P279* ?rootType
            #    这句话的意思是：查找 neighbor 的类型，或者它类型的父类、祖父类...
            # 2. VALUES ?rootType { ... }
            #    只保留那些“祖先”是我们 Config 里定义的 Root Class 的结果。
            # 这相当于在 SPARQL 端完成了 isValidSubclassOf() 的检查。
            query = f"""
            SELECT DISTINCT ?p ?neighbor ?neighborLabel ?rootType WHERE {{
              {self.sparql_prop_values}
              {pattern}
              
              # 推理核心：检查 neighbor 是否是我们关注的根类的实例（或子类的实例）
              ?neighbor wdt:P31/wdt:P279* ?rootType .
              {self.sparql_type_values}
              
              SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
            }} LIMIT 300
            """

            res = self._execute_sparql_query(query)
            if not res:
                return []

            # 1. 聚合结果
            # 因为一个 neighbor 可能匹配多个 rootType (如既是 Director 也是 Person)
            # 结构: { "Q123": { "label": "X", "relations": { "P1": {"rootA", "rootB"} } } }
            temp_nodes = {}

            for r in res["results"]["bindings"]:
                p_id = r["p"]["value"].split("/")[-1]
                n_id = r["neighbor"]["value"].split("/")[-1]
                n_label = r.get("neighborLabel", {}).get("value", n_id)
                r_type = (
                    r.get("rootType", {}).get("value", "").split("/")[-1]
                )  # 这是一个 Root Class ID

                if n_id not in temp_nodes:
                    temp_nodes[n_id] = {"label": n_label, "edges": {}}

                if p_id not in temp_nodes[n_id]["edges"]:
                    temp_nodes[n_id]["edges"][p_id] = set()

                if r_type:
                    temp_nodes[n_id]["edges"][p_id].add(r_type)

            local_res = []

            # 2. 匹配验证
            for n_id, data in temp_nodes.items():
                for p_id, found_roots in data["edges"].items():
                    if p_id in self.prop_to_actions:
                        possible_actions = self.prop_to_actions[p_id]

                        for action in possible_actions:
                            # 方向检查
                            if action["direction"] != direction:
                                continue

                            # 类型检查 (基于 Root Class)
                            # 只要 SPARQL 找到的 ?rootType 与 Action 要求的 allowed_root_types 有交集
                            # 就说明这个 Neighbor 是合法的子类实例
                            allowed = action["allowed_root_types"]
                            if allowed:
                                if not found_roots.intersection(allowed):
                                    continue  # 虽然有连线，但类型推导不匹配

                            local_res.append(
                                {
                                    "neighbor_id": n_id,
                                    "neighbor_label": data["label"],
                                    "action_metadata": action,
                                }
                            )
            return local_res

        # 执行双向查询
        # 注意：这里可能会有些慢，因为涉及到 wdt:P279* 推理
        # 但因为限定了 VALUES ?rootType，查询引擎通常能优化
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
