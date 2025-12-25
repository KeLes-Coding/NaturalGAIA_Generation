import os
import json
import yaml
import logging
from datetime import datetime


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


# 加载配置的辅助函数
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


# 初始化一个默认 logger 供模块使用
logger = logging.getLogger("BenchmarkBuilder")
