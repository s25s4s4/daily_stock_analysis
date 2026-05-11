# 小白手把手部署视频教程（适配第一次部署）

> 建议时长：12–18 分钟  
> 目标：`新手 0 背景` 也能在 1 台 Linux 云服务器上跑通本项目

本文档用于“照着录一套可直接发视频的讲解脚本 + 实操清单”。  
默认路线：**本地测试 → 云服务器 Docker Compose 正式上线**。  
可选路线：最后给出直接运行方式，便于本地或开发机快速验证。

---

## 适用范围（先说清楚）

1. 你有一台 Ubuntu/CentOS 服务器（推荐 Ubuntu 20.04/22.04）  
2. 你有项目运行所需的 Key（至少一项 AI Key）  
3. 你希望先“看视频一条龙学会”，后续自己能自行复测  

## 录制脚本（按时间轴）

### 0:00 - 0:30 开场（先交代目标）

**画面**：打开本项目主页截图 + 本文档标题。  
**口播**：
“今天我们用新手友好方式把 `daily_stock_analysis` 从 0 到可运行做一遍：先把环境准备好，复制 `.env`，启动服务，最后验证 Web 界面和一次手工分析。即使你没接触过 Python 或 Docker 也能照着做。”

### 0:30 - 2:00 讲清准备工作

**画面**：终端，展示服务器信息和软件版本。

1. 说明将用的部署方式（Docker Compose 推荐）  
2. 说明最少权限：有 SSH 登录、可执行 `sudo`  

建议在讲解时同步贴出这张命令清单：

```bash
uname -a
python3 --version || true
git --version
docker --version || true
docker-compose --version || true
```

### 2:00 - 4:30 安装前置环境（首次）

**口播**：
“没有 Docker 就先安装，不用一次次折腾。”

#### Ubuntu/Debian

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"
newgrp docker
```

#### CentOS

```bash
sudo yum install -y docker docker-compose
sudo systemctl start docker
sudo systemctl enable docker
```

**小提示**：这一步若提示 `docker-compose` 命令不存在，先确认系统有 `docker-compose`；若只有 `docker compose`，则统一改成后续命令即可（本教程先按 `docker-compose` 命令执行）。

### 4:30 - 6:30 获取代码并准备配置文件

**画面**：`ls`、`git clone`、目录切换

```bash
cd /opt
git clone <your-repo-url> stock-analyzer
cd stock-analyzer
cp .env.example .env
```

然后重点讲 `.env` 的“最小可运行配置”：

1. `STOCK_LIST`（必须）  
2. 至少一个模型 Key：`ANSPIRE_API_KEYS` 或 `AIHUBMIX_KEY` 或 `OPENAI_API_KEY` 或 `GEMINI_API_KEY`  
3. 通知渠道至少一个：如 `WECHAT_WEBHOOK_URL` 或 `EMAIL_SENDER` + `EMAIL_PASSWORD`  
4. 搜索增强至少一个：`ANSPIRE_API_KEYS` 或 `SERPAPI_API_KEYS`（推荐）

命令示例（按需修改）：

```bash
vim .env
```

**口播**：
“先别怕，少填也能先把框架跑通；后续再回来补齐高级参数。”

### 6:30 - 9:00 一键启动（Docker 推荐）

```bash
docker-compose -f ./docker/docker-compose.yml up -d
```

启动后给 3 秒等待，再看三条验证命令：

```bash
docker-compose -f ./docker/docker-compose.yml ps
docker-compose -f ./docker/docker-compose.yml logs -f --tail=80
docker-compose -f ./docker/docker-compose.yml exec -u dsa analyzer python main.py --help
```

#### 预期结果
- 容器状态 `Up`  
- 日志出现服务初始化信息（无立即报错退出）  
- `--help` 能输出命令列表  

### 9:00 - 10:30 验证 Web 访问

**画面**：浏览器输入 `http://服务器IP:8000`  

```bash
sudo ufw allow 8000/tcp   # 若你在用 UFW
```

**说明**：有些场景是云厂商安全组也要放行 8000 端口。  
提示：可先从“本地测试”到“外网访问”过度，避免一上来就盲目排查网络。

### 10:30 - 12:00 手工触发一次分析任务（最关键）

**方式 A：容器内执行一次**

```bash
docker-compose -f ./docker/docker-compose.yml exec -u dsa analyzer python main.py --no-notify
```

**方式 B：用 Web 界面**  
打开 WebUI，点击分析按钮并观察状态变化与报告页。

**验收点**：
- 任务能从“进行中”变为“完成”  
- 关键指标输出有返回（不是卡死或 500）  
- 成功时可见报告结果 / 日志中无致命异常  

### 12:00 - 13:30 加入定时任务（可选）

**口播**：
“如果你只是想先跑一遍，先别急着加定时；先确认单次能跑，再加 schedule。”

建议配置：
- `SCHEDULE_ENABLED=true`（或运行时使用 `--schedule`）  
- `SCHEDULE_TIME=18:00`（默认可直接沿用）  
- 时区使用 `Asia/Shanghai`  

### 13:30 - 15:00 追加：本地/开发机直接部署（备选）

**当你不想用 Docker，或者只想临时验证时可用。**

```bash
python3.10 -m venv venv
source venv/bin/activate
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
cp .env.example .env
vim .env
python main.py
```

### 15:00 - 17:00 常见错误快速排查（视频结尾金句）

#### 症状 1：页面可以打开但资源乱掉

```bash
tail -n 120 /opt/stock-analyzer/logs/stock_analysis_*.log
```
说明 `static/assets` 资源是否 404；若有，按 `DEPLOY.md` 中“资源重建”步骤重做镜像。

#### 症状 2：容器一直重启 / 退出 1

```bash
docker-compose -f ./docker/docker-compose.yml logs -f --tail=120
```
重点看 `.env` 是否缺项、AI Key 是否错误、数据库路径是否可写。

#### 症状 3：端口访问失败

```bash
docker-compose -f ./docker/docker-compose.yml exec server ss -lntp | grep ${API_PORT:-8000}
sudo ufw status
```
常见是 8000 没放行或进程未监听。

#### 症状 4：命令返回 `Permission denied`

- 检查容器执行用户与挂载目录权限  
- 该项目文档默认 `data/logs/reports` 由入口处理权限修正；若仍异常，可先检查挂载点属主。

### 17:00 - 18:00 一句话收口

**口播**：
“你现在已经能完成从 `克隆项目`、`配置 .env`、`Docker 一键启动`、`手动跑一次分析` 的完整流程。后续只要保持 `.env` 秘钥和 `STOCK_LIST` 有效，日常就是看日志和任务结果。下一篇可以做‘通知渠道细节配置’专项。”

---

## 适合放到录屏里的台词清单（可直接复制）

- “先把环境装好，再装业务；先有结果，再追求漂亮。”  
- “这个项目支持 Docker 和直接运行，先用 Docker 是为了快、稳、少踩坑。”  
- “今天只追求‘一次能跑’，不是‘一次配置完美’。”  
- “遇到问题别看日志都不懂先按 checklist：进程、端口、配置、权限、日志。”  

## 录制素材建议（可选）

- `terminal` 全程同屏（建议字体放大）  
- 命令输入前后用 `sleep` 暂停 2-3 秒，方便新手跟读  
- 出错演示建议加一个“故意错配端口”片段再回到正确流程，记忆度更高  

---

## 交付核对清单

- [ ] 服务器可 SSH  
- [ ] Docker / docker-compose 可用  
- [ ] `.env` 至少填了 `STOCK_LIST` + 一个模型 Key  
- [ ] `docker-compose up -d` 后服务状态为 `Up`  
- [ ] 可访问 `http://IP:8000`  
- [ ] `python main.py --no-notify` 在容器内能单次执行通过  
- [ ] 至少出现一次成功报告/日志完成记录  

