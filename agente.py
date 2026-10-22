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


def estimar_sentimento(pergunta, cfg, cache=None, chamadas=None):
    bearer = os.environ.get("X_BEARER_TOKEN")
    fontes = list(cfg.get("fontesSentimento", ["reddit", "hnews", "news"]))
    if cfg.get("usarX") and bearer:
        fontes.append("x")
    termos = termos_de_busca(pergunta)
    chave = "|".join(sorted(termos))
    ttl = float(cfg.get("cacheLLMMinutos", 360)) * 60
    if cache is not None and chave in cache:
        entrada = cache[chave]
        if time.time() - entrada.get("ts", 0) < ttl and entrada.get("resultado"):
            return entrada["resultado"]
    posts = []
    for termo in termos:
        posts += sentimento.coletar(termo, fontes, bearer)
    lex = sentimento.avaliar(posts, cfg.get("minAmostrasSentimento", 6), termos)
    if cfg.get("usarLLM"):
        teto = int(cfg.get("maxChamadasLLM", 4))
        if chamadas is not None and chamadas["n"] >= teto:
            return lex
        if chamadas is not None:
            chamadas["n"] += 1
        llm = sentimento_llm.avaliar_llm(pergunta, posts, modelos=cfg.get("modelosLLM"))
        if llm:
            lex = dict(lex)
            lex["p"] = llm["p"]
            lex["confianca"] = llm["confianca"]
            lex["llm"] = llm
            lex["z"] = (llm["p"] - 0.5) * 4
        if cache is not None:
            cache[chave] = {"ts": time.time(), "resultado": lex}
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


def carregar_env():
    caminho = os.path.join(RAIZ, ".env")
    if not os.path.exists(caminho):
        return
    with open(caminho, "r", encoding="utf-8-sig") as f:
        for linha in f:
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            chave, valor = linha.split("=", 1)
            os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


def cache_llm_carregar(caminho):
    if not os.path.exists(caminho):
        return {}
    try:
        with open(caminho, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


def cache_llm_salvar(caminho, cache):
    pasta = os.path.dirname(caminho)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def registrar_sinal(cfg, sinal, executado=False, shares=0):
    caminho = cfg.get("caminhoSinais", "sinais.jsonl")
    pasta = os.path.dirname(caminho)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    janela = float(cfg.get("janelaDedupeSinais", 720)) * 60
    if os.path.exists(caminho):
        try:
            with open(caminho, "r", encoding="utf-8-sig") as f:
                for linha in f:
                    linha = linha.strip()
                    if not linha:
                        continue
                    try:
                        antigo = json.loads(linha)
                    except Exception:
                        continue
                    if (antigo.get("token_id") == sinal.get("token_id")
                            and antigo.get("lado") == sinal.get("lado")):
                        try:
                            ts = datetime.datetime.fromisoformat(antigo.get("ts")).timestamp()
                        except Exception:
                            continue
                        if time.time() - ts < janela:
                            return antigo
        except Exception:
            pass
    registro = {
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "mercado": sinal["pergunta"],
        "slug": sinal.get("slug"),
        "token_id": sinal.get("token_id"),
        "lado": sinal["lado"],
        "preco": round(sinal["preco_token"], 4),
        "p_estimada": round(sinal["p_token"], 4),
        "p_mercado": round(sinal["p_mercado"], 4),
        "edge": round(sinal["edge_token"], 4),
        "preco_pago": round(sinal["preco_pago"], 4),
        "p_paga": round(sinal["p_paga"], 4),
        "modelo": (sinal.get("sent", {}).get("llm") or {}).get("modelo", "lexico"),
        "motivo": (sinal.get("sent", {}).get("llm") or {}).get("motivo", ""),
        "executado": executado,
        "shares": shares,
        "preco_depois": None,
    }
    with open(caminho, "a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")
    return registro


def marcar_executado(cfg, sinal, shares):
    caminho = cfg.get("caminhoSinais", "sinais.jsonl")
    if not os.path.exists(caminho):
        return
    linhas = []
    with open(caminho, "r", encoding="utf-8-sig") as f:
        for linha in f:
            linha = linha.strip()
            if linha:
                try:
                    linhas.append(json.loads(linha))
                except Exception:
                    pass
    for s in reversed(linhas):
        if s.get("token_id") == sinal.get("token_id") and s.get("lado") == sinal.get("lado"):
            s["executado"] = True
            s["shares"] = shares
            break
    with open(caminho, "w", encoding="utf-8") as f:
        for s in linhas:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")


def medir_sinais(cfg, horas_minimas=6):
    caminho = cfg.get("caminhoSinais", "sinais.jsonl")
    if not os.path.exists(caminho):
        return {}
    linhas = []
    with open(caminho, "r", encoding="utf-8-sig") as f:
        for linha in f:
            linha = linha.strip()
            if linha:
                try:
                    linhas.append(json.loads(linha))
                except Exception:
                    pass
    agora = time.time()
    medidos = 0
    acertos = 0
    for s in linhas:
        if s.get("preco_depois") is not None:
            ts = datetime.datetime.fromisoformat(s["ts"]).timestamp()
            if agora - ts < horas_minimas * 3600:
                continue
            delta = float(s["preco_depois"]) - float(s["preco"])
            s["delta"] = round(delta, 4)
            s["acerto"] = 1 if delta > 0 else 0
            medidos += 1
            acertos += s["acerto"]
        else:
            ts = datetime.datetime.fromisoformat(s["ts"]).timestamp()
            if agora - ts < horas_minimas * 3600:
                continue
            token_id = s.get("token_id")
            if not token_id:
                continue
            lv = markets.livro(token_id)
            lado = "sell" if s.get("lado") == "YES" else "buy"
            melhor = markets.melhor_livro(lv, lado)
            if not melhor:
                continue
            s["preco_depois"] = melhor["preco"]
    with open(caminho, "w", encoding="utf-8") as f:
        for s in linhas:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    return {"sinais": len(linhas), "medidos": medidos, "acertos": acertos,
            "acerto_pct": round(100 * acertos / medidos, 1) if medidos else None}


def main():
    cfg = carregar_config()
    carregar_env()
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
    cache_llm = cache_llm_carregar(cfg.get("caminhoCacheLLM", "cache_llm.json"))

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
        chamadas = {"n": 0}
        for m in brutos:
            pergunta = m.get("question", "")
            tokens = m.get("tokens", [])
            if not tokens:
                continue
            token_yes = next((t for t in tokens if (t.get("outcome") or "").lower() == "yes"), None)
            token_no = next((t for t in tokens if (t.get("outcome") or "").lower() == "no"), None)
            if not token_yes or not token_no:
                continue
            id_yes = token_yes.get("token_id")
            id_no = token_no.get("token_id")
            if not id_yes or not id_no:
                continue
            lv_yes = valor_de_mercado(id_yes, books_cache)
            lv_no = valor_de_mercado(id_no, books_cache)
            ask_yes = lv_yes.get("ask")
            ask_no = lv_no.get("ask")
            if not ask_yes and m.get("best_ask"):
                ask_yes = {"preco": float(m["best_ask"]), "tamanho": 999}
            if not ask_no and m.get("best_bid"):
                ask_no = {"preco": round(1.0 - float(m["best_bid"]), 4), "tamanho": 999}
            if not ask_yes or not ask_no:
                continue
            preco_yes = ask_yes["preco"]
            preco_no = ask_no["preco"]
            if not (0.02 < preco_yes < 0.98) or not (0.02 < preco_no < 0.98):
                continue
            if min(ask_yes.get("tamanho", 0), ask_no.get("tamanho", 0)) < cfg.get("minShares", 5):
                continue

            sent = estimar_sentimento(pergunta, cfg, cache_llm, chamadas)
            if cfg.get("debug"):
                log(f"  {pergunta[:52]} | YES={preco_yes:.3f} NO={preco_no:.3f} | "
                    f"n={sent['n']} p={sent['p']} conf={sent.get('confianca')} "
                    f"llm={(sent.get('llm') or {}).get('modelo', '-')}")
            if sent["p"] is None or sent["confianca"] < cfg.get("confiancaMinima", 0.35):
                continue

            p_yes = sent["p"]
            edge_yes = p_yes - preco_yes
            if abs(edge_yes) < cfg.get("edgeMinimo", 0.08):
                continue

            if edge_yes > 0:
                lado, token_id, preco_pago, p_paga = "YES", id_yes, preco_yes, p_yes
            else:
                lado, token_id, preco_pago, p_paga = "NO", id_no, preco_no, 1 - p_yes

            shares, risco_usado, kf = kelly.tamanho_posicao(
                vida.saldo(), p_paga, preco_pago,
                cfg.get("kellyFracao", 0.25), cfg.get("riscoMaximoOperacao", 0.06),
                cfg.get("minShares", 5))
            sinal = {
                "pergunta": pergunta, "slug": m.get("slug"), "token_id": token_id,
                "lado": lado, "preco": preco_pago, "p_estimada": p_paga,
                "p_mercado": preco_pago, "edge": edge_yes, "shares": shares,
                "risco": risco_usado, "kelly": kf, "sent": sent,
                "preco_token": preco_pago, "p_token": p_paga, "p_mercado": preco_pago,
                "edge_token": edge_yes, "preco_pago": preco_pago, "p_paga": p_paga,
            }
            registrar_sinal(cfg, sinal, executado=bool(shares), shares=shares)
            if shares <= 0:
                continue
            pode, motivo = gerenciador.pode_operar(preco_pago * shares)
            if not pode:
                log(f"bloqueado: {motivo}")
                continue
            sinais.append(sinal)

        for sinal in sinais:
            if cfg.get("mode") == "live":
                operar_live(cfg, vida, sinal)
            else:
                operar_paper(cfg, vida, sinal)
            marcar_executado(cfg, sinal, sinal.get("shares", 0))

        try:
            cache_llm_salvar(cfg.get("caminhoCacheLLM", "cache_llm.json"), cache_llm)
        except Exception as e:
            log(f"erro ao salvar cache llm: {e}")

        vida.heartbeat()
        gerenciador.atualizar_pnl()
        vida.salvar()
        try:
            dashboard.gerar(cfg)
            levamento.exportar_extrato(cfg, cfg.get("caminhoExtratoPagina", "docs/extrato.csv"))
            r = levamento.resumo(cfg)
            med = medir_sinais(cfg, int(cfg.get("medicaoHoras", 6)))
            if med.get("medidos"):
                log(f"medicao de sinais: {med['medidos']} avaliados, acerto {med['acerto_pct']}%")
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
