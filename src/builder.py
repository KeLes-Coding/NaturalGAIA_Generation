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
        max_workers=5,  # 恢复并发数
        data_dir="data",
    ):
        self.seed_val = seed_val
        self.rng = random.Random(seed_val)
        self.max_workers = max_workers
        self.data_dir = data_dir
        os.makedirs(os.path.join(self.data_dir, "graphs"), exist_ok=True)

        self.schema_config = load_json_config(config_file)
        self.prop_to_actions = self._parse_schema_to_actions()
        self.all_props = list(self.prop_to_actions.keys())

        self.sparql_values_clause = (
            "VALUES ?p { " + " ".join([f"wdt:{pid}" for pid in self.all_props]) + " }"
        )
        logger.info(f"GraphBuilder ready. Monitoring {len(self.all_props)} properties.")

    def _parse_schema_to_actions(self):
        map_data = {}
        for domain, d_data in self.schema_config["domains"].items():
            apps = d_data.get("apps", {})
            for app_name, app_data in apps.items():
                entities = app_data.get("entities", {})
                for ent_name, ent_data in entities.items():
                    actions = ent_data.get("actions", {})
                    for action_key, action_info in actions.items():
                        raw_rel = action_info["relation"]
                        if raw_rel.startswith("reverse_"):
                            pid = raw_rel.replace("reverse_", "").split("_")[0]
                            direction = "reverse"
                        else:
                            pid = raw_rel
                            direction = "forward"

                        if pid not in map_data:
                            map_data[pid] = []
                        map_data[pid].append(
                            {
                                "domain": domain,
                                "app": app_name,
                                "source_entity_type": ent_name,
                                "target_entity_type": action_info["target"],
                                "action_key": action_key,
                                "action_desc": action_info["desc"],
                                "direction": direction,
                            }
                        )
        return map_data

    # 重试策略：遇到网络错误才等待，否则全速运行
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        retry=retry_if_exception_type((URLError, RemoteDisconnected, Exception)),
        reraise=False,  # 失败三次后不抛异常，而是返回 None 并在上层处理
    )
    def _execute_sparql_query(self, query):
        sparql = SPARQLWrapper("https://query.wikidata.org/sparql")
        sparql.setReturnFormat(JSON)
        # 简化 User-Agent
        sparql.addCustomHttpHeader("User-Agent", f"NaturalGaia/SpeedBot")
        sparql.setTimeout(20)  # 减少超时等待
        sparql.setQuery(query)
        return sparql.query().convert()

    def _fetch_node_neighbors(self, entity_id):
        valid_neighbors = []

        # 1. 构造合并查询（Union）或者分两次极速查询
        # 这里为了稳妥，分两次，但 Limit 降为 150
        def run_query(direction):
            if direction == "forward":
                pattern = f"wd:{entity_id} ?p ?neighbor ."
            else:
                pattern = f"?neighbor ?p wd:{entity_id} ."

            query = f"""
            SELECT ?p ?neighbor ?neighborLabel WHERE {{
              {self.sparql_values_clause}
              {pattern}
              ?neighbor wdt:P31 ?anyType .
              SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
            }} LIMIT 150 
            """
            # LIMIT 150 足够了，300太慢

            res = self._execute_sparql_query(query)
            if not res:
                return []

            local_res = []
            for r in res["results"]["bindings"]:
                p_id = r["p"]["value"].split("/")[-1]
                n_id = r["neighbor"]["value"].split("/")[-1]
                n_label = r.get("neighborLabel", {}).get("value", n_id)

                if p_id in self.prop_to_actions:
                    possible_actions = self.prop_to_actions[p_id]
                    for action in possible_actions:
                        if action["direction"] == direction:
                            local_res.append(
                                {
                                    "neighbor_id": n_id,
                                    "neighbor_label": n_label,
                                    "action_metadata": action,
                                }
                            )
            return local_res

        # 移除中间的 sleep，全速请求
        valid_neighbors.extend(run_query("forward"))
        valid_neighbors.extend(run_query("reverse"))
        return entity_id, valid_neighbors

    def build_subgraph_parallel(self, start_entity_id, max_nodes=300, max_branch=3):
        logger.info(f"--- Stage 1: Building Graph (High Speed Mode) ---")
        self.rng = random.Random(self.seed_val)

        # 强制使用 MultiDiGraph
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

                        # 边逻辑 (无论是否已访问，都加边)
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
        # 确保目录存在
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # NetworkX 的 node_link_data 会自动处理 multigraph 属性
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
