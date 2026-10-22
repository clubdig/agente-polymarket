import math


def kelly_fraction(p, preco):
    if not (0 < preco < 1) or not (0 < p < 1):
        return 0.0
    b = (1.0 - preco) / preco
    f = (p * b - (1.0 - p)) / b
    return max(0.0, f)


def tamanho_posicao(bancada, p, preco, fracao_kelly, risco_maximo, min_shares=5):
    f = kelly_fraction(p, preco)
    if f <= 0:
        return 0, 0.0, f
    risco_kelly = bancada * f * fracao_kelly
    risco = min(risco_kelly, bancada * risco_maximo)
    shares = math.floor(risco / preco)
    if shares < min_shares:
        return 0, risco, f
    return int(shares), risco, f


def p_justa(preco):
    return preco
