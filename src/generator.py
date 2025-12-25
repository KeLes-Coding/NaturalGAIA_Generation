import networkx as nx
import random
import os
import json
from tqdm import tqdm
from src.utils import logger


class TaskGenerator:
    def __init__(self, seed_val=2025, data_dir="data"):
        self.seed_val = seed_val
        self.data_dir = data_dir
        os.makedirs(os.path.join(self.data_dir, "tasks"), exist_ok=True)

    def generate_tasks(self, G, total_paths=20, min_len=3, max_len=6):
        logger.info("--- Stage 2: Generating Scenarios (Optimized Logic) ---")
        rng = random.Random(self.seed_val)
        tasks = []
        nodes = list(G.nodes())

        if len(nodes) < 2:
            return []

        attempts = 0
        max_attempts = total_paths * 500
        pbar = tqdm(total=total_paths, desc="Generating Tasks")

        while len(tasks) < total_paths:
            if attempts > max_attempts:
                logger.warning("Max attempts reached.")
                break
            attempts += 1

            start_node = rng.choice(nodes)
            path = [start_node]
            curr = start_node
            steps = []
            apps_used = []
            domains_used = []

            target_len = rng.randint(min_len, max_len)
            valid_walk = True

            for _ in range(target_len):
                neighbors = list(G.successors(curr))

                # --- 优化策略 1: 智能筛选 ---
                candidates = []
                for n in neighbors:
                    if n in path:
                        continue  # 禁止环路
                    if n == curr:
                        continue  # 禁止自环
                    edge = G.get_edge_data(curr, n)
                    candidates.append((n, edge))

                if not candidates:
                    valid_walk = False
                    break

                # --- 优化策略 2: 域偏好打分 ---
                scored_candidates = []
                last_app = apps_used[-1] if apps_used else None
                last_domain = domains_used[-1] if domains_used else None

                for n, edge in candidates:
                    score = 1.0
                    if last_app and edge["app"] != last_app:
                        score += 2.0
                    if last_domain and edge["domain"] != last_domain:
                        score += 4.0
                    scored_candidates.append((n, edge, score))

                # 轮盘赌选择
                total_score = sum(s for _, _, s in scored_candidates)
                r = rng.uniform(0, total_score)
                upto = 0
                selected_n, selected_edge = None, None

                for n, edge, score in scored_candidates:
                    if upto + score >= r:
                        selected_n, selected_edge = n, edge
                        break
                    upto += score

                if selected_n is None:  # 兜底
                    selected_n, selected_edge = scored_candidates[-1][:2]

                # 记录
                start_label = G.nodes[curr].get("label", curr)
                next_label = G.nodes[selected_n].get("label", selected_n)

                steps.append(
                    {
                        "step_idx": len(steps) + 1,
                        "from": start_label,
                        "to": next_label,
                        "app": selected_edge["app"],
                        "tool": selected_edge["tool"],
                        "domain": selected_edge["domain"],
                        "description": f"Use {selected_edge['app']} to find {next_label} ({selected_edge['r_label']})",
                    }
                )
                apps_used.append(selected_edge["app"])
                domains_used.append(selected_edge["domain"])
                path.append(selected_n)
                curr = selected_n

            # --- 优化策略 3: 验收 ---
            unique_apps = set(apps_used)
            if valid_walk and len(steps) >= min_len and len(unique_apps) >= 2:
                start_label = G.nodes[path[0]].get("label", "Unknown")
                end_label = G.nodes[path[-1]].get("label", "Unknown")

                tasks.append(
                    {
                        "task_id": f"task_{self.seed_val}_{len(tasks)}",
                        "meta": {
                            "complexity_score": len(steps) + len(set(domains_used)) * 2,
                            "domain_path": domains_used,
                            "app_path": apps_used,
                        },
                        "input_prompt_skeleton": {
                            "start": start_label,
                            "end": end_label,
                            "type": "multi_hop_search",
                        },
                        "ground_truth": {"final_answer": end_label, "path": steps},
                    }
                )
                pbar.update(1)

        pbar.close()
        filepath = os.path.join(
            self.data_dir, "tasks", f"tasks_{self.seed_val}_optimized.json"
        )
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)
        logger.info(f"Generated {len(tasks)} tasks. Saved to {filepath}")
        return tasks, filepath
