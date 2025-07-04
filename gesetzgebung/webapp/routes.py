from flask import (
    Response,
    jsonify,
    render_template,
    request,
    session,
    stream_with_context,
)

from gesetzgebung.infrastructure.flask_file import app
from gesetzgebung.infrastructure.logger import get_logger
from gesetzgebung.logic.chat_service import chat_completion
from gesetzgebung.logic.law_parser import parse_law
from gesetzgebung.logic.law_search import search_laws
from gesetzgebung.infrastructure.models import get_law_by_id

### Everything related to RAG
# from langchain_docling import DoclingLoader
# from langchain_docling.loader import ExportType
# from gesetzgebung.tokenizer_wrapper import OpenAITokenizerWrapper
# from docling.chunking import HybridChunker
# from docling.document_converter import DocumentConverter, PdfFormatOption
# from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
# from docling.datamodel.pipeline_options import PdfPipelineOptions
# from docling.datamodel.base_models import InputFormat
# from langchain_openai.embeddings import OpenAIEmbeddings
# from langchain_community.vectorstores import SupabaseVectorStore
# from supabase.client import Client, create_client
# supabase_url = os.environ.get("SUPABASE_URL")
# supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")
# supabase: Client = create_client(supabase_url, supabase_key)
# embeddings = OpenAIEmbeddings()


logger = get_logger(__name__)


@app.route("/", methods=["GET", "POST"])
@app.route("/index")
def index():
    return render_template("index.html")


@app.route("/submit/<law_titel>", methods=["GET"])
def submit(law_titel):
    law_id = request.args.get("law_id")
    if not law_id or not (law := get_law_by_id(law_id)):
        return render_template("error.html")
    return parse_law(law)


@app.route("/autocomplete")
def autocomplete():
    query = request.args.get("q", "").lower()
    results = search_laws(query)
    return jsonify(results)


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    user_message = data.get("message", "")
    if not (infos := session.get("infos", None)):
        law_id = data.get("law_id", "")
        law = get_law_by_id(law_id)
        infos = parse_law(law, display=False, use_session=True)
        session["infos"] = infos
    law_titel = session.get("titel", "")
    answer_generator = chat_completion(user_message, infos, law_titel)
    return Response(stream_with_context(answer_generator), mimetype="text/event-stream")
