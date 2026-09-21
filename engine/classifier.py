"""
Multi-Signal Classification Engine for Sorti (v2.2 Overhaul).
Sniffs document text in-memory (<5ms) from Word (.docx), PowerPoint (.pptx), and multi-page PDFs (<15ms).
Applies academic stopword filtering, multi-word phrase entity recognition,
parent-course semantic isolation, few-shot exemplar folder memory, and ambiguity triage guards.
"""

from pathlib import Path
import zipfile
import re
import json
import xml.etree.ElementTree as ET
from typing import Dict, List, Any, Optional, Tuple, Set

import numpy as np

# Roman numeral mapping for academic seminars (e.g. Seminar IV -> 4)
ROMAN_NUMERALS = {
    'i': 1, 'ii': 2, 'iii': 3, 'iv': 4, 'v': 5,
    'vi': 6, 'vii': 7, 'viii': 8, 'ix': 9, 'x': 10,
    'xi': 11, 'xii': 12, 'xiii': 13, 'xiv': 14, 'xv': 15
}

BROADER_DOC_MARKERS = [
    "course specification", "course spec", "syllabus", "course guide",
    "course handbook", "handbook", "course outline", "module outline",
    "reading list", "assessment guidance", "general information",
    "timetable", "course info", "programme specification"
]

# Comprehensive stopword list covering common English discourse and structural university noise.
# Prevents false positive keyword matches on words like 'you' and 'like' from 'As You Like It'.
ACADEMIC_STOPWORDS = {
    'a', 'about', 'above', 'after', 'again', 'against', 'all', 'am', 'an', 'and', 'any',
    'are', 'as', 'at', 'be', 'because', 'been', 'before', 'being', 'below', 'between',
    'both', 'but', 'by', 'can', 'could', 'did', 'do', 'does', 'doing', 'down', 'during',
    'each', 'few', 'for', 'from', 'further', 'had', 'has', 'have', 'having', 'he',
    'her', 'here', 'hers', 'herself', 'him', 'himself', 'his', 'how', 'i', 'if', 'in',
    'into', 'is', 'it', 'its', 'itself', 'just', 'like', 'me', 'more', 'most', 'my',
    'myself', 'no', 'nor', 'not', 'now', 'of', 'off', 'on', 'once', 'only', 'or',
    'other', 'our', 'ours', 'ourselves', 'out', 'over', 'own', 'same', 'she', 'should',
    'so', 'some', 'such', 'than', 'that', 'the', 'their', 'theirs', 'them', 'themselves',
    'then', 'there', 'these', 'they', 'this', 'those', 'through', 'to', 'too', 'under',
    'until', 'up', 'very', 'was', 'we', 'were', 'what', 'when', 'where', 'which',
    'while', 'who', 'whom', 'why', 'will', 'with', 'would', 'you', 'your', 'yours',
    'yourself', 'yourselves',
    # Academic structural noise tokens
    'seminar', 'week', 'lecture', 'topic', 'tutorial', 'sem', 'lec', 'wk', 'tut',
    'session', 'class', 'module', 'course', 'reading', 'readings', 'part', 'volume',
    'vol', 'edition', 'chapter', 'ch', 'page', 'pages',
    # Academic discourse & meta unigrams (prevents generic unigrams like 'language' or 'words' from bleeding across folders)
    'language', 'words', 'study', 'ideas', 'criticism', 'theory', 'forms', 'uses', 'notes', 'introduction', 'text', 'texts'
}


def extract_subfolder_phrases_and_topics(sub_name: str) -> Tuple[List[str], List[str]]:
    """
    Extracts multi-word entity phrases (e.g. 'as you like it', 'titus andronicus', 'creative morphology')
    and substantive topic unigrams from subfolder names.
    """
    # Split on hyphens, colons, slashes, or underscores to get segments
    segments = re.split(r'[\-_:/|]+', sub_name)
    phrases = []
    topic_tokens = []

    for seg in segments:
        seg_clean = re.sub(r'[^a-zA-Z0-9\s]', ' ', seg).strip().lower()
        words = seg_clean.split()
        if not words:
            continue

        # Ignore pure session prefix segments like "sem4", "week 2", "01"
        if re.match(r'^(?:sem|seminar|week|wk|lecture|lec|topic|tutorial)?\s*0*\d+$', seg_clean):
            continue

        # Multi-word phrase if 2+ words (e.g. "as you like it", "titus andronicus", "creative morphology")
        if len(words) >= 2:
            phrases.append(seg_clean)

        # Substantive non-stopword tokens
        for w in words:
            if len(w) > 2 and w not in ACADEMIC_STOPWORDS:
                topic_tokens.append(w)

    return phrases, list(dict.fromkeys(topic_tokens))


class DocumentClassifier:
    def __init__(self, taxonomy_manager, min_confidence: float = 0.65, semantic_classifier: Optional[Any] = None):
        self.taxonomy_manager = taxonomy_manager
        self.min_confidence = min_confidence
        if semantic_classifier is not None:
            self.semantic_classifier = semantic_classifier
        else:
            try:
                from .semantic import LocalSemanticClassifier
                self.semantic_classifier = LocalSemanticClassifier()
            except Exception as e:
                print(f"[Classifier] Semantic engine notice: {e}")
                self.semantic_classifier = None
        self._embedding_cache: Dict[str, Any] = {}

    def _get_embedding(self, text: str) -> Optional[Any]:
        """Caches and returns normalized dense embedding vector for text."""
        if not self.semantic_classifier or not text or not text.strip():
            return None
        cache_key = text[:250].strip()
        if cache_key in self._embedding_cache:
            return self._embedding_cache[cache_key]
        vec = self.semantic_classifier.embed_text(text)
        if vec is not None:
            self._embedding_cache[cache_key] = vec
        return vec

    def load_rules(self) -> Dict[str, Any]:
        """Loads persistent user rules and learned associations from disk."""
        try:
            rules_file = self.taxonomy_manager.config_file.parent / "rules.json"
            if rules_file.exists():
                with open(rules_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            print(f"[Classifier] Failed to load rules: {e}")
        return {"learned_stems": {}, "file_rules": {}}

    def save_rules(self, rules: Dict[str, Any]) -> None:
        """Persists user rules and learned associations to disk."""
        try:
            rules_file = self.taxonomy_manager.config_file.parent / "rules.json"
            rules_file.parent.mkdir(parents=True, exist_ok=True)
            with open(rules_file, "w", encoding="utf-8") as f:
                json.dump(rules, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[Classifier] Failed to save rules: {e}")

    def learn_user_override(self, filename: str, destination: str) -> None:
        """
        Learns from a user's manual override or triage selection.
        Saves exact file mapping. NEVER saves bare author names to prevent
        cross-unit contamination (e.g. Miriam Jacobson or Ross Cranston).
        Only saves compound stems if they include a distinguishing topic or chapter.
        """
        if not filename or not destination:
            return
        rules = self.load_rules()
        file_rules = rules.setdefault("file_rules", {})
        compound_rules = rules.setdefault("compound_rules", {})

        # 1. Exact filename mapping is always safe and deterministic
        file_rules[filename.lower()] = destination

        # 2. Extract safe compound stem: e.g. "Cranston chapter 1" or "Revision Questions after seminar 3"
        raw_stem = Path(filename).stem.lower()
        chapter_match = re.search(r'\b(?:chapter|ch|part|pt|vol|volume|seminar|sem|week|wk)\s*\d+', raw_stem)
        if chapter_match:
            match_str = chapter_match.group(0)
            prefix_part = raw_stem[:chapter_match.start()].strip(' -_:.')
            if prefix_part:
                compound_key = f"{prefix_part} {match_str}".strip()
                compound_rules[compound_key] = destination

        self.save_rules(rules)

    def extract_docx_text(self, file_path: Path, max_words: int = 800) -> str:
        """Fast in-memory extraction of text from .docx XML without launching Word."""
        extracted = []
        try:
            with zipfile.ZipFile(file_path, 'r') as zf:
                if 'docProps/core.xml' in zf.namelist():
                    try:
                        core_xml = zf.read('docProps/core.xml')
                        root = ET.fromstring(core_xml)
                        for elem in root.iter():
                            if elem.text and elem.text.strip():
                                extracted.append(elem.text.strip())
                    except Exception:
                        pass

                if 'word/document.xml' in zf.namelist():
                    doc_xml = zf.read('word/document.xml').decode('utf-8', errors='ignore')
                    text_only = re.sub(r'<w:p[ >]', '\n', doc_xml)
                    text_only = re.sub(r'<[^>]+>', ' ', text_only)
                    text_only = re.sub(r'\s+', ' ', text_only).strip()
                    words = text_only.split()[:max_words]
                    extracted.append(" ".join(words))
        except Exception as e:
            print(f"[Classifier] Text extraction note on {file_path.name}: {e}")

        return " ".join(extracted)

    def extract_pptx_text(self, file_path: Path, max_words: int = 700) -> str:
        """Fast in-memory extraction of slide titles and content from .pptx XML without PowerPoint."""
        extracted = []
        try:
            with zipfile.ZipFile(file_path, 'r') as zf:
                slide_names = [n for n in zf.namelist() if re.match(r'ppt/slides/slide\d+\.xml', n)]
                slide_names.sort(key=lambda s: int(re.search(r'\d+', s).group()) if re.search(r'\d+', s) else 0)

                for s_name in slide_names[:12]:
                    xml_content = zf.read(s_name).decode('utf-8', errors='ignore')
                    texts = re.findall(r'<a:t[^>]*>(.*?)</a:t>', xml_content)
                    if texts:
                        clean_text = " ".join(t.strip() for t in texts if t.strip())
                        extracted.append(clean_text)

                if 'docProps/core.xml' in zf.namelist():
                    try:
                        core_xml = zf.read('docProps/core.xml')
                        root = ET.fromstring(core_xml)
                        for elem in root.iter():
                            if elem.text and elem.text.strip():
                                extracted.append(elem.text.strip())
                    except Exception:
                        pass

        except Exception as e:
            print(f"[Classifier] PPTX text extraction note on {file_path.name}: {e}")

        all_text = " ".join(extracted)
        return " ".join(all_text.split()[:max_words])

    def extract_pdf_preview(self, file_path: Path, max_pages: int = 20, max_words: int = 4000) -> str:
        """
        Two-Zone Smart Text Extraction (<40ms):
        Zone 1: First 3 pages (title, author, abstract, opening thesis).
        Zone 2: Section headers, structural markers, and play titles sampled across pages 4 to max_pages.
        Strips digital library/publisher cover sheet disclaimers.
        """
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(file_path))
            num_pages = len(reader.pages)
            if num_pages == 0:
                return ""

            collected_text = []

            # Zone 1: First 3 pages (full text)
            zone1_pages = min(num_pages, 3)
            for i in range(zone1_pages):
                try:
                    p_text = reader.pages[i].extract_text() or ""
                    if p_text.strip():
                        collected_text.append(p_text)
                except Exception:
                    continue

            # Zone 2: Structural sample across remaining pages (up to page 20)
            if num_pages > 3:
                max_scan = min(num_pages, max_pages)
                step = 1 if num_pages <= 16 else 2
                for i in range(3, max_scan, step):
                    try:
                        p_text = reader.pages[i].extract_text() or ""
                        if not p_text.strip():
                            continue
                        lines = p_text.split('\n')
                        sampled_lines = []
                        for line in lines:
                            l_str = line.strip()
                            # Keep short/structural lines (headers, titles, subheadings) or act/scene lines
                            if l_str and (len(l_str) < 95 or any(kw in l_str.lower() for kw in ('chapter', 'act', 'scene', 'part', 'section', 'play', 'shakespear'))):
                                sampled_lines.append(l_str)
                        if sampled_lines:
                            collected_text.append(" ".join(sampled_lines))
                        else:
                            words_page = p_text.split()[:80]
                            collected_text.append(" ".join(words_page))
                    except Exception:
                        continue

            full_raw = "\n".join(collected_text)

            # Strip academic repository & publisher cover page boilerplate
            cleaned = re.sub(r'(?i)downloaded\s+(?:from|by).*?(?:\n|$)', ' ', full_raw)
            cleaned = re.sub(r'(?i)access\s+provided\s+by.*?(?:\n|$)', ' ', cleaned)
            cleaned = re.sub(r'(?i)terms\s+and\s+conditions\s+of\s+use.*?(?:\n|$)', ' ', cleaned)
            cleaned = re.sub(r'(?i)all\s+rights\s+reserved.*?(?:\n|$)', ' ', cleaned)
            cleaned = re.sub(r'(?i)this\s+content\s+downloaded\s+from.*?(?:\n|$)', ' ', cleaned)
            cleaned = re.sub(r'(?i)for\s+permissions,\s+please\s+email.*?(?:\n|$)', ' ', cleaned)
            cleaned = re.sub(r'(?i)https?://\S+', ' ', cleaned)
            cleaned = re.sub(r'(?i)doi:\s*10\.\S+', ' ', cleaned)
            cleaned = re.sub(r'\s+', ' ', cleaned).strip()

            words = cleaned.split()[:max_words]
            return " ".join(words)
        except Exception as e:
            print(f"[Classifier] PDF preview note on {file_path.name}: {e}")
            return ""

    def get_document_preview(self, file_path: Path) -> Tuple[str, str]:
        """Returns (document_text, short_preview_snippet) for UI display."""
        ext = file_path.suffix.lower()
        full_text = ""
        if ext in ('.docx', '.doc'):
            full_text = self.extract_docx_text(file_path)
        elif ext in ('.pptx', '.ppt'):
            full_text = self.extract_pptx_text(file_path)
        elif ext == '.pdf':
            full_text = self.extract_pdf_preview(file_path)
        elif ext in ('.txt', '.md'):
            try:
                full_text = file_path.read_text(encoding='utf-8', errors='ignore')[:3000]
            except Exception:
                pass

        snippet = full_text[:280].strip()
        if len(full_text) > 280:
            snippet += "..."
        return full_text, snippet

    def extract_session_numbers(self, text: str) -> Dict[str, Set[int]]:
        """
        Extracts structural session numbers from text.
        Excludes numbers associated with chapters, volumes, parts, editions, or pages.
        Returns mapping of category -> set of numbers, e.g. {'seminar': {4}, 'week': {2}}
        """
        results: Dict[str, Set[int]] = {
            'seminar': set(),
            'week': set(),
            'lecture': set(),
            'topic': set(),
            'tutorial': set(),
        }
        text_lower = text.lower()

        # Guard: Strip out numbers preceded by chapter, volume, part, book, edition, or page
        # e.g., "Shakespeare 2 - Words" (where 2 is vol/chapter), "Chapter 4", "Part 2", "Vol 1"
        sanitized_text = re.sub(
            r'\b(?:chapter|ch|part|pt|volume|vol|book|bk|edition|ed|page|p|pp)[\s_\-\.:]*0*\d+\b',
            ' ',
            text_lower
        )

        # Regular expressions for category + number (strict prefixes, avoiding single-letter traps)
        patterns = [
            (r'\b(?:seminar|sem)[\s_\-\.]*0*(\d{1,2})\b', 'seminar'),
            (r'\b(?:week|wk)[\s_\-\.]*0*(\d{1,2})\b', 'week'),
            (r'\b(?:lecture|lec)[\s_\-\.]*0*(\d{1,2})\b', 'lecture'),
            (r'\b(?:topic|top)[\s_\-\.]*0*(\d{1,2})\b', 'topic'),
            (r'\b(?:tutorial|tut)[\s_\-\.]*0*(\d{1,2})\b', 'tutorial'),
        ]

        for pat, cat in patterns:
            for match in re.finditer(pat, sanitized_text):
                num = int(match.group(1))
                results[cat].add(num)

        # Leading number in folder name or short title (e.g. "1-Introduction", "01. Topic", "2 - Shaped Bodies")
        # Guard: do not match book chapter numbers, page numbers, or long document text
        is_short_title = len(text.strip()) < 80 and '\n' not in text.strip()
        has_chapter_marker = bool(re.search(r'\b(?:chapter|ch|part|pt|vol|volume|book|bk|edition|ed|page|p)\b', text_lower[:60]))
        if is_short_title and not has_chapter_marker:
            leading_num_match = re.match(r'^0*(\d{1,2})[\s_\-\.]+', text_lower.strip())
            if leading_num_match:
                num = int(leading_num_match.group(1))
                # Register under all session types so it matches "Week 1", "Seminar 1", "Lecture 1"
                for cat in results:
                    results[cat].add(num)

        # Roman numeral matches: "Seminar IV", "Week II"
        roman_pat = r'\b(seminar|week|lecture|topic|tutorial)[\s_\-\.]+([ivxlc]+)\b'
        for match in re.finditer(roman_pat, sanitized_text):
            cat = match.group(1)
            rom = match.group(2)
            if rom in ROMAN_NUMERALS:
                if cat in results:
                    results[cat].add(ROMAN_NUMERALS[rom])

        return results

    def is_broader_course_document(self, filename: str, full_text: str) -> Tuple[bool, str]:
        """Checks if a document represents a broad course syllabus, guide, or specification."""
        search = f"{filename} {full_text[:500]}".lower()
        for marker in BROADER_DOC_MARKERS:
            if marker in search:
                return True, marker
        return False, ""

    def classify_file(self, file_path: Path) -> Dict[str, Any]:
        """
        Evaluates a file against the active taxonomy using Hierarchical Gated Routing:
        Stage 1: Parent Course Identification with cross-course pruning.
        Stage 2: Subfolder Resolution within Winning Course via Cross-Encoder Reranking & Active Learning.
        """
        filename = file_path.name
        full_text, snippet = self.get_document_preview(file_path)
        search_corpus = f"{filename} {full_text}".lower()

        # Check Active Learning / User Rules first
        rules = self.load_rules()
        file_rules = rules.get("file_rules", {})
        learned_stems = rules.get("learned_stems", {})

        # 1. Exact file match rule
        if filename.lower() in file_rules:
            exact_dest = file_rules[filename.lower()]
            parts = exact_dest.split("/", 1)
            course_part = parts[0]
            sub_part = parts[1] if len(parts) > 1 else None
            match_obj = {
                "course": course_part,
                "subfolder": sub_part,
                "destination": exact_dest,
                "confidence": 1.0,
                "matched_terms": ["Exact user-confirmed rule match"],
                "sub_ambiguous": False
            }
            return {
                "filename": filename,
                "path": str(file_path),
                "snippet": snippet,
                "is_auto_sort": True,
                "is_ambiguous": False,
                "ambiguity_reason": "",
                "best_match": match_obj,
                "candidates": [match_obj]
            }

        # Check compound rules (e.g. author + chapter/topic) and legacy stems
        compound_rules = rules.get("compound_rules", {})
        learned_stems = rules.get("learned_stems", {})
        all_stems = {**learned_stems, **compound_rules}
        matched_stem_dest = None
        matched_stem_key = None
        for stem_key, stem_dest in all_stems.items():
            if stem_key in filename.lower() or stem_key in search_corpus[:400]:
                matched_stem_dest = stem_dest
                matched_stem_key = stem_key
                break

        # Structural signals
        doc_sessions = self.extract_session_numbers(search_corpus)
        is_broader, broader_marker = self.is_broader_course_document(filename, full_text)

        # AI Semantic Dense Vector (Offline Embedding)
        doc_summary_text = f"{filename}. {full_text[:800]}"
        doc_vec = self._get_embedding(doc_summary_text)

        taxonomy_tree = self.taxonomy_manager.get_taxonomy_tree()
        if not taxonomy_tree:
            return {
                "filename": filename,
                "path": str(file_path),
                "snippet": snippet,
                "is_auto_sort": False,
                "is_ambiguous": True,
                "ambiguity_reason": "No courses found in taxonomy",
                "best_match": None,
                "candidates": []
            }

        # =========================================================================
        # STAGE 1: PARENT COURSE EVALUATION & GATING
        # =========================================================================
        course_scores = []
        for course in taxonomy_tree:
            course_name = course["name"]
            c_score = 0.0
            c_notes = []

            # Clean tokens for matching
            course_clean = re.sub(r'[^a-zA-Z0-9\s]', ' ', course_name).lower()
            course_tokens = [t for t in course_clean.split() if len(t) > 1 and t not in ACADEMIC_STOPWORDS]

            # 1. Filename match
            if course_clean in filename.lower():
                c_score += 0.55
                c_notes.append(f"Filename contains '{course_name}'")
            else:
                for token in course_tokens:
                    if len(token) > 2 and token in filename.lower():
                        c_score += 0.25
                        c_notes.append(f"Filename contains '{token}'")

            # 2. Aliases match
            aliases = course.get("aliases", [])
            for alias in aliases:
                alias_lower = alias.lower()
                if alias_lower in filename.lower():
                    c_score += 0.50
                    c_notes.append(f"Filename matches alias '{alias}'")
                elif alias_lower in search_corpus:
                    c_score += 0.35
                    c_notes.append(f"Content matches alias '{alias}'")

            # 3. Document text match (lexical)
            if course_clean in full_text.lower():
                c_score += 0.40
                c_notes.append(f"Document header contains '{course_name}'")
            else:
                meaningful_tokens = [t for t in course_tokens if len(t) > 2]
                if meaningful_tokens:
                    token_matches = [t for t in meaningful_tokens if t in full_text.lower()]
                    if token_matches:
                        ratio = len(token_matches) / max(len(meaningful_tokens), 1)
                        c_score += 0.35 * ratio
                        c_notes.append(f"Keywords matched ({', '.join(token_matches)})")

            # 4. Dense semantic similarity
            c_sem_score = 0.0
            if doc_vec is not None and self.semantic_classifier:
                course_desc = course_name
                if aliases:
                    course_desc += f" ({', '.join(aliases)})"
                course_vec = self._get_embedding(course_desc)
                if course_vec is not None:
                    course_sim = self.semantic_classifier.cosine_similarity(doc_vec, course_vec)
                    if course_sim >= 0.42:
                        c_sem_score = min(1.0, (course_sim - 0.38) / 0.32)
                        if course_sim >= 0.52:
                            c_notes.append(f"AI semantic match ({round(course_sim * 100)}%)")

            # Blend lexical + semantic
            if c_score > 0 and c_sem_score > 0:
                combined_c_score = max(c_score, (c_score * 0.55) + (c_sem_score * 0.45))
            elif c_sem_score > 0:
                combined_c_score = c_sem_score * 0.70
            else:
                combined_c_score = c_score

            # 5. Learned stem bonus
            if matched_stem_dest and matched_stem_dest.startswith(course_name):
                combined_c_score += 0.50
                c_notes.append(f"Learned rule for '{matched_stem_key}'")

            course_scores.append({
                "course": course,
                "course_name": course_name,
                "score": combined_c_score,
                "notes": c_notes
            })

        course_scores.sort(key=lambda x: x["score"], reverse=True)

        # Hierarchical Gating: Determine which courses proceed to subfolder evaluation
        top_course_score = course_scores[0]["score"] if course_scores else 0.0
        second_course_score = course_scores[1]["score"] if len(course_scores) > 1 else 0.0

        # If top course has clear dominance, PRUNE all other courses to prevent leakage!
        active_course_nodes = []
        if top_course_score >= 0.40 and (top_course_score - second_course_score >= 0.14 or second_course_score < 0.25):
            active_course_nodes = [course_scores[0]]
        else:
            active_course_nodes = [c for c in course_scores if c["score"] >= 0.20][:2]
            if not active_course_nodes and course_scores:
                active_course_nodes = [course_scores[0]]

        # =========================================================================
        # STAGE 2: SUBFOLDER RESOLUTION (ISOLATED TO ACTIVE COURSES)
        # =========================================================================
        candidates = []

        for c_entry in active_course_nodes:
            course = c_entry["course"]
            course_name = c_entry["course_name"]
            course_score = c_entry["score"]
            course_matched_terms = list(c_entry["notes"])

            best_subfolder = None
            best_sub_score = 0.0
            best_sub_notes = []
            sub_candidates = []

            for sub in course.get("subfolders", []):
                sub_name = sub["name"]
                sub_score = 0.0
                current_sub_notes = []
                sub_sessions = self.extract_session_numbers(sub_name)

                # A. Numerical Session Matching (with Chapter Guard)
                has_number_match = False
                has_number_clash = False

                all_doc_sessions = (
                    doc_sessions.get('seminar', set()) |
                    doc_sessions.get('week', set()) |
                    doc_sessions.get('lecture', set()) |
                    doc_sessions.get('topic', set()) |
                    doc_sessions.get('tutorial', set())
                )
                all_sub_sessions = (
                    sub_sessions.get('seminar', set()) |
                    sub_sessions.get('week', set()) |
                    sub_sessions.get('lecture', set()) |
                    sub_sessions.get('topic', set()) |
                    sub_sessions.get('tutorial', set())
                )

                if all_sub_sessions and all_doc_sessions:
                    overlap = all_sub_sessions.intersection(all_doc_sessions)
                    if overlap:
                        has_number_match = True
                        matched_num = list(overlap)[0]
                        sub_score += 0.75
                        current_sub_notes.append(f"Session {matched_num} exact match")
                    else:
                        has_number_clash = True
                        sub_score -= 1.0

                if has_number_clash and not has_number_match:
                    continue

                # B. Multi-word Phrase Recognition
                sub_phrases, sub_tokens = extract_subfolder_phrases_and_topics(sub_name)
                for phrase in sub_phrases:
                    if phrase in filename.lower() or phrase in search_corpus[:400]:
                        sub_score += 0.85
                        current_sub_notes.append(f"Title/primary phrase: '{phrase}'")
                    elif phrase in search_corpus:
                        occ = search_corpus.count(phrase)
                        if occ >= 2:
                            freq_bonus = min(0.35, (occ - 2) * 0.05)
                            sub_score += 0.65 + freq_bonus
                            current_sub_notes.append(f"Recurring phrase: '{phrase}' ({occ}x)")
                        else:
                            sub_score += 0.25
                            current_sub_notes.append(f"Passing citation: '{phrase}'")

                # C. Topic Unigrams
                if sub_tokens:
                    topic_hits = [t for t in sub_tokens if t in search_corpus]
                    if topic_hits:
                        ratio = len(topic_hits) / max(len(sub_tokens), 1)
                        sub_score += 0.45 * ratio
                        current_sub_notes.append(f"Topic keywords ({', '.join(topic_hits)})")

                # D. Few-Shot Exemplar Matching
                exemplar_files = sub.get("files", [])
                if exemplar_files:
                    exemplar_tokens = set()
                    for ef in exemplar_files:
                        raw_name = Path(ef.get("name", "")).stem
                        ef_clean = re.sub(r'[^a-zA-Z0-9\s]', ' ', raw_name).lower()
                        for w in ef_clean.split():
                            if len(w) > 2 and w not in ACADEMIC_STOPWORDS:
                                exemplar_tokens.add(w)
                    if exemplar_tokens:
                        ef_hits = [w for w in exemplar_tokens if w in search_corpus]
                        if ef_hits:
                            ef_ratio = min(len(ef_hits) / max(len(exemplar_tokens), 1), 1.0)
                            sub_score += 0.35 * ef_ratio
                            current_sub_notes.append(f"Matches folder files ({', '.join(ef_hits[:3])})")

                # E. Subfolder Segment in Filename
                for seg in re.split(r'[\-_:/|]+', sub_name):
                    seg_clean = re.sub(r'[^a-zA-Z0-9\s]', ' ', seg).strip().lower()
                    if len(seg_clean) > 3 and seg_clean not in ACADEMIC_STOPWORDS:
                        if re.match(r'^(?:sem|seminar|week|wk|lecture|lec|topic|tutorial)?\s*0*\d+$', seg_clean):
                            continue
                        if seg_clean in filename.lower():
                            sub_score += 0.50
                            current_sub_notes.append(f"Filename contains '{seg.strip()}'")
                            break

                # F. Dense Semantic Subfolder Embedding
                if doc_vec is not None and self.semantic_classifier:
                    clean_sub_topic = re.sub(
                        r'^(?:sem|seminar|week|wk|lecture|lec|topic|tutorial)?\s*0*\d+[\s_\-\.:]*',
                        '',
                        sub_name,
                        flags=re.I
                    ).strip()
                    phrase_desc = ", ".join(sub_phrases) if sub_phrases else clean_sub_topic
                    sub_desc = f"{clean_sub_topic}. {phrase_desc}. Topics for {sub_name}."
                    sub_vec = self._get_embedding(sub_desc)
                    if sub_vec is not None:
                        sub_sim = self.semantic_classifier.cosine_similarity(doc_vec, sub_vec)
                        if sub_sim >= 0.45:
                            sub_sem_boost = min(0.60, (sub_sim - 0.40) * 1.5)
                            sub_score += sub_sem_boost
                            if sub_sim >= 0.55:
                                current_sub_notes.append(f"AI topic similarity ({round(sub_sim * 100)}%)")

                # G. Active Learning Learned Rule Match for Subfolder
                if matched_stem_dest == f"{course_name}/{sub_name}":
                    sub_score += 0.85
                    current_sub_notes.append(f"Learned rule match: '{matched_stem_key}'")

                if sub_score > 0:
                    sub_candidates.append({
                        "subfolder": sub_name,
                        "score": sub_score,
                        "notes": current_sub_notes
                    })

            # H. Cross-Encoder Joint Reranking on Top Subfolder Candidates
            if len(sub_candidates) >= 2 and self.semantic_classifier and hasattr(self.semantic_classifier, 'rerank'):
                top_sub_list = sorted(sub_candidates, key=lambda s: s["score"], reverse=True)[:4]
                sub_query_candidates = [f"{course_name} {s['subfolder']}" for s in top_sub_list]
                doc_query = f"{filename}. {snippet[:350]}"
                rerank_scores = self.semantic_classifier.rerank(doc_query, sub_query_candidates)
                if rerank_scores and any(s != 0.0 for s in rerank_scores):
                    best_re_idx = int(np.argmax(rerank_scores))
                    best_re_score = rerank_scores[best_re_idx]
                    sorted_re = sorted(rerank_scores, reverse=True)
                    re_margin = sorted_re[0] - sorted_re[1] if len(sorted_re) > 1 else 0.0
                    if best_re_score > -6.0 and re_margin >= 1.5:
                        top_sub_list[best_re_idx]["score"] += 0.40
                        top_sub_list[best_re_idx]["notes"].append(f"Neural rerank leader (margin {round(re_margin, 1)})")

            sub_candidates.sort(key=lambda s: s["score"], reverse=True)
            if sub_candidates:
                best_subfolder = sub_candidates[0]["subfolder"]
                best_sub_score = sub_candidates[0]["score"]
                best_sub_notes = sub_candidates[0]["notes"]

            # Determine Target Destination: Broader vs Specific
            matched_terms = list(course_matched_terms)
            if is_broader:
                destination = course_name
                matched_terms.append(f"General course document: '{broader_marker}'")
                final_confidence = min(course_score + 0.20, 0.99)
            elif best_subfolder and best_sub_score >= 0.35:
                destination = f"{course_name}/{best_subfolder}"
                matched_terms.extend(best_sub_notes)
                final_confidence = min(course_score + (best_sub_score * 0.40), 0.99)
            else:
                destination = course_name
                matched_terms.append("General course materials")
                final_confidence = min(course_score, 0.99)

            # Check for close competition between subfolders within this course
            sub_ambiguous = False
            if not is_broader and destination != course_name and len(sub_candidates) >= 2:
                s_diff = sub_candidates[0]["score"] - sub_candidates[1]["score"]
                has_definitive = any(
                    "exact" in n.lower() or "phrase" in n.lower() or "rule" in n.lower() or "rerank" in n.lower()
                    for n in sub_candidates[0]["notes"]
                )
                if s_diff < 0.08 and not has_definitive and final_confidence < 0.85:
                    sub_ambiguous = True

            candidates.append({
                "course": course_name,
                "subfolder": best_subfolder if destination != course_name else None,
                "destination": destination,
                "confidence": round(final_confidence, 2),
                "matched_terms": matched_terms,
                "sub_ambiguous": sub_ambiguous
            })

        # Sort candidates descending by confidence
        candidates.sort(key=lambda c: c["confidence"], reverse=True)

        best_match = candidates[0] if candidates else None
        is_ambiguous = False
        ambiguity_reason = ""

        if best_match and best_match.get("sub_ambiguous"):
            is_ambiguous = True
            ambiguity_reason = "Close thematic call between multiple seminars"
        elif len(candidates) >= 2:
            diff = candidates[0]["confidence"] - candidates[1]["confidence"]
            has_definitive = any(
                "exact" in t.lower() or "phrase" in t.lower() or "rule" in t.lower() or "rerank" in t.lower()
                for t in candidates[0]["matched_terms"]
            )
            if diff < 0.08 and candidates[0]["confidence"] < 0.85 and not has_definitive:
                is_ambiguous = True
                ambiguity_reason = f"Close match between '{candidates[0]['destination']}' and '{candidates[1]['destination']}'"

        is_auto_sort = (best_match is not None and best_match["confidence"] >= self.min_confidence and not is_ambiguous)

        return {
            "filename": filename,
            "path": str(file_path),
            "snippet": snippet,
            "is_auto_sort": is_auto_sort,
            "is_ambiguous": is_ambiguous,
            "ambiguity_reason": ambiguity_reason,
            "best_match": best_match,
            "candidates": candidates[:4]
        }
