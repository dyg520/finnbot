"""
finnbot · 端到端验收脚本（不依赖企业微信、不依赖真实大模型）
运行：python smoke_test.py

作用：在部署/交付前，模拟四类财税消息经"主智能体意图路由"后的链路是否通畅：
  - 发票票据（本地解析 + 风险校验，无需外部网络）
  - 记账核算（本地科目分类 + 凭证建议）
  - 税务申报（本地税额测算 + 草稿）
  - 知识库检索（验证制度文档已加载可命中）
  - 加解密 round-trip（验证企业微信回调基础能力）

政策问答需真实 LLM，未配置 LLM_API_KEY 时跳过并提示。

该脚本让"没有企业微信、没有 LLM 账号"的情况下，也能把四个业务场景的
代码链路跑通，便于本地验收与 CI。
"""
import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(__file__))


def _hr(title: str):
    print(f"\n{'=' * 56}\n  {title}\n{'=' * 56}")


async def run_all():
    # ---------- 0. 加解密基础 ----------
    _hr("0. 企业微信加解密 round-trip")
    from wecom import WXBizMsgCrypt
    import base64 as _b64
    token = "smoketoken"
    aes_key = _b64.b64encode(b"0" * 32).decode()[:43]
    crypt = WXBizMsgCrypt(token, aes_key, "wwsmokecorp")
    plain = "<xml><Content><![CDATA[测试消息]]></Content></xml>"
    enc = crypt.encrypt(plain)
    dec = crypt.decrypt(enc)
    assert dec == plain, "加解密不一致"
    print("[OK] 企业微信消息加解密可还原")

    # ---------- 1. 知识库检索 ----------
    _hr("1. 知识库检索（制度文档命中）")
    from knowledge_base import KnowledgeBase
    kb = KnowledgeBase(os.path.join(os.path.dirname(__file__), "knowledge"))
    assert kb.chunks, "知识库为空"
    hits = kb.search("差旅住宿费标准")
    assert hits, "检索未命中"
    print(f"[OK] 知识库加载 {len(kb.chunks)} 片段，'差旅住宿费标准'命中 {len(hits)} 条")

    # ---------- 2. 发票票据 ----------
    _hr("2. 发票票据（解析 + 本地风险校验）")
    from agent import invoice_flow
    out = await invoice_flow(
        "查验 011002300311 12345678 2024-05-12 560.00 123456", "smoke_user"
    )
    assert "风险等级" in out and "发票" in out, out
    print("[OK] 发票四要素解析 + 风险校验链路通畅")
    print("     示例输出片段：")
    for line in out.splitlines()[:3]:
        print(f"       {line}")

    # ---------- 3. 记账核算 ----------
    _hr("3. 记账核算（科目分类 + 凭证建议）")
    from agent import handle_message
    out = await handle_message("smoke_user", "2024-05-12 支付某东办公用品 560.00")
    assert "凭证" in out or "科目" in out, out
    print("[OK] 记账流水解析 + 凭证建议链路通畅")
    for line in out.splitlines()[:3]:
        print(f"       {line}")

    # ---------- 4. 税务申报 ----------
    _hr("4. 税务申报（税额测算 + 草稿）")
    out = await handle_message("smoke_user", "申报 小规模 销售额 400000 季度")
    assert "增值税" in out, out
    print("[OK] 税务测算 + 申报草稿链路通畅")
    for line in out.splitlines()[:3]:
        print(f"       {line}")

    # ---------- 5. 政策问答（需 LLM） ----------
    _hr("5. 政策问答（需配置 LLM_API_KEY）")
    from config import LLM_API_KEY
    if not LLM_API_KEY:
        print("[SKIP] 未配置 LLM_API_KEY，跳过真实政策问答；"
              "部署时在 .env 填入后即可验证（见 README 第三步）。")
    else:
        out = await handle_message("smoke_user", "小微企业增值税有什么优惠？")
        assert out and len(out) > 0, "政策问答返回为空"
        print("[OK] 政策问答链路通畅（返回长度 %d 字）" % len(out))

    _hr("验收结论")
    print("✅ 核心链路（加解密 / 知识库 / 发票 / 记账 / 申报）全部通畅。")
    print("   政策问答需配置 LLM_API_KEY 后在企业微信或 smoke_test 中验收。")


if __name__ == "__main__":
    try:
        asyncio.run(run_all())
    except AssertionError as e:
        print(f"\n❌ 验收失败：{e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 运行异常：{e}")
        sys.exit(1)
