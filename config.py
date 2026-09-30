"""
finnbot · 配置中心
所有密钥/敏感项一律走环境变量（.env），绝不硬编码进代码或日志。
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ---------- 企业微信 ----------
WECOM_CORP_ID = os.getenv("WECOM_CORP_ID", "")          # 我的企业 → 企业信息 → CorpID
WECOM_AGENT_ID = os.getenv("WECOM_AGENT_ID", "")        # 自建应用详情 → AgentId
WECOM_CORP_SECRET = os.getenv("WECOM_CORP_SECRET", "")  # 自建应用详情 → Secret（仅显示一次）
WECOM_CALLBACK_TOKEN = os.getenv("WECOM_CALLBACK_TOKEN", "")    # 接收消息 → Token（自建）
WECOM_ENCODING_AES = os.getenv("WECOM_ENCODING_AES", "")       # 接收消息 → EncodingAESKey

# ---------- 大模型（OpenAI 兼容接口，国产合规模型优先）----------
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.hunyuan.cloud.tencent.com/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "hunyuan-pro")

# ---------- 知识库 ----------
KNOWLEDGE_DIR = os.getenv("KNOWLEDGE_DIR", "knowledge")
# local: 本地轻量检索（零额外服务）；rag: 接入外部向量库（填下面两项）
KNOWLEDGE_MODE = os.getenv("KNOWLEDGE_MODE", "local")
RAG_API_URL = os.getenv("RAG_API_URL", "")
RAG_API_KEY = os.getenv("RAG_API_KEY", "")

# ---------- 发票查验 / OCR（Phase 2，按需配置）----------
# 第三方发票查验服务商标识（如 piaoyitong / huihui / piaochacha / baiwang / aisin）。
# 留空则仅做本地风险校验 + 引导，不调用外部查验。
INVOICE_PROVIDER = os.getenv("INVOICE_PROVIDER", "")
INVOICE_API_BASE = os.getenv("INVOICE_API_BASE", "")        # 服务商 API 基础地址，如 https://open.xxx.com
INVOICE_API_KEY = os.getenv("INVOICE_API_KEY", "")
INVOICE_APP_ID = os.getenv("INVOICE_APP_ID", "")            # 服务商分配的 appKey / appId
INVOICE_APP_SECRET = os.getenv("INVOICE_APP_SECRET", "")    # 服务商分配的 appSecret
# OCR 服务商（图片/PDF 直接结构化）：留空则手动输入四要素
INVOICE_OCR_PROVIDER = os.getenv("INVOICE_OCR_PROVIDER", "")

# ---------- 服务 ----------
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/wecom/callback")
