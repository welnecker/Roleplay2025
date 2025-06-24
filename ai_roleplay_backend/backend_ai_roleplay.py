from fastapi import FastAPI, Query
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from fastapi.responses import JSONResponse
from dateutil import parser as dateparser
from openai import OpenAI
import json
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# Configuração Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_dict = json.loads(os.environ["GOOGLE_CREDS_JSON"])
if "private_key" in creds_dict:
    creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
gsheets_client = gspread.authorize(creds)
PLANILHA_ID = "1qFTGu-NKLt-4g5tfa-BiKPm0xCLZ9ZEv5eafUyWqQow"
GITHUB_IMG_URL = "https://welnecker.github.io/roleplay_imagens/"

# Utilitário de limpeza de texto com correção de codificação
def limpar_texto(texto: str) -> str:
    if not texto:
        return ""
    try:
        texto = texto.encode("latin1").decode("utf-8")
    except:
        pass
    texto = texto.encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")
    texto = texto.replace("\u00A0", " ")
    return texto.strip()

# FastAPI
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Modelo de entrada
class Message(BaseModel):
    user_input: str
    score: int
    modo: str = "romântico"
    personagem: str = "Jennifer"

# Censura
CENSURA = [
    "desculpe, não posso ajudar com isso", "não posso continuar com esse assunto",
    "não sou capaz de ajudar nesse tema", "como uma ia de linguagem",
    "não posso fornecer esse tipo de conteúdo", "minhas diretrizes não permitem"
]

def is_blocked_response(resposta_ia: str) -> bool:
    texto = resposta_ia.lower()
    return any(msg in texto for msg in CENSURA)

def call_ai(mensagens, temperature=0.88, max_tokens=750):
    openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=mensagens,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content.strip()

def carregar_dados_personagem(nome_personagem: str):
    aba_pers = gsheets_client.open_by_key(PLANILHA_ID).worksheet("personagens")
    dados = aba_pers.get_all_records()
    for p in dados:
        if p['nome'].strip().lower() == nome_personagem.strip().lower():
            return p
    return {}

@app.get("/personagens/")
def listar_personagens():
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet("personagens")
        dados = aba.get_all_records()
        personagens = []
        for p in dados:
            nome = p.get("nome", "")
            personagens.append({
                "nome": nome,
                "descricao": p.get("descrição curta", ""),
                "idade": p.get("idade", ""),
                "estilo": p.get("estilo fala", ""),
                "estado_emocional": p.get("estado_emocional", ""),
                "foto": f"{GITHUB_IMG_URL}{nome.strip()}.jpg"
            })
        return personagens
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/chat/")
def chat_with_ai(message: Message):
    nome_usuario = "Janio"
    nome_personagem = message.personagem
    dados_pers = carregar_dados_personagem(nome_personagem)

    estado_emocional = dados_pers.get("estado_emocional", "neutro")
    estilo = dados_pers.get("estilo fala", "fala natural e emocional")
    prompt_modo = {
        "romântico": "texto padrão romântico",
        "cotidiano": "texto cotidiano",
        "sexy": "texto sexy"
    }.get(message.modo, "")

    system_prompt = f"Estilo de fala: {estilo}\nEstado emocional: {estado_emocional}\nDiretriz positiva: {dados_pers.get('diretriz_positiva', '')}\nDiretriz negativa: {dados_pers.get('diretriz_negativa', '')}\n{prompt_modo}"

    dynamic_prompt = f"""
- Estruture a resposta SEMPRE em 4 parágrafos:
  1. Fala direta do personagem.
  2. Pensamento interno (em aspas).
  3. Nova fala com atitude.
  4. Narração curta do que o personagem faz (*...*).
"""

    mensagens = [
        {"role": "system", "content": f"{system_prompt}\n{dynamic_prompt}"},
        {"role": "user", "content": message.user_input}
    ]

    try:
        resposta_ia = call_ai(mensagens)
        if is_blocked_response(resposta_ia):
            resposta_ia = f"{nome_personagem} te puxa para perto com desejo e toma a iniciativa."
    except Exception as e:
        return {"error": str(e)}

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        aba_mensagens = gsheets_client.open_by_key(PLANILHA_ID).worksheet(nome_personagem)
        aba_mensagens.append_row([timestamp, "user", limpar_texto(message.user_input)])
        aba_mensagens.append_row([timestamp, "assistant", limpar_texto(resposta_ia)])
    except Exception as e:
        print(f"Erro ao salvar mensagens: {e}")

    return {
        "response": resposta_ia,
        "new_score": message.score,
        "state": estado_emocional,
        "modo": message.modo
    }

@app.get("/intro/")
def obter_intro(nome: str = Query("Janio"), personagem: str = Query("Jennifer")):
    try:
        sheet = gsheets_client.open_by_key(PLANILHA_ID).worksheet(personagem)
        system_prompt_base = f"Sinopse gerada para {nome}."

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
            f"{nome}: {r[2]}" if r[1].lower() == "usuário" else f"{personagem}: {r[2]}" for r in bloco_atual
        ])

        prompt_intro = (
            "Gere uma sinopse como se fosse uma novela popular, usando linguagem simples, leve e natural. "
            "Comece com 'No capítulo anterior...' e resuma apenas o que aconteceu. "
            f"A conversa aconteceu em {horario_referencia}."
        )

        resumo = call_ai([
                {"role": "system", "content": prompt_intro},
                {"role": "user", "content": dialogo}
            ], temperature=0.6, max_tokens=500)
            
            resumo = limpar_texto(resumo)
            usage = len(resumo.split())
        aba_sinopse = f"{personagem}_sinopse"
        plan_sinopse = gsheets_client.open_by_key(PLANILHA_ID).worksheet(aba_sinopse)
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
