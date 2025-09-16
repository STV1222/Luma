from __future__ import annotations
import os
import json
from typing import Dict, Any
from PyQt6.QtCore import QLocale, QTranslator, QCoreApplication
from PyQt6.QtWidgets import QApplication

class TranslationManager:
    """Manages translations and language switching for the application."""
    
    def __init__(self):
        self.current_language = "en"
        self.translations: Dict[str, Dict[str, str]] = {}
        self.translator = QTranslator()
        self.load_translations()
    
    def load_translations(self):
        """Load all available translations from the translations directory."""
        translations_dir = os.path.join(os.path.dirname(__file__), "translations")
        
        if not os.path.exists(translations_dir):
            os.makedirs(translations_dir)
            self._create_default_translations()
        
        for filename in os.listdir(translations_dir):
            if filename.endswith('.json'):
                lang_code = filename[:-5]  # Remove .json extension
                filepath = os.path.join(translations_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        self.translations[lang_code] = json.load(f)
                except Exception as e:
                    print(f"Failed to load translation {lang_code}: {e}")
    
    def _create_default_translations(self):
        """Create default translation files for major languages."""
        translations_dir = os.path.join(os.path.dirname(__file__), "translations")
        
        # English (default)
        en_translations = {
            "app_title": "Luma (Modular)",
            "search_placeholder": "Search for apps and commands...",
            "ask_ai": "Ask AI",
            "no_ai": "No AI",
            "private_mode": "Private Mode",
            "cloud_mode": "Cloud Mode",
            "ask_follow_up": "Ask follow-up…",
            "send": "Send",
            "metadata": "Metadata",
            "summary": "Summary",
            "summarize": "Summarize",
            "loading_preview": "Loading preview...",
            "preview_failed": "Preview failed",
            "question_failed": "Question failed",
            "summary_failed": "Summary failed",
            "ai_thinking": "AI is thinking…",
            "you": "You",
            "ai": "AI",
            "summary_intro": "Summary (3 sentences max):",
            "file_types": {
                "all": "All",
                "documents": "Documents",
                "images": "Images",
                "slides": "Slides",
                "pdf": "PDF",
                "spreadsheets": "Spreadsheets",
                "code": "Code"
            },
            "settings": "Settings",
            "language": "Language",
            "select_language": "Select Language",
            "back": "←"
        }
        
        # Spanish
        es_translations = {
            "app_title": "Luma (Modular)",
            "search_placeholder": "Buscar aplicaciones y comandos...",
            "ask_ai": "Preguntar IA",
            "no_ai": "Sin IA",
            "private_mode": "Modo Privado",
            "cloud_mode": "Modo Nube",
            "ask_follow_up": "Hacer seguimiento…",
            "send": "Enviar",
            "metadata": "Metadatos",
            "summary": "Resumen",
            "summarize": "Resumir",
            "loading_preview": "Cargando vista previa...",
            "preview_failed": "Vista previa falló",
            "question_failed": "Pregunta falló",
            "summary_failed": "Resumen falló",
            "ai_thinking": "La IA está pensando…",
            "you": "Tú",
            "ai": "IA",
            "summary_intro": "Resumen (máximo 3 oraciones):",
            "file_types": {
                "all": "Todos",
                "documents": "Documentos",
                "images": "Imágenes",
                "slides": "Presentaciones",
                "pdf": "PDF",
                "spreadsheets": "Hojas de cálculo",
                "code": "Código"
            },
            "settings": "Configuración",
            "language": "Idioma",
            "select_language": "Seleccionar Idioma",
            "back": "←"
        }
        
        # French
        fr_translations = {
            "app_title": "Luma (Modulaire)",
            "search_placeholder": "Rechercher des applications et commandes...",
            "ask_ai": "Demander IA",
            "no_ai": "Sans IA",
            "private_mode": "Mode Privé",
            "cloud_mode": "Mode Cloud",
            "ask_follow_up": "Poser une question de suivi…",
            "send": "Envoyer",
            "metadata": "Métadonnées",
            "summary": "Résumé",
            "summarize": "Résumer",
            "loading_preview": "Chargement de l'aperçu...",
            "preview_failed": "Échec de l'aperçu",
            "question_failed": "Question échouée",
            "summary_failed": "Résumé échoué",
            "ai_thinking": "L'IA réfléchit…",
            "you": "Vous",
            "ai": "IA",
            "summary_intro": "Résumé (3 phrases max):",
            "file_types": {
                "all": "Tous",
                "documents": "Documents",
                "images": "Images",
                "slides": "Présentations",
                "pdf": "PDF",
                "spreadsheets": "Feuilles de calcul",
                "code": "Code"
            },
            "settings": "Paramètres",
            "language": "Langue",
            "select_language": "Sélectionner la Langue",
            "back": "←"
        }
        
        # German
        de_translations = {
            "app_title": "Luma (Modular)",
            "search_placeholder": "Apps und Befehle suchen...",
            "ask_ai": "KI fragen",
            "no_ai": "Keine KI",
            "private_mode": "Privater Modus",
            "cloud_mode": "Cloud Modus",
            "ask_follow_up": "Nachfrage stellen…",
            "send": "Senden",
            "metadata": "Metadaten",
            "summary": "Zusammenfassung",
            "summarize": "Zusammenfassen",
            "loading_preview": "Vorschau wird geladen...",
            "preview_failed": "Vorschau fehlgeschlagen",
            "question_failed": "Frage fehlgeschlagen",
            "summary_failed": "Zusammenfassung fehlgeschlagen",
            "ai_thinking": "KI denkt nach…",
            "you": "Sie",
            "ai": "KI",
            "summary_intro": "Zusammenfassung (max. 3 Sätze):",
            "file_types": {
                "all": "Alle",
                "documents": "Dokumente",
                "images": "Bilder",
                "slides": "Präsentationen",
                "pdf": "PDF",
                "spreadsheets": "Tabellenkalkulationen",
                "code": "Code"
            },
            "settings": "Einstellungen",
            "language": "Sprache",
            "select_language": "Sprache auswählen",
            "back": "←"
        }
        
        # Chinese (Simplified)
        zh_translations = {
            "app_title": "Luma (模块化)",
            "search_placeholder": "搜索应用程序和命令...",
            "ask_ai": "询问AI",
            "no_ai": "无AI",
            "private_mode": "私有模式",
            "cloud_mode": "云模式",
            "ask_follow_up": "询问后续问题…",
            "send": "发送",
            "metadata": "元数据",
            "summary": "摘要",
            "summarize": "总结",
            "loading_preview": "正在加载预览...",
            "preview_failed": "预览失败",
            "question_failed": "问题失败",
            "summary_failed": "摘要失败",
            "ai_thinking": "AI正在思考…",
            "you": "您",
            "ai": "AI",
            "summary_intro": "摘要（最多3句话）：",
            "file_types": {
                "all": "全部",
                "documents": "文档",
                "images": "图片",
                "slides": "演示文稿",
                "pdf": "PDF",
                "spreadsheets": "电子表格",
                "code": "代码"
            },
            "settings": "设置",
            "language": "语言",
            "select_language": "选择语言",
            "back": "←"
        }
        
        # Japanese
        ja_translations = {
            "app_title": "Luma (モジュラー)",
            "search_placeholder": "アプリとコマンドを検索...",
            "ask_ai": "AIに質問",
            "no_ai": "AIなし",
            "private_mode": "プライベートモード",
            "cloud_mode": "クラウドモード",
            "ask_follow_up": "フォローアップ質問…",
            "send": "送信",
            "metadata": "メタデータ",
            "summary": "要約",
            "summarize": "要約する",
            "loading_preview": "プレビューを読み込み中...",
            "preview_failed": "プレビューに失敗",
            "question_failed": "質問に失敗",
            "summary_failed": "要約に失敗",
            "ai_thinking": "AIが考えています…",
            "you": "あなた",
            "ai": "AI",
            "summary_intro": "要約（最大3文）：",
            "file_types": {
                "all": "すべて",
                "documents": "ドキュメント",
                "images": "画像",
                "slides": "プレゼンテーション",
                "pdf": "PDF",
                "spreadsheets": "スプレッドシート",
                "code": "コード"
            },
            "settings": "設定",
            "language": "言語",
            "select_language": "言語を選択",
            "back": "←"
        }
        
        # Save all translation files
        translations = {
            "en": en_translations,
            "es": es_translations,
            "fr": fr_translations,
            "de": de_translations,
            "zh": zh_translations,
            "ja": ja_translations
        }
        
        for lang_code, translations_data in translations.items():
            filepath = os.path.join(translations_dir, f"{lang_code}.json")
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(translations_data, f, ensure_ascii=False, indent=2)
    
    def get_available_languages(self) -> Dict[str, str]:
        """Get available languages with their display names."""
        return {
            "en": "English",
            "es": "Español",
            "fr": "Français",
            "de": "Deutsch",
            "zh": "中文",
            "ja": "日本語"
        }
    
    def set_language(self, lang_code: str):
        """Set the current language."""
        if lang_code in self.translations:
            self.current_language = lang_code
            return True
        return False
    
    def translate(self, key: str, **kwargs) -> str:
        """Get translated text for a key."""
        if self.current_language in self.translations:
            translation = self.translations[self.current_language].get(key, key)
        else:
            translation = self.translations.get("en", {}).get(key, key)
        
        # Handle nested keys (e.g., "file_types.documents")
        if "." in key:
            parts = key.split(".")
            current = self.translations.get(self.current_language, {})
            for part in parts:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    return key
            translation = current
        
        # Format with kwargs if provided
        try:
            return translation.format(**kwargs)
        except (KeyError, ValueError):
            return translation
    
    def get_current_language(self) -> str:
        """Get the current language code."""
        return self.current_language

# Global translation manager instance
_translation_manager = None

def get_translation_manager() -> TranslationManager:
    """Get the global translation manager instance."""
    global _translation_manager
    if _translation_manager is None:
        _translation_manager = TranslationManager()
    return _translation_manager

def tr(key: str, **kwargs) -> str:
    """Convenience function for translation."""
    return get_translation_manager().translate(key, **kwargs)
