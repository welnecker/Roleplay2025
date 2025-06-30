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

class Message(BaseModel):
    personagem: str
    user_input: str
    modo: str = "default"
    primeira_interacao: bool = False
    evento: str = None  # opcional


def call_ai(mensagens, temperature=0.6, max_tokens=350):
    try:
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
        mensagens_validas = [m for m in mensagens if m['role'] in ["system", "user", "assistant"]]
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
        for p in aba.get_all_records():
            if p.get('nome','').strip().lower() == nome_personagem.strip().lower():
                return p
    except Exception as e:
        print(f"[ERRO ao carregar dados do personagem] {e}")
    return {}


def carregar_memorias_do_personagem(nome_personagem: str):
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet("memorias")
        todas = aba.get_all_records()
        filtradas = [m for m in todas if m.get('personagem','').strip().lower() == nome_personagem.strip().lower()]
        filtradas.sort(key=lambda m: datetime.strptime(m.get('data',''), "%Y-%m-%d"), reverse=True)
        return [f"[{m.get('tipo')}] {m.get('titulo')} ({m.get('data')}): {m.get('conteudo')}" for m in filtradas]
    except Exception as e:
        print(f"[ERRO ao carregar memórias] {e}")
    return []


def salvar_dialogo(nome_personagem: str, role: str, conteudo: str):
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet(nome_personagem)
        aba.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), role, conteudo])
    except Exception as e:
        print(f"[ERRO ao salvar diálogo] {e}")


def salvar_sinopse(nome_personagem: str, texto: str):
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet(f"{nome_personagem}_sinopse")
        registros = aba.get_all_values()
        if not registros:
            aba.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), texto, len(texto), "fixa"])
        else:
            aba.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), texto, len(texto)])
    except Exception as e:
        print(f"[ERRO ao salvar sinopse] {e}")


def expandir_prompt_com_dados(dados: dict, prompt: str) -> str:
    # adiciona campos opcionais
    if dados.get('descrição curta') or dados.get('traços físicos'):
        prompt += f"\n\nDescrição física e estilo: {dados.get('descrição curta','')}, {dados.get('traços físicos','')}"
    for campo,label in [
        ('humor_base','Humor predominante'),
        ('objetivo_narrativo','Objetivo da personagem nesta fase'),
        ('traumas','Feridas emocionais ou traumas marcantes'),
        ('segredos','Segredos guardados'),
        ('estilo_fala','Estilo de fala esperado'),
        ('regras_de_discurso','Regras específicas de discurso'),
        ('relationship',f"Tipo de relação com {dados.get('user_name','usuário')}")
    ]:
        if dados.get(campo):
            prompt += f"\n{label}: {dados[campo]}"
    return prompt


def gerar_resumo_ultimas_interacoes(personagem: str) -> dict:
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet(personagem)
        registros = aba.get_all_values()
        if not registros:
            return {"resumo": carregar_dados_personagem(personagem).get('introducao','')}
        ult_assist = next((row[2] for row in reversed(registros) if row[1]=='assistant'), None)
        if not ult_assist:
            return {"resumo": carregar_dados_personagem(personagem).get('introducao','')}
        sys = [{"role":"system","content":"Resuma como um capítulo sensual e objetivo."},
               {"role":"assistant","content":ult_assist}]
        resumo = call_ai(sys, temperature=0.4, max_tokens=200)
        salvar_sinopse(personagem,resumo)
        return {"resumo":resumo}
    except Exception as e:
        print(f"[ERRO ao gerar sinopse] {e}")
        return {"resumo":""}


@app.post("/chat/")
def chat_with_ai(msg: Message):
    nome = msg.personagem.strip()
    texto = msg.user_input.strip()
    if not nome or not texto:
        return JSONResponse({"erro":"Personagem e mensagem são obrigatórios."}, status_code=400)

    dados = carregar_dados_personagem(nome)
    if not dados:
        return JSONResponse({"erro":"Personagem não encontrado."}, status_code=404)

    # base do prompt
    prompt = dados.get('prompt_base', '')
    # adiciona detalhes enriquecidos
    prompt = expandir_prompt_com_dados(dados, prompt)
    # adiciona sinopse e memórias
    sinopse = gerar_resumo_ultimas_interacoes(nome)
    memorias = carregar_memorias_do_personagem(nome)
    if sinopse.get('resumo'):
        prompt += f"\n\nResumo recente: {sinopse['resumo']}"
    if memorias:
        prompt += "\n\nMemórias importantes:\n" + "\n".join(memorias)

    # chamada à IA
    resposta = call_ai([{"role":"system","content":prompt}, {"role":"user","content":texto}])

    # salvar diálogo
    salvar_dialogo(nome, 'user', texto)
    salvar_dialogo(nome, 'assistant', resposta)

    return {"response":resposta, "sinopse": sinopse.get('resumo','')}
