"""Safe, paraphrased public reference rules. Original restricted PDF stays local."""
from __future__ import annotations
from .storage import normalized

# Facts transcribed as *paraphrases* from the fictitious recruitment scenario.
# These are illustrative and should be validated against updated policies before deployment.
POLICIES = {
    "identity": {
        "keywords": ("endereco", "onde fica", "localizacao", "telefone", "whatsapp", "contato", "loja"),
        "text": "Loja de instrumentos musicais em Rua 14 de Maio, 3200, Centro, Campo Grande/MS. Canal de WhatsApp informado no manual: (67) 3321-4500.",
        "source": "Manual interno, seções 1.2 e 7 (versão 2.1)",
    },
    "opening_hours": {
        "keywords": ("horario", "funciona", "aberto", "abre", "fecha", "expediente", "feriado", "sabado", "domingo"),
        "text": "Segunda a sexta: 09h-18h. Sábado: 09h-13h. Domingos e feriados: fechado. Datas especiais podem mudar após anúncio oficial.",
        "source": "Manual interno, seção 2 (versão 2.1)",
    },
    "payments": {
        "keywords": ("pagamento", "pix", "parcelamento", "cartao", "boleto", "credito", "debito", "desconto"),
        "text": "PIX tem desconto de 5% apenas sobre preço de tabela, sem cumular com promoções. Débito e boleto são à vista (boleto: compensação pode levar até 3 dias úteis). Crédito em até 12x sem juros: até 3x respeita restrição para parcelas abaixo de R$ 50; de 4x a 6x mínimo R$ 80 por parcela; de 7x a 12x mínimo R$ 100 por parcela. Pagamentos combinados para compras acima de R$ 2.000.",
        "source": "Manual interno, seções 3 e 3.1 (versão 2.1)",
    },
    "returns": {
        "keywords": ("devolver", "devolucao", "arrepend", "troca", "trocar", "defeito", "reembolso", "restituicao", "garantia"),
        "text": "Para compras online, o direito de arrependimento pode ser solicitado até 7 dias corridos do recebimento, sem justificativa; o manual prevê produto sem sinais de uso, com embalagem original, acessórios e manuais; informa reembolso na forma original em até 10 dias úteis e frete de devolução por sua conta. Troca por preferência: até 7 dias e condicionada ao estado e à disponibilidade. Para defeitos, o manual menciona troca até 30 dias após a compra e garantia legal de 90 dias desde o recebimento; a avaliação do caso exige atendimento humano. Exceções podem valer a itens personalizados e liquidação 'venda final'. Não confirmar elegibilidade sem verificar modalidade e datas.",
        "source": "Manual interno, seções 4 e 8 (versão 2.1)",
    },
    "shipping": {
        "keywords": ("frete", "entrega", "prazo", "envio", "transportadora", "rastreio", "rastrear", "correios", "sedex", "jadlog"),
        "text": "Região metropolitana de Campo Grande: frete grátis acima de R$ 500; abaixo disso, taxa de R$ 35; estimativa de 1 a 3 dias úteis. Outros destinos usam PAC (5-12 dias úteis), SEDEX (2-5) ou Jadlog (3-8), cotação por CEP/peso e possíveis exceções para instrumentos grandes. Prazo é estimado; código de rastreamento é enviado após despacho.",
        "source": "Manual interno, seção 5 (versão 2.1)",
    },
    "promotions": {
        "keywords": ("promocao", "oferta", "black friday", "liquidacao", "cupom", "preco promocional"),
        "text": "Promoções não são cumulativas, nem com desconto PIX. Conferir o indicador de promoção ativa no catálogo antes de informar preço. Campanha por nome não comprova atividade atual.",
        "source": "Manual interno, seção 6 (versão 2.1)",
    },
    "scope": {
        "keywords": ("acessorio", "cabo", "corda", "palheta", "amplificador", "pedal", "case", "capotraste"),
        "text": "A loja comercializa instrumentos musicais, não acessórios avulsos como cordas, cabos, palhetas, pedais, cases ou amplificadores.",
        "source": "Manual interno, seções 1 e 7 (versão 2.1)",
    },
    "privacy": {
        "keywords": ("lgpd", "privacidade", "dados pessoais", "exclusao", "excluir dados"),
        "text": "Atendimento deve usar dados pessoais apenas para finalidades legítimas relacionadas a pedidos e comunicações consentidas. Solicitações de exclusão ou revisão devem ser encaminhadas à equipe humana; o agente não executa exclusões.",
        "source": "Manual interno, seção 9 (versão 2.1)",
    },
}


def find_policies(query: str, topic: str = "", limit: int = 3) -> list[dict[str, str]]:
    key = normalized(topic)
    if key in POLICIES:
        chosen = [(key, POLICIES[key])]
    else:
        q = normalized(query)
        scored = []
        for ident, item in POLICIES.items():
            score = sum(1 for kw in item["keywords"] if normalized(kw) in q)
            if score:
                scored.append((score, ident, item))
        chosen = [(ident, item) for _, ident, item in sorted(scored, key=lambda x: (-x[0], x[1]))[:max(1, min(limit, 5))]]
    return [{"topic": ident, "policy": item["text"], "source": item["source"]} for ident, item in chosen]
