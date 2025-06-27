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

environment = os.environ

# === Setup Google Sheets ===
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]
creds_dict = json.loads(environment.get("GOOGLE_CREDS_JSON", "{}"))
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

def call_ai(mensagens, temperature=0.8, max_tokens=220):
    try:
        client = OpenAI(api_key=environment.get("OPENAI_API_KEY", ""))
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

def carregar_memorias_do_personagem(nome_personagem: str):
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet("memorias")
        todas = aba.get_all_records()
        filtradas = [m for m in todas
                     if m.get('personagem','').strip().lower() == nome_personagem.strip().lower()]
        return [f"[{m.get('tipo')}] {m.get('conteudo')}" for m in filtradas]
    except Exception as e:
        print(f"[ERRO ao carregar memórias] {e}")
        return []

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
        aba.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), texto])
    except Exception as e:
        print(f"[ERRO ao salvar sinopse] {e}")

def gerar_resumo_ultimas_interacoes(nome_personagem: str) -> str:
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet(f"{nome_personagem}_sinopse")
        sinopses_existentes = aba.get_all_values()
        if sinopses_existentes and len(sinopses_existentes[-1]) > 1:
            ultimo_resumo = sinopses_existentes[-1][1].strip()
            if ultimo_resumo.lower() != "resumo":
                return ultimo_resumo

        aba_dialogos = gsheets_client.open_by_key(PLANILHA_ID).worksheet(nome_personagem)
        dialogos = aba_dialogos.get_all_values()
        if len(dialogos) < 3:
            dados_pers = carregar_dados_personagem(nome_personagem)
            return dados_pers.get("introducao", "").strip()

        ult = dialogos[-2:]
        txt = "\n".join([f"{l[1]}: {l[2]}" for l in ult if len(l) >= 3])
        prompt = [
            {"role": "system", "content": (
                "Você é um narrador sensual e direto. Escreva em terceira pessoa, apenas com base no conteúdo fornecido nas interações. "
                "Não invente lugares, ações ou eventos não mencionados. Concentre-se em resumir o que foi dito, destacando emoções, decisões e interações reais. "
                "Evite descrições de ambiente. Foque na conexão entre os personagens. "
                "Use no máximo 2 parágrafos curtos, com até 2 frases cada. Mantenha o texto sensual, direto e objetivo, em português."
            )},
            {"role": "user", "content": f"Gere uma narrativa com base nestes trechos:\n\n{txt}"}
        ]
        resumo = call_ai(prompt).strip()
        if resumo and resumo.lower() != "resumo":
            salvar_sinopse(nome_personagem, resumo)
            return resumo
        else:
            print(f"[AVISO] Resumo inválido: '{resumo}'")
            dados_pers = carregar_dados_personagem(nome_personagem)
            return dados_pers.get("introducao", "").strip()
    except Exception as e:
        print(f"[ERRO ao gerar resumo de interações] {e}")
        return ""

# ... (demais rotas e funções continuam como estavam)
