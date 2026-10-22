import json
import os
import urllib.request

API = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
UA = "Mozilla/5.0 (compatible; AgentePolymarket/1.0)"


def _pedido(prompt, api_key, timeout=30):
    url = f"{API}?key={api_key}"
    corpo = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 400},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(corpo).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": UA},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def avaliar_llm(pergunta, posts, api_key=None, max_posts=25):
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key or not posts:
        return None
    linhas = []
    for p in posts[:max_posts]:
        texto = (p.get("texto") or "").replace("\n", " ")[:220]
        linhas.append(f"- [{p.get('fonte')}] {texto}")
    if not linhas:
        return None
    prompt = (
        "Voce e um analista de mercados de previsao. Abaixo esta a pergunta de um mercado binario "
        "(YES/NO) e noticias/tweets recentes.\n\n"
        f"PERGUNTA: {pergunta}\n\n"
        "NOTICIAS/TWEETS:\n" + "\n".join(linhas) + "\n\n"
        "Responda SOMENTE com JSON valido, sem texto extra, neste formato exato:\n"
        '{"p": <probabilidade de YES entre 0 e 1, com 2 casas>, '
        '"forca": "fraca|media|forte", "motivo": "<maximo 25 palavras>"}\n\n'
        "Regras: use apenas o que esta nas noticias; se as noticias nao.allow informarem o resultado, "
        "estime pela Tendencia; nao invente fatos. Se as noticias forem irrelevantes, use p=0.5 e forca=fraca."
    )
    try:
        dados = _pedido(prompt, api_key)
        texto = dados["candidates"][0]["content"]["parts"][0]["text"].strip()
        texto = texto.replace("```json", "").replace("```", "").strip()
        inicio = texto.find("{")
        fim = texto.rfind("}")
        if inicio < 0 or fim < 0:
            return None
        obj = json.loads(texto[inicio:fim + 1])
        p = float(obj.get("p", 0.5))
        p = max(0.02, min(0.98, p))
        forca = str(obj.get("forca", "fraca")).lower()
        confianca = {"fraca": 0.25, "media": 0.5, "forte": 0.8}.get(forca, 0.3)
        return {"p": round(p, 4), "confianca": confianca, "forca": forca,
                "motivo": str(obj.get("motivo", ""))[:200], "n": len(posts[:max_posts])}
    except Exception:
        return None
