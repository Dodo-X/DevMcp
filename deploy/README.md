# 部署指南

本目录包含 DevPartner 的所有部署相关配置和脚本。

## 📦 部署方式

### 方式 A: Docker Compose（推荐用于生产）

#### 前置要求
- Docker Engine ≥ 20.10
- Docker Compose ≥ 2.0
- 可用端口: 8082 (Web UI), 8080 (API)

#### 快速启动
```bash
cd deploy/

# 复制环境变量模板
cp .env.example .env

# 编辑配置（修改模型路径等）
vim .env

# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f devpartner
```

#### 访问服务
- Web Dashboard: http://localhost:8082
- API 文档: http://localhost:8082/api/docs
- 健康检查: http://localhost:8082/health

#### 常用命令
```bash
# 停止服务
docker-compose down

# 重启服务
docker-compose restart

# 查看资源占用
docker stats devpartner-agent

# 进入容器调试
docker-compose exec agent bash

# 备份数据
docker cp devpartner-agent:/app/data/databases ./backups/
```

---

### 方式 B: Docker 单容器（适合开发测试）

#### 构建镜像
```bash
cd deploy/
docker build -t devpartner:latest .
```

#### 运行容器
```bash
docker run -d \
  --name devpartner \
  -p 8082:8082 \
  -v $(pwd)/data:/app/data \
  -v /path/to/models:/app/models:ro \
  -e MODEL_PATH=/app/models/qwen3.5-9b-q4_1.gguf \
  devpartner:latest
```

#### 参数说明
| 参数 | 说明 | 示例 |
|------|------|------|
| `-p` | 端口映射 | 主机端口:容器端口 |
| `-v` | 目录挂载 | 本地路径:容器路径 |
| `-e` | 环境变量 | 配置项 |
| `--gpus` | GPU 加速（可选） | `all` 或 `"device=0"` |

---

### 方式 C: 本地裸机部署（推荐用于开发）

#### 前置要求
- Python 3.10+
- 内存 ≥ 8GB
- 磁盘空间 ≥ 10GB

#### 安装步骤
```bash
# 1. 克隆项目
git clone https://github.com/your-repo/devpartner.git
cd devPartner

# 2. 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows

# 3. 安装依赖
pip install -r requirements.txt

# 4. 安装 LLM 引擎
pip install llama-cpp-python>=0.2.79

# 5. 准备模型文件
mkdir -p models
# 将 qwen3.5-9b-q4_1.gguf 放入 models/ 目录

# 6. 配置系统
cp devpartner_agent/config.yaml.example devpartner_agent/config.yaml
# 编辑 config.yaml 设置模型路径

# 7. 启动服务
python server.py
```

---

## ⚙️ 配置说明

### 环境变量 (.env)

```bash
# ===== 基础配置 =====
DEVPARTNER_HOST=0.0.0.0
DEVPARTNER_PORT=8082
DEVPARTNER_DEBUG=false

# ===== LLM 配置 =====
MODEL_PATH=/app/models/qwen3.5-9b-q4_1.gguf
LLM_N_CTX=8192
LLM_N_GPU_LAYERS=-1
LLM_N_THREADS=8
LLM_MAX_TOKENS=2048
LLM_TEMPERATURE=0.3

# ===== 数据库配置 =====
DB_PATH=/app/data/databases/devpartner.db
DB_BACKUP_ENABLED=true
DB_BACKUP_INTERVAL=24h  # 自动备份间隔

# ===== 日志配置 =====
LOG_LEVEL=INFO
LOG_FILE=/app/data/logs/agent.log
LOG_MAX_SIZE=100MB
LOG_BACKUP_COUNT=5

# ===== 安全配置 =====
AUTH_ENABLED=false
API_KEY=your-secret-key-here  # 如果启用认证
ALLOWED_ORIGINS=*  # CORS 配置
```

### config.yaml (Agent 配置)

详见 [../README.md](../README.md#🔧-高级配置) 的"高级配置"章节。

---

## 🐳 Dockerfile 详解

### 多阶段构建优化
```dockerfile
# Stage 1: 基础环境
FROM python:3.11-slim as base
RUN apt-get update && apt-get install -y build-essential

# Stage 2: 依赖安装
FROM base as builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 3: 运行时镜像
FROM base as runtime
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY . .

EXPOSE 8082
CMD ["python", "server.py"]
```

**优势**:
- 最终镜像体积小（~800MB vs ~2GB）
- 构建缓存友好（依赖层独立）
- 安全性高（不暴露构建工具）

---

## 📊 性能调优

### CPU 优化
```yaml
# config.yaml
llm:
  n_threads: 8        # 设为 CPU 核心数
  n_batch: 512        # 批处理大小
  use_mmap: true      # 内存映射减少 RAM 占用
```

### GPU 优化
```bash
# docker-compose.yml
services:
  agent:
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
```

### 内存优化
```yaml
llm:
  n_ctx: 4096         # 减少上下文窗口
  use_mlock: false    # 不锁定物理内存
  split_mode: true    # 分层加载（大模型）
```

---

## 🔒 安全建议

### 生产环境必做
1. **修改默认密码**
   ```bash
   export API_KEY=$(openssl rand -hex 32)
   ```

2. **限制网络访问**
   ```yaml
   # docker-compose.yml
   ports:
     - "127.0.0.1:8082:8082"  # 仅本地访问
   ```

3. **启用 HTTPS**
   ```nginx
   # 反向代理配置
   server {
       listen 443 ssl;
       ssl_certificate /path/to/cert.pem;
       location / {
           proxy_pass http://localhost:8082;
       }
   }
   ```

4. **定期备份**
   ```bash
   # Cron 定时备份
   0 2 * * * docker exec devpartner-agent python scripts/backup_db.py
   ```

---

## 🔄 升级与回滚

### 升级到新版本
```bash
# 1. 备份数据
docker cp devpartner-agent:/app/data ./backup_$(date +%Y%m%d)

# 2. 拉取新镜像
docker pull devpartner:latest

# 3. 停止旧版本
docker-compose down

# 4. 启动新版本
docker-compose up -d

# 5. 运行数据库迁移（如需要）
docker-compose exec agent python scripts/upgrade_to_v5.py
```

### 回滚到旧版本
```bash
# 1. 停止当前版本
docker-compose down

# 2. 使用旧镜像启动
docker run -d ... devpartner:v5.1.0

# 3. 恢复备份数据
docker cp ./backup_YYYYMMDD/data devpartner-agent:/app/
```

---

## 🐛 故障排查

### 容器无法启动？
```bash
# 查看日志
docker-compose logs agent

# 常见原因:
# - 端口被占用 → 修改 ports 映射
# - 权限不足 → chmod 777 data/
# - 模型文件缺失 → 检查 volume 挂载
```

### LLM 加载失败？
```bash
# 检查模型文件
docker exec agent ls -lh models/

# 验证文件完整性
docker exec agent md5sum models/*.gguf

# 查看资源占用
docker stats agent
```

### 数据库损坏？
```bash
# 进入容器修复
docker exec -it agent bash
python scripts/check_db_integrity.py --repair

# 如修复失败，从备份恢复
docker cp backup_YYYYMMDD/databases/devpartner.db data/databases/
```

---

## 📞 技术支持

遇到部署问题？

1. 查看 [故障排查文档](../docs/troubleshooting.md)
2. 提交 [GitHub Issue](https://github.com/your-repo/issues)
3. 加入 [讨论区](https://github.com/your-repo/discussions)

---

**维护者**: DevPartner DevOps Team  
**最后更新**: 2026-07-03  
**适用版本**: DevPartner v5.2+