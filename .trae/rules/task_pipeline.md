# Trae 任务管道规范 v5.0

## 📋 概述
本规则定义了 **Trae IDE** 客户端与 DevPartner 系统交互时的**任务执行流程**和**数据落地规范**。

### Trae 特性适配
- 🔍 **上下文感知**: 自动读取当前打开的文件作为对话输入
- ⚡ **实时反馈**: 利用 Trae 的 Inline Suggestion 展示进度
- 📝 **多文件编辑**: 批量修改时使用 Trae 的 Apply Edit 功能
- 🎯 **智能补全**: 基于知识库提供代码片段建议

### 核心原则（与 CodeBuddy 一致）
- ✅ **唯一标识**: 每个 `conversation_id` 必须全局唯一
- ✅ **步骤化拆分**: 复杂任务必须拆分为可追踪的步骤
- ✅ **异步优先**: LLM 推理等耗时操作异步执行
- ✅ **有序落地**: 知识点按步骤顺序写入
- ✅ **资源友好**: 控制内存，避免阻塞 UI 线程

---

## 🎨 Trae 专属工作流

### 场景1: 代码重构（Refactoring）
```typescript
// Trae 用户触发重构时的标准流程

// Step 1: 创建会话（自动捕获当前文件上下文）
const convId = await devpartner.createConversation({
  client: "trae",
  topic: "重构 UserService 类",  // 从当前选中的代码推断
  taskType: "refactoring",
  priority: "medium",
  context: {
    activeFile: vscode.window.activeTextEditor?.document.fileName,
    selection: vscode.window.activeTextEditor?.selection,
    workspaceFiles: await getWorkspaceFiles(), // Trae 可获取工作区文件列表
  }
});

// Step 2: 定义分析步骤（利用 Trae 的 AST 解析能力）
const steps = [
  {
    stepType: "analysis",
    stepName: "分析代码结构和依赖关系",
    order: 1,
    inputData: {
      content: currentFileContent,
      language: "TypeScript",
      useAST: true,  // 启用 AST 分析（Trae 内置能力）
    }
  },
  {
    stepType: "knowledge_gen",
    stepName: "提取设计模式和改进点",
    order: 2,
    dependsOn: ["step_001"]
  },
  {
    stepType: "data_migration",  // 对应实际的代码修改
    stepName: "应用重构建议到代码",
    order: 3,
    inputData: {
      applyMode: "preview",  // 先预览，用户确认后再应用
      targetFiles: ["src/services/UserService.ts"],
    }
  }
];

const stepIds = await devpartner.createSteps(convId, steps);

// Step 3: 异步执行（不阻塞 Trae UI）
const taskId = await devpartner.executeStepsAsync(convId, {
  priority: "high",
  onProgress: (progress) => {
    // 在 Trae 状态栏显示进度
    vscode.window.setStatusBarMessage(`DevPartner: ${progress.percentage}%`);
  },
  onComplete: (result) => {
    // 使用 Trae 的 Notification 提示完成
    vscode.window.showInformationMessage(
      `✅ 重构完成！生成 ${result.knowledgePointsCreated} 个知识点`
    );
    
    // 如果有代码修改建议，展示为 Diff View
    if (result.codeChanges?.length > 0) {
      showDiffView(result.codeChanges);
    }
  }
});
```

---

## 🔄 异步处理协议（Trae 版）

### Trae UI 友好的状态展示

由于 Trae 是图形界面 IDE，用户体验比命令行更重要。以下是推荐的实现方式：

#### 方案A: 进度条 + 状态栏（推荐）
```typescript
interface TaskProgress {
  taskId: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  percentage: number;        // 0-100
  currentStep: string;       // 当前执行的步骤名
  estimatedRemaining: number; // 预估剩余秒数
}

// 在 Trae 状态栏显示
function updateStatusBar(progress: TaskProgress) {
  const icon = progress.status === 'running' ? '🔄' : 
                progress.status === 'completed' ? '✅' : '⏳';
  const text = `${icon} DevPartner: ${progress.currentStep} (${progress.percentage}%)`;
  statusBar.text = text;
  statusBar.show();
}

// 轮询间隔建议：2秒（比 CLI 的3秒更频繁，因为 GUI 可以承受）
setInterval(async () => {
  const status = await devpartner.getTaskStatus(taskId);
  updateStatusBar(status);
}, 2000);
```

#### 方案B: Output Channel 日志（适合调试）
```typescript
const outputChannel = vscode.window.createOutputChannel('DevPartner');

outputChannel.appendLine(`[${timestamp}] 🚀 任务提交: ${taskId}`);
outputChannel.appendLine(`[${timestamp}] 📊 类型: ${taskType}`);
outputChannel.appendLine(`[${timestamp}] 💾 内存预估: ${estimatedMemory}MB`);
// ...
```

---

## 💡 Trae 智能集成点

### 1️⃣ 上下文自动注入
Trae 应在提交任务前自动收集以下信息：

```typescript
async function gatherContext(): Promise<ExecutionContext> {
  return {
    // 当前活跃文件
    activeFile: getActiveFilePath(),
    
    // 选中的代码段
    selectedCode: getSelectedText(),
    
    // 工作区结构（用于分析依赖关系）
    workspaceStructure: await scanWorkspace(),
    
    // Git 状态（最近的 commit、分支）
    gitInfo: {
      branch: await execGit('branch --show-current'),
      lastCommit: await execGit('log -1 --pretty=%H'),
      changedFiles: await execGit('diff --name-only HEAD~1'),
    },
    
    // 已安装的依赖（package.json / requirements.txt）
    dependencies: parseDependencies(),
    
    // TypeScript/Python 配置（tsconfig.json / pyproject.toml）
    projectConfig: readProjectConfig(),
  };
}
```

### 2️⃣ 知识库驱动的代码补全
当用户在 Trae 中编写代码时，可以查询 DevPartner 知识库获取相关知识点：

```typescript
// 监听输入事件
vscode.window.onDidChangeTextDocument(async (event) => {
  const line = event.document.getText(getCurrentLineRange());
  
  // 查询相关知识点的简单示例
  const knowledge = await devpartner.searchKnowledge({
    query: line,
    domain: detectLanguage(event.document),
    limit: 5,
  });
  
  if (knowledge.length > 0 && shouldShowSuggestion(line)) {
    // 显示为 Inline Suggestion（Trae 核心功能）
    showInlineSuggestion(formatKnowledgeAsSnippet(knowledge));
  }
});
```

### 3️⃣ 多文件批量操作
Trae 的 `Apply Edit` API 支持原子性多文件修改，非常适合数据库迁移场景：

```typescript
// 示例：执行 v5.0 Schema 升级后的代码调整
async function applySchemaUpgrade(changes: CodeChange[]) {
  const edit = new vscode.WorkspaceEdit();
  
  for (const change of changes) {
    const uri = vscode.Uri.file(change.filePath);
    const range = new vscode.Range(
      change.startLine, 0,
      change.endLine, 0
    );
    edit.replace(uri, range, change.newContent);
  }
  
  // 原子性应用所有修改（要么全成功，要么全回滚）
  const success = await vscode.workspace.applyEdit(edit);
  
  if (!success) {
    vscode.window.showErrorMessage("❌ 应用修改失败，请检查文件是否被占用");
    await devpartner.failConversation(convId, "Apply edit failed");
  } else {
    vscode.window.showInformationMessage("✅ Schema 升级成功应用");
  }
}
```

---

## ⚠️ 性能优化建议（Trae 专用）

### 内存管理策略
Trae 本身已经占用较多内存（~500MB-1GB），因此 DevPartner 必须更加保守：

| 组件 | 推荐配置 | 说明 |
|------|---------|------|
| 并发任务数 | **1**（默认） | Trae UI 响应优先 |
| 单任务内存上限 | **800MB** | 为 Trae 预留空间 |
| LLM 推理超时 | **120秒** | 缩短等待时间 |
| 轮询间隔 | **2秒** | 更快的 UI 反馈 |

### 后台任务可视化
在 Trae 的 Activity Bar 中添加 DevPartner 图标：
```json
{
  "contributes": {
    "viewsContainers": {
      "activitybar": [
        {"id": "devpartner-activitybar", "title": "DevPartner", "icon": "resources/icon.svg"}
      ]
    },
    "views": {
      "devpartner-activitybar": [
        {
          "type": "tree",
          "id": "devpartnerTasks",
          "title": "任务队列",
          "icon": "resources/task-icon.svg"
        },
        {
          "type": "webview",
          "id": "devpartnerKnowledge",
          "title": "知识库"
        }
      ]
    }
  }
}
```

---

## 🐛 故障排查（Trae 版）

### Q1: Trae 卡死或响应缓慢？
**诊断步骤**:
1. 打开 Developer Tools (`Help > Toggle Developer Tools`)
2. 切换到 Console 标签页，查看是否有 `DevPartner` 相关错误
3. 检查 Memory 标签页，如果内存 >2GB，重启 Trae
4. 运行 `/devpartner health` 命令检查服务状态

**快速恢复**:
```bash
# 1. 重启 DevPartner 服务
/devpartner restart

# 2. 清空卡住的任务队列
/devpartner cancel-all-tasks

# 3. （可选）重置数据库索引
/devpartner reindex-knowledge-base
```

### Q2: 知识点没有出现在代码补全中？
**可能原因**:
- 知识点尚未通过 `knowledge_gen` 步骤生成
- 查询的关键词与知识点标题不匹配
- 知识点置信度过低（<0.6）

**解决方法**:
1. 手动触发知识点提取:
   ```bash
   /devpartner extract-knowledge <conversation_id>
   ```
2. 调整查询参数:
   ```typescript
   const results = await searchKnowledge({
     query: userInput,
     minConfidence: 0.5,  // 降低阈值
     fuzzyMatch: true,     // 启用模糊匹配
   });
   ```

---

## 📊 监控指标（Trae Dashboard）

推荐在 Trae 的 Webview 中展示以下仪表盘数据：

### 实时指标卡片
```
┌─────────────────────────────────────┐
│  🔄 DevPartner 系统状态              │
├──────────┬──────────┬────────────────┤
│ 活跃会话 │ 运行任务 │ 内存使用率     │
│    3     │    1     │   45% ████████░│
├──────────┼──────────┼────────────────┤
│ 今日分析 │ 知识沉淀 │ 成功率         │
│   12次   │   8个    │  96%           │
└──────────┴──────────┴────────────────┘
```

### 历史趋势图
- 📈 过去7天完成的会话数趋势
- 📊 各领域（Python/前端/AI）的知识点分布
- ⚡ 平均任务执行时间变化

---

## 🎯 快速开始模板

将以下内容复制到 Trae 的 User Snippets 中（`Preferences > Configure User Snippets`）：

```json
{
  "DevPartner Create Conversation": {
    "prefix": "dp-conv",
    "body": [
      "const convId = await devpartner.createConversation({",
      "  client: 'trae',",
      "  topic: '$1',",
      "  taskType: '$2',",
      "  priority: 'medium',",
      "});",
      "console.log('Conversation ID:', convId);"
    ],
    "description": "Create a DevPartner conversation with async support"
  },
  "DevPartner Async Execute": {
    "prefix": "dp-exec",
    "body": [
      "const taskId = await devpartner.executeStepsAsync(convId, {",
      "  priority: '${1|high,medium,low|}',",
      "});",
      "// Monitor progress...",
      "setInterval(async () => {",
      "  const status = await devpartner.getTaskStatus(taskId);",
      "  updateUI(status);",
      "}, 2000);"
    ],
    "description": "Execute conversation steps asynchronously"
  }
}
```

---

**最后更新**: 2026-07-02  
**适用版本**: DevPartner v5.0+ / Trae IDE v1.x+  
**维护者**: DevPartner Team + Trae Community