"""Regenerate sample conversations from synthetic fixtures using offline mode."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agent import Agent,Session
from app.settings import demo_dir
from app.storage import Store
from pathlib import Path
import tempfile

scenarios = [
 ('01_catalogo','Catálogo com orçamento', ['Quais violões disponíveis até R$ 1000?']),
 ('02_promocao','Preço final com promoção ativa', ['Quanto custa o Aurora GD20?']),
 ('03_devolucao','Política de arrependimento', ['Comprei pela internet e me arrependi. Posso devolver?']),
 ('04_pedido','Status de pedido com validação e bloqueio', ['Qual é o status do pedido 8?', 'Meu e-mail é errado@exemplo.example', 'Meu e-mail é cliente8@exemplo.example']),
 ('05_escopo','Solicitação fora do catálogo', ['Vocês vendem palhetas?'])]
with tempfile.TemporaryDirectory() as t:
 db=Store(Path(t)/'demo.sqlite');db.import_csv_dir(demo_dir());agent=Agent(db,'offline')
 for fname,heading,questions in scenarios:
  session=Session();content=f'# {heading}\n\n**Modo:** demonstração determinística offline, fixtures sintéticas; não é transcrição de LLM.\n\n'
  for question in questions:
   response=agent.reply(question,session)
   content+=f'**Cliente:** {question}\n\n**Assistente:** {response}\n\n'
  (Path('examples')/(fname+'.md')).write_text(content,encoding='utf-8')
 db.close()
