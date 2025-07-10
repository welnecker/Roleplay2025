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
    dados_personagem = buscar_dados_personagem(mensagem.personagem)
    memoria_inicial = dados_personagem.get("memoria_inicial", "")
    memorias_fixas = buscar_memorias_fixas(mensagem.personagem)
    memorias_chroma = buscar_memorias_chroma(mensagem.personagem, mensagem.user_input)
    historico = buscar_historico_recentemente(mensagem.personagem)

    total_interacoes = len(historico)
    nivel = total_interacoes // 5
    fill_index = total_interacoes % 5

    prompt = f"""
{dados_personagem.get('prompt_base', '')}

Personagem: {mensagem.personagem}
Modo: {mensagem.modo}
Estado emocional: {mensagem.estado}
Nível de intimidade: {nivel}

Contexto atual:
{dados_personagem.get('contexto', '')}

Memórias fixas:
{memorias_fixas}

Memórias dinâmicas:
{memorias_chroma}

Histórico recente:
{historico}

Mensagem do usuário:
"{mensagem.user_input}"

Responda de forma natural e envolvente, usando:
- Fala direta da personagem;
- Pensamentos íntimos (entre parênteses ou travessões);
- Narração em terceira pessoa quando fizer sentido.
Evite numerar ou identificar os blocos. Foque em conexão emocional e autenticidade.
"""

    if mensagem.plataforma == "openai":
        resposta, _ = usar_openai(prompt)
    elif mensagem.plataforma == "openrouter":
        resposta, _ = usar_openrouter(prompt)
    elif mensagem.plataforma == "local":
        resposta, _ = usar_local_llm(prompt)
    else:
        return JSONResponse(content={"erro": "Plataforma não suportada."}, status_code=400)

    if mensagem.traduzir:
        resposta = traduzir_texto(resposta)

    salvar_interacao(mensagem.personagem, mensagem.user_input, resposta)
    adicionar_memoria_chroma(mensagem.personagem, resposta)

    return JSONResponse(content={"resposta": resposta, "nivel": nivel, "fill_index": fill_index})


def usar_openai(prompt):
    from openai import OpenAI
    openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    response = openai_client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "Você é uma personagem fictícia com memória e estilo próprio."},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content.strip(), 0


def usar_openrouter(prompt):
    headers = {
        "Authorization": f"Bearer {os.environ.get('OPENROUTER_API_KEY')}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://amaprojeto.site",
        "X-Title": "Roleplay2025"
    }
    payload = {
        "model": "gryphe/mythomax-l2-13b",
        "messages": [
            {"role": "system", "content": "Você é uma personagem fictícia com memória e estilo próprio."},
            {"role": "user", "content": prompt}
        ]
    }
    response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload)
    return response.json()["choices"][0]["message"]["content"], 0


def usar_local_llm(prompt):
    return f"[Local LLM] Resposta para: {prompt}", 0


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


def buscar_dados_personagem(personagem):
    aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet("personagens")
    for linha in aba.get_all_records():
        if linha.get("nome", "").strip().lower() == personagem.lower():
            return linha
    return {}


def buscar_memorias_fixas(personagem):
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet("memorias_fixas")
        return [l["conteudo"] for l in aba.get_all_records() if l["personagem"].lower() == personagem.lower()]
    except:
        return []


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


def adicionar_memoria_chroma(personagem, conteudo):
    url = f"{CHROMA_BASE_URL}/api/v2/tenants/janio/databases/minha_base/collections/memorias/add"
    dados = {
        "documents": [conteudo],
        "ids": [f"{personagem}_{datetime.now().timestamp()}"],
        "metadata": {"personagem": personagem}
    }
    requests.post(url, json=dados)


def buscar_historico_recentemente(personagem):
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet(personagem)
        valores = aba.get_all_values()
        return "\n".join(["{}: {}".format(l[1], l[2]) for l in valores[-10:] if len(l) >= 3])
    except:
        return ""

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
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet(personagem)
        return aba.get_all_records()
    except Exception as e:
        return JSONResponse(content={"erro": str(e)}, status_code=500)

@app.get("/intro/")
def obter_intro(personagem: str):
    dados = buscar_dados_personagem(personagem)
    return {"intro": dados.get("memoria_inicial", "")}

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
