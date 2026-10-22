import json
import os
import re
import sys
import time
import datetime

import kelly
import markets
import risco
import sentimento
import sentimento_llm
import dashboard
import levamento
from vida import Vida

RAIZ = os.path.dirname(os.path.abspath(__file__))


def log(msg):
    linha = f"[{datetime.datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(linha, flush=True)
    try:
        with open(os.path.join(RAIZ, "agente.log"), "a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except Exception:
        pass


def carregar_config():
    caminho = os.path.join(RAIZ, "config.json")
    with open(caminho, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def termos_de_busca(pergunta):
    limpo = re.sub(r"[^a-zA-Z0-9\s$%.]", " ", pergunta)
    limpo = re.sub(r"\s+", " ", limpo)
    stop = {"will", "be", "the", "a", "an", "in", "on", "by", "before", "after", "at", "of",
            "to", "for", "and", "or", "than", "any", "this", "that", "there", "it", "is",
            "are", "who", "what", "when", "how", "does", "do", "have", "has", "no", "yes",
            "up", "down", "out", "over", "under", "above", "below", "market", "vs", "new",
            "get", "gets", "make", "makes", "hit", "hits", "next", "last", "first", "second"}
    palavras = [p.strip().lower() for p in limpo.split(" ") if len(p) > 3 and p.lower() not in stop]
    palavras = [p for p in palavras if not p.isdigit()]
    uniq = []
    for p in palavras:
        if p not in uniq:
            uniq.append(p)
    uniq.sort(key=len, reverse=True)
    return uniq[:3] if uniq else [limpo.strip()[:40]]


def estimar_sentimento(pergunta, cfg):
    bearer = os.environ.get("X_BEARER_TOKEN")
    fontes = list(cfg.get("fontesSentimento", ["reddit", "hnews", "news"]))
    if cfg.get("usarX") and bearer:
        fontes.append("x")
    termos = termos_de_busca(pergunta)
    posts = []
    for termo in termos:
        posts += sentimento.coletar(termo, fontes, bearer)
    lex = sentimento.avaliar(posts, cfg.get("minAmostrasSentimento", 6), termos)
    if cfg.get("usarLLM"):
        llm = sentimento_llm.avaliar_llm(pergunta, posts)
        if llm:
            lex = dict(lex)
            lex["p"] = llm["p"]
            lex["confianca"] = llm["confianca"]
            lex["llm"] = llm
            lex["z"] = (llm["p"] - 0.5) * 4
    return lex


def simbolo_para_mercado(market):
    tokens = market.get("tokens", [])
    if not tokens:
        return None
    return tokens[0]


def valor_de_mercado(token_id, books_cache):
    if token_id in books_cache:
        return books_cache[token_id]
    lv = markets.livro(token_id)
    ask = markets.melhor_livro(lv, "sell")
    bid = markets.melhor_livro(lv, "buy")
    books_cache[token_id] = {"ask": ask, "bid": bid, "raw": lv}
    return books_cache[token_id]


def operar_paper(cfg, vida, sinal):
    preco = sinal["preco"]
    shares = sinal["shares"]
    custo = round(preco * shares, 6)
    vida.posicoes.append({
        "mercado": sinal["pergunta"],
        "slug": sinal.get("slug"),
        "token_id": sinal.get("token_id"),
        "lado": sinal["lado"],
        "shares": shares,
        "preco": preco,
        "custo": custo,
        "p_estimada": sinal["p_estimada"],
        "edge": sinal["edge"],
        "aberta_em": datetime.datetime.now().isoformat(timespec="seconds"),
        "status": "aberta",
    })
    vida.estado["saldo"] = round(vida.saldo() - custo, 6)
    vida.registrar_operacao(-custo)
    vida.salvar()
    levamento.registrar_operacao(cfg, {
        "mercado": sinal["pergunta"], "lado": sinal["lado"], "shares": shares,
        "preco": preco, "custo": custo, "p_estimada": sinal["p_estimada"],
        "edge": sinal["edge"], "token_id": sinal.get("token_id"), "slug": sinal.get("slug"),
        "modo": "paper",
    })
    log(f"[PAPER] compra {sinal['lado']} {shares} @ {preco:.3f} - {sinal['pergunta'][:60]}")


def eh_categoria_interessante(m, cfg):
    if m.get("sports"):
        return False
    tags = [str(t).lower() for t in (m.get("tags") or [])]
    cat = str(m.get("categoria") or "").lower()
    bloqueadas = [t.lower() for t in cfg.get("categoriasExcluidas", ["sports", "nba", "nfl", "mlb", "nhl", "soccer", "tennis"])]
    for t in tags + [cat]:
        if any(b == t or b in t for b in bloqueadas):
            return False
    permitidas = [p.lower() for p in cfg.get("categoriasPermitidas", [])]
    if permitidas:
        return any(p in cat or any(p in t for t in tags) for p in permitidas)
    return True


def operar_live(cfg, vida, sinal):
    pk = os.environ.get("POLY_PRIVATE_KEY")
    funder = os.environ.get("POLY_FUNDER") or ""
    if not pk:
        log("modo live sem POLY_PRIVATE_KEY - operacao ignorada")
        return False
    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import OrderArgs
        from py_clob_client.order_builder.constants import BUY
    except Exception as e:
        log(f"py-clob-client indisponivel ({e}) - use: pip install py-clob-client")
        return False
    try:
        client = ClobClient("https://clob.polymarket.com", key=pk, chain_id=137,
                            funder=funder, signature_type=2)
        creds = client.create_or_derive_api_creds()
        client.set_api_creds(creds)
        resp = client.create_and_post_order(OrderArgs(
            token_id=sinal["token_id"], price=sinal["preco"], size=sinal["shares"], side=BUY))
        log(f"[LIVE] ordem {sinal['lado']} {sinal['shares']} @ {sinal['preco']:.3f} -> {resp}")
        vida.estado["saldo"] = round(vida.saldo() - sinal["preco"] * sinal["shares"], 6)
        vida.registrar_operacao(-sinal["preco"] * sinal["shares"])
        vida.salvar()
        return True
    except Exception as e:
        log(f"falha ao enviar ordem: {e}")
        return False


def main():
    cfg = carregar_config()
    vida = Vida(cfg)
    gerenciador = risco.Gerenciador(cfg, vida)
    log(f"agente iniciado | modo={cfg.get('mode')} | saldo=${vida.saldo():.4f} | viva={vida.viva}")

    if not vida.viva:
        if vida.talvez_reviver():
            log("agente revivido: saldo suficiente apos recarga")
        else:
            log(f"agente morto: {vida.estado.get('motivo_morte')} - recarregue a carteira para reviver")
            return 0

    bearer = os.environ.get("X_BEARER_TOKEN")
    if cfg.get("usarX") and not bearer:
        log("X_BEARER_TOKEN ausente - fonte X desativada")

    cap = vida.saldo() * cfg.get("riscoMaximoOperacao", 0.06)
    log(f"teto por operacao (6% do saldo) = ${cap:.4f} | lote minimo Polymarket = "
        f"{cfg.get('minShares', 5)} acoes (custo minimo US$0.05..US$4.50 conforme o preco)")
    if cap < 0.05:
        log("ATENCAO: com este saldo o teto de 6% fica abaixo do custo do lote minimo - "
            "o agente fica vivo, mas nao pode operar sem aumentar a banca")

    while True:
        if not vida.viva:
            log("agente morreu - encerrando loop")
            break

        try:
            brutos = markets.mercados_gamma(limite=cfg.get("maxMercadosPorCiclo", 12) * 2,
                                            min_liquidez=cfg.get("minLiquidez", 5000))
            if not brutos:
                brutos = markets.listar_mercados(limite=cfg.get("maxMercadosPorCiclo", 12))
        except Exception as e:
            log(f"erro ao listar mercados: {e}")
            time.sleep(cfg.get("cicloSegundos", 120))
            continue

        brutos = [m for m in brutos if m.get("accepting_orders") and m.get("active")]
        brutos = [m for m in brutos if eh_categoria_interessante(m, cfg)]
        brutos = brutos[:cfg.get("maxMercadosPorCiclo", 12)]

        books_cache = {}
        sinais = []
        for m in brutos:
            pergunta = m.get("question", "")
            tokens = m.get("tokens", [])
            if not tokens:
                continue
            for t in tokens:
                outcome = (t.get("outcome") or "").lower()
                if outcome not in ("yes", "no"):
                    continue
                token_id = t.get("token_id")
                if not token_id:
                    continue
                lv = valor_de_mercado(token_id, books_cache)
                ask = lv.get("ask")
                preco = None
                if ask:
                    preco = ask["preco"]
                elif outcome == "yes" and m.get("best_ask"):
                    preco = float(m["best_ask"])
                elif outcome == "no" and m.get("best_bid"):
                    preco = round(1.0 - float(m["best_bid"]), 4)
                if preco is None:
                    continue
                if preco <= 0.02 or preco >= 0.98:
                    continue
                if ask and ask.get("tamanho", 0) < cfg.get("minShares", 5):
                    continue

                sent = estimar_sentimento(pergunta, cfg)
                if cfg.get("debug"):
                    log(f"  [{outcome.upper()}] {pergunta[:52]} | preco={preco:.3f} | "
                        f"n={sent['n']} p={sent['p']} conf={sent.get('confianca')} "
                        f"z={sent.get('z')}")
                if sent["p"] is None or sent["confianca"] < cfg.get("confiancaMinima", 0.35):
                    continue

                p = sent["p"]
                p_mercado = preco if outcome == "yes" else 1 - preco
                edge = p - p_mercado
                if abs(edge) < cfg.get("edgeMinimo", 0.08):
                    continue

                lado = "YES" if edge > 0 else "NO"
                preco_efetivo = preco if lado == "YES" else 1 - preco
                p_efetiva = p if lado == "YES" else 1 - p
                shares, risco_usado, kf = kelly.tamanho_posicao(
                    vida.saldo(), p_efetiva, preco_efetivo,
                    cfg.get("kellyFracao", 0.25), cfg.get("riscoMaximoOperacao", 0.06),
                    cfg.get("minShares", 5))
                if shares <= 0:
                    continue
                pode, motivo = gerenciador.pode_operar(preco_efetivo * shares)
                if not pode:
                    log(f"bloqueado: {motivo}")
                    continue
                sinais.append({
                    "pergunta": pergunta, "slug": m.get("slug"), "token_id": token_id,
                    "lado": lado, "preco": preco_efetivo, "p_estimada": p_efetiva,
                    "p_mercado": p_mercado, "edge": edge, "shares": shares,
                    "risco": risco_usado, "kelly": kf, "sent": sent,
                })

        for sinal in sinais:
            if cfg.get("mode") == "live":
                operar_live(cfg, vida, sinal)
            else:
                operar_paper(cfg, vida, sinal)

        vida.heartbeat()
        gerenciador.atualizar_pnl()
        vida.salvar()
        try:
            dashboard.gerar(cfg)
            levamento.exportar_extrato(cfg, cfg.get("caminhoExtratoPagina", "docs/extrato.csv"))
            r = levamento.resumo(cfg)
            log(f"ledger: {r['operacoes']} operacoes | pnl_total=${r['pnl_total']:+.4f} "
                f"| saldo=${r['saldo']:.4f}")
        except Exception as e:
            log(f"erro ao gerar dashboard/ledger: {e}")
        log(f"ciclo: {len(brutos)} mercados, {len(sinais)} sinais | saldo=${vida.saldo():.4f} "
            f"pnl=${vida.pnl_operacoes():+.4f} dd={vida.drawdown()*100:.1f}%")
        gerenciador.checar_morte()
        vida.salvar()

        if "--once" in sys.argv:
            break
        time.sleep(cfg.get("cicloSegundos", 120))

    return 0


if __name__ == "__main__":
    sys.exit(main())
