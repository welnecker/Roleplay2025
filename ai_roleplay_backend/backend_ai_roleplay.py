# backend.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from datetime import datetime
import json
import os
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# === Configurações ===
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
CHROMA_BASE_URL = "https://humorous-beauty-production.up.railway.app"
GITHUB_IMG_URL = "https://welnecker.github.io/roleplay_imagens/"

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
    modo: str = "Normal"
    estado: str = "Neutro"
    plataforma: str = "openai"
    traduzir: bool = True

class PersonagemPayload(BaseModel):
    personagem: str

@app.post("/chat/")
async def chat(mensagem: MensagemUsuario):
    if mensagem.plataforma == "openai":
        resposta, nivel = usar_openai(mensagem)
    elif mensagem.plataforma == "openrouter":
        resposta, nivel = usar_openrouter(mensagem)
    elif mensagem.plataforma == "local":
        resposta, nivel = usar_local_llm(mensagem)
    else:
        return JSONResponse(content={"erro": "Plataforma não suportada."}, status_code=400)

    if mensagem.traduzir:
        resposta = traduzir_texto(resposta)

    salvar_interacao(mensagem.personagem, mensagem.user_input, resposta)

    return JSONResponse(content={"resposta": resposta, "nivel": nivel})

def usar_openai(mensagem):
    from openai import OpenAI
    openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

    prompt = f"""
Personagem: {mensagem.personagem}
Modo: {mensagem.modo}
Estado emocional: {mensagem.estado}

MENSAGEM:
"{mensagem.user_input}"
"""

    response = openai_client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "Você é uma personagem de roleplay."},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content.strip(), 0

def usar_openrouter(mensagem):
    headers = {
        "Authorization": f"Bearer {os.environ.get('OPENROUTER_API_KEY')}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://amaprojeto.site",
        "X-Title": "Roleplay2025"
    }
    prompt = f"""
Personagem: {mensagem.personagem}
Modo: {mensagem.modo}
Estado emocional: {mensagem.estado}

MENSAGEM:
"{mensagem.user_input}"
"""
    payload = {
        "model": "gryphe/mythomax-l2-13b",
        "messages": [
            {"role": "system", "content": "Você é uma personagem de roleplay."},
            {"role": "user", "content": prompt}
        ]
    }
    response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload)
    if response.status_code == 200:
        dados = response.json()
        return dados["choices"][0]["message"]["content"], 0
    else:
        return f"Erro na OpenRouter: {response.text}", 0

def usar_local_llm(mensagem):
    return (f"[Local LLM] Resposta para: {mensagem.user_input}", 0)

def traduzir_texto(texto):
    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        r = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Traduza o seguinte texto para o português de forma natural."},
                {"role": "user", "content": texto}
            ]
        )
        return r.choices[0].message.content.strip()
    except Exception as e:
        return texto + f"\n\n(Erro na tradução: {str(e)})"

def salvar_interacao(personagem, user_input, resposta):
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet(personagem)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        aba.append_row([timestamp, "user", user_input])
        aba.append_row([timestamp, "assistant", resposta])
    except Exception as e:
        print("Erro ao salvar na planilha:", e)





# === Funções ===
def salvar_mensagem(personagem, role, content):
    aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet(personagem)
    aba.append_row([datetime.now().isoformat(), role, content])

def mensagens_personagem(personagem):
    aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet(personagem)
    return aba.get_all_records()

def obter_memoria_inicial(personagem):
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet("personagens")
        for linha in aba.get_all_records():
            if linha.get("nome", "").strip().lower() == personagem.lower():
                return linha.get("memoria_inicial", "")
    except:
        return ""
    return ""

def adicionar_memoria_chroma(personagem, conteudo):
    url = f"{CHROMA_BASE_URL}/api/v2/tenants/janio/databases/minha_base/collections/memorias/add"
    dados = {
        "documents": [conteudo],
        "ids": [f"{personagem}_{datetime.now().timestamp()}"],
        "metadata": {"personagem": personagem}
    }
    requests.post(url, json=dados)

def buscar_memorias_chroma(personagem, texto):
    url = f"{CHROMA_BASE_URL}/api/v2/tenants/janio/databases/minha_base/collections/memorias/query"
    dados = {
        "query_texts": [texto],
        "n_results": 8,
        "where": {"personagem": personagem}
    }
    resp = requests.post(url, json=dados)
    if resp.ok:
        return [x for grupo in resp.json().get("documents", []) for x in grupo]
    return []

def buscar_memorias_fixas(personagem):
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet("memorias_fixas")
        return [l["conteudo"] for l in aba.get_all_records() if l["personagem"].lower() == personagem.lower()]
    except:
        return []

# === Rotas ===
@app.get("/personagens/")
def listar_personagens():
    aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet("personagens")
    personagens = []
    for linha in aba.get_all_records():
        if linha.get("usar", "").strip().lower() == "sim":
            linha["foto"] = f"https://raw.githubusercontent.com/welnecker/roleplay_imagens/main/{linha['nome']}.jpg"
            personagens.append(linha)
    return personagens

@app.get("/mensagens/")
def obter_mensagens(personagem: str):
    try:
        dados = mensagens_personagem(personagem)
        if dados and dados[0].get("role") == "system":
            return dados[1:]
        return dados
    except Exception as e:
        return JSONResponse(content={"erro": str(e)}, status_code=500)

@app.get("/intro/")
def obter_intro(personagem: str):
    texto = obter_memoria_inicial(personagem)
    return {"intro": texto}

@app.post("/memoria_inicial/")
def inserir_memoria_inicial(payload: PersonagemPayload):
    memoria = obter_memoria_inicial(payload.personagem)
    adicionar_memoria_chroma(payload.personagem, memoria)
    return {"status": "Memória inserida", "mensagem_inicial": memoria}

@app.post("/chat/")
def chat(mensagem: MensagemUsuario):
    personagem = mensagem.personagem
    texto_usuario = mensagem.user_input

    # Busca contexto da memória
    contexto = "\n".join(buscar_memorias_chroma(personagem, texto_usuario))
    if not contexto:
        contexto = obter_memoria_inicial(personagem)

    memorias_fixas = buscar_memorias_fixas(personagem)
    if memorias_fixas:
        contexto += "\n" + "\n".join(memorias_fixas)

    # Cálculo de nível
    total_interacoes = len([m for m in mensagens_personagem(personagem) if m["role"] == "user"])
    nivel = total_interacoes // 5
    fill_index = total_interacoes % 5

    # Novo prompt sem numeração, com liberdade de estilo
    prompt = f"""
Personagem: {personagem}
Nível de intimidade: {nivel}

MEMÓRIAS:
{contexto}

MENSAGEM DO USUÁRIO:
\"{texto_usuario}\"

Responda com naturalidade e profundidade, combinando:
- Uma fala direta da personagem;
- Um pensamento íntimo (entre parênteses ou travessões);
- Uma breve narração em terceira pessoa, se fizer sentido.

Evite numerar os trechos. Use fluidez, criatividade e o estilo próprio da personagem. Foque em gerar conexão emocional realista.
"""

    resposta = OpenAI(api_key=os.environ.get("OPENAI_API_KEY")).chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "Você é uma personagem fictícia com memória e sensualidade."},
            {"role": "user", "content": prompt}
        ]
    )
    conteudo = resposta.choices[0].message.content.strip()

    adicionar_memoria_chroma(personagem, texto_usuario)
    salvar_mensagem(personagem, "user", texto_usuario)
    salvar_mensagem(personagem, "assistant", conteudo)

    return {
        "resposta": conteudo,
        "nivel": nivel,
        "fill_index": fill_index
    }

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
