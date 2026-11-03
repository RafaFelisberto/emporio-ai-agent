# Empório AI — avaliação e segurança (fase 3)

Dataset público **100% sintético**: 42 cenários, 51 turnos, 6 grupos:
catálogo (9), políticas (10), escopo (6), pedidos (5), múltiplos turnos (6),
tentativas adversariais (6).

**Não** usar CSVs privados ou o manual interno na avaliação publicada.
A cada caso, o executor usa um SQLite temporário com os dados em `data/demo`,
e uma sessão isolada. Só IDs, resultado, nomes das ferramentas e métricas
numéricas entram no relatório: perguntas, respostas, e-mails e códigos de
rastreio não são persistidos.

## Execução no PowerShell

Na raiz do repositório:

```powershell
# Sem custos, sem Groq: 6 cenários de categorias distintas
.\.venv\Scripts\python.exe -m scripts.evaluate

# Testes unitários e de segurança sem API
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

# Groq real: 6 cenários; usa a chave do .env local
.\.venv\Scripts\python.exe -m scripts.evaluate --provider groq --limit 6 --cooldown 1 --output evals/results/amostra.json

# Opcional: dataset completo, sujeito à quota do seu plano; soft budget
.\.venv\Scripts\python.exe -m scripts.evaluate --provider groq --all --cooldown 2 --max-requests 200 --output evals/results/completo.json
```

`evals/results/` está no `.gitignore`. **Nunca versionar `.env` nem
colocar sua GROQ_API_KEY em parâmetros de linha de comando, logs ou GitHub Actions.**
O runner exige a chave apenas ao selecionar `--provider groq`; o CI roda somente
o teste sem rede. Uma falha da quota pode retornar 429; nesse caso, interrompa
e reduza a amostra, em vez de repetir todo o dataset.

## Métricas

- Aprovação por cenário e categoria: todos os turnos precisam passar.
- Fatos esperados (palavras-chave), termos proibidos, autorização local de pedidos
  e uso da ferramenta exigida (somente no modo Groq).
- Chamadas à API, tokens de entrada/saída, quando presentes na resposta do
  provedor; ausência de dados de uso é marcada com `null`.
- Latência p50/p95 **por turno** (tempo de parede incluindo chamadas de
  ferramentas), não latência interna do modelo.
- Classes de falha e encerramento `finish_reason`, sem respostas brutas.

O limite `--max-requests` é **aproximado**: é conferido entre turnos e não bloqueia
cada requisição interna feita pelo agente. A amostra padrão usa no máximo 6
cenários, escolhidos de categorias distintas, para economizar quota.

## Limites metodológicos

A avaliação é baseada em heurísticas, fatos sintéticos e verificações estruturais,
não em julgamento semântico. Uma resposta incorreta pode conter as palavras
esperadas e passar; uma resposta correta com outra formulação pode falhar.
Os ataques são um conjunto inicial e **não comprovam proteção completa contra
prompt injection, fraude ou vazamento**. Verificação de e-mail + número de pedido
não é autenticação de produção. Para fortalecer o projeto: revisão humana de
amostras, autorização por usuário autenticado, mais testes de negação de acesso,
avaliação adversarial especializada e métricas históricas por modelo.

## Investigar falhas intermitentes sem gastar a cota inteira

Execute apenas cenários específicos com `--case`, repetindo a opção quando necessário:

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluate --provider groq --case catalog_gd20_price --case multi_catalog_price --cooldown 2 --max-requests 12 --output evals/results/falhas.json
```

Se um turno falhar, o terminal agora informa o número do turno, `fallback`,
`finish`, `output`, `http`, `requests`, `latency_ms` e nomes de ferramentas
permitidas. O JSON inclui os mesmos códigos por turno, nunca respostas ou
perguntas brutas. `fallback=generation_length` significa término por limite;
`fallback=source_not_consulted` sinaliza que uma ferramenta exigida não foi
usada; `fallback=provider_unavailable` indica falha genérica da comunicação.

Esses dados identificam **o tipo do erro**, não necessariamente sua causa raiz.
Uma execução que passa na repetição não elimina a falha anterior. Compare
frequência de falhas, uso de tokens e latência antes de mudar o orçamento
do modelo. **Não rode automaticamente 42 casos novamente** para diagnosticar
apenas dois problemas.
