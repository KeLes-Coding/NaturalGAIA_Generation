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
                "https://api.openai.com/v1",
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

            for future in tqdm(
                as_completed(future_to_task), total=len(tasks), desc="LLM Refining"
            ):
                try:
                    res = future.result()
                    results.append(res)
                except Exception as e:
                    logger.error(f"Critical Worker Error: {e}")

        success_tasks = [t for t in results if t.get("refined_query")]

        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(success_tasks, f, ensure_ascii=False, indent=2)

        logger.info(f"Saved {len(success_tasks)} refined tasks to {output_file}")
        if len(success_tasks) == 0:
            logger.warning(
                "No tasks were saved! PLEASE CHECK THE LOG FILE (logs/run_xxx.log) FOR DETAILS."
            )

    def _process_single(self, task):
        """处理单个任务，包含详细的 Debug 日志"""
        if "refined_query" in task:
            return task

        # --- 1. 构建 Prompt ---
        start_entity = task["input_prompt_skeleton"]["start"]
        # 收集所有必须被“隐藏”的实体（中间节点 + 最终答案）
        forbidden_entities = []
        path_desc = []

        for idx, step in enumerate(task["ground_truth"]["path"]):
            target = step["to"]
            forbidden_entities.append(target)
            intent = (
                step.get("tool", "")
                .replace("get_", "")
                .replace("search_", "")
                .replace("_", " ")
            )
            path_desc.append(
                f"Step {idx+1}: Use App '{step.get('app')}' to find '{target}' (Intent: {intent})."
            )

        path_str = "\n".join(path_desc)
        forbidden_str = ", ".join([f"'{e}'" for e in forbidden_entities])

        system_msg = (
            "You are a user constructing a complex, multi-step instruction for a GUI Agent. "
            "Output ONLY JSON object."
        )

        user_msg = f"""
        **Mission**: Generate a "Stream of Consciousness" style user query.

        **Input**:
        Start: "{start_entity}"
        Path:
        {path_str}

        **RULES**:
        1. **NO SPOILERS**: DO NOT mention these targets: [{forbidden_str}]. Use "that city", "the year", etc.
        2. **NARRATIVE**: Write a flow of thoughts (Motivation -> Action 1 -> Action 2).
        3. **FORMAT**: Return JSON with key "natural_query".

        **Example**:
        {{ "natural_query": "I am looking for... please use Spotify to..." }}
        """

        retries = 3
        for attempt in range(retries):
            try:
                # 注意：移除了 response_format 以防止 400 错误，靠 _clean_json_string 处理
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": user_msg},
                    ],
                    temperature=0.8,
                )
                content = response.choices[0].message.content

                # --- 清洗与解析 ---
                cleaned_content = self._clean_json_string(content)

                try:
                    parsed_json = json.loads(cleaned_content)
                    query = parsed_json.get("natural_query", "")

                    if not query:
                        raise ValueError("Empty query generated")

                    # 检查是否泄露答案 (简单检查)
                    for forbidden in forbidden_entities:
                        if forbidden.lower() in query.lower():
                            logger.warning(
                                f"[Task {task.get('task_id')}] Retry: Leaked answer '{forbidden}'"
                            )
                            raise ValueError(f"Leaked answer: {forbidden}")

                    task["refined_query"] = query
                    return task

                except json.JSONDecodeError:
                    logger.error(
                        f"[Task {task.get('task_id')}] JSON Fail (Attempt {attempt+1})"
                    )
                    logger.error(
                        f"   >>> Raw Content: {content[:500]}..."
                    )  # 打印前500字符
                    logger.error(f"   >>> Cleaned: {cleaned_content}")
                    continue
                except ValueError as ve:
                    # 捕获逻辑校验错误（如泄露答案）
                    continue

            except Exception as e:
                logger.error(
                    f"[Task {task.get('task_id')}] API/Net Error (Attempt {attempt+1}): {e}"
                )
                time.sleep(1)

        task["refined_query"] = None
        return task

    def _clean_json_string(self, content):
        """
        强力清洗：
        1. 去除 <think>...</think> 标签 (DeepSeek 特性)
        2. 去除 ```json 代码块
        3. 寻找最外层 {}
        """
        content = content.strip()

        # 1. 去除 DeepSeek 的 <think> 标签
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

        # 2. 去除 Markdown 代码块
        pattern = r"```(?:json)?\s*(.*?)\s*```"
        match = re.search(pattern, content, re.DOTALL)
        if match:
            content = match.group(1).strip()

        # 3. 寻找 JSON 对象边界
        start = content.find("{")
        end = content.rfind("}")

        if start != -1 and end != -1 and end > start:
            return content[start : end + 1]

        return content
