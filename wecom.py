"""
finnbot · 企业微信消息收发
包含：回调签名校验、消息加解密（AES-256-CBC，企业微信官方算法）、access_token 缓存、主动发消息。
依赖：pycryptodome
"""
import base64
import hashlib
import os
import struct
import time
import xml.etree.ElementTree as ET
import requests

try:
    from Crypto.Cipher import AES
except ImportError:
    raise ImportError("请先安装依赖：pip install pycryptodome")


class PKCS7Encoder:
    block_size = 32

    def encode(self, text: bytes) -> bytes:
        amount_to_pad = self.block_size - (len(text) % self.block_size)
        if amount_to_pad == 0:
            amount_to_pad = self.block_size
        pad = bytes([amount_to_pad]) * amount_to_pad
        return text + pad

    def decode(self, decrypted: bytes) -> bytes:
        pad = decrypted[-1]
        if pad < 1 or pad > 32:
            return decrypted
        return decrypted[:-pad]


class WXBizMsgCrypt:
    """企业微信消息体加解密（标准算法实现）。"""

    def __init__(self, token: str, encoding_aes_key: str, receive_id: str):
        self.token = token
        self.receive_id = receive_id
        # 延迟校验：缺配置（未填 .env）时不崩溃，保证 /health 等接口可用；
        # 真正加解密时若 key 无效再抛出清晰错误。
        try:
            self.key = base64.b64decode(encoding_aes_key + "=")
        except Exception:
            self.key = b""
        if len(self.key) == 32:
            self.iv = self.key[:16]
        else:
            self.key = None
            self.iv = None

    # ---- 签名 ----
    def _signature(self, timestamp: str, nonce: str, encrypt: str) -> str:
        arr = sorted([self.token, timestamp, nonce, encrypt])
        sha = hashlib.sha1()
        sha.update("".join(arr).encode("utf-8"))
        return sha.hexdigest()

    def verify_signature(self, msg_signature: str, timestamp: str, nonce: str, encrypt: str) -> bool:
        return self._signature(timestamp, nonce, encrypt) == msg_signature

    # ---- 加密 ----
    def encrypt(self, text: str) -> str:
        if self.key is None:
            raise RuntimeError("EncodingAESKey 未正确配置（WECOM_ENCODING_AES 应为 43 位 Base64 字符串）")
        text_bytes = text.encode("utf-8")
        random16 = os.urandom(16)
        msg_len = struct.pack(">I", len(text_bytes))
        raw = random16 + msg_len + text_bytes + self.receive_id.encode("utf-8")
        raw = PKCS7Encoder().encode(raw)
        cipher = AES.new(self.key, AES.MODE_CBC, self.iv)
        encrypted = cipher.encrypt(raw)
        return base64.b64encode(encrypted).decode("utf-8")

    # ---- 解密 ----
    def decrypt(self, text: str) -> str:
        if self.key is None:
            raise RuntimeError("EncodingAESKey 未正确配置（WECOM_ENCODING_AES 应为 43 位 Base64 字符串）")
        encrypted = base64.b64decode(text)
        cipher = AES.new(self.key, AES.MODE_CBC, self.iv)
        raw = cipher.decrypt(encrypted)
        raw = PKCS7Encoder().decode(raw)
        content = raw[16:]
        xml_len = struct.unpack(">I", content[:4])[0]
        xml_content = content[4:4 + xml_len]
        from_receive = content[4 + xml_len:]
        if from_receive.decode("utf-8") != self.receive_id:
            raise ValueError("receive_id 校验失败，疑似伪造消息")
        return xml_content.decode("utf-8")


# ---------------- access_token 缓存 ----------------
_TOKEN_CACHE = {"token": "", "expire_at": 0}


def get_access_token(corp_id: str, corp_secret: str) -> str:
    now = time.time()
    if _TOKEN_CACHE["token"] and now < _TOKEN_CACHE["expire_at"] - 60:
        return _TOKEN_CACHE["token"]
    url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
    resp = requests.get(url, params={"corpid": corp_id, "corpsecret": corp_secret}, timeout=10)
    data = resp.json()
    if data.get("errcode", 0) != 0:
        raise RuntimeError(f"获取 access_token 失败: {data}")
    _TOKEN_CACHE["token"] = data["access_token"]
    _TOKEN_CACHE["expire_at"] = now + data.get("expires_in", 7200)
    return _TOKEN_CACHE["token"]


def send_app_text(corp_id: str, corp_secret: str, agent_id: str, user_id: str, text: str) -> dict:
    """主动发送应用消息（用于异步回推，规避 5 秒被动回复超时）。"""
    token = get_access_token(corp_id, corp_secret)
    url = "https://qyapi.weixin.qq.com/cgi-bin/message/send"
    payload = {
        "touser": user_id,
        "msgtype": "text",
        "agentid": int(agent_id),
        "text": {"content": text[:2000]},  # 企业微信单条文本上限约 2000 字
    }
    resp = requests.post(url, params={"access_token": token}, json=payload, timeout=10)
    return resp.json()


def parse_incoming_xml(xml_text: str) -> dict:
    """解析解密后的明文消息 XML。"""
    root = ET.fromstring(xml_text)
    return {child.tag: (child.text or "") for child in root}
