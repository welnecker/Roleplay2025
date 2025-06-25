# -*- coding: utf-8 -*-

# === 1. Importações e setup ===
from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from fastapi.responses import JSONResponse
from openai import OpenAI
import json
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# === 2. Setup Google Sheets ===
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_dict = json.loads(os.environ["GOOGLE_CREDS_JSON"])
if "private_key" in creds_dict:
    creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
gsheets_client = gspread.authorize(creds)

PLANILHA_ID = "1qFTGu-NKLt-4g5tfa-BiKPm0xCLZ9ZEv5eafUyWqQow"
GITHUB_IMG_URL = "https://welnecker.github.io/roleplay_imagens/"

# === 3. FastAPI setup ===
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Message(BaseModel):
    user_input: str
    score: int
    modo: str = "romântico"
    personagem: str = "Jennifer"

def call_ai(mensagens, temperature=0.88, max_tokens=750):
    openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=mensagens,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content.strip()

# === Funções relacionadas a personagens e memórias ===
def carregar_dados_personagem(nome_personagem: str):
    aba_pers = gsheets_client.open_by_key(PLANILHA_ID).worksheet("personagens")
    dados = aba_pers.get_all_records()
    for p in dados:
        if p['nome'].strip().lower() == nome_personagem.strip().lower() and p.get("usar", "").strip().lower() == "sim":
            return p
    return {}

def carregar_memorias_do_personagem(nome_personagem: str):
    aba_memorias = gsheets_client.open_by_key(PLANILHA_ID).worksheet("memorias")
    todas = aba_memorias.get_all_records()
    return [m["conteudo"] for m in todas if m.get("personagem", "").strip().lower() == nome_personagem.strip().lower()]

def salvar_dialogo(nome_personagem: str, role: str, conteudo: str):
    try:
        aba_dialogo = gsheets_client.open_by_key(PLANILHA_ID).worksheet(nome_personagem)
        nova_linha = [datetime.now().strftime("%Y-%m-%d %H:%M:%S"), role, conteudo]
        aba_dialogo.append_row(nova_linha)
    except Exception as e:
        print(f"[ERRO ao salvar diálogo] {e}")

def gerar_sinopse(nome_personagem: str):
    try:
        aba_dialogo = gsheets_client.open_by_key(PLANILHA_ID).worksheet(nome_personagem)
        dialogos = aba_dialogo.get_all_values()
        if len(dialogos) < 5:
            return
        ultimas_interacoes = dialogos[-5:]
        texto_interacoes = "\n".join(f"{linha[1]}: {linha[2]}" for linha in ultimas_interacoes)

        prompt_sinopse = f"""Faça uma breve sinopse narrando as últimas interações:\n{texto_interacoes}\nSinopse:"""

        sinopse = call_ai([{"role": "user", "content": prompt_sinopse}], temperature=0.5, max_tokens=150)

        aba_sinopse = gsheets_client.open_by_key(PLANILHA_ID).worksheet(f"{nome_personagem}_sinopse")
        nova_linha = [datetime.now().strftime("%Y-%m-%d %H:%M:%S"), sinopse, len(sinopse.split())]
        aba_sinopse.append_row(nova_linha)
    except Exception as e:
        print(f"[ERRO ao gerar sinopse] {e}")

def carregar_ultima_sinopse(nome_personagem: str) -> str:
    try:
        aba_sinopse = gsheets_client.open_by_key(PLANILHA_ID).worksheet(f"{nome_personagem}_sinopse")
        sinopses = aba_sinopse.get_all_values()
        if not sinopses:
            return ""
        return f"No capítulo anterior: {sinopses[-1][1]}\n\n"
    except Exception as e:
        print(f"[ERRO ao carregar sinopse] {e}")
        return ""

@app.post("/chat/")
def chat_with_ai(message: Message):
    nome_personagem = message.personagem
    dados_pers = carregar_dados_personagem(nome_personagem)

    memorias = carregar_memorias_do_personagem(nome_personagem)
    sinopse = carregar_ultima_sinopse(nome_personagem)

    prompt_base = f"""{sinopse}Você é {nome_personagem}, personagem de {dados_pers.get('idade')} anos.\nDescrição: {dados_pers.get('descrição curta')}\nEstilo: {dados_pers.get('estilo fala')}\nEmocional: {dados_pers.get('estado_emocional')}"""

    prompt_memorias = "\n".join(memorias)

    mensagens = [
        {"role": "system", "content": prompt_base + "\n" + prompt_memorias},
        {"role": "user", "content": message.user_input}
    ]

    resposta_ia = call_ai(mensagens)

    salvar_dialogo(nome_personagem, "user", message.user_input)
    salvar_dialogo(nome_personagem, "assistant", resposta_ia)

    if len(gsheets_client.open_by_key(PLANILHA_ID).worksheet(nome_personagem).get_all_values()) % 10 == 0:
        gerar_sinopse(nome_personagem)

    return {"response": resposta_ia, "modo": message.modo}

@app.get("/personagens/")
def listar_personagens():
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet("personagens")
        dados = aba.get_all_records()
        personagens = []
        for p in dados:
            if str(p.get("usar", "")).strip().lower() != "sim":
                continue
            nome = p.get("nome", "")
            personagens.append({
                "nome": nome,
                "descricao": p.get("descrição curta", ""),
                "idade": p.get("idade", ""),
                "estilo": p.get("estilo fala", ""),
                "estado_emocional": p.get("estado_emocional", ""),
                "foto": f"{GITHUB_IMG_URL}{nome.strip()}.jpg"
            })
        return personagens
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
