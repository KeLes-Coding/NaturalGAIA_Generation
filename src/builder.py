import networkx as nx
import random
import time
import json
import os
from SPARQLWrapper import SPARQLWrapper, JSON
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from src.utils import logger, load_json_config


class GraphBuilder:
    def __init__(
        self,
        config_file="tools_config.json",
        seed_val=2025,
        max_workers=4,
        data_dir="data",
    ):
        self.seed_val = seed_val
        self.rng = random.Random(seed_val)
        self.max_workers = max_workers
        self.data_dir = data_dir

        os.makedirs(os.path.join(self.data_dir, "graphs"), exist_ok=True)

        # 加载工具配置
        self.schema_config = load_json_config(config_file)
        self.schema_map = self._parse_schema()
        self.allowed_props = list(self.schema_map.keys())

        # 预生成 SPARQL 过滤子句
        self.sparql_values_clause = (
            "VALUES ?p { "
            + " ".join([f"wdt:{pid}" for pid in self.allowed_props])
            + " }"
        )
        logger.info(
            f"GraphBuilder ready. Filtering {len(self.allowed_props)} properties."
        )

    def _parse_schema(self):
        """解析 tools_config.json 为扁平映射"""
        flat_map = {}
        for domain, content in self.schema_config["domains"].items():
            if "tools" in content:
                for pid, info in content["tools"].items():
                    flat_map[pid] = {
                        "domain": domain,
                        "app": info["app"],
                        "tool_name": info["name"],
                    }
        return flat_map

    def _fetch_node_neighbors(self, entity_id):
        """执行双向 SPARQL 查询"""
        sparql = SPARQLWrapper("https://query.wikidata.org/sparql")
        sparql.setReturnFormat(JSON)
        ua = f"AcademicBenchmarkBot/1.0 (RandomSeed: {self.rng.randint(1, 10000)})"
        sparql.addCustomHttpHeader("User-Agent", ua)
        sparql.setTimeout(30)

        valid_neighbors = []

        def run_query(query_type):
            if query_type == "forward":
                query = f"""
                SELECT ?p ?neighbor ?neighborLabel ?propLabel WHERE {{
                  {self.sparql_values_clause}
                  wd:{entity_id} ?p ?neighbor .
                  ?neighbor wdt:P31 ?anyType . 
                  ?prop wikibase:directClaim ?p .
                  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
                }} LIMIT 50
                """
            else:  # reverse
                query = f"""
                SELECT ?p ?neighbor ?neighborLabel ?propLabel WHERE {{
                  {self.sparql_values_clause}
                  ?neighbor ?p wd:{entity_id} .
                  ?neighbor wdt:P31 ?anyType .
                  ?prop wikibase:directClaim ?p .
                  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
                }} LIMIT 50
                """

            sparql.setQuery(query)
            try:
                results = sparql.query().convert()
                local_results = []
                for r in results["results"]["bindings"]:
                    p_id = r["p"]["value"].split("/")[-1]
                    if p_id not in self.schema_map:
                        continue

                    local_results.append(
                        {
                            "r_id": p_id,
                            "r_label": r.get("propLabel", {}).get("value", p_id),
                            "e_id": r["neighbor"]["value"].split("/")[-1],
                            "e_label": r.get("neighborLabel", {}).get(
                                "value", "Unknown"
                            ),
                            "app_info": self.schema_map[p_id],
                            "direction": query_type,
                        }
                    )
                return local_results
            except Exception as e:
                logger.warning(
                    f"[{query_type.upper()}] Query failed for {entity_id}: {str(e)}"
                )
                return []

        # 执行查询
        valid_neighbors.extend(run_query("forward"))
        time.sleep(0.2)
        valid_neighbors.extend(run_query("reverse"))

        return entity_id, valid_neighbors

    def build_subgraph_parallel(self, start_entity_id, max_nodes=200, max_branch=3):
        logger.info(f"--- Stage 1: Building Subgraph (Seed: {start_entity_id}) ---")
        self.rng = random.Random(self.seed_val)

        G = nx.DiGraph()
        G.add_node(start_entity_id, label="StartNode")  # Label 需在外部修正

        queue = [start_entity_id]
        visited_or_queued = {start_entity_id}

        pbar = tqdm(total=max_nodes, desc="Crawling Nodes")
        pbar.update(1)

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            while len(G.nodes) < max_nodes and queue:
                batch_size = self.max_workers * 2
                current_batch = []
                for _ in range(batch_size):
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
                    selected = neighbors[:max_branch]

                    for n in selected:
                        if len(G.nodes) >= max_nodes:
                            break

                        target_id = n["e_id"]
                        if target_id not in visited_or_queued:
                            visited_or_queued.add(target_id)
                            if len(G.nodes) < max_nodes:
                                queue.append(target_id)

                        if not G.has_node(target_id):
                            G.add_node(target_id, label=n["e_label"])
                            pbar.update(1)

                        # 处理边和工具描述
                        is_reverse = n["direction"] == "reverse"
                        action_desc = n["app_info"]["tool_name"]
                        if is_reverse:
                            action_desc = (
                                f"search_{n['app_info']['domain']}_by_{n['r_label']}"
                            )

                        G.add_edge(
                            original_id,
                            target_id,
                            r_id=n["r_id"],
                            r_label=n["r_label"],
                            app=n["app_info"]["app"],
                            tool=action_desc,
                            domain=n["app_info"]["domain"],
                            direction=n["direction"],
                        )
                time.sleep(0.5)
        pbar.close()

        if len(G.nodes) < 5:
            logger.critical(f"Graph too small ({len(G.nodes)} nodes).")

        return G

    def save_graph(self, G, filename):
        path = os.path.join(self.data_dir, "graphs", filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                nx.node_link_data(G, edges="edges"), f, ensure_ascii=False, indent=2
            )
        logger.info(f"Graph saved to {path}")

    def load_graph(self, filename):
        path = os.path.join(self.data_dir, "graphs", filename)
        if not os.path.exists(path):
            logger.info(f"Graph file not found: {path}")
            return None
        with open(path, "r", encoding="utf-8") as f:
            return nx.node_link_graph(json.load(f), edges="edges")
