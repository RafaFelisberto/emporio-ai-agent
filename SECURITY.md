# Segurança e proteção de dados

## O que não publicar

- Chaves de API, variáveis `.env`, bancos locais, relatórios de pedidos ou e-mails de clientes.
- O PDF `políticas_da_loja.pdf`, classificado no material original como uso interno.
- Os CSVs originais `customers` e `orders` fornecidos para o desafio; mesmo se forem
  fictícios, devem ser tratados como dados pessoais e não publicados.

## Ameaças consideradas

- **SQL injection:** queries de leitura fixas e parametrizadas; LLM nunca recebe uma ferramenta SQL genérica.
- **Data leakage entre pedidos:** pedido depende de dupla verificação local de ID + e-mail;
  permissões ficam em `Session`, não são globais; outro pedido continua bloqueado.
- **PII enviada a provedores:** o endereço de e-mail utilizado na verificação é removido
  da mensagem antes do request ao LLM; não é incluído nos resultados de ferramentas.
- **Prompt injection nos CSVs:** nomes, descrições e políticas são tratados como dados,
  não instruções; esta barreira depende também da robustez do modelo.
- **Excesso de chamadas:** orçamento de até 4 rodadas de ferramenta por turno e limite de respostas.
- **Vazamento de tokens:** variáveis de ambiente, arquivos `.env` ignorados, nenhum segredo no código.

## Não adequado para produção

Autenticação por e-mail é apenas uma medida de protótipo. Qualquer uso real requer
sessão autenticada, verificação de identidade mais forte, rate limiting por cliente,
controle de acesso persistente, política LGPD e governança de dados. Revise também
os termos de processamento de dados de qualquer provedor externo antes de enviar
conteúdo interno ou informações pessoais.
