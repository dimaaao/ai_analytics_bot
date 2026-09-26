import json
import re
import logging
from os import getenv
from pathlib import Path

import gspread
from dotenv import load_dotenv

from google.oauth2.service_account import Credentials
from google.cloud import bigquery


load_dotenv("config.env")

SPREADSHEET_URL = getenv('SPREADSHEET_URL')
SERVICE_ACCOUNT_PATH = getenv('SERVICE_ACCOUNT_PATH')


def get_google_sheet_config():
    try:
        if not SPREADSHEET_URL or not SERVICE_ACCOUNT_PATH:
            raise ValueError("SPREADSHEET_URL или SERVICE_ACCOUNT_PATH не заданы в config.env")

        scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
        credentials = Credentials.from_service_account_file(SERVICE_ACCOUNT_PATH, scopes=scopes)
        client = gspread.authorize(credentials)
        sheet = client.open_by_url(SPREADSHEET_URL).worksheet('ai_bot_config')
        records = sheet.get_all_records()
        logging.info("Google Sheets config загружен")
        return records

    except Exception as e:
        logging.exception   (f"Ошибка при чтении Google Таблицы: {e}")
        return []

def execute_bq_sql(sql_code: str, source_table: str | None = None) -> str:
    try:
        logging.info("Выполняю запрос в BigQuery...")
        credentials = Credentials.from_service_account_file(SERVICE_ACCOUNT_PATH)
        project_id = source_table.split(".")[0] if source_table else None
        
        client = bigquery.Client(credentials=credentials, project=project_id)
        query_job = client.query(sql_code)
        results = query_job.result()

        output = []
        for row in results:
            row_data = ", ".join([f"{key}: {val}" for key, val in row.items()])
            output.append(row_data)

        if not output:
            logging.warning("BigQuery вернул пустой результат")
            return "Данные не найдены (пустой результат)."

        final_string = "\n".join(output)
        logging.info("Данные из BigQuery успешно получены")
        return final_string[:10000]

    except Exception as e:
        logging.exception(f"Ошибка выполнения в BigQuery: {e}")
        return f"Ошибка выполнения в BigQuery:\n{e}"
        
def get_data_from_config(configs, chat_id):
    for row in configs:
        if str(row.get('chat_id')) == str(chat_id):
            status = str(row.get('status')).upper()
            if status != 'TRUE':
                logging.warning(f"Доступ отключен для chat_id={chat_id}")
                return None
            source_table = row.get('source_table')
            gemini_version = row.get('gemini_version') or 'gemini-2.5-flash' # если версия не указана берем по дефолту эту
            prompt_prefix = row.get('prompt_prefix')
            return {
                "source_table": source_table,
                "gemini_version": gemini_version,
                "prompt_prefix": prompt_prefix
            }
    return None

def sanitize_telegram_text(text: str) -> str:
    if not text:
        return ""

    cleaned_text = re.sub(r'[*_`~\[\]#]', '', text) 
    cleaned_text = cleaned_text.replace("```", "")
    cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text)
    cleaned_text = re.sub(r"[ \t]+\n", "\n", cleaned_text)
    
    return cleaned_text.strip()

def split_long_message(text: str, max_chars: int = 3000) -> list[str]:
    text = sanitize_telegram_text(text)
    if len(text) <= max_chars:
        return [text]

    chunks = []
    current = ""

    for paragraph in text.split("\n\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(current) + len(paragraph) + 2 <= max_chars:
            current = (current + "\n\n" + paragraph).strip()
        else:
            if current:
                chunks.append(current)
            if len(paragraph) <= max_chars:
                current = paragraph
            else:
                for part in [paragraph[i:i + max_chars] for i in range(0, len(paragraph), max_chars)]:
                    cleaned_part = part.strip()
                    if cleaned_part:
                        chunks.append(cleaned_part)
                current = ""

    if current:
        chunks.append(current)

    return [chunk for chunk in chunks if chunk]