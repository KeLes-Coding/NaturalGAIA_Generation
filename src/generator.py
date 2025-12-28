import networkx as nx
import random
import os
import json
import time
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from SPARQLWrapper import SPARQLWrapper, JSON
from src.utils import logger, load_json_config


class TaskGenerator:
    def __init__(
        self,
        config_file="config/tools_config.json",
        seed_val=2025,
        data_dir="data",
        workers=5,
    ):
        self.seed_val = seed_val
        self.data_dir = data_dir
        self.workers = workers
        self.config_data = load_json_config(config_file)
        os.makedirs(os.path.join(self.data_dir, "tasks"), exist_ok=True)

        self.global_node_usage = {}
        self.type_constraints = self._parse_constraints()

        self.blacklisted_terms = [
            "list of",
            "discography",
            "filmography",
            "bibliography",
            "category:",
            "template:",
            "chronological",
            "appearances",
        ]

    def _parse_constraints(self):
        map_data = {}
        for domain, d_data in self.config_data["domains"].items():
            for app, app_data in d_data["apps"].items():
                for ent, ent_data in app_data["entities"].items():
                    key = f"{app}.{ent}"
                    cons = [c.split(" ")[0] for c in ent_data.get("constraints", [])]
                    map_data[key] = cons
        return map_data

    def _is_valid_node_label(self, label):
        if not label:
            return False
        label_lower = label.lower()
        for term in self.blacklisted_terms:
            if term in label_lower:
                return False
        return True

    def _clean_constraint_value(self, pid, val):
        if not val:
            return None
        # P2047: 时长 (Seconds -> MM:SS)
        if pid == "P2047":
            try:
                seconds = int(float(val))
                return f"{seconds // 60}:{seconds % 60:02d}"
            except:
                return None
        # 日期只取年份
        if pid in ["P577", "P569", "P570"]:
            if "T" in val:
                return val.split("T")[0].split("-")[0]
        # 忽略坐标
        if "Point(" in val:
            return None
        return val

    def _fetch_node_data(self, entity_id, type_key):
        """只获取 Config 定义的 Constraints，不再强制检查 P31 类型"""
        constraints_list = self.type_constraints.get(type_key, [])
        # 如果是 Person，多抓取一些强属性用于 Wiki 搜索验证
        if ".Person" in type_key:
            constraints_list = list(
                set(constraints_list + ["P26", "P22", "P25", "P40", "P166"])
            )

        if not constraints_list:
            return entity_id, {}

        values_clause = " ".join([f"wdt:{p}" for p in constraints_list])
        query = f"""
        SELECT ?p ?oLabel WHERE {{
          VALUES ?p {{ {values_clause} }}
          wd:{entity_id} ?p ?o .
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
        }} LIMIT 30
        """

        sparql = SPARQLWrapper("https://query.wikidata.org/sparql")
        sparql.setReturnFormat(JSON)
        sparql.setQuery(query)
        sparql.addCustomHttpHeader("User-Agent", f"NaturalGaia/Gen")

        data = {}
        try:
            results = sparql.query().convert()
            for r in results["results"]["bindings"]:
                p_id = r["p"]["value"].split("/")[-1]
                val = r.get("oLabel", {}).get("value")

                if val and not val.startswith("Q") and len(val) < 80:
                    clean_val = self._clean_constraint_value(p_id, val)
                    if clean_val:
                        if p_id in data:
                            if clean_val not in data[p_id]:
                                data[p_id] += f", {clean_val}"
                        else:
                            data[p_id] = clean_val
        except:
            pass
        return entity_id, data

    def _validate_step_uniqueness(self, step_data, context):
        """
        验证逻辑：
        1. 导航动作 (Click/Pick) -> 只要 Context 不为空最好，为空也放行 (信任链接)
        2. 搜索动作 (Search/Find) -> 必须有强约束 (Strong Constraints)
        """
        action = step_data.get("action", "")
        # 导航类动作：只要路径存在，通常都是可点击的链接，不需要强约束来搜索
        is_navigation = any(
            prefix in action
            for prefix in [
                "click_",
                "pick_",
                "artist_link",
                "zoom_",
                "check_",
                "filmography",
            ]
        )

        if is_navigation:
            return True, "Navigation"

        # 搜索类动作：必须有约束
        if not context:
            return False, "No constraints for search"

        # 强属性列表
        strong_props = [
            "P26",
            "P22",
            "P25",
            "P40",
            "P166",
            "P106",
            "P175",
            "P264",
            "P569",
            "P577",
        ]
        if any(pid in strong_props for pid in context):
            return True, "Strong constraints"

        return False, "Weak constraints"

    def generate_tasks(self, G, total_paths=20, min_len=3, max_len=6):
        logger.info("--- Stage 2: Generating Tasks (Permissive Mode) ---")
        rng = random.Random(self.seed_val)
        tasks = []
        nodes = list(G.nodes())

        if len(nodes) < 2:
            return []

        attempts = 0
        pbar = tqdm(total=total_paths, desc="Drafting")

        while len(tasks) < total_paths:
            if attempts > total_paths * 500:
                break
            attempts += 1

            candidates = sorted(nodes, key=lambda n: self.global_node_usage.get(n, 0))
            top_k = max(1, int(len(nodes) * 0.3))
            start_node = rng.choice(candidates[:top_k])

            start_label = G.nodes[start_node].get("label", start_node)
            if not self._is_valid_node_label(start_label):
                continue

            path = [start_node]
            curr = start_node
            steps = []
            apps_used = []
            local_visited = {start_node}

            target_len = rng.randint(min_len, max_len)
            valid_walk = True

            for _ in range(target_len):
                neighbors = list(G.successors(curr))
                valid_neighbors = [n for n in neighbors if n not in local_visited]

                if not valid_neighbors:
                    valid_walk = False
                    break

                selected_n = rng.choice(valid_neighbors)

                to_label = G.nodes[selected_n].get("label", selected_n)
                if not self._is_valid_node_label(to_label):
                    valid_walk = False
                    break

                edge_data_raw = G.get_edge_data(curr, selected_n)
                if G.is_multigraph():
                    edge_key = rng.choice(list(edge_data_raw.keys()))
                    edge = edge_data_raw[edge_key]
                else:
                    edge = edge_data_raw

                # 不再检查 required_source_type，信任图谱结构

                from_lbl = G.nodes[curr].get("label", curr)
                steps.append(
                    {
                        "step_idx": len(steps) + 1,
                        "from_id": curr,
                        "to_id": selected_n,
                        "from": from_lbl,
                        "to": to_label,
                        "app": edge["app"],
                        "action": edge["action_key"],
                        "target_type": edge["target_type"],
                        "intent_template": edge.get("action_intent", "find the target"),
                        "description": "",
                    }
                )

                apps_used.append(edge["app"])
                path.append(selected_n)
                local_visited.add(selected_n)
                curr = selected_n

            unique_apps = set(apps_used)
            if valid_walk and len(steps) >= min_len and len(unique_apps) >= 2:
                tasks.append(
                    {
                        "task_id": f"temp_{len(tasks)}",
                        "meta": {"complexity": len(steps), "apps": list(unique_apps)},
                        "input_prompt_skeleton": {
                            "start": steps[0]["from"],
                            "end": steps[-1]["to"],
                        },
                        "ground_truth": {
                            "final_answer": steps[-1]["to"],
                            "path": steps,
                        },
                    }
                )
                pbar.update(0.5)

        pbar.close()

        logger.info(f"Validating {len(tasks)} candidate tasks...")

        query_jobs = set()
        for t in tasks:
            for step in t["ground_truth"]["path"]:
                if step.get("to_id") and step.get("target_type"):
                    key = f"{step['app']}.{step['target_type']}"
                    # 总是查询，即使不在 Config 里（会返回空，但流程能走下去）
                    query_jobs.add((step["to_id"], key))

        results_map = {}
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            future_to_job = {
                executor.submit(self._fetch_node_data, j[0], j[1]): j[0]
                for j in query_jobs
            }
            for future in tqdm(
                as_completed(future_to_job),
                total=len(query_jobs),
                desc="Fetching Context",
            ):
                eid, data = future.result()
                if eid not in results_map:
                    results_map[eid] = {}
                results_map[eid].update(data)

        final_valid_tasks = []

        for t in tasks:
            is_task_viable = True
            final_path = []

            for step in t["ground_truth"]["path"]:
                eid = step.get("to_id")
                context = results_map.get(eid, {})
                step["context"] = context

                # 验证唯一性 (Navigation 总是通过，Search 需强约束)
                is_valid, reason = self._validate_step_uniqueness(step, context)

                if not is_valid:
                    # 记录丢弃原因以便调试
                    # logger.warning(f"Discarded Step: {step['action']} -> {step['to']}: {reason}")
                    is_task_viable = False
                    break

                # 生成描述
                app_name = step["app"]
                start_label = step["from"]
                intent = step.get("intent_template", "find the target")
                base_desc = f"Use {app_name} to find '{start_label}' and {intent}"

                if context:
                    # 将约束格式化为自然语言列表
                    strong_props = [
                        "P26",
                        "P22",
                        "P166",
                        "P106",
                        "P175",
                        "P264",
                        "P569",
                        "P577",
                    ]
                    sorted_keys = sorted(
                        context.keys(), key=lambda k: 0 if k in strong_props else 1
                    )
                    cons_list = [f"{context[k]}" for k in sorted_keys[:4]]
                    cons_str = ", ".join(cons_list)
                    step["description"] = f"{base_desc} (Constraints: {cons_str})"
                else:
                    step["description"] = base_desc

                final_path.append(step)

            if is_task_viable:
                for step in final_path:
                    self.global_node_usage[step["to_id"]] = (
                        self.global_node_usage.get(step["to_id"], 0) + 1
                    )

                t["task_id"] = f"task_{self.seed_val}_{len(final_valid_tasks)}"
                t["ground_truth"]["path"] = final_path
                final_valid_tasks.append(t)

        filepath = os.path.join(
            self.data_dir, "tasks", f"tasks_{self.seed_val}_verified.json"
        )
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(final_valid_tasks, f, ensure_ascii=False, indent=2)

        logger.info(
            f"Generated {len(final_valid_tasks)} verified tasks. Saved to {filepath}"
        )
        return final_valid_tasks, filepath
