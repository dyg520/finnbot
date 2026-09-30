"""
finnbot · 智能记账核算（Phase 3）
- 解析银行流水 / 票据文本为结构化记录（日期、摘要、金额）
- 基于关键词规则给出科目分类建议
- 生成凭证分录草稿（仅建议，绝不自动过账）
安全：不连接任何账套 / 数据库写入；所有输出仅供财务人工确认。
"""
import re

# 关键词 → (建议借方科目, 备注)。贷方科目由分录方向决定（见 build_voucher）。
RULES = [
    ("工资|薪酬|社保|公积金|五险一金", "应付职工薪酬", "区分工资薪金与职工福利费；个税代扣代缴需单独处理"),
    ("办公用品|文具|耗材|打印|硒鼓", "管理费用-办公费", ""),
    ("餐饮|招待|吃饭|宴请|业务招待", "管理费用-业务招待费", "税前扣除有限额：发生额 60% 且不超过当年营收 0.5%"),
    ("差旅|机票|火车|高铁|住宿|酒店|出差", "管理费用-差旅费", ""),
    ("加油|过路|停车|打车|网约车|交通", "管理费用-交通费", ""),
    ("房租|租赁|物业|写字楼", "管理费用-租赁费", "经营租赁；融资租赁需资本化处理"),
    ("广告|宣传|推广|营销|展会", "销售费用-广告宣传费", "一般企业税前扣除不超过当年营收 15%（超额结转）"),
    ("快递|邮寄|物流|货运", "管理费用-快递费", ""),
    ("水电|电费|水费|燃气", "管理费用-水电费", ""),
    ("咨询|顾问|审计|法律|中介|服务费", "管理费用-服务费", ""),
    ("固定资产|设备|电脑|服务器|车辆|机器", "固定资产", "达确认标准入账并计提折旧/摊销"),
    ("利息|手续费|银行|工本费|账户", "财务费用-手续费", ""),
    ("收入|销售|收款|营收|货款|回款", "主营业务收入", "对应贷方为银行存款 / 应收账款"),
    ("税|缴税|增值税|所得税|附加税", "应交税费", "区分税种与所属期"),
]


def parse_records(text: str) -> list:
    """从文本解析多条流水记录。支持每行一条：日期 摘要 金额（分隔符不限）。
    返回 [{"date","desc","amount"}]。"""
    records = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.search(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})", line)
        date = m.group(1).replace("/", "-") if m else ""
        rest = re.sub(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", " ", line)
        amt_m = re.search(r"(\d+(?:\.\d{1,2})?)", rest)
        if not amt_m:
            continue  # 无金额的行跳过（引导语/表头）
        amount = amt_m.group(1)
        desc = re.sub(r"\d+(?:\.\d{1,2})?", "", rest)
        desc = desc.strip(" ,，、;；:-—")
        records.append({"date": date, "desc": desc or "（未识别摘要）", "amount": amount})
    return records


def suggest_subject(desc: str):
    for kw, subject, note in RULES:
        if re.search(kw, desc):
            return subject, note
    return "管理费用-其他", "未匹配到明确科目，请财务据实归类"


def build_voucher(record: dict) -> dict:
    subject, note = suggest_subject(record["desc"])
    is_income = bool(re.search(r"收入|销售|收款|营收|货款|回款", record["desc"]))
    if is_income:
        entries = [
            {"direction": "借", "subject": "银行存款 / 应收账款", "amount": record["amount"]},
            {"direction": "贷", "subject": subject, "amount": record["amount"]},
        ]
    else:
        entries = [
            {"direction": "借", "subject": subject, "amount": record["amount"]},
            {"direction": "贷", "subject": "银行存款 / 库存现金", "amount": record["amount"]},
        ]
    return {"date": record["date"], "desc": record["desc"], "amount": record["amount"],
            "entries": entries, "note": note, "is_income": is_income}


def bookkeeping_flow(text: str) -> str:
    """记账核算主流程：流水解析 → 科目分类 → 凭证建议（不自动过账）。"""
    records = parse_records(text)
    if not records:
        return (
            "📒 智能记账引导\n"
            "请发送银行流水或票据文本，我来帮您做【科目分类 + 凭证建议】（不自动过账）。\n"
            "支持格式（每行一条：日期 摘要 金额）：\n"
            "  2024-05-12 支付某东办公用品 560.00\n"
            "  2024-05-13 收到客户货款 10000.00\n"
            "可一次粘贴多行；复杂账务建议导出 Excel 后分批处理。"
        )
    lines = ["📒 记账核算建议（仅供财务确认，未过账）"]
    for r in records:
        v = build_voucher(r)
        lines.append(f"\n· 日期 {v['date']}｜摘要：{v['desc']}｜金额 {v['amount']}")
        for e in v["entries"]:
            lines.append(f"    {e['direction']} {e['subject']}  {e['amount']}")
        if v["note"]:
            lines.append(f"    ⚠️ {v['note']}")
    lines.append("\n以上为辅助凭证建议，请在财务软件中人工核对科目与金额后过账；"
                 "涉及税前扣除限额、资产折旧、收入确认等以准则与税务规定为准。")
    return "\n".join(lines)
