from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from datetime import datetime
import json
import os
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# === Google Sheets Setup ===
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

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
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
async def chat_with_ai(request: ChatRequest):
    personagem_dados = buscar_dados_personagem(request.personagem)
    if not personagem_dados:
        return JSONResponse(content={"erro": "Personagem não encontrado."}, status_code=404)

    memoria_inicial = personagem_dados.get("memoria_inicial", "")
    if memoria_inicial:
        adicionar_memoria_chroma(request.personagem, memoria_inicial)

    prompt = montar_prompt(personagem_dados, request.user_input)

    if request.plataforma == "openai":
        resposta_raw, _ = usar_openai(prompt)
    elif request.plataforma == "openrouter":
        resposta_raw, _ = usar_openrouter(prompt, personagem_dados.get("prompt_base", ""))
    elif request.plataforma == "local":
        resposta_raw, _ = usar_local_llm(prompt)
    else:
        return JSONResponse(content={"erro": "Plataforma não suportada."}, status_code=400)

    resposta = resposta_raw if isinstance(resposta_raw, str) else resposta_raw.get("resposta", "[Erro ao gerar resposta com IA]")

    if request.traduzir and request.plataforma == "openai":
        resposta = traduzir_texto(resposta)

    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet(request.personagem)
        agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        aba.append_row([agora, "user", request.user_input])
        aba.append_row([agora, "assistant", resposta])
    except Exception as e:
        print("Erro ao salvar conversa:", e)

    adicionar_memoria_chroma(request.personagem, resposta)

    return {
        "resposta": resposta,
        "nivel": 0
    }


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


def usar_openrouter(prompt, prompt_base):
    headers = {
        "Authorization": f"Bearer {os.environ.get('OPENROUTER_API_KEY')}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://amaprojeto.site",
        "X-Title": "Roleplay2025"
    }
    payload = {
        "model": "nousresearch/hermes-2-pro-llama-3-8b",
        "messages": [
            {"role": "system", "content": prompt_base or "Você é uma personagem fictícia com memória."},
            {"role": "user", "content": prompt}
        ]
    }
    try:
        response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload)
        response.raise_for_status()
        resposta = response.json()
        print("Resposta bruta do OpenRouter:", resposta)
        if "choices" in resposta and len(resposta["choices"]) > 0:
            return resposta["choices"][0]["message"]["content"], 0
        else:
            return {"resposta": "[Resposta inválida ou incompleta do modelo Hermes 2 Pro]"}, 0
    except Exception as e:
        print("Erro na resposta do OpenRouter:", e)
        return {"resposta": "[Erro ao gerar resposta com Hermes 2 Pro]"}, 0


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


def adicionar_memoria_chroma(personagem, conteudo):
    url = f"{CHROMA_BASE_URL}/api/v2/tenants/janio/databases/minha_base/collections/memorias/add"
    dados = {
        "documents": [conteudo],
        "ids": [f"{personagem}_{datetime.now().timestamp()}"],
        "metadata": {"personagem": personagem}
    }
    requests.post(url, json=dados)


def buscar_dados_personagem(nome):
    sheet = gsheets_client.open_by_key(PLANILHA_ID).worksheet("personagens")
    dados = sheet.get_all_records()
    for linha in dados:
        if linha.get("nome", "").strip().lower() == nome.strip().lower():
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


def buscar_historico_recentemente(personagem):
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet(personagem)
        valores = aba.get_all_values()
        return "\n".join(["{}: {}".format(l[1], l[2]) for l in valores[-10:] if len(l) >= 3])
    except:
        return ""


def montar_prompt(personagem_dados: dict, user_input: str):
    campos = [
        "essencia_personagem", "tecnicas_atuacao", "tecnica_narracao", "tecnica_pensamento",
        "cenografia", "auto_definicao", "gatilhos_emocionais", "valores_conflitos"
    ]
    prompt = f"Você está interpretando o personagem: {personagem_dados.get('nome', 'Desconhecido')}\n"
    prompt += f"Idade: {personagem_dados.get('idade', 'não especificada')}\n"
    prompt += f"Aparência: {personagem_dados.get('aparencia', '')}\n\n"
    for campo in campos:
        conteudo = personagem_dados.get(campo, "")
        if conteudo:
            prompt += f"[{campo.upper()}]\n{conteudo}\n\n"
    memorias = buscar_memorias_fixas(personagem_dados.get("nome", ""))
    if memorias:
        prompt += f"[MEMÓRIAS FIXAS]\n" + "\n".join(memorias) + "\n\n"
    historico = buscar_historico_recentemente(personagem_dados.get("nome", ""))
    if historico:
        prompt += f"[HISTÓRICO RECENTE]\n{historico}\n\n"
    prompt += f"[MENSAGEM DO USUÁRIO]\n{user_input}\n"
    return prompt


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
