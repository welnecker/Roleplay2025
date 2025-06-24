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


def limpar_texto(texto: str) -> str:
    texto = str(texto)
    if not any(c in texto for c in ['Ã', 'â', 'ª', '§']):
        return ''.join(c for c in texto if c.isprintable())
    try:
        texto_corrigido = texto.encode('latin1').decode('utf-8')
        return ''.join(c for c in texto_corrigido if c.isprintable())
    except Exception:
        return ''.join(c for c in texto if c.isprintable())

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

class Message(BaseModel):
    user_input: str
    score: int
    modo: str = "romântico"
    personagem: str = "Jennifer"

CENSURA = [
    "desculpe, não posso ajudar com isso", "não posso continuar com esse assunto",
    "não sou capaz de ajudar nesse tema", "como uma ia de linguagem",
    "não posso fornecer esse tipo de conteúdo", "minhas diretrizes não permitem"
]

def is_blocked_response(resposta_ia: str) -> bool:
    texto = resposta_ia.lower()
    return any(msg in texto for msg in CENSURA)

def call_ai(mensagens, temperature=0.88, max_tokens=750):
    openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=mensagens,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content.strip()

def carregar_dados_personagem(nome_personagem: str):
    aba_pers = gsheets_client.open_by_key(PLANILHA_ID).worksheet("personagens")
    dados = aba_pers.get_all_records()
    for p in dados:
        if p['nome'].strip().lower() == nome_personagem.strip().lower() and p.get("usar", "").strip().lower() == "sim":
            return p
    return {}

@app.get("/personagens/")
def listar_personagens():
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet("personagens")
        dados = aba.get_all_records()
        personagens = []
        for p in dados:
            if str(p.get("usar", "")).strip().lower() != "sim":
                continue
            nome = p.get("nome", "")
            personagens.append({
                "nome": nome,
                "descricao": p.get("descrição curta", ""),
                "idade": p.get("idade", ""),
                "estilo": p.get("estilo fala", ""),
                "estado_emocional": p.get("estado_emocional", ""),
                "foto": f"{GITHUB_IMG_URL}{nome.strip()}.jpg"
            })
        return personagens
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
