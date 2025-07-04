from fastapi import FastAPI, Query
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/personagens/")
def listar_personagens():
    try:
        sheet = gsheets_client.open_by_key(PLANILHA_ID)
        aba = sheet.worksheet("personagens")
        dados = aba.get_all_records()
        return dados
    except Exception as e:
        return JSONResponse(content={"erro": f"Erro ao acessar planilha: {e}"}, status_code=500)

@app.get("/intro/")
def obter_intro_personagem(personagem: str):
    try:
        sheet = gsheets_client.open_by_key(PLANILHA_ID)
        aba = sheet.worksheet(personagem)
        dados = aba.get_all_records()
        if dados and dados[0].get("role") == "system":
            return {"resumo": dados[0].get("content", "")}
        else:
            return JSONResponse(content={"erro": "Introdução não encontrada."}, status_code=404)
    except Exception as e:
        return JSONResponse(content={"erro": f"Erro ao acessar planilha: {e}"}, status_code=500)

@app.get("/")
def home():
    return {"status": "API Roleplay Online"}
