from gesetzgebung.infrastructure.flask_file import app
from gesetzgebung.updater.logger import logger
from gesetzgebung.infrastructure.models import (
    datetime,
    is_update_active,
    set_update_active,
)
from gesetzgebung.updater.update_news import update_news_update_candidates
from gesetzgebung.updater.update_laws import update_laws

import datetime
import os
from dotenv import load_dotenv

### Below imports were experimental, not currently needed
# from langchain_docling import DoclingLoader
# from langchain_docling.loader import ExportType
# from langchain_openai.embeddings import OpenAIEmbeddings
# from langchain_community.vectorstores import SupabaseVectorStore
# from supabase.client import Client, create_client
# from docling.chunking import HybridChunker
# from gesetzgebung.tokenizer_wrapper import OpenAITokenizerWrapper
# import tempfile
# from pathlib import Path
# supabase_url = os.environ.get("SUPABASE_URL")
# supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")
# supabase: Client = create_client(supabase_url, supabase_key)
# embeddings = OpenAIEmbeddings()


def launch():
    basedir = os.path.abspath(os.path.dirname(__file__))
    load_dotenv(os.path.join(basedir, ".env"))

    with app.app_context():
        if is_update_active():
            logger.critical(
                f"Script already in progress. Immediately terminating new process at {datetime.datetime.now()}.",
                subject="Daily update launched while still in progress.",
            )

        set_update_active(True)

        try:
            update_laws()
            update_news_update_candidates()
        except Exception as e:
            logger.critical(f"Unknown exception: {e}", subject="Unknown exception")

        set_update_active(False)


if __name__ == "__main__":
    launch()
