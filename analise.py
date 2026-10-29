"""
AdControl Web - calculos de analise

Funcoes puras (nao dependem do Flask nem do MongoDB): indicadores (RF06),
series por dia, funil, comparacao de periodos (RF09) e a geometria dos
graficos do Dashboard (RF07). Por serem puras, podem ser testadas sozinhas.

Todas as formulas de indicadores ficam aqui, num unico lugar (RNF09).
"""

import math
from datetime import date


def dividir(numerador, denominador):
    """Divisao segura: devolve 0 quando o denominador e zero (RNF09)."""
    return numerador / denominador if denominador else 0.0


def _soma(registros, campo):
    return sum(r.get(campo, 0) or 0 for r in registros)


# ---------- indicadores (RF06) ----------

def calcular_resumo(investimentos, metricas):
    """
    Soma investimentos e metricas e calcula os cinco indicadores do sistema:
      CTR = cliques / impressoes x 100
      CPC = investimento / cliques
      Taxa de conversao = vendas / visitas x 100
      Custo por venda = investimento / vendas
      ROAS = receita atribuida / investimento
    """
    investido = _soma(investimentos, "investimento")
    impressoes = _soma(metricas, "impressoes")
    cliques = _soma(metricas, "cliques")
    visitas = _soma(metricas, "visitas")
    vendas = _soma(metricas, "vendas")
    receita = _soma(metricas, "receita_atribuida")

    return {
        "investido": investido,
        "impressoes": int(impressoes),
        "cliques": int(cliques),
        "visitas": int(visitas),
        "vendas": int(vendas),
        "receita": receita,
        "ctr": round(dividir(cliques, impressoes) * 100, 2),
        "cpc": round(dividir(investido, cliques), 2),
        "taxa_conversao": round(dividir(vendas, visitas) * 100, 2),
        "custo_por_venda": round(dividir(investido, vendas), 2),
        "roas": round(dividir(receita, investido), 2),
    }


def no_periodo(registro, data_ini, data_fim):
    """True se a data do registro esta dentro do periodo (datas 'AAAA-MM-DD')."""
    data = registro.get("data") or ""
    if data_ini and (not data or data < data_ini):
        return False
    if data_fim and (not data or data > data_fim):
        return False
    return True


# ---------- serie por dia ----------

def serie_diaria(investimentos, metricas):
    """
    Agrupa investimentos e metricas por dia e devolve uma lista ordenada
    de dicionarios {data, investido, receita, impressoes, cliques, visitas,
    vendas, roas}. Registros sem data valida ficam de fora.
    """
    dias = {}

    def dia(data):
        try:
            date.fromisoformat(data)
        except (TypeError, ValueError):
            return None
        return dias.setdefault(data, {
            "data": data, "investido": 0.0, "receita": 0.0,
            "impressoes": 0, "cliques": 0, "visitas": 0, "vendas": 0,
        })

    for i in investimentos:
        d = dia(i.get("data"))
        if d is not None:
            d["investido"] += i.get("investimento", 0) or 0

    for m in metricas:
        d = dia(m.get("data"))
        if d is not None:
            d["receita"] += m.get("receita_atribuida", 0) or 0
            for campo in ("impressoes", "cliques", "visitas", "vendas"):
                d[campo] += int(m.get(campo, 0) or 0)

    resultado = sorted(dias.values(), key=lambda x: x["data"])
    for d in resultado:
        d["roas"] = round(dividir(d["receita"], d["investido"]), 2)
    return resultado


# ---------- funil ----------

def montar_funil(resumo):
    """Etapas do funil: impressoes -> cliques -> visitas -> vendas, com a taxa de cada etapa."""
    etapas = [
        {"nome": "Impressões", "valor": resumo["impressoes"], "taxa": None, "descricao": ""},
        {"nome": "Cliques", "valor": resumo["cliques"],
         "taxa": dividir(resumo["cliques"], resumo["impressoes"]) * 100,
         "descricao": "das impressões viraram cliques"},
        {"nome": "Visitas", "valor": resumo["visitas"],
         "taxa": dividir(resumo["visitas"], resumo["cliques"]) * 100,
         "descricao": "dos cliques viraram visitas"},
        {"nome": "Vendas", "valor": resumo["vendas"],
         "taxa": dividir(resumo["vendas"], resumo["visitas"]) * 100,
         "descricao": "das visitas viraram vendas"},
    ]
    for etapa in etapas[1:]:
        etapa["taxa"] = round(etapa["taxa"], 2)
        etapa["largura"] = min(etapa["taxa"], 100)
    return etapas


# ---------- comparacao de periodos (RF09) ----------

# (campo, nome, formato, "maior e melhor?")  None = neutro
METRICAS_COMPARACAO = [
    ("investido", "Investido", "brl", None),
    ("receita", "Receita atribuída", "brl", True),
    ("roas", "ROAS", "x", True),
    ("ctr", "CTR", "pct", True),
    ("cpc", "CPC", "brl", False),
    ("taxa_conversao", "Taxa de conversão", "pct", True),
    ("custo_por_venda", "Custo por venda", "brl", False),
    ("vendas", "Vendas", "num", True),
]


def comparar_periodos(resumo_a, resumo_b):
    """
    Compara dois resumos (periodo A e periodo B). A variacao e a mudanca de A
    para B em %. 'sentido' diz se a mudanca foi boa, ruim ou neutra:
    CPC e custo por venda sao melhores quando diminuem.
    """
    linhas = []
    for campo, nome, formato, maior_e_melhor in METRICAS_COMPARACAO:
        a, b = resumo_a[campo], resumo_b[campo]
        variacao = round((b - a) / a * 100, 1) if a else None
        if variacao is None or variacao == 0 or maior_e_melhor is None:
            sentido = "neutro"
        else:
            sentido = "bom" if (variacao > 0) == maior_e_melhor else "ruim"
        linhas.append({
            "nome": nome, "formato": formato, "a": a, "b": b,
            "variacao": variacao, "sentido": sentido,
        })
    return linhas


# ---------- geometria do grafico de linhas (RF07) ----------

def teto_agradavel(valor):
    """Arredonda para cima para um limite 'redondo' de eixo (ex.: 8.700 -> 10.000)."""
    if valor <= 0:
        return 1
    ordem = 10 ** math.floor(math.log10(valor))
    for passo in (1, 2, 2.5, 5, 10):
        if valor <= passo * ordem:
            return passo * ordem
    return 10 * ordem


def abreviar_brl(valor):
    """1500 -> 'R$ 1,5 mil'; 2000 -> 'R$ 2 mil'; 800 -> 'R$ 800'."""
    if valor >= 1_000_000:
        texto = f"{valor / 1_000_000:.1f} mi"
    elif valor >= 1000:
        texto = f"{valor / 1000:.1f} mil"
    else:
        texto = f"{valor:.0f}"
    return "R$ " + texto.replace(".", ",").replace(",0 ", " ")


def _data_br(data_iso, curta=False):
    d = date.fromisoformat(data_iso)
    return d.strftime("%d/%m") if curta else d.strftime("%d/%m/%Y")


def geometria_linhas(serie, largura=720, altura=290):
    """
    Calcula as coordenadas do grafico 'investimento x receita por dia'.
    O desenho em si (SVG) fica no template; aqui so ficam os numeros.
    Devolve None se nao houver dados.
    """
    if not serie:
        return None

    esq, dir_, topo, base = 82, 20, 20, 40
    area_l = largura - esq - dir_
    area_a = altura - topo - base

    maximo = teto_agradavel(max(max(d["investido"], d["receita"]) for d in serie))
    ordinais = [date.fromisoformat(d["data"]).toordinal() for d in serie]
    o_min, o_max = min(ordinais), max(ordinais)

    def x(ordinal):
        if o_max == o_min:
            return esq + area_l / 2
        return esq + (ordinal - o_min) / (o_max - o_min) * area_l

    def y(valor):
        return topo + area_a - (valor / maximo) * area_a

    pontos = []
    for d, o in zip(serie, ordinais):
        pontos.append({
            "x": round(x(o), 1),
            "y_investido": round(y(d["investido"]), 1),
            "y_receita": round(y(d["receita"]), 1),
            "data": _data_br(d["data"]),
            "investido": d["investido"],
            "receita": d["receita"],
        })

    # no maximo 6 marcas no eixo X, sempre incluindo a primeira e a ultima
    n = len(pontos)
    indices = list(range(n)) if n <= 6 else sorted({round(i * (n - 1) / 5) for i in range(6)})
    marcas_x = [{"x": pontos[i]["x"], "rotulo": _data_br(serie[i]["data"], curta=True)} for i in indices]

    marcas_y = [
        {"y": round(y(maximo * f), 1), "rotulo": abreviar_brl(maximo * f) if f else "R$ 0"}
        for f in (0, 0.2, 0.4, 0.6, 0.8, 1)
    ]

    return {
        "largura": largura, "altura": altura, "esq": esq, "dir": dir_,
        "pontos": pontos, "marcas_x": marcas_x, "marcas_y": marcas_y,
        "linha_investido": " ".join(f"{p['x']},{p['y_investido']}" for p in pontos),
        "linha_receita": " ".join(f"{p['x']},{p['y_receita']}" for p in pontos),
    }
