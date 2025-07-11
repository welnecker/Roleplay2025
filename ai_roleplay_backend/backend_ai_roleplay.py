# backend_personagem_completo.py

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

# === FastAPI Setup ===
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === Models ===
class ChatRequest(BaseModel):
    user_input: str
    personagem: str
    regenerar: bool = False
    modo: str = "Normal"
    estado: str = "Neutro"

class PersonagemPayload(BaseModel):
    personagem: str

# === Função para buscar dados do personagem ===
def buscar_dados_personagem(nome):
    sheet = gsheets_client.open_by_key(PLANILHA_ID).worksheet("personagens")
    dados = sheet.get_all_records()
    for linha in dados:
        if linha.get("nome", "").strip().lower() == nome.strip().lower():
            return linha
    return {}

# === Função para buscar memórias fixas do personagem ===
def buscar_memorias_fixas(personagem):
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet("memorias_fixas")
        memorias = [l["conteudo"] for l in aba.get_all_records() if l["personagem"].strip().lower() == personagem.strip().lower()]
        return memorias
    except:
        return []

# === Função para buscar histórico recente ===
def buscar_historico_recentemente(personagem):
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet(personagem)
        valores = aba.get_all_values()
        return "\n".join(["{}: {}".format(l[1], l[2]) for l in valores[-10:] if len(l) >= 3])
    except:
        return ""

# === Montagem do prompt ===
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

# === Endpoint principal ===
@app.post("/chat/")
async def chat_with_ai(request: ChatRequest):
    personagem_dados = buscar_dados_personagem(request.personagem)
    if not personagem_dados:
        return JSONResponse(content={"erro": "Personagem não encontrado."}, status_code=404)

    prompt = montar_prompt(personagem_dados, request.user_input)

    headers = {
        "Authorization": f"Bearer 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",
        "Content-Type": "application/json"
    }
    data = {
        "model": "openrouter/openai/gpt-4",
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": request.user_input}
        ]
    }
    response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=data)

    if response.status_code != 200:
        print("Erro OpenRouter:", response.status_code, response.text)
        return JSONResponse(content={"erro": "Falha na resposta da IA."}, status_code=500)

    try:
        resposta = response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print("Erro ao decodificar resposta da IA:", e)
        return JSONResponse(content={"erro": "Erro ao processar resposta da IA."}, status_code=500)

    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet(request.personagem)
        agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        aba.append_row([agora, "user", request.user_input])
        aba.append_row([agora, "assistant", resposta])
    except Exception as e:
        print("Erro ao salvar conversa:", e)

    return {
        "resposta": resposta,
        "nivel": 0
    }

# === Endpoint para listar personagens visíveis ===
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
