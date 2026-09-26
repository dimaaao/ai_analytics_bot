import os
import logging
from os import getenv
from dotenv import load_dotenv

from google import genai
from google.genai import types

load_dotenv("config.env")  
SERVICE_ACCOUNT_PATH = getenv('SERVICE_ACCOUNT_PATH')

if SERVICE_ACCOUNT_PATH:
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = SERVICE_ACCOUNT_PATH
else:
    logging.error("Путь к сервисному аккаунту не найден в config.env")

def load_system_prompt(filepath: str) -> str:
    try:
        with open(filepath, "r", encoding="utf-8") as file:
            return file.read()
    except FileNotFoundError:
        logging.error(f"Файл с инструкцией не найден: {filepath}")
        return ""

def generate_sql(question: str, target_table: str, gemini_version: str) -> str:
    try:
        project_id = target_table.split(".")[0]
        try:
            client = genai.Client(
                vertexai=True,
                project=project_id,
                location='us-central1'
            )
        except Exception as e:
            return f"Ошибка инициализации клиента: {e}"
        
        system_instruction = load_system_prompt('instructions/get_sql_instruction.md')

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.0  
        )

        prompt = (
            f"Задача: {question}\n\n"
            f"КРИТИЧЕСКОЕ ОГРАНИЧЕНИЕ:\n"
            f"1. **Изоляция данных:** Запрещено использовать любые другие таблицы, кроме {target_table}. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО выдумывать JOIN с несуществующими таблицами (например, `users`, `orders`, `amo.amo_view`, `dicts` и т.д.).\n"
            f"2. **Строгое соответствие схеме (No Hallucinations):** Использовать ТОЛЬКО те столбцы, измерения и метрики, которые описаны в блоках \"СТРУКТУРА ДАННЫХ\". Запрещено выдумывать свои названия колонок (например, нельзя писать `revenue` — используй только `sum_of_payment...` с нужным суффиксом).\n"
            f"3. **Безопасность (Только чтение):** Разрешены только `SELECT` запросы. Категорически запрещено генерировать выражения `UPDATE`, `DELETE`, `INSERT`, `DROP`, `CREATE` или `MERGE`.\n"
            f"4. **Синтаксис:** Использовать исключительно диалект **Google Standard SQL (BigQuery)**. При работе с датами используй стандартные функции BigQuery (например, `DATE_TRUNC`, `DATE_ADD`, `CURRENT_DATE()`, `EXTRACT`).\n"
            f"5. **Формат ответа:** Выводи ТОЛЬКО чистый SQL-код, готовый к выполнению. Никаких приветствий, извинений, пояснений логики и markdown-разметки (не оборачивай код в ```sql).\n"
        )
        
        logging.info("Генерация SQL-запроса...")
        response = client.models.generate_content(
            model=gemini_version,
            contents=prompt,
            config=config
        )
        
        sql_result = response.text.strip()
        sql_result = sql_result.replace("```sql", "").replace("```", "").strip()
        
        forbidden_keywords = ["UPDATE", "DELETE", "INSERT", "DROP", "CREATE", "MERGE", "JOIN"]
        if any(keyword in sql_result.upper() for keyword in forbidden_keywords):
            logging.warning("Бот попытался использовать запрещенные операторы (JOIN/UPDATE).")
            return " Бот попытался обратиться к сторонним таблицам. Попробуй переформулировать вопрос."
        
        return sql_result

    except Exception as e:
        logging.exception(f"Ошибка генерации SQL: {e}")
        return f" Ошибка генерации: {e}"

def analyze_data_with_agent(
    question: str, target_table: str,
    sql_code: str, raw_data: str, 
    gemini_version: str, prompt_prefix: str) -> str:

    project_id = target_table.split(".")[0]
    
    try:
        client = genai.Client(
            vertexai=True,
            project=project_id,
            location='us-central1'
        )

        analytics_role = load_system_prompt('instructions/analytics_instruction.md')
        data_dictionary = load_system_prompt('instructions/get_sql_instruction.md')

        combined_instruction = (
            f"{analytics_role}\n\n"
            f"=== СПРАВОЧНИК ПО СТРУКТУРЕ ДАННЫХ (ДЛЯ ТВОЕГО ПОНИМАНИЯ) ===\n"
            f"Ниже приведена структура таблицы, из которой взяты данные. "
            f"Используй эту информацию, чтобы правильно интерпретировать названия колонок и суффиксы:\n\n"
            f"{data_dictionary}\n"
            f"ДОПОЛНИТЕЛЬНЫЕ НАСТРОЙКИ:\n"
            f"{prompt_prefix if prompt_prefix else 'Нет дополнительных настроек.'}"
        )

        config = types.GenerateContentConfig(
            system_instruction=combined_instruction,
            temperature=0.4
        )

        prompt = (
            f"Вопрос клиента: {question}\n\n"
            f"Сгенерированный код:\n```sql\n{sql_code}\n```\n\n"
            f"Сырые данные из базы:\n{raw_data}\n\n"
            f"Сделай вдумчивый вывод на основе этих данных и ответь на вопрос."
        )
            
        logging.info("Анализ данных через ИИ...")
        response = client.models.generate_content(
            model=gemini_version,
            contents=prompt,
            config=config
        )

        return response.text.strip()
    except Exception as e:
        logging.exception(f"Ошибка анализа данных: {e}")
        return f" Ошибка анализа данных: {e}"