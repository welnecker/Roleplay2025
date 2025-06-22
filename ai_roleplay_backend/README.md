📄 Conteúdo sugerido: ai_roleplay_backend/README.md
markdown
Copiar
Editar
# Backend FastAPI - AI Roleplay

Este é o backend da aplicação **Janio AI Roleplay**, responsável por gerar respostas com base em interações emocionais e personalidades via OpenAI.

---

## 🚀 Como rodar localmente

### Pré-requisitos:

- Python 3.10+
- Biblioteca `openai`, `fastapi`, `uvicorn`, `python-dotenv`, `pydantic`

### Instalação:

```bash
pip install -r requirements.txt
Ou manualmente:

bash
Copiar
Editar
pip install fastapi uvicorn openai python-dotenv
🔐 Configuração da API Key
Crie um arquivo .env com o seguinte conteúdo:

env
Copiar
Editar
OPENAI_API_KEY=sk-sua-chave-aqui
▶️ Executar servidor
bash
Copiar
Editar
uvicorn backend_ai_roleplay:app --reload
Acesse em: http://127.0.0.1:8000

📌 Estrutura principal
backend_ai_roleplay.py: código principal da API

.env: (ignorado no Git) armazena sua chave de acesso à API OpenAI

.env.example: modelo de configuração

✍️ Licença
Projeto pessoal educacional. Não utilize para fins inadequados ou ofensivos.

yaml
Copiar
Editar

---

### ✅ Próximo passo:

1. Salve esse arquivo como `README.md` na pasta `ai_roleplay_backend/`.
2. Depois:

```bash
git add ai_roleplay_backend/README.md
git commit -m "Adiciona README do backend FastAPI"
git push
