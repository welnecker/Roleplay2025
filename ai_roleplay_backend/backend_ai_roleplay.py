from fastapi import FastAPI, Request, Query
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import json
import os
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from fastapi.responses import JSONResponse
from dateutil import parser as dateparser
from openai import OpenAI

# --- Inicialização ---
states = ["padrão"]

# --- Carregamento do .env somente em ambiente local ---
if not os.environ.get("RAILWAY_STATIC_URL"):  # ou use "RAILWAY_ENVIRONMENT" se preferir
    from dotenv import load_dotenv
    load_dotenv()  # Só carrega o .env se não estiver no Railway

# --- Setup GSheets ---
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]
google_creds_json = os.environ["GOOGLE_CREDS_JSON"]
creds_dict = json.loads(google_creds_json)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
gsheets_client = gspread.authorize(creds)
db = gsheets_client.open_by_key("1qFTGu-NKLt-4g5tfa-BiKPm0xCLZ9ZEv5eafUyWqQow")

# --- FastAPI + CORS ---
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Utilitários ---
def is_blocked_response(resposta_ia: str) -> bool:
    censura = [
        "desculpe, não posso ajudar com isso",
        "não posso continuar com esse assunto",
        "não sou capaz de ajudar nesse tema",
        "como uma ia de linguagem",
        "não sou capaz de fornecer esse conteúdo",
        "não posso responder a esse pedido",
        "não é apropriado",
        "não estou autorizada",
        "não posso cumprir esse pedido",
        "minhas diretrizes não permitem",
        "não é permitido",
        "não posso fornecer esse tipo de conteúdo",
        "como uma inteligência artificial",
        "me desculpe, mas não posso",
        "não posso criar esse conteúdo"
    ]
    texto = resposta_ia.lower()
    return any(msg in texto for msg in censura)

def call_ai(mensagens, modelo="gpt", temperature=0.88, max_tokens=750):
    if modelo == "lmstudio":
        url = "http://127.0.0.1:1234/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        data = {
            "model": "llama-3-8b-lexi-uncensored",
            "messages": mensagens,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        resp = requests.post(url, headers=headers, json=data, timeout=60)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    elif modelo == "gpt":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("Chave da OpenAI não encontrada. Verifique seu .env")
        openai_client = OpenAI(api_key=api_key)
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=mensagens,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content.strip()
    else:
        raise ValueError("Modelo de IA não reconhecido. Use 'gpt' ou 'lmstudio'.")

# --- Classes ---
class Message(BaseModel):
    user_input: str
    score: int
    modo: str = "cotidiano"
    modelo: str = "gpt"
    personagem: str = "Jennifer"

# --- Auxiliares de Personagem ---
def carregar_personagem(nome):
    aba_personagens = db.worksheet("personagens")
    dados = aba_personagens.get_all_records()
    for linha in dados:
        if linha['nome'].lower() == nome.lower():
            if 'foto' not in linha or not linha['foto']:
                linha['foto'] = f"https://raw.githubusercontent.com/welnecker/roleplay_imagens/main/{linha['nome']}.jpg"
            return linha
    raise ValueError(f"Personagem '{nome}' não encontrado na planilha.")

def construir_prompt_personagem(info, estado_emocional, modo):
    return f"""
Personagem: {info['nome']} ({info['idade']} anos)
Traços físicos: {info['traços físicos']}
Estilo de fala: {info['estilo fala']}
Estado emocional atual: {estado_emocional}
Modo atual: {modo}
Diretriz positiva: {info.get('diretriz_positiva', '')}
Diretriz negativa: {info.get('diretriz_negativa', '')}

ESTILO ESTRUTURAL:
- Estruture a resposta SEMPRE em 4 parágrafos:
  1. Fala direta (em primeira pessoa), entre 1-3 linhas, revelando emoção ou impulso.
  2. Pensamento íntimo em aspas (máx. 2 linhas).
  3. Nova fala direta com atitude.
  4. Narração em UMA linha (ação física, sensação ou gesto).

SEM ENROLAÇÃO. Personagem sente, fala, pensa e age com autenticidade.
"""

# --- Endpoint Principal ---
@app.post("/chat/")
def chat_with_ai(message: Message):
    personagem = message.personagem
    aba_mensagens = db.worksheet(personagem)

    linhas = aba_mensagens.get_all_values()[1:]
    memoria = [
        {"role": l[1], "content": l[2]}
        for l in linhas[-10:] if len(l) >= 3
    ]

    try:
        info = carregar_personagem(personagem)
        estado_emocional = info.get("estado_emocional", "neutro")
        prompt = construir_prompt_personagem(info, estado_emocional, message.modo)

        mensagens = [
            {"role": "system", "content": prompt},
            *memoria,
            {"role": "user", "content": message.user_input},
        ]

        resposta_ia = call_ai(mensagens, modelo=message.modelo)

        if is_blocked_response(resposta_ia):
            resposta_ia = "(A resposta foi censurada. Tente outra abordagem.)"

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        aba_mensagens.append_row([timestamp, "user", message.user_input])
        aba_mensagens.append_row([timestamp, "assistant", resposta_ia])

        return {
            "response": resposta_ia,
            "new_score": message.score,
            "state": estado_emocional,
            "modo": message.modo,
            "foto": info.get("foto", "")
        }

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# --- Endpoint: lista de personagens ---
@app.get("/personagens/")
def listar_personagens():
    try:
        aba = db.worksheet("personagens")
        dados = aba.get_all_records()
        personagens = []
        for linha in dados:
            nome = linha.get("nome")
            if not nome:
                continue
            imagem = linha.get("foto") or f"https://raw.githubusercontent.com/welnecker/roleplay_imagens/main/{nome}.jpg"
            personagens.append({
                "nome": nome,
                "descricao": linha.get("descrição curta", ""),
                "foto": imagem
            })
        return personagens
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
