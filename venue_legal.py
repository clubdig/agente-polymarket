import csv
import datetime
import json
import os
import time

import kelly
import venues


def _cache_chave(pergunta):
    return "|".join(sorted(pergunta.lower().split()[:6]))


def estimar_probabilidade(pergunta, cfg, cache_llm, contexto="", chamadas=None, vida=None):
    import sentimento
    import sentimento_llm

    bearer = os.environ.get("X_BEARER_TOKEN")
    fontes = list(cfg.get("fontesSentimento", ["reddit", "hnews", "news"]))
    if cfg.get("usarX") and bearer:
        fontes.append("x")
    termos = [t for t in _cache_chave(pergunta).split("|") if len(t) > 3]
    chave = _cache_chave(pergunta)
    ttl = float(cfg.get("cacheLLMMinutos", 360)) * 60
    if cache_llm and chave in cache_llm:
        entrada = cache_llm[chave]
        if time.time() - entrada.get("ts", 0) < ttl and entrada.get("resultado"):
            return entrada["resultado"]
    posts = []
    for termo in termos[:3]:
        posts += sentimento.coletar(termo, fontes, bearer)
    lex = sentimento.avaliar(posts, cfg.get("minAmostrasSentimento", 4), termos)
    if cfg.get("usarLLM"):
        if chamadas is not None:
            if chamadas["n"] >= int(cfg.get("maxChamadasLLM", 4)):
                return lex
            chamadas["n"] += 1
        if vida is not None:
            pode, _ = vida.llm_pode_chamar()
            if not pode:
                return lex
        llm = sentimento_llm.avaliar_llm(pergunta, posts, contexto=contexto,
                                       modelos=cfg.get("modelosLLM"))
        if llm and llm.get("erro") == "quota":
            if vida is not None:
                vida.llm_registrar_429()
            return lex
        if llm:
            if vida is not None:
                vida.llm_registrar_chamada()
            lex = dict(lex)
            lex["p"] = llm["p"]
            lex["confianca"] = llm["confianca"]
            lex["llm"] = llm
    if cache_llm is not None:
        cache_llm[chave] = {"ts": time.time(), "resultado": lex}
    return lex


def ciclo_legal(cfg, cache_llm, chamadas=None, vida=None):
    """Venue legal: Kalshi (distribuido no Brasil pela XP International) - tickets manuais."""
    if not cfg.get("usarVenueLegal", True):
        return {"tickets": [], "candidatos": 0}
    try:
        candidatos = venues.kalshi_candidatos(
            max_dias=int(cfg.get("venueMaxDias", 5000)),
            limite_eventos=int(cfg.get("venueMaxEventos", 40)))
    except Exception as e:
        return {"tickets": [], "candidatos": 0, "erro": str(e)}
    if not candidatos:
        return {"tickets": [], "candidatos": 0}

    foco = venues.foco_resumo_texto()
    contexto = ("Consenso oficial do Banco Central (Focus, " + foco + ") e dados de mercado "
                "para eventos economicos dos EUA. Use como referencia de mercado.") if foco else ""
    banca = float(cfg.get("bancadaLegalBRL", 500.0))
    cambio = float(cfg.get("dolarBRL", 5.0))
    max_analises = int(cfg.get("venueMaxAnalises", 8))
    tickets = []
    analisados = 0
    for c in candidatos:
        if analisados >= max_analises:
            break
        if c.get("preco") is None:
            continue
        analisados += 1
        sent = estimar_probabilidade(c["pergunta"], cfg, cache_llm, contexto, chamadas, vida)
        if not sent.get("p") or sent.get("confianca", 0) < cfg.get("confiancaMinima", 0.35):
            continue
        p = sent["p"]
        preco = c["preco"]
        edge = p - preco
        if abs(edge) < cfg.get("edgeMinimo", 0.08):
            continue
        lado = "SIM" if edge > 0 else "NAO"
        preco_pago = preco if edge > 0 else round(1 - preco, 4)
        p_paga = p if edge > 0 else round(1 - p, 4)
        banca_usd = banca / cambio
        qtd, risco_usd, kf = kelly.tamanho_posicao(
            banca_usd, p_paga, preco_pago, cfg.get("kellyFracao", 0.25),
            cfg.get("riscoMaximoOperacao", 0.06), cfg.get("minShares", 1))
        custo_usd = qtd * preco_pago
        tickets.append({
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "venue": "Kalshi via XP International",
            "ticker": c["ticker"],
            "evento": c["titulo"],
            "desfecho": c["rotulo"],
            "lado": lado,
            "preco_prob": preco,
            "preco_pago": preco_pago,
            "p_estimada": p_paga,
            "edge": round(edge, 4),
            "qtd": qtd,
            "custo_usd": round(custo_usd, 2),
            "custo_brl": round(custo_usd * cambio, 2),
            "risco_usd": round(custo_usd, 2),
            "risco_brl": round(custo_usd * cambio, 2),
            "kelly": round(kf, 3),
            "fecha": c["fecha"],
            "liquidez": c["liquidez"],
            "motivo": (sent.get("llm") or {}).get("motivo", ""),
            "modelo": (sent.get("llm") or {}).get("modelo", "lexico"),
            "status": "PAPER - executar manualmente na Clear/XP",
        })
    gravar_tickets(cfg, tickets)
    return {"tickets": tickets, "candidatos": len(candidatos), "analisados": analisados,
            "foco": foco}


def gravar_tickets(cfg, tickets):
    caminho = cfg.get("caminhoTickets", "tickets.csv")
    pasta = os.path.dirname(caminho)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    novos = [t for t in tickets if t.get("status", "").startswith("PAPER")]
    if not novos:
        return caminho
    existe = os.path.exists(caminho)
    campos = ["ts", "venue", "ticker", "evento", "desfecho", "lado", "preco_prob",
              "p_estimada", "edge", "qtd", "custo_usd", "custo_brl", "risco_brl",
              "fecha", "motivo", "status"]
    with open(caminho, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        if not existe:
            w.writeheader()
        for t in novos:
            w.writerow(t)
    return caminho
