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
import unicodedata
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

def normalizar(texto):
    return ''.join(c for c in unicodedata.normalize('NFD', texto.lower().strip()) if unicodedata.category(c) != 'Mn')

# Função: adiciona memória ao ChromaDB
def adicionar_memoria_chroma(personagem: str, conteudo: str):
    url = f"{CHROMA_BASE_URL}/api/v2/tenants/janio/databases/minha_base/collections/memorias/add"
    dados = {
        "documents": [conteudo],
        "ids": [f"{personagem}_{datetime.now().timestamp()}"],
        "metadata": {"personagem": personagem, "timestamp": str(datetime.now())}
    }
    requests.post(url, json=dados)

# Função: apaga todas as memórias da personagem no ChromaDB
def apagar_memorias_chroma(personagem: str):
    url = f"{CHROMA_BASE_URL}/api/v2/tenants/janio/databases/minha_base/collections/memorias/delete"
    dados = {
        "where": {"personagem": personagem}
    }
    resposta = requests.post(url, json=dados)
    return resposta.json()

# Função: busca memórias recentes do ChromaDB para a personagem
def buscar_memorias_chroma(personagem: str, texto: str):
    url = f"{CHROMA_BASE_URL}/api/v2/tenants/janio/databases/minha_base/collections/memorias/query"
    dados = {
        "query_texts": [texto],
        "n_results": 8,
        "where": {"personagem": personagem}
    }
    resposta = requests.post(url, json=dados)
    if resposta.status_code == 200:
        itens = resposta.json().get("documents", [])
        return [mem for grupo in itens for mem in grupo]  # achatar lista
    return []

# Função: salva mensagens no histórico (Google Sheets)
def salvar_mensagem_na_planilha(personagem: str, role: str, content: str):
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet(personagem)
        aba.append_row([datetime.now().isoformat(), role, content])
    except Exception as e:
        print(f"Erro ao salvar mensagem na planilha: {e}")

# Endpoint: limpa memórias da personagem
@app.post("/memorias_clear/")
def limpar_memorias_personagem(payload: PersonagemPayload):
    try:
        resultado = apagar_memorias_chroma(payload.personagem)
        return {"status": f"Memórias apagadas para {payload.personagem}.", "detalhes": resultado}
    except Exception as e:
        return JSONResponse(content={"erro": str(e)}, status_code=500)

# Endpoint: semeia memórias da aba 'personagens' para a personagem
@app.post("/memorias_seed/")
def semear_memorias_personagem(payload: PersonagemPayload):
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet("personagens")
        dados = aba.get_all_records()
        personagem_normalizado = normalizar(payload.personagem)
        personagem_dados = next(
            (p for p in dados if normalizar(p.get("nome", "")) == personagem_normalizado),
            None
        )
        if not personagem_dados:
            return JSONResponse(content={"erro": "Personagem não encontrada."}, status_code=404)

        campos = ["descrição curta", "traços físicos", "diretriz_positiva", "diretriz_negativa",
                  "exemplo_narrador", "exemplo_personagem", "exemplo_pensamento", "prompt_base",
                  "user_name", "relationship", "contexto", "humor_base", "objetivo_narrativo",
                  "traumas", "segredos", "estilo_fala", "regras_de_discurso"]

        sementes = [f"{campo.capitalize()}: {personagem_dados[campo]}" for campo in campos if personagem_dados.get(campo)]

        for memoria in sementes:
            adicionar_memoria_chroma(payload.personagem, memoria)

        return {"status": f"Memórias semeadas com sucesso para {payload.personagem}.", "total": len(sementes)}
    except Exception as e:
        return JSONResponse(content={"erro": str(e)}, status_code=500)

# ✅ NOVO: semear memórias fixas da aba 'memorias_fixas'
@app.post("/memorias_seed_fixas/")
def semear_memorias_fixas(payload: PersonagemPayload):
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet("memorias_fixas")
        dados = aba.get_all_records()
        memorias_personagem = [m for m in dados if normalizar(m.get("personagem", "")) == normalizar(payload.personagem)]

        if not memorias_personagem:
            return JSONResponse(content={"erro": "Nenhuma memória fixa encontrada."}, status_code=404)

        for linha in memorias_personagem:
            adicionar_memoria_chroma(payload.personagem, linha["conteudo"])

        return {"status": f"Memórias fixas adicionadas com sucesso para {payload.personagem}.", "total": len(memorias_personagem)}
    except Exception as e:
        return JSONResponse(content={"erro": str(e)}, status_code=500)

# ✅ NOVO: endpoint para listar personagens
@app.get("/personagens/")
def listar_personagens():
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet("personagens")
        dados = aba.get_all_records()

        personagens = []
        for linha in dados:
            personagens.append({
                "nome": linha.get("nome", ""),
                "descricao": linha.get("descrição curta", ""),
                "foto": f"{GITHUB_IMG_URL}{linha.get('nome', '').lower()}.jpg"
            })

        return personagens
    except Exception as e:
        return JSONResponse(content={"erro": str(e)}, status_code=500)

# Endpoint: conversa principal com IA e memórias
@app.post("/chat/")
def chat_com_personagem(dados: MensagemUsuario):
    try:
        if not dados.regenerar:
            salvar_mensagem_na_planilha(dados.personagem, "user", dados.user_input)

        # Recuperar memórias
        memorias = buscar_memorias_chroma(dados.personagem, dados.user_input)
        memorias_texto = "\n".join(memorias)

        prompt = f"""
Você é {dados.personagem}. Aja de forma coerente com os traços e estilo abaixo:
{memorias_texto}

Agora responda ao usuário com base nisso:
Usuário: {dados.user_input}
"""

        client = OpenAI()
        resposta = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Você é uma personagem de roleplay."},
                {"role": "user", "content": prompt}
            ]
        )
        resposta_texto = resposta.choices[0].message.content

        if not dados.regenerar:
            salvar_mensagem_na_planilha(dados.personagem, "assistant", resposta_texto)

        return {"resposta": resposta_texto}

    except Exception as e:
        return JSONResponse(content={"erro": str(e)}, status_code=500)
