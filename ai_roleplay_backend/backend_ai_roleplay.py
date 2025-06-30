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

def call_ai(mensagens, temperature=0.6, max_tokens=350):
    try:
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
        mensagens_validas = [m for m in mensagens if m['role'] in ["system", "user", "assistant", "tool", "function", "developer"]]
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=mensagens_validas,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[ERRO no call_ai] {e}")
        return f"Erro ao chamar IA: {e}"

def carregar_dados_personagem(nome_personagem: str):
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet("personagens")
        dados = aba.get_all_records()
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
        filtradas = [m for m in todas if m.get('personagem','').strip().lower() == nome_personagem.strip().lower()]
        filtradas.sort(key=lambda m: datetime.strptime(m.get('data', ''), "%Y-%m-%d"), reverse=True)
        return [f"[{m.get('tipo','')}] ({m.get('emoção','')}) {m.get('titulo','')} - {m.get('data','')}: {m.get('conteudo','')} (Relevância: {m.get('relevância','')})" for m in filtradas]
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
        valores = aba.get_all_values()
        if not valores:
            aba.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), texto, len(texto), "fixa"])
        else:
            aba.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), texto, len(texto)])
    except Exception as e:
        print(f"[ERRO ao salvar sinopse] {e}")

# EXPANSÃO DO PROMPT COM TODOS OS CAMPOS OPCIONAIS DA ABA PERSONAGENS

def expandir_prompt_com_dados(dados: dict, prompt_base: str) -> str:
    if dados.get('descrição curta') or dados.get('traços físicos'):
        prompt_base += f"\n\nDescrição física e estilo:\n{dados.get('descrição curta', '')}, {dados.get('traços físicos', '')}"
    if dados.get('humor_base'):
        prompt_base += f"\n\nHumor predominante: {dados['humor_base']}"
    if dados.get('objetivo_narrativo'):
        prompt_base += f"\nObjetivo da personagem nesta fase: {dados['objetivo_narrativo']}"
    if dados.get('traumas'):
        prompt_base += f"\nFeridas emocionais ou traumas marcantes: {dados['traumas']}"
    if dados.get('segredos'):
        prompt_base += f"\nSegredos guardados: {dados['segredos']}"
    if dados.get('estilo_fala'):
        prompt_base += f"\nEstilo de fala esperado: {dados['estilo_fala']}"
    if dados.get('regras_de_discurso'):
        prompt_base += f"\nRegras específicas de discurso: {dados['regras_de_discurso']}"
    if dados.get('relationship'):
        prompt_base += f"\nTipo de relação com {dados.get('user_name', 'usuário')}: {dados['relationship']}"
    return prompt_base
