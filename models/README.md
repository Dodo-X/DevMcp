# 🤖 模型文件目录

## 📋 说明

此目录用于存放 LLM 推理所需的模型文件。

**重要**: 此目录下的模型文件 **不纳入 Git 版本控制**（见 `.gitignore` 配置）。

---

## 🔧 支持的模型格式

| 格式 | 扩展名 | 用途 | 推荐工具 |
|------|--------|------|---------|
| GGUF | `.gguf` | llama-cpp-python 推理 | ✅ **推荐** |
| Safetensors | `.safetensors` | HuggingFace transformers | 备选 |
| PyTorch Bin | `.bin` | 原生 PyTorch 模型 | 不推荐 |

---

## 📦 当前项目使用的模型

### **Qwen3.5-9B-Instruct-GGUF (Q4_1 量化版本)**

- **文件名**: `Qwen3.5-9B-Q4_1.gguf`
- **大小**: ~5.7 GB
- **量化等级**: Q4_1 (4-bit量化，平衡性能与体积)
- **用途**: 本地 LLM 推理、对话生成、代码分析

#### 为什么选择这个模型？

1. ✅ **中文能力强**: Qwen 系列在中文场景表现优异
2. ✅ **体积适中**: 9B参数 + 4bit量化 = ~5.7GB，可本地运行
3. ✅ **推理速度快**: 支持 llama-cpp-python 加速
4. ✅ **功能全面**: 对话、代码、数学、推理全覆盖

---

## ⬇️ 下载方式

### 方式一：从 ModelScope 下载（国内用户推荐）

```bash
# 安装 modelscope CLI
pip install modelscope

# 下载模型到当前目录
modelscope download --model Qwen/Qwen3.5-9B-Instruct-GGUF \
    --local_dir . \
    Qwen3.5-9B-Q4_1.gguf
```

### 方式二：从 HuggingFace 下载

```bash
# 使用 huggingface-cli
pip install huggingface_hub

huggingface-cli download Qwen/Qwen3.5-9B-Instruct-GGUF \
    Qwen3.5-9B-Q4_1.gguf \
    --local-dir .
```

### 方式三：手动下载

1. 访问 [ModelScope 模型页面](https://modelscope.cn/models/Qwen/Qwen3.5-9B-Instruct-GGUF/files)
2. 找到 `Qwen3.5-9B-Q4_1.gguf` 文件
3. 点击下载（约 5.7GB）
4. 将文件放到本目录 (`models/`)

---

## 🔧 验证模型文件

下载完成后，验证文件完整性：

```bash
# 检查文件是否存在
ls -lh models/Qwen3.5-9B-Q4_1.gguf

# 预期输出:
# -rw-r--r-- 1 user user 5.7G Jul  3 13:30 models/Qwen3.5-9B-Q4_1.gguf

# 验证 MD5（如果提供）
md5sum models/Qwen3.5-9B-Q4_1.gguf
```

---

## ⚙️ 配置说明

### 自动检测路径

DevPartner 会自动在以下位置查找模型：

```
优先级顺序：
1. config.yaml 中配置的 llm.model_path
2. 环境变量 MODEL_PATH
3. ./models/Qwen3.5-9B-Q4_1.gguf (默认)
4. ../models/Qwen3.5-9B-Q4_1.gguf (Docker 容器内)
```

### 手动配置路径

编辑 `config.yaml`:

```yaml
llm:
  model_path: "./models/Qwen3.5-9B-Q4_1.gguf"
  # 或使用绝对路径:
  # model_path: "D:/WorkSpace/AI_model/Qwen3.5-9B-Q4_1.gguf"
  
  # 模型参数
  n_ctx: 4096          # 上下文窗口大小
  n_batch: 512         # 批处理大小
  n_gpu_layers: -1     # GPU 加速 (-1=全部加载到GPU)
```

或通过环境变量：

```bash
# Linux/Mac
export MODEL_PATH="./models/Qwen3.5-9B-Q4_1.gguf"

# Windows (PowerShell)
$env:MODEL_PATH=".\models\Qwen3.5-9B-Q4_1.gguf"
```

---

## 🐳 Docker 部署

### 轻量模式（推荐）

镜像不包含模型，通过 volume 挂载：

```yaml
# docker-compose.yml
services:
  devpartner:
    image: devpartner:lite
    volumes:
      - ./models:/app/models  # 挂载本地模型目录
    ports:
      - "7860:7860"
```

### 完整模式

将模型打包进 Docker 镜像（~6.5GB）：

```bash
# 取消 deploy/.dockerignore 中的模型排除规则
# models/*.gguf  ← 注释掉这行

# 构建完整镜像
docker build -t devpartner:full -f deploy/Dockerfile .

# 运行（无需挂载）
docker run -d -p 7860:7860 devpartner:full
```

详细说明见 [../deploy/README.md](../deploy/README.md)

---

## ☁️ ModelScope 云端部署

### 方案 A: Dataset 挂载

1. 在 ModelScope 创建 Dataset
2. 上传模型文件到 Dataset
3. 部署时挂载 Dataset:

```yaml
volumes:
  - your-model-dataset:/app/models
```

### 方案 B: OSS/S3 存储

将模型上传到对象存储服务，启动时自动下载：

```python
# config.yaml
llm:
  model_source: "remote"
  model_url: "https://your-bucket.oss-cn-hangzhou.aliyuncs.com/models/Qwen3.5-9B-Q4_1.gguf"
  auto_download: true
```

详细说明见 [../DEPLOYMENT_GUIDE.md](../DEPLOYMENT_GUIDE.md)

---

## ❓ 常见问题

### Q1: 下载速度慢怎么办？

**A**: 
- 使用 ModelScope 国内镜像（速度快）
- 选择非高峰期下载（凌晨）
- 使用下载工具（如 aria2, IDM）多线程下载

### Q2: 可以用其他模型吗？

**A**: 可以！支持任何 GGUF 格式模型。推荐配置：

| 场景 | 推荐模型 | 大小 |
|------|---------|------|
| 轻量级 | Qwen3.5-1.5B-Q4 | ~1GB |
| 平衡级 | Qwen3.5-9B-Q4 (**当前**) | **~5.7GB** |
| 高性能 | Qwen3.5-32B-Q4 | ~18GB |
| 专业级 | Qwen3.5-72B-Q4 | ~40GB |

### Q3: 磁盘空间不足？

**A**: 
- 使用更小模型（1.5B 或 3B 版本）
- 或使用云端部署（ModelScope/Docker）
- 清理不需要的缓存: `rm -rf ~/.cache/huggingface/`

### Q4: 如何更新模型版本？

**A**:
```bash
# 1. 备份旧模型
mv models/Qwen3.5-9B-Q4_1.gguf models/Qwen3.5-9B-Q4_1.gguf.bak

# 2. 下载新版本
# （重复上面的下载步骤）

# 3. 删除备份（确认新版本正常后）
rm models/Qwen3.5-9B-Q4_1.gguf.bak
```

---

## 📚 相关资源

- **官方文档**: [Qwen3.5 GitHub](https://github.com/QwenLM/Qwen3.5)
- **ModelScope**: [Qwen3.5-9B-Instruct-GGUF](https://modelscope.cn/models/Qwen/Qwen3.5-9B-Instruct-GGUF)
- **HuggingFace**: [Qwen3.5-9B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen3.5-9B-Instruct-GGUF)
- **llama-cpp-python**: [GitHub](https://github.com/abetlen/llama-cpp-python)

---

## 📝 维护记录

| 日期 | 操作 | 说明 |
|------|------|------|
| 2026-07-03 | 创建文档 | v6.0 初始化 |
| 2026-07-03 | 更新配置 | 添加多环境部署说明 |

---

**维护者**: DevPartner Team  
**最后更新**: 2026-07-03  
**适用版本**: DevPartner v6.0+