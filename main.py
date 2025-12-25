import argparse
import os
from src.utils import setup_logger
from src.builder import GraphBuilder
from src.generator import TaskGenerator
from src.llm_client import LLMClient

# 初始化日志
logger = setup_logger()


def main():
    parser = argparse.ArgumentParser(description="Agentic Benchmark Builder")

    # --- 恢复你的默认设置 ---
    parser.add_argument(
        "--seed", type=int, default=2025, help="Random seed (default: 2025)"
    )
    parser.add_argument(
        "--workers", type=int, default=5, help="Crawler threads (default: 5)"
    )
    parser.add_argument(
        "--nodes", type=int, default=300, help="Max nodes in graph (default: 300)"
    )
    parser.add_argument(
        "--tasks", type=int, default=20, help="Total tasks to generate (default: 20)"
    )

    parser.add_argument(
        "--seed_entity",
        default="Q26876",
        help="Wikidata Item ID (default: Taylor Swift)",
    )
    parser.add_argument(
        "--seed_label", default="Taylor Swift", help="Label for seed entity"
    )
    parser.add_argument(
        "--skip_llm", action="store_true", help="Skip LLM refinement step"
    )

    args = parser.parse_args()

    logger.info(
        f"Starting Benchmark Builder with Seed: {args.seed}, Workers: {args.workers}, Target Tasks: {args.tasks}"
    )

    # --- 关键修正：定义正确的配置文件路径 ---
    tools_config_path = os.path.join("config", "tools_config.json")
    llm_config_path = os.path.join("config", "llm_config.yaml")

    # 1. 爬取与建图
    # 修正：传入 config_file 参数
    builder = GraphBuilder(
        config_file=tools_config_path, seed_val=args.seed, max_workers=args.workers
    )
    graph_file = f"app_graph_{args.seed}.json"

    G = builder.load_graph(graph_file)
    if G is None:
        G = builder.build_subgraph_parallel(
            args.seed_entity, max_nodes=args.nodes, max_branch=4
        )
        if G.has_node(args.seed_entity):
            G.nodes[args.seed_entity]["label"] = args.seed_label
        builder.save_graph(G, graph_file)
    else:
        if G.has_node(args.seed_entity):
            G.nodes[args.seed_entity]["label"] = args.seed_label

    # 2. 生成任务骨架
    generator = TaskGenerator(seed_val=args.seed)
    tasks, task_file = generator.generate_tasks(G, total_paths=args.tasks)

    # 3. LLM 润色 (可选)
    if not args.skip_llm:
        logger.info("Starting LLM Refinement...")
        # 修正：传入 config_path 参数
        llm_client = LLMClient(config_path=llm_config_path)
        refined_file = os.path.join("data", "tasks", f"tasks_{args.seed}_refined.json")
        llm_client.paraphrase_tasks(task_file, refined_file)
    else:
        logger.info("Skipping LLM refinement.")


if __name__ == "__main__":
    main()
