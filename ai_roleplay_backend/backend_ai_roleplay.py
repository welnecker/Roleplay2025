# backendnovo.py atualizado com prompt sem uso de modo/estado

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
CHROMA_BASE_URL = "https://humorous-beauty-production.up.railway.app"

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class MensagemUsuario(BaseModel):
    user_input: str
    personagem: str
    regenerar: bool = False

class PersonagemPayload(BaseModel):
    personagem: str

# === Funções auxiliares ===
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

def mensagens_do_personagem(personagem: str):
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet(personagem)
        return aba.get_all_records()
    except:
        return []

@app.get("/mensagens/")
def obter_mensagens_personagem(personagem: str):
    try:
        sheet = gsheets_client.open_by_key(PLANILHA_ID)
        aba = sheet.worksheet(personagem)
        dados = aba.get_all_records()
        if dados and dados[0].get("role") == "system":
            return dados[1:]
        return dados
    except Exception as e:
        return JSONResponse(content={"erro": f"Erro ao acessar mensagens: {e}"}, status_code=500)

@app.post("/memoria_inicial/")
def inserir_memoria_inicial(payload: PersonagemPayload):
    personagem = payload.personagem
    conteudo = obter_memoria_inicial(personagem)
    if not conteudo:
        return JSONResponse(content={"erro": "Personagem desconhecida."}, status_code=400)
    adicionar_memoria_chroma(personagem, conteudo)
    return {"status": f"Memória inicial de {personagem} adicionada com sucesso.", "mensagem_inicial": conteudo}

@app.get("/intro/")
def obter_intro_personagem(personagem: str):
    texto = obter_memoria_inicial(personagem)
    if not texto:
        return JSONResponse(content={"erro": "Personagem desconhecida."}, status_code=400)
    return {"intro": texto}

@app.post("/chat/")
def chat_com_memoria(mensagem: MensagemUsuario):
    personagem = mensagem.personagem
    texto_usuario = mensagem.user_input
    memorias = buscar_memorias_chroma(personagem, texto_usuario)
    contexto = "\n".join(memorias)
    if not contexto:
        contexto = obter_memoria_inicial(personagem)
        memorias_fixas = buscar_memorias_fixas(personagem)
        if memorias_fixas:
            contexto += "\n" + "\n".join(memorias_fixas)

    total_interacoes = len([m for m in mensagens_do_personagem(personagem) if m['role'] == 'user'])
    nivel = total_interacoes // 5
    fill_index = total_interacoes % 5

    prompt = f"""
Personagem: {personagem}
Nível de intimidade com o usuário: {nivel}

MEMÓRIAS RELEVANTES:
{contexto}

MENSAGEM DO USUÁRIO:
\"{texto_usuario}\"

Sua resposta deve conter:
1. Uma fala direta da personagem (de preferência em primeira pessoa).
2. Um pensamento íntimo entre parênteses.
3. Uma narração em terceira pessoa (curta), com no máximo 2 frases.

Evite respostas longas. Use frases curtas, mas permita expressividade emocional e sensual. Varie ritmo e impacto.
Se o nível de intimidade estiver alto, aprofunde o envolvimento emocional ou permita avanços sutis e mais ousados.
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

    return JSONResponse(content={
        "response": conteudo,
        "resposta": conteudo,
        "nivel": nivel,
        "fill_index": fill_index
    })

@app.get("/personagens/")
def listar_personagens():
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet("personagens")
        dados = aba.get_all_records()
        personagens_validos = []
        for linha in dados:
            nome = linha.get("nome", "").strip()
            usar = linha.get("usar", "").strip().lower()
            if nome and usar == "sim":
                linha["foto"] = f"https://raw.githubusercontent.com/welnecker/roleplay_imagens/main/{nome}.jpg"
                personagens_validos.append(linha)
        return personagens_validos
    except Exception as e:
        return JSONResponse(status_code=500, content={"erro": str(e)})

@app.post("/memorias_clear/")
def apagar_memorias(payload: PersonagemPayload):
    try:
        personagem = payload.personagem
        url = f"{CHROMA_BASE_URL}/api/v2/tenants/janio/databases/minha_base/collections/memorias/delete"
        dados = {"where": {"personagem": personagem}}
        resposta = requests.post(url, json=dados)

        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet(personagem)
        total_linhas = len(aba.get_all_values())
        if total_linhas > 1:
            aba.batch_clear([f"A2:C{total_linhas}"])

        if resposta.status_code == 200:
            return {"status": f"Memórias de {personagem} apagadas com sucesso."}
        else:
            return JSONResponse(content={"erro": "Erro ao apagar memórias."}, status_code=resposta.status_code)
    except Exception as e:
        return JSONResponse(content={"erro": f"Erro inesperado: {e}"}, status_code=500)
