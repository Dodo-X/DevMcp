# DevPartner v6.0 - ModelScope 部署指南

> **适用环境**: ModelScope Docker 创空间（云端部署）
>
> **本地开发**: 请直接运行 `python server.py` 或 `start.bat`（无需使用此目录）

---

## 📋 目录结构

```
deploy/
├── Dockerfile          # ModelScope 创空间专用 Dockerfile
├── docker-compose.yml  # Docker Compose 配置（可选，用于本地测试）
└── README.md           # 本文件（部署说明）
```

---

## 🎯 核心特性

### ✨ v6.0 升级要点

| 特性 | 说明 |
|------|------|
| **Streamable HTTP** | 替代 SSE 模式，更好的兼容性和性能 |
| **统一模型路径** | `/app/models/Qwen3.5-9B-Q4_1.gguf` |
| **智能启动脚本** | 自动检测模型文件、支持降级模式 |
| **健康检查** | 内置 60 秒间隔健康监控 |
| **Dataset 挂载** | 支持 ModelScope Dataset volume 挂载 |

---

## 🚀 快速部署

### **Step 1: 准备代码仓库**

确保项目根目录包含以下关键文件：

```bash
# 必需文件清单
✅ server.py                    # 主程序入口
✅ requirements.txt             # Python 依赖
✅ devpartner_agent/            # 智能管家层
✅ devpartner_tools/            # 纯工具层
✅ models/README.md             # 模型管理文档
✅ .gitignore                   # Git 排除规则（排除模型文件）

# 可选但推荐
✅ start.bat                    # Windows 启动脚本
✅ scripts/check_model.py       # 模型检查工具
```

### **Step 2: 上传模型到 ModelScope Dataset**

#### 方法一：上传到 Dataset（推荐用于云端部署）

1️⃣ **登录 ModelScope**
   ```
   访问: https://modelscope.cn
   登录账号（支持 GitHub/手机号登录）
   ```

2️⃣ **创建新 Dataset**
   ```
   点击右上角 "+" → "创建 Dataset"

   填写信息：
   - Dataset 名称: `devpartner-models` (或自定义)
   - 可见性: Public (公开) 或 Private (私有)
   - 描述: `DevPartner v6.0 LLM 推理模型 - Qwen3.5-9B-Q4_1`

   点击 "创建"
   ```

3️⃣ **上传模型文件**
   ```
   进入刚创建的 Dataset 页面
   点击 "上传文件" 或拖拽文件

   选择文件:
   ✅ Qwen3.5-9B-Q4_1.gguf (~5.7GB)

   等待上传完成（根据网速，可能需要10-30分钟）

   上传完成后，记录 Dataset 路径:
   例如: your_username/devpartner-models
   ```

### **Step 3: 创建 ModelScope 创空间**

1️⃣ **创建 Docker 创空间**
   ```
   在 ModelScope 主页点击 "创建空间"

   选择配置:
   - 类型: Docker Space (必须！)
   - 名称: devpartner-v6 (或自定义)
   - 可见性: Public 或 Private
   - SDK/Docker: 选择 "Docker"
   - 关联 GitHub 仓库: 选择你的 devPartner 仓库

   ⚠️ 重要提示:
     ModelScope 会自动从根目录读取 Dockerfile！
     但我们的 Dockerfile 位于 deploy/ 目录下。

     解决方案:
     方案A: 将 deploy/Dockerfile 复制到项目根目录
     方案B: 在创空间设置中指定 Dockerfile 路径（如果支持）
   ```

2️⃣ **配置 Volume 挂载（关键！）**
   ```
   进入创空间 → 设置 → 存储卷 (Volumes)

   添加挂载:
   - 来源: your_username/devpartner-models (你刚创建的Dataset)
   - 目标: /app/models
   - 权限: 读写 (RW)

   保存设置
   ```

3️⃣ **配置环境变量（可选）**
   ```
   在创空间设置中添加:

   MCP_PORT=7860
   TZ=Asia/Shanghai
   MODEL_PATH=/app/models/Qwen3.5-9B-Q4_1.gguf
   MODEL_SOURCE=dataset
   TRANSPORT_MODE=streamable-http
   ```

### **Step 4: 构建和启动**

1️⃣ **首次构建**
   ```
   在创空间页面点击:
   - "重新构建" (首次需要构建)
   - 或 "启动" (如果已构建)

   等待时间:
   - 构建: 约 5-10 分钟（安装依赖 + 复制代码）
   - 启动: 约 1-2 分钟（初始化数据库 + 加载模型）
   ```

2️⃣ **查看日志**
   ```
   在创空间页面点击 "日志" 标签

   应该看到:
   ╔════════════════════════════════════════╗
   ║  ⚡ DevPartner v6.0 · ModelScope 启动器 ║
   ╚════════════════════════════════════════╝

   [步骤 1/3] 检查模型文件...
          ✅ 模型文件已存在: Qwen3.5-9B-Q4_1.gguf (5.7 GB)

   [步骤 2/3] 初始化数据目录...
          ✅ 数据目录已就绪

   [步骤 3/3] 启动 DevPartner 服务...
          🚀 服务正在启动...

   [INFO] devpartner-tools: 21 个纯工具已注册
   ...
   ```

3️⃣ **访问 Dashboard**
   ```
   访问地址: http://your-space-id.modelscope.cn:7860/dashboard

   应该看到:
   - 🌱 成长视角 标签页（默认显示）
   - ⚙️ 运维视角 标签页
   - 双向成长仪表盘数据正常加载
   ```

---

## 🔧 高级配置

### **模型来源选项**

| 来源 | 配置方法 | 适用场景 |
|------|---------|---------|
| **Dataset 挂载** ⭐ | Volume 挂载到 `/app/models` | 推荐用于云端部署 |
| **打包进镜像** | 构建时包含模型文件 | 离线/私有环境 |
| **运行时下载** | 设置 `MODEL_URL` 环境变量 | 动态切换模型 |

### **性能优化**

```bash
# 启用 GPU 加速（如果有 GPU 实例，无显卡保持 0）
N_GPU_LAYERS=-1  # 全部层使用GPU（需要GPU实例）
N_GPU_LAYERS=0   # 纯CPU模式（无显卡默认）

# 增加 CPU 并行度
N_THREADS=8  # 根据 CPU 核心数调整

# 调整批处理大小
N_BATCH=1024  # 提高吞吐量（增加内存使用）
```

### **成本优化**

| 方案 | 月费用估算 | 适用场景 |
|------|-----------|---------|
| **CPU Basic (免费)** | ¥0 | 开发测试 |
| **CPU Standard** | ¥~100/月 | 小规模公开服务 |
| **GPU 基础版** | ¥~300-500/月 | 需要 LLM 推理加速 |
| **GPU 高级版** | ¥~1000+/月 | 高并发生产环境 |

---

## 🆘 常见问题排查

### ❌ **问题1: 构建失败**

**症状**: ModelScope 显示 "Docker build failed"

**解决方案**:
```bash
# 1. 检查本地是否能成功构建
cd deploy
docker build -t test-modelscope ../

# 2. 如果失败，查看详细错误信息
docker build -t test-modelscope ../ 2>&1 | tee build.log

# 常见原因:
# - requirements.txt 缺少依赖
# - Dockerfile 语法错误
# - 文件复制路径错误
```

### ❌ **问题2: 模型文件未找到**

**症状**: 日志显示 `[步骤 1/3] ⚠️ 模型文件不存在`

**解决方案**:
```bash
# 1. 检查 Dataset 是否正确挂载
# 在创空间设置中确认:
# - Volume 来源路径正确
# - 目标路径是 /app/models
# - 权限是 RW (读写)

# 2. 进入容器检查
docker exec -it <container_id> ls -lh /app/models/
# 应该看到 Qwen3.5-9B-Q4_1.gguf 文件
```

### ❌ **问题3: 内存不足 (OOM)**

**症状**: 容器被强制终止，日志显示 "OOMKilled"

**解决方案**:
```bash
# 1. 升级硬件配置（在创空间设置中）
#    CPU Basic (免费): 4GB内存 → 可能不够
#    推荐: CPU Standard (付费) 或 GPU 实例

# 2. 优化 LLM 参数
# 设置环境变量:
N_CTX=4096       # 减小上下文窗口 (默认8192)
N_GPU_LAYERS=0   # 使用纯CPU模式 (节省GPU内存)
N_THREADS=4      # 减少线程数
```

### ❌ **问题4: 端口无法访问**

**症状**: 浏览器无法打开 http://your-space:7860

**解决方案**:
```bash
# 1. 确认端口配置
# ModelScope 只允许: 7860 或 8080
# 检查 Dockerfile: EXPOSE 7860

# 2. 检查防火墙/安全组
# ModelScope 平台通常会自动处理

# 3. 等待更长时间
# 首次启动可能需要 2-3 分钟初始化
```

---

## 📊 验证清单

启动成功后，逐一确认：

### **基本功能**
- [ ] Dashboard 页面正常打开（无404错误）
- [ ] 可以在"成长视角"和"运维视角"之间切换
- [ ] 用户技能雷达图数据正常显示
- [ ] 系统进化面板数据正确

### **API端点**
- [ ] `http://your-space:7860/api/growth/user-overview` 返回JSON
- [ ] `http://your-space:7860/api/growth/skill-radar` 返回雷达图数据
- [ ] `http://your-space:7860/docs` API文档可访问

### **LLM推理**
- [ ] 在Dashboard中可以发送对话消息
- [ ] 收到LLM生成的回复（非错误信息）
- [ ] 响应时间合理（<30秒）

### **持久化**
- [ ] 重启创空间后，对话记录保留
- [ ] 用户数据和系统状态恢复
- [ ] 模型文件无需重新下载

---

## 📚 相关文档

| 文档 | 内容 | 适用场景 |
|------|------|---------|
| **[DEPLOYMENT_GUIDE.md](../DEPLOYMENT_GUIDE.md)** | 通用部署指南 | 本地/Docker/ModelScope通用 |
| **[models/README.md](../models/README.md)** | 模型管理文档 | 模型下载与配置 |
| **[server.py](../server.py)** | 主程序入口 | 启动方式和参数说明 |

---

## 💡 最佳实践

### **开发流程**

```bash
# 1. 本地开发（使用 stdio 模式）
python server.py
# 或
start.bat

# 2. 测试 Streamable HTTP 模式（本地预览）
python server.py 7860
# 访问: http://localhost:7860/dashboard

# 3. 使用 Docker Compose 测试（模拟云端环境）
cd deploy
docker-compose up --build

# 4. 推送到 GitHub 并同步到 ModelScope
git add .
git commit -m "feat(v6.0): 更新功能"
git push origin main
# ModelScope 自动触发重新构建
```

### **版本发布**

```bash
# 1. 更新版本号
# 编辑 server.py 顶部的版本字符串
# 例如: 版本：6.0.0 → 版本：6.1.0

# 2. 更新 CHANGELOG.md
# 添加新版本的功能和修复记录

# 3. 提交并推送
git add .
git commit -m "release(v6.1.0): 新功能描述"
git push origin main

# 4. 在 ModelScope 创空间点击"重新构建"
```

---

## 🆕 v6.0 变更日志

### **新增功能**

- ✅ **Streamable HTTP 模式**: 替代 SSE，更好的兼容性
- ✅ **双向成长仪表盘**: 用户成长 + 系统进化可视化
- ✅ **智能启动脚本**: 自动检测模型、支持降级模式
- ✅ **统一模型路径**: 所有环境从 `models/` 目录加载

### **破坏性变更**

- ⚠️ **移除 SSE 模式**: 不再支持 `python server.py sse`
- ⚠️ **新的启动参数**: 改用端口号直接启动 HTTP 模式

### **迁移指南**

如果你之前使用的是 v5.x 的 SSE 模式：

```bash
# 旧命令（v5.x）- 已弃用
python server.py sse 7860

# 新命令（v6.0）- 推荐
python server.py 7860
```

---

**🎯 准备好开始部署了吗？按照上面的步骤操作即可！**

如有任何问题，请查阅相关文档或提交 Issue 到 GitHub 仓库。

---

**作者**: DevPartner Team
**版本**: v6.0.0
**最后更新**: 2026-07-03