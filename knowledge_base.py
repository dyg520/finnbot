"""
finnbot · 知识库检索（Phase 1 默认 local 模式）
- 递归加载 knowledge/ 下所有 .txt/.md（含子目录，跳过隐藏文件）
- 按 Markdown 标题 + 空行分块，并记录来源文件名、更新日期等 metadata
- jieba 中文分词（可选），未安装时降级为字符二元组
- 零外部服务即可跑通；可切 rag 模式接入向量库（见 agent.py 的 query_rag）
"""
import os
import re

try:
    import jieba
    jieba.setLogLevel(20)  # 静默
except ImportError:
    jieba = None


class KnowledgeBase:
    def __init__(self, dir_path: str):
        self.chunks = []
        self._load(dir_path)

    def _load(self, dir_path: str):
        if not os.path.isdir(dir_path):
            print(f"[knowledge] 目录不存在: {dir_path}，知识库为空")
            return
        files = []
        for root, _, fns in os.walk(dir_path):
            if os.path.basename(root).startswith("."):  # 跳过隐藏目录
                continue
            for fn in sorted(fns):
                if fn.endswith((".txt", ".md")) and not fn.startswith("."):
                    files.append(os.path.join(root, fn))
        for fp in files:
            self._load_file(dir_path, fp)
        print(f"[knowledge] 已加载 {len(self.chunks)} 个片段，来源文件 {len(files)} 个")

    def _load_file(self, base_dir: str, fp: str):
        rel = os.path.relpath(fp, base_dir)
        with open(fp, encoding="utf-8") as f:
            text = f.read()
        meta = self._parse_frontmatter(text)
        body = meta.get("_body", text)
        for chunk in self._split(body):
            chunk = chunk.strip()
            if len(chunk) < 20:
                continue
            self.chunks.append({
                "source": rel,
                "text": chunk,
                "updated": meta.get("updated", ""),
            })

    @staticmethod
    def _parse_frontmatter(text: str) -> dict:
        """解析简单 YAML frontmatter：
        ---
        updated: 2024-01-01
        category: 制度
        ---
        可选；用于标注文档更新日期 / 分类，方便溯源与过期提醒。"""
        m = re.match(r"^\s*---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
        if not m:
            return {}
        meta = {}
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        meta["_body"] = m.group(2)
        return meta

    @staticmethod
    def _split(text: str):
        """按 Markdown 标题（#/##/###）分块；无标题段落按空行切。
        返回带标题上下文的文本片段列表。"""
        lines = text.splitlines()
        blocks = []
        cur_heading = []
        buf = []
        for ln in lines:
            hm = re.match(r"^(#{1,3})\s+(.*)$", ln)
            if hm:
                if buf:
                    blocks.append((" > ".join(cur_heading), "\n".join(buf)))
                    buf = []
                cur_heading = [hm.group(2).strip()]
            else:
                if ln.strip():
                    buf.append(ln)
                else:
                    if buf:
                        blocks.append((" > ".join(cur_heading), "\n".join(buf)))
                        buf = []
        if buf:
            blocks.append((" > ".join(cur_heading), "\n".join(buf)))
        out = []
        for heading, body in blocks:
            out.append(f"【{heading}】\n{body}" if heading else body)
        return out

    @staticmethod
    def _tokens(text: str):
        if jieba:
            return set(t for t in jieba.cut(text) if len(t) > 1)
        # 降级：字符二元组
        return set(text[i:i + 2] for i in range(len(text) - 1))

    def search(self, query: str, top_k: int = 3):
        q_tokens = self._tokens(query)
        if not q_tokens:
            return []
        scored = []
        for c in self.chunks:
            c_tokens = self._tokens(c["text"])
            overlap = len(q_tokens & c_tokens)
            if overlap > 0:
                scored.append((overlap, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored[:top_k]]
