# AI Analytics Telegram Bot (Text-to-SQL & Insights)

Интеллектуальный Telegram-бот для бизнес-аналитики на базе LLM (Google Cloud Vertex AI) и Google BigQuery. Бот принимает вопросы от стейкхолдеров на естественном языке, генерирует валидные SQL-запросы к корпоративному хранилищу данных (DWH), выполняет их и возвращает структурированный ответ с интерпретацией метрик и выводами.

---

## Возможности и архитектура

Пайплайн работы бота разделен на два агентных шага:

```mermaid
flowchart LR
    User([Пользователь в Telegram]) -->|Вопрос на естественном языке| Bot[bot.py: Aiogram]
    Bot --> Agent[agent.py: AI Agent]
    
    subgraph LLM_Pipeline [Vertex AI Pipeline]
        Agent -->|Вопрос + get_sql_instruction.md| SQL_Gen[SQL Generator]
        SQL_Gen -->|Сгенерированный SQL| BQ[(Google BigQuery)]
        BQ -->|Датасет с результатами| Interpreter[Analytics Interpreter]
        Interpreter -->|analytics_instruction.md| Summary[Интерпретация и инсайты]
    end
    
    Summary --> Bot
    Bot -->|Готовый аналитический отчет| User
