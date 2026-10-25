"""Archain AI package."""
from .ai import AIConfig, AIClient, AIError, fetch_ollama_models, build_chat_messages, build_suggest_messages, popular_tags, parse_suggestion, rank_entries, keywords, fold, stats_text, build_stats, _ThinkStripper

__all__ = [
    "AIConfig",
    "AIClient",
    "AIError",
    "fetch_ollama_models",
    "build_chat_messages",
    "build_suggest_messages",
    "popular_tags",
    "parse_suggestion",
    "rank_entries",
    "keywords",
    "fold",
    "stats_text",
    "build_stats",
    "_ThinkStripper",
]