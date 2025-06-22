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


# OpenAI (só se for usar GPT)
from openai import OpenAI

# --- Filtro para respostas bloqueadas (raro em uncensored) ---
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

# --- Função universal: alterna GPT ou LM Studio local ---
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
        # Carregar chave do .env
        load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
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

# --- Carregar .env (Google) e planilha ---
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]
# Carregar credencial do Google a partir da variável de ambiente (Railway)
google_creds_json = os.environ["GOOGLE_CREDS_JSON"]
creds_dict = json.loads(google_creds_json)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
gsheets_client = gspread.authorize(creds)
sheet = gsheets_client.open_by_key("1qFTGu-NKLt-4g5tfa-BiKPm0xCLZ9ZEv5eafUyWqQow").worksheet("mensagens")


# --- FastAPI e CORS ---
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Classe Message com seleção de IA ---
class Message(BaseModel):
    user_input: str
    score: int
    modo: str = "romântico"
    modelo: str = "gpt"  # "gpt" (padrão) ou "lmstudio"

# ... Suas funções auxiliares (memória, prompt, etc.) ...

@app.post("/chat/")
def chat_with_ai(message: Message):
    nome_usuario = "Janio"
    mensagens_memoria = obter_memoria_recente()
    estado_emocional = analisar_estado_emocional(mensagens_memoria, message.score)
    modo_ajustado = analisar_modo(mensagens_memoria, message.user_input.lower(), message.modo)
    prompt_modo = modes.get(modo_ajustado, "")

    system_prompt_base = gerar_prompt_base(nome_usuario) + "\n" + prompt_modo

    dynamic_prompt = f"""
Estado emocional atual: {estado_emocional}.
Modo atual: {modo_ajustado}.
# ... (continue com o prompt dinâmico que você já usa) ...
"""

    mensagens = [{"role": "system", "content": f"{system_prompt_base}\n{dynamic_prompt}"}] + mensagens_memoria
    mensagens.append({"role": "user", "content": message.user_input})

    try:
        resposta_ia = call_ai(mensagens, modelo=message.modelo)
        if is_blocked_response(resposta_ia):
            resposta_ia = (
                "Jennifer te puxa para perto, olha nos seus olhos com desejo e toma a iniciativa sem pedir licença. Ela não espera, só age do jeito que sente vontade."
            )
    except Exception as e:
        return {"error": f"Erro ao chamar a IA: {str(e)}"}

    # Salvar na planilha
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
            "Gere uma sinopse como se fosse uma novela popular, usando linguagem simples, leve e natural, sem palavras difíceis nem frases longas. "
            "Comece com 'No capítulo anterior...' e resuma apenas o que realmente aconteceu, sem prever ou sugerir o futuro. "
            "Seja clara, objetiva e até um pouco divertida, como se estivesse contando para um amigo, sem exagerar no romantismo. "
            f"A conversa aconteceu em {horario_referencia}."
        )

        # Aqui usa LM Studio também:
        completion = call_local_llm([
            {"role": "system", "content": prompt_intro},
            {"role": "user", "content": dialogo}
        ], temperature=0.6, max_tokens=500)
        resumo = completion

        usage = len(resumo.split())  # Só uma estimativa de tokens

        plan_sinopse = gsheets_client.open_by_key("1qFTGu-NKLt-4g5tfa-BiKPm0xCLZ9ZEv5eafUyWqQow").worksheet("sinopse")
        plan_sinopse.append_row([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            resumo,
            usage
        ])

        return {
            "resumo": resumo,
            "response": "",
            "state": states[0],
            "new_score": 0,
            "tokens": usage
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend_ai_roleplay:app", host="0.0.0.0", port=8000, reload=True)
