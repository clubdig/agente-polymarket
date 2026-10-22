import csv
import datetime
import json
import os

from vida import Vida

USDC_POLYGON = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"


def caminho_operacoes(cfg):
    return cfg.get("caminhoOperacoes", "operacoes.json")


def carregar_operacoes(cfg):
    caminho = caminho_operacoes(cfg)
    if not os.path.exists(caminho):
        return []
    try:
        with open(caminho, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return []


def registrar_operacao(cfg, entrada):
    caminho = caminho_operacoes(cfg)
    ops = carregar_operacoes(cfg)
    entrada = dict(entrada)
    entrada.setdefault("ts", datetime.datetime.now().isoformat(timespec="seconds"))
    ops.append(entrada)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(ops, f, indent=2, ensure_ascii=False)
    return entrada


def resumo(cfg):
    vida = Vida(cfg)
    ops = carregar_operacoes(cfg)
    realizado = 0.0
    aberto = 0.0
    for p in vida.posicoes:
        if p.get("status") == "aberta":
            aberto += float(p.get("pnl") or 0.0)
        else:
            realizado += float(p.get("pnl") or 0.0)
    custo_total = sum(float(o.get("custo", 0)) for o in ops)
    return {
        "saldo": round(vida.saldo(), 4),
        "pnl_realizado": round(realizado, 4),
        "pnl_aberto": round(aberto, 4),
        "pnl_total": round(realizado + aberto, 4),
        "custo_investido": round(custo_total, 4),
        "operacoes": len(ops),
        "viva": vida.viva,
        "drawdown": round(vida.drawdown() * 100, 2),
    }


def exportar_extrato(cfg, caminho=None):
    ops = carregar_operacoes(cfg)
    vida = Vida(cfg)
    por_chave = {p.get("token_id") + "|" + str(p.get("preco")): p for p in vida.posicoes}
    destino = caminho or cfg.get("caminhoExtrato", "extrato.csv")
    pasta = os.path.dirname(destino)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    with open(destino, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "mercado", "lado", "shares", "preco_entrada", "custo",
                    "p_estimada", "edge", "preco_atual", "pnl", "status"])
        for o in ops:
            chave = o.get("token_id", "") + "|" + str(o.get("preco"))
            p = por_chave.get(chave, {})
            w.writerow([
                o.get("ts", ""), o.get("mercado", "")[:70], o.get("lado", ""),
                o.get("shares", ""), o.get("preco", ""), f'{o.get("custo", 0):.6f}',
                o.get("p_estimada", ""), f'{o.get("edge", 0):.4f}',
                p.get("preco_atual", ""), f'{p.get("pnl", "")}', p.get("status", "aberta"),
            ])
    return destino


def sacar(cfg, destino=None, minimo=None, dry_run=True):
    destino = destino or os.environ.get("POLY_DESTINO") or cfg.get("destinoSaque", "")
    minimo = minimo if minimo is not None else float(cfg.get("saqueMinimo", 5.0))
    r = resumo(cfg)
    disponivel = r["saldo"]
    if not destino:
        return {"ok": False, "motivo": "destino de saque nao configurado (POLY_DESTINO ou destinoSaque)"}
    if disponivel < minimo:
        return {"ok": False, "motivo": f"saldo {disponivel} abaixo do minimo de saque {minimo}"}
    if dry_run:
        return {"ok": True, "dry_run": True, "destino": destino, "valor": disponivel,
                "motivo": "simulacao: nenhum valor foi movimentado"}
    pk = os.environ.get("POLY_PRIVATE_KEY")
    if not pk:
        return {"ok": False, "motivo": "POLY_PRIVATE_KEY ausente"}
    try:
        from eth_account import Account
        from web3 import Web3
    except Exception as e:
        return {"ok": False, "motivo": f"web3/eth-account nao instalados: {e}"}
    try:
        w3 = Web3(Web3.HTTPProvider("https://polygon-rpc.com"))
        conta = Account.from_key(pk)
        contrato = w3.eth.contract(address=Web3.to_checksum_address(USDC_POLYGON),
                                    abi=[{"name": "transfer", "type": "function",
                                          "inputs": [{"name": "to", "type": "address"},
                                                     {"name": "amount", "type": "uint256"}],
                                          "outputs": [{"name": "", "type": "bool"}],
                                          "stateMutability": "nonpayable"}])
        valor = w3.to_wei(disponivel, 18)
        tx = contrato.functions.transfer(Web3.to_checksum_address(destino), valor) \
            .transact({"from": conta.address})
        return {"ok": True, "dry_run": False, "tx": tx.hex, "valor": disponivel, "destino": destino}
    except Exception as e:
        return {"ok": False, "motivo": str(e)}


if __name__ == "__main__":
    import sys
    with open("config.json", "r", encoding="utf-8-sig") as f:
        cfg_local = json.load(f)
    if "--sacar" in sys.argv:
        print(json.dumps(sacar(cfg_local, dry_run="--real" not in sys.argv), indent=2, ensure_ascii=False))
    else:
        print(json.dumps(resumo(cfg_local), indent=2, ensure_ascii=False))
        print("extrato:", exportar_extrato(cfg_local))
