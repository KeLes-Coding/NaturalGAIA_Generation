import os
import json
import time
import re
import httpx
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
from openai import OpenAI
from src.utils import logger, load_yaml_config


class LLMClient:
    def __init__(self, config_path="config/llm_config.yaml", provider_name=None):
        if not os.path.exists(config_path):
            logger.warning(f"{config_path} not found. Using env vars.")
            self.api_key = os.getenv("OPENAI_API_KEY")
            self.base_url = os.getenv(
                "OPENAI_BASE_URL",
                "[https://api.openai.com/v1](https://api.openai.com/v1)",
            )
            self.model = "gpt-3.5-turbo"
            self.concurrency = 3
            self.proxy = None
        else:
            self.config = load_yaml_config(config_path)
            selected = provider_name or self.config.get("default_provider", "openai")
            provider = self.config["providers"][selected]

            self.api_key = provider.get("api_key") or os.getenv("LLM_API_KEY")
            self.base_url = provider.get("base_url")
            self.model = provider.get("model")
            self.concurrency = provider.get("concurrency", 3)
            self.proxy = self.config.get("proxy")

        # --- 配置带有代理的 HTTP Client ---
        http_client = None
        if self.proxy:
            logger.info(f"Using Proxy: {self.proxy}")
            # 增加超时设置，防止代理慢导致报错
            http_client = httpx.Client(proxy=self.proxy, timeout=60.0)
        else:
            http_client = httpx.Client(timeout=60.0)

        self.client = OpenAI(
            api_key=self.api_key, base_url=self.base_url, http_client=http_client
        )
        logger.info(f"LLM Client init: {self.base_url} (Model: {self.model})")

    def paraphrase_tasks(self, input_file, output_file):
        if not os.path.exists(input_file):
            logger.error(f"Input file {input_file} not found.")
            return

        with open(input_file, "r", encoding="utf-8") as f:
            tasks = json.load(f)

        logger.info(
            f"Paraphrasing {len(tasks)} tasks with concurrency {self.concurrency}..."
        )

        results = []
        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            future_to_task = {
                executor.submit(self._process_single, t): t for t in tasks
            }

            # 使用 tqdm 并在出错时打印
            for future in tqdm(
                as_completed(future_to_task), total=len(tasks), desc="LLM Refining"
            ):
                try:
                    res = future.result()
                    results.append(res)
                except Exception as e:
                    tqdm.write(f"Critical Worker Error: {e}")  # 直接打印到控制台

        success_tasks = [t for t in results if t.get("refined_query")]

        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(success_tasks, f, ensure_ascii=False, indent=2)

        logger.info(f"Saved {len(success_tasks)} refined tasks to {output_file}")
        if len(success_tasks) == 0:
            logger.warning(
                "No tasks were saved! Check the console logs above for API errors."
            )

    def _process_single(self, task):
        if "refined_query" in task:
            return task

        system_msg = "You are an AI dataset creator. Convert the logical path into a natural user query. Output ONLY JSON."
        steps_str = " -> ".join(
            [f"[{s['domain']}] Find {s['to']}" for s in task["ground_truth"]["path"]]
        )

        user_msg = f"""
        Goal: Find "{task['ground_truth']['final_answer']}" starting from "{task['input_prompt_skeleton']['start']}".
        Logical Path: {steps_str}
        
        Task: Write a natural question asking for this information without revealing the steps explicitly.
        Output Format: JSON with key "natural_query".
        Example: {{"natural_query": "Which city was the director of 'Inception' born in?"}}
        """

        retries = 3
        for attempt in range(retries):
            try:
                # 注意：有些第三方 API 不完全支持 response_format={"type": "json_object"}
                # 如果依然报错，可以尝试把这一行删掉
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": user_msg},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.7,
                )
                content = response.choices[0].message.content

                # --- 增强的 JSON 清洗与解析 ---
                cleaned_content = self._clean_json_string(content)

                try:
                    parsed_json = json.loads(cleaned_content)
                    task["refined_query"] = parsed_json.get("natural_query", "")
                    return task
                except json.JSONDecodeError:
                    tqdm.write(
                        f"JSON Parse Error for Task {task.get('task_id')}: {content[:100]}..."
                    )
                    # 只有解析失败才重试
                    continue

            except Exception as e:
                tqdm.write(f"API Error (Attempt {attempt+1}): {e}")
                time.sleep(2)

        task["refined_query"] = None
        return task

    def _clean_json_string(self, content):
        """
        清洗 LLM 返回的字符串，去除 Markdown 代码块标记
        例如: ```json { "key": "value" } ``` -> { "key": "value" }
        """
        content = content.strip()
        # 使用正则去除 ```json 和 ```
        pattern = r"^```(?:json)?\s*(.*?)\s*```$"
        match = re.search(pattern, content, re.DOTALL)
        if match:
            return match.group(1)
        return content
