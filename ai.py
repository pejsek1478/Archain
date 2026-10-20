"""Local AI assistant for Archain.

Design goals: stable and portable first, fast second.

* No extra Python packages - only the standard library talks to the model server.
* The model runs in a separate, local inference server (Ollama by default, or any
  OpenAI-compatible server such as llama.cpp's ``llama-server``). Those servers pick the
  right CPU code path at run time (AVX2/AVX-512 on Intel and AMD, NEON on ARM) and use
  several threads, so this app never has to be compiled for a specific processor.
* CPU only by default: GPU drivers are the most common source of crashes, so the GPU is
  never touched unless ARCHAIN_AI_USE_GPU=1.
* On a CPU the expensive part is reading the prompt, so the app sends a *small* prompt:
  statistics are computed in Python and only the few most relevant entries are included.
* Only one generation runs at a time (extra requests wait in a short queue), because
  several parallel generations on the same cores just make everything slower.
"""

import http.client
import json
import os
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter
from datetime import timedelta
from pathlib import Path

TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}

CONFIG_PATH = Path(__file__).with_name("ai_config.json")


def load_ai_config():
    """Load AI prompts from JSON config file."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {
            "system_prompt": "You are the assistant of Archain, a field diary for archaeologists. Answer using ONLY the diary overview and entries given below. If the answer is not in them, say that the diary does not contain it. Never invent finds, dates, measurements or places. Cite entries as [#id], for example [#12]. Reply in the language of the user's question. Be short and concrete.",
            "suggest_prompt": "You label entries of an archaeological field diary.\nReply with exactly two lines and nothing else:\nTitle: <short title, at most 8 words>\nTags: <3 to 6 short lowercase tags separated by commas>\nKeep the words 'Title:' and 'Tags:' in English, but write the title and the tags in the language of the notes. Reuse these existing tags when they fit: {existing_tags}.",
            "default_model": "qwen3.5:4b"
        }


AI_PROMPTS = load_ai_config()


def _int(value, default, low, high):
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def fetch_ollama_models(url):
    """Fetch available models from Ollama server."""
    try:
        req = urllib.request.Request(f"{url.rstrip('/')}/api/tags", method="GET")
        with _OPENER.open(req, timeout=3) as resp:
            data = json.loads(resp.read(2_000_000) or b"{}")
        return [m.get("name") or m.get("model") or "" for m in data.get("models", [])]
    except Exception:
        return []


class AIConfig:
    """All settings come from environment variables (see README)."""

    def __init__(self, env=None):
        env = os.environ if env is None else env
        self.enabled = env.get("ARCHAIN_AI", "on").strip().lower() not in FALSE_VALUES
        backend = env.get("ARCHAIN_AI_BACKEND", "ollama").strip().lower()
        self.backend = backend if backend in {"ollama", "openai"} else "ollama"
        default_url = "http://127.0.0.1:11434" if self.backend == "ollama" else "http://127.0.0.1:8080"
        self.url = env.get("ARCHAIN_AI_URL", default_url).strip().rstrip("/") or default_url
        
        # Load model from env or fetch from Ollama
        env_model = env.get("ARCHAIN_AI_MODEL", "").strip()
        if env_model:
            self.model = env_model
        elif self.backend == "ollama":
            models = fetch_ollama_models(self.url)
            self.model = next((m for m in models if AI_PROMPTS.get("default_model", "qwen3.5:4b") in m), AI_PROMPTS.get("default_model", "qwen3.5:4b"))
        else:
            self.model = AI_PROMPTS.get("default_model", "qwen3.5:4b")
            
        # None = let the runtime choose (Ollama picks the physical/performance cores).
        self.threads = _int(env.get("ARCHAIN_AI_THREADS"), None, 1, 512)
        self.ctx = _int(env.get("ARCHAIN_AI_CTX"), 4096, 1024, 131072)
        self.max_tokens = _int(env.get("ARCHAIN_AI_MAX_TOKENS"), 400, 32, 4096)
        self.context_chars = _int(env.get("ARCHAIN_AI_CONTEXT_CHARS"), 3500, 800, 60000)
        self.use_gpu = env.get("ARCHAIN_AI_USE_GPU", "0").strip().lower() in TRUE_VALUES
        self.keep_alive = env.get("ARCHAIN_AI_KEEP_ALIVE", "30m").strip() or "30m"
        self.timeout = _int(env.get("ARCHAIN_AI_TIMEOUT"), 300, 10, 3600)
        self.queue_timeout = _int(env.get("ARCHAIN_AI_QUEUE_TIMEOUT"), 90, 1, 3600)
        self.api_key = env.get("ARCHAIN_AI_API_KEY", "").strip()


class AIError(Exception):
    """An error that is safe to show to the user."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.message = message
        self.status = status


# Never use system proxy settings for the model server: it is almost always on localhost.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_GEN_LOCK = threading.Lock()


def _error_text(err):
    try:
        body = err.read(4000).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 - best effort only
        return ""
    try:
        data = json.loads(body)
        found = data.get("error") if isinstance(data, dict) else None
        if isinstance(found, dict):
            found = found.get("message")
        if found:
            return str(found)[:300]
    except ValueError:
        pass
    return body.strip()[:300]


def _has_model(wanted, installed):
    wanted = wanted.lower()
    if ":" not in wanted.rsplit("/", 1)[-1]:
        wanted += ":latest"
    for name in installed:
        name = (name or "").lower()
        if name == wanted or name == wanted.replace(":latest", ""):
            return True
    return False


class _ThinkStripper:
    """Removes <think>...</think> blocks from a stream, even when a tag is split across chunks."""

    OPEN = "<think>"
    CLOSE = "</think>"

    def __init__(self):
        self.buffer = ""
        self.inside = False
        self.after_block = False

    @staticmethod
    def _partial(text, tag):
        for size in range(min(len(tag) - 1, len(text)), 0, -1):
            if tag.startswith(text[-size:]):
                return size
        return 0

    def feed(self, text):
        self.buffer += text
        out = []
        while True:
            if self.inside:
                index = self.buffer.find(self.CLOSE)
                if index == -1:
                    keep = self._partial(self.buffer, self.CLOSE)
                    self.buffer = self.buffer[len(self.buffer) - keep:] if keep else ""
                    break
                self.buffer = self.buffer[index + len(self.CLOSE):]
                self.inside = False
                self.after_block = True
            else:
                index = self.buffer.find(self.OPEN)
                if index == -1:
                    keep = self._partial(self.buffer, self.OPEN)
                    cut = len(self.buffer) - keep
                    out.append(self.buffer[:cut])
                    self.buffer = self.buffer[cut:]
                    break
                out.append(self.buffer[:index])
                self.buffer = self.buffer[index + len(self.OPEN):]
                self.inside = True
        result = "".join(out)
        if self.after_block and result:
            result = result.lstrip()
            self.after_block = not result
        return result

    def flush(self):
        if self.inside:
            self.buffer = ""
            return ""
        result, self.buffer = self.buffer, ""
        return result.lstrip() if self.after_block else result


class AIClient:
    def __init__(self, config):
        self.cfg = config
        self._send_think = True  # switched off for servers/models that reject the flag
        self._last_warm = None

    # ------------------------------------------------------------------ plumbing
    def describe(self):
        cfg = self.cfg
        return {
            "backend": cfg.backend,
            "url": cfg.url,
            "model": cfg.model,
            "threads": cfg.threads or "auto",
            "gpu": cfg.use_gpu,
            "ctx": cfg.ctx,
            "logical_cpus": os.cpu_count(),
        }

    def _request(self, method, path, payload=None, timeout=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if self.cfg.api_key:
            headers["Authorization"] = "Bearer " + self.cfg.api_key
        request = urllib.request.Request(self.cfg.url + path, data=data, headers=headers, method=method)
        try:
            return _OPENER.open(request, timeout=timeout or self.cfg.timeout)
        except urllib.error.HTTPError as err:
            message = _error_text(err)
            status = err.code
            err.close()
            raise AIError(message or f"The AI server answered with HTTP {status}.", status=status) from None
        except urllib.error.URLError as err:
            raise AIError(f"Cannot reach the AI server at {self.cfg.url} ({err.reason}). Is it running?") from None
        except (OSError, http.client.HTTPException) as err:
            raise AIError(f"The connection to the AI server failed ({err}).") from None

    def status(self):
        cfg = self.cfg
        info = self.describe()
        info.update(enabled=cfg.enabled, state="unreachable", message="", hint="", installed=[])
        try:
            if cfg.backend == "ollama":
                with self._request("GET", "/api/tags", timeout=3) as response:
                    data = json.loads(response.read(2_000_000) or b"{}")
                names = [m.get("name") or m.get("model") or "" for m in data.get("models", [])]
                info["installed"] = names[:30]
                if _has_model(cfg.model, names):
                    info["state"] = "ok"
                else:
                    info["state"] = "model_missing"
                    info["message"] = f"The model {cfg.model} is not installed on the AI server."
                    info["hint"] = f"ollama pull {cfg.model}"
            else:
                with self._request("GET", "/v1/models", timeout=3) as response:
                    response.read(1000)
                info["state"] = "ok"
        except AIError as err:
            if err.status is not None and cfg.backend != "ollama":
                info["state"] = "ok"  # the server answered, it just has no /v1/models
            else:
                info["message"] = err.message
                if cfg.backend == "ollama":
                    info["hint"] = f"Install Ollama (ollama.com), start it, then run: ollama pull {cfg.model}"
                else:
                    info["hint"] = "Start your OpenAI-compatible server (for example llama-server)."
        return info

    # ------------------------------------------------------------------ generation
    def _load_options(self):
        """Options that make Ollama (re)load the model - they must be identical for every call."""
        options = {"num_ctx": self.cfg.ctx}
        if self.cfg.threads:
            options["num_thread"] = self.cfg.threads
        if not self.cfg.use_gpu:
            options["num_gpu"] = 0
        return options

    def _open_ollama_chat(self, payload):
        try:
            return self._request("POST", "/api/chat", payload)
        except AIError as err:
            if "think" in payload and err.status == 400 and "think" in err.message.lower():
                payload.pop("think")
                self._send_think = False
                return self._request("POST", "/api/chat", payload)
            raise

    def _friendly(self, err):
        text = err.message.lower()
        if err.status == 404 and "not found" in text and self.cfg.backend == "ollama":
            return AIError(
                f"The model {self.cfg.model} is not installed. Run: ollama pull {self.cfg.model}",
                status=404,
            )
        return err

    def _stream_ollama(self, messages, max_tokens, temperature):
        payload = {
            "model": self.cfg.model,
            "messages": messages,
            "stream": True,
            "keep_alive": self.cfg.keep_alive,
            "options": {**self._load_options(), "num_predict": max_tokens, "temperature": temperature},
        }
        if self._send_think:
            payload["think"] = False  # reasoning models would burn minutes of CPU time on hidden thoughts
        try:
            response = self._open_ollama_chat(payload)
        except AIError as err:
            raise self._friendly(err) from None
        stats = {}
        announced = False
        try:
            for raw in response:
                line = raw.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if obj.get("error"):
                    raise AIError(str(obj["error"])[:300])
                message = obj.get("message") or {}
                text = message.get("content") or ""
                if text:
                    yield ("delta", text)
                elif message.get("thinking") and not announced:
                    announced = True
                    yield ("thinking", "")
                if obj.get("done"):
                    stats = {
                        "tokens": obj.get("eval_count"),
                        "eval_seconds": (obj.get("eval_duration") or 0) / 1e9,
                    }
                    break
        finally:
            response.close()
        yield ("done", stats)

    def _stream_openai(self, messages, max_tokens, temperature):
        payload = {
            "model": self.cfg.model,
            "messages": messages,
            "stream": True,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        try:
            response = self._request("POST", "/v1/chat/completions", payload)
        except AIError as err:
            raise self._friendly(err) from None
        chunks = 0
        try:
            for raw in response:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except ValueError:
                    continue
                if obj.get("error"):
                    error = obj["error"]
                    raise AIError(str(error.get("message") if isinstance(error, dict) else error)[:300])
                choices = obj.get("choices") or []
                delta = (choices[0].get("delta") or {}) if choices else {}
                text = delta.get("content") or ""
                if text:
                    chunks += 1
                    yield ("delta", text)
                elif delta.get("reasoning_content") and chunks == 0:
                    yield ("thinking", "")
        finally:
            response.close()
        yield ("done", {"tokens": chunks, "eval_seconds": 0})

    def stream_chat(self, messages, max_tokens=None, temperature=0.3):
        """Yield events: queued, start, thinking, delta, done. Raises AIError on failure."""
        max_tokens = max_tokens or self.cfg.max_tokens
        if not _GEN_LOCK.acquire(blocking=False):
            yield {"type": "queued"}
            if not _GEN_LOCK.acquire(timeout=self.cfg.queue_timeout):
                raise AIError("The assistant is busy with another request. Please try again in a moment.", status=429)
        inner = None
        try:
            yield {"type": "start"}
            opener = self._stream_ollama if self.cfg.backend == "ollama" else self._stream_openai
            inner = opener(messages, max_tokens, temperature)
            started = time.monotonic()
            stripper = _ThinkStripper()
            produced = False
            stats = {}
            for kind, value in inner:
                if kind == "delta":
                    text = stripper.feed(value)
                    if not produced:
                        text = text.lstrip()
                    if text:
                        produced = True
                        yield {"type": "delta", "text": text}
                elif kind == "thinking":
                    yield {"type": "thinking"}
                else:
                    stats = value
            tail = stripper.flush()
            if not produced:
                tail = tail.lstrip()
            if tail:
                produced = True
                yield {"type": "delta", "text": tail}
            if not produced:
                raise AIError(
                    "The model returned an empty answer. Use an instruct (non-reasoning) model "
                    "or raise ARCHAIN_AI_MAX_TOKENS."
                )
            elapsed = time.monotonic() - started
            tokens = stats.get("tokens")
            eval_seconds = stats.get("eval_seconds") or 0
            rate = None
            if tokens and eval_seconds:
                rate = tokens / eval_seconds
            elif tokens and elapsed:
                rate = tokens / elapsed
            yield {
                "type": "done",
                "tokens": tokens,
                "seconds": round(elapsed, 1),
                "tps": round(rate, 1) if rate else None,
            }
        except (OSError, http.client.HTTPException) as err:
            raise AIError(f"The connection to the AI server was interrupted ({err}).") from None
        finally:
            if inner is not None:
                inner.close()
            _GEN_LOCK.release()

    def complete(self, messages, max_tokens, temperature=0.2):
        parts = []
        for event in self.stream_chat(messages, max_tokens=max_tokens, temperature=temperature):
            if event["type"] == "delta":
                parts.append(event["text"])
        return "".join(parts)

    def warm_up(self):
        """Load the model into memory so the first question does not wait for the disk."""
        now = time.monotonic()
        if self.cfg.backend != "ollama" or (self._last_warm is not None and now - self._last_warm < 20):
            return
        self._last_warm = now
        if not _GEN_LOCK.acquire(blocking=False):
            return  # busy means the model is already loaded
        try:
            payload = {
                "model": self.cfg.model,
                "messages": [],
                "keep_alive": self.cfg.keep_alive,
                "options": self._load_options(),
            }
            with self._request("POST", "/api/chat", payload) as response:
                response.read(100_000)
        except AIError:
            pass
        finally:
            _GEN_LOCK.release()

    def warm_up_async(self):
        threading.Thread(target=self.warm_up, name="archain-ai-warmup", daemon=True).start()


# ---------------------------------------------------------------------- text helpers
def fold(text):
    """Lower-case and strip diacritics so 'Keramika' and 'keramiká' compare equal."""
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(char for char in text if not unicodedata.combining(char)).lower()


_STOPWORDS = {
    fold(word)
    for word in """
    the and for with from that this what which who how many much were was are did does any about have has had
    our you your all can tell show give list please entry entries record records note notes diary
    jake jaky jaka jaci ktere ktery ktera kolik kde kdy proc pro pri ale nebo aby tak tam tady ten tyto tento
    tato vsech vsechny mam mame jsme jsem jsou byl byla bylo byly zaznam zaznamy zaznamu denik poznamky
    najdi ukaz rekni napis jak
    """.split()
}


def _stem(word):
    if len(word) >= 6:
        return word[:5]
    if len(word) == 5:
        return word[:4]
    return word


def keywords(question):
    words = re.findall(r"\w+", fold(question))
    return list(dict.fromkeys(_stem(w) for w in words if len(w) >= 3 and w not in _STOPWORDS))


def rank_entries(question, entries):
    """Return (score, entry) pairs with score > 0, best first (ties keep the incoming newest-first order)."""
    stems = keywords(question)
    if not stems:
        return []
    scored = []
    for entry in entries:
        title = fold(entry["title"])
        tags = fold(" ".join(entry["tags"]))
        place = fold(" ".join(filter(None, [entry["location"], " ".join(entry["people"]), entry["author"] or ""])))
        notes = fold(entry["notes"])
        score = 0
        for stem in stems:
            if stem in title:
                score += 4
            if stem in tags:
                score += 3
            if stem in place:
                score += 2
            score += min(notes.count(stem), 3)
        if score:
            scored.append((score, entry))
    scored.sort(key=lambda pair: -pair[0])
    return scored


# ---------------------------------------------------------------------- statistics
def build_stats(entries):
    """Numbers are computed here in Python - small models are bad at counting, good at explaining."""
    total = len(entries)
    stats = {
        "total": total, "first": None, "last": None, "with_gps": 0, "with_files": 0, "files": 0,
        "tags": [], "people": [], "authors": [], "weeks": [],
    }
    if not total:
        return stats
    dated = [e["when"] for e in entries if e["when"]]
    if dated:
        stats["first"] = min(dated).strftime("%Y-%m-%d")
        stats["last"] = max(dated).strftime("%Y-%m-%d")
    stats["with_gps"] = sum(1 for e in entries if e["lat"] is not None and e["lon"] is not None)
    stats["with_files"] = sum(1 for e in entries if e["files"])
    stats["files"] = sum(e["files"] for e in entries)
    stats["tags"] = Counter(t for e in entries for t in e["tags"]).most_common(10)
    stats["people"] = Counter(p for e in entries for p in e["people"]).most_common(6)
    stats["authors"] = Counter(e["author"] for e in entries if e["author"]).most_common(6)
    if dated:
        newest = max(dated).date()
        monday = newest - timedelta(days=newest.weekday())
        buckets = Counter()
        for moment in dated:
            day = moment.date()
            buckets[day - timedelta(days=day.weekday())] += 1
        weeks = []
        for offset in range(7, -1, -1):
            start = monday - timedelta(weeks=offset)
            year, week, _ = start.isocalendar()
            weeks.append({"label": f"{year}-W{week:02d}", "count": buckets.get(start, 0)})
        peak = max(w["count"] for w in weeks) or 1
        for item in weeks:
            item["pct"] = round(100 * item["count"] / peak)
        stats["weeks"] = weeks
    return stats


def stats_text(stats):
    if not stats["total"]:
        return "The diary is empty."
    lines = [
        f"Entries: {stats['total']}"
        + (f", from {stats['first']} to {stats['last']}" if stats["first"] else "")
        + f"; {stats['with_gps']} with GPS; {stats['with_files']} with files ({stats['files']} files in total)."
    ]
    if stats["weeks"]:
        lines.append("Entries per week (oldest to newest): " + ", ".join(f"{w['label']}: {w['count']}" for w in stats["weeks"]))
    if stats["tags"]:
        lines.append("Top tags: " + ", ".join(f"{name} ({count})" for name, count in stats["tags"][:8]))
    if stats["people"]:
        lines.append("Finders: " + ", ".join(f"{name} ({count})" for name, count in stats["people"][:5]))
    if stats["authors"]:
        lines.append("Authors: " + ", ".join(f"{name} ({count})" for name, count in stats["authors"][:5]))
    return "\n".join(lines)


# ---------------------------------------------------------------------- prompts
SYSTEM_PROMPT = AI_PROMPTS.get("system_prompt", "You are the assistant of Archain, a field diary for archaeologists.\nAnswer using ONLY the diary overview and entries given below. If the answer is not in them, say that the diary does not contain it. Never invent finds, dates, measurements or places.\nCite entries as [#id], for example [#12]. Reply in the language of the user's question. Be short and concrete.")


def entry_block(entry, note_chars):
    meta = []
    if entry["when"]:
        meta.append(entry["when"].strftime("%Y-%m-%d %H:%M"))
    if entry["location"]:
        meta.append(entry["location"])
    if entry["lat"] is not None and entry["lon"] is not None:
        meta.append(f"GPS {entry['lat']:.5f}, {entry['lon']:.5f}")
    if entry["weather"]:
        meta.append(f"weather: {entry['weather']}")
    if entry["tags"]:
        meta.append("tags: " + ", ".join(entry["tags"]))
    if entry["people"]:
        meta.append("found by: " + ", ".join(entry["people"]))
    if entry["author"]:
        meta.append("author: " + entry["author"])
    if entry["files"]:
        meta.append(f"{entry['files']} file(s)")
    notes = " ".join((entry["notes"] or "").split())
    if len(notes) > note_chars:
        notes = notes[:note_chars].rstrip() + "…"
    head = f"[#{entry['id']}] {entry['title']}"
    if meta:
        head += " | " + " | ".join(meta)
    return head + "\n" + notes


def _clean_history(history, char_budget):
    cleaned = []
    for item in history if isinstance(history, list) else []:
        if not isinstance(item, dict):
            continue
        role, content = item.get("role"), item.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str) or not content.strip():
            continue
        if cleaned and cleaned[-1]["role"] == role:
            continue  # models expect alternating turns
        cleaned.append({"role": role, "content": content.strip()[:1200]})
    cleaned = cleaned[-6:]
    while cleaned and cleaned[0]["role"] != "user":
        cleaned.pop(0)
    while cleaned and sum(len(m["content"]) for m in cleaned) > char_budget:
        cleaned = cleaned[2:] if len(cleaned) > 1 else []
    if cleaned and cleaned[-1]["role"] == "user":
        cleaned.pop()  # the current question is added separately
    return cleaned


def build_chat_messages(question, history, entries, cfg, focus_id=None):
    """Build the (small) prompt and return (messages, sources).

    ``entries`` must already be limited to what the current user may see, newest first.
    """
    question = question.strip()[:1000]
    overview = stats_text(build_stats(entries))
    system = SYSTEM_PROMPT + "\n\nDIARY OVERVIEW\n" + overview  # stable prefix: cached by the server between turns

    prompt_budget = int((cfg.ctx - cfg.max_tokens - 256) * 2.5)  # ~2.5 characters per token is safe for most languages
    history_budget = min(2400, max(0, prompt_budget // 4))
    history_messages = _clean_history(history, history_budget)
    used_history = sum(len(m["content"]) for m in history_messages)
    context_budget = prompt_budget - len(system) - len(question) - used_history - 200
    context_budget = max(600, min(cfg.context_chars, context_budget))

    candidates = []
    seen = set()
    focus = next((e for e in entries if e["id"] == focus_id), None) if focus_id else None
    if focus:
        candidates.append((focus, 1800))
        seen.add(focus["id"])
    for _, entry in rank_entries(question, entries)[:8]:
        if entry["id"] not in seen:
            candidates.append((entry, 700 if len(candidates) < 3 else 350))
            seen.add(entry["id"])
    for entry in entries:  # not enough hits (or an overview question): add the newest entries
        if len(candidates) >= 3:
            break
        if entry["id"] not in seen:
            candidates.append((entry, 350))
            seen.add(entry["id"])

    blocks, sources, used = [], [], 0
    for entry, note_chars in candidates:
        block = entry_block(entry, note_chars)
        if blocks and used + len(block) > context_budget:
            break
        if not blocks and len(block) > context_budget:
            block = block[:context_budget].rstrip() + "…"
        blocks.append(block)
        sources.append({"id": entry["id"], "title": entry["title"]})
        used += len(block) + 2

    context = "\n\n".join(blocks) if blocks else "(no entries)"
    user = f"DIARY ENTRIES\n{context}\n\nQUESTION\n{question}"
    messages = [{"role": "system", "content": system}, *history_messages, {"role": "user", "content": user}]
    return messages, sources


def build_suggest_messages(title, notes, existing_tags):
    existing = ", ".join(existing_tags[:40]) or "(none yet)"
    template = AI_PROMPTS.get("suggest_prompt", "You label entries of an archaeological field diary.\nReply with exactly two lines and nothing else:\nTitle: <short title, at most 8 words>\nTags: <3 to 6 short lowercase tags separated by commas>\nKeep the words 'Title:' and 'Tags:' in English, but write the title and the tags in the language of the notes. Reuse these existing tags when they fit: {existing_tags}.")
    system = template.format(existing_tags=existing)
    user = f"Current title: {title.strip() or '(none)'}\nNotes:\n{' '.join(notes.split())[:1500]}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _clean_label(value):
    return re.sub(r"[*_`]+", "", value).strip().strip("\"'“”‘’ ").strip()


def parse_suggestion(text):
    title, tag_line = "", ""
    for line in text.splitlines():
        match = re.match(r"^\W*title\s*[:\-]\s*(.+)$", line, re.I)
        if match and not title:
            title = _clean_label(match.group(1))[:120]
            continue
        match = re.match(r"^\W*tags?\s*[:\-]\s*(.+)$", line, re.I)
        if match and not tag_line:
            tag_line = match.group(1)
    if not tag_line and not title and len(text) < 300:
        # the model skipped the labels: use the first line that looks like a comma separated list
        tag_line = next((line for line in text.splitlines() if "," in line), "")
    tags = []
    for token in re.split(r"[,;\n]", tag_line):
        tag = re.sub(r"^[#\-\s\d.)]+", "", _clean_label(token))
        tag = " ".join(tag.lower().split())
        if 2 <= len(tag) <= 40 and ":" not in tag and tag not in tags:
            tags.append(tag)
    return {"title": title, "tags": tags[:6]}


def popular_tags(entries, limit=40):
    return [name for name, _ in Counter(t for e in entries for t in e["tags"]).most_common(limit)]
