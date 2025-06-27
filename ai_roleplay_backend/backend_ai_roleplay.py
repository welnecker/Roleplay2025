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

# === FastAPI ===
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


def call_ai(mensagens, temperature=0.3, max_tokens=100):
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
        return "Sorry, there was a problem generating the response."

# Funções auxiliares

def carregar_dados_personagem(nome_personagem: str):
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet("personagens")
        dados = aba.get_all_records()
        if dados:
            print("[DEBUG] Colunas em 'personagens':", dados[0].keys())
        encontrado_ignorar = None
        for p in dados:
            nome_planilha = p.get('nome', '').strip().lower()
            usar = str(p.get('usar', '')).strip().lower()
            print(f"[DEBUG] Verificando personagem: '{nome_planilha}', usar='{usar}'")
            if nome_planilha == nome_personagem.strip().lower():
                if usar == 'sim':
                    print(f"[DEBUG] Encontrado e válido: {p}")
                    return p
                if encontrado_ignorar is None:
                    encontrado_ignorar = p
        if encontrado_ignorar:
            print(f"[WARNING] Personagem '{nome_personagem}' encontrado mas 'usar' != 'sim', retornando mesmo assim.")
            return encontrado_ignorar
        print(f"[DEBUG] Nenhum personagem correspondeu ao nome '{nome_personagem}'.")
        return {}
    except Exception as e:
        print(f"[ERRO ao carregar dados do personagem] {e}")
        return {}


def carregar_memorias_do_personagem(nome_personagem: str):
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet("memorias")
        todas = aba.get_all_records()
        filtradas = [
            m for m in todas
            if m.get('personagem', '').strip().lower() == nome_personagem.strip().lower()
        ]
        try:
            filtradas.sort(
                key=lambda m: datetime.strptime(m.get('data', ''), "%Y-%m-%d"),
                reverse=True
            )
        except Exception:
            pass
        mems = []
        for m in filtradas:
            mems.append(
                f"[{m.get('tipo','')}] ({m.get('emoção','')}) {m.get('titulo','')} - "
                f"{m.get('data','')}: {m.get('conteudo','')} (Relevância: {m.get('relevância','')})"
            )
        return mems
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
        aba.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), texto, len(texto)])
    except Exception as e:
        print(f"[ERRO ao salvar sinopse] {e}")


def gerar_resumo_ultimas_interacoes(nome_personagem: str) -> str:
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet(nome_personagem)
        dialogos = aba.get_all_values()
        if len(dialogos) < 5:
            return ""

        ult = dialogos[-5:]
        txt = "\n".join([f"{l[1]}: {l[2]}" for l in ult if len(l) >= 3])

        prompt = [
            {
                "role": "system",
                "content": (
                    "Você é um narrador cinematográfico: escreva em terceira pessoa, "
                    "com descrições sensoriais vívidas (visão, tato, som), metáforas e emoções. "
                    "Revele pensamentos internos em itálico. Sempre em português."
                )
            },
            {
                "role": "assistant",
                "content": (
                    "Exemplo:\n"
                    "A tempestade tamborilava sobre o capacete de Regina, cada gota um sussurro gelado. "
                    "Quando avistou o letreiro em neon, um arrepio atravessou sua espinha — não só pelo frio, "
                    "mas pelas memórias que vieram com o motor desligando."
                )
            },
            {
                "role": "user",
                "content": (
                    "Agora, usando esse estilo, gere uma sequência envolvente a partir destes excertos:\n\n"
                    f"{txt}"
                )
            }
        ]

        resumo = call_ai(prompt, temperature=0.8, top_p=0.9, max_tokens=350)
        salvar_sinopse(nome_personagem, resumo)
        return resumo

    except Exception as e:
        print(f"[ERRO ao gerar resumo de interações] {e}")
        return ""
