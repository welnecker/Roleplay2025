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

class Message(BaseModel):
    personagem: str
    user_input: str
    modo: str = "default"
    primeira_interacao: bool = False

contador_interacoes = {}

def call_ai(mensagens, temperature=0.3, max_tokens=280):
    try:
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=mensagens,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[ERRO no call_ai] {e}")
        return ""

def carregar_dados_personagem(nome_personagem: str):
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet("personagens")
        dados = aba.get_all_records()
        if dados:
            for p in dados:
                if p.get('nome','').strip().lower() == nome_personagem.strip().lower():
                    return p
        return {}
    except Exception as e:
        print(f"[ERRO ao carregar dados do personagem] {e}")
        return {}

def salvar_dialogo(nome_personagem: str, role: str, conteudo: str):
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet(nome_personagem)
        linha = [datetime.now().strftime("%Y-%m-%d %H:%M:%S"), role, conteudo]
        aba.append_row(linha)
    except Exception as e:
        print(f"[ERRO ao salvar diálogo] {e}")

def salvar_sinopse(nome_personagem: str, texto: str):
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet(f"{nome_personagem}_sinopse")
        valores = aba.get_all_values()
        if not valores:
            aba.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), texto, len(texto), "fixa"])
        else:
            aba.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), texto, len(texto)])
    except Exception as e:
        print(f"[ERRO ao salvar sinopse] {e}")

@app.post("/chat/")
def chat_with_ai(msg: Message):
    nome = msg.personagem
    user_input = msg.user_input.strip()

    if not nome or not user_input:
        return JSONResponse(content={"erro": "Personagem e mensagem são obrigatórios."}, status_code=400)

    dados = carregar_dados_personagem(nome)
    if not dados:
        return JSONResponse(content={"erro": "Personagem não encontrado."}, status_code=404)

    prompt_base = dados.get("prompt_base", "")
    contexto = dados.get("contexto", "")
    diretriz_positiva = dados.get("diretriz_positiva", "")
    diretriz_negativa = dados.get("diretriz_negativa", "")
    exemplo_narrador = dados.get("exemplo_narrador", "")
    exemplo_personagem = dados.get("exemplo_personagem", "")
    exemplo_pensamento = dados.get("exemplo_pensamento", "")

    prompt_base += f"\n\nDiretrizes:\n{diretriz_positiva}\n\nEvite:\n{diretriz_negativa}"
    prompt_base += f"\n\nExemplo de narração:\n{exemplo_narrador}\n\nExemplo de fala:\n{exemplo_personagem}\n\nExemplo de pensamento:\n{exemplo_pensamento}"
    prompt_base += f"\n\nContexto atual:\n{contexto}\n"

    try:
        aba_personagem = gsheets_client.open_by_key(PLANILHA_ID).worksheet(nome)
        historico = aba_personagem.get_all_values()[-5:] if not msg.primeira_interacao else []
    except:
        historico = []

    mensagens = [
        {"role": "system", "content": prompt_base}
    ]

    for linha in historico:
        if len(linha) >= 3:
            mensagens.append({"role": linha[1], "content": linha[2]})

    mensagens.append({"role": "user", "content": user_input})
    resposta = call_ai(mensagens)

    salvar_dialogo(nome, "user", user_input)
    salvar_dialogo(nome, "assistant", resposta)

    return {"resposta": resposta, "foto": f"{GITHUB_IMG_URL}{nome.strip().lower()}.jpg"}

@app.get("/personagens/")
def listar_personagens():
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet("personagens")
        dados = aba.get_all_records()
        pers = []
        for p in dados:
            if str(p.get("usar", "")).strip().lower() != "sim":
                continue
            pers.append({
                "nome": p.get("nome", ""),
                "descricao": p.get("descrição curta", ""),
                "idade": p.get("idade", ""),
                "foto": f"{GITHUB_IMG_URL}{p.get('nome','').strip().lower()}.jpg"
            })
        return pers
    except Exception as e:
        return JSONResponse(content={"erro": str(e)}, status_code=500)

@app.get("/intro/")
def gerar_resumo_ultimas_interacoes(personagem: str):
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet(personagem)
        ultimas = aba.get_all_values()[-5:]
        mensagens = [{"role": l[1], "content": l[2]} for l in ultimas if len(l) >= 3]
        mensagens.insert(0, {"role": "system", "content": "Resuma as últimas interações como se fosse um capítulo anterior de uma história."})
        resumo = call_ai(mensagens, temperature=0.3, max_tokens=300)
        salvar_sinopse(personagem, resumo)
        return {"resumo": resumo}
    except Exception as e:
        return JSONResponse(content={"erro": str(e)}, status_code=500)
