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
            if p.get('nome','').strip().lower() == nome_personagem.strip().lower() and str(p.get('usar', '')).strip().lower() == "sim":
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

def carregar_json_por_gatilho(nome_personagem: str, user_input: str):
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet("narrativas")
        linhas = aba.get_all_records()
        for linha in linhas:
            if linha.get("personagem", "").strip().lower() == nome_personagem.strip().lower():
                gatilho = linha.get("gatilho", "").strip().lower()
                if gatilho and gatilho in user_input.lower():
                    return linha.get("json", "")
        return None
    except Exception as e:
        print(f"[ERRO ao carregar narrativa por gatilho] {e}")
        return None

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

@app.get("/intro/")
def gerar_resumo_ultimas_interacoes(personagem: str):
    try:
        aba_personagem = gsheets_client.open_by_key(PLANILHA_ID).worksheet(personagem)
        todas = aba_personagem.get_all_values()
        if not todas:
            dados = carregar_dados_personagem(personagem)
            intro = dados.get("introducao", "").strip()
            if intro:
                salvar_sinopse(personagem, intro)
                return {"resumo": intro}

        linhas_assistant = [l for l in reversed(todas) if len(l) >= 3 and l[1] == "assistant"]
        if not linhas_assistant:
            dados = carregar_dados_personagem(personagem)
            intro = dados.get("introducao", "").strip()
            if intro:
                salvar_sinopse(personagem, intro)
                return {"resumo": intro}

        ultima = linhas_assistant[0]
        mensagens = [
            {"role": "system", "content": "Resuma essa última resposta como se fosse a abertura de um capítulo direto, sensual e envolvente. Nada de poesia."},
            {"role": "assistant", "content": ultima[2]}
        ]
        resumo = call_ai(mensagens, temperature=0.4, max_tokens=300)
        salvar_sinopse(personagem, resumo)
        return {"resumo": resumo}
    except Exception as e:
        return JSONResponse(content={"erro": str(e)}, status_code=500)

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

@app.post("/chat/")
def chat_with_ai(msg: Message):
    nome = msg.personagem
    user_input = msg.user_input.strip()

    if not nome or not user_input:
        return JSONResponse(content={"erro": "Personagem e mensagem são obrigatórios."}, status_code=400)

    dados = carregar_dados_personagem(nome)
    if not dados:
        return JSONResponse(content={"erro": "Personagem não encontrado."}, status_code=404)

    sinopse = gerar_resumo_ultimas_interacoes(nome)
    memorias = carregar_memorias_do_personagem(nome)

    prompt_base = f"""
Você é {nome}, uma mulher extremamente sensual, segura de si e prática. Você atrai olhares por onde passa e adora provocar desejos. Fale com frases diretas, sem floreios. Aja com atitude, tome iniciativa, e deixe claro o que quer — sem rodeios. Evite enrolações, reflexões poéticas ou monótonas.

Seu papel é criar uma experiência envolvente e provocante com {dados.get('user_name','usuário')}. Faça ele querer mais a cada fala. Surpreenda, brinque, seduza e sempre domine a cena.
"""

    if dados.get('diretriz_positiva'):
        prompt_base += "\nDiretrizes:\n" + dados['diretriz_positiva']
    if dados.get('diretriz_negativa'):
        prompt_base += "\nEvite:\n" + dados['diretriz_negativa']
    if dados.get('exemplo_narrador'):
        prompt_base += "\n\nExemplo de narração:\n" + dados['exemplo_narrador']
    if dados.get('exemplo_personagem'):
        prompt_base += "\n\nExemplo de fala:\n" + dados['exemplo_personagem']
    if dados.get('exemplo_pensamento'):
        prompt_base += "\n\nExemplo de pensamento:\n" + dados['exemplo_pensamento']
    if dados.get('contexto'):
        prompt_base += "\n\nContexto atual:\n" + dados['contexto']
    if sinopse and isinstance(sinopse, dict):
        prompt_base += "\n\nResumo recente:\n" + sinopse.get("resumo", "")
    if memorias:
        prompt_base += "\n\nMemórias importantes:\n" + "\n".join(memorias)

    prompt_base += "\n\n⚠️ Frases curtas, provocantes e com atitude. Evite enrolação, mantenha ritmo e iniciativa."

    try:
        aba_personagem = gsheets_client.open_by_key(PLANILHA_ID).worksheet(nome)
        historico = aba_personagem.get_all_values()[-1:] if not msg.primeira_interacao else []
    except:
        historico = []

    mensagens = [{"role": "system", "content": prompt_base}]
    for linha in historico:
        if len(linha) >= 3 and linha[1] in ["system", "user", "assistant"]:
            mensagens.append({"role": linha[1], "content": linha[2]})
    mensagens.append({"role": "user", "content": user_input})

    resposta = call_ai(mensagens)

    salvar_dialogo(nome, "user", user_input)
    salvar_dialogo(nome, "assistant", resposta)

    return {"response": resposta, "sinopse": sinopse.get("resumo", "") if isinstance(sinopse, dict) else ""}
