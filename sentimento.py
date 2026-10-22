import json
import os
import re
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (compatible; AgentePNCP/1.0)"

POSITIVAS = {
    "surge": 1.0, "soar": 0.8, "rally": 1.0, "beat": 0.9, "beats": 0.9, "record": 0.7,
    "growth": 0.6, "gain": 0.7, "gains": 0.7, "upgrade": 0.9, "bullish": 1.0, "bull": 0.8,
    "breakthrough": 0.9, "approval": 0.8, "approved": 0.8, "wins": 0.8, "win": 0.7,
    "strong": 0.6, "boost": 0.7, "buy": 0.6, "bullrun": 1.0, "higher": 0.5, "rises": 0.6,
    "rise": 0.6, "jump": 0.6, "jumps": 0.6, "soars": 0.9, "outperform": 0.8, "profit": 0.6,
    "confident": 0.5, "breakthroughs": 0.8, "cresce": 0.6, "alta": 0.6, "sobe": 0.6, "ganha": 0.6,
    "vitória": 0.7, "aprovado": 0.7, "recorde": 0.6, "crescimento": 0.6, "superar": 0.6,
}

NEGATIVAS = {
    "crash": -1.0, "plunge": -1.0, "plunges": -1.0, "tumble": -0.9, "fall": -0.7, "falls": -0.7,
    "drop": -0.7, "drops": -0.7, "downgrade": -0.9, "bearish": -1.0, "bear": -0.7, "loss": -0.7,
    "losses": -0.7, "weak": -0.6, "sell": -0.6, "lawsuit": -0.7, "probe": -0.6, "investigation": -0.7,
    "ban": -0.8, "banned": -0.8, "fail": -0.8, "fails": -0.8, "failure": -0.8, "recession": -0.9,
    "collapse": -1.0, "scandal": -0.9, "delay": -0.5, "delays": -0.5, "risk": -0.4, "risks": -0.4,
    "warning": -0.6, "warns": -0.6, "cut": -0.5, "cuts": -0.5, "layoff": -0.7, "layoffs": -0.7,
    "queda": -0.8, "cai": -0.7, "perda": -0.7, "prejuizo": -0.8, "fracasso": -0.8, "crise": -0.9,
    "investiga": -0.6, "proibido": -0.8, "retração": -0.7, "recessão": -0.9, "derrumba": -1.0,
}

NEGACAO = re.compile(r"\b(not|no|never|without|sem|não|nao|nunca)\b", re.I)


def _texto_score(texto):
    t = (texto or "").lower()
    score = 0.0
    n = 0
    for termo, peso in list(POSITIVAS.items()) + list(NEGATIVAS.items()):
        for m in re.finditer(r"(?<![a-z])" + re.escape(termo) + r"(?![a-z])", t):
            peso_real = peso
            janela = t[max(0, m.start() - 25):m.start()]
            if NEGACAO.search(janela):
                peso_real = -peso_real * 0.8
            score += peso_real
            n += 1
    if "🚀" in t or "📈" in t:
        score += 0.5
    if "💀" in t or "📉" in t:
        score -= 0.5
    return score, n


def _get(url, timeout=12, headers=None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def reddit_posts(termo, limite=15):
    url = ("https://www.reddit.com/search.json?q=" + urllib.parse.quote(termo) +
           "&sort=new&t=day&limit=" + str(limite))
    try:
        raw = _get(url, headers={"User-Agent": UA})
        dados = json.loads(raw)
    except Exception:
        return []
    out = []
    for child in dados.get("data", {}).get("children", []):
        d = child.get("data", {})
        out.append({"texto": (d.get("title", "") or "") + " " + (d.get("selftext", "") or "")[:300],
                    "peso": max(1, d.get("score", 1)),
                    "fonte": "reddit",
                    "hora": d.get("created_utc", 0)})
    return out


def hn_posts(termo, limite=15):
    url = ("https://hn.algolia.com/api/v1/search_by_date?query=" + urllib.parse.quote(termo) +
           "&tags=story&hitsPerPage=" + str(limite))
    try:
        dados = json.loads(_get(url))
    except Exception:
        return []
    out = []
    for h in dados.get("hits", []):
        out.append({"texto": (h.get("title") or "") + " " + (h.get("story_text") or "")[:200],
                    "peso": max(1, h.get("points") or 1),
                    "fonte": "hn",
                    "hora": h.get("created_at_i", 0)})
    return out


def news_posts(termo, limite=10):
    url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(termo) + "&hl=en-US&gl=US&ceid=US:en"
    try:
        xml = _get(url)
    except Exception:
        return []
    out = []
    for titulo in re.findall(r"<title>(.*?)</title>", xml, re.S)[:limite + 1]:
        limpo = re.sub(r"<.*?>", "", titulo)
        limpo = re.sub(r"&amp;", "&", limpo)
        if limpo.strip():
            out.append({"texto": limpo, "peso": 1, "fonte": "news", "hora": 0})
    return out


def x_posts(termo, bearer=None, limite=25):
    if not bearer:
        return []
    url = ("https://api.x.com/2/tweets/search/recent?query=" + urllib.parse.quote(termo) +
           "&max_results=" + str(limite) + "&tweet.fields=created_at,public_metrics")
    try:
        raw = _get(url, headers={"Authorization": "Bearer " + bearer, "User-Agent": UA})
        dados = json.loads(raw)
    except Exception:
        return []
    out = []
    for t in dados.get("data", []):
        out.append({"texto": t.get("text", ""), "peso": 1, "fonte": "x", "hora": 0})
    return out


def coletar(termo, fontes, bearer_x=None):
    posts = []
    for fonte in fontes:
        if fonte == "reddit":
            posts += reddit_posts(termo)
        elif fonte == "hnews":
            posts += hn_posts(termo)
        elif fonte == "news":
            posts += news_posts(termo)
        elif fonte == "x":
            posts += x_posts(termo, bearer_x)
    return posts


def avaliar(posts, min_amostras=6, termos=None):
    if not posts:
        return {"n": 0, "score": 0.0, "z": 0.0, "p": None, "confianca": 0.0, "top": []}
    termos = [t.lower() for t in (termos or []) if len(t) > 3]
    pesos, scores = [], []
    detalhes = []
    for p in posts:
        texto = (p["texto"] or "").lower()
        if termos:
            hits = sum(1 for t in termos if t in texto)
            if hits == 0:
                continue
            s, n = _texto_score(p["texto"])
            peso = float(p.get("peso", 1)) * (1 + 0.5 * hits)
        else:
            s, n = _texto_score(p["texto"])
            peso = float(p.get("peso", 1))
        pesos.append(peso)
        scores.append(s)
        detalhes.append({"fonte": p.get("fonte"), "score": round(s, 2), "texto": p["texto"][:160]})
    if len(scores) < min_amostras:
        return {"n": len(scores), "score": 0.0, "z": 0.0, "p": None,
                "confianca": 0.0, "top": detalhes[:5]}
    media = sum(scores) / len(scores)
    variancia = sum((s - media) ** 2 for s in scores) / max(1, len(scores) - 1)
    desvio = variancia ** 0.5
    peso_medio = sum(pesos) / len(pesos)
    z = media * (1 + min(1.0, peso_medio / 10.0)) / (desvio + 0.6)
    confianca = min(1.0, len(scores) / 20.0) * min(1.0, abs(z) / 2.0)
    p = 0.5 + 0.5 * (z / (1 + abs(z)))
    p = max(0.03, min(0.97, p))
    detalhes.sort(key=lambda d: abs(d["score"]), reverse=True)
    return {"n": len(scores), "score": round(media, 3), "z": round(z, 3), "p": round(p, 4),
            "confianca": round(confianca, 3), "top": detalhes[:5]}
