# === 1. Importações e setup ===
from fastapi import FastAPI, Query
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from fastapi.responses import JSONResponse
from dateutil import parser as dateparser
from openai import OpenAI
import json
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# === 2. Setup Google Sheets ===
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_dict = json.loads(os.environ["GOOGLE_CREDS_JSON"])
if "private_key" in creds_dict:
    creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
gsheets_client = gspread.authorize(creds)

PLANILHA_ID = "1qFTGu-NKLt-4g5tfa-BiKPm0xCLZ9ZEv5eafUyWqQow"
GITHUB_IMG_URL = "https://welnecker.github.io/roleplay_imagens/"

# === 3. FastAPI setup ===
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === 4. Utilitários ===
def limpar_texto(texto: str) -> str:
    return ''.join(c for c in texto if c.isprintable())

# === 5. Nova rota para /personagens/ ===
@app.get("/personagens/")
def listar_personagens():
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet("personagens")
        dados = aba.get_all_records()
        personagens = []

        for p in dados:
            if str(p.get("usar", "não")).strip().lower() != "sim":
                continue

            nome = p.get("nome", "").strip()
            personagens.append({
                "nome": nome,
                "descricao": p.get("descrição curta", "").strip(),
                "idade": p.get("idade", "").strip(),
                "estilo": p.get("estilo fala", "").strip(),
                "estado_emocional": p.get("estado_emocional", "").strip(),
                "exemplo": p.get("exemplo", "").strip(),
                "foto": f"{GITHUB_IMG_URL}{nome}.jpg"
            })

        return personagens

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# === 6. Memórias automáticas ===
def carregar_memorias(personagem):
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet("memorias")
        linhas = aba.get_all_records()
        memorias = [linha for linha in linhas if linha["personagem"].lower().strip() == personagem.lower().strip()]
        return memorias
    except Exception as e:
        return []

def salvar_memoria(personagem, tipo, titulo, conteudo):
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet("memorias")
        data_hoje = datetime.now().strftime("%Y-%m-%d")
        aba.append_row([personagem, tipo, titulo, data_hoje, conteudo])
    except Exception as e:
        pass

# === 7. Rota aprimorada para /chat/ ===
class Message(BaseModel):
    user_input: str
    personagem: str

@app.post("/chat/")
def chat_com_ia(mensagem: Message):
    try:
        personagem = mensagem.personagem
        aba_personagens = gsheets_client.open_by_key(PLANILHA_ID).worksheet("personagens")
        dados = aba_personagens.get_all_records()
        personagem_dados = next((p for p in dados if p.get("nome").lower() == personagem.lower()), {})

        memorias = carregar_memorias(personagem)
        memorias_texto = "\n".join([f"{m['tipo']}: {m['titulo']} - {m['conteudo']}" for m in memorias])

        prompt = f"""Estilo de fala: {personagem_dados.get('estilo fala')}\n
        Estado emocional: {personagem_dados.get('estado_emocional')}\n
        Exemplo: {personagem_dados.get('exemplo')}\n
        Memórias:\n{memorias_texto}\n
        Usuário: {mensagem.user_input}\nPersonagem:"""

        openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        resposta = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": prompt}],
            temperature=0.8,
            max_tokens=750,
        ).choices[0].message.content.strip()

        salvar_memoria(personagem, "evento", "Interação", resposta)

        return {"resposta": resposta}

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
