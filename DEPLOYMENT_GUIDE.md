# 🚀 DevPartner v7.3 部署指南

> **版本**: v7.3 | **更新日期**: 2026-07-10  
> **适用环境**: 本地开发 / Docker / ModelScope 云端  
> **推理引擎**: Ollama（已替代 llama-cpp-python）

---

## 📋 目录

1. [快速开始](#快速开始)
2. [Ollama 推理引擎配置](#ollama-推理引擎配置)
3. [GitHub → ModelScope 同步流程](#github--modelscope-同步流程)
4. [本地部署](#本地部署)
5. [Docker 部署](#docker-部署)
6. [ModelScope 云端部署](#modelscope-云端部署)
7. [常见问题排查](#常见问题排查)

---

## 快速开始

### ✅ 前置条件

| 依赖 | 版本要求 | 用途 |
|------|---------|------|
| Python | ≥3.10 | 运行时环境 |
| Git | ≥2.30 | 版本控制 |
| Docker (可选) | ≥20.10 | 容器化部署 |
| Ollama | 最新版 | LLM 推理引擎 |

> **重要**: v7.3 已完全迁移到 **Ollama**，不再需要下载 GGUF 模型文件。模型由 Ollama 统一管理。

### ⚡ 三步启动（本地）

```bash
# 0️⃣ 安装并启动 Ollama（如已安装可跳过）
# 下载: https://ollama.com
# 启动后拉取模型:
ollama pull qwen3:latest

# 1️⃣ 克隆代码
git clone https://github.com/YOUR_USERNAME/devPartner.git
cd devPartner

# 2️⃣ 安装依赖并启动
pip install -r requirements.txt
python server.py 7860
```

访问: http://localhost:7860

---

## Ollama 推理引擎配置

### 🎯 核心原则

**v7.3 起，DevPartner 使用 Ollama 作为推理引擎**，原因：
- 零模型文件管理 — 模型由 Ollama 自身拉取和管理
- 标准 HTTP API — 无需处理本地 GGUF 文件、CUDA 版本、指令集兼容
- 开箱即用 — 安装 Ollama → `ollama pull qwen3` → 直接使用
- 不依赖 llama-cpp-python 预编译 wheel

### 📦 安装 Ollama

```bash
# Windows / macOS / Linux 通用
# 从 https://ollama.com 下载安装包

# 启动 Ollama 服务（默认 http://localhost:11434）
ollama serve

# 拉取推荐模型（Qwen3，约 4.7GB）
ollama pull qwen3:latest

# 验证
ollama list
```

### ⚙️ 配置模型

编辑 `config.yaml`:

```yaml
llm:
  enabled: true
  ollama_model: "qwen3"        # Ollama 模型名称
  ollama_timeout: 120          # 推理超时（秒）
  temperature: 0.7
  max_tokens: 2048
  enhance_analysis: true
  fallback_to_rules: false
```

或通过环境变量：

```bash
# 自定义 Ollama 地址（非本地时）
export OLLAMA_BASE_URL="http://192.168.1.100:11434"
```

### 📁 目录结构（v7.3 简化）

```
devPartner/
├── models/
│   └── README.md             # Ollama 使用说明（Git 跟踪）
├── data/                     # 运行时数据
└── config.yaml               # LLM 配置（指向 Ollama）
```

> 不再需要 `models/` 目录存放 GGUF 文件。`models/README.md` 仅包含 Ollama 配置指引。

---

## GitHub → ModelScope 同步流程

### 🔄 推荐工作流

```
┌─────────────┐     push      ┌─────────────┐    自动同步     ┌─────────────┐
│   本地开发   │ ──────────→ │   GitHub    │ ───────────→ │  ModelScope │
│             │   (纯代码)   │  Repository │   (镜像同步)  │  云端运行   │
└─────────────┘              └─────────────┘               └─────────────┘
                                    ↑                            │
                                    │                       Ollama 自带模型
                              仅代码+配置                     (无需手动上传)
```

### 步骤详解

#### **Step 1: 准备 Git 仓库**

```bash
cd devPartner

# 初始化仓库（如果还没有）
git init

# 确认 .gitignore 已正确配置
cat .gitignore | grep "models/"

# 预期输出应包含:
# models/*.gguf
# models/*.bin
```

#### **Step 2: 提交代码（不含模型）**

```bash
git add .
git status

# 确认无大文件被跟踪
# 应该看到类似:
# On branch main
# Changes to be committed:
#   (use "git restore --staged <file>..." to unstage)
#         new file:   devpartner_agent/core/config.py
#         ...

git commit -m "feat(v7.3): Ollama 引擎 + 业务知识提取 + Obsidian 导出"
git push origin main
```

#### **Step 3: 配置 GitHub → ModelScope 同步**

**方式 A: 使用 ModelScope 镜像功能（推荐）**

1. 登录 [ModelScope](https://modelscope.cn)
2. 创建新项目/数据集
3. 选择"从 GitHub 导入"
4. 输入你的 GitHub 仓库地址
5. 开启自动同步（可选）

**方式 B: 手动同步**

```bash
# 在 ModelScope 项目目录下
git remote add github https://github.com/YOUR_USERNAME/devPartner.git
git pull github main
git push origin main
```

#### **Step 4: ⭐ ModelScope 云端配置 Ollama（核心步骤）**

> ⚠️ **v7.3 重要变更**: 不再需要上传 GGUF 模型文件。推理引擎已切换为 Ollama HTTP API。
> ModelScope 云端部署需要在容器中安装并启动 Ollama。

##### **📋 前置准备**

1. **确认 Dockerfile 包含 Ollama 安装**
   ```bash
   # 查看 Dockerfile
   cat Dockerfile | grep ollama
   
   # 应包含:
   # RUN curl -fsSL https://ollama.com/install.sh | sh
   ```

2. **确认启动脚本拉取模型**
   ```bash
   # 查看启动命令或 docker-compose.yml
   # 应包含:
   # ollama serve &
   # sleep 3
   # ollama pull qwen3:latest
   ```

---

##### **🎯 方法一：Docker 内嵌 Ollama（推荐）**

**适用场景**: ModelScope 云端运行、Docker 部署

**操作步骤**:

1️⃣ **修改 Dockerfile**
   ```dockerfile
   FROM python:3.11-slim
   
   # 安装 Ollama
   RUN curl -fsSL https://ollama.com/install.sh | sh
   
   # 复制代码
   COPY . /app
   WORKDIR /app
   RUN pip install -r requirements.txt
   
   # 启动脚本
   CMD ["bash", "start.sh"]
   ```

2️⃣ **编写 start.sh**
   ```bash
   #!/bin/bash
   # 启动 Ollama 后台服务
   ollama serve &
   sleep 5
   
   # 拉取模型（首次启动需要，后续可缓存）
   ollama pull qwen3:latest
   
   # 启动 DevPartner
   python server.py 7860
   ```

3️⃣ **构建并推送镜像**
   ```bash
   docker build -t devpartner:v7.3 .
   docker tag devpartner:v7.3 registry.cn-hangzhou.aliyuncs.com/yournamespace/devpartner:v7.3
   docker push registry.cn-hangzhou.aliyuncs.com/yournamespace/devpartner:v7.3
   ```

**✅ 优点**:
- 模型由 Ollama 管理，自动处理版本和量化
- 无需手动下载/上传 GGUF 文件
- Ollama 支持 GPU 加速（自动检测 CUDA/Metal）

**❌ 缺点**:
- 首次拉取模型需网络和时间
- 容器内需同时运行 Ollama + DevPartner

---

##### **🎯 方法二：Ollama 独立服务 + DevPartner 轻量容器**

**适用场景**: 已有独立 Ollama 服务，多实例共享

**操作步骤**:

1️⃣ **部署独立 Ollama 服务**
   ```bash
   # 在 GPU 节点上部署 Ollama
   ollama serve
   ollama pull qwen3:latest
   ```

2️⃣ **DevPartner 指向远程 Ollama**
   ```yaml
   # config.yaml 或环境变量
   llm:
     ollama_model: "qwen3"
   
   # 环境变量方式
   environment:
     - OLLAMA_BASE_URL=http://ollama-host:11434
   ```

3️⃣ **构建轻量 DevPartner 镜像**（不含 Ollama）
   ```dockerfile
   FROM python:3.11-slim
   COPY . /app
   WORKDIR /app
   RUN pip install -r requirements.txt
   CMD ["python", "server.py", "7860"]
   ```

**✅ 优点**:
- 镜像轻量（~500MB），无需内嵌 Ollama
- 多实例共享一个 Ollama 推理服务
- 模型集中管理，更新方便

**❌ 缺点**:
- 需要独立的 Ollama 服务节点
- 网络延迟可能影响推理速度

---

##### **🎯 方法三：ModelScope 创空间 + 预装 Ollama**

**适用场景**: ModelScope 创空间一键部署

**操作步骤**:

1️⃣ **在 ModelScope 创建创空间**
   ```
   选择 Python 3.10+ 环境
   上传代码（通过 GitHub 同步）
   ```

2️⃣ **配置启动命令**
   ```bash
   # 创空间设置 → 启动命令
   curl -fsSL https://ollama.com/install.sh | sh
   ollama serve &
   sleep 5
   ollama pull qwen3:latest
   pip install -r requirements.txt
   python server.py 7860
   ```

3️⃣ **验证部署**
   ```bash
   # 测试 API
   curl https://modelscope.cn/studios/yourname/devpartner/api/system/status
   ```

**✅ 优点**:
- 零配置，平台托管
- 免费额度大

**❌ 缺点**:
- 创空间资源有限（CPU 推理较慢）
- 每次重启需重新拉模型（除非持久化）

---

#### **Step 5: 选择最适合你的方案**

| 部署场景 | 推荐方案 | 原因 |
|---------|---------|------|
| **个人开发/学习** | 本地 Ollama | 最简单，安装即可用 |
| **小团队内部使用** | Docker + 独立 Ollama 节点 | 团队共享推理资源 |
| **ModelScope 公开服务** | Docker 内嵌 Ollama | 自包含，无需外部依赖 |
| **企业私有部署** | Ollama 独立服务 + 轻量镜像 | 安全可控，集中管理 |
| **高并发生产环境** | Ollama 集群 + LB | 弹性扩展，性能最优 |

**💡 个人推荐（针对你的情况）**:
```
如果你要部署到 ModelScope 创空间:
  → 使用方法一（Docker 内嵌 Ollama）

如果你要在本地开发测试:
  → 安装 Ollama → ollama pull qwen3 → python server.py 7860
```

---

在 `config.yaml` 中配置：

```yaml
llm:
  enabled: true
  ollama_model: "qwen3"
  ollama_timeout: 120
  temperature: 0.7
  max_tokens: 2048
  enhance_analysis: true
  fallback_to_rules: false
```

---

## 本地部署

### 📦 安装依赖

```bash
# 创建虚拟环境（推荐）
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# 安装依赖
pip install -r requirements.txt

# 确认 Ollama 运行中
ollama list
```

### 🚀 启动服务

#### 方式一：直接启动

```bash
python server.py 7860
```

#### 方式二：使用启动脚本

**Windows:**
```cmd
start.bat
```

### ✅ 验证服务

```bash
# 测试 API
curl http://localhost:7860/api/system/status

# 检查 Ollama 连接
curl http://localhost:11434/api/tags
```

---

## Docker 部署

### 🐳 构建镜像

#### 轻量模式（不含 Ollama，连接外部服务）

```bash
# 构建轻量镜像（~500MB）
docker build \
  -t devpartner:lite \
  -f Dockerfile .
```

#### 完整模式（内嵌 Ollama）

```bash
# 构建完整镜像（~2GB，含 Ollama + 模型需额外拉取）
docker build \
  -t devpartner:full \
  -f Dockerfile .
```

### ▶️ 运行容器

#### 使用 docker-compose（推荐）

```yaml
# docker-compose.yml
services:
  devpartner:
    image: devpartner:lite
    ports:
      - "7860:7860"
    volumes:
      - ./data:/app/data
    environment:
      - OLLAMA_BASE_URL=http://host.docker.internal:11434  # 连宿主机 Ollama
    restart: unless-stopped
```

```bash
docker-compose up -d
docker-compose logs -f devpartner
```

#### 使用 docker run

**轻量模式（连接宿主机 Ollama）：**
```bash
docker run -d \
  --name devpartner \
  -p 7860:7860 \
  -v $(pwd)/data:/app/data \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  --restart unless-stopped \
  devpartner:lite
```

**完整模式（内嵌 Ollama）：**
```bash
docker run -d \
  --name devpartner \
  -p 7860:7860 \
  -p 11434:11434 \
  -v $(pwd)/data:/app/data \
  --restart unless-stopped \
  devpartner:full
```

### 📊 资源需求

| 模式 | CPU | 内存 | GPU | 存储 |
|------|-----|------|-----|------|
| 轻量模式（连外部 Ollama） | 2核+ | 2GB+ | 无需 | 2GB+ |
| 完整模式（内嵌 Ollama） | 4核+ | 8GB+ | 推荐 | 8GB+ |
| GPU 加速 | 4核+ | 8GB+ | 8GB+ VRAM | 8GB+ |

---

## ModelScope 云端部署

### ☁️ 准备工作

1. 注册 [ModelScope](https://modelscope.cn) 账号
2. 创建项目空间
3. 准备 Dockerfile（包含 Ollama 安装步骤）

### 📤 步骤一：上传代码

**通过 GitHub 同步（推荐）：**
1. 将代码推送到 GitHub
2. 在 ModelScope 项目设置中启用 GitHub 同步
3. 等待自动同步完成

**手动上传：**
```bash
# 打包代码（排除数据目录）
tar --exclude='data/*' \
    --exclude='.git' \
    --exclude='__pycache__' \
    -czvf devpartner-code.tar.gz .

# 通过 ModelScope Web UI 或 CLI 上传
mscli upload devpartner-code.tar.gz
```

### 📦 步骤二：配置 Ollama

#### **方案 A: Docker 内嵌 Ollama（推荐）**

Dockerfile 中预装 Ollama，启动时自动拉取模型：

```dockerfile
FROM python:3.11-slim
RUN curl -fsSL https://ollama.com/install.sh | sh
COPY . /app
WORKDIR /app
RUN pip install -r requirements.txt
CMD ["bash", "-c", "ollama serve & sleep 5 && ollama pull qwen3 && python server.py 7860"]
```

#### **方案 B: 创空间手动安装**

在创空间启动脚本中安装：
```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve &
sleep 5
ollama pull qwen3:latest
pip install -r requirements.txt
python server.py 7860
```

### 🚀 步骤三：部署应用

#### **使用 ModelScope Notebook（快速测试）**

```python
import subprocess
subprocess.run(["pip", "install", "-r", "requirements.txt"], check=True)
subprocess.run(["python", "server.py", "7860"])
```

#### **使用 ModelScope 创空间 (生产环境)**

1. 上传代码到创空间
2. 配置启动命令（见方案 B）
3. 设置端口为 7860
4. 启动创空间

### 🔧 步骤四：验证部署

```bash
# 检查服务状态
curl https://modelscope.cn/studios/yourname/devpartner/api/system/status

# 检查 LLM 引擎（应返回 "ollama"）
curl https://modelscope.cn/studios/yourname/devpartner/api/system/status | grep engine
```

---

## 常见问题排查

### ❌ 问题 1: Ollama 连接失败

**症状**: 
```
Ollama 服务 (http://localhost:11434) 不可达
```

**解决方案**:
```bash
# 1. 确认 Ollama 正在运行
ollama list
# 或
curl http://localhost:11434/api/tags

# 2. 如果未运行，启动 Ollama
ollama serve

# 3. Docker 内连接宿主机 Ollama
# 使用 host.docker.internal 替代 localhost
export OLLAMA_BASE_URL=http://host.docker.internal:11434

# 4. 检查防火墙/端口占用
netstat -ano | findstr 11434  # Windows
lsof -i :11434                 # Linux/Mac
```

### ❌ 问题 2: 模型未找到

**症状**: 
```
model 'qwen3' not found
```

**解决方案**:
```bash
# 1. 列出已安装的模型
ollama list

# 2. 拉取推荐模型
ollama pull qwen3:latest

# 3. 或使用其他可用模型
ollama pull qwen2.5:7b

# 4. 修改 config.yaml 中的模型名
llm:
  ollama_model: "qwen2.5:7b"
```

### ❌ 问题 3: Docker 容器内存不足

**症状**: 容器频繁重启或 OOMKilled

**解决方案**:
```bash
# 1. 使用轻量模式（连接宿主机 Ollama）
docker run -d \
  --name devpartner-lite \
  -p 7860:7860 \
  --memory=2g \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  devpartner:lite

# 2. 增加内存限制（内嵌 Ollama 模式）
docker update --memory=8g --memory-swap=16g devpartner

# 3. 启用 GPU（如果可用）
docker run -d \
  --gpus all \
  --name devpartner-gpu \
  -p 7860:7860 \
  devpartner:full
```

### ❌ 问题 4: API 调用超时

**症状**: 页面长时间无响应

**解决方案**:
```bash
# 1. 检查后端 API
curl http://localhost:7860/api/system/status
curl http://localhost:7860/api/health/check

# 2. 增加 Ollama 超时（config.yaml）
llm:
  ollama_timeout: 300  # 增加到 5 分钟

# 3. 查看服务器日志
# 日志输出到控制台，查看推理耗时
```

### ❌ 问题 5: ModelScope 同步延迟

**症状**: GitHub 更新后 ModelScope 未及时同步

**解决方案**:
1. 检查 ModelScope 项目设置的同步状态
2. 手动触发同步（Web UI → 设置 → 同步）
3. 或使用 CLI 强制同步:
   ```bash
   mscli sync --repo YOUR_REPO_NAME --force
   ```

---

## 📊 性能优化建议

### 💾 内存优化

```yaml
# config.yaml
llm:
  ollama_model: "qwen3:latest"   # 使用量化版本减少内存
  ollama_timeout: 120            # 适当超时
  temperature: 0.7
  max_tokens: 1024               # 减小最大输出长度
```

Ollama 端优化:
```bash
# 设置 Ollama 并发限制
export OLLAMA_NUM_PARALLEL=2
export OLLAMA_MAX_LOADED_MODELS=1
```

### ⚡ 响应速度优化

1. **使用 GPU 加速**: Ollama 自动检测 CUDA/Metal，确保驱动正确安装
2. **模型预热**: 启动后先跑一次简单推理预热模型
3. **异步处理**: DevPartner 后台任务队列已支持异步分析

### 🔄 自动扩展

```yaml
# Kubernetes HPA（适用于独立 Ollama 服务模式）
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: devpartner-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: devpartner
  minReplicas: 1
  maxReplicas: 5
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

---

## 📝 维护清单

### 定期任务

| 频率 | 任务 | 命令 |
|------|------|------|
| 每日 | 检查服务状态 | `curl localhost:7860/api/health/check` |
| 每周 | 检查 Ollama 模型更新 | `ollama pull qwen3:latest` |
| 每月 | 备份数据库 | `cp data/devpartner.db backups/db_$(date +%Y%m).db` |
| 季度 | 更新依赖 | `pip install -r requirements.txt --upgrade` |

### 监控指标

- **API 响应时间**: P99 < 500ms
- **LLM 推理延迟**: < 30s (Ollama)
- **错误率**: < 1%
- **CPU 使用率**: < 80%
- **内存使用率**: < 85%

---

## 📚 相关资源

- **主文档**: [README.md](README.md)
- **架构设计**: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **API 文档**: [docs/API.md](docs/API.md)
- **Ollama 说明**: [models/README.md](models/README.md)
- **变更记录**: [CHANGELOG.md](CHANGELOG.md)

---

## 🆘 获取帮助

- **GitHub Issues**: https://github.com/YOUR_USERNAME/devPartner/issues
- **Ollama 文档**: https://github.com/ollama/ollama
- **ModelScope 论坛**: https://modelscope.cn/forum

---

**维护者**: DevPartner Team  
**最后更新**: 2026-07-10  
**适用版本**: DevPartner v7.3+