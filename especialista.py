"""Regras simples e explicáveis para MPA e alertas de desempenho."""

from analise import dividir


def analisar(investimentos, metricas, anuncios, produtos, campanhas):
    """Calcula MPA por produto e alertas a partir dos dados já filtrados."""
    receita_por_campanha = {}
    gasto_por_campanha = {}
    receita_por_produto = {}
    vendas_por_produto = {}

    anuncio_por_id = {str(a["_id"]): a for a in anuncios}
    produto_por_id = {str(p["_id"]): p for p in produtos}
    nomes_campanha = {str(c["_id"]): c.get("nome", "Campanha") for c in campanhas}

    for registro in investimentos:
        cid = registro.get("campanha_id")
        gasto_por_campanha[cid] = gasto_por_campanha.get(cid, 0) + (registro.get("investimento", 0) or 0)
    for registro in metricas:
        cid = registro.get("campanha_id")
        receita = registro.get("receita_atribuida", 0) or 0
        receita_por_campanha[cid] = receita_por_campanha.get(cid, 0) + receita
        anuncio = anuncio_por_id.get(registro.get("anuncio_id"))
        if not anuncio:
            continue
        pid = anuncio.get("produto_id")
        produto = produto_por_id.get(pid)
        if not produto:
            continue
        totais = receita_por_produto.setdefault(pid, {"nome": produto.get("nome", "Produto"), "receita": 0.0, "vendas": 0})
        totais["receita"] += receita
        totais["vendas"] += registro.get("vendas", 0) or 0

    investimento_total = sum(gasto_por_campanha.values())
    receita_total = sum(item["receita"] for item in receita_por_produto.values())
    for pid, item in receita_por_produto.items():
        produto = produto_por_id[pid]
        custo_unidades = item["vendas"] * ((produto.get("custo_produto", 0) or 0) + (produto.get("frete_vendedor", 0) or 0))
        custos_pct = item["receita"] * ((produto.get("taxas_pct", 0) or 0) + (produto.get("impostos_pct", 0) or 0)) / 100
        verba_ads = investimento_total * dividir(item["receita"], receita_total)
        item["mpa"] = round(item["receita"] - custo_unidades - custos_pct - verba_ads, 2)
        item["w_mpa"] = 0
        item["custos"] = round(custo_unidades + custos_pct + verba_ads, 2)

    escala = max((abs(p["mpa"]) for p in receita_por_produto.values()), default=1) or 1
    for item in receita_por_produto.values():
        item["w_mpa"] = round(max(item["mpa"], 0) / escala * 100, 1)

    alertas = []
    for cid, gasto in gasto_por_campanha.items():
        receita = receita_por_campanha.get(cid, 0)
        if gasto > 0 and receita < gasto:
            alertas.append({"nivel": "critico", "titulo": f"Retorno baixo: {nomes_campanha.get(cid, 'Campanha')}",
                            "mensagem": f"ROAS {receita / gasto:.2f}x; receita atribuída não cobre o investimento."})
    for item in receita_por_produto.values():
        if item["mpa"] < 0:
            alertas.append({"nivel": "critico", "titulo": f"MPA negativa: {item['nome']}",
                            "mensagem": f"Margem pós-anúncios estimada em R$ {item['mpa']:.2f}. Confira os custos e a atribuição."})
        elif item["mpa"] <= item["receita"] * 0.1:
            alertas.append({"nivel": "atencao", "titulo": f"Margem baixa: {item['nome']}",
                            "mensagem": f"MPA estimada em R$ {item['mpa']:.2f}, até 10% da receita atribuída."})
    if not alertas:
        alertas.append({"nivel": "ok", "titulo": "Sem alertas pelas regras atuais", "mensagem": "Os dados não indicam ROAS abaixo de 1 nem MPA menor que 10% da receita."})
    return sorted(receita_por_produto.values(), key=lambda p: p["mpa"], reverse=True), alertas
