"""
finnbot · FastAPI 入口
企业微信回调：GET 校验 / POST 接收。关键：收到消息先立即回 success，再异步主动发消息，规避 5 秒超时。
"""
import asyncio
import xml.etree.ElementTree as ET
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

from config import (
    WECOM_CORP_ID, WECOM_AGENT_ID, WECOM_CORP_SECRET,
    WECOM_CALLBACK_TOKEN, WECOM_ENCODING_AES, WEBHOOK_PATH,
)
from wecom import WXBizMsgCrypt, send_app_text, parse_incoming_xml
from agent import handle_message

app = FastAPI(title="finnbot · 财税智能体工作台")

crypt = WXBizMsgCrypt(WECOM_CALLBACK_TOKEN, WECOM_ENCODING_AES, WECOM_CORP_ID)


@app.get(WEBHOOK_PATH)
async def verify(msg_signature: str, timestamp: str, nonce: str, echostr: str):
    """企业微信 GET 校验：解密 echostr 原样返回。"""
    if not crypt.verify_signature(msg_signature, timestamp, nonce, echostr):
        return PlainTextResponse("invalid", status_code=403)
    try:
        plain = crypt.decrypt(echostr)
    except Exception as e:
        return PlainTextResponse(f"decrypt error: {e}", status_code=400)
    return PlainTextResponse(plain)


@app.post(WEBHOOK_PATH)
async def receive(request: Request, msg_signature: str, timestamp: str, nonce: str):
    """企业微信 POST 接收：先回 success，再异步处理并主动发消息。"""
    body = await request.body()
    root = ET.fromstring(body)
    encrypt = root.findtext("Encrypt")
    if not crypt.verify_signature(msg_signature, timestamp, nonce, encrypt):
        return PlainTextResponse("invalid", status_code=403)

    xml_msg = crypt.decrypt(encrypt)
    msg = parse_incoming_xml(xml_msg)
    user = msg.get("FromUserName", "")
    content = msg.get("Content", "")
    msg_type = msg.get("MsgType", "")

    # 立即返回，避免 5 秒被动回复超时
    asyncio.create_task(process_and_reply(user, content, msg_type))
    return PlainTextResponse("success")


async def process_and_reply(user: str, content: str, msg_type: str):
    if msg_type != "text" or not content:
        reply = "暂仅支持文本消息，请直接输入您的财税问题。"
    else:
        try:
            reply = await handle_message(user, content)
        except Exception as e:
            reply = f"处理出错，请稍后重试。（错误：{e}）"
            print(f"[error] handle_message 失败: {e}")

    try:
        await asyncio.to_thread(
            send_app_text, WECOM_CORP_ID, WECOM_CORP_SECRET, WECOM_AGENT_ID, user, reply
        )
    except Exception as e:
        print(f"[error] 发送消息失败 user={user}: {e}")


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
