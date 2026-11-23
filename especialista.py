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
                "custo_produto": produto.get("custo_produto", 0) or 0,
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


def orientar(aba, campanhas, produtos_mpa, investimentos, metricas, anuncios):
    """Gera recomendações simples para a aba; cada mensagem informa sua regra."""
    dicas = []
    if aba == "campanhas":
        com_gasto = [c for c in campanhas if (c.get("total_investido", 0) or 0) > 0]
        abaixo = [c for c in com_gasto if (c.get("roas", 0) or 0) < 1]
        sem_metricas = [c for c in com_gasto if (c.get("total_impressoes", 0) or 0) == 0]
        estouradas = [c for c in campanhas if (c.get("orcamento_planejado", 0) or 0) > 0 and (c.get("total_investido", 0) or 0) > c.get("orcamento_planejado", 0)]
        for c in abaixo[:3]:
            dicas.append({"nivel": "critico", "titulo": f"Revise {c.get('nome', 'a campanha')}", "mensagem": f"ROAS {c.get('roas', 0):.2f}x: a receita registrada está abaixo do investimento."})
        for c in estouradas[:3]:
            dicas.append({"nivel": "atencao", "titulo": f"Orçamento excedido: {c.get('nome', 'campanha')}", "mensagem": "O investimento acumulado passou do orçamento planejado."})
        for c in sem_metricas[:3]:
            dicas.append({"nivel": "atencao", "titulo": f"Confira as métricas de {c.get('nome', 'campanha')}", "mensagem": "Há investimento registrado, mas nenhuma impressão. Confira se as métricas foram lançadas."})
        if not dicas:
            dicas.append({"nivel": "ok", "titulo": "Campanhas sem alertas pelas regras atuais", "mensagem": "Nenhuma campanha investida está abaixo do ROAS 1 ou acima do orçamento."})

    elif aba == "produtos":
        negativas = [p for p in produtos_mpa if p["mpa"] < 0]
        baixas = [p for p in produtos_mpa if p["receita"] > 0 and 0 <= p["mpa"] <= p["receita"] * 0.12]
        sem_custo = [p for p in produtos_mpa if p.get("custo_produto", 0) == 0]
        for p in negativas[:3]:
            dicas.append({"nivel": "critico", "titulo": f"Margem negativa: {p['nome']}", "mensagem": f"MPA estimada em R$ {p['mpa']:.2f}; revise custos, frete, taxas e investimento atribuído."})
        for p in baixas[:3]:
            dicas.append({"nivel": "atencao", "titulo": f"Margem baixa: {p['nome']}", "mensagem": f"MPA está em até 12% da receita (R$ {p['mpa']:.2f})."})
        if sem_custo:
            dicas.append({"nivel": "atencao", "titulo": "Complete os custos dos produtos", "mensagem": f"{len(sem_custo)} produto(s) estão com custo unitário zero; a MPA pode estar superestimada."})
        if not dicas:
            dicas.append({"nivel": "ok", "titulo": "Margens sem alertas pelas regras atuais", "mensagem": "Produtos com receita estão acima do limite de MPA de 12%."})

    elif aba == "investimentos":
        estouradas = [c for c in campanhas if (c.get("orcamento_planejado", 0) or 0) > 0 and (c.get("total_investido", 0) or 0) > c.get("orcamento_planejado", 0)]
        perto = [c for c in campanhas if (c.get("orcamento_planejado", 0) or 0) > 0 and 0.8 <= (c.get("total_investido", 0) or 0) / c["orcamento_planejado"] <= 1]
        for c in estouradas[:3]:
            dicas.append({"nivel": "critico", "titulo": f"Orçamento excedido: {c.get('nome', 'campanha')}", "mensagem": f"Investido {c.get('total_investido', 0):.2f} de {c.get('orcamento_planejado', 0):.2f} planejados."})
        for c in perto[:3]:
            dicas.append({"nivel": "atencao", "titulo": f"Orçamento quase no limite: {c.get('nome', 'campanha')}", "mensagem": f"Já foram usados {c.get('total_investido', 0):.2f} de {c.get('orcamento_planejado', 0):.2f} planejados."})
        sem_verba = [c for c in campanhas if c.get("status") == "ativa" and not (c.get("total_investido", 0) or 0)]
        for c in sem_verba[:3]:
            dicas.append({"nivel": "atencao", "titulo": f"Campanha ativa sem investimento: {c.get('nome', 'campanha')}", "mensagem": "Ainda não há investimento registrado para esta campanha."})
        if not dicas:
            dicas.append({"nivel": "ok", "titulo": "Orçamentos dentro dos limites", "mensagem": "Nenhum orçamento ultrapassado ou acima de 80% foi encontrado."})

    elif aba == "metricas":
        sem_anuncio = sum(1 for m in metricas if not m.get("anuncio_id"))
        sem_visitas = sum(1 for m in metricas if (m.get("cliques", 0) or 0) > 0 and not (m.get("visitas", 0) or 0))
        sem_vendas = sum(1 for m in metricas if (m.get("visitas", 0) or 0) > 0 and not (m.get("vendas", 0) or 0))
        if sem_anuncio:
            dicas.append({"nivel": "atencao", "titulo": "Parte das métricas não está ligada a anúncios", "mensagem": f"{sem_anuncio} registro(s) sem anúncio reduzem a precisão da análise por produto."})
        if sem_visitas:
            dicas.append({"nivel": "atencao", "titulo": "Cliques sem visitas registradas", "mensagem": f"Revise {sem_visitas} registro(s): têm cliques, mas nenhuma visita informada."})
        if sem_vendas:
            dicas.append({"nivel": "atencao", "titulo": "Visitas sem vendas", "mensagem": f"{sem_vendas} registro(s) têm visitas e nenhuma venda; confira conversão e qualidade do tráfego."})
        if not dicas:
            dicas.append({"nivel": "ok", "titulo": "Métricas sem lacunas detectadas", "mensagem": "Os registros têm associação a anúncio e dados de visitas/vendas consistentes com as regras simples."})

    elif aba == "anuncios":
        totais = {}
        for m in metricas:
            aid = m.get("anuncio_id")
            if aid:
                t = totais.setdefault(aid, {"impressoes": 0, "cliques": 0, "visitas": 0, "vendas": 0})
                for chave in t:
                    t[chave] += m.get(chave, 0) or 0
        sem_impressao = sum(1 for a in anuncios if str(a["_id"]) not in totais)
        sem_cliques = sum(1 for t in totais.values() if t["impressoes"] and not t["cliques"])
        if sem_impressao:
            dicas.append({"nivel": "atencao", "titulo": "Anúncios sem métricas", "mensagem": f"{sem_impressao} anúncio(s) ainda não têm impressões registradas."})
        if sem_cliques:
            dicas.append({"nivel": "atencao", "titulo": "Impressões sem cliques", "mensagem": f"{sem_cliques} anúncio(s) têm impressões, mas nenhum clique; avalie criativo e público."})
        if not dicas:
            dicas.append({"nivel": "ok", "titulo": "Sem oportunidade evidente nos dados", "mensagem": "Há registros de desempenho e nenhum anúncio com impressões zeradas em cliques."})

    elif aba in ("relatorios", "indicadores", "comparar"):
        piores = sorted((c for c in campanhas if (c.get("total_investido", 0) or 0) > 0), key=lambda c: c.get("roas", 0) or 0)
        if piores and (piores[0].get("roas", 0) or 0) < 1:
            c = piores[0]
            dicas.append({"nivel": "critico", "titulo": f"Priorize a análise de {c.get('nome', 'campanha')}", "mensagem": f"É a campanha de menor ROAS ({c.get('roas', 0):.2f}x); confira período, público e qualidade das métricas."})
        rentaveis = [c for c in campanhas if (c.get("roas", 0) or 0) >= 1]
        if rentaveis:
            melhor = max(rentaveis, key=lambda c: c.get("roas", 0) or 0)
            dicas.append({"nivel": "ok", "titulo": f"Referência de desempenho: {melhor.get('nome', 'campanha')}", "mensagem": f"ROAS {melhor.get('roas', 0):.2f}x; compare estratégia e período com campanhas de menor retorno."})
        if not dicas:
            dicas.append({"nivel": "atencao", "titulo": "Ainda não há base suficiente para comparar retorno", "mensagem": "Registre investimentos e métricas para que o ROAS comparativo seja calculado."})

    elif aba == "visao_geral":
        com_gasto = [c for c in campanhas if (c.get("total_investido", 0) or 0) > 0]
        abaixo = sorted((c for c in com_gasto if (c.get("roas", 0) or 0) < 1), key=lambda c: c.get("roas", 0) or 0)
        for c in abaixo[:3]:
            dicas.append({"nivel": "critico", "titulo": f"Revise a campanha {c.get('nome', 'sem nome')}", "mensagem": f"ROAS de {c.get('roas', 0):.2f}x: receita atribuída abaixo do investimento."})
        margem_baixa = [p for p in produtos_mpa if p["receita"] > 0 and p["mpa"] <= p["receita"] * 0.12]
        for p in margem_baixa[:3]:
            dicas.append({"nivel": "atencao" if p["mpa"] >= 0 else "critico", "titulo": f"Confira a margem de {p['nome']}", "mensagem": f"MPA estimada em R$ {p['mpa']:.2f} sobre R$ {p['receita']:.2f} de receita."})
        if not dicas:
            dicas.append({"nivel": "ok", "titulo": "Visão geral sem alertas", "mensagem": "Nenhuma campanha com ROAS abaixo de 1 ou produto com MPA até 12% foi identificado."})
    else:
        dicas.append({"nivel": "ok", "titulo": "Assistente do AdControl", "mensagem": "As recomendações usam regras transparentes sobre os dados registrados; revise os cadastros para melhorar a precisão."})

    return dicas
