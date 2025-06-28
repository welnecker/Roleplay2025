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

@app.post("/chat/")
def chat_with_ai(msg: Message):
    nome = msg.personagem
    user_input = msg.user_input.strip()

    if not nome or not user_input:
        return JSONResponse(content={"erro": "Personagem e mensagem são obrigatórios."}, status_code=400)

    # Carrega dados do personagem e valida
    dados = carregar_dados_personagem(nome)
    if not dados:
        return JSONResponse(content={"erro": "Personagem não encontrado."}, status_code=404)

    # Gera sinopse (resumo das últimas interações ou introdução)
    sinopse = gerar_resumo_ultimas_interacoes(nome)
    # Carrega memórias (detalhes importantes)
    memorias = carregar_memorias_do_personagem(nome)

    # Monta prompt com diretrizes, exemplos e contexto
    prompt_base = dados.get("prompt_base", "")
    contexto = dados.get("contexto", "")
    diretriz_positiva = dados.get("diretriz_positiva", "")
    diretriz_negativa = dados.get("diretriz_negativa", "")
    exemplo_narrador = dados.get("exemplo_narrador", "")
    exemplo_personagem = dados.get("exemplo_personagem", "")
    exemplo_pensamento = dados.get("exemplo_pensamento", "")

    # Adiciona instruções ao prompt
    prompt_base += f"

Diretrizes:
{diretriz_positiva}

Evite:
{diretriz_negativa}"
    prompt_base += f"

Exemplo de narração:
{exemplo_narrador}

Exemplo de fala:
{exemplo_personagem}

Exemplo de pensamento:
{exemplo_pensamento}"
    if contexto:
        prompt_base += f"

Contexto atual:
{contexto}"
    if sinopse:
        prompt_base += f"

Resumo recente:
{sinopse}"
    if memorias:
        prompt_base += "

Memórias importantes:
" + "
".join(memorias)

    # Prepara histórico de diálogo
    try:
        aba_personagem = gsheets_client.open_by_key(PLANILHA_ID).worksheet(nome)
        historico = aba_personagem.get_all_values()[-5:] if not msg.primeira_interacao else []
    except:
        historico = []

    # Monta mensagens para a IA
    mensagens = [{"role": "system", "content": prompt_base}]
    for linha in historico:
        if len(linha) >= 3:
            mensagens.append({"role": linha[1], "content": linha[2]})
    mensagens.append({"role": "user", "content": user_input})

    # Chama a IA
    resposta = call_ai(mensagens)

    # Salva no Google Sheets
    salvar_dialogo(nome, "user", user_input)
    salvar_dialogo(nome, "assistant", resposta)

    return {"response": resposta, "sinopse": sinopse}

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
                "foto": f"{GITHUB_IMG_URL}{p.get('nome','').strip()}.jpg"
            })
        return pers
    except Exception as e:
        return JSONResponse(content={"erro": str(e)}, status_code=500)

@app.get("/intro/")
def gerar_resumo_ultimas_interacoes(personagem: str):
    try:
        aba_sinopse = gsheets_client.open_by_key(PLANILHA_ID).worksheet(f"{personagem}_sinopse")
        sinopses = aba_sinopse.get_all_values()
        if sinopses:
            for s in reversed(sinopses):
                if len(s) >= 2 and s[1].strip().lower() != "resumo":
                    return {"resumo": s[1].strip()}
        aba_personagem = gsheets_client.open_by_key(PLANILHA_ID).worksheet(personagem)
        if len(aba_personagem.get_all_values()) < 3:
            dados = carregar_dados_personagem(personagem)
            intro = dados.get("introducao", "").strip()
            if intro:
                salvar_sinopse(personagem, intro)
                return {"resumo": intro}
        ultimas = aba_personagem.get_all_values()[-5:]
        mensagens = [{"role": l[1], "content": l[2]} for l in ultimas if len(l) >= 3]
        mensagens.insert(0, {"role": "system", "content": "Resuma as últimas interações como se fosse um capítulo anterior de uma história."})
        resumo = call_ai(mensagens, temperature=0.3, max_tokens=300)
        salvar_sinopse(personagem, resumo)
        return {"resumo": resumo}
    except Exception as e:
        return JSONResponse(content={"erro": str(e)}, status_code=500)
