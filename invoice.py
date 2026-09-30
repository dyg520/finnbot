"""
finnbot · 发票票据处理（Phase 2）
- 发票结构化：从自然语言/文本中解析发票四要素（代码/号码/日期/金额/校验码）。
- 发票查验：封装第三方发票查验 API（可配置服务商，当前为通用模板，按文档替换实现）。
- 报销风险校验：纯本地规则 —— 重复报销检测（基于代码+号码去重，存本地 SQLite）、字段完整性。
- OCR 入口：占位，配置 OCR 服务商后可由图片/PDF 直接结构化。

安全：发票号码等敏感信息输出前做掩码；重复报销记录仅存本地，不外发。
"""
import os
import re
import hashlib
import sqlite3
import time
import httpx
from datetime import datetime

from config import (
    INVOICE_PROVIDER, INVOICE_API_BASE, INVOICE_API_KEY,
    INVOICE_APP_ID, INVOICE_APP_SECRET, INVOICE_OCR_PROVIDER,
)

DB_PATH = os.getenv("INVOICE_DB_PATH", "data/invoice_records.db")


# ---------- 发票四要素解析 ----------
def parse_invoice_fields(text: str) -> dict:
    """从文本中提取发票四要素（校验码可选）。支持两种输入格式：
      格式一：查验 011002300311 12345678 2024-05-12 560.00 123456
      格式二：发票代码011002300311 发票号码12345678 开票日期2024-05-12 价税合计560 校验码123456
    策略：先按键值提取；关键字段缺失时，按数字特征（10/12位=代码、8位=号码、
    日期、6位=校验码、带小数=金额）做位置解析回退。
    返回字段：invoice_code/invoice_no/invoice_date/amount/check_code（缺项为 None）。
    """
    fields = {
        "invoice_code": None,   # 发票代码（10/12 位）
        "invoice_no": None,     # 发票号码（8 位）
        "invoice_date": None,   # 开票日期 YYYY-MM-DD
        "amount": None,         # 价税合计（优先）；不含税金额次之
        "check_code": None,     # 校验码后 6 位
    }
    # 1) 键值提取
    kv = [
        ("invoice_code", r"(?:发票代码|代码)[\s:：]*(\d{10,12})"),
        ("invoice_no", r"(?:发票号码|号码|票号)[\s:：]*(\d{8})"),
        ("invoice_date", r"(?:开票日期|日期)[\s:：]*(\d{4}[-/]\d{1,2}[-/]\d{1,2})"),
        ("amount", r"(?:价税合计|金额|合计)[\s:：]*(\d+(?:\.\d{1,2})?)"),
        ("check_code", r"(?:校验码|校验)[\s:：]*(\d{6})"),
    ]
    for key, pat in kv:
        m = re.search(pat, text)
        if m:
            fields[key] = m.group(1).replace("/", "-") if key == "invoice_date" else m.group(1)

    # 2) 关键字段缺失 → 位置解析回退
    if not (fields["invoice_code"] and fields["invoice_no"] and fields["invoice_date"]):
        if not fields["invoice_date"]:
            m = re.search(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})", text)
            if m:
                fields["invoice_date"] = m.group(1).replace("/", "-")
        # 去掉日期，避免数字干扰代码/号码/金额识别
        cleaned = re.sub(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", " ", text)
        if not fields["invoice_code"]:
            m = re.search(r"\b(\d{12})\b|\b(\d{10})\b", cleaned)
            if m:
                fields["invoice_code"] = m.group(1) or m.group(2)
        if not fields["invoice_no"]:
            m = re.search(r"\b(\d{8})\b", cleaned)
            if m:
                fields["invoice_no"] = m.group(1)
        if not fields["check_code"]:
            m = re.search(r"\b(\d{6})\b", cleaned)
            if m:
                fields["check_code"] = m.group(1)
        if not fields["amount"]:
            nums = re.findall(r"\b(\d+(?:\.\d{1,2})?)\b", cleaned)
            # 排除代码/号码/校验码长度的整数串，取数值最大者作为金额
            cands = [n for n in nums if not (n.isdigit() and len(n) in (6, 8, 10, 12))]
            if cands:
                fields["amount"] = max(cands, key=lambda x: float(x))
    return fields


def _mask(s: str) -> str:
    if not s:
        return "—"
    if len(s) <= 4:
        return "***"
    return s[:2] + "***" + s[-2:]


# ---------- 第三方发票查验（聚合平台参考实现） ----------
async def verify_invoice_aggregator(fields: dict) -> dict:
    """聚合类发票查验平台参考实现（以 票易通 / 慧穗 / 票查查 等常见形态为例）。

    接入你的服务商只需按注释对齐 3 处：① 签名拼接种子 ② 请求路径 ③ 返回字段映射。
    其余（HTTPS POST JSON、超时、错误捕获、结果标准化）已通用化。

    返回统一结构：
    {
      "ok": bool,                          # 查验请求是否成功返回
      "status": "真票"/"假票"/"异常"/"未知",
      "result": {发票代码/号码/日期/金额/销方/购方/税率/查验状态},  # 标准化
      "consistency": {金额是否一致, notes}, # 输入与平台返回的一致性核对（防篡改/输错）
      "raw": {...}                         # 平台原始返回，便于排查
    }
    """
    timestamp = str(int(time.time() * 1000))
    nonce = hashlib.md5(f"{timestamp}{INVOICE_APP_SECRET}".encode()).hexdigest()[:16]

    # ① 签名：常见 MD5(appKey + timestamp + nonce + appSecret).upper()
    #    不同服务商可能去掉 nonce 或调整顺序 —— 按你的文档替换这一行
    sign_seed = f"{INVOICE_APP_ID}{timestamp}{nonce}{INVOICE_APP_SECRET}"
    sign = hashlib.md5(sign_seed.encode("utf-8")).hexdigest().upper()

    # ② 请求路径：聚合平台多为 /{provider}/invoice/verify —— 按文档替换
    url = f"{INVOICE_API_BASE.rstrip('/')}/{INVOICE_PROVIDER}/invoice/verify"

    payload = {
        "appKey": INVOICE_APP_ID,
        "timestamp": timestamp,
        "nonce": nonce,
        "sign": sign,
        "invoiceCode": fields.get("invoice_code"),     # 发票代码（10/12 位）
        "invoiceNo": fields.get("invoice_no"),         # 发票号码（8 位）
        "invoiceDate": fields.get("invoice_date"),     # 开票日期 YYYY-MM-DD
        "amount": fields.get("amount"),                # 价税合计
        "checkCode": fields.get("check_code"),         # 校验码后 6 位（专票必填）
        # "invoiceType": "01",  # 如需发票类型（01 专票 / 04 普票）按文档补充
    }
    headers = {"Content-Type": "application/json",
               "Authorization": f"Bearer {INVOICE_API_KEY}"}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return {"ok": False, "status": "异常", "result": {}, "consistency": {},
                "raw": {}, "error": f"查验请求失败：{e}"}

    # ③ 返回字段兼容：{"success":true,"data":{...}} 或 {"code":0,"result":{...}}
    ok = bool(data.get("success", data.get("code") in (0, "0", "200")))
    raw_result = data.get("data") or data.get("result") or {}
    standardized = _map_aggregator_result(raw_result)
    consistency = _check_consistency(fields, standardized)
    status = ("真票" if (ok and consistency.get("amount_match")) else
              ("假票" if ok else "未知"))
    return {"ok": ok, "status": status, "result": standardized,
            "consistency": consistency, "raw": data}


def _map_aggregator_result(r: dict) -> dict:
    """把不同服务商返回的不同字段命名，映射为统一结构。
    各服务商字段命名略有差异，按你的文档在此补充别名即可（如 fpdm/fphm 等税控常用字段）。
    """
    def pick(*keys):
        for k in keys:
            v = r.get(k)
            if v not in (None, ""):
                return v
        return None
    return {
        "invoice_code": pick("invoiceCode", "fpdm", "invoice_code"),
        "invoice_no": pick("invoiceNo", "fphm", "invoice_no"),
        "invoice_date": pick("invoiceDate", "kprq", "invoice_date"),
        "amount": pick("amount", "jshj", "totalAmount"),
        "seller_name": pick("sellerName", "xfmc", "seller_name"),
        "buyer_name": pick("buyerName", "gfmc", "buyer_name"),
        "tax_rate": pick("taxRate", "sl", "tax_rate"),
        "verify_state": pick("state", "yzzt", "verify_state", "status"),
    }


def _check_consistency(input_fields: dict, std: dict) -> dict:
    """核对输入金额与查验平台返回金额是否一致（防篡改 / 输错）。"""
    out = {"amount_match": None, "notes": []}
    a_in = input_fields.get("amount")
    a_out = std.get("amount")
    if a_in is not None and a_out is not None:
        try:
            match = abs(float(a_in) - float(a_out)) < 0.005
            out["amount_match"] = match
            if not match:
                out["notes"].append(f"金额不一致：输入 {a_in}，查验返回 {a_out}")
        except (ValueError, TypeError):
            out["notes"].append("金额格式异常，无法比对")
    else:
        out["notes"].append("缺少金额，跳过一致性核对")
    return out


async def verify_invoice(fields: dict) -> dict:
    """发票查验统一入口：按 INVOICE_PROVIDER 路由到对应实现。
    未配置服务商时返回引导提示（此时仍可做本地风险校验）。
    """
    if not INVOICE_PROVIDER or INVOICE_PROVIDER == "none":
        return {"ok": False,
                "error": "未配置发票查验服务商（INVOICE_PROVIDER）。请在 .env 配置后启用；"
                         "当前仅提供本地风险校验。聚合平台参考实现见 verify_invoice_aggregator（按文档微调 3 处即可）。"}
    # 当前统一走聚合参考实现；若以后接入航信/百望等专属接口，可在此按 provider 分支
    return await verify_invoice_aggregator(fields)


# ---------- 报销风险校验（本地纯规则） ----------
def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS invoice_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_code TEXT,
        invoice_no TEXT,
        invoice_date TEXT,
        amount REAL,
        payer TEXT,
        created_at TEXT,
        UNIQUE(invoice_code, invoice_no)
    )""")
    conn.commit()
    return conn


def check_reimbursement_risk(fields: dict, payer: str = "") -> dict:
    """纯规则报销风险校验：
    1) 重复报销：同 代码+号码 已存在 → 高风险拦截
    2) 字段完整性：缺少必填项 → 中风险提示
    返回 {"level":"高/中/低","reasons":[...]}。
    """
    reasons = []
    level = "低"
    if fields.get("invoice_code") and fields.get("invoice_no"):
        try:
            conn = init_db()
            cur = conn.execute(
                "SELECT payer, created_at FROM invoice_records "
                "WHERE invoice_code=? AND invoice_no=?",
                (fields["invoice_code"], fields["invoice_no"]),
            )
            row = cur.fetchone()
            conn.close()
            if row:
                level = "高"
                reasons.append(
                    f"⚠️ 重复报销风险：该发票（代码 {_mask(fields['invoice_code'])} "
                    f"号码 {_mask(fields['invoice_no'])}）已于 {row[1]} 由 {row[0] or '他人'} 提交过报销。"
                )
        except Exception as e:
            reasons.append(f"（重复检测异常：{e}）")
    missing = [k for k in ("invoice_code", "invoice_no", "invoice_date", "amount")
               if not fields.get(k)]
    if missing:
        if level != "高":
            level = "中"
        reasons.append(f"发票信息不完整，缺少：{', '.join(missing)}（查验前需补全）。")
    if not reasons:
        reasons.append("初步校验通过：暂未发现明显风险，建议完成发票查验后归档。")
    return {"level": level, "reasons": reasons}


def record_invoice(fields: dict, payer: str = "") -> bool:
    """人工确认报销后登记，用于后续重复检测。绝不自动调用，须财务确认后执行。"""
    try:
        conn = init_db()
        conn.execute(
            "INSERT OR IGNORE INTO invoice_records "
            "(invoice_code, invoice_no, invoice_date, amount, payer, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (fields.get("invoice_code"), fields.get("invoice_no"), fields.get("invoice_date"),
             float(fields["amount"]) if fields.get("amount") else None,
             payer, datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[invoice] 登记失败: {e}")
        return False


# ---------- OCR 入口（占位） ----------
async def ocr_invoice(image_path_or_url: str) -> dict:
    """发票 OCR 结构化（占位）。需配置 OCR 服务商（如腾讯云/百度 OCR）。
    接入后把返回映射为 parse_invoice_fields 的字段结构即可。"""
    if not INVOICE_OCR_PROVIDER or INVOICE_OCR_PROVIDER == "none":
        return {"ok": False,
                "error": "未配置 OCR 服务商（INVOICE_OCR_PROVIDER）。可先手动输入发票四要素，"
                         "或接入 OCR 后由图片直接结构化。"}
    # TODO: 按服务商文档实现，调用后映射到 parse_invoice_fields 字段结构
    return {"ok": False, "error": "OCR 接入模板待实现，请按服务商文档补充。"}
