# 🚀 DevPartner v6.0 部署指南

> **版本**: v6.0 | **更新日期**: 2026-07-03  
> **适用环境**: 本地开发 / Docker / ModelScope 云端

---

## 📋 目录

1. [快速开始](#快速开始)
2. [模型文件管理](#模型文件管理)
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
| 模型文件 | Qwen3.5-9B-Q4_1.gguf (~5.7GB) | LLM 推理 |

### ⚡ 三步启动（本地）

```bash
# 1️⃣ 克隆代码
git clone https://github.com/YOUR_USERNAME/devPartner.git
cd devPartner

# 2️⃣ 下载模型文件到 models/ 目录
# 方式A: 手动下载（推荐）
# 从 ModelScope/HuggingFace 下载 Qwen3.5-9B-Q4_1.gguf 到 ./models/
# 或使用以下命令自动下载:
python scripts/download_model.py

# 3️⃣ 安装依赖并启动
pip install -r requirements.txt
python server.py sse 7860
```

访问: http://localhost:7860/dashboard

---

## 模型文件管理

### 🎯 核心原则

**模型文件不纳入 Git 版本控制**，原因：
- 文件过大 (~5.7GB)，超出 GitHub 单文件限制 (100MB)
- Git LFS 免费额度有限 (1GB存储 + 1GB/月带宽)
- ModelScope 支持更灵活的模型托管方式

### 📁 目录结构

```
devPartner/
├── models/
│   ├── .gitkeep              # 占位符（Git 跟踪）
│   ├── README.md             # 模型说明文档（Git 跟踪）
│   └── Qwen3.5-9B-Q4_1.gguf  # ❌ 不纳入 Git（手动管理）
```

### 🔧 .gitignore 配置

```gitignore
# ===== 模型文件（v6.0: 不纳入 Git）=====
models/*.gguf           # GGUF 格式模型文件
models/*.bin            # 其他二进制模型文件
models/*.safetensors    # HuggingFace safetensors 格式
!models/.gitkeep        # 保留占位符文件
!models/README.md       # 保留说明文档
```

---

## GitHub → ModelScope 同步流程

### 🔄 推荐工作流

```
┌─────────────┐     push      ┌─────────────┐    自动同步     ┌─────────────┐
│   本地开发   │ ──────────→ │   GitHub    │ ───────────→ │  ModelScope │
│             │   (不含模型) │  Repository │   (镜像同步)  │  云端运行   │
└─────────────┘              └─────────────┘               └─────────────┘
                                    ↑                            │
                                    │                      手动上传模型
                              仅代码+配置                     (Dataset/Volume)
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

# 确认 models/*.gguf 未被跟踪
# 应该看到类似:
# On branch main
# Changes to be committed:
#   (use "git restore --staged <file>..." to unstage)
#         new file:   devpartner_agent/core/config.py
#         ...
# Untracked files:
#   (use "git add <file>..." to include in commit)
#         models/Qwen3.5-9B-Q4_1.gguf  ← 这个不应该出现！

git commit -m "feat(v6.0): 双向成长仪表盘 + 多环境部署支持"
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

#### **Step 4: 处理模型文件**

**在 ModelScope 端有三种选择：**

##### **选项 A: 上传到 Dataset（推荐用于云端）**

```bash
# 1. 在 ModelScope 创建 Dataset
# 2. 上传模型文件到 Dataset
# 3. 在 docker-compose.yml 中配置 volume 挂载:

services:
  devpartner:
    volumes:
      - modelscope_dataset:/app/models  # 挂载 Dataset 到容器内

volumes:
  modelscope_dataset:
    external: true
    name: your_model_dataset_name
```

##### **选项 B: 打包进 Docker 镜像（适合离线环境）**

```bash
# 修改 deploy/.dockerignore，注释掉模型排除规则:
# models/*.gguf  ← 注释这行

# 构建完整镜像（包含模型，~6.5GB）
docker build -t devpartner:full -f deploy/Dockerfile .

# 注意: 构建时间长，镜像体积大
```

##### **选项 C: 运行时动态下载（需要网络）**

在 `config.yaml` 中配置：

```yaml
llm:
  model_source: "remote"
  model_url: "https://modelscope.cn/models/Qwen/Qwen3.5-9B-Instruct-GGUF/resolve/master/Qwen3.5-9B-Q4_1.gguf"
  auto_download: true
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

# 验证安装
python -c "import llama_cpp; print('✅ llama-cpp-python OK')"
```

### 🚀 启动服务

#### 方式一：直接启动

```bash
python server.py sse 7860
```

#### 方式二：使用启动脚本

**Linux/Mac:**
```bash
chmod +x deploy/start.sh
./deploy/start.sh
```

**Windows:**
```cmd
deploy\start.bat
```

### ✅ 验证服务

```bash
# 测试 API
curl http://localhost:7860/api/system/status

# 访问 Dashboard
# 打开浏览器访问: http://localhost:7860/dashboard
```

---

## Docker 部署

### 🐳 构建镜像

#### 轻量模式（推荐，不包含模型）

```bash
# 构建轻量镜像（~800MB）
docker build \
  --build-arg SKIP_MODEL=true \
  -t devpartner:lite \
  -f deploy/Dockerfile .
```

#### 完整模式（包含模型）

```bash
# 1. 确保 models/ 目录有模型文件
ls -lh models/Qwen3.5-9B-Q4_1.gguf

# 2. 修改 deploy/.dockerignore，取消模型排除
# 注释掉: models/*.gguf

# 3. 构建完整镜像（~6.5GB，耗时较长）
docker build \
  -t devpartner:full \
  -f deploy/Dockerfile .
```

### ▶️ 运行容器

#### 使用 docker-compose（推荐）

```bash
# 编辑 docker-compose.yml 配置
vim deploy/docker-compose.yml

# 启动服务
cd deploy
docker-compose up -d

# 查看日志
docker-compose logs -f devpartner
```

#### 使用 docker run

**轻量模式（挂载本地模型）：**
```bash
docker run -d \
  --name devpartner \
  -p 7860:7860 \
  -v $(pwd)/models:/app/models \
  -v $(pwd)/data:/app/data \
  --restart unless-stopped \
  devpartner:lite
```

**完整模式（模型内置）：**
```bash
docker run -d \
  --name devpartner \
  -p 7860:7860 \
  -v $(pwd)/data:/app/data \
  --restart unless-stopped \
  devpartner:full
```

### 📊 资源需求

| 模式 | CPU | 内存 | GPU | 存储 |
|------|-----|------|-----|------|
| 轻量模式 | 2核+ | 4GB+ | 可选 | 2GB+ |
| 完整模式 | 4核+ | 8GB+ | 推荐 | 8GB+ |
| GPU 加速 | 4核+ | 8GB+ | 8GB+ VRAM | 8GB+ |

---

## ModelScope 云端部署

### ☁️ 准备工作

1. 注册 [ModelScope](https://modelscope.cn) 账号
2. 创建项目空间
3. 准备模型文件（上传到 Dataset 或打包进镜像）

### 📤 步骤一：上传代码

**通过 GitHub 同步（推荐）：**
1. 将代码推送到 GitHub
2. 在 ModelScope 项目设置中启用 GitHub 同步
3. 等待自动同步完成

**手动上传：**
```bash
# 打包代码（排除模型和数据）
tar --exclude='models/*.gguf' \
    --exclude='data/*' \
    --exclude='.git' \
    --exclude='__pycache__' \
    -czvf devpartner-code.tar.gz .

# 通过 ModelScope Web UI 或 CLI 上传
mscli upload devpartner-code.tar.gz
```

### 📦 步骤二：处理模型文件

#### **方案 A: 使用 ModelScope Dataset（推荐）**

1. 在 ModelScope 创建 Dataset
2. 上传模型文件:
   ```bash
   mscli dataset upload your-dataset-name models/Qwen3.5-9B-Q4_1.gguf
   ```
3. 在部署配置中挂载 Dataset

#### **方案 B: 打包进镜像**

```dockerfile
# 在 Dockerfile 中添加:
COPY models/Qwen3.5-9B-Q4_1.gguf /app/models/

# 构建并推送镜像到 ModelScope Registry
docker tag devpartner:full registry.cn-beijing.aliyuncs.com/yournamespace/devpartner:latest
docker push registry.cn-beijing.aliyuncs.com/yournamespace/devpartner:latest
```

### 🚀 步骤三：部署应用

#### **使用 ModelScope Notebook（快速测试）**

```python
# 在 Notebook 中运行
import subprocess
subprocess.run(["pip", "install", "-r", "requirements.txt"], check=True)
subprocess.run(["python", "server.py", "sse", "7860"])
```

#### **使用 ModelScope Swarm (生产环境)**

创建 `swarm.yaml`:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: devpartner
spec:
  replicas: 1
  selector:
    matchLabels:
      app: devpartner
  template:
    metadata:
      labels:
        app: devpartner
    spec:
      containers:
      - name: devpartner
        image: registry.cn-beijing.aliyuncs.com/yournamespace/devpartner:latest
        ports:
        - containerPort: 7860
        resources:
          requests:
            memory: "4Gi"
            cpu: "2000m"
          limits:
            memory: "8Gi"
            cpu: "4000m"
        volumeMounts:
        - name: model-data
          mountPath: /app/models
      volumes:
      - name: model-data
        persistentVolumeClaim:
          claimName: model-pvc
---
apiVersion: v1
kind: Service
metadata:
  name: devpartner-service
spec:
  selector:
    app: devpartner
  ports:
  - port: 80
    targetPort: 7860
  type: LoadBalancer
```

部署:
```bash
kubectl apply -f swarm.yaml
kubectl get svc devpartner-service
```

### 🔧 步骤四：验证部署

```bash
# 检查 Pod 状态
kubectl get pods -l app=devpartner

# 查看日志
kubectl logs -f deployment/devpartner

# 测试 API
curl http://YOUR-SERVICE-URL/api/system/status
```

---

## 常见问题排查

### ❌ 问题 1: 模型文件未找到

**症状**: 
```
FileNotFoundError: No such file or directory: './models/Qwen3.5-9B-Q4_1.gguf'
```

**解决方案**:
```bash
# 1. 确认模型文件存在
ls -lh models/Qwen3.5-9B-Q4_1.gguf

# 2. 检查路径配置
grep -r "model_path" config.yaml

# 3. Docker 环境检查 volume 挂载
docker inspect devpartner | grep -A 10 "Mounts"
```

### ❌ 问题 2: GitHub 推送失败（文件过大）

**症状**: 
```
error: GH001: large files detected.
This repository exceeds the 100MB GitHub file size limit.
```

**解决方案**:
```bash
# 1. 确认 .gitignore 已生效
git check-ignore models/Qwen3.5-9B-Q4_1.gguf
# 应该输出: models/Qwen3.5-9B-Q4_1.gguf

# 2. 如果已被跟踪，先移除
git rm --cached models/Qwen3.5-9B-Q4_1.gguf
git commit -m "chore: remove model from git tracking"

# 3. 如果历史提交包含大文件，使用 Git History 重写
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch models/Qwen3.5-9B-Q4_1.gguf' \
  --prune-empty --tag-name-filter cat -- --all
```

### ❌ 问题 3: Docker 容器内存不足

**症状**: 容器频繁重启或 OOMKilled

**解决方案**:
```bash
# 1. 增加内存限制
docker update --memory=8g --memory-swap=16g devpartner

# 2. 使用轻量模式 + volume 挂载
docker run -d \
  --name devpartner-lite \
  -p 7860:7860 \
  --memory=4g \
  -v $(pwd)/models:/app/models \
  devpartner:lite

# 3. 启用 GPU（如果可用）
docker run -d \
  --gpus all \
  --name devpartner-gpu \
  -p 7860:7860 \
  devpartner:full
```

### ❌ 问题 4: Dashboard 数据加载失败

**症状**: 页面显示"加载中..."或错误提示

**解决方案**:
```bash
# 1. 检查后端 API 是否正常
curl http://localhost:7860/api/growth/user-overview
curl http://localhost:7860/api/system/status

# 2. 查看服务器日志
tail -f logs/server.log | grep ERROR

# 3. 检查数据库是否初始化
sqlite3 data/devpartner.db "SELECT COUNT(*) FROM user_skills;"
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
  n_ctx: 2048           # 减小上下文窗口（默认4096）
  n_batch: 512          # 减小批处理大小
  n_gpu_layers: -1      # 使用所有GPU层（如果有GPU）
  use_mmap: true        # 使用内存映射
  use_mlock: false      # 不锁定内存（避免OOM）
```

### ⚡ 响应速度优化

1. **启用 HTTP 缓存**（Nginx 反向代理）
2. **使用 Redis 缓存**高频查询结果
3. **异步加载** Dashboard 组件
4. **CDN 加速**静态资源

### 🔄 自动扩展

```yaml
# Kubernetes HPA
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
| 每周 | 清理日志 | `truncate -s 0 logs/*.log` |
| 每月 | 备份数据库 | `cp data/devpartner.db backups/db_$(date +%Y%m).db` |
| 季度 | 更新依赖 | `pip install -r requirements.txt --upgrade` |
| 按需 | 更新模型 | 下载新版模型文件替换 |

### 监控指标

- **API 响应时间**: P99 < 500ms
- **错误率**: < 1%
- **CPU 使用率**: < 80%
- **内存使用率**: < 85%
- **磁盘使用率**: < 90%

---

## 📚 相关资源

- **主文档**: [README.md](README.md)
- **架构设计**: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **API 文档**: [docs/API.md](docs/API.md)
- **模型说明**: [models/README.md](models/README.md)
- **变更记录**: [CHANGELOG.md](CHANGELOG.md)

---

## 🆘 获取帮助

- **GitHub Issues**: https://github.com/YOUR_USERNAME/devPartner/issues
- **ModelScope 论坛**: https://modelscope.cn/forum
- **文档反馈**: 提交 PR 改进本文档

---

**维护者**: DevPartner Team  
**最后更新**: 2026-07-03  
**适用版本**: DevPartner v6.0+