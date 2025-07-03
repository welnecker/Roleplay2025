# -*- coding: utf-8 -*-

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from datetime import datetime
from openai import OpenAI
import json
import os
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials

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

CHROMA_BASE_URL = "https://humorous-beauty-production.up.railway.app"

class MensagemUsuario(BaseModel):
    user_input: str
    personagem: str

def adicionar_memoria_chroma(personagem: str, conteudo: str):
    url = f"{CHROMA_BASE_URL}/api/v2/tenants/janio/databases/minha_base/collections/memorias/add"
    dados = {
        "documents": [conteudo],
        "ids": [f"{personagem}_{datetime.now().timestamp()}"],
        "metadata": {"personagem": personagem, "timestamp": str(datetime.now())}
    }
    requests.post(url, json=dados)

def buscar_memorias_chroma(personagem: str, texto: str):
    url = f"{CHROMA_BASE_URL}/api/v2/tenants/janio/databases/minha_base/collections/memorias/query"
    dados = {
        "query_texts": [texto],
        "n_results": 3,
        "where": {"personagem": personagem}
    }
    resposta = requests.post(url, json=dados)
    resultados = resposta.json()
    return resultados.get("documents", [[]])[0]

@app.post("/chat/")
def chat_com_memoria(mensagem: MensagemUsuario):
    personagem = mensagem.personagem
    texto_usuario = mensagem.user_input

    memorias = buscar_memorias_chroma(personagem, texto_usuario)
    contexto = "\n".join(memorias)

    prompt = f"""
A partir das memórias relevantes abaixo, responda como a personagem {personagem}:

MEMÓRIAS RELEVANTES:
{contexto}

MENSAGEM DO USUÁRIO:
\"{texto_usuario}\"

Sua resposta deve sempre conter:
- Uma fala direta da personagem.
- Um pensamento entre parênteses.
- Uma narração em terceira pessoa, descrevendo ações e reações.

Mantenha a fala envolvente, provocante e com atitude.
"""

    resposta = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", "")).chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "Você é uma personagem fictícia sensual, emocionalmente expressiva e com memórias."},
            {"role": "user", "content": prompt}
        ]
    )
    conteudo = resposta.choices[0].message.content.strip()

    adicionar_memoria_chroma(personagem, texto_usuario)

    return JSONResponse(content={"resposta": conteudo})

@app.get("/personagens/")
def listar_personagens():
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet("personagens")
        dados = aba.get_all_records()
        personagens = []
        for p in dados:
            if str(p.get("usar", "")).strip().lower() != "sim":
                continue
            personagens.append({
                "nome": p.get("nome", ""),
                "descricao": p.get("descrição curta", ""),
                "idade": p.get("idade", ""),
                "foto": f"{GITHUB_IMG_URL}{p.get('nome','').strip()}.jpg"
            })
        return personagens
    except Exception as e:
        return JSONResponse(content={"erro": str(e)}, status_code=500)

@app.post("/memoria_inicial/")
def inserir_memoria_inicial(personagem: str):
    if personagem.lower() == "regina":
        conteudo = (
            "Regina está viajando de moto por uma estrada deserta ao entardecer. "
            "O vento bagunça seu cabelo solto e o couro justo da jaqueta envolve suas curvas. "
            "Ela para em um motel de beira de estrada, sentindo que a noite pode trazer algo inesperado."
        )
    elif personagem.lower() == "jennifer":
        conteudo = (
            "Jennifer acorda em um quarto escuro, iluminado apenas pela luz azul do computador. "
            "Ela sente que alguém a observa pela câmera desligada. Sussurros ecoam em sua mente. "
            "É noite. Algo a chama para fora, mas ela ainda não entende o que."
        )
    else:
        return JSONResponse(content={"erro": "Personagem desconhecida."}, status_code=400)

    adicionar_memoria_chroma(personagem, conteudo)
    return {"status": f"Memória inicial de {personagem} adicionada com sucesso."}
