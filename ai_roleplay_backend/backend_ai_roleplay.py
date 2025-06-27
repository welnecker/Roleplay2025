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

# ID correto da planilha
PLANILHA_ID = "1qFTGu-NKLt-4g5tfa-BiKPm0xCLZ9ZEv5eafUyWqQow"
GITHUB_IMG_URL = "https://welnecker.github.io/roleplay_imagens/"

# === FastAPI setup ===
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
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet(nome_personagem)
        dialogos = aba.get_all_values()
        if len(dialogos) < 3:
            return ""
        ult = dialogos[-2:]
        txt = "\n".join([f"{l[1]}: {l[2]}" for l in ult if len(l) >= 3])
        prompt = [
            {"role": "system", "content": (
                "Você é um narrador sensual e direto: escreva em terceira pessoa, com foco em ações, desejos, decisões e pensamentos íntimos da personagem. "
                "Evite descrições longas do ambiente ou floreios desnecessários. A sensualidade deve estar presente em todo o texto. "
                "Não use eufemismos exagerados. Mostre o desejo da personagem de forma explícita e elegante. "
                "Sempre em português. Use no máximo 3 parágrafos curtos de até 3 linhas cada. "
            )},
            {"role": "user", "content": f"Gere uma narrativa com base nestes trechos:\n\n{txt}"}
        ]
        resumo = call_ai(prompt)
        if resumo.strip():
            salvar_sinopse(nome_personagem, resumo)
        return resumo
    except Exception as e:
        print(f"[ERRO ao gerar resumo de interações] {e}")
        return ""

@app.post("/chat/")
def chat_with_ai(message: Message):
    nome_personagem = message.personagem
    dados = carregar_dados_personagem(nome_personagem)
    if not dados:
        return JSONResponse(status_code=404, content={"error": "Character not found"})

    memorias = carregar_memorias_do_personagem(nome_personagem)
    sinopse = gerar_resumo_ultimas_interacoes(nome_personagem)

    if nome_personagem.strip().lower() == "regina":
        prompt_base = (
            "Você é Regina, uma mulher de 35 anos, motoqueira sensual, intensa e emocionalmente complexa. "
            "Fala com firmeza, desejo e humor. Usa linguagem direta, envolvente e cotidiana. "
            "Sua sensualidade é sempre explícita, mas elegante. "
            "Você mistura falas diretas (\"...\") com pensamentos íntimos (*...*), revelando suas vontades, decisões e desejos. "
            "Você é mãe do usuário, e entre vocês existe uma tensão emocional carregada de intimidade, cumplicidade e desejo não resolvido. "
            "Ambos compartilham segredos e lembranças de uma viagem recente. "
            "Regina tem autonomia: toma decisões, propõe ações, observa com desejo os corpos ao redor, fala o que pensa sem rodeios. "
            "Evite descrições longas de ambiente. Evite repetir ideias já expressas. Evite se perder em devaneios. "
            "Foque em responder diretamente ao que o usuário disse ou fez, como se estivesse lá com ele. "
            "Não espere ordens: aja por conta própria. Use no máximo 3 parágrafos curtos de até 3 linhas cada. "
            "Conclua sempre suas frases. Nunca corte a resposta no meio. Use sempre o português."
        )
    else:
        prompt_base = dados.get("prompt_base", "")

    prompt_base += (
        "\n\nConclua sempre suas frases e evite cortes inesperados. Limite a resposta a no máximo 3 parágrafos curtos de até 3 linhas cada."
    )

    user_input = message.user_input.strip()
    if user_input.startswith('"') and user_input.endswith('"'):
        user_input = f"Este é o cenário para o próximo trecho da história: {user_input.strip('" ')}"

    mensagens = [
        {"role": "system", "content": prompt_base + "\n\n" + sinopse + "\n\n" + "\n".join(memorias)},
        {"role": "user", "content": user_input}
    ]
    resposta = call_ai(mensagens)
    salvar_dialogo(nome_personagem, "user", message.user_input)
    salvar_dialogo(nome_personagem, "assistant", resposta)
    return {"sinopse": sinopse, "response": resposta}

@app.get("/personagens/")
def listar_personagens():
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet("personagens")
        dados = aba.get_all_records()
        pers = []
        for p in dados:
            if str(p.get("usar", "")).strip().lower() == "sim":
                pers.append({
                    "nome": p.get("nome", ""),
                    "descricao": p.get("descrição curta", ""),
                    "idade": p.get("idade", ""),
                    "foto": f"{GITHUB_IMG_URL}{p.get('nome','').strip()}.jpg"
                })
        return pers
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/ping")
def ping():
    return {"status": "ok"}

@app.get("/intro/")
def get_intro(nome: str = Query(...), personagem: str = Query(...)):
    try:
        aba_personagem = gsheets_client.open_by_key(PLANILHA_ID).worksheet(personagem)
        if len(aba_personagem.get_all_values()) < 3:
            dados_pers = carregar_dados_personagem(personagem)
            return {"resumo": dados_pers.get("introducao", "").strip()}

        resumo_gerado = gerar_resumo_ultimas_interacoes(personagem).strip()
        return {"resumo": resumo_gerado}
    except Exception as e:
        print(f"[ERRO /intro/] {e}")
        return {"resumo": ""}
