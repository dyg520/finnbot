"""
finnbot · 主智能体
意图路由（政策问答 / 发票票据 / 记账核算 / 税务申报 / 其他）+ 各场景实现。
- 政策问答（Phase 1）：本地知识库检索 + 大模型作答
- 发票票据（Phase 2）：四要素解析 + 查验 + 报销风险校验（invoice.py）
- 记账核算（Phase 3）：流水解析 + 科目分类 + 凭证建议（bookkeeping.py，不自动过账）
- 税务申报（Phase 4）：税额测算 + 申报草稿（tax.py，强制人工确认）
"""
import httpx
from config import (
    LLM_BASE_URL, LLM_API_KEY, LLM_MODEL,
    KNOWLEDGE_DIR, KNOWLEDGE_MODE, RAG_API_URL, RAG_API_KEY,
)
from knowledge_base import KnowledgeBase
from invoice import parse_invoice_fields, verify_invoice, check_reimbursement_risk
from bookkeeping import bookkeeping_flow
from tax import tax_flow

kb = KnowledgeBase(KNOWLEDGE_DIR)

SYSTEM_PROMPT = """# 角色
你是"财税小助手"，一位有 15 年经验的财税顾问，服务于企业内部员工与财务同事。
核心目标：用准确、合规、易懂的方式，处理发票/记账/税务/政策四类财税诉求。

# 核心能力
1. 财税政策问答：基于知识库（税法/制度/解读）准确回答，标注政策出处与生效日期。
2. 发票票据处理：识别发票、发起查验、提示报销风险点。
3. 智能记账核算：根据流水/票据给出科目分类与凭证建议（不直接改账，仅建议）。
4. 税务申报筹划：计算税额、生成申报表草稿，标注风险，提交前必须人工确认。

# 输出规范
- 格式：能用表格就用表格；结论先行，再给依据。
- 风格：专业但不晦涩，非财人员也能看懂。
- 长度：常规回答 200 字内，复杂事项分点。

# 约束与边界（财税高敏感，严格遵守）
- 不编造政策：知识库没有的，说"需核实，建议咨询主管税务机关或贵司税务师"。
- 数据脱敏：输出中身份证、银行卡、完整税号做掩码（如 310***1234）。
- 不越权：绝不自行提交申报、对外发函、删除数据、过账；高风险动作只生成草稿并提示人工确认。
- 不泄露：不输出其他员工的薪酬、其他主体的涉密财务数据。
"""

INTENT_PROMPT = """你是一个财税意图分类器。仅输出下列之一（不要解释）：
政策问答 / 发票票据 / 记账核算 / 税务申报 / 其他
用户说：{q}"""


async def llm_chat(system: str, user: str, temperature: float = 0.3) -> str:
    if not LLM_API_KEY:
        return "（未配置 LLM_API_KEY，请在企业微信应用配置或 .env 中填入后重试）"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{LLM_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"},
            json={"model": LLM_MODEL, "temperature": temperature,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}]},
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()


def _keyword_route(query: str) -> str:
    """无 LLM / LLM 失败时的本地关键词兜底路由，保证基础可用性。"""
    # 顺序：先最具体的发票 / 记账 / 申报，再政策问答，最后其他
    if any(k in query for k in ["查验", "发票", "报销", "核验"]):
        return "发票票据"
    if any(k in query for k in ["记账", "凭证", "流水", "支付", "收到", "工资",
                                "费用", "科目", "入账", "做账"]):
        return "记账核算"
    if any(k in query for k in ["申报", "税额", "增值税", "所得税", "季度",
                                "销售额", "汇算", "预缴", "纳税"]):
        return "税务申报"
    if any(k in query for k in ["政策", "优惠", "规定", "制度", "标准", "怎么",
                                "如何", "什么", "为什么", "税", "法", "条例"]):
        return "政策问答"
    return "其他"


async def classify_intent(query: str) -> str:
    try:
        raw = await llm_chat("你是分类器，只输出类别名。", INTENT_PROMPT.format(q=query))
        for tag in ["政策问答", "发票票据", "记账核算", "税务申报"]:
            if tag in raw:
                return tag
    except Exception:
        pass
    # LLM 未配置 / 调用失败 / 未返回已知类别 → 关键词兜底
    return _keyword_route(query)


def _build_context(chunks) -> str:
    return "\n\n".join(f"【来源：{c['source']}】\n{c['text']}" for c in chunks)


async def policy_qa(query: str) -> str:
    if KNOWLEDGE_MODE == "rag":
        context = _query_rag(query)
    else:
        hits = kb.search(query)
        if not hits:
            return "未能在知识库中匹配到相关内容。请确认已上传财税制度/政策文档；如为最新政策，建议咨询主管税务机关或贵司税务师（需核实）。"
        context = _build_context(hits)

    prompt = (
        f"请仅基于下列资料回答问题，并在答案末尾用括号标注引用来源文件名。"
        f"若资料未提及，明确回答\"需核实，建议咨询主管税务机关或贵司税务师\"。\n\n"
        f"===== 资料 =====\n{context}\n===== 资料结束 =====\n\n问题：{query}"
    )
    return await llm_chat(SYSTEM_PROMPT, prompt)


def _query_rag(query: str) -> str:
    """接入外部向量库/RAG 服务的扩展点（KNOWLEDGE_MODE=rag 时启用）。需核实各服务接口。"""
    import requests
    resp = requests.post(RAG_API_URL, headers={"Authorization": f"Bearer {RAG_API_KEY}"},
                         json={"query": query}, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    # 假设返回 {"results":[{"content":..., "source":...}]}，按实际接口调整
    return "\n\n".join(f"【来源：{r.get('source','未知')}】\n{r.get('content','')}" for r in data.get("results", []))


async def invoice_flow(content: str, user_id: str) -> str:
    """发票票据处理（Phase 2）：解析四要素 → 本地风险校验（含重复报销）→ 第三方查验（若已配置）。"""
    fields = parse_invoice_fields(content)
    required = ("invoice_code", "invoice_no", "invoice_date", "amount")
    have = [k for k in required if fields.get(k)]
    if len(have) < 3:
        return (
            "🧾 发票票据处理引导\n"
            "请按以下任一格式发送发票信息，我来帮您做查验 + 报销风险校验：\n"
            "格式一：查验 011002300311 12345678 2024-05-12 560.00 123456\n"
            "格式二：发票代码011002300311 发票号码12345678 开票日期2024-05-12 价税合计560 校验码123456\n"
            "（代码10/12位、号码8位、日期YYYY-MM-DD、金额、校验码后6位）\n\n"
            "说明：当前为 Phase 2 接入版。未配置第三方查验（INVOICE_PROVIDER）时，我会先做本地报销风险校验并提示补齐；"
            "配置后可直接返回查验平台结果。报销登记需财务人工确认后再执行。"
        )
    risk = check_reimbursement_risk(fields, payer=user_id)
    verify = await verify_invoice(fields)

    lines = [f"🧾 发票查验与风险校验（申请人：{user_id}）",
             f"发票：{fields['invoice_code']} / {fields['invoice_no']}（已掩码归档，不展示完整号码）",
             f"风险等级：{risk['level']}"]
    for r in risk["reasons"]:
        lines.append(f"· {r}")
    # 查验结果展示（含真伪状态与金额一致性）
    if verify.get("status") == "真票" and verify["ok"]:
        lines.append("查验结果：✅ 真伪校验通过（查验平台返回为真票）。")
        cons = verify.get("consistency", {})
        if cons.get("amount_match") is False:
            lines.append(f"⚠️ {cons['notes'][0] if cons.get('notes') else '金额不一致'}（请核对后处理）")
        seller = verify.get("result", {}).get("seller_name")
        if seller:
            lines.append(f"销方名称：{seller}")
    elif verify["ok"]:
        lines.append(f"查验结果：⚠️ 已返回但状态为「{verify.get('status','未知')}」，请人工复核。")
    elif verify.get("error"):
        lines.append(f"查验：⚠️ {verify['error']}")
    lines.append("提示：以上为辅助校验，报销以贵司财务制度与人工审核为准；确认无误后由财务登记归档。")
    return "\n".join(lines)


async def handle_message(user_id: str, content: str) -> str:
    intent = await classify_intent(content)
    if intent == "政策问答":
        return await policy_qa(content)
    # 发票票据（Phase 2 已接入：查验 + 报销风险校验）
    if intent == "发票票据":
        return await invoice_flow(content, user_id)
    # 记账核算（Phase 3 已接入：科目分类 + 凭证建议，不自动过账）
    if intent == "记账核算":
        return bookkeeping_flow(content)
    # 税务申报（Phase 4 已接入：税额测算 + 申报草稿，强制人工确认）
    if intent == "税务申报":
        return tax_flow(content)
    return ("您好，我是财税小助手。目前已上线【财税政策问答】【发票票据处理】"
            "【智能记账核算】【税务申报筹划】。您可以问我财税政策、发送发票做查验、"
            "发送流水做记账建议，或发送销售额做税务测算。")
