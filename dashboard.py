import datetime
import json
import os

from vida import Vida


def esc(s):
    return (str(s) if s is not None else "").replace("&", "&amp;").replace("<", "&lt;") \
        .replace(">", "&gt;").replace('"', "&quot;")


def _sinais(cfg):
    caminho = cfg.get("caminhoSinais", "sinais.jsonl")
    if not os.path.exists(caminho):
        return {"total": 0, "medidos": 0, "acertos": 0, "acerto_pct": None, "ultimos": []}
    linhas = []
    with open(caminho, "r", encoding="utf-8-sig") as f:
        for linha in f:
            linha = linha.strip()
            if linha:
                try:
                    linhas.append(json.loads(linha))
                except Exception:
                    pass
    medidos = [s for s in linhas if s.get("acerto") is not None]
    acertos = sum(1 for s in medidos if s.get("acerto"))
    return {"total": len(linhas), "medidos": len(medidos), "acertos": acertos,
            "acerto_pct": round(100 * acertos / len(medidos), 1) if medidos else None,
            "ultimos": linhas[-12:][::-1]}


def gerar(cfg):
    vida = Vida(cfg)
    e = vida.estado
    s = _sinais(cfg)
    linhas_sinais = ""
    for x in s["ultimos"]:
        marca = "&#10003;" if x.get("acerto") == 1 else ("&#10007;" if x.get("acerto") == 0 else "&#8226;")
        lado = "YES" if x.get("lado") == "YES" else "NO"
        linhas_sinais += f"""<tr>
<td>{esc(x.get('ts','')[5:16])}</td><td>{esc(str(x.get('mercado'))[:46])}</td>
<td>{lado}</td><td>{esc(x.get('preco'))}</td><td>{esc(x.get('p_estimada'))}</td>
<td class="pos">{esc(x.get('edge'))}</td><td>{marca} {esc(x.get('delta',''))}</td></tr>"""
    linhas_pos = ""
    for p in vida.posicoes:
        if p.get("status") != "aberta":
            continue
        linhas_pos += f"""<tr>
<td>{esc(p.get('mercado'))}</td><td>{esc(p.get('lado'))}</td><td>{esc(p.get('shares'))}</td>
<td>{esc(p.get('preco'))}</td><td>{esc(p.get('preco_atual', '-'))}</td>
<td class="{'pos' if (p.get('pnl') or 0) >= 0 else 'neg'}">{esc(p.get('pnl', 0))}</td>
<td><a href="https://polymarket.com/event/{esc(p.get('slug'))}" target="_blank">abrir</a></td></tr>"""

    html = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="30">
<title>Agente Polymarket - painel</title>
<style>
body{{font-family:system-ui,sans-serif;background:#0b1220;color:#e2e8f0;margin:0;padding:24px}}
.wrap{{max-width:1000px;margin:0 auto}}
h1{{font-size:20px;margin:0 0 4px}}
.vivo{{display:inline-block;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:700}}
.viva{{background:#14532d;color:#86efac}} .morta{{background:#7f1d1d;color:#fca5a5}}
.cards{{display:flex;gap:12px;flex-wrap:wrap;margin:18px 0}}
.card{{background:#111c2e;border:1px solid #1f2b40;border-radius:10px;padding:12px 16px;min-width:150px}}
.card .k{{font-size:12px;color:#94a3b8;text-transform:uppercase}}
.card .v{{font-size:20px;font-weight:700;margin-top:4px}}
table{{width:100%;border-collapse:collapse;font-size:13px;margin-top:10px}}
th,td{{text-align:left;padding:7px 8px;border-bottom:1px solid #1f2b40}}
th{{color:#94a3b8;font-weight:600}}
.pos{{color:#4ade80}} .neg{{color:#f87171}}
.mono{{font-family:ui-monospace,monospace;font-size:12px;color:#94a3b8}}
</style></head><body><div class="wrap">
<h1>Agente Polymarket <span class="vivo {'viva' if vida.viva else 'morta'}">{'VIVO' if vida.viva else 'MORTO'}</span></h1>
<div class="mono">nascimento {esc(e.get('nascimento'))} | ultimo heartbeat {esc(e.get('ultimo_heartbeat'))} | modo {esc(cfg.get('mode'))}</div>
<div class="cards">
<div class="card"><div class="k">Saldo</div><div class="v">$ {esc(round(e.get('saldo',0),4))}</div></div>
<div class="card"><div class="k">PnL</div><div class="v pos">$ {esc(round(e.get('pnl',0),4))}</div></div>
<div class="card"><div class="k">Operacoes</div><div class="v">{esc(e.get('operacoes',0))}</div></div>
<div class="card"><div class="k">Vitorias/Derrotas</div><div class="v">{esc(e.get('vitorias',0))}/{esc(e.get('derrotas',0))}</div></div>
<div class="card"><div class="k">Drawdown</div><div class="v">{esc(round(vida.drawdown()*100,2))}%</div></div>
<div class="card"><div class="k">Pico</div><div class="v">$ {esc(round(e.get('pico',0),4))}</div></div>
<div class="card"><div class="k">Sinais (edge>8%)</div><div class="v">{esc(s['total'])}</div></div>
<div class="card"><div class="k">Acerto medido</div><div class="v">{esc(s['acerto_pct']) if s['acerto_pct'] is not None else '-'}{'%' if s['acerto_pct'] is not None else ''}</div></div>
</div>
<h2 style="font-size:15px">Sinais detectados (edge &gt; 8%) e medicao de direcao</h2>
<table><tr><th>quando</th><th>Mercado</th><th>Lado</th><th>Preco</th><th>p estimada</th><th>Edge</th><th>Depois</th></tr>
{linhas_sinais or '<tr><td colspan="7">nenhum sinal com edge acima de 8%</td></tr>'}
</table>
<h2 style="font-size:15px;margin-top:24px">Posicoes abertas</h2>
<table><tr><th>Mercado</th><th>Lado</th><th>Shares</th><th>Entrada</th><th>Atual</th><th>PnL</th><th></th></tr>
{linhas_pos or '<tr><td colspan="7">nenhuma posicao aberta</td></tr>'}
</table>
</div></body></html>"""
    caminho = cfg.get("caminhoDashboard", "dashboard.html")
    pasta = os.path.dirname(caminho)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(html)
    return caminho
