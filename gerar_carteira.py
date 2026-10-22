import json
import os
import secrets
import time

ARQUIVO = "carteira_agente.json"


def gerar():
    try:
        from eth_account import Account
    except Exception:
        print("instale: pip install eth-account")
        return None
    conta = Account.create(secrets.token_bytes(32))
    dados = {
        "endereco": conta.address,
        "chave_privada": conta.key.hex(),
        "criada_em": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "rede": "Polygon (chain 137)",
        "aviso": "CHAVE PRIVADA - guarde em local seguro. Esta e a 'conta do agente'. "
                 "Deposite USDC aqui para alimentar a vida do agente.",
    }
    with open(ARQUIVO, "w", encoding="utf-8") as f:
        json.dump(dados, f, indent=2, ensure_ascii=False)
    return dados


if __name__ == "__main__":
    d = gerar()
    if d:
        print("carteira do agente criada")
        print("endereco (Polygon):", d["endereco"])
        print("chave privada salva em", os.path.abspath(ARQUIVO), "- nao versionar esse arquivo")
