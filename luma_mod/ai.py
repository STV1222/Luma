from __future__ import annotations
import json
from typing import Any, Dict, Optional
from urllib.request import urlopen
from urllib.error import URLError

from .dates import extract_time_window
from .utils import FILETYPE_MAP, find_dirs_by_hint, find_dirs_by_tokens, find_exact_folder_match, DEFAULT_FOLDERS
from .content import extract_text_from_file

try:
    from langchain_community.llms import Ollama
    from langchain.callbacks.manager import CallbackManager
    from langchain.callbacks.streaming_stdout import StreamingStdOutCallbackHandler
    HAVE_OLLAMA = True
except Exception:
    HAVE_OLLAMA = False

try:
    from openai import OpenAI
    HAVE_OPENAI = True
except Exception:
    HAVE_OPENAI = False

def extract_keywords(q: str):
    import re
    from .utils import STOPWORDS
    quoted = re.findall(r'"([^\"]+)"', q)
    q_wo = re.sub(r'"[^\"]+"', ' ', q)
    words = re.findall(r"[A-Za-z0-9_\-]+", q_wo)
    return [*quoted, *[w for w in words if w.lower() not in STOPWORDS]]

def strip_time_keywords(keywords, original_query, time_range):
    import re
    if not keywords:
        return keywords
    months = {
        "jan","january","feb","february","mar","march","apr","april","may","jun","june",
        "jul","july","aug","august","sep","sept","september","oct","october","nov","november","dec","december"
    }
    noise = {"edited","created","modified","updated","on","in","during","between","from","to","at"}
    has_time = time_range and time_range != (None, None)
    cleaned = []
    for w in keywords:
        wl = w.lower()
        if wl in noise: continue
        if wl in months: continue
        if has_time and re.fullmatch(r"20\d{2}", wl): continue
        cleaned.append(w)
    return cleaned

def _query_mentions_explicit_types(q: str) -> bool:
    import re
    if not q:
        return False
    
    # Multilingual explicit type mentions
    type_patterns = [
        # English
        r"\b(pdf|png|jpg|jpeg|gif|image|images|photo|photos|picture|pictures|screenshot|screenshots|pptx?|slides?|presentation|docx?|word|rtf|txt|text|md|markdown|csv|xls[x]?|spreadsheet|code|py|js|ts|java|go|rb|rs|file|files)\b",
        # Chinese
        r"(文件|檔案|圖片|照片|簡報|投影片|簡報檔|ppt|pptx|pdf|doc|docx|excel|xls|xlsx|程式碼|代碼|代碼檔|代碼文件)",
        # Spanish
        r"\b(archivo|archivos|imagen|imágenes|foto|fotos|presentación|documento|pdf|ppt|pptx|doc|docx)\b",
        # French
        r"\b(fichier|fichiers|image|images|photo|photos|présentation|document|pdf|ppt|pptx|doc|docx)\b",
        # German
        r"\b(datei|dateien|bild|bilder|foto|fotos|präsentation|dokument|pdf|ppt|pptx|doc|docx)\b",
        # Japanese
        r"(ファイル|画像|写真|プレゼンテーション|文書|pdf|ppt|pptx|doc|docx)",
        # Arabic
        r"(ملف|ملفات|صورة|صور|عرض|عروض|وثيقة|وثائق|pdf|ppt|pptx|doc|docx)",
        # Russian
        r"\b(файл|файлы|изображение|изображения|фото|фотографии|презентация|документ|pdf|ppt|pptx|doc|docx)\b"
    ]
    
    for pattern in type_patterns:
        if re.search(pattern, q, re.IGNORECASE):
            return True
    
    # If user says "all files" or "everything", it's explicitly NOT narrowing
    if re.search(r"\b(all\s+files|everything|any\s+file|所有文件|所有檔案)\b", q, re.IGNORECASE):
        return False
    return False

class LumaAI:
    def __init__(self, mode: str = "private", openai_api_key: str = None) -> None:
        self._model = None
        self._openai_client = None
        self.mode = mode  # "private" for local AI, "cloud" for OpenAI
        self.openai_api_key = openai_api_key

    def _ensure(self) -> bool:
        if self.mode == "cloud":
            return self._ensure_openai()
        else:
            return self._ensure_ollama()
    
    def _ensure_ollama(self) -> bool:
        if not HAVE_OLLAMA:
            return False
        # Quick health check to avoid long blocking if Ollama isn't running
        try:
            urlopen("http://127.0.0.1:11434/api/tags", timeout=1.5).read(1)
        except URLError:
            return False
        except Exception:
            return False
        if self._model is None:
            try:
                self._model = Ollama(model="gemma2:2b",
                                     callback_manager=CallbackManager([StreamingStdOutCallbackHandler()]))
            except Exception:
                return False
        return True
    
    def _ensure_openai(self) -> bool:
        if not HAVE_OPENAI or not self.openai_api_key:
            return False
        if self._openai_client is None:
            try:
                self._openai_client = OpenAI(api_key=self.openai_api_key)
            except Exception:
                return False
        return True
    
    def _invoke_ai(self, prompt: str) -> str:
        """Invoke the appropriate AI model based on current mode."""
        if self.mode == "cloud" and self._ensure_openai():
            try:
                response = self._openai_client.chat.completions.create(
                    model="gpt-5-nano",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=1000,
                    temperature=0.1
                )
                return response.choices[0].message.content.strip()
            except Exception:
                return ""
        elif self.mode == "private" and self._ensure_ollama():
            try:
                return self._model.invoke(prompt).strip()
            except Exception:
                return ""
        return ""

    def parse_query_nonai(self, query: str) -> Dict[str, Any]:
        tr = extract_time_window(query)
        kws = strip_time_keywords(extract_keywords(query), query, tr)
        # Simple folder hint: phrases like "in <name> folder" or "under <name>"
        import re
        folder_hint = None
        # Accept variants: "in <name> folder", "under <name>", "in <name>", or quoted folder names
        m = re.search(r"\b(?:in|under|inside)\s+([A-Za-z0-9_\- ]+)\s+folder\b", query, re.IGNORECASE)
        if not m:
            m = re.search(r"\bfolder\s+([A-Za-z0-9_\- ]+)\b", query, re.IGNORECASE)
        if not m:
            m = re.search(r"\b(?:in|under|inside)\s+\"([^\"]+)\"\b", query)
        if not m:
            m = re.search(r"\b(?:in|under|inside)\s+([A-Za-z0-9_\- ]+)\b", query, re.IGNORECASE)
        if m:
            folder_hint = m.group(1).strip()
        folders = None
        # If user says/implies folder, prioritize exact folder resolution first
        if folder_hint:
            # Try exact matching first, then fall back to fuzzy matching
            folders = find_exact_folder_match(folder_hint)
            if not folders:
                folders = find_dirs_by_tokens(DEFAULT_FOLDERS, [folder_hint]) or find_dirs_by_hint(DEFAULT_FOLDERS, folder_hint)
        else:
            # If no explicit hint but “folder” word present anywhere, extract best token
            if re.search(r"\bfolder\b", query, re.IGNORECASE):
                folders = find_dirs_by_tokens(DEFAULT_FOLDERS, kws)
        return {"keywords": kws, "time_range": None if tr==(None,None) else tr, "file_types": [], "time_attr": "mtime", "folders": folders or []}

    def parse_query_ai(self, query: str) -> Dict[str, Any]:
        if not self._ensure() or not query.strip():
            return self.parse_query_nonai(query)
        # Get current date/time context for AI
        from datetime import datetime
        now = datetime.now()
        current_date = now.strftime("%Y-%m-%d (%A)")
        current_time = now.strftime("%H:%M:%S")
        current_weekday = now.strftime("%A")
        
        prompt = (
            f"CURRENT DATE/TIME CONTEXT:\n"
            f"Today is: {current_date}\n"
            f"Current time: {current_time}\n"
            f"Current weekday: {current_weekday}\n\n"
            "You are an intelligent file search assistant that understands ANY user query in ANY language and determines the optimal search strategy.\n\n"
            "CORE PRINCIPLE: Think like a human assistant who knows the user's files and can intelligently find what they need based on context, not just keywords.\n\n"
            "ANALYSIS PROCESS:\n"
            "1. UNDERSTAND: What is the user really looking for? What's their underlying goal?\n"
            "2. CONTEXTUALIZE: What type of files would contain this information? What would they likely be named?\n"
            "3. STRATEGIZE: How can we find these files most effectively?\n\n"
            "INTELLIGENT SEARCH STRATEGIES:\n"
            "- If user asks for 'financial statements' → look for Excel files, PDFs, files with 'financial', 'statement', 'report' in name, or files in 'finance' folders\n"
            "- If user asks for 'presentation' → look for PowerPoint, Keynote, PDF files, or files with 'presentation', 'slides', 'deck' in name\n"
            "- If user asks for 'photos from vacation' → look for image files with 'vacation', 'trip', 'travel' in name or folder\n"
            "- If user asks for 'work documents from last week' → look for office files modified in last week\n"
            "- If user asks for 'code I wrote yesterday' → look for programming files modified yesterday\n\n"
            "DYNAMIC APPROACH:\n"
            "- Don't rely on hardcoded patterns - understand the user's intent\n"
            "- Consider semantic relationships and synonyms\n"
            "- Think about what files would logically contain what they're looking for\n"
            "- Use folder names, file names, and content types intelligently\n\n"
            "Return a JSON object with these fields:\n"
            "- user_intent: What the user is really looking for (in English)\n"
            "- search_strategy: Your intelligent approach to find what they need\n"
            "- semantic_keywords: Array of keywords that capture the semantic meaning (not just literal words)\n"
            "- file_name_patterns: Array of patterns that might appear in filenames\n"
            "- folder_hints: Array of folder names that might contain relevant files\n"
            "- time_range: Specific date/time if mentioned, or null\n"
            "- file_types: Array of file extensions that might contain the content\n"
            "- content_hints: Array of content-related terms to help with semantic search\n"
            "- confidence: 0-100 score of how confident you are in understanding their intent\n"
            "- language: detected language of the query\n"
            "- reasoning: Detailed explanation of your analysis and strategy\n\n"
            "UNIVERSAL LANGUAGE SUPPORT:\n"
            "The system should understand queries in ANY language including but not limited to:\n"
            "- English, Chinese (Simplified/Traditional), Japanese, Korean\n"
            "- Spanish, French, German, Italian, Portuguese, Russian\n"
            "- Arabic, Hindi, Thai, Vietnamese, Indonesian, Malay\n"
            "- Dutch, Swedish, Norwegian, Danish, Finnish, Polish\n"
            "- Turkish, Greek, Hebrew, Persian, Urdu, Bengali\n"
            "- And any other language the user might use\n\n"
            "COMMON PATTERNS ACROSS LANGUAGES:\n"
            "Time expressions: 'yesterday', 'last week', 'this month', 'today', 'recently'\n"
            "Chinese time expressions: '昨天', '上週', '這個月', '今天', '最近', '8/31', '8月31日'\n"
            "File types: 'images', 'documents', 'photos', 'screenshots', 'videos', 'music'\n"
            "Chinese file types: '圖片', '文件', '照片', '截圖', '影片', '音樂'\n"
            "Actions: 'find', 'search', 'show', 'get', 'look for', 'need'\n"
            "Chinese actions: '找', '搜尋', '顯示', '取得', '尋找', '需要', '幫我找'\n"
            "Locations: 'in folder', 'on desktop', 'from downloads', 'in documents'\n"
            "Chinese locations: '在資料夾', '在桌面', '從下載', '在文件'\n\n"
            "FILE TYPE MAPPING (Universal):\n"
            "Images: any word meaning 'image', 'photo', 'picture', 'screenshot', '截圖', '圖片' → ['png', 'jpg', 'jpeg', 'gif', 'heic', 'webp', 'bmp', 'tiff']\n"
            "Presentations: any word meaning 'presentation', 'slides', 'ppt', 'powerpoint' → ['ppt', 'pptx', 'key']\n"
            "Documents: any word meaning 'document', 'text', 'word', '文件' → ['pdf', 'doc', 'docx', 'md', 'txt', 'rtf', 'pages', 'numbers', 'xls', 'xlsx', 'csv']\n"
            "Videos: any word meaning 'video', 'movie', 'film' → ['mp4', 'avi', 'mov', 'mkv', 'wmv', 'flv']\n"
            "Audio: any word meaning 'music', 'audio', 'sound' → ['mp3', 'wav', 'flac', 'aac', 'ogg', 'm4a']\n"
            "Code: any word meaning 'code', 'program', 'script' → ['py', 'js', 'ts', 'cpp', 'c', 'java', 'go', 'rb', 'rs', 'php', 'swift', 'kt']\n"
            "Archives: any word meaning 'archive', 'zip', 'compressed' → ['zip', 'rar', '7z', 'tar', 'gz']\n\n"
            "IMPORTANT TYPE NARROWING RULES:\n"
            "1. If query contains '文件/document(s)', default to document-like extensions only unless user overrules\n"
            "2. Penalize or exclude executables/code by default: ['py', 'sh', 'exe', 'app', 'bin', 'o', 'dylib']\n"
            "3. Focus on user content files, not system/development files\n\n"
            "EXAMPLES OF INTELLIGENT UNDERSTANDING:\n"
            "- 'find my financial statements' → {\"user_intent\": \"User wants to find financial documents, reports, or statements\", \"search_strategy\": \"Search for Excel files, PDFs, and files with financial terms in name or folder\", \"semantic_keywords\": [\"financial\", \"statement\", \"report\", \"accounting\", \"budget\"], \"file_name_patterns\": [\"financial\", \"statement\", \"report\", \"budget\", \"accounting\", \"revenue\", \"expense\"], \"folder_hints\": [\"finance\", \"accounting\", \"reports\", \"financial\"], \"time_range\": null, \"file_types\": [\"xlsx\", \"xls\", \"pdf\", \"csv\"], \"content_hints\": [\"financial data\", \"accounting\", \"budget\", \"revenue\", \"expense\"], \"confidence\": 90, \"language\": \"en\", \"reasoning\": \"User wants financial documents - will search for Excel/PDF files with financial terms in name or finance folders\"}\n"
            "- '幫我找我8/31更改過的檔案' → {\"user_intent\": \"User wants to find files they modified on August 31st\", \"search_strategy\": \"Search for all files modified on August 31st, regardless of type\", \"semantic_keywords\": [\"modified\", \"changed\", \"edited\"], \"file_name_patterns\": [], \"folder_hints\": [], \"time_range\": \"8/31\", \"file_types\": [], \"content_hints\": [], \"confidence\": 95, \"language\": \"zh\", \"reasoning\": \"Clear date specification with modification action - search all files from that date\"}\n"
            "- 'find my vacation photos' → {\"user_intent\": \"User wants to find photos from their vacation\", \"search_strategy\": \"Search for image files with vacation-related terms in name or folder\", \"semantic_keywords\": [\"vacation\", \"trip\", \"travel\", \"holiday\"], \"file_name_patterns\": [\"vacation\", \"trip\", \"travel\", \"holiday\", \"beach\", \"mountain\"], \"folder_hints\": [\"vacation\", \"travel\", \"photos\", \"trip\"], \"time_range\": null, \"file_types\": [\"jpg\", \"jpeg\", \"png\", \"heic\", \"gif\"], \"content_hints\": [\"vacation photos\", \"travel images\"], \"confidence\": 85, \"language\": \"en\", \"reasoning\": \"User wants vacation photos - search image files with vacation terms in name or travel folders\"}\n"
            "- 'find my presentation slides' → {\"user_intent\": \"User wants to find presentation materials\", \"search_strategy\": \"Search for presentation files and files with presentation terms in name\", \"semantic_keywords\": [\"presentation\", \"slides\", \"deck\", \"pitch\"], \"file_name_patterns\": [\"presentation\", \"slides\", \"deck\", \"pitch\", \"demo\"], \"folder_hints\": [\"presentations\", \"slides\", \"work\"], \"time_range\": null, \"file_types\": [\"ppt\", \"pptx\", \"key\", \"pdf\"], \"content_hints\": [\"presentation slides\", \"pitch deck\"], \"confidence\": 90, \"language\": \"en\", \"reasoning\": \"User wants presentation materials - search PowerPoint/Keynote files with presentation terms\"}\n"
            "- Spanish: 'buscar documentos de ayer' → {\"keywords\": [], \"time_range\": \"ayer\", \"file_types\": [\"doc\", \"docx\", \"pdf\"], \"action\": \"edited\", \"folders\": [], \"intent\": \"documents from yesterday\", \"language\": \"es\"}\n"
            "- French: 'trouver mes images de cette semaine' → {\"keywords\": [], \"time_range\": \"cette semaine\", \"file_types\": [\"jpg\", \"png\", \"heic\"], \"action\": \"edited\", \"folders\": [], \"intent\": \"images from this week\", \"language\": \"fr\"}\n"
            "- Japanese: '昨日のファイルを見つけて' → {\"keywords\": [], \"time_range\": \"昨日\", \"file_types\": [], \"action\": \"edited\", \"folders\": [], \"intent\": \"files from yesterday\", \"language\": \"ja\"}\n"
            "- German: 'zeige mir alle Bilder vom letzten Monat' → {\"keywords\": [], \"time_range\": \"letzten Monat\", \"file_types\": [\"jpg\", \"png\", \"heic\"], \"action\": \"edited\", \"folders\": [], \"intent\": \"images from last month\", \"language\": \"de\"}\n"
            "- Arabic: 'ابحث عن المستندات من الأسبوع الماضي' → {\"keywords\": [], \"time_range\": \"الأسبوع الماضي\", \"file_types\": [\"doc\", \"docx\", \"pdf\"], \"action\": \"edited\", \"folders\": [], \"intent\": \"documents from last week\", \"language\": \"ar\"}\n\n"
            "IMPORTANT INTERPRETATION RULES: \n"
            "1. Always detect the language and provide appropriate file type mappings based on the user's intent\n"
            "2. Use the current date/time context to interpret relative time expressions correctly\n"
            "3. DEFAULT TO ON-DAY mode for phrases like '昨天/前天/上週一/上周一/上禮拜一' when there's NO explicit '從/自/以來/since'\n"
            "4. ONLY use SINCE-DAY mode when query explicitly says '從前天/自前天/since last Monday'\n"
            "5. For ON-DAY: return the specific day (e.g., '前天' = specific date, not range)\n"
            "6. For SINCE-DAY: return range from that day to now\n"
            "7. Time window should be half-open [start, end) - start = local_day@00:00, end = start + 1 day\n\n"
            f"Query: {query}\nJSON:"
        )
        try:
            raw = self._invoke_ai(prompt)
            if not raw.startswith("{"): raw = raw[raw.find("{"):]
            if not raw.endswith("}"): raw = raw[:raw.rfind("}")+1]
            data = json.loads(raw)
            tr_model = extract_time_window(str(data.get("time_range","")) or "")
            tr_query = extract_time_window(query)
            def span(t):
                if not t or t==(None,None): return 0
                s,e=t; 
                if s is None or e is None: return 0
                return max(0, e - s)
            # Always prefer the query-derived time range when it exists and is specific
            # If query has a specific time range (not None), use it over the model's
            if tr_query and tr_query != (None, None):
                tr = tr_query
            else:
                tr = tr_model
            allow = ['.'+e.lstrip('.') for e in data.get("file_types", [])]
            # Choose the right timestamp based on query wording
            action = str(data.get("action","")).lower()
            if any(word in action for word in ["creat", "建立", "建立於", "created"]):
                time_attr = "birthtime"  # macOS: kMDItemFSCreationDate / st_birthtime
            else:
                time_attr = "mtime"      # macOS: kMDItemContentModificationDate / st_mtime
            # Use AI semantic keywords if provided, otherwise extract from query
            ai_semantic_keywords = data.get("semantic_keywords", [])
            ai_file_patterns = data.get("file_name_patterns", [])
            ai_folder_hints = data.get("folder_hints", [])
            
            # Combine semantic keywords and file patterns for search
            kws = []
            if ai_semantic_keywords:
                kws.extend(ai_semantic_keywords)
            if ai_file_patterns:
                kws.extend(ai_file_patterns)
            
            # If no AI keywords, fall back to extraction
            if not kws:
                kws = extract_keywords(query)
            
            kws = strip_time_keywords(kws, query, tr)
            # Use AI-proposed file types if the query explicitly mentions a type OR if AI provided specific types
            if not _query_mentions_explicit_types(query) and not allow:
                allow = []
            
            # Use AI folder hints first, then fall back to regex
            ai_folders = data.get("folders", [])
            ai_folder_hints = data.get("folder_hints", [])
            folders = []
            
            # Combine AI folders and folder hints
            all_folder_hints = ai_folders + ai_folder_hints
            
            if all_folder_hints:
                # Use AI-extracted folder names with exact matching first
                folders = []
                for folder_name in all_folder_hints:
                    exact_matches = find_exact_folder_match(folder_name)
                    if exact_matches:
                        folders.extend(exact_matches)
                    else:
                        # Fall back to fuzzy matching only if no exact matches found
                        fuzzy_matches = find_dirs_by_tokens(DEFAULT_FOLDERS, [folder_name]) or find_dirs_by_hint(DEFAULT_FOLDERS, folder_name)
                        folders.extend(fuzzy_matches)
            else:
                # Fall back to regex pattern matching
                import re
                folder_hint = None
                m2 = re.search(r"\b(?:in|under|inside)\s+([A-Za-z0-9_\- ]+)\s+folder\b", query, re.IGNORECASE)
                if not m2:
                    m2 = re.search(r"\bfolder\s+([A-Za-z0-9_\- ]+)\b", query, re.IGNORECASE)
                if not m2:
                    m2 = re.search(r"\b(?:in|under|inside)\s+\"([^\"]+)\"\b", query)
                if not m2:
                    m2 = re.search(r"\b(?:in|under|inside)\s+([A-Za-z0-9_\- ]+)\b", query, re.IGNORECASE)
                if m2:
                    folder_hint = m2.group(1).strip()
                    folders = find_dirs_by_tokens(DEFAULT_FOLDERS, [folder_hint]) or find_dirs_by_hint(DEFAULT_FOLDERS, folder_hint)
                elif re.search(r"\bfolder\b", query, re.IGNORECASE):
                    folders = find_dirs_by_tokens(DEFAULT_FOLDERS, kws)
            result = {"keywords": kws, "time_range": None if tr==(None,None) else tr,
                     "file_types": allow, "time_attr": time_attr, "folders": folders, 
                     "user_intent": data.get("user_intent", "unknown"), 
                     "search_strategy": data.get("search_strategy", "unknown"),
                     "semantic_keywords": ai_semantic_keywords,
                     "file_name_patterns": ai_file_patterns,
                     "folder_hints": ai_folder_hints,
                     "content_hints": data.get("content_hints", []),
                     "confidence": data.get("confidence", 0),
                     "reasoning": data.get("reasoning", "unknown"),
                     "language": data.get("language", "unknown")}
            
            # Debug output for AI query understanding
            print(f"🧠 AI-First Understanding:")
            print(f"   Query: {query}")
            print(f"   User Intent: {data.get('user_intent', 'unknown')}")
            print(f"   Search Strategy: {data.get('search_strategy', 'unknown')}")
            print(f"   Semantic Keywords: {ai_semantic_keywords}")
            print(f"   File Name Patterns: {ai_file_patterns}")
            print(f"   Folder Hints: {ai_folder_hints}")
            print(f"   Content Hints: {data.get('content_hints', [])}")
            print(f"   Confidence: {data.get('confidence', 0)}%")
            print(f"   Reasoning: {data.get('reasoning', 'unknown')}")
            print(f"   Language: {data.get('language', 'unknown')}")
            print(f"   Combined Keywords: {kws}")
            print(f"   Time Range: {tr}")
            print(f"   File Types: {allow}")
            print(f"   Folders: {folders}")
            print()
            
            return result
        except Exception:
            return self.parse_query_nonai(query)


    def warmup(self) -> bool:
        """Preload the AI model so the first user action is fast.
        Runs in background; safe to ignore failures.
        """
        try:
            if not self._ensure():
                return False
            # Minimal single-token style prompt to force model load
            _ = self._invoke_ai("Warm up and reply: OK")
            return True
        except Exception:
            return False


    # ------------------- Fast extractive summarization -------------------
    def summarize_file_extractive(self, path: str, sentences: int = 3, method: str = "lexrank") -> Optional[str]:
        """Summarize with classic extractive methods (no LLM, CPU-only).
        Falls back to lead-3 style if Sumy isn't available.
        """
        text = extract_text_from_file(path)
        if not text:
            return None
        try:
            from sumy.parsers.plaintext import PlaintextParser  # type: ignore
            from sumy.nlp.tokenizers import Tokenizer  # type: ignore
            if method.lower() == "luhn":
                from sumy.summarizers.luhn import LuhnSummarizer as Summarizer  # type: ignore
            else:
                from sumy.summarizers.lex_rank import LexRankSummarizer as Summarizer  # type: ignore
            parser = PlaintextParser.from_string(text, Tokenizer("english"))
            summarizer = Summarizer()
            sents = summarizer(parser.document, max(1, sentences))
            out = " ".join(str(s) for s in sents).strip()
            return out or None
        except Exception:
            # Fallback: take the first few sentences
            try:
                import re
                chunks = re.split(r"(?<=[.!?])\s+", text)
                draft = " ".join(chunks[:max(1, sentences)]).strip()
                return draft or None
            except Exception:
                return None

    # ------------------- AI filename/path re-ranking -------------------
    def rerank_by_name(self, query: str, items: list[str], time_window=None, file_types=None, folders=None) -> Optional[dict[str, float]]:
        """Ask the local LLM to score relatedness using only names/paths.
        Returns a mapping of path -> score (higher is better). If AI is
        unavailable, returns None so the caller can skip.
        """
        if not items or not query.strip():
            return None
        if not self._ensure():
            return None
        # Keep prompt tiny; cap list length outside the caller ideally
        enum = "\n".join(f"- {p}" for p in items)
        
        # Include metadata guardrails
        metadata_info = ""
        if time_window:
            metadata_info += f"TIME WINDOW: {time_window}\n"
        if file_types:
            metadata_info += f"FILE TYPES: {file_types}\n"
        if folders:
            metadata_info += f"FOLDERS: {folders}\n"
        
        prompt = (
            "Given a user query and a list of file names/paths, assign a relevance score 0-100 "
            "for how related each file is to the query. Consider semantic hints in names, extensions, and folders. "
            "IMPORTANT: Only re-order the provided files - do NOT add new files. "
            "Discard anything outside the specified time window/file types/folders. "
            "Respond as compact JSON object: {\"path\": score, ...} with no extra text.\n\n"
            f"{metadata_info}QUERY: {query}\nFILES:\n{enum}\nJSON:"
        )
        try:
            raw = self._invoke_ai(prompt)
            if "{" in raw and "}" in raw:
                raw = raw[raw.find("{"): raw.rfind("}")+1]
            data = json.loads(raw)
            out: dict[str, float] = {}
            for p in items:
                try:
                    v = float(data.get(p, data.get(p.split("/")[-1], 0)))
                except Exception:
                    v = 0.0
                out[p] = v
            return out
        except Exception:
            return None

    def summarize_file(self, path: str, max_chars: int = 10_000) -> Optional[str]:
        if not self._ensure():
            return None
        text = extract_text_from_file(path)
        if not text:
            return None
        text = text[:max_chars]
        prompt = (
            "You are a helpful assistant. Read the following file content and produce a very concise summary in at most 3 sentences. "
            "Focus on the main purpose, key ideas, and any clear outcomes. Use plain language.\n\n"
            f"CONTENT:\n{text}\n\nSUMMARY:" 
        )
        try:
            out = self._invoke_ai(prompt)
            return out.strip()
        except Exception:
            return None

    def answer_about_file(self, path: str, question: str, max_chars: int = 12_000) -> Optional[str]:
        if not self._ensure():
            return None
        base = extract_text_from_file(path)
        if not base:
            return None
        context = base[:max_chars]
        prompt = (
            "You are assisting with questions about a specific file. Use the provided file content as context."
            " If the answer is not clearly present, say you are not sure. Keep answers concise.\n\n"
            f"FILE CONTENT:\n{context}\n\n"
            f"QUESTION: {question}\n\nANSWER:"
        )
        try:
            out = self._invoke_ai(prompt)
            return out.strip()
        except Exception:
            return None

