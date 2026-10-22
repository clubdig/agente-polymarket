import datetime

import markets


class Gerenciador:
    def __init__(self, cfg, vida):
        self.cfg = cfg
        self.vida = vida
        self.dia = datetime.date.today().isoformat()
        self.pnl_dia = 0.0

    def pode_operar(self, custo):
        pode, motivo = self.vida.pode_operar(custo)
        if not pode:
            return False, motivo
        if self.pnl_dia <= -self.cfg.get("perdaDiariaMaxima", 0.10) * max(self.vida.pico(), 0.01):
            return False, "perda diaria maxima atingida"
        exposicao = sum(p.get("custo", 0) for p in self.vida.posicoes if p.get("status") == "aberta")
        if (exposicao + custo) > self.cfg.get("exposicaoMaxima", 0.30) * self.vida.pico():
            return False, "exposicao maxima atingida"
        return True, "ok"

    def atualizar_pnl(self):
        hoje = datetime.date.today().isoformat()
        if hoje != self.dia:
            self.dia = hoje
            self.pnl_dia = 0.0
        pnl_total = 0.0
        for p in self.vida.posicoes:
            if p.get("status") != "aberta":
                continue
            token_id = p.get("token_id")
            if not token_id:
                continue
            lv = markets.livro(token_id)
            lado = "sell" if p.get("lado") == "YES" else "buy"
            melhor = markets.melhor_livro(lv, lado)
            if not melhor:
                continue
            p["preco_atual"] = melhor["preco"]
            p["valor"] = round(melhor["preco"] * p["shares"], 6)
            p["pnl"] = round(p["valor"] - p["custo"], 6)
            pnl_total += p["pnl"]
        self.pnl_dia = pnl_total
        self.vida.estado["pnl"] = round(pnl_total, 6)
        self.vida.estado["exposicao"] = round(
            sum(p.get("custo", 0) for p in self.vida.posicoes if p.get("status") == "aberta"), 6)
        return pnl_total

    def checar_morte(self):
        cfg = self.cfg
        if not self.vida.viva:
            return
        if self.vida.saldo() < cfg.get("morteSeSaldoAbaixo", 0.10):
            self.vida.registrar_morte("saldo abaixo do minimo de sobrevivencia")
            return
        if self.vida.drawdown() >= cfg.get("drawdownMaximo", 0.40):
            self.vida.registrar_morte("drawdown maximo atingido")
            return
        if self.pnl_dia <= -cfg.get("perdaDiariaMaxima", 0.10) * max(self.vida.pico(), 0.01):
            self.vida.registrar_morte("perda diaria maxima atingida")
