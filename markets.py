import json
import urllib.request

CLOB = "https://clob.polymarket.com"
GAMMA = "https://gamma-api.polymarket.com"
UA = "Mozilla/5.0 (compatible; AgentePolymarket/1.0)"


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _paginas(endpoint, params, max_paginas=4):
    cursor = "MA=="
    itens = []
    for _ in range(max_paginas):
        q = dict(params)
        q["next_cursor"] = cursor
        url = endpoint + "?" + "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in q.items())
        dados = _get(url)
        itens += dados.get("data", [])
        cursor = dados.get("next_cursor", "")
        if not cursor or cursor == "MA==" or not dados.get("data"):
            break
    return itens


def listar_mercados(ativo=True, limite=100):
    params = {"closed": "false", "active": str(ativo).lower(),
              "order": "volume24hr", "ascending": "false", "limit": 100}
    brutos = _paginas(f"{CLOB}/sampling-markets", params, max_paginas=4)
    ativos = [m for m in brutos if m.get("accepting_orders") and not m.get("closed")]
    brutos += _paginas(f"{CLOB}/markets", params, max_paginas=2)
    vistos = set()
    saida = []
    for m in brutos + ativos:
        cid = m.get("condition_id")
        if cid in vistos:
            continue
        vistos.add(cid)
        saida.append(m)
    return saida[:limite]


def mercados_gamma(limite=40, min_liquidez=0):
    try:
        dados = _get(f"{GAMMA}/markets?closed=false&active=true&limit=100&order=volume24hr&ascending=false")
    except Exception:
        return []
    saida = []
    for g in dados:
        try:
            liq = float(g.get("liquidity") or 0)
        except Exception:
            liq = 0
        if liq < min_liquidez:
            continue
        saida.append({
            "condition_id": g.get("conditionId"),
            "question": g.get("question", ""),
            "slug": g.get("slug"),
            "clob_token_ids": g.get("clobTokenIds"),
            "outcomes": g.get("outcomes"),
            "tokens": _tokens_gamma(g),
            "accepting_orders": True,
            "active": True,
            "closed": False,
            "minimum_order_size": 5,
            "minimum_tick_size": 0.01,
            "end_date": g.get("endDate"),
            "liquidez": liq,
            "volume24hr": float(g.get("volume24hr") or 0),
            "tags": g.get("tags") or [],
            "categoria": g.get("category") or "",
            "sports": g.get("sportsMarketType"),
            "best_bid": g.get("bestBid"),
            "best_ask": g.get("bestAsk"),
            "order_min_size": g.get("orderMinSize"),
        })
        if len(saida) >= limite:
            break
    return saida


def _tokens_gamma(g):
    ids = g.get("clobTokenIds")
    outs = g.get("outcomes")
    tokens = []
    if isinstance(ids, str):
        try:
            ids = json.loads(ids)
        except Exception:
            ids = []
    if isinstance(outs, str):
        try:
            outs = json.loads(outs)
        except Exception:
            outs = []
    if not isinstance(ids, list):
        ids = []
    if not isinstance(outs, list):
        outs = []
    for i, tid in enumerate(ids):
        outcome = outs[i] if i < len(outs) else str(i)
        tokens.append({"token_id": str(tid), "outcome": str(outcome)})
    return tokens


def detalhes_gamma(slug):
    try:
        dados = _get(f"{GAMMA}/markets?slug={slug}")
        return dados[0] if dados else None
    except Exception:
        return None


def livro(token_id):
    try:
        return _get(f"{CLOB}/book?token_id={token_id}")
    except Exception:
        return {}


def precos(token_ids):
    if not token_ids:
        return {}
    try:
        return _get(f"{CLOB}/prices?token_ids={','.join(token_ids)}")
    except Exception:
        return {}


def midpoints(token_ids):
    if not token_ids:
        return {}
    try:
        return _get(f"{CLOB}/midpoints?token_ids={','.join(token_ids)}")
    except Exception:
        return {}


def melhor_livro(livro_raw, lado):
    linhas = livro_raw.get("bids" if lado == "buy" else "asks", [])
    if not linhas:
        return None
    melhor = max(linhas, key=lambda l: float(l["price"])) if lado == "buy" else min(
        linhas, key=lambda l: float(l["price"]))
    return {"preco": float(melhor["price"]), "tamanho": float(melhor["size"])}


def token_para_lado(market, outcome):
    for t in market.get("tokens", []):
        if (t.get("outcome") or "").lower() == outcome.lower():
            return t.get("token_id")
    return None
