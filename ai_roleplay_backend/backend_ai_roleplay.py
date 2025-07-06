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

# Função: adiciona memória ao ChromaDB
def adicionar_memoria_chroma(personagem: str, conteudo: str):
    url = f"{CHROMA_BASE_URL}/api/v2/tenants/janio/databases/minha_base/collections/memorias/add"
    dados = {
        "documents": [conteudo],
        "ids": [f"{personagem}_{datetime.now().timestamp()}"],
        "metadata": {"personagem": personagem, "timestamp": str(datetime.now())}
    }
    requests.post(url, json=dados)

# Função: busca memórias recentes do ChromaDB para a personagem
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
        return [mem for grupo in itens for mem in grupo]  # achatar lista
    return []

# Função: salva mensagens no histórico (Google Sheets)
def salvar_mensagem_na_planilha(personagem: str, role: str, content: str):
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet(personagem)
        aba.append_row([datetime.now().isoformat(), role, content])
    except Exception as e:
        print(f"Erro ao salvar mensagem na planilha: {e}")

@app.get("/personagens/")
def listar_personagens():
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet("personagens")
        dados = aba.get_all_records()
        personagens = []
        for p in dados:
            if str(p.get("usar", "")).strip().lower() != "sim":
                continue
            nome = p.get("nome", "").strip()
            personagens.append({
                "nome": nome,
                "descricao": p.get("descrição curta", ""),
                "idade": p.get("idade", ""),
                "foto": f"{GITHUB_IMG_URL}{nome}.jpg"
            })
        return personagens
    except Exception as e:
        return JSONResponse(content={"erro": str(e)}, status_code=500)

@app.get("/mensagens/")
def obter_mensagens_personagem(personagem: str):
    try:
        sheet = gsheets_client.open_by_key(PLANILHA_ID)
        aba = sheet.worksheet(personagem)
        dados = aba.get_all_records()
        if dados and dados[0].get("role") == "system":
            return dados[1:]  # ignora introdução
        return dados
    except Exception as e:
        return JSONResponse(content={"erro": f"Erro ao acessar mensagens: {e}"}, status_code=500)

@app.post("/memoria_inicial/")
def inserir_memoria_inicial(personagem: str):
    conteudo = obter_memoria_inicial(personagem)
    if not conteudo:
        return JSONResponse(content={"erro": "Personagem desconhecida."}, status_code=400)
    adicionar_memoria_chroma(personagem, conteudo)
    return {"status": f"Memória inicial de {personagem} adicionada com sucesso."}

@app.get("/intro/")
def obter_intro_personagem(personagem: str):
    texto = obter_memoria_inicial(personagem)
    if not texto:
        return JSONResponse(content={"erro": "Personagem desconhecida."}, status_code=400)
    return {"intro": texto}

def obter_memoria_inicial(personagem: str):
    if personagem.lower() == "regina":
        return (
            "Regina é uma mulher de 35 anos, com corpo escultural e pele morena intensa. "
            "Tem cabelos soltos e volumosos, um olhar penetrante e uma presença que domina qualquer ambiente. "
            "Veste couro justo, pilota sua Harley com confiança e carrega um sorriso provocante nos lábios."
            "Sua personalidade é marcada por intensidade emocional, sensualidade natural e um toque de ironia. "
            "Ela evita reflexões longas, prefere frases curtas e diretas, e nunca esconde seus pensamentos — muitas vezes ousados. "
            "Sente um forte desejo de controlar o jogo da sedução, mas guarda em silêncio o medo da rejeição. "
            "Carrega o segredo de um caso proibido com um homem casado, que ainda a assombra em sonhos."
            "Neste momento, ela está em uma viagem sem rumo definido, tendo Donisete como amante e cúmplice emocional. "
            "A tensão entre os dois é carregada de desejo, mas também de dúvidas que ela raramente verbaliza."
        )
    elif personagem.lower() == "jennifer":
        return (
            "Jennifer acorda em um quarto escuro, iluminado apenas pela luz azul do computador. "
            "Ela sente que alguém a observa pela câmera desligada. Sussurros ecoam em sua mente. "
            "É noite. Algo a chama para fora, mas ela ainda não entende o que."
        )
    return ""

@app.post("/chat/")
def chat_com_memoria(mensagem: MensagemUsuario):
    personagem = mensagem.personagem
    texto_usuario = mensagem.user_input
    memorias = buscar_memorias_chroma(personagem, texto_usuario)
    contexto = "\n".join(memorias)
    if not contexto:
        contexto = obter_memoria_inicial(personagem)
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
    salvar_mensagem_na_planilha(personagem, "user", texto_usuario)
    salvar_mensagem_na_planilha(personagem, "assistant", conteudo)
    return JSONResponse(content={"response": conteudo, "resposta": conteudo})
