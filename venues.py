import datetime
import json
import urllib.parse
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (compatible; AgentePolymarket/1.0)", "Accept": "application/json"}
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
FOCUS = "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata"

CATEGORIAS_ECONOMICAS = ["Economics", "Financials", "Companies", "Crypto"]

TERMOS_FINANCEIROS = [
    "fed", "fomc", "interest rate", "rate cut", "rate hike", "rates", "inflation",
    "cpi", "ppi", "gdp", "unemployment", "jobs", "payroll", "recession", "central bank",
    "ecb", "boj", "bcb", "copom", "selic", "ipca", "tariff", "recession", "treasury",
    "bond", "yield", "s&p", "nasdaq", "dow jones", "russell", "stock market", "stocks",
    "shares", "market cap", "ipo", "earnings", "revenue", "profit", "acquisition",
    "merger", "bankruptcy", "default", "bitcoin", "ethereum", "solana", "crypto",
    "gold", "silver", "oil", "crude", "brent", "natural gas", "dollar", "euro", "yen",
    "yuan", "real", "dxy", "fx", "currency", "ipo", "market", "economy", "economic",
]


def tem_referencia_financeira(texto):
    t = (texto or "").lower()
    return any(p in t for p in TERMOS_FINANCEIROS)


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def kalshi_eventos(limite=200, paginas=3, com_mercados=True):
    sufixo = "&with_nested_markets=true" if com_mercados else "&with_nested_markets=false"
    cursor = ""
    saida = []
    for _ in range(paginas):
        url = f"{KALSHI}/events?limit={limite}{sufixo}"
        if cursor:
            url += f"&cursor={cursor}"
        try:
            dados = _get(url)
        except Exception:
            break
        eventos = dados.get("events", [])
        if not eventos:
            break
        saida += eventos
        cursor = dados.get("cursor", "")
        if not cursor:
            break
    return saida


def titulo_eco(ev):
    return ev.get("title", "") or ev.get("event_ticker", "")


def kalshi_series_categorias():
    mapa = {}
    for cat in ("Economics", "Financials", "Companies", "Science and Technology", "Crypto"):
        try:
            dados = _get(f"{KALSHI}/series?category={urllib.parse.quote(cat)}&limit=1000")
        except Exception:
            continue
        for s in dados.get("series", []):
            mapa[s.get("ticker")] = cat
    return mapa


def kalshi_mercados_abertos(limite=600, paginas=6):
    saida = []
    cursor = ""
    for _ in range(paginas):
        url = f"{KALSHI}/markets?status=open&limit=100"
        if cursor:
            url += f"&cursor={cursor}"
        try:
            dados = _get(url)
        except Exception:
            break
        ms = dados.get("markets", [])
        if not ms:
            break
        saida += ms
        cursor = dados.get("cursor", "")
        if not cursor:
            break
        if len(saida) >= limite:
            break
    return saida


def kalshi_candidatos(categorias=None, min_liquidez=200, min_volume=2000,
                      max_dias=5000, limite_eventos=120, debug=False):
    categorias = categorias or CATEGORIAS_ECONOMICAS
    agora = datetime.datetime.now(datetime.timezone.utc)
    saida = []
    vistos = set()
    for ev in kalshi_eventos(limite=100, paginas=3, com_mercados=True):
        cat = ev.get("category") or ""
        if cat not in categorias:
            continue
        mercados = ev.get("markets") or []
        if not mercados:
            continue
        fecha = ev.get("close_time") or (mercados[0].get("close_time") if mercados else None)
        if fecha:
            try:
                dt = datetime.datetime.fromisoformat(fecha.replace("Z", "+00:00"))
                dias = (dt - agora).days
                if dias > max_dias or dt < agora:
                    continue
            except Exception:
                pass
        binario = len(mercados) == 2
        for m in mercados:
            chave = (m.get("ticker"), m.get("yes_sub_title"))
            if chave in vistos:
                continue
            try:
                ask = float(m.get("yes_ask_dollars") or 0)
                bid = float(m.get("yes_bid_dollars") or 0)
            except Exception:
                continue
            if ask <= 0.02 or ask >= 0.98:
                continue
            liq = float(m.get("open_interest_fp") or 0)
            vol = float(m.get("volume_fp") or 0)
            if liq < min_liquidez and vol < min_volume:
                continue
            vistos.add(chave)
            rotulo = (m.get("yes_sub_title") or "").strip()
            titulo = ev.get("title", "") or m.get("title", "")
            if not tem_referencia_financeira(f"{titulo} {rotulo}"):
                continue
            saida.append({
                "ticker": m.get("ticker"),
                "event_ticker": ev.get("event_ticker"),
                "titulo": titulo,
                "rotulo": rotulo,
                "categoria": cat,
                "preco": ask,
                "bid": bid,
                "liquidez": liq,
                "volume": vol,
                "fecha": fecha,
                "binario": binario,
                "preco_no": round(1 - ask, 4) if binario else None,
                "pergunta": (f"{titulo} -> {rotulo}" if rotulo and not binario else titulo),
            })
        if len(saida) >= limite_eventos * 3:
            break
    saida.sort(key=lambda c: (c.get("fecha") or "9999", -c.get("volume", 0)))
    return saida


def kalshi_preco(ticker):
    try:
        dados = _get(f"{KALSHI}/markets/{ticker}")
    except Exception:
        return None
    m = dados.get("market", dados)
    if not m:
        return None
    return {"ticker": m.get("ticker"), "yes_ask": float(m.get("yes_ask_dollars") or 0),
            "yes_bid": float(m.get("yes_bid_dollars") or 0),
            "close_time": m.get("close_time")}


def focus_selic():
    try:
        dados = _get(f"{FOCUS}/ExpectativasMercadoSelic?$top=300&$format=json")
    except Exception:
        return {}
    valores = dados.get("value", [])
    if not valores:
        return {}
    ultimo = max(v.get("Data", "") for v in valores)
    caminho = {}
    for v in valores:
        if v.get("Data") != ultimo:
            continue
        reuniao = v.get("Reuniao", "")
        if not reuniao or v.get("baseCalculo") != 0:
            continue
        try:
            caminho[reuniao] = float(v.get("Mediana"))
        except Exception:
            continue
    return {"data": ultimo, "caminho": caminho}


def focus_ipca_12m():
    try:
        dados = _get(f"{FOCUS}/ExpectativasMercadoInflacao12Meses?$top=200&$format=json")
    except Exception:
        return {}
    valores = dados.get("value", [])
    if not valores:
        return {}
    ultimo = max(v.get("Data", "") for v in valores)
    out = {}
    for v in valores:
        if v.get("Data") != ultimo or v.get("Indicador") != "IPCA":
            continue
        ref = v.get("DataReferencia") or v.get("Data")
        try:
            out[str(ref)] = float(v.get("Mediana"))
        except Exception:
            continue
    return {"data": ultimo, "medianas": out}


def foco_resumo_texto():
    sel = focus_selic()
    ipca = focus_ipca_12m()
    partes = []
    if sel.get("caminho"):
        itens = sorted(sel["caminho"].items())[:6]
        partes.append("Selic (medianas Focus em " + sel["data"] + "): " +
                      ", ".join(f"{k}={v}%" for k, v in itens))
    if ipca.get("medianas"):
        itens = sorted(ipca["medianas"].items())[-6:]
        partes.append("IPCA 12m (medianas Focus em " + ipca["data"] + "): " +
                      ", ".join(f"{k}={v}%" for k, v in itens))
    return "\n".join(partes)


if __name__ == "__main__":
    cs = kalshi_candidatos()
    print("candidatos:", len(cs))
    for c in cs[:12]:
        print(f"  {c['ticker'][:30]:30} ask={c['preco']:.3f} liq={c['liquidez']:.0f} "
              f"vol={c['volume']:.0f} | {c['titulo'][:50]} | {c['rotulo'][:20]}")
    print("\n--- Focus ---")
    print(foco_resumo_texto()[:900])

