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

def carregar_memorias_do_personagem(nome_personagem: str):
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet("memorias")
        todas = aba.get_all_records()
        filtradas = [m for m in todas if m.get('personagem','').strip().lower() == nome_personagem.strip().lower()]
        filtradas.sort(key=lambda m: datetime.strptime(m.get('data', ''), "%Y-%m-%d"), reverse=True)
        mems = []
        for m in filtradas:
            mems.append(f"[{m.get('tipo','')}] ({m.get('emoção','')}) {m.get('titulo','')} - {m.get('data','')}: {m.get('conteudo','')} (Relevância: {m.get('relevância','')})")
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
        valores = aba.get_all_values()
        if not valores:
            aba.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), texto, len(texto), "fixa"])
        else:
            aba.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), texto, len(texto)])
    except Exception as e:
        print(f"[ERRO ao salvar sinopse] {e}")

def gerar_resumo_ultimas_interacoes(nome_personagem: str) -> str:
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet(nome_personagem)
        dialogos = aba.get_all_values()
        if len(dialogos) < 3:
            return ""

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

        resumo = call_ai(prompt)
        if resumo and resumo.lower() != "resumo":
            if nome_personagem not in contador_interacoes:
                contador_interacoes[nome_personagem] = 1
            else:
                contador_interacoes[nome_personagem] += 1

            if contador_interacoes[nome_personagem] >= 3:
                salvar_sinopse(nome_personagem, resumo)
                contador_interacoes[nome_personagem] = 0
            return resumo
        else:
            print(f"[AVISO] Resumo inválido: '{resumo}'")
            return ""
    except Exception as e:
        print(f"[ERRO ao gerar resumo de interações] {e}")
        return ""

@app.post("/chat/")
def chat_with_ai(message: Message):
    try:
        personagem = message.personagem
        entrada_usuario = message.user_input.strip()

        dados = carregar_dados_personagem(personagem)
        if not dados:
            return JSONResponse(status_code=404, content={"error": "Character not found"})

        sinopse = gerar_resumo_ultimas_interacoes(personagem)
        memorias = carregar_memorias_do_personagem(personagem)

        user_name = dados.get("user_name", "Usuário")
        relacionamento = dados.get("relationship", "companheira")

        prompt_base = f"Você é {personagem}, {relacionamento} de {user_name}.\n"

        caracteristicas = []
        if dados.get("idade"):
            caracteristicas.append(f"tem {dados['idade']} anos")
        if dados.get("traços físicos"):
            caracteristicas.append(dados["traços físicos"])
        if dados.get("estilo fala"):
            caracteristicas.append(f"fala de forma {dados['estilo fala']}")
        if caracteristicas:
            prompt_base += f"Você {', '.join(caracteristicas)}.\n"

        prompt_base += "Continue exatamente de onde a história parou. Não reinvente elementos ou reinicie a história.\n"
        prompt_base += "Nunca contradiga a sinopse fixa inicial, ela define o cenário, a ambientação e o relacionamento.\n"
        if sinopse:
            prompt_base += f"Resumo recente: {sinopse}\n"
        if memorias:
            prompt_base += "\n\nMemórias importantes:\n" + "\n".join(memorias)

        mensagens = [
            {"role": "system", "content": prompt_base},
            {"role": "user", "content": entrada_usuario}
        ]

        resposta = call_ai(mensagens)
        salvar_dialogo(personagem, "user", entrada_usuario)
        salvar_dialogo(personagem, "assistant", resposta)

        return {"response": resposta, "sinopse": sinopse}
    except Exception as e:
        print(f"[ERRO /chat/] {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/intro/")
def get_intro(nome: str = Query(...), personagem: str = Query(...)):
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

        return {"resumo": gerar_resumo_ultimas_interacoes(personagem)}
    except Exception as e:
        print(f"[ERRO /intro/] {e}")
        return {"resumo": ""}

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
        return JSONResponse(status_code=500, content={"error": str(e)})
