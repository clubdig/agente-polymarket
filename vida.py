import json
import os
import time


def _agora():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class Vida:
    def __init__(self, cfg):
        self.cfg = cfg
        self.caminho = cfg.get("caminhoEstado", "state.json")
        self.estado = self._carregar()
        self.posicoes = self._carregar_posicoes()
        self.mortes = 0
        self.ultima_ordem = 0.0

    def _carregar(self):
        if os.path.exists(self.caminho):
            try:
                with open(self.caminho, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "nascimento": _agora(),
            "viva": True,
            "saldo_inicial": self.cfg.get("bancadaInicial", 0.95),
            "saldo": self.cfg.get("bancadaInicial", 0.95),
            "operacoes": 0,
            "vitorias": 0,
            "derrotas": 0,
            "pnl": 0.0,
            "melhor_sequencia": 0,
            "pior_sequencia": 0,
            "sequencia": 0,
            "pico": self.cfg.get("bancadaInicial", 0.95),
            "ultimo_heartbeat": _agora(),
            "motivo_morte": None,
        }

    def _carregar_posicoes(self):
        caminho = self.cfg.get("caminhoPosicoes", "posicoes.json")
        if os.path.exists(caminho):
            try:
                with open(caminho, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def salvar(self):
        self.estado["ultimo_heartbeat"] = _agora()
        with open(self.caminho, "w", encoding="utf-8") as f:
            json.dump(self.estado, f, indent=2, ensure_ascii=False)
        with open(self.cfg.get("caminhoPosicoes", "posicoes.json"), "w", encoding="utf-8") as f:
            json.dump(self.posicoes, f, indent=2, ensure_ascii=False)

    def heartbeat(self):
        self.estado["ultimo_heartbeat"] = _agora()

    @property
    def viva(self):
        return bool(self.estado.get("viva", True))

    def saldo(self):
        return float(self.estado.get("saldo", 0.0))

    def pico(self):
        return float(self.estado.get("pico", 0.0))

    def drawdown(self):
        pico = self.pico()
        if pico <= 0:
            return 1.0
        return max(0.0, 1.0 - self.saldo() / pico)

    def pnl_operacoes(self):
        return float(self.estado.get("pnl", 0.0))

    def registrar_operacao(self, resultado):
        self.estado["operacoes"] = int(self.estado.get("operacoes", 0)) + 1
        self.estado["pnl"] = round(self.pnl_operacoes() + resultado, 6)
        if resultado > 0:
            self.estado["vitorias"] = int(self.estado.get("vitorias", 0)) + 1
            self.estado["sequencia"] = int(self.estado.get("sequencia", 0)) + 1
            self.estado["melhor_sequencia"] = max(int(self.estado.get("melhor_sequencia", 0)),
                                                  int(self.estado.get("sequencia", 0)))
        else:
            self.estado["derrotas"] = int(self.estado.get("derrotas", 0)) + 1
            self.estado["sequencia"] = int(self.estado.get("sequencia", 0)) - 1
            self.estado["pior_sequencia"] = min(int(self.estado.get("pior_sequencia", 0)),
                                                 int(self.estado.get("sequencia", 0)))
        self.estado["pico"] = max(self.pico(), self.saldo())

    def liquidar_posicao(self, resultado):
        self.estado["saldo"] = round(self.saldo() + resultado, 6)
        self.estado["pico"] = max(self.pico(), self.saldo())

    def pode_operar(self, minimo_custo_operacao):
        if not self.viva:
            return False, "agente esta morto"
        if self.saldo() < self.cfg.get("morteSeSaldoAbaixo", 0.10):
            return False, "saldo abaixo do limite de sobrevivencia"
        if self.saldo() < minimo_custo_operacao:
            return False, "saldo insuficiente para o menor lote"
        if self.drawdown() >= self.cfg.get("drawdownMaximo", 0.40):
            return False, "drawdown maximo atingido"
        return True, "ok"

    def registrar_morte(self, motivo):
        self.estado["viva"] = False
        self.estado["motivo_morte"] = motivo
        self.estado["morte_em"] = _agora()
        self.mortes += 1
        self.salvar()

    def talvez_reviver(self):
        if self.viva:
            return True
        minimo = float(self.cfg.get("morteSeSaldoAbaixo", 0.10)) * 2
        if self.saldo() > minimo:
            self.estado["viva"] = True
            self.estado["motivo_morte"] = None
            self.estado["ressurreicao"] = _agora()
            self.estado["mortes"] = int(self.estado.get("mortes", 0)) + 1
            self.salvar()
            return True
        return False
