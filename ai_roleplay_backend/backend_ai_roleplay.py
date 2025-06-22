from fastapi import FastAPI, Request, Query
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from datetime import datetime
import json
import os
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from fastapi.responses import JSONResponse
from dateutil import parser as dateparser
from openai import OpenAI

# --- Estados e modos ---
states = ["padrão"]

modes = {
    "romântico": "texto padrão romântico",
    "cotidiano": "texto cotidiano",
    "sexy": "texto sexy"
}

# --- Funções auxiliares ---
def gerar_prompt_base(nome_usuario):
    return f"Sinopse gerada para {nome_usuario}."

def is_blocked_response(resposta_ia: str) -> bool:
    censura = [
        "desculpe, não posso ajudar com isso", "não posso continuar com esse assunto",
        "não sou capaz de ajudar nesse tema", "como uma ia de linguagem",
        "não posso fornecer esse conteúdo", "não posso responder a esse pedido",
        "não estou autorizada", "minhas diretrizes não permitem",
        "me desculpe, mas não posso", "não posso criar esse conteúdo"
    ]
    return any(msg in resposta_ia.lower() for msg in censura)

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
        load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("Chave da OpenAI não encontrada.")
        openai_client = OpenAI(api_key=api_key)
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=mensagens,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content.strip()
    else:
        raise ValueError("Modelo não reconhecido: use 'gpt' ou 'lmstudio'.")

# --- Setup planilha Google ---
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]
google_creds_json = os.environ["GOOGLE_CREDS_JSON"]
creds_dict = json.loads(google_creds_json)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
gsheets_client = gspread.authorize(creds)
sheet = gsheets_client.open_by_key("1qFTGu-NKLt-4g5tfa-BiKPm0xCLZ9ZEv5eafUyWqQow").worksheet("mensagens")

# --- API FastAPI ---
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Message(BaseModel):
    user_input: str
    score: int
    modo: str = "romântico"
    modelo: str = "gpt"

@app.get("/intro/")
def obter_intro(nome: str = Query("Janio")):
    try:
        nome_usuario = nome
        system_prompt_base = gerar_prompt_base(nome_usuario)
        linhas = sheet.get_all_values()[1:]
        registros = sorted(
            [(dateparser.parse(l[0]), l[1], l[2]) for l in linhas if l[0] and l[1] and l[2]],
            key=lambda x: x[0], reverse=True
        )
        if not registros:
            return JSONResponse(content={
                "resumo": "No capítulo anterior... Nada aconteceu ainda.",
                "response": "",
                "state": states[0],
                "new_score": 0,
                "tokens": 0
            })
        bloco_atual = [registros[0]]
        for i in range(1, len(registros)):
            if (bloco_atual[-1][0] - registros[i][0]).total_seconds() <= 600:
                bloco_atual.append(registros[i])
            else:
                break
        bloco_atual = list(reversed(bloco_atual))
        horario_referencia = bloco_atual[0][0].strftime("%d/%m/%Y às %H:%M")
        dialogo = "\n".join(
            [f"{nome_usuario}: {r[2]}" if r[1].lower() == "usuário" else f"Jennifer: {r[2]}" for r in bloco_atual]
        )
        prompt_intro = (
            "Gere uma sinopse como se fosse uma novela popular, com linguagem simples, leve e natural. "
            "Comece com 'No capítulo anterior...' e resuma sem prever o futuro. "
            f"A conversa aconteceu em {horario_referencia}."
        )

        resumo = call_ai([
            {"role": "system", "content": prompt_intro},
            {"role": "user", "content": dialogo}
        ], modelo="gpt", temperature=0.6, max_tokens=500)

        usage = len(resumo.split())
        plan_sinopse = gsheets_client.open_by_key("1qFTGu-NKLt-4g5tfa-BiKPm0xCLZ9ZEv5eafUyWqQow").worksheet("sinopse")
        plan_sinopse.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), resumo, usage])

        return {
            "resumo": resumo,
            "response": "",
            "state": states[0],
            "new_score": 0,
            "tokens": usage
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    
    # <- FORA de qualquer função
class ChatRequest(BaseModel):
    user_input: str
    score: int
    modo: str
    modelo: str

@app.get("/intro/")
def obter_intro(nome: str = Query("Janio")):
    try:
        nome_usuario = nome
        system_prompt_base = gerar_prompt_base(nome_usuario)
        linhas = sheet.get_all_values()[1:]
        registros = sorted(
            [(dateparser.parse(l[0]), l[1], l[2]) for l in linhas if l[0] and l[1] and l[2]],
            key=lambda x: x[0], reverse=True
        )
        if not registros:
            return JSONResponse(content={
                "resumo": "No capítulo anterior... Nada aconteceu ainda.",
                "response": "",
                "state": states[0],
                "new_score": 0,
                "tokens": 0
            })
        bloco_atual = [registros[0]]
        for i in range(1, len(registros)):
            if (bloco_atual[-1][0] - registros[i][0]).total_seconds() <= 600:
                bloco_atual.append(registros[i])
            else:
                break
        bloco_atual = list(reversed(bloco_atual))
        horario_referencia = bloco_atual[0][0].strftime("%d/%m/%Y às %H:%M")
        dialogo = "\n".join(
            [f"{nome_usuario}: {r[2]}" if r[1].lower() == "usuário" else f"Jennifer: {r[2]}" for r in bloco_atual]
        )
        prompt_intro = (
            "Gere uma sinopse como se fosse uma novela popular, com linguagem simples, leve e natural. "
            "Comece com 'No capítulo anterior...' e resuma sem prever o futuro. "
            f"A conversa aconteceu em {horario_referencia}."
        )

        resumo = call_ai([
            {"role": "system", "content": prompt_intro},
            {"role": "user", "content": dialogo}
        ], modelo="gpt", temperature=0.6, max_tokens=500)

        usage = len(resumo.split())
        plan_sinopse = gsheets_client.open_by_key("1qFTGu-NKLt-4g5tfa-BiKPm0xCLZ9ZEv5eafUyWqQow").worksheet("sinopse")
        plan_sinopse.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), resumo, usage])

        return {
            "resumo": resumo,
            "response": "",
            "state": states[0],
            "new_score": 0,
            "tokens": usage
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/chat/")
def chat_endpoint(payload: ChatRequest):
    try:
        resposta_ia = call_ai(
            [{"role": "user", "content": payload.user_input}],
            modelo=payload.modelo,
            temperature=0.85,
            max_tokens=600
        )

        # Acessar a aba "mensagens"
        worksheet = gsheets_client.open_by_key("1qFTGu-NKLt-4g5tfa-BiKPm0xCLZ9ZEv5eafUyWqQow").worksheet("mensagens")

        # Gerar timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Gravar a mensagem do usuário e da Jennifer
        worksheet.append_row([timestamp, "usuário", payload.user_input])
        worksheet.append_row([timestamp, "jennifer", resposta_ia])

        return {
            "response": resposta_ia,
            "new_score": payload.score,
            "state": states[0],
            "modo": payload.modo
        }

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend_ai_roleplay:app", host="0.0.0.0", port=8000, reload=True)

