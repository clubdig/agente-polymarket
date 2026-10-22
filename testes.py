import unittest

import kelly
import risco
import sentimento
from vida import Vida


class TesteKelly(unittest.TestCase):
    def test_edge_zero_nao_posiciona(self):
        shares, _, f = kelly.tamanho_posicao(1000, 0.50, 0.50, 0.25, 0.06, 5)
        self.assertEqual(shares, 0)
        self.assertEqual(f, 0.0)

    def test_ganho_porcentual(self):
        p = 0.60
        preco = 0.50
        f = kelly.kelly_fraction(p, preco)
        self.assertAlmostEqual(f, 0.2, places=6)

    def test_teto_de_risco_respeitado(self):
        banco = 1000
        preco = 0.20
        p = 0.90
        shares, risco_usado, _ = kelly.tamanho_posicao(banco, p, preco, 1.0, 0.06, 5)
        custo = shares * preco
        self.assertLessEqual(custo, banco * 0.06 + 1e-9)

    def test_lote_minimo_respeitado(self):
        banco = 0.95
        preco = 0.50
        p = 0.95
        shares, _, _ = kelly.tamanho_posicao(banco, p, preco, 0.25, 0.06, 5)
        self.assertEqual(shares, 0)


class TesteSentimento(unittest.TestCase):
    def test_positivo(self):
        s, n = sentimento._texto_score("Stocks surge to record high on strong growth")
        self.assertGreater(s, 0)
        self.assertGreater(n, 0)

    def test_negativo(self):
        s, n = sentimento._texto_score("Market crash and massive losses after failed upgrade")
        self.assertLess(s, 0)

    def test_negacao_inverte(self):
        s_pos, _ = sentimento._texto_score("not bullish")
        s_neutro, _ = sentimento._texto_score("bullish")
        self.assertLess(s_pos, s_neutro)

    def test_relevancia_ignora_posts_sem_termo(self):
        posts = [{"texto": "unrelated content about cooking", "peso": 1, "fonte": "reddit"}]
        r = sentimento.avaliar(posts, 1, ["senate"])
        self.assertEqual(r["n"], 0)
        self.assertIsNone(r["p"])


class TesteVida(unittest.TestCase):
    def setUp(self):
        self.cfg = {
            "bancadaInicial": 100.0, "morteSeSaldoAbaixo": 10.0, "drawdownMaximo": 0.40,
            "caminhoEstado": "teste_state.json", "caminhoPosicoes": "teste_posicoes.json",
        }
        self.vida = Vida(self.cfg)

    def tearDown(self):
        import os
        for f in ("teste_state.json", "teste_posicoes.json"):
            if os.path.exists(f):
                os.remove(f)

    def test_perda_dispara_morte(self):
        self.vida.estado["saldo"] = 5.0
        pode, _ = self.vida.pode_operar(1.0)
        self.assertFalse(pode)

    def test_drawdown(self):
        self.vida.estado["pico"] = 100.0
        self.vida.estado["saldo"] = 60.0
        self.assertAlmostEqual(self.vida.drawdown(), 0.4, places=6)
        pode, _ = self.vida.pode_operar(1.0)
        self.assertFalse(pode)

    def test_sequencia(self):
        self.vida.registrar_operacao(1.0)
        self.vida.registrar_operacao(1.0)
        self.assertEqual(self.vida.estado["melhor_sequencia"], 2)
        self.vida.registrar_operacao(-1.0)
        self.assertEqual(self.vida.estado["sequencia"], 1)


if __name__ == "__main__":
    unittest.main()
