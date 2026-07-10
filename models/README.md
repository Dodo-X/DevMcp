# 🤖 Ollama 推理引擎说明

## 📋 概述

**v7.3 起，DevPartner 使用 [Ollama](https://ollama.com) 作为 LLM 推理引擎。**

不再需要手动下载 GGUF 模型文件到此目录。模型由 Ollama 统一管理。

---

## 🔧 安装 Ollama

### 方式一：官方安装包（推荐）

1. 访问 [ollama.com](https://ollama.com) 下载对应系统安装包
2. 安装完成后启动服务：
   ```bash
   ollama serve
   ```
3. 拉取推荐模型：
   ```bash
   ollama pull qwen3:latest
   ```

### 方式二：Docker

```bash
docker run -d --name ollama -p 11434:11434 ollama/ollama
docker exec -it ollama ollama pull qwen3:latest
```

### 方式三：Linux 命令行

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3:latest
```

---

## 📦 推荐模型

| 场景 | 模型 | 大小 | 命令 |
|------|------|------|------|
| 轻量级 | `qwen3:1.8b` | ~1.1GB | `ollama pull qwen3:1.8b` |
| 平衡级 | `qwen3:latest` | ~4.7GB | `ollama pull qwen3:latest` |
| 高性能 | `qwen3:14b` | ~8.5GB | `ollama pull qwen3:14b` |
| 备选 | `qwen2.5:7b` | ~4.4GB | `ollama pull qwen2.5:7b` |

> **推荐 `qwen3:latest`**：中文能力强、体积适中、推理速度快。

---

## ⚙️ 配置说明

### DevPartner 自动检测

DevPartner 默认连接 `http://localhost:11434`，自动检测 Ollama 服务状态和可用模型。

### 手动配置

编辑 `config.yaml`:

```yaml
llm:
  enabled: true
  ollama_model: "qwen3"         # Ollama 模型名
  ollama_timeout: 120           # 推理超时（秒）
  temperature: 0.7
  max_tokens: 2048
  enhance_analysis: true
  fallback_to_rules: false
```

### 环境变量

```bash
# 自定义 Ollama 地址（非本地时）
export OLLAMA_BASE_URL="http://192.168.1.100:11434"

# Windows (PowerShell)
$env:OLLAMA_BASE_URL="http://192.168.1.100:11434"
```

---

## 🐳 Docker 部署

### 轻量模式（连宿主机 Ollama）

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
      - OLLAMA_BASE_URL=http://host.docker.internal:11434
```

### 完整模式（内嵌 Ollama）

```dockerfile
FROM python:3.11-slim
RUN curl -fsSL https://ollama.com/install.sh | sh
COPY . /app
WORKDIR /app
RUN pip install -r requirements.txt
CMD ["bash", "-c", "ollama serve & sleep 5 && ollama pull qwen3 && python server.py 7860"]
```

---

## ✅ 验证

```bash
# 检查 Ollama 服务
ollama list
# 或
curl http://localhost:11434/api/tags

# 检查 DevPartner LLM 引擎
curl http://localhost:7860/api/system/status | grep engine
# 应返回: "engine": "ollama"

# 运行检查脚本
python scripts/check_model.py
```

---

## ❓ 常见问题

### Q1: 下载速度慢怎么办？

**A**: Ollama 从官方仓库拉取模型，国内可使用镜像：
```bash
# 设置 Ollama 镜像（如有）
export OLLAMA_HOST=https://ollama-mirror.example.com
```

### Q2: 可以用其他模型吗？

**A**: 可以！Ollama 支持数千种模型：
```bash
ollama pull llama3.2:3b
ollama pull mistral:7b
ollama pull deepseek-r1:8b
```

修改 `config.yaml` 中 `ollama_model` 即可。

### Q3: 如何切换模型版本？

**A**:
```bash
# 拉取不同版本
ollama pull qwen3:14b

# 修改 config.yaml
llm:
  ollama_model: "qwen3:14b"
```

### Q4: GPU 加速如何配置？

**A**: Ollama 自动检测 GPU：
- **NVIDIA**: 自动使用 CUDA（需安装 NVIDIA 驱动）
- **Apple Silicon**: 自动使用 Metal
- **AMD**: 自动使用 ROCm（Linux）

无需额外配置。

### Q5: 如何清理不需要的模型？

**A**:
```bash
# 列出所有模型
ollama list

# 删除指定模型
ollama rm qwen3:1.8b
```

---

## 📚 相关资源

- **Ollama 官方**: https://ollama.com
- **Ollama GitHub**: https://github.com/ollama/ollama
- **模型库**: https://ollama.com/library
- **DevPartner 部署指南**: [../DEPLOYMENT_GUIDE.md](../DEPLOYMENT_GUIDE.md)

---

## 📝 维护记录

| 日期 | 操作 | 说明 |
|------|------|------|
| 2026-07-10 | 重写文档 | v7.3 迁移到 Ollama，移除 GGUF 说明 |
| 2026-07-03 | 创建文档 | v6.0 初始化（已废弃） |

---

**维护者**: DevPartner Team  
**最后更新**: 2026-07-10  
**适用版本**: DevPartner v7.3+
