"""Regras de negócio para margem pós-anúncios (MPA) e alertas."""

from analise import dividir


def analisar(investimentos, metricas, anuncios, produtos, campanhas):
    """Calcula MPA por produto e alertas usando os registros do filtro atual."""
    anuncios_por_id = {str(a["_id"]): a for a in anuncios}
    produtos_por_id = {str(p["_id"]): p for p in produtos}
    nomes_campanhas = {str(c["_id"]): c.get("nome", "Campanha") for c in campanhas}

    gasto_por_campanha = {}
    receita_por_campanha = {}
    produtos_por_campanha = {}

    for registro in investimentos:
        campanha_id = registro.get("campanha_id")
        gasto_por_campanha[campanha_id] = gasto_por_campanha.get(campanha_id, 0) + (registro.get("investimento", 0) or 0)

    for registro in metricas:
        campanha_id = registro.get("campanha_id")
        receita = registro.get("receita_atribuida", 0) or 0
        receita_por_campanha[campanha_id] = receita_por_campanha.get(campanha_id, 0) + receita

        anuncio = anuncios_por_id.get(registro.get("anuncio_id"))
        produto_id = anuncio.get("produto_id") if anuncio else None
        produto = produtos_por_id.get(produto_id)
        if not produto:
            continue

        campanha = produtos_por_campanha.setdefault(campanha_id, {})
        totais = campanha.setdefault(produto_id, {
            "nome": produto.get("nome", "Produto"), "receita": 0.0, "vendas": 0,
            "custo_unidades": 0.0, "custos_percentuais": 0.0, "verba_ads": 0.0,
        })
        totais["receita"] += receita
        totais["vendas"] += registro.get("vendas", 0) or 0

    # O anúncio de cada campanha é rateado pela receita de produto / receita total
    # da campanha. Receita sem anúncio permanece fora do cálculo por produto.
    resultados = {}
    for campanha_id, produtos_campanha in produtos_por_campanha.items():
        receita_campanha = receita_por_campanha.get(campanha_id, 0)
        gasto_campanha = gasto_por_campanha.get(campanha_id, 0)
        for produto_id, item in produtos_campanha.items():
            produto = produtos_por_id[produto_id]
            item["custo_unidades"] += item["vendas"] * (
                (produto.get("custo_produto", 0) or 0) + (produto.get("frete_vendedor", 0) or 0)
            )
            item["custos_percentuais"] += item["receita"] * (
                (produto.get("taxas_pct", 0) or 0) + (produto.get("impostos_pct", 0) or 0)
            ) / 100
            item["verba_ads"] += gasto_campanha * dividir(item["receita"], receita_campanha)

            total = resultados.setdefault(produto_id, {
                "nome": item["nome"], "receita": 0.0, "vendas": 0,
                "custo_unidades": 0.0, "custos_percentuais": 0.0, "verba_ads": 0.0,
            })
            for campo in ("receita", "vendas", "custo_unidades", "custos_percentuais", "verba_ads"):
                total[campo] += item[campo]

    for item in resultados.values():
        item["custos"] = round(item["custo_unidades"] + item["custos_percentuais"] + item["verba_ads"], 2)
        item["mpa"] = round(item["receita"] - item["custos"], 2)

    escala = max((abs(item["mpa"]) for item in resultados.values()), default=1) or 1
    for item in resultados.values():
        item["w_mpa"] = round(max(item["mpa"], 0) / escala * 100, 1)

    alertas = []
    for campanha_id, gasto in gasto_por_campanha.items():
        receita = receita_por_campanha.get(campanha_id, 0)
        if gasto > 0 and receita < gasto:
            alertas.append({
                "nivel": "critico", "titulo": f"Retorno baixo: {nomes_campanhas.get(campanha_id, 'Campanha')}",
                "mensagem": f"ROAS {receita / gasto:.2f}x; receita atribuída não cobre o investimento.",
            })

    for item in resultados.values():
        # Sem receita não há base para classificar margem percentual.
        if item["receita"] <= 0:
            continue
        if item["mpa"] < 0:
            alertas.append({
                "nivel": "critico", "titulo": f"MPA negativa: {item['nome']}",
                "mensagem": f"Margem pós-anúncios estimada em R$ {item['mpa']:.2f}. Confira os custos e a atribuição.",
            })
        elif item["mpa"] <= item["receita"] * 0.12:
            alertas.append({
                "nivel": "atencao", "titulo": f"Margem baixa: {item['nome']}",
                "mensagem": f"MPA estimada em R$ {item['mpa']:.2f}, até 12% da receita atribuída.",
            })

    if not alertas:
        alertas.append({
            "nivel": "ok", "titulo": "Sem alertas pelas regras atuais",
            "mensagem": "Os dados não indicam ROAS abaixo de 1 nem MPA até 12% da receita.",
        })
    return sorted(resultados.values(), key=lambda item: item["mpa"], reverse=True), alertas
