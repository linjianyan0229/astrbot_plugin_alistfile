# Alist文件管理插件

这是一个用于AstrBot的Alist文件管理插件，让您可以通过聊天界面方便地管理Alist服务器上的文件。

## ✨ 主要功能

- 📁 **智能导航** - 序号快速导航，支持一键进入目录或下载文件
- ⬅️ **快速回退** - /alist quit 命令快速返回上级目录
- 📥 **后台下载** - 自动下载小文件并直接发送给用户
- 📤 **文件上传** - 上传模式支持直接发送文件上传到Alist
- 🔍 **文件搜索** - 在指定目录下搜索文件
- 📋 **文件信息** - 查看文件详细信息（大小、修改时间等）
- 🔗 **下载链接** - 获取文件直接下载链接
- ⚙️ **灵活配置** - 支持用户独立配置和全局配置两种模式
- 🎨 **美化显示** - 智能文件图标，直观的信息展示
- 🌐 **WebUI支持** - 管理员可在Dashboard中配置插件全局设置

- ⚠️⚠️只能上传图片，因为astrbot对文件程序逻辑有问题，暂时无法上传文件

## 🔧 配置方式

### 两种配置模式

#### 1. 用户独立配置模式（默认）
- 每个用户拥有独立的Alist连接配置
- 用户配置互不干扰，支持连接不同的Alist服务器
- 用户首次使用需要自行配置连接信息

#### 2. 全局配置模式
- 所有用户共享同一个Alist服务器连接
- 管理员在WebUI中统一配置
- 适合团队共享同一个文件服务器的场景

### WebUI配置（管理员）

1. 打开AstrBot Dashboard  
2. 进入"插件管理"页面
3. 找到"Alist文件管理插件"，点击"插件配置"按钮
4. 在配置页面中设置全局选项：
   - **默认Alist服务器地址** - 用户配置的默认值（支持http://或https://）
   - **最大显示文件数** - 限制每次显示的文件数量（范围：1-100）
   - **允许的文件扩展名** - 控制显示的文件类型（用逗号分隔，如：.txt,.pdf,.jpg）
   - **启用文件预览** - 是否显示文件预览功能
   - **要求用户认证** - 切换用户独立配置/全局配置模式

> 注意：配置保存后会立即生效，影响所有用户的使用体验

### 用户配置（聊天界面）

#### 快速配置向导
```
/alist config setup
```

#### 手动配置
```bash
# 显示当前配置
/alist config show

# 设置Alist服务器地址
/alist config set alist_url http://your-server:5244

# 设置用户名（可选）
/alist config set username your_username

# 设置密码（可选）
/alist config set password your_password

# 设置访问Token（可选，优先级高于用户名密码）
/alist config set token your_token

# 测试连接
/alist config test

# 清理文件缓存
/alist config clear_cache
```

## 📖 使用指南

### 智能序号导航

```bash
# 查看帮助
/alist help

# 列出根目录文件 (自动显示序号)
/alist ls

# 使用序号快速导航
/alist ls 1     # 进入1号目录或下载1号文件
/alist ls 3     # 进入3号项目

# 返回上级目录
/alist quit

# 传统路径方式仍然支持
/alist ls /movies
```

### 文件搜索与信息

```bash
# 搜索文件
/alist search movie.mp4

# 在指定目录搜索
/alist search keyword /path/to/search

# 查看文件信息
/alist info /path/to/file.txt
```

### 下载功能

```bash
# 序号下载 (推荐)
/alist download 2   # 直接下载2号文件

# 路径下载
/alist download /path/to/file.pdf   # 获取下载链接

# 在文件列表中直接选择文件序号也会自动下载
/alist ls 5    # 如果5号是文件，会自动开始下载
```

### 文件上传

```bash
# 开始上传模式
/alist upload

# 在上传模式下直接发送文件或图片即可上传
# （支持任何文件类型：文档、图片、视频等）

# 取消上传模式
/alist upload cancel

# 上传模式会在10分钟后自动取消
```

### 配置示例

#### 用户独立配置示例
```bash
# 用户A配置自己的家庭NAS
/alist config set alist_url http://home-nas:5244
/alist config set username userA
/alist config set password ****

# 用户B配置自己的云盘
/alist config set alist_url http://cloud-drive:5244
/alist config set username userB
/alist config set password ****
```

#### 管理员全局配置示例
在WebUI中设置：
- 默认Alist服务器地址：`http://company-files:5244`
- 要求用户认证：`false`（切换到全局模式）
- 最大显示文件数：`30`

## 🎨 功能特色

### 智能文件图标
- 🖼️ 图片文件（jpg, png, gif等）
- 🎬 视频文件（mp4, avi, mkv等）
- 🎵 音频文件（mp3, wav, flac等）
- 📄 文档文件（pdf, doc等）
- 📦 压缩文件（zip, rar等）
- 📂 目录

### 信息显示
- 文件大小自动格式化（B/KB/MB/GB）
- 文件修改时间显示
- 分类显示（目录优先，文件在后）
- 超出限制时显示省略提示

### 安全特性
- 密码和Token自动隐藏
- 用户配置隔离
- 输入验证和错误处理
- 详细的日志记录

### 性能优化
- 智能文件列表缓存系统
- 可配置的缓存有效期
- 按用户独立缓存
- 支持手动清理缓存

## 🔧 高级配置

### 配置项详解

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `default_alist_url` | string | "" | 默认Alist服务器地址 |
| `default_username` | string | "" | 默认用户名 |
| `default_password` | string | "" | 默认密码 |
| `default_token` | string | "" | 默认访问Token |
| `max_display_files` | int | 20 | 最大显示文件数量 |
| `allowed_extensions` | text | ".txt,.pdf,..." | 允许显示的文件扩展名 |
| `enable_preview` | bool | true | 启用文件预览功能 |
| `enable_cache` | bool | true | 启用文件列表缓存 |
| `cache_duration` | int | 300 | 缓存有效期(秒) |
| `max_download_size` | int | 50 | 最大下载文件大小(MB) |
| `max_upload_size` | int | 100 | 最大上传文件大小(MB) |
| `require_user_auth` | bool | true | 要求用户独立认证 |

### 文件存储结构
```
data/plugins_data/alistfile/
├── global_config.json          # 全局配置文件
├── users/                     # 用户配置目录
│   ├── user1.json            # 用户1的配置
│   ├── user2.json            # 用户2的配置
│   └── ...
├── cache/                     # 文件列表缓存目录
│   ├── abc123.json           # 缓存文件(MD5命名)
│   └── ...
└── downloads/                 # 临时下载目录
    ├── user123_1234567890_file.txt   # 临时下载文件
    └── ...
```

## 🚀 快速开始

### 用户首次使用
1. 运行配置向导：`/alist config setup`
2. 按提示设置Alist服务器地址
3. 测试连接：`/alist config test`
4. 开始使用：`/alist ls /`

### 管理员部署
1. 在WebUI插件管理中安装插件
2. 进入插件配置页面
3. 根据需求选择配置模式：
   - **团队共享**：关闭"要求用户认证"，设置默认服务器
   - **用户独立**：保持"要求用户认证"开启，用户自行配置
4. 调整其他参数（文件显示数量、允许的扩展名等）

## 🛠️ 故障排除

### 常见问题

**Q: 提示"❌ 请先配置Alist连接信息"**
A: 运行 `/alist config setup` 开始配置向导，或使用 `/alist config set alist_url` 设置服务器地址

**Q: 连接测试失败**
A: 检查服务器地址是否正确，网络是否可达，用户名密码是否正确

**Q: 文件列表为空**
A: 检查路径是否存在，是否有访问权限，或尝试访问根目录 `/alist ls /`

**Q: 在WebUI中看不到插件配置**
A: 确保插件已正确安装并启用，刷新页面重试

### 配置验证

使用以下命令验证配置：
```bash
/alist config show    # 查看当前配置
/alist config test    # 测试连接
/alist ls /          # 测试文件列表
```

## 📋 依赖要求

- aiohttp >= 3.8.0
- AstrBot >= 3.5.0

## 🔄 版本历史

### v1.0.0
- ✨ 支持基本的文件浏览、搜索、信息查看功能
- ✨ 新增用户独立配置系统
- ✨ 新增WebUI配置界面支持
- ✨ 新增配置向导功能
- ✨ 支持全局配置和用户配置两种模式
- 🎨 美化文件显示效果
- 🔒 增强安全性和错误处理

## 📞 技术支持

如有问题或建议，请：
1. 查阅本文档的故障排除部分
2. 在AstrBot社区群聊中寻求帮助
3. 提交Issue到插件仓库

---

💡 **提示**：建议新用户首先使用配置向导（`/alist config setup`）来完成初始设置，这样可以避免大部分配置问题。
