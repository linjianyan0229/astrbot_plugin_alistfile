import asyncio
import json
import os
import hashlib
import time
import tempfile
from typing import List, Dict, Optional
from urllib.parse import urljoin, quote, urlparse
import aiohttp

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain, Image, File
from astrbot.api import logger
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
from astrbot.api.event.filter import CustomFilter
from astrbot.core.config import AstrBotConfig


class FileUploadFilter(CustomFilter):
    """文件上传自定义过滤器 - 处理包含文件或图片的消息"""

    def filter(self, event: AstrMessageEvent, cfg: AstrBotConfig) -> bool:
        """检查消息是否包含文件或图片组件"""
        messages = event.get_messages()
        file_components = [msg for msg in messages if isinstance(msg, (File, Image))]
        return len(file_components) > 0


class AlistClient:
    """Alist API 客户端"""

    def __init__(
        self, base_url: str, username: str = "", password: str = "", token: str = ""
    ):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.token = token
        self.session = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        if not self.token and self.username and self.password:
            await self.login()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def login(self) -> bool:
        """登录获取token"""
        try:
            login_data = {"username": self.username, "password": self.password}

            async with self.session.post(
                f"{self.base_url}/api/auth/login", json=login_data
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    if result.get("code") == 200:
                        self.token = result.get("data", {}).get("token", "")
                        return True
                return False
        except Exception as e:
            logger.error(f"Alist登录失败: {e}")
            return False

    async def list_files(
        self, path: str = "/", page: int = 1, per_page: int = 30
    ) -> Optional[Dict]:
        """获取文件列表"""
        try:
            headers = {}
            if self.token:
                headers["Authorization"] = self.token

            list_data = {
                "path": path,
                "password": "",
                "page": page,
                "per_page": per_page,
                "refresh": False,
            }

            async with self.session.post(
                f"{self.base_url}/api/fs/list", json=list_data, headers=headers
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    if result.get("code") == 200:
                        return result.get("data")
                return None
        except Exception as e:
            logger.error(f"获取文件列表失败: {e}")
            return None

    async def get_file_info(self, path: str) -> Optional[Dict]:
        """获取文件信息"""
        try:
            headers = {}
            if self.token:
                headers["Authorization"] = self.token

            get_data = {"path": path, "password": ""}

            async with self.session.post(
                f"{self.base_url}/api/fs/get", json=get_data, headers=headers
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    if result.get("code") == 200:
                        return result.get("data")
                return None
        except Exception as e:
            logger.error(f"获取文件信息失败: {e}")
            return None

    async def search_files(self, keyword: str, path: str = "/") -> Optional[List[Dict]]:
        """搜索文件"""
        try:
            headers = {}
            if self.token:
                headers["Authorization"] = self.token

            search_data = {
                "parent": path,
                "keywords": keyword,
                "scope": 0,  # 0: 当前目录及子目录
                "page": 1,
                "per_page": 100,
            }

            async with self.session.post(
                f"{self.base_url}/api/fs/search", json=search_data, headers=headers
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    if result.get("code") == 200:
                        return result.get("data", {}).get("content", [])
                return []
        except Exception as e:
            logger.error(f"搜索文件失败: {e}")
            return []

    async def get_download_url(self, path: str) -> Optional[str]:
        """获取文件下载链接"""
        file_info = await self.get_file_info(path)
        if file_info and not file_info.get("is_dir", True):
            # 构建下载链接
            encoded_path = quote(path.encode("utf-8"))
            return f"{self.base_url}/d{encoded_path}"
        return None

    async def upload_file(
        self, file_path: str, target_path: str, filename: str = None
    ) -> bool:
        """上传文件到Alist

        Args:
            file_path: 本地文件路径
            target_path: 目标目录路径
            filename: 目标文件名（可选，默认使用原文件名）

        Returns:
            bool: 上传是否成功
        """
        try:
            if not os.path.exists(file_path):
                logger.error(f"文件不存在: {file_path}")
                return False

            if filename is None:
                filename = os.path.basename(file_path)

            # 构造上传URL
            upload_url = f"{self.base_url}/api/fs/put"

            # 准备上传数据
            with open(file_path, "rb") as f:
                file_data = f.read()

            # 构造请求头
            headers = {
                "Content-Type": "application/octet-stream",
                "File-Path": quote(f"{target_path.rstrip('/')}/{filename}", safe="/"),
            }

            # 如果有token，添加授权头
            if hasattr(self, "token") and self.token:
                headers["Authorization"] = self.token

            async with self.session.put(
                upload_url, data=file_data, headers=headers
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    return result.get("code") == 200
                else:
                    logger.error(f"上传失败，HTTP状态: {response.status}")
                    return False

        except Exception as e:
            logger.error(f"上传文件失败: {e}")
            return False


class UserConfigManager:
    """用户配置管理器 - 每个用户独立配置"""

    def __init__(self, plugin_name: str, user_id: str):
        self.plugin_name = plugin_name
        self.user_id = user_id
        # 使用 plugins_data 目录结构
        self.config_dir = os.path.join(
            get_astrbot_data_path(), "plugins_data", plugin_name, "users"
        )
        os.makedirs(self.config_dir, exist_ok=True)
        self.config_file = os.path.join(self.config_dir, f"{user_id}.json")
        self.default_config = {
            "alist_url": "",
            "username": "",
            "password": "",
            "token": "",
            "max_display_files": 20,
            "allowed_extensions": [
                ".txt",
                ".pdf",
                ".doc",
                ".docx",
                ".zip",
                ".rar",
                ".jpg",
                ".png",
                ".gif",
                ".mp4",
                ".mp3",
            ],
            "enable_preview": True,
            "setup_completed": False,  # 用户是否完成了初始配置
        }

    def load_config(self) -> Dict:
        """加载用户配置"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
                # 合并默认配置
                merged_config = self.default_config.copy()
                merged_config.update(config)
                return merged_config
            return self.default_config.copy()
        except Exception as e:
            logger.error(f"加载用户 {self.user_id} 配置失败: {e}")
            return self.default_config.copy()

    def save_config(self, config: Dict):
        """保存用户配置"""
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存用户 {self.user_id} 配置失败: {e}")

    def is_configured(self) -> bool:
        """检查用户是否已配置"""
        config = self.load_config()
        return config.get("setup_completed", False) and bool(config.get("alist_url"))


class CacheManager:
    """文件缓存管理器"""

    def __init__(self, plugin_name: str):
        self.plugin_name = plugin_name
        # 使用 plugins_data 目录结构
        self.cache_dir = os.path.join(
            get_astrbot_data_path(), "plugins_data", plugin_name, "cache"
        )
        os.makedirs(self.cache_dir, exist_ok=True)

    def _get_cache_key(self, url: str, path: str, user_id: str) -> str:
        """生成缓存键"""
        content = f"{url}:{path}:{user_id}"
        return hashlib.md5(content.encode("utf-8")).hexdigest()

    def _get_cache_file(self, cache_key: str) -> str:
        """获取缓存文件路径"""
        return os.path.join(self.cache_dir, f"{cache_key}.json")

    def get_cache(
        self, url: str, path: str, user_id: str, max_age: int = 300
    ) -> Optional[Dict]:
        """获取缓存"""
        try:
            cache_key = self._get_cache_key(url, path, user_id)
            cache_file = self._get_cache_file(cache_key)

            if not os.path.exists(cache_file):
                return None

            # 检查缓存是否过期
            if time.time() - os.path.getmtime(cache_file) > max_age:
                try:
                    os.remove(cache_file)
                except:
                    pass
                return None

            with open(cache_file, "r", encoding="utf-8") as f:
                cache_data = json.load(f)
                return cache_data.get("data")
        except Exception as e:
            logger.debug(f"读取缓存失败: {e}")
            return None

    def set_cache(self, url: str, path: str, user_id: str, data: Dict):
        """设置缓存"""
        try:
            cache_key = self._get_cache_key(url, path, user_id)
            cache_file = self._get_cache_file(cache_key)

            cache_data = {"timestamp": time.time(), "data": data}

            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug(f"写入缓存失败: {e}")

    def clear_cache(self, user_id: str = None):
        """清理缓存"""
        try:
            if user_id:
                # 清理指定用户的缓存
                for filename in os.listdir(self.cache_dir):
                    if filename.endswith(".json"):
                        cache_key = filename[:-5]  # 移除.json
                        # 简单检查缓存键是否包含用户ID（通过MD5不完美但够用）
                        test_key = self._get_cache_key("test", "test", user_id)
                        if user_id in test_key or cache_key.startswith(test_key[:8]):
                            try:
                                os.remove(os.path.join(self.cache_dir, filename))
                            except:
                                pass
            else:
                # 清理所有缓存
                for filename in os.listdir(self.cache_dir):
                    if filename.endswith(".json"):
                        try:
                            os.remove(os.path.join(self.cache_dir, filename))
                        except:
                            pass
        except Exception as e:
            logger.debug(f"清理缓存失败: {e}")


class GlobalConfigManager:
    """全局配置管理器"""

    def __init__(self, plugin_name: str):
        # 使用 plugins_data 目录结构
        self.config_dir = os.path.join(
            get_astrbot_data_path(), "plugins_data", plugin_name
        )
        os.makedirs(self.config_dir, exist_ok=True)
        self.config_file = os.path.join(self.config_dir, "global_config.json")
        self.default_config = {
            "default_alist_url": "",
            "max_display_files": 20,
            "allowed_extensions": ".txt,.pdf,.doc,.docx,.zip,.rar,.jpg,.png,.gif,.mp4,.mp3",
            "enable_preview": True,
            "require_user_auth": True,
        }

    def load_config(self) -> Dict:
        """加载全局配置"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
                # 合并默认配置
                merged_config = self.default_config.copy()
                merged_config.update(config)
                return merged_config
            return self.default_config.copy()
        except Exception as e:
            logger.error(f"加载全局配置失败: {e}")
            return self.default_config.copy()

    def save_config(self, config: Dict):
        """保存全局配置"""
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存全局配置失败: {e}")


@register(
    "alistfile",
    "linjianyan",
    "Alist文件管理插件",
    "1.0.0",
    "https://github.com/AstrBotDevs/astrbot_plugin_alistfile",
)
class AlistFilePlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)

        # 用户配置管理器
        self.user_config_managers = {}

        # 插件WebUI配置 (通过_conf_schema.json定义)
        self.config = config

        # 全局配置管理器（用于存储用户独立配置等）
        self.global_config_manager = GlobalConfigManager("alistfile")
        self.global_config = self.global_config_manager.load_config()

        # 缓存管理器
        self.cache_manager = CacheManager("alistfile")

        # 用户导航状态管理 {user_id: {"current_path": str, "items": List[Dict], "parent_paths": List[str]}}
        self.user_navigation_state = {}

        # 用户上传状态管理 {user_id: {"waiting": bool, "target_path": str}}
        self.user_upload_state = {}

    def get_webui_config(self, key: str, default=None):
        """获取WebUI配置项"""
        if self.config:
            return self.config.get("global_settings", {}).get(key, default)
        return default

    async def initialize(self):
        """插件初始化"""
        logger.info("Alist文件管理插件已加载")
        default_url = self.get_webui_config("default_alist_url", "")
        require_auth = self.get_webui_config("require_user_auth", True)

        if not default_url and not require_auth:
            logger.warning(
                "Alist URL未配置，请使用 /alist config 命令配置或在WebUI中配置"
            )

    def get_user_config_manager(self, user_id: str) -> UserConfigManager:
        """获取用户配置管理器"""
        if user_id not in self.user_config_managers:
            self.user_config_managers[user_id] = UserConfigManager("alistfile", user_id)
        return self.user_config_managers[user_id]

    def get_user_config(self, user_id: str) -> Dict:
        """获取用户配置，如果用户未配置则使用全局配置"""
        # 从WebUI获取配置
        require_user_auth = self.get_webui_config("require_user_auth", True)
        default_alist_url = self.get_webui_config("default_alist_url", "")
        default_username = self.get_webui_config("default_username", "")
        default_password = self.get_webui_config("default_password", "")
        default_token = self.get_webui_config("default_token", "")
        max_display_files = self.get_webui_config("max_display_files", 20)
        allowed_extensions = self.get_webui_config(
            "allowed_extensions",
            ".txt,.pdf,.doc,.docx,.zip,.rar,.jpg,.png,.gif,.mp4,.mp3",
        )
        enable_preview = self.get_webui_config("enable_preview", True)

        if require_user_auth:
            # 需要用户认证，使用用户独立配置
            user_manager = self.get_user_config_manager(user_id)
            user_config = user_manager.load_config()

            # 如果用户未配置，使用WebUI设置的默认值
            if not user_config.get("alist_url") and default_alist_url:
                user_config["alist_url"] = default_alist_url
            if not user_config.get("username") and default_username:
                user_config["username"] = default_username
            if not user_config.get("password") and default_password:
                user_config["password"] = default_password
            if not user_config.get("token") and default_token:
                user_config["token"] = default_token

            # 使用WebUI配置覆盖用户的部分设置
            user_config["max_display_files"] = max_display_files
            user_config["allowed_extensions"] = (
                allowed_extensions.split(",")
                if isinstance(allowed_extensions, str)
                else allowed_extensions
            )
            user_config["enable_preview"] = enable_preview

            return user_config
        else:
            # 不需要用户认证，使用全局配置
            return {
                "alist_url": default_alist_url,
                "username": default_username,
                "password": default_password,
                "token": default_token,
                "max_display_files": max_display_files,
                "allowed_extensions": allowed_extensions.split(",")
                if isinstance(allowed_extensions, str)
                else allowed_extensions,
                "enable_preview": enable_preview,
            }

    def _validate_config(self, user_config: Dict) -> bool:
        """验证配置"""
        return bool(user_config.get("alist_url"))

    def _get_user_navigation_state(self, user_id: str) -> Dict:
        """获取用户导航状态"""
        if user_id not in self.user_navigation_state:
            self.user_navigation_state[user_id] = {
                "current_path": "/",
                "items": [],
                "parent_paths": [],
            }
        return self.user_navigation_state[user_id]

    def _update_user_navigation_state(self, user_id: str, path: str, items: List[Dict]):
        """更新用户导航状态"""
        nav_state = self._get_user_navigation_state(user_id)

        # 如果是新路径，保存到历史
        if path != nav_state["current_path"]:
            # 只有在前进时才保存当前路径到历史
            if self._is_forward_navigation(nav_state["current_path"], path):
                nav_state["parent_paths"].append(nav_state["current_path"])

            nav_state["current_path"] = path

        nav_state["items"] = items

    def _is_forward_navigation(self, current_path: str, new_path: str) -> bool:
        """判断是否是前进导航（进入子目录）"""
        # 标准化路径
        current = current_path.rstrip("/")
        new = new_path.rstrip("/")

        # 如果新路径以当前路径开头，且比当前路径长，则认为是前进
        return new.startswith(current + "/") if current != "/" else new.startswith("/")

    def _get_item_by_number(self, user_id: str, number: int) -> Optional[Dict]:
        """根据序号获取文件/目录项"""
        nav_state = self._get_user_navigation_state(user_id)
        if 1 <= number <= len(nav_state["items"]):
            return nav_state["items"][number - 1]
        return None

    def _get_user_upload_state(self, user_id: str) -> Dict:
        """获取用户上传状态"""
        if user_id not in self.user_upload_state:
            self.user_upload_state[user_id] = {"waiting": False, "target_path": "/"}
        return self.user_upload_state[user_id]

    def _set_user_upload_waiting(
        self, user_id: str, waiting: bool, target_path: str = "/"
    ):
        """设置用户上传等待状态"""
        upload_state = self._get_user_upload_state(user_id)
        upload_state["waiting"] = waiting
        upload_state["target_path"] = target_path

    def _format_file_size(self, size: int) -> str:
        """格式化文件大小"""
        if size < 1024:
            return f"{size}B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f}KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f}MB"
        else:
            return f"{size / (1024 * 1024 * 1024):.1f}GB"

    def _format_file_list(
        self,
        files: List[Dict],
        current_path: str,
        user_config: Dict,
        user_id: str = None,
    ) -> str:
        """格式化文件列表"""
        if not files:
            return f"📁 {current_path}\n\n❌ 目录为空"

        result = f"📁 {current_path}\n\n"

        # 分类显示：先目录，后文件
        dirs = [f for f in files if f.get("is_dir", False)]
        files_only = [f for f in files if not f.get("is_dir", False)]

        # 合并所有项目（目录在前，文件在后）
        all_items = dirs + files_only
        max_files = user_config.get("max_display_files", 20)

        # 更新用户导航状态
        if user_id:
            self._update_user_navigation_state(
                user_id, current_path, all_items[:max_files]
            )

        # 显示项目（带序号）
        for i, item in enumerate(all_items[:max_files], 1):
            name = item.get("name", "")
            size = item.get("size", 0)
            modified = item.get("modified", "")
            is_dir = item.get("is_dir", False)

            if modified:
                modified = modified.split("T")[0]  # 只显示日期部分

            # 选择图标
            if is_dir:
                icon = "📂"
                result += f"{i:2d}. {icon} {name}/\n"
                if modified:
                    result += f"     📅 {modified}\n"
            else:
                # 文件图标
                ext = os.path.splitext(name)[1].lower()
                if ext in [".jpg", ".jpeg", ".png", ".gif", ".bmp"]:
                    icon = "🖼️"
                elif ext in [".mp4", ".avi", ".mkv", ".mov"]:
                    icon = "🎬"
                elif ext in [".mp3", ".wav", ".flac", ".aac"]:
                    icon = "🎵"
                elif ext in [".pdf"]:
                    icon = "📄"
                elif ext in [".doc", ".docx"]:
                    icon = "📝"
                elif ext in [".zip", ".rar", ".7z"]:
                    icon = "📦"
                else:
                    icon = "📄"

                result += f"{i:2d}. {icon} {name}\n"
                result += f"     💾 {self._format_file_size(size)}"
                if modified:
                    result += f" | 📅 {modified}"
                result += "\n"

        total_items = len(all_items)
        displayed_items = min(total_items, max_files)

        if total_items > displayed_items:
            result += f"\n... 还有 {total_items - displayed_items} 个项目未显示"

        result += f"\n📊 总计: {len(dirs)} 个目录, {len(files_only)} 个文件"

        # 添加导航提示
        result += f"\n\n💡 快速导航:"
        result += f"\n   • /alist ls <序号> - 进入对应项目"
        result += f"\n   • /alist quit - 返回上级目录"
        if user_id:
            nav_state = self._get_user_navigation_state(user_id)
            if nav_state["parent_paths"]:
                result += f"\n   • 当前可回退 {len(nav_state['parent_paths'])} 级"

        return result

    async def _download_file(
        self, event: AstrMessageEvent, file_item: Dict, user_config: Dict
    ):
        """下载文件并发送给用户"""
        user_id = event.get_sender_id()
        file_name = file_item.get("name", "")
        file_size = file_item.get("size", 0)

        # 检查文件大小限制 (默认50MB)
        max_download_size_mb = self.get_webui_config("max_download_size", 50)
        max_download_size = max_download_size_mb * 1024 * 1024
        if file_size > max_download_size:
            size_mb = file_size / (1024 * 1024)
            yield event.plain_result(
                f"❌ 文件过大: {size_mb:.1f}MB > {max_download_size_mb}MB\n💡 请使用下载链接命令获取链接"
            )
            return

        try:
            # 获取当前路径
            nav_state = self._get_user_navigation_state(user_id)
            current_path = nav_state["current_path"]
            if current_path.endswith("/"):
                file_path = f"{current_path}{file_name}"
            else:
                file_path = f"{current_path}/{file_name}"

            # 获取下载链接
            async with AlistClient(
                user_config["alist_url"],
                user_config.get("username", ""),
                user_config.get("password", ""),
                user_config.get("token", ""),
            ) as client:
                download_url = await client.get_download_url(file_path)
                if not download_url:
                    yield event.plain_result("❌ 无法获取下载链接")
                    return

                # 创建临时文件
                downloads_dir = os.path.join(
                    get_astrbot_data_path(), "plugins_data", "alistfile", "downloads"
                )
                os.makedirs(downloads_dir, exist_ok=True)

                # 使用安全的文件名
                safe_filename = "".join(
                    c for c in file_name if c.isalnum() or c in "._- "
                )[:100]
                temp_file_path = os.path.join(
                    downloads_dir, f"{user_id}_{int(time.time())}_{safe_filename}"
                )

                # 开始下载
                yield event.plain_result(
                    f"📥 开始下载: {file_name}\n💾 大小: {self._format_file_size(file_size)}"
                )

                async with aiohttp.ClientSession() as session:
                    async with session.get(download_url) as response:
                        if response.status == 200:
                            with open(temp_file_path, "wb") as f:
                                downloaded = 0
                                async for chunk in response.content.iter_chunked(8192):
                                    f.write(chunk)
                                    downloaded += len(chunk)

                                    # 每下载10MB报告一次进度 (对于大文件)
                                    if (
                                        file_size > 10 * 1024 * 1024
                                        and downloaded % (10 * 1024 * 1024) < 8192
                                    ):
                                        progress = (downloaded / file_size) * 100
                                        yield event.plain_result(
                                            f"📥 下载进度: {progress:.1f}% ({self._format_file_size(downloaded)}/{self._format_file_size(file_size)})"
                                        )

                            # 下载完成，发送文件
                            yield event.plain_result(f"✅ 下载完成，正在发送文件...")

                            # 发送文件消息组件
                            file_component = File(name=file_name, file=temp_file_path)
                            yield event.chain_result([file_component])

                            # 清理临时文件 (延迟删除)
                            async def cleanup_file():
                                await asyncio.sleep(10)  # 等待10秒后删除
                                try:
                                    if os.path.exists(temp_file_path):
                                        os.remove(temp_file_path)
                                except:
                                    pass

                            asyncio.create_task(cleanup_file())

                        else:
                            yield event.plain_result(
                                f"❌ 下载失败: HTTP {response.status}"
                            )

        except Exception as e:
            logger.error(f"用户 {user_id} 下载文件失败: {e}")
            yield event.plain_result(f"❌ 下载失败: {str(e)}")

    async def _upload_file(
        self, event: AstrMessageEvent, file_component: File, user_config: Dict
    ):
        """上传文件到Alist"""
        user_id = event.get_sender_id()
        upload_state = self._get_user_upload_state(user_id)
        target_path = upload_state["target_path"]

        try:
            # 获取文件信息
            file_name = file_component.name
            file_path = await file_component.get_file()

            if not file_path or not os.path.exists(file_path):
                yield event.plain_result("❌ 无法获取文件，请重新发送")
                return

            file_size = os.path.getsize(file_path)

            # 检查文件大小限制 (默认100MB)
            max_upload_size_mb = self.get_webui_config("max_upload_size", 100)
            max_upload_size = max_upload_size_mb * 1024 * 1024
            if file_size > max_upload_size:
                size_mb = file_size / (1024 * 1024)
                yield event.plain_result(
                    f"❌ 文件过大: {size_mb:.1f}MB > {max_upload_size_mb}MB"
                )
                return

            # 开始上传
            yield event.plain_result(
                f"📤 开始上传: {file_name}\n💾 大小: {self._format_file_size(file_size)}\n📂 目标: {target_path}"
            )

            async with AlistClient(
                user_config["alist_url"],
                user_config.get("username", ""),
                user_config.get("password", ""),
                user_config.get("token", ""),
            ) as client:
                success = await client.upload_file(file_path, target_path, file_name)

                if success:
                    yield event.plain_result(
                        f"✅ 上传成功!\n📄 文件: {file_name}\n📂 路径: {target_path}"
                    )

                    # 清理上传状态
                    self._set_user_upload_waiting(user_id, False)

                    # 刷新当前目录显示
                    result = await client.list_files(target_path)
                    if result:
                        files = result.get("content", [])
                        formatted_list = self._format_file_list(
                            files, target_path, user_config, user_id
                        )
                        yield event.plain_result(
                            f"📁 当前目录已更新:\n\n{formatted_list}"
                        )
                else:
                    yield event.plain_result(f"❌ 上传失败，请检查网络连接和权限")

        except Exception as e:
            logger.error(f"用户 {user_id} 上传文件失败: {e}")
            yield event.plain_result(f"❌ 上传失败: {str(e)}")
            self._set_user_upload_waiting(user_id, False)

    async def _upload_image(
        self, event: AstrMessageEvent, image_component: Image, user_config: Dict
    ):
        """上传图片到Alist"""
        user_id = event.get_sender_id()
        upload_state = self._get_user_upload_state(user_id)
        target_path = upload_state["target_path"]

        try:
            # 获取图片文件路径
            image_path = await image_component.convert_to_file_path()

            if not image_path or not os.path.exists(image_path):
                yield event.plain_result("❌ 无法获取图片文件，请重新发送")
                return

            # 生成文件名（使用原始扩展名或默认为.jpg）
            import time

            timestamp = int(time.time())
            if image_path.lower().endswith(
                (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
            ):
                ext = os.path.splitext(image_path)[1]
            else:
                ext = ".jpg"
            filename = f"image_{timestamp}{ext}"

            file_size = os.path.getsize(image_path)

            # 检查文件大小限制 (默认100MB)
            max_upload_size_mb = self.get_webui_config("max_upload_size", 100)
            max_upload_size = max_upload_size_mb * 1024 * 1024
            if file_size > max_upload_size:
                size_mb = file_size / (1024 * 1024)
                yield event.plain_result(
                    f"❌ 图片过大: {size_mb:.1f}MB > {max_upload_size_mb}MB"
                )
                return

            # 开始上传
            yield event.plain_result(
                f"📤 开始上传图片: {filename}\n💾 大小: {self._format_file_size(file_size)}\n📂 目标: {target_path}"
            )

            async with AlistClient(
                user_config["alist_url"],
                user_config.get("username", ""),
                user_config.get("password", ""),
                user_config.get("token", ""),
            ) as client:
                success = await client.upload_file(image_path, target_path, filename)

                if success:
                    yield event.plain_result(
                        f"✅ 图片上传成功!\n📄 文件: {filename}\n📂 路径: {target_path}"
                    )

                    # 清理上传状态
                    self._set_user_upload_waiting(user_id, False)

                    # 刷新当前目录显示
                    result = await client.list_files(target_path)
                    if result:
                        files = result.get("content", [])
                        formatted_list = self._format_file_list(
                            files, target_path, user_config, user_id
                        )
                        yield event.plain_result(
                            f"📁 当前目录已更新:\n\n{formatted_list}"
                        )
                else:
                    yield event.plain_result(f"❌ 上传失败，请检查网络连接和权限")

        except Exception as e:
            logger.error(f"用户 {user_id} 上传图片失败: {e}")
            yield event.plain_result(f"❌ 上传失败: {str(e)}")
            self._set_user_upload_waiting(user_id, False)

    @filter.command_group("alist")
    def alist_group(self):
        """Alist文件管理命令组"""
        pass

    @alist_group.command("config")
    async def config_command(
        self,
        event: AstrMessageEvent,
        action: str = "show",
        key: str = "",
        value: str = "",
    ):
        """配置Alist连接信息

        用法:
        /alist config show - 显示当前配置
        /alist config set <key> <value> - 设置配置项
        /alist config test - 测试连接
        /alist config setup - 快速配置向导

        配置项:
        - alist_url: Alist服务器地址 (如: http://localhost:5244)
        - username: 用户名
        - password: 密码
        - max_display_files: 最大显示文件数 (默认20)
        """
        user_id = event.get_sender_id()

        if action == "show":
            user_config = self.get_user_config(user_id)
            config_text = f"📋 用户 {event.get_sender_name()} 的配置:\n\n"

            # 隐藏敏感信息
            safe_config = user_config.copy()
            if safe_config.get("password"):
                safe_config["password"] = "***"
            if safe_config.get("token"):
                safe_config["token"] = "***"

            for k, v in safe_config.items():
                if k != "setup_completed":  # 不显示内部状态
                    config_text += f"🔹 {k}: {v}\n"

            # 显示全局配置信息
            require_auth = self.get_webui_config("require_user_auth", True)
            default_url = self.get_webui_config("default_alist_url", "")

            if require_auth:
                config_text += f"\n💡 提示: 当前启用了用户独立配置模式"
                if default_url:
                    config_text += f"\n🌐 默认服务器: {default_url}"
            else:
                config_text += f"\n💡 提示: 当前使用全局配置模式"

            yield event.plain_result(config_text)

        elif action == "setup":
            # 配置向导
            user_manager = self.get_user_config_manager(user_id)
            user_config = user_manager.load_config()

            setup_text = """🛠️ Alist配置向导
            
请按以下步骤配置:

1️⃣ 设置Alist服务器地址:
   /alist config set alist_url http://your-server:5244

2️⃣ 设置用户名(可选):
   /alist config set username your_username

3️⃣ 设置密码(可选):
   /alist config set password your_password

4️⃣ 测试连接:
   /alist config test

5️⃣ 开始使用:
   /alist ls /
   
💡 如果服务器不需要登录，只需要设置alist_url即可"""

            yield event.plain_result(setup_text)

        elif action == "set":
            if not key:
                yield event.plain_result("❌ 请指定配置项名称")
                return
            if not value:
                yield event.plain_result("❌ 请指定配置项值")
                return

            user_manager = self.get_user_config_manager(user_id)
            user_config = user_manager.load_config()

            # 验证配置项
            valid_keys = [
                "alist_url",
                "username",
                "password",
                "token",
                "max_display_files",
            ]
            if key not in valid_keys:
                yield event.plain_result(
                    f"❌ 未知的配置项: {key}。可用配置项: {', '.join(valid_keys)}"
                )
                return

            # 类型转换
            if key == "max_display_files":
                try:
                    value = int(value)
                    if value < 1 or value > 100:
                        yield event.plain_result("❌ max_display_files 必须在1-100之间")
                        return
                except ValueError:
                    yield event.plain_result("❌ max_display_files 必须是数字")
                    return

            user_config[key] = value

            # 如果设置了alist_url，标记为已配置
            if key == "alist_url" and value:
                user_config["setup_completed"] = True

            user_manager.save_config(user_config)
            yield event.plain_result(
                f"✅ 已为用户 {event.get_sender_name()} 设置 {key} = {value}"
            )

        elif action == "test":
            user_config = self.get_user_config(user_id)

            if not self._validate_config(user_config):
                yield event.plain_result(
                    "❌ 请先配置Alist URL\n💡 使用 /alist config setup 开始配置向导"
                )
                return

            try:
                async with AlistClient(
                    user_config["alist_url"],
                    user_config.get("username", ""),
                    user_config.get("password", ""),
                    user_config.get("token", ""),
                ) as client:
                    files = await client.list_files("/")
                    if files is not None:
                        yield event.plain_result("✅ Alist连接测试成功!")
                    else:
                        yield event.plain_result("❌ Alist连接失败，请检查配置")
            except Exception as e:
                yield event.plain_result(f"❌ 连接测试失败: {str(e)}")

        elif action == "clear_cache":
            # 清理用户缓存
            self.cache_manager.clear_cache(user_id)
            yield event.plain_result("✅ 已清理您的文件列表缓存")

        else:
            yield event.plain_result(
                "❌ 未知的操作，支持: show, set, test, setup, clear_cache"
            )

    @alist_group.command("ls")
    async def list_files(self, event: AstrMessageEvent, path: str = "/"):
        """列出指定路径的文件和目录

        用法:
        /alist ls [路径] - 列出指定路径内容
        /alist ls <序号> - 进入对应序号的项目
        示例: /alist ls /movies 或 /alist ls 1
        """
        user_id = event.get_sender_id()
        user_config = self.get_user_config(user_id)

        if not self._validate_config(user_config):
            yield event.plain_result(
                "❌ 请先配置Alist连接信息\n💡 使用 /alist config setup 开始配置向导"
            )
            return

        # 检查是否是序号导航
        target_path = path
        if path.isdigit():
            number = int(path)
            nav_state = self._get_user_navigation_state(user_id)
            item = self._get_item_by_number(user_id, number)
            if item:
                if item.get("is_dir", False):
                    # 进入目录
                    item_name = item.get("name", "")
                    current_path = nav_state["current_path"]
                    if current_path.endswith("/"):
                        target_path = f"{current_path}{item_name}"
                    else:
                        target_path = f"{current_path}/{item_name}"
                else:
                    # 选择的是文件，启动下载
                    yield event.plain_result(
                        f"📥 正在准备下载文件: {item.get('name', '')}..."
                    )
                    async for result in self._download_file(event, item, user_config):
                        yield result
                    return
            else:
                yield event.plain_result(
                    f"❌ 序号 {number} 无效，请使用 /alist ls 查看当前目录"
                )
                return

        try:
            # 检查缓存
            enable_cache = self.get_webui_config("enable_cache", True)
            cache_duration = self.get_webui_config("cache_duration", 300)

            if enable_cache:
                cached_result = self.cache_manager.get_cache(
                    user_config["alist_url"], target_path, user_id, cache_duration
                )
                if cached_result:
                    files = cached_result.get("content", [])
                    formatted_list = self._format_file_list(
                        files, target_path, user_config, user_id
                    )
                    formatted_list += "\n\n💾 (来自缓存)"
                    yield event.plain_result(formatted_list)
                    return

            # 缓存未命中，从API获取
            async with AlistClient(
                user_config["alist_url"],
                user_config.get("username", ""),
                user_config.get("password", ""),
                user_config.get("token", ""),
            ) as client:
                result = await client.list_files(target_path)
                if result is not None:
                    # 保存到缓存
                    if enable_cache:
                        self.cache_manager.set_cache(
                            user_config["alist_url"], target_path, user_id, result
                        )

                    files = result.get("content", [])
                    formatted_list = self._format_file_list(
                        files, target_path, user_config, user_id
                    )
                    yield event.plain_result(formatted_list)
                else:
                    yield event.plain_result(f"❌ 无法访问路径: {target_path}")
        except Exception as e:
            logger.error(f"用户 {user_id} 列出文件失败: {e}")
            yield event.plain_result(f"❌ 操作失败: {str(e)}")

    @alist_group.command("search")
    async def search_files(
        self, event: AstrMessageEvent, keyword: str, path: str = "/"
    ):
        """搜索文件

        用法: /alist search <关键词> [搜索路径]
        示例: /alist search movie.mp4 /videos
        """
        if not keyword:
            yield event.plain_result("❌ 请提供搜索关键词")
            return

        user_id = event.get_sender_id()
        user_config = self.get_user_config(user_id)

        if not self._validate_config(user_config):
            yield event.plain_result(
                "❌ 请先配置Alist连接信息\n💡 使用 /alist config setup 开始配置向导"
            )
            return

        try:
            async with AlistClient(
                user_config["alist_url"],
                user_config.get("username", ""),
                user_config.get("password", ""),
                user_config.get("token", ""),
            ) as client:
                files = await client.search_files(keyword, path)
                if files:
                    max_files = user_config.get("max_display_files", 20)
                    result = f"🔍 搜索结果 (关键词: {keyword})\n搜索路径: {path}\n\n"

                    for i, file_item in enumerate(files[:max_files], 1):
                        name = file_item.get("name", "")
                        parent = file_item.get("parent", "")
                        size = file_item.get("size", 0)
                        is_dir = file_item.get("is_dir", False)

                        icon = "📂" if is_dir else "📄"
                        result += f"{i}. {icon} {name}\n"
                        result += f"   📍 {parent}\n"
                        if not is_dir:
                            result += f"   💾 {self._format_file_size(size)}\n"
                        result += "\n"

                    if len(files) > max_files:
                        result += f"... 还有 {len(files) - max_files} 个结果未显示"

                    yield event.plain_result(result)
                else:
                    yield event.plain_result(f"🔍 未找到包含 '{keyword}' 的文件")
        except Exception as e:
            logger.error(f"用户 {user_id} 搜索文件失败: {e}")
            yield event.plain_result(f"❌ 搜索失败: {str(e)}")

    @alist_group.command("info")
    async def file_info(self, event: AstrMessageEvent, path: str):
        """获取文件详细信息

        用法: /alist info <文件路径>
        示例: /alist info /documents/readme.txt
        """
        if not path:
            yield event.plain_result("❌ 请提供文件路径")
            return

        user_id = event.get_sender_id()
        user_config = self.get_user_config(user_id)

        if not self._validate_config(user_config):
            yield event.plain_result(
                "❌ 请先配置Alist连接信息\n💡 使用 /alist config setup 开始配置向导"
            )
            return

        try:
            async with AlistClient(
                user_config["alist_url"],
                user_config.get("username", ""),
                user_config.get("password", ""),
                user_config.get("token", ""),
            ) as client:
                file_info = await client.get_file_info(path)
                if file_info:
                    name = file_info.get("name", "")
                    size = file_info.get("size", 0)
                    modified = file_info.get("modified", "")
                    is_dir = file_info.get("is_dir", False)
                    provider = file_info.get("provider", "")

                    info_text = f"📋 文件信息\n\n"
                    info_text += f"📄 名称: {name}\n"
                    info_text += f"📁 类型: {'目录' if is_dir else '文件'}\n"
                    info_text += f"📍 路径: {path}\n"

                    if not is_dir:
                        info_text += f"💾 大小: {self._format_file_size(size)}\n"

                    if modified:
                        info_text += (
                            f"📅 修改时间: {modified.replace('T', ' ').split('.')[0]}\n"
                        )

                    if provider:
                        info_text += f"🔗 存储: {provider}\n"

                    # 如果是文件且不是目录，提供下载链接
                    if not is_dir:
                        download_url = await client.get_download_url(path)
                        if download_url:
                            info_text += f"\n🔗 下载链接:\n{download_url}"

                    yield event.plain_result(info_text)
                else:
                    yield event.plain_result(f"❌ 文件不存在: {path}")
        except Exception as e:
            logger.error(f"用户 {user_id} 获取文件信息失败: {e}")
            yield event.plain_result(f"❌ 操作失败: {str(e)}")

    @alist_group.command("download")
    async def get_download_link(self, event: AstrMessageEvent, path: str):
        """获取文件下载链接或直接下载

        用法:
        /alist download <文件路径> - 获取指定路径文件的下载链接
        /alist download <序号> - 直接下载对应序号的文件
        示例: /alist download /documents/file.pdf 或 /alist download 3
        """
        if not path:
            yield event.plain_result("❌ 请提供文件路径或序号")
            return

        user_id = event.get_sender_id()
        user_config = self.get_user_config(user_id)

        if not self._validate_config(user_config):
            yield event.plain_result(
                "❌ 请先配置Alist连接信息\n💡 使用 /alist config setup 开始配置向导"
            )
            return

        # 检查是否是序号下载
        target_path = path
        if path.isdigit():
            number = int(path)
            item = self._get_item_by_number(user_id, number)
            if item:
                if item.get("is_dir", False):
                    yield event.plain_result(
                        f"❌ 序号 {number} 是目录，无法下载\n💡 使用 /alist ls {number} 进入目录"
                    )
                    return
                else:
                    # 直接下载文件
                    yield event.plain_result(
                        f"📥 正在准备下载文件: {item.get('name', '')}..."
                    )
                    async for result in self._download_file(event, item, user_config):
                        yield result
                    return
            else:
                yield event.plain_result(
                    f"❌ 序号 {number} 无效，请使用 /alist ls 查看当前目录"
                )
                return

        try:
            async with AlistClient(
                user_config["alist_url"],
                user_config.get("username", ""),
                user_config.get("password", ""),
                user_config.get("token", ""),
            ) as client:
                download_url = await client.get_download_url(target_path)
                if download_url:
                    file_info = await client.get_file_info(target_path)
                    if file_info:
                        name = file_info.get("name", "")
                        size = file_info.get("size", 0)

                        result = f"📥 下载链接\n\n"
                        result += f"📄 文件: {name}\n"
                        result += f"💾 大小: {self._format_file_size(size)}\n"
                        result += f"🔗 链接: {download_url}\n\n"
                        result += "💡 提示: 点击链接即可下载文件"

                        yield event.plain_result(result)
                    else:
                        yield event.plain_result(download_url)
                else:
                    yield event.plain_result(
                        f"❌ 无法获取下载链接，文件可能不存在或是目录: {target_path}"
                    )
        except Exception as e:
            logger.error(f"用户 {user_id} 获取下载链接失败: {e}")
            yield event.plain_result(f"❌ 操作失败: {str(e)}")

    @alist_group.command("quit")
    async def quit_navigation(self, event: AstrMessageEvent):
        """返回上级目录

        用法: /alist quit
        注意: 此命令不接受任何参数
        """
        user_id = event.get_sender_id()
        user_config = self.get_user_config(user_id)

        if not self._validate_config(user_config):
            yield event.plain_result(
                "❌ 请先配置Alist连接信息\n💡 使用 /alist config setup 开始配置向导"
            )
            return

        nav_state = self._get_user_navigation_state(user_id)

        if not nav_state["parent_paths"]:
            yield event.plain_result("📂 已经在根目录，无法继续回退")
            return

        # 回退到上一级目录
        previous_path = nav_state["parent_paths"].pop()

        try:
            # 重新加载上级目录
            async with AlistClient(
                user_config["alist_url"],
                user_config.get("username", ""),
                user_config.get("password", ""),
                user_config.get("token", ""),
            ) as client:
                result = await client.list_files(previous_path)
                if result is not None:
                    files = result.get("content", [])
                    # 直接更新导航状态，不调用_update_user_navigation_state避免重复处理
                    nav_state["current_path"] = previous_path
                    nav_state["items"] = files[
                        : self.get_webui_config("max_display_files", 20)
                    ]

                    formatted_list = self._format_file_list(
                        files, previous_path, user_config, user_id
                    )
                    yield event.plain_result(f"⬅️ 已返回上级目录\n\n{formatted_list}")
                else:
                    yield event.plain_result(f"❌ 无法访问上级目录: {previous_path}")
        except Exception as e:
            logger.error(f"用户 {user_id} 回退目录失败: {e}")
            yield event.plain_result(f"❌ 回退失败: {str(e)}")

    @alist_group.command("upload")
    async def upload_command(self, event: AstrMessageEvent, action: str = ""):
        """上传文件命令

        用法:
        - /alist upload - 开始上传模式
        - /alist upload cancel - 取消上传模式
        """
        user_id = event.get_sender_id()

        if action == "cancel":
            upload_state = self._get_user_upload_state(user_id)

            if upload_state["waiting"]:
                self._set_user_upload_waiting(user_id, False)
                yield event.plain_result("✅ 已取消上传模式")
            else:
                yield event.plain_result("❌ 当前不在上传模式")

        elif not action:
            # 开始上传模式
            user_config = self.get_user_config(user_id)

            if not self._validate_config(user_config):
                yield event.plain_result(
                    "❌ 请先配置Alist连接信息\n💡 使用 /alist config setup 开始配置向导"
                )
                return

            # 获取当前导航状态中的路径
            nav_state = self._get_user_navigation_state(user_id)
            current_path = nav_state["current_path"]

            # 设置上传等待状态
            self._set_user_upload_waiting(user_id, True, current_path)

            upload_text = f"""📤 上传模式已启动
            
📂 目标目录: {current_path}

💡 请直接发送文件或图片，系统会自动上传到此目录
⏰ 上传模式将在10分钟后自动取消

📋 支持的操作:
• 直接发送文件 - 上传文件
• 直接发送图片 - 上传图片
• /alist upload cancel - 取消上传模式
• /alist ls - 查看当前目录"""

            yield event.plain_result(upload_text)

            # 设置自动取消上传模式的定时器
            async def auto_cancel_upload():
                await asyncio.sleep(600)  # 10分钟
                upload_state = self._get_user_upload_state(user_id)
                if upload_state["waiting"]:
                    self._set_user_upload_waiting(user_id, False)
                    # 注意：这里不能使用yield，因为在异步任务中无法发送消息给用户
                    logger.info(f"用户 {user_id} 上传模式已自动取消（超时10分钟）")

            asyncio.create_task(auto_cancel_upload())

        else:
            yield event.plain_result(
                "❌ 未知操作，支持: /alist upload 或 /alist upload cancel"
            )

    @filter.custom_filter(FileUploadFilter)
    async def handle_file_message(self, event: AstrMessageEvent):
        """处理文件消息 - 用于上传功能"""
        user_id = event.get_sender_id()
        upload_state = self._get_user_upload_state(user_id)

        # 检查是否在上传模式
        if not upload_state["waiting"]:
            return  # 不在上传模式，忽略文件消息

        user_config = self.get_user_config(user_id)
        if not self._validate_config(user_config):
            yield event.plain_result("❌ 请先配置Alist连接信息")
            self._set_user_upload_waiting(user_id, False)
            return

        # 获取文件或图片组件
        messages = event.get_messages()
        file_components = [msg for msg in messages if isinstance(msg, (File, Image))]

        if not file_components:
            yield event.plain_result("❌ 未检测到文件或图片，请重新发送")
            return

        # 处理第一个文件/图片（通常消息只包含一个文件）
        file_component = file_components[0]

        # 根据组件类型调用不同的上传方法
        if isinstance(file_component, Image):
            async for result in self._upload_image(event, file_component, user_config):
                yield result
        else:
            async for result in self._upload_file(event, file_component, user_config):
                yield result

    @alist_group.command("help")
    async def help_command(self, event: AstrMessageEvent):
        """显示帮助信息"""
        user_id = event.get_sender_id()
        user_config = self.get_user_config(user_id)
        is_user_auth_mode = self.get_webui_config("require_user_auth", True)

        help_text = """📚 Alist文件管理插件帮助

🔧 配置命令:
/alist config show - 显示当前配置
/alist config setup - 快速配置向导
/alist config set <key> <value> - 设置配置项
/alist config test - 测试连接
/alist config clear_cache - 清理文件缓存

📁 智能导航:
/alist ls [路径] - 列出文件和目录 (带序号)
/alist ls <序号> - 进入对应项目或下载文件
/alist quit - 返回上级目录

🔍 文件操作:
/alist search <关键词> [路径] - 搜索文件
/alist info <文件路径> - 查看文件详细信息
/alist download <路径/序号> - 获取下载链接或直接下载

📤 上传操作:
/alist upload - 开始上传模式
/alist upload cancel - 取消上传模式
(在上传模式下直接发送文件或图片即可上传)

📝 示例:
/alist config setup (推荐新手使用)
/alist config set alist_url http://localhost:5244
/alist ls /movies
/alist ls 1 (进入1号目录或下载1号文件)
/alist quit (返回上级目录)
/alist search movie.mp4
/alist download 3 (直接下载3号文件)"""

        if is_user_auth_mode:
            help_text += f"""

👤 用户认证模式:
- 当前启用了用户独立配置模式
- 每个用户需要独立配置自己的Alist连接
- 您的配置不会影响其他用户"""

            if not self._validate_config(user_config):
                help_text += f"""

⚠️  您尚未配置Alist连接，请使用以下命令开始:
   /alist config setup"""
        else:
            help_text += f"""

🌐 全局配置模式:
- 当前使用全局配置模式
- 所有用户共享相同的Alist服务器连接
- 管理员可在WebUI中配置全局设置"""

        help_text += f"""

💡 提示:
1. 首次使用建议运行 /alist config setup 配置向导
2. 如果Alist需要登录，请配置用户名和密码
3. 路径区分大小写，以/开头表示根目录
4. 管理员可在WebUI插件配置页面调整全局设置"""

        yield event.plain_result(help_text)

    async def terminate(self):
        """插件销毁时的清理工作"""
        logger.info("Alist文件管理插件已卸载")
