import json
import os
import sys
from pathlib import Path


class ConfigManager:
    def __init__(self, registry_path="config/app_registry.json"):
        # 自动定位项目根目录，确保路径绝对正确
        self.root_dir = self._find_project_root()
        self.registry_path = self.root_dir / registry_path
        self.full_config = {"domains": {}}

    def _find_project_root(self):
        """向上查找，定位包含 config 文件夹的根目录"""
        current = Path(os.getcwd())
        # 简单的启发式查找：如果在当前或父级找不到config，可能需要根据你的具体项目结构调整
        if (current / "config").exists():
            return current
        if (current.parent / "config").exists():
            return current.parent
        # 如果找不到，假定当前运行目录就是根目录
        return current

    def load_config(self):
        """加载注册表并递归合并所有子配置"""
        print(f"[Config] Loading registry from: {self.registry_path}")

        if not self.registry_path.exists():
            raise FileNotFoundError(
                f"CRITICAL: Registry file not found at {self.registry_path}"
            )

        try:
            with open(self.registry_path, "r", encoding="utf-8") as f:
                registry = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"CRITICAL: Registry JSON is invalid. Error: {e}")

        # 遍历注册表中的 domains
        # 假设 registry 结构为: {"app_sources": {"Multimedia": "config/domains/multimedia.json", ...}}
        sources = registry.get("app_sources", {})
        active_domains = registry.get("active_domains", [])

        if not sources:
            raise ValueError("CRITICAL: No 'app_sources' defined in registry.")

        for domain, relative_path in sources.items():
            # 只有在 active_domains 中的才会被加载（如果你在 json 里做了开关控制）
            # 如果 json 里没有 active_domains 字段，默认全部加载
            if active_domains and domain not in active_domains:
                print(f"[Config] Skipping disabled domain: {domain}")
                continue

            file_path = self.root_dir / relative_path

            if not file_path.exists():
                raise FileNotFoundError(
                    f"CRITICAL: Domain config for '{domain}' missing at {file_path}"
                )

            try:
                with open(file_path, "r", encoding="utf-8") as df:
                    domain_data = json.load(df)

                    # 健壮性检查：确保子文件里有 'apps' 字段
                    if "apps" not in domain_data:
                        # 如果没有 apps 层级，可能是直接定义的，我们尝试自动修正结构
                        # 但作为严格的专家，我建议你强制要求 json 结构统一
                        print(
                            f"[Warning] Domain '{domain}' config missing 'apps' key. Assuming flat structure."
                        )
                        # 视具体情况，可能需要 domain_data = {"apps": domain_data}

                    self.full_config["domains"][domain] = domain_data
                    print(
                        f"[Config] Loaded domain: {domain} ({len(domain_data.get('apps', {}))} apps)"
                    )

            except json.JSONDecodeError as e:
                raise ValueError(
                    f"CRITICAL: Config for '{domain}' is invalid JSON. Error: {e}"
                )

        return self.full_config


# 全局单例接口
def get_config():
    manager = ConfigManager()
    return manager.load_config()
