import json
import requests
import sys
import os
from src.utils import load_json_config


def debug_entity_mapping(entity_id, config_file="config/tools_config.json"):
    """
    Schema Debugger V3:
    1. 双向查询 (Forward & Reverse)
    2. 过滤掉所有非 Q-ID 的噪音数据 (FILTER isIRI)
    3. 验证 Type Filter 是否覆盖了真实数据
    """
    print(f"Loading config from: {config_file}")
    config = load_json_config(config_file)

    # --- 1. 建立 Config 映射表 ---
    # map[PID] = [ { app, action, direction, allowed_types } ]
    prop_constraints = {}

    for domain, d_data in config["domains"].items():
        for app, app_data in d_data["apps"].items():
            for ent, ent_data in app_data["entities"].items():
                for action_key, action in ent_data.get("actions", {}).items():
                    rel = action["relation"]
                    target_ent_name = action["target"]

                    # 获取目标类型的白名单
                    target_ent_def = app_data["entities"].get(target_ent_name, {})
                    # 兼容不同字段名
                    allowed = set(
                        target_ent_def.get("type_filter")
                        or target_ent_def.get("target_filters")
                        or []
                    )

                    # 识别方向
                    if rel.startswith("reverse_"):
                        clean_pid = rel.replace("reverse_", "").split("_")[0]
                        direction = "reverse"
                    else:
                        clean_pid = rel
                        direction = "forward"

                    if clean_pid not in prop_constraints:
                        prop_constraints[clean_pid] = []

                    prop_constraints[clean_pid].append(
                        {
                            "app": app,
                            "action": action_key,
                            "direction": direction,
                            "target_types": allowed,
                        }
                    )

    print(f"--- Debugging Entity: {entity_id} ---")
    print(f"Monitoring {len(prop_constraints)} properties from Config.")

    # --- 2. 构造 SPARQL (关键修改：FILTER isIRI + UNION 查询) ---
    query = f"""
    SELECT ?direction ?p ?pLabel ?neighbor ?neighborLabel ?type ?typeLabel WHERE {{
      {{
        # Forward: Entity -> Neighbor
        BIND("forward" AS ?direction)
        wd:{entity_id} ?p ?neighbor .
        # 核心过滤：必须是 Wikidata Item (Q...)，排除字符串/URL
        FILTER(isIRI(?neighbor) && STRSTARTS(STR(?neighbor), "http://www.wikidata.org/entity/Q"))
      }}
      UNION
      {{
        # Reverse: Neighbor -> Entity
        BIND("reverse" AS ?direction)
        ?neighbor ?p wd:{entity_id} .
        FILTER(isIRI(?neighbor) && STRSTARTS(STR(?neighbor), "http://www.wikidata.org/entity/Q"))
      }}

      # 只查询 Config 里定义的属性，大大减少无关数据
      VALUES ?p {{ {' '.join(['wdt:'+k for k in prop_constraints.keys()])} }}

      # 获取类型
      OPTIONAL {{ ?neighbor wdt:P31 ?type . }}
      
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }} LIMIT 200
    """

    try:
        url = "https://query.wikidata.org/sparql"
        print("Sending filtered SPARQL query...")
        r = requests.get(
            url,
            params={"format": "json", "query": query},
            headers={"User-Agent": "GaiaDebugger"},
        )
        data = r.json()
    except Exception as e:
        print(f"SPARQL Error: {e}")
        return

    results = data["results"]["bindings"]
    print(f"Found {len(results)} relevant connections.\n")

    # 表头
    header = f"{'DIR':<8} | {'PID':<6} | {'NEIGHBOR (ID)':<30} | {'TYPE (ID)':<30} | {'STATUS':<8} | {'REASON'}"
    print(header)
    print("-" * 130)

    # --- 3. 分析结果 ---
    for item in results:
        direction = item["direction"]["value"]
        p_url = item["p"]["value"]
        p_id = p_url.split("/")[-1]

        n_url = item.get("neighbor", {}).get("value", "")
        n_id = n_url.split("/")[-1]
        n_label = item.get("neighborLabel", {}).get("value", n_id)

        t_url = item.get("type", {}).get("value", "")
        t_id = t_url.split("/")[-1] if t_url else "NoType"
        t_label = item.get("typeLabel", {}).get("value", "")

        type_display = f"{t_label} ({t_id})" if t_id != "NoType" else "No Type"

        # 匹配逻辑
        status = "IGNORE"
        reasons = []

        if p_id in prop_constraints:
            potential_rules = prop_constraints[p_id]

            for rule in potential_rules:
                # 1. 检查方向是否匹配
                if rule["direction"] != direction:
                    continue

                # 2. 检查类型是否匹配
                allowed = rule["target_types"]
                if not allowed:
                    status = "PASS"
                    reasons.append(f"✅{rule['app']}(NoFilter)")
                elif t_id in allowed:
                    status = "PASS"
                    reasons.append(f"✅{rule['app']}[{rule['action']}]")
                else:
                    # 这是一个潜在的匹配，但类型不对，需要记录下来告诉用户
                    if status != "PASS":
                        status = "DROP"
                    reasons.append(f"❌{rule['app']}:Wanted {list(allowed)[:2]}...")

        if not reasons:
            reasons = ["Wrong Direction"]

        final_reason = " | ".join(set(reasons))

        # 打印
        print(
            f"{direction:<8} | {p_id:<6} | {n_label[:25]+' ('+n_id+')':<30} | {type_display[:30]:<30} | {status:<8} | {final_reason}"
        )


if __name__ == "__main__":
    debug_entity_mapping("Q26876")  # Taylor Swift
