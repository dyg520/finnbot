"""
finnbot · 本地自测（无需企业微信即可验证核心逻辑）
运行：python selftest.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from wecom import WXBizMsgCrypt
from knowledge_base import KnowledgeBase


def test_crypto_roundtrip():
    import base64 as _b64
    token = "testtoken"
    # 模拟企业微信 43 字符 EncodingAESKey（base64 编码 32 字节后去掉末尾 '='）
    aes_key = _b64.b64encode(b"0" * 32).decode()[:43]
    receive_id = "wwcorpid123"
    crypt = WXBizMsgCrypt(token, aes_key, receive_id)

    plain = "<xml><Content><![CDATA[小规模纳税人增值税优惠]]></Content></xml>"
    enc = crypt.encrypt(plain)
    dec = crypt.decrypt(enc)
    assert dec == plain, f"加解密不一致: {dec}"

    sig = crypt._signature("1700000000", "nonce123", enc)
    assert crypt.verify_signature(sig, "1700000000", "nonce123", enc)
    print("[OK] 加解密 round-trip 与签名校验通过")


def test_knowledge_search():
    kb = KnowledgeBase(os.path.join(os.path.dirname(__file__), "knowledge"))
    assert kb.chunks, "知识库为空，请检查 knowledge/ 目录"
    hits = kb.search("小规模纳税人的增值税优惠")
    assert hits, "检索未命中"
    print(f"[OK] 知识库加载 {len(kb.chunks)} 片段，检索命中 {len(hits)} 条")
    for h in hits:
        print(f"     - 来源 {h['source']} | 前20字: {h['text'][:20]}")

    # 验证多文件/规范化文档被加载并命中
    hit2 = kb.search("差旅住宿费标准 一线城市")
    assert hit2 and any("差旅" in h["source"] for h in hit2), "规范化示例文档未被加载/命中"
    print(f"[OK] 多文件知识库命中规范文档：{hit2[0]['source']}")


def test_invoice():
    import importlib
    import invoice as inv
    from invoice import parse_invoice_fields

    # 1) 四要素解析 —— 格式一（空格分隔）
    f1 = parse_invoice_fields("查验 011002300311 12345678 2024-05-12 560.00 123456")
    assert f1["invoice_code"] == "011002300311", f1
    assert f1["invoice_no"] == "12345678"
    assert f1["invoice_date"] == "2024-05-12"
    assert f1["amount"] == "560.00"
    assert f1["check_code"] == "123456"

    # 2) 四要素解析 —— 格式二（键值对）
    f2 = parse_invoice_fields("发票代码011002300311 发票号码12345678 开票日期2024-05-12 价税合计560 校验码123456")
    assert f2["invoice_code"] == "011002300311"
    assert f2["amount"] == "560"

    # 3) 报销风险校验 + 重复报销检测（用临时库，避免污染）
    tmp = os.path.join(os.path.dirname(__file__), "data", "selftest_tmp.db")
    if os.path.exists(tmp):
        os.remove(tmp)
    os.environ["INVOICE_DB_PATH"] = tmp
    importlib.reload(inv)
    inv.init_db()
    assert inv.record_invoice(f1, payer="tester") is True
    risk = inv.check_reimbursement_risk(f1, payer="another")
    assert risk["level"] == "高", risk
    os.remove(tmp)
    print("[OK] 发票四要素解析（两种格式）与重复报销检测通过")


def test_bookkeeping():
    from bookkeeping import parse_records, bookkeeping_flow
    recs = parse_records(
        "2024-05-12 支付某东办公用品 560.00\n"
        "2024-05-13 收到客户货款 10000.00"
    )
    assert len(recs) == 2, recs
    out = bookkeeping_flow("2024-05-12 支付某东办公用品 560.00")
    assert ("管理费用-办公费" in out) or ("凭证" in out), out
    print("[OK] 记账流水解析与科目建议通过")


def test_tax():
    from tax import tax_flow, parse_tax_input, calc_vat
    d = parse_tax_input("申报 小规模 销售额 120000 季度")
    assert d["type"] == "小规模" and d["sales"] == 120000, d
    assert calc_vat(d)["exempt"] is True  # 12 万 < 30 万起征点，免
    out = tax_flow("申报 小规模 销售额 400000 季度")
    assert "增值税" in out, out
    print("[OK] 税务测算（小规模起征点/征收率）通过")


if __name__ == "__main__":
    test_crypto_roundtrip()
    test_knowledge_search()
    test_invoice()
    test_bookkeeping()
    test_tax()
    print("\n全部自测通过 ✅")
