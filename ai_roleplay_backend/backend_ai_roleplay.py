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

# Controle de introducao mostrada por personagem e usuario
introducao_mostrada_por_usuario = {}

class Message(BaseModel):
    personagem: str
    user_input: str
    modo: str = "default"
    primeira_interacao: bool = False


def call_ai(mensagens, temperature=0.3, max_tokens=100):
    try:
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=mensagens,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[ERRO no call_ai] {e}")
        return "Sorry, there was a problem generating the response."

# Funções auxiliares

def carregar_dados_personagem(nome_personagem: str):
    """
    Carrega dados do personagem pelo nome. Primeiro tenta validar 'usar' == 'sim',
    mas, se encontrar um personagem com nome correspondente mesmo que 'usar' != 'sim',
    retorna-o (emite warning).
    """
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet("personagens")
        dados = aba.get_all_records()
        # Debug: mostrar colunas e linhas
        if dados:
            print("[DEBUG] Colunas disponíveis em 'personagens':", list(dados[0].keys()))
        match_ignorar_uso = None
        for p in dados:
            nome_planilha = p.get('nome','').strip().lower()
            usar = str(p.get('usar','')).strip().lower()
            print(f"[DEBUG] Verificando: nome='{nome_planilha}', usar='{usar}'")
            if nome_planilha == nome_personagem.strip().lower():
                if usar == 'sim':
                    print("[DEBUG] Personagem validado e retornado:", p)
                    return p
                if match_ignorar_uso is None:
                    match_ignorar_uso = p
        if match_ignorar_uso:
            print(f"[WARNING] Personagem '{nome_personagem}' encontrado mas 'usar' != 'sim': retornando mesmo assim.")
            return match_ignorar_uso
        print(f"[DEBUG] Nenhum personagem correspondeu ao nome '{nome_personagem}'.")
        return {}
    except Exception as e:
        print(f"[ERRO ao carregar dados do personagem] {e}")
        return {}
    except Exception as e:
        print(f"[ERRO ao carregar dados do personagem] {e}")
        return {}


def carregar_memorias_do_personagem(nome_personagem: str):
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet("memorias")
        todas = aba.get_all_records()
        filtradas = [m for m in todas if m.get('personagem', '').strip().lower() == nome_personagem.strip().lower()]
        try:
            filtradas.sort(key=lambda m: datetime.strptime(m.get('data',''), "%Y-%m-%d"), reverse=True)
        except:
            pass
        mems = []
        for m in filtradas:
            mems.append(
                f"[{m.get('tipo','')}] ({m.get('emoção','')}) {m.get('titulo','')} - {m.get('data','')}: {m.get('conteudo','')} (Relevância: {m.get('relevância','')})"
            )
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
        aba.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), texto, len(texto)])
    except Exception as e:
        print(f"[ERRO ao salvar sinopse] {e}")


def gerar_resumo_ultimas_interacoes(nome_personagem: str) -> str:
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet(nome_personagem)
        dialogos = aba.get_all_values()
        if len(dialogos) < 5:
            return ""
        ult = dialogos[-5:]
        txt = "\n".join([f"{l[1]}: {l[2]}" for l in ult if len(l)>=3])
        prompt = [
            {"role":"system","content":"Summarize the following dialogue excerpts into a short, engaging narrative in the style of 'previously on...'"},
            {"role":"user","content":txt}
        ]
        resumo = call_ai(prompt, max_tokens=280)
        salvar_sinopse(nome_personagem, resumo)
        return f"Previously on...\n\n{resumo}"
    except Exception as e:
        print(f"[ERRO ao gerar resumo de interações] {e}")
        return ""

@app.post("/chat/")
def chat_with_ai(message: Message):
    nome_personagem = message.personagem
    dados = carregar_dados_personagem(nome_personagem)
    if not dados:
        return JSONResponse(status_code=404, content={"error":"Character not found"})

    memorias = carregar_memorias_do_personagem(nome_personagem)
    sinopse = gerar_resumo_ultimas_interacoes(nome_personagem)

    user_name = dados.get("user_name","the user")
    relationship = dados.get("relationship","companion")
    contexto = dados.get("contexto","")
    introducao = dados.get("introducao","")

    prompt_base = f"You are {nome_personagem}, the {relationship} of {user_name}.\n"
    if contexto:
        prompt_base += f"Context: {contexto}\n"
    if introducao:
        prompt_base += f"Intro: {introducao}\n"
    prompt_base += dados.get("prompt_base","")

    for field,label in [("idade","Age"),("traços físicos","Physical traits"),("diretriz_positiva","Desired behavior"),("diretriz_negativa","Avoid"),("exemplo","Example of expected response")]:
        if dados.get(field):
            prompt_base += f"\n{label}: {dados[field]}"

    prompt_base += (
        "\nSpeak in natural, sensual, and emotionally engaging English. "
        "Use evocative descriptions, physical gestures, and sensations. "
        "Take initiative — don’t ask repetitive or generic questions. "
        "Avoid robotic or reflective monologues. "
        "Show desire through action, body language, eye contact, and brief seductive dialogue. "
        "Blend thoughts in italics with spoken lines in quotation marks."
    )

    # style guidelines para respostas práticas, sem drama
    prompt_base += (
        "\n\n**Style guidelines:**\n"
        "- Máximo 2 frases por parágrafo.\n"
        "- Vocabulário simples e cotidiano (até 8ª série).\n"
        "- Sem descrições longas de ambiente.\n"
        "- Proibido uso de metáforas, linguagem poética ou rebuscada.\n"
        "- Não incluir pensamentos internos ou texto em *itálico*.\n"
        "- Focar em ações objetivas e diálogo realista.\n"
        "- Tom prático, autêntico e conversacional.\n"
    )

    mensagens = []
    ui = message.user_input.strip()
    # detecção de cena entre aspas
    if ui.startswith('"') and ui.endswith('"'):
        cena = ui.strip('"').strip()
        mensagens.append({
            "role":"system",
            "content":(
                f"You are {nome_personagem}. The text between quotes is a SCENE DIRECTION: "
                f"{cena}". Respond in short, objective sentences, without florid language.
            )
        })
    else:
        mensagens.append({
            "role":"system",
            "content": prompt_base + "\n\n" + sinopse + "\n\n" + "\n".join(memorias)
        })

    mensagens.append({"role":"user","content":ui})

    resposta = call_ai(mensagens)

    salvar_dialogo(nome_personagem,"user", message.user_input)
    salvar_dialogo(nome_personagem,"assistant", resposta)

    chave = f"{nome_personagem.lower()}_{user_name.lower()}"
    mostrar_intro = False
    if message.primeira_interacao and not introducao_mostrada_por_usuario.get(chave):
        mostrar_intro = True
        introducao_mostrada_por_usuario[chave] = True

    return {"sinopse": sinopse, "response": resposta, "modo": message.modo, "introducao": introducao if mostrar_intro else ""}

@app.get("/personagens/")
def listar_personagens():
    try:
        aba = gsheets_client.open_by_key(PLANILHA_ID).worksheet("personagens")
        dados = aba.get_all_records()
        pers = []
        for p in dados:
            if str(p.get("usar","")).strip().lower() != "sim":
                continue
            pers.append({
                "nome": p.get("nome",""),
                "descricao": p.get("descrição curta",""),
                "idade": p.get("idade",""),
                "foto": f"{GITHUB_IMG_URL}{p.get('nome','').strip()}.jpg"
            })
        return pers
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/ping")
def ping():
    return {"status":"ok"}

@app.get("/intro/")
def get_intro(nome: str = Query(...), personagem: str = Query(...)):
    try:
        dados_pers = carregar_dados_personagem(personagem)
        introducao_texto = dados_pers.get("introducao","").strip()
        sinopse = gerar_resumo_ultimas_interacoes(personagem).strip()
        resumo = sinopse if sinopse else introducao_texto
        return {"resumo": resumo}
    except Exception as e:
        print(f"[ERRO /intro/] {e}")
        return {"resumo":""}
