from __future__ import annotations

import io
import re
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter

import streamlit as st

st.set_page_config(page_title="DocuMind AI", page_icon="📄", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700&display=swap');
html, body, [class*="css"] { font-family: Cairo, sans-serif; }
.hero { background: linear-gradient(135deg,#0f766e,#155e75); color:white; padding:24px; border-radius:16px; margin-bottom:18px; }
.hero h1 { margin:0; }
.source { background:#f0fdfa; border-right:4px solid #0f766e; padding:12px; border-radius:8px; margin:8px 0; }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="hero"><h1>DocuMind AI</h1><p>فهم المستندات، التلخيص، البحث، والإجابة عن الأسئلة</p></div>', unsafe_allow_html=True)


def read_docx(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        xml_data = archive.read("word/document.xml")
    root = ET.fromstring(xml_data)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs = []
    for paragraph in root.findall(".//w:p", ns):
        text = "".join(node.text or "" for node in paragraph.findall(".//w:t", ns))
        if text.strip():
            paragraphs.append(text)
    return "\n".join(paragraphs)


def read_pdf_basic(data):
    # Lightweight PDF text reader using only the Python standard library.
    raw = data.decode("latin-1", errors="ignore")
    pieces = []
    for block in re.findall(r"stream\s*(.*?)\s*endstream", raw, flags=re.S):
        for value in re.findall(r"\((.*?)\)\s*T[Jj]", block, flags=re.S):
            value = value.replace(r"\n", " ").replace(r"\(", "(").replace(r"\)", ")")
            pieces.append(value)
    if not pieces:
        pieces = re.findall(r"\(([^()] {2,})\)", raw)
    return " ".join(pieces)


def read_file(name, data):
    extension = name.lower().rsplit(".", 1)[-1]
    if extension in {"txt", "md"}:
        return data.decode("utf-8", errors="ignore")
    if extension == "docx":
        return read_docx(data)
    if extension == "pdf":
        return read_pdf_basic(data)
    raise ValueError("الأنواع المدعومة: PDF وDOCX وTXT وMD")


def chunks_from_text(text, size=850):
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return []
    sentences = re.split(r"(?<=[.!؟?؛])\s+", clean)
    chunks, current = [], ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > size:
            chunks.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def tokens(text):
    return re.findall(r"[\w\u0600-\u06FF]{2,}", text.lower())


def relevance(query, text):
    q = Counter(tokens(query))
    t = Counter(tokens(text))
    if not q or not t:
        return 0.0
    common = sum(min(count, t[word]) for word, count in q.items())
    return common / max(1, sum(q.values()))


def important_sentences(chunks, count=5):
    all_words = Counter(tokens(" ".join(chunks)))
    scored = []
    for position, chunk in enumerate(chunks):
        words = tokens(chunk)
        score = sum(all_words[word] for word in words) / max(1, len(words))
        scored.append((score, position, chunk))
    return [chunk for _, _, chunk in sorted(scored, reverse=True)[:count]]


def extract_data(text):
    dates = re.findall(r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})\b", text)
    emails = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    phones = re.findall(r"(?:\+?\d[\d\s().-]{7,}\d)", text)
    names = re.findall(r"(?:الاسم|اسم العميل|المسؤول|السيد|السيدة)\s*[:：-]\s*([^،,؛;\n]{2,50})", text)
    return {"التواريخ": dates, "البريد الإلكتروني": emails, "أرقام الهاتف": phones, "أسماء محتملة": names}


uploaded = st.file_uploader("ارفعي مستندًا للتحليل", type=["pdf", "docx", "txt", "md"])

if uploaded:
    try:
        text = read_file(uploaded.name, uploaded.getvalue())
        chunks = chunks_from_text(text)
        if not chunks:
            st.error("لم أستطع استخراج نص من الملف. جرّبي TXT أو DOCX، أو استخدمي PDF نصيًا غير ممسوح ضوئيًا.")
        else:
            st.session_state.document = {"name": uploaded.name, "text": text, "chunks": chunks}
            st.success(f"تمت قراءة الملف وفهرسة {len(chunks)} مقطعًا")
    except Exception as error:
        st.error(f"حدث خطأ أثناء قراءة الملف: {error}")

document = st.session_state.get("document")
if not document:
    st.info("ارفعي ملفًا من الأعلى للبدء.")
else:
    chunks = document["chunks"]
    text = document["text"]
    overview, questions, data_tab, extracted = st.tabs(["نظرة عامة", "اسألي المستند", "البيانات المهمة", "النص المستخرج"])

    with overview:
        st.metric("عدد المقاطع", len(chunks))
        if st.button("إنشاء ملخص", type="primary"):
            summary = important_sentences(chunks)
            st.session_state.summary = "\n\n".join("• " + item for item in summary)
        if st.session_state.get("summary"):
            st.subheader("الملخص")
            st.write(st.session_state.summary)

    with questions:
        question = st.text_input("اكتبي سؤالك عن المستند", placeholder="مثال: ما أهم التواريخ المذكورة؟")
        if st.button("إجابة", type="primary", disabled=not question.strip()):
            results = sorted(((relevance(question, chunk), index, chunk) for index, chunk in enumerate(chunks)), reverse=True)
            results = [(score, index, chunk) for score, index, chunk in results[:5] if score > 0]
            if results:
                answer = "\n\n".join("• " + chunk for _, _, chunk in results[:3])
            else:
                answer = "لم أجد مقطعًا مرتبطًا بالسؤال داخل المستند."
            st.session_state.answer = answer
            st.session_state.results = results
        if st.session_state.get("answer"):
            st.subheader("الإجابة")
            st.write(st.session_state.answer)
            st.subheader("المصادر")
            for number, (score, index, chunk) in enumerate(st.session_state.get("results", []), 1):
                st.markdown(f'<div class="source"><b>المصدر {number} — المقطع {index + 1}</b><br>{chunk}<br>درجة الصلة: {score:.2f}</div>', unsafe_allow_html=True)

    with data_tab:
        st.subheader("البيانات المهمة")
        for label, values in extract_data(text).items():
            st.markdown(f"**{label}**")
            st.write("، ".join(dict.fromkeys(values)) if values else "لم يتم العثور على بيانات")

    with extracted:
        st.text_area("النص المستخرج", text, height=450)
