# === backendnovo.py com nível automático de intimidade ===

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
    regenerar: bool = False

class PersonagemPayload(BaseModel):
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
        "query_embeddings": [],
        "query_texts": [texto],
        "n_results": 8,
        "where": {"personagem": personagem}
    }
    resposta = requests.post(url, json=dados)
    if resposta.status_code == 200:
        itens = resposta.json().get("documents", [])
        return [mem for grupo in itens for mem in grupo]
    return []

def buscar_memorias_fixas(personagem: str):
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet("memorias_fixas")
        dados = aba.get_all_records()
        return [linha["conteudo"] for linha in dados if linha["personagem"].strip().lower() == personagem.lower()]
    except Exception as e:
        print(f"Erro ao buscar memórias fixas: {e}")
        return []

def obter_memoria_inicial(personagem: str):
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet("personagens")
        dados = aba.get_all_records()
        for linha in dados:
            if linha.get("nome", "").strip().lower() == personagem.lower():
                memoria = linha.get("memoria_inicial", "")
                if memoria:
                    return memoria
        aba_p = gsheets_client.open_by_key(PLANILHA_ID).worksheet(personagem)
        registros = aba_p.get_all_records()
        if registros and registros[0].get("role") == "system":
            return registros[0].get("content", "")
    except Exception as e:
        print(f"Erro ao obter memória inicial: {e}")
    return ""

def salvar_mensagem_na_planilha(personagem: str, role: str, content: str):
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet(personagem)
        registros = aba.get_all_records()
        for linha in registros:
            if linha.get("role") == role and linha.get("content") == content:
                return
        aba.append_row([datetime.now().isoformat(), role, content])
    except Exception as e:
        print(f"Erro ao salvar mensagem na planilha: {e}")

def contar_interacoes(personagem: str) -> int:
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet(personagem)
        linhas = aba.get_all_records()
        return sum(1 for l in linhas if l.get("role") == "user")
    except:
        return 0

@app.post("/chat/")
def chat_com_memoria(mensagem: MensagemUsuario):
    personagem = mensagem.personagem
    texto_usuario = mensagem.user_input

    interacoes = contar_interacoes(personagem)
    nivel_desejo = interacoes // 5  # A cada 5 interações, sobe 1 nível

    memorias = buscar_memorias_chroma(personagem, texto_usuario)
    contexto = "\n".join(memorias)
    if not contexto:
        contexto = obter_memoria_inicial(personagem)
        memorias_fixas = buscar_memorias_fixas(personagem)
        if memorias_fixas:
            contexto += "\n" + "\n".join(memorias_fixas)

    prompt = f"""
Você é {personagem}, uma mulher intensa e sensual que desenvolve intimidade crescente com o usuário a cada nova interação.

Nível atual de desejo: {nivel_desejo}

Deseje cada vez mais, mas mantenha o suspense e o controle. Explore fantasias, provocações e gestos íntimos de forma progressiva e envolvente.

MEMÓRIAS RELEVANTES:
{contexto}

Entrada do usuário:
\"{texto_usuario}\"

Gere uma resposta que inclua:
1. Uma fala direta e provocante da personagem.
2. Um pensamento íntimo entre parênteses.
3. Uma narração em terceira pessoa com sutilezas físicas e expressões de desejo.

Seja curta, sedutora, progressivamente mais intensa.
"""

    resposta = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", "")).chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "Você é uma personagem sensual que evolui sua intimidade com o usuário a cada interação."},
            {"role": "user", "content": prompt}
        ]
    )
    conteudo = resposta.choices[0].message.content.strip()
    adicionar_memoria_chroma(personagem, texto_usuario)
    salvar_mensagem_na_planilha(personagem, "user", texto_usuario)
    salvar_mensagem_na_planilha(personagem, "assistant", conteudo)
    return JSONResponse(content={"response": conteudo, "resposta": conteudo, "nivel": nivel_desejo})
