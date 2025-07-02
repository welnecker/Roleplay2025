# -*- coding: utf-8 -*-

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from datetime import datetime
from openai import OpenAI
import json
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from chromadb.config import Settings
import chromadb

# === Setup Google Sheets ===
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]
creds_dict = json.loads(os.environ.get("GOOGLE_CREDS_JSON", "{}"))
if "private_key" in creds_dict:
    creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
gsheets_client = gspread.authorize(creds)

PLANILHA_ID = "1qFTGu-NKLt-4g5tfa-BiKPm0xCLZ9ZEv5eafUyWqQow"
GITHUB_IMG_URL = "https://welnecker.github.io/roleplay_imagens/"

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

introducao_mostrada_por_usuario = {}
contador_interacoes = {}

# === ChromaDB ===
chroma_client = chromadb.Client(Settings(
    chroma_db_impl=os.environ.get("CHROMA_DB_IMPL", "chromadb.db.postgres.PostgresDB"),
    chroma_postgres_host=os.environ.get("CHROMA_POSTGRES_HOST"),
    chroma_postgres_port=os.environ.get("CHROMA_POSTGRES_PORT"),
    chroma_postgres_user=os.environ.get("CHROMA_POSTGRES_USER"),
    chroma_postgres_password=os.environ.get("CHROMA_POSTGRES_PASSWORD"),
    chroma_postgres_database=os.environ.get("CHROMA_POSTGRES_DATABASE")
))

# Cria a coleção de memórias vetoriais
chroma_memorias = chroma_client.get_or_create_collection(name="memorias")

# Salva memória vetorial
def salvar_memoria_vetorial(personagem: str, conteudo: str):
    try:
        id_memoria = f"{personagem}_{datetime.now().timestamp()}"
        chroma_memorias.add(
            documents=[conteudo],
            ids=[id_memoria],
            metadata={"personagem": personagem, "timestamp": str(datetime.now())}
        )
    except Exception as e:
        print(f"[ERRO salvar_memoria_vetorial] {e}")

# Busca memórias similares
def buscar_memorias_similares(personagem: str, texto: str, n: int = 3):
    try:
        resultados = chroma_memorias.query(
            query_texts=[texto],
            n_results=n,
            where={"personagem": personagem}
        )
        return resultados.get("documents", [[]])[0]
    except Exception as e:
        print(f"[ERRO buscar_memorias_similares] {e}")
        return []

# === Modelos de entrada ===
class MensagemUsuario(BaseModel):
    user_input: str
    personagem: str

@app.post("/chat/")
def chat_com_memoria(mensagem: MensagemUsuario):
    personagem = mensagem.personagem
    texto_usuario = mensagem.user_input

    # Buscar memórias similares
    memorias = buscar_memorias_similares(personagem, texto_usuario, n=3)
    contexto = "\n".join(memorias)

    prompt = f"""
A partir das memórias relevantes abaixo, responda como a personagem {personagem}:

MEMÓRIAS RELEVANTES:
{contexto}

MENSAGEM DO USUÁRIO:
"{texto_usuario}"

Sua resposta deve sempre conter:
- Uma fala direta da personagem.
- Um pensamento entre parênteses.
- Uma narração em terceira pessoa, descrevendo ações e reações.

Mantenha a fala envolvente, provocante e com atitude.
"""

    resposta = OpenAI().chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "Você é uma personagem fictícia sensual, emocionalmente expressiva e com memórias."},
            {"role": "user", "content": prompt}
        ]
    )
    conteudo = resposta.choices[0].message.content.strip()

    # Salvar memória nova
    salvar_memoria_vetorial(personagem, texto_usuario)

    return JSONResponse(content={"resposta": conteudo})
