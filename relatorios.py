"""
AdControl Web - relatorios gerenciais e exportacao (funcoes puras, sem Flask nem MongoDB)

Os relatorios usam os mesmos calculos de analise.py. Os CSV saem no formato que o
Excel em portugues abre direto: separador ';', decimais com virgula e codificacao
UTF-8 com BOM. O Power BI tambem le esse formato.
"""

import csv
import io

from analise import calcular_resumo, dividir, serie_diaria


def _agrupar(registros, chave):
    grupos = {}
    for r in registros:
        grupos.setdefault(chave(r), []).append(r)
    return grupos


def por_campanha(investimentos, metricas, campanhas):
    """Uma linha por campanha, considerando so os registros do filtro."""
    inv = _agrupar(investimentos, lambda r: r.get("campanha_id"))
    met = _agrupar(metricas, lambda r: r.get("campanha_id"))
    linhas = []
    for c in campanhas:
        cid = str(c["_id"])
        r = calcular_resumo(inv.get(cid, []), met.get(cid, []))
        linhas.append({"campanha": c.get("nome"), "status": c.get("status"),
                       "orcamento": c.get("orcamento_planejado") or 0, **r})
    linhas.sort(key=lambda l: l["receita"], reverse=True)
    return linhas


def por_anuncio(metricas, anuncios, nomes_campanha, nomes_produto):
    """Uma linha por anuncio. Sem ROAS: o investimento e registrado por campanha."""
    met = _agrupar(metricas, lambda r: r.get("anuncio_id"))
    linhas = []
    for a in anuncios:
        r = calcular_resumo([], met.get(str(a["_id"]), []))
        linhas.append({
            "anuncio": a.get("titulo"),
            "campanha": nomes_campanha.get(a.get("campanha_id"), "(campanha removida)"),
            "produto": nomes_produto.get(a.get("produto_id"), "(produto removido)"),
            "impressoes": r["impressoes"], "cliques": r["cliques"], "ctr": r["ctr"],
            "visitas": r["visitas"], "vendas": r["vendas"], "conversao": r["taxa_conversao"],
            "receita": r["receita"], "ticket": round(dividir(r["receita"], r["vendas"]), 2),
        })
    linhas.sort(key=lambda l: l["receita"], reverse=True)
    return linhas


def por_produto(metricas, anuncios, nomes_produto):
    """Uma linha por produto, somando os anuncios que o divulgam."""
    produto_do_anuncio = {str(a["_id"]): a.get("produto_id") for a in anuncios}
    qtd_anuncios = {}
    for a in anuncios:
        qtd_anuncios[a.get("produto_id")] = qtd_anuncios.get(a.get("produto_id"), 0) + 1
    por_prod = _agrupar([m for m in metricas if m.get("anuncio_id") in produto_do_anuncio],
                        lambda m: produto_do_anuncio[m["anuncio_id"]])
    linhas = []
    for pid, mets in por_prod.items():
        r = calcular_resumo([], mets)
        linhas.append({"produto": nomes_produto.get(pid, "(produto removido)"), "anuncios": qtd_anuncios.get(pid, 0),
                       "impressoes": r["impressoes"], "cliques": r["cliques"], "ctr": r["ctr"],
                       "vendas": r["vendas"], "receita": r["receita"]})
    linhas.sort(key=lambda l: l["receita"], reverse=True)
    return linhas


def por_dia(investimentos, metricas):
    return list(reversed(serie_diaria(investimentos, metricas)))


# ---------- CSV ----------

def _celula(valor):
    if isinstance(valor, float):
        return f"{valor:.2f}".replace(".", ",")
    return "" if valor is None else valor


def para_csv(cabecalho, linhas):
    """Devolve bytes UTF-8 com BOM, separador ';' e decimais com virgula."""
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=";", lineterminator="\r\n")
    escritor.writerow(cabecalho)
    for linha in linhas:
        escritor.writerow([_celula(v) for v in linha])
    return ("\ufeff" + saida.getvalue()).encode("utf-8")


CABECALHOS = {
    "campanhas": ["Campanha", "Status", "Orçamento planejado", "Investido", "Impressões", "Cliques", "CTR (%)", "CPC",
                  "Visitas", "Vendas", "Taxa de conversão (%)", "Custo por venda", "Receita atribuída", "ROAS"],
    "dias": ["Data", "Investido", "Impressões", "Cliques", "Visitas", "Vendas", "Receita atribuída", "ROAS do dia"],
    "anuncios": ["Anúncio", "Campanha", "Produto", "Impressões", "Cliques", "CTR (%)", "Visitas", "Vendas",
                 "Taxa de conversão (%)", "Receita atribuída", "Ticket médio"],
    "produtos": ["Produto", "Anúncios", "Impressões", "Cliques", "CTR (%)", "Vendas", "Receita atribuída"],
    "metricas": ["Data", "Campanha", "Anúncio", "Produto", "Impressões", "Cliques", "Visitas", "Vendas", "Receita atribuída"],
    "investimentos": ["Data", "Campanha", "Investimento"],
}


def linhas_csv(tipo, dados):
    """Converte as linhas de cada relatorio na ordem das colunas do CSV."""
    if tipo == "campanhas":
        return [[l["campanha"], l["status"], float(l["orcamento"]), float(l["investido"]), l["impressoes"], l["cliques"],
                 l["ctr"], l["cpc"], l["visitas"], l["vendas"], l["taxa_conversao"], l["custo_por_venda"],
                 float(l["receita"]), l["roas"]] for l in dados]
    if tipo == "dias":
        return [[l["data"], float(l["investido"]), l["impressoes"], l["cliques"], l["visitas"], l["vendas"],
                 float(l["receita"]), l["roas"]] for l in dados]
    if tipo == "anuncios":
        return [[l["anuncio"], l["campanha"], l["produto"], l["impressoes"], l["cliques"], l["ctr"], l["visitas"],
                 l["vendas"], l["conversao"], float(l["receita"]), l["ticket"]] for l in dados]
    if tipo == "produtos":
        return [[l["produto"], l["anuncios"], l["impressoes"], l["cliques"], l["ctr"], l["vendas"], float(l["receita"])] for l in dados]
    return dados   # metricas e investimentos ja chegam prontos
