import os
import json
import yaml
import logging
from datetime import datetime


# --- 原有的 setup_logger 保持不变 ---
def setup_logger(name="BenchmarkBuilder", log_dir="logs"):
    """配置并返回一个全局 Logger"""
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"run_{timestamp}.log")

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    if logger.hasHandlers():
        logger.handlers.clear()

    # 文件 Handler
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(threadName)s - %(message)s"
    )
    file_handler.setFormatter(file_formatter)

    # 控制台 Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter("%(levelname)s: %(message)s")
    console_handler.setFormatter(console_formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    logger.info(f"Logger initialized. Saving logs to: {log_file}")
    return logger


# --- 原有的 load_json_config 保持不变 ---
def load_json_config(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Config file {path} not found.")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_yaml_config(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Config file {path} not found.")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# --- 【新增】 模块化配置加载器 ---
def load_registry_config(registry_path):
    """
    读取注册表并合并所有子域配置文件。
    返回结构与旧版 tools_config.json 完全一致：
    { "domains": { "Multimedia": { "apps": ... }, ... } }
    """
    logger = logging.getLogger("BenchmarkBuilder")
    if not os.path.exists(registry_path):
        raise FileNotFoundError(f"Registry file {registry_path} not found.")

    logger.info(f"Loading App Registry from: {registry_path}")
    with open(registry_path, "r", encoding="utf-8") as f:
        registry = json.load(f)

    merged_config = {"domains": {}}

    # 遍历 app_sources
    sources = registry.get("app_sources", {})
    active_list = registry.get("active_domains", [])

    for domain_name, rel_path in sources.items():
        # 如果定义了 active_domains 且当前 domain 不在其中，则跳过
        if active_list and domain_name not in active_list:
            logger.info(f"[Config] Skipping disabled domain: {domain_name}")
            continue

        # 路径处理：假设路径是相对于项目根目录的
        if not os.path.exists(rel_path):
            logger.warning(
                f"[Config] ⚠️ Missing config file for {domain_name}: {rel_path}"
            )
            continue

        try:
            with open(rel_path, "r", encoding="utf-8") as sub_f:
                domain_data = json.load(sub_f)
                # 将子文件内容挂载到 domains 下
                merged_config["domains"][domain_name] = domain_data
                logger.info(f"[Config] Loaded domain: {domain_name} from {rel_path}")
        except json.JSONDecodeError:
            logger.error(f"[Config] ❌ Invalid JSON in {rel_path}")
        except Exception as e:
            logger.error(f"[Config] ❌ Error loading {domain_name}: {str(e)}")

    return merged_config


# 初始化一个默认 logger 供模块使用
logger = logging.getLogger("BenchmarkBuilder")
