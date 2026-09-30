"""
finnbot · 税务申报筹划（Phase 4）
- 基于输入做简易税额测算（增值税及附加、企业所得税示意）
- 生成申报表草稿文本
- 强制人工确认，绝不自动提交电子税务局
安全：不连接电子税务局；只出草稿。税率/优惠以最新政策与主管税务机关口径为准，需核实。
"""
import re


def parse_tax_input(text: str) -> dict:
    d = {"type": None, "sales": None, "period": "月", "input_tax": None}
    if re.search(r"小规模", text):
        d["type"] = "小规模"
    elif re.search(r"一般", text):
        d["type"] = "一般"
    m = re.search(r"销售额[^\d]*(\d+(?:\.\d{1,2})?)", text)
    if m:
        d["sales"] = float(m.group(1))
    if re.search(r"季度", text):
        d["period"] = "季度"
    m = re.search(r"进项[^\d]*(\d+(?:\.\d{1,2})?)", text)
    if m:
        d["input_tax"] = float(m.group(1))
    return d


def calc_vat(d: dict) -> dict:
    sales = d["sales"] or 0
    if d["type"] == "小规模":
        # 现行：月销售额 10 万 / 季 30 万以下免征增值税；征收率减按 1%（以最新政策为准）
        threshold = 300000 if d["period"] == "季度" else 100000
        rate = 0.01
        if sales <= threshold:
            return {"vat": 0.0, "surcharge": 0.0, "exempt": True, "rate": rate}
        vat = round(sales * rate, 2)
        surcharge = round(vat * 0.12, 2)  # 城建7% + 教育3% + 地方教育2%
        return {"vat": vat, "surcharge": surcharge, "exempt": False, "rate": rate}
    else:
        # 一般纳税人：简易示意（应纳税额 ≈ 销项 - 进项），实际按适用税率分业务
        input_tax = d["input_tax"] or 0
        output = round(sales * 0.13, 2)  # 示意销项税率 13%
        vat = round(max(output - input_tax, 0), 2)
        surcharge = round(vat * 0.12, 2) if vat else 0
        return {"vat": vat, "surcharge": surcharge, "exempt": False,
                "rate": 0.13, "output": output}


def tax_flow(text: str) -> str:
    d = parse_tax_input(text)
    if d["sales"] is None:
        return (
            "🧮 税务申报筹划引导\n"
            "请发送测算请求，我来帮您做【税额测算 + 申报草稿】（不代为提交）。\n"
            "示例：申报 小规模 销售额 120000 季度\n"
            "示例：申报 一般 销售额 500000 进项 30000\n"
            "说明：测算为辅助估算，最终以电子税务局申报表与最新政策为准；本助手不自动提交申报。"
        )
    res = calc_vat(d)
    lines = [f"🧮 税务测算草稿（{d['type']}纳税人 / {d['period']}）",
             f"销售额：{d['sales']:.2f}"]
    if res.get("exempt"):
        lines.append("增值税：✅ 未超起征点，免征增值税（含附加）")
    else:
        lines.append(f"增值税（征收率/税率 {res['rate']}）：{res['vat']:.2f}")
    lines.append(f"附加税费（合计约 12%）：{res['surcharge']:.2f}")
    lines.append(f"合计应纳税额（估）：{res['vat'] + res['surcharge']:.2f}")
    lines.append("\n⚠️ 风险提示：")
    lines.append("· 以上为辅助测算，税率 / 起征点 / 优惠以最新政策与主管税务机关口径为准，需核实。")
    lines.append("· 本助手仅生成草稿，请财务在电子税务局人工核对并提交，绝不自动申报。")
    return "\n".join(lines)
