# finnbot · 财税智能体工作台（后端）

企业微信自建应用 + 自建后端（FastAPI）的最小可运行实现。Phase 1 已上线**财税政策问答**（本地知识库检索 + 大模型作答），并搭好四场景意图路由框架。

## 目录结构
```
finnbot/
├── main.py            # FastAPI 入口：企业微信回调（GET校验 / POST接收 + 异步回复）
├── wecom.py           # 企业微信加解密 + access_token 缓存 + 主动发消息
├── agent.py           # 主智能体：意图路由 + 政策问答 + 大模型调用
├── knowledge_base.py  # 知识库检索（local 模式，jieba 分词）
├── config.py          # 配置中心（全部走环境变量）
├── requirements.txt
├── .env.example       # 环境变量模板（复制为 .env 填值）
├── knowledge/         # 放你的财税政策/制度文档（.txt / .md，支持子目录）
│   ├── 差旅费报销管理办法.md   # 示例：规范化制度文档
│   ├── 发票管理规范.md
│   ├── FAQ-常见财税问题.md
│   └── sample_policy.txt
├── 知识库整理规范.md    # 如何整理真实制度文档（必读）
├── deploy/            # 生产部署：Nginx + HTTPS 反代配置与说明
│   ├── nginx.conf.example   # Nginx 反代 + HTTPS 终止示例
│   ├── gunicorn.conf.py     # 后端生产启动配置（uvicorn worker）
│   ├── finnbot.service      # systemd 守护单元文件
│   └── README.md            # 证书申请 / 部署 / 运维全步骤
├── selftest.py        # 本地自测：加解密 + 知识库（不依赖企业微信/LLM）
└── smoke_test.py      # 端到端验收：模拟四类消息跑通主智能体链路（无需企业微信）
```

## 一、安装与配置
```bash
cd finnbot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # 然后编辑 .env 填入真实值
```

## 二、准备知识库
先读 `知识库整理规范.md`，按规范把贵司真实的财税政策、内部制度、常见问答整理成 `.md` 放进 `knowledge/`（支持子目录）。示例见 `knowledge/` 下三个范例文件（均为示例，请替换）。**注意规范中的敏感信息红线：个人薪酬、客户金额、银行账号、密钥等严禁入库。**

## 三、本地自测与端到端验收（不依赖企业微信）
```bash
# 1) 单元自测：加解密 + 知识库检索
python selftest.py

# 2) 端到端验收：模拟四类财税消息经主智能体路由（发票/记账/申报/知识库 + 加解密）
#    政策问答需配置 LLM_API_KEY，未配置时自动跳过并提示
python smoke_test.py
```
`smoke_test.py` 用于在**没有企业微信、没有 LLM 账号**时也能把四个业务场景的代码链路跑通，便于交付前验收与 CI。四类消息的返回关键词都会被断言，任一链路异常即报错退出。

## 四、企业微信后台配置（关键）
1. 管理后台 → 我的企业 → 企业信息 → 复制 **CorpID**。
2. 应用管理 → 自建 → 创建应用 → 复制 **AgentId / Secret**。
3. 应用详情 → 接收消息 → 设置 API 接收：
   - URL：`https://你的域名/wecom/callback`（必须 HTTPS + 已备案域名）
   - Token / EncodingAESKey：自定义 / 随机生成，与 `.env` 一致。
4. 应用详情 → 开发者接口 → 可信 IP：填你服务器公网出口 IP。
5. 权限管理：勾选消息相关权限（通讯录只读可选）。

## 五、部署运行
```bash
# 开发
uvicorn main:app --host 0.0.0.0 --port 8000

# 生产（推荐 Nginx 反代 + HTTPS，企业微信强制 HTTPS）
# 使用内置 gunicorn 配置：
gunicorn -c deploy/gunicorn.conf.py main:app
```
生产部署与 HTTPS 证书申请、系统守护（systemd 单元 `deploy/finnbot.service`）、运维，详见 `deploy/README.md`（含 `deploy/nginx.conf.example`）。Nginx 负责 HTTPS 终止，并把 `/wecom/callback` 反代到后端 8000。保存应用配置时企业微信会发 GET 校验，通过后即生效。

## 六、验证对话
在企业微信里给你的应用发消息，例如"小微企业增值税有什么优惠？"，应收到带出处的政策答复。

## 七、扩展路线（在 agent.py 接入口）
- 发票票据：✅ 已在 `invoice.py` 实现（四要素解析 + 本地风险校验/重复报销检测 + 第三方聚合查验**参考实现** `verify_invoice_aggregator`，含 3 处按服务商文档微调的标注），并在 `agent.py` 接入。配置 `INVOICE_PROVIDER` 等即可启用查验。
- 记账核算：✅ 已在 `bookkeeping.py` 实现（流水解析 + 科目分类 + 凭证建议，不自动过账），并在 `agent.py` 接入。接入财务软件 API 后可直接读流水。
- 税务申报：✅ 已在 `tax.py` 实现（简易税额测算 + 申报草稿，强制人工确认），并在 `agent.py` 接入。直连电子税务局门槛高，由人工提交。

## 安全红线
- 所有密钥走 `.env`，绝不入库、不写日志。
- 身份证/银行卡/税号在输出中掩码。
- 申报、对外发函、删除、过账一律人工确认，Agent 不自动执行。

> 平台按钮位置以企业微信当前实际界面为准（已标注"需核实"）。
