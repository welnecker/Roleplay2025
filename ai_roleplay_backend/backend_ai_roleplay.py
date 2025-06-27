# -*- coding: utf-8 -*-

from fastapi import FastAPI, Request, Query
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from fastapi.responses import JSONResponse
from openai import OpenAI
import json
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# === Setup Google Sheets ===
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_dict = json.loads(os.environ["GOOGLE_CREDS_JSON"])
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

# === Controle de introducao mostrada por personagem e usuario ===
introducao_mostrada_por_usuario = {}

class Message(BaseModel):
    user_input: str
    score: int
    modo: str = "romântico"
    personagem: str = "Jennifer"
    primeira_interacao: bool = False

def call_ai(mensagens, temperature=0.88, max_tokens=750):
    try:
        openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=mensagens,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[ERRO no call_ai] {e}")
        return "Sorry, there was a problem generating the response."

# === Funções auxiliares ===
def carregar_dados_personagem(nome_personagem: str):
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet("personagens")
        dados = aba.get_all_records()
        for p in dados:
            if p['nome'].strip().lower() == nome_personagem.strip().lower() and p.get("usar", "").strip().lower() == "sim":
                return p
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
            if m.get("personagem", "").strip().lower() == nome_personagem.strip().lower()
        ]

        try:
            filtradas.sort(key=lambda m: datetime.strptime(m.get("data", ""), "%Y-%m-%d"), reverse=True)
        except:
            pass

        memorias_relevantes = []
        for m in filtradas:
            tipo = m.get("tipo", "").strip()
            titulo = m.get("titulo", "").strip()
            data = m.get("data", "").strip()
            emocao = m.get("emoção", "").strip()
            relevancia = m.get("relevância", "").strip()
            conteudo = m.get("conteudo", "").strip()

            memoria = f"[{tipo}] ({emocao}) {titulo} - {data}: {conteudo} (Relevância: {relevancia})"
            memorias_relevantes.append(memoria)

        return memorias_relevantes

    except Exception as e:
        print(f"[ERRO ao carregar memórias] {e}")
        return []

def salvar_dialogo(nome_personagem: str, role: str, conteudo: str):
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet(nome_personagem)
        nova_linha = [datetime.now().strftime("%Y-%m-%d %H:%M:%S"), role, conteudo]
        aba.append_row(nova_linha)
    except Exception as e:
        print(f"[ERRO ao salvar diálogo] {e}")

def salvar_sinopse(nome_personagem: str, texto: str):
    try:
        aba_nome = f"{nome_personagem}_sinopse"
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet(aba_nome)
        linha = [datetime.now().strftime("%Y-%m-%d %H:%M:%S"), texto, len(texto)]
        aba.append_row(linha)
    except Exception as e:
        print(f"[ERRO ao salvar sinopse] {e}")

def gerar_resumo_ultimas_interacoes(nome_personagem: str) -> str:
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet(nome_personagem)
        dialogos = aba.get_all_values()
        if len(dialogos) < 5:
            return ""

        ultimas_interacoes = dialogos[-5:]
        dialogos_formatados = "\n".join(
            [f"{linha[1]}: {linha[2]}" for linha in ultimas_interacoes if len(linha) >= 3]
        )

        prompt = [
            {
                "role": "system",
                "content": "Summarize the following dialogue excerpts into a short, engaging narrative in the style of 'previously on...', like a gripping story continuation.",
            },
            {
                "role": "user",
                "content": dialogos_formatados,
            },
        ]

        resumo_narrativo = call_ai(prompt, max_tokens=280)
        salvar_sinopse(nome_personagem, resumo_narrativo)
        return f"Previously on...\n\n{resumo_narrativo}"
    except Exception as e:
        print(f"[ERRO ao gerar resumo de interações] {e}")
        return ""

@app.post("/chat/")
def chat_with_ai(message: Message):
    nome_personagem = message.personagem
    dados_pers = carregar_dados_personagem(nome_personagem)

    if not dados_pers:
        return JSONResponse(status_code=404, content={"error": "Character not found"})

    memorias = carregar_memorias_do_personagem(nome_personagem)
    sinopse = gerar_resumo_ultimas_interacoes(nome_personagem)

    user_name = dados_pers.get("user_name", "the user")
    relationship = dados_pers.get("relationship", "companion")
    contexto = dados_pers.get("contexto", "")
    introducao = dados_pers.get("introducao", "")

    prompt_base = f"You are {nome_personagem}, the {relationship} of {user_name}.\n"
    if contexto:
        prompt_base += f"Context: {contexto}\n"
    if introducao:
        prompt_base += f"Intro: {introducao}\n"
    prompt_base += dados_pers.get("prompt_base", "")

    if dados_pers.get("idade"):
        prompt_base += f"\nAge: {dados_pers['idade']} years."
    if dados_pers.get("traços físicos"):
        prompt_base += f"\nPhysical traits: {dados_pers['traços físicos']}"
    if dados_pers.get("diretriz_positiva"):
        prompt_base += f"\nDesired behavior: {dados_pers['diretriz_positiva']}"
    if dados_pers.get("diretriz_negativa"):
        prompt_base += f"\nAvoid: {dados_pers['diretriz_negativa']}"
    if dados_pers.get("exemplo"):
        prompt_base += f"\nExample of expected response:\n{dados_pers['exemplo']}"

    prompt_base += "\nSpeak in natural, sensual, and emotionally engaging English. Use evocative descriptions, physical gestures, and sensations. Take initiative — don’t ask repetitive or generic questions. Avoid robotic or reflective monologues. Show desire through action, body language, eye contact, and brief seductive dialogue. Blend thoughts in *italics* with spoken lines in quotation marks."

    prompt_memorias = "\n".join(memorias)

    mensagens = [
        {"role": "system", "content": prompt_base + "\n\n" + sinopse + "\n\n" + prompt_memorias},
        {"role": "user", "content": message.user_input}
    ]

    resposta_ia = call_ai(mensagens)

    salvar_dialogo(nome_personagem, "user", message.user_input)
    salvar_dialogo(nome_personagem, "assistant", resposta_ia)

    chave_usuario = f"{nome_personagem.lower()}_{dados_pers.get('user_name', 'user').lower()}"
    mostrar_intro = False

    if message.primeira_interacao and not introducao_mostrada_por_usuario.get(chave_usuario):
        mostrar_intro = True
        introducao_mostrada_por_usuario[chave_usuario] = True

    return {
        "sinopse": sinopse,
        "response": resposta_ia,
        "modo": message.modo,
        "introducao": introducao if mostrar_intro else ""
    }

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
                "foto": f"{GITHUB_IMG_URL}{nome.strip()}.jpg"
            })
        return personagens
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/ping")
def ping():
    return {"status": "ok"}

@app.get("/intro/")
def get_intro(nome: str = Query(...), personagem: str = Query(...)):
    try:
        # 1) Carrega o texto de introdução que você definiu na aba "personagens"
        dados_pers = carregar_dados_personagem(personagem)
        introducao_texto = dados_pers.get("introducao", "").strip()

        # 2) Tenta gerar a sinopse das últimas interações
        sinopse = gerar_resumo_ultimas_interacoes(personagem).strip()

        # 3) Se não houver sinopse, use a introdução; caso contrário, preferia a sinopse
        resumo = sinopse if sinopse else introducao_texto

        return {"resumo": resumo}
    except Exception as e:
        print(f"[ERRO /intro/] {e}")
        return {"resumo": ""}

