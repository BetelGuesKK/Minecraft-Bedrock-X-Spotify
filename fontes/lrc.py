"""
Letra sincronizada (LRC) -> cues no formato do addon: [inicioMs, fimMs, "texto"].

A quebra de linhas longas usa o MESMO algoritmo do build_songs.py (split_long),
com o mesmo limite de caracteres (MAX_LINE_CHARS = 42).
"""
import re

MAX_LINE_CHARS = 42      # igual ao build_songs.py
MAX_CUE_MS = 10000       # nenhuma linha fica na tela mais que isso
DEFAULT_LAST_MS = 4000   # duração da última linha (o LRC não diz quando ela acaba)

_TS = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_TAG = re.compile(r"^\[([a-zA-Z]+):([^\]]*)\]\s*$")


def _ts_ms(m, s, frac):
    frac = ((frac or "0") + "000")[:3]
    return (int(m) * 60 + int(s)) * 1000 + int(frac)


def clean_text(body):
    """Mesma limpeza do parse_srt do build_songs.py (tags, § e notas musicais)."""
    body = re.sub(r"<[^>]+>", "", body)       # <i>, <b>, tempo por palavra <00:12.30>
    body = re.sub(r"\{[^}]*\}", "", body)
    body = re.sub(r"\[[^\]]*\]", "", body)
    body = body.replace("§", "")              # § quebraria a formatação do Minecraft
    body = re.sub(r"[♪♫♬♩]", "", body)
    return re.sub(r"\s+", " ", body).strip()


def split_long(start, end, text):
    """Divide linhas longas em pedaços, repartindo o tempo pelo número de letras.
    (cópia do build_songs.py; só acrescenta corte por caracteres para texto sem espaços,
    como japonês/chinês, que o original deixaria numa linha só)"""
    if len(text) <= MAX_LINE_CHARS:
        return [[start, end, text]]
    if " " not in text:
        n = -(-len(text) // MAX_LINE_CHARS)
        size = -(-len(text) // n)
        parts = [text[i:i + size] for i in range(0, len(text), size)]
    else:
        words = text.split(" ")
        n = -(-len(text) // MAX_LINE_CHARS)
        limit = min(MAX_LINE_CHARS, len(text) // n + 8)
        parts, cur = [], ""
        for w in words:
            if cur and len(cur) + 1 + len(w) > limit:
                parts.append(cur)
                cur = w
            else:
                cur = (cur + " " + w).strip()
        if cur:
            parts.append(cur)
    total = sum(len(p) for p in parts)
    out, t = [], start
    for i, p in enumerate(parts):
        d = round((end - start) * len(p) / total)
        e = end if i == len(parts) - 1 else t + d
        out.append([t, e, p])
        t = e
    return out


def parse_lrc(lrc_text):
    """Devolve a lista de cues [inicio, fim, texto] ordenada por tempo."""
    offset = 0
    entries = []  # (ms, texto)
    for raw in lrc_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        tag = _TAG.match(line)
        if tag and not _TS.match(line):
            if tag.group(1).lower() == "offset":
                try:
                    offset = int(tag.group(2).strip())
                except ValueError:
                    pass
            continue
        stamps = list(_TS.finditer(line))
        if not stamps:
            continue
        text = clean_text(line[stamps[-1].end():])
        for m in stamps:
            entries.append((_ts_ms(*m.groups()), text))
    # [offset:+500] no LRC significa "a letra aparece 500 ms mais cedo"
    entries = [(max(0, ms - offset), t) for ms, t in entries]
    entries.sort(key=lambda e: e[0])

    cues = []
    for i, (start, text) in enumerate(entries):
        if not text:
            continue  # linha vazia = pausa instrumental (só serve para marcar o fim da anterior)
        nxt = entries[i + 1][0] if i + 1 < len(entries) else start + DEFAULT_LAST_MS
        end = nxt if nxt > start else start + DEFAULT_LAST_MS
        end = min(end, start + MAX_CUE_MS)
        if end <= start:
            end = start + 1500
        cues.extend(split_long(start, end, text))
    cues.sort(key=lambda c: c[0])
    return cues
