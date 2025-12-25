import json
import os
import yaml
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
from openai import OpenAI
import argparse

# 设置简单的日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/paraphrase.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


class LLMParaphraser:
    def __init__(self, config_path="config/llm_config.yaml", provider_name=None):
        self.config = self._load_config(config_path)

        # 确定使用哪个 Provider
        selected_provider = provider_name or self.config.get(
            "default_provider", "openai"
        )
        provider_config = self.config["providers"][selected_provider]

        self.api_key = os.getenv("LLM_API_KEY") or provider_config["api_key"]
        self.base_url = provider_config["base_url"]
        self.model = provider_config["model"]
        self.concurrency = provider_config.get("concurrency", 3)

        # 初始化 OpenAI Client (这是目前兼容性最好的 SDK)
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

        logger.info(
            f"LLM Paraphraser initialized with provider: {selected_provider} (Model: {self.model})"
        )

    def _load_config(self, path):
        if not os.path.exists(path):
            raise FileNotFoundError(f"Config file {path} not found.")
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _construct_prompt(self, task_data):
        """
        构建高效的 Prompt。
        策略：仅提供必要的元数据，减少 Token 消耗。
        """
        start = task_data["input_prompt_skeleton"]["start"]
        end = task_data["input_prompt_skeleton"]["end"]
        steps = task_data["ground_truth"]["path"]

        # 将复杂的 JSON 步骤压缩为简单的文本链，节省 Token
        # 格式: Step 1: [Music] Find Taylor Swift -> Step 2: [Geo] Find USA...
        path_desc = " -> ".join(
            [f"Step {s['step_idx']} ({s['domain']}): {s['intent']}" for s in steps]
        )

        system_prompt = (
            "You are an expert dataset creator for GUI Agents. "
            "Your goal is to convert a structured logical path into a natural, realistic user query."
        )

        user_prompt = f"""
        **Context**: A user wants to find information starting from entity "{start}" and ending at "{end}".
        
        **Logical Path**:
        {path_desc}
        
        **Task**:
        1. Write a natural language query that a human would ask an AI Assistant.
        2. The query must imply the need for multi-step reasoning or using multiple apps (Music, Maps, Wiki, etc.).
        3. Do NOT explicitly list the steps. Make it sound like a curiosity-driven question or a specific request.
        4. Return ONLY the JSON object with the key "natural_query".
        
        **Example Output**:
        {{"natural_query": "I was listening to Taylor Swift and wondered, which city was her spouse born in?"}}
        """
        return system_prompt, user_prompt

    def process_single_task(self, task):
        """处理单个任务的函数，供线程池调用"""
        task_id = task.get("task_id", "unknown")

        # 如果已经有润色过的 query，跳过（断点续传）
        if "refined_query" in task:
            return task

        system_msg, user_msg = self._construct_prompt(task)

        retries = 3
        for attempt in range(retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": user_msg},
                    ],
                    temperature=0.7,
                    response_format={"type": "json_object"},  # 强制 JSON 输出，防止废话
                )

                content = response.choices[0].message.content
                result_json = json.loads(content)

                # 将结果回写到 task 对象中
                task["refined_query"] = result_json.get("natural_query", "")
                return task

            except Exception as e:
                logger.warning(
                    f"Task {task_id} failed (Attempt {attempt+1}/{retries}): {e}"
                )
                time.sleep(2 * (attempt + 1))  # 指数退避

        logger.error(f"Task {task_id} permanently failed.")
        task["refined_query"] = None  # 标记失败
        return task

    def run_batch(self, input_file, output_file):
        """主入口：并发处理"""
        if not os.path.exists(input_file):
            logger.error(f"Input file {input_file} not found.")
            return

        with open(input_file, "r", encoding="utf-8") as f:
            tasks = json.load(f)

        logger.info(
            f"Loaded {len(tasks)} tasks. Starting parallel processing (Workers: {self.concurrency})..."
        )

        results = []
        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            # 提交任务
            future_to_task = {
                executor.submit(self.process_single_task, t): t for t in tasks
            }

            # 进度条
            for future in tqdm(
                as_completed(future_to_task), total=len(tasks), desc="Paraphrasing"
            ):
                try:
                    res = future.result()
                    results.append(res)
                except Exception as e:
                    logger.error(f"Worker exception: {e}")

        # 过滤掉失败的任务
        success_tasks = [t for t in results if t.get("refined_query")]

        # 保存
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(success_tasks, f, ensure_ascii=False, indent=2)

        logger.info(
            f"Done. {len(success_tasks)}/{len(tasks)} tasks paraphrased successfully."
        )
        logger.info(f"Saved to {output_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLM Paraphraser for Benchmark Tasks")
    parser.add_argument(
        "--input",
        default="data/tasks/tasks_2025_optimized.json",
        help="Path to raw tasks json",
    )
    parser.add_argument(
        "--output",
        default="data/tasks/refined/tasks_final.json",
        help="Path to save refined tasks",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="Override provider in config (e.g., openai, deepseek)",
    )

    args = parser.parse_args()

    # 检查输入文件是否存在
    if not os.path.exists(args.input):
        print(
            f"Error: Input file {args.input} does not exist. Please run main.py first."
        )
        exit(1)

    paraphraser = LLMParaphraser(provider_name=args.provider)
    paraphraser.run_batch(args.input, args.output)
