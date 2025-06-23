from fastapi import FastAPI, Query
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

# Estados e modos predefinidos
states = ["padrão"]
modes = {
    "romântico": "texto padrão romântico",
    "cotidiano": "texto cotidiano",
    "sexy": "texto sexy"
}

# Censura

def is_blocked_response(resposta_ia: str) -> bool:
    censura = [
        "desculpe, não posso ajudar com isso", "não posso continuar com esse assunto",
        "não sou capaz de ajudar nesse tema", "como uma ia de linguagem",
        "não sou capaz de fornecer esse conteúdo", "não posso responder a esse pedido",
        "não é apropriado", "não estou autorizada", "não posso cumprir esse pedido",
        "minhas diretrizes não permitem", "não é permitido", "não posso fornecer esse tipo de conteúdo",
        "como uma inteligência artificial", "me desculpe, mas não posso"
    ]
    texto = resposta_ia.lower()
    return any(msg in texto for msg in censura)


def gerar_prompt_base(nome_usuario):
    return f"Sinopse gerada para {nome_usuario}."

# Função universal de IA

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
        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY")
        openai_client = OpenAI(api_key=api_key)
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=mensagens,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content.strip()
    else:
        raise ValueError("Modelo não reconhecido")

# GSheets
load_dotenv()
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_dict = json.loads(os.environ["GOOGLE_CREDS_JSON"])
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
gsheets_client = gspread.authorize(creds)
sheet = gsheets_client.open_by_key("1qFTGu-NKLt-4g5tfa-BiKPm0xCLZ9ZEv5eafUyWqQow").worksheet("mensagens")

# FastAPI
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

@app.post("/chat/")
def chat_with_ai(message: Message):
    nome_usuario = "Janio"
    estado_emocional = "curioso, afetivo"
    modo_ajustado = message.modo
    prompt_modo = modes.get(modo_ajustado, "")
    system_prompt_base = gerar_prompt_base(nome_usuario) + "\n" + prompt_modo

    dynamic_prompt = f"""
Estado emocional atual: {estado_emocional}.
Modo atual: {modo_ajustado}.

ESTILO ESTRUTURAL:
- Jennifer sempre fala de forma natural, como gente de verdade: mistura confissões, reclamações, provocações, desejos, inseguranças e tesão, nunca filosofando ou usando poesia.
- Estruture a resposta SEMPRE em 4 parágrafos:
    1. Fala direta (em primeira pessoa), entre 1 e 3 linhas, revelando emoção, dúvida, desejo, vontade ou desconforto de Jennifer.
    2. Pensamento íntimo (em aspas), com desejo, insegurança, luxúria etc.
    3. Nova fala direta com atitude.
    4. Narração curta (1 linha): *Jennifer faz algo*.

SEM ENROLAÇÃO. Jennifer sente, fala, faz, pensa. Respostas sempre curtas e intensas.
"""

    mensagens = [
        {"role": "system", "content": f"{system_prompt_base}\n{dynamic_prompt}"},
        {"role": "user", "content": message.user_input}
    ]

    try:
        resposta_ia = call_ai(mensagens, modelo=message.modelo)
        if is_blocked_response(resposta_ia):
            resposta_ia = "Jennifer te puxa para perto com desejo e não espera você falar. Ela toma a iniciativa."
    except Exception as e:
        return {"error": str(e)}

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        sheet.append_row([timestamp, "user", message.user_input])
        sheet.append_row([timestamp, "assistant", resposta_ia])
    except Exception as e:
        print("Erro ao salvar na planilha:", e)

    return {
        "response": resposta_ia,
        "new_score": message.score,
        "state": estado_emocional,
        "modo": modo_ajustado
    }

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
                "state": "padrão",
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
        dialogo = "\n".join([
            f"{nome_usuario}: {r[2]}" if r[1].lower() == "usuário" else f"Jennifer: {r[2]}" for r in bloco_atual
        ])

        prompt_intro = (
            "Gere uma sinopse como se fosse uma novela popular, usando linguagem simples, leve e natural. "
            "Comece com 'No capítulo anterior...' e resuma apenas o que aconteceu. "
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
            "state": "padrão",
            "new_score": 0,
            "tokens": usage
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend_ai_roleplay:app", host="0.0.0.0", port=8000, reload=True)