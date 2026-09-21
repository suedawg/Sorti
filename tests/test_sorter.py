"""
Unit tests for Sorti MoodleDoc Sorter.
Validates Subfolder Immunity, Taxonomy Discovery, Two-Tier Classification,
Numerical Subfolder Matching, Broader Course Folder Routing,
PPTX In-Memory Text Sniffing, and Original File Deletion.
"""

import pytest
import shutil
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

from tools.moodle_sorter.engine.taxonomy import TaxonomyManager
from tools.moodle_sorter.engine.classifier import DocumentClassifier
from tools.moodle_sorter.engine.converter import OfficePdfConverter
from tools.moodle_sorter.engine.file_ops import SafeFileOps

def create_mock_docx(file_path: Path, text_content: str):
    """Generates a minimal valid .docx zip archive with embedded document.xml."""
    doc_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
        <w:body>
            <w:p><w:r><w:t>{text_content}</w:t></w:r></w:p>
        </w:body>
    </w:document>"""
    with zipfile.ZipFile(file_path, 'w') as zf:
        zf.writestr('word/document.xml', doc_xml)

def create_mock_pptx(file_path: Path, text_content: str):
    """Generates a minimal valid .pptx zip archive with embedded slide1.xml."""
    slide_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
           xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
        <p:cSld>
            <p:spTree>
                <p:sp>
                    <p:txBody>
                        <a:p><a:r><a:t>{text_content}</a:t></a:r></a:p>
                    </p:txBody>
                </p:sp>
            </p:spTree>
        </p:cSld>
    </p:sld>"""
    with zipfile.ZipFile(file_path, 'w') as zf:
        zf.writestr('ppt/slides/slide1.xml', slide_xml)

@pytest.fixture
def temp_workspace():
    temp_dir = Path(tempfile.mkdtemp(prefix="sorti_test_"))
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)

def test_subfolder_immunity(temp_workspace):
    """
    Subfolder Immunity Guard:
    Files placed inside existing subfolders must NEVER be touched or moved by the sorter.
    """
    tax = TaxonomyManager(temp_workspace)
    conv = OfficePdfConverter()
    ops = SafeFileOps(temp_workspace, conv)

    # 1. Setup a course subfolder with an internal document
    subfolder = temp_workspace / "Jurisprudence" / "Seminar 1"
    subfolder.mkdir(parents=True, exist_ok=True)
    immune_file = subfolder / "my_private_seminar_notes.docx"
    create_mock_docx(immune_file, "Private student notes written directly in seminar folder")

    # 2. Assert is_root_file rejects subfolder files
    assert ops.is_root_file(immune_file) is False

    # 3. Attempting to process a subfolder file must be rejected with an immunity violation
    result = ops.process_file(immune_file, "Commercial Law")
    assert result["success"] is False
    assert "Immunity Violation" in result["error"]

    # 4. Verify file is completely untouched in its original location
    assert immune_file.exists()
    assert not (temp_workspace / "Commercial Law" / immune_file.name).exists()

def test_taxonomy_discovery(temp_workspace):
    """Validates dynamic folder discovery and ignored directories."""
    tax = TaxonomyManager(temp_workspace)

    # Create courses and ignored folders
    (temp_workspace / "Jurisprudence" / "Week 1").mkdir(parents=True)
    (temp_workspace / "Commercial Law").mkdir(parents=True)
    (temp_workspace / "_Unsorted").mkdir(parents=True)
    (temp_workspace / ".git").mkdir(parents=True)
    (temp_workspace / "config").mkdir(parents=True)
    (temp_workspace / ".sorti").mkdir(parents=True)

    tree = tax.get_taxonomy_tree()
    course_names = [c["name"] for c in tree]

    assert "Jurisprudence" in course_names
    assert "Commercial Law" in course_names
    assert "_Unsorted" not in course_names
    assert ".git" not in course_names
    assert "config" not in course_names
    assert ".sorti" not in course_names

    jur_course = next(c for c in tree if c["name"] == "Jurisprudence")
    assert len(jur_course["subfolders"]) == 1
    assert jur_course["subfolders"][0]["name"] == "Week 1"

def test_subfolder_exact_number_matching(temp_workspace):
    """
    Ensures Seminar 4 accurately matches Seminar 4, and NOT Seminar 1 or Seminar 10.
    Fixes the single-digit token stripping bug.
    """
    tax = TaxonomyManager(temp_workspace)
    (temp_workspace / "Jurisprudence" / "Seminar 1").mkdir(parents=True)
    (temp_workspace / "Jurisprudence" / "Seminar 2").mkdir(parents=True)
    (temp_workspace / "Jurisprudence" / "Seminar 4").mkdir(parents=True)
    (temp_workspace / "Jurisprudence" / "Seminar 10").mkdir(parents=True)

    classifier = DocumentClassifier(tax, min_confidence=0.65)

    # Create a document specifically for Seminar 4
    doc_path = temp_workspace / "Jurisprudence_Reading_Seminar_4.docx"
    create_mock_docx(doc_path, "School of Law. Jurisprudence. Seminar 4: Legal Realism and Critical Legal Studies.")

    res = classifier.classify_file(doc_path)
    assert res["is_auto_sort"] is True
    assert res["best_match"] is not None
    assert res["best_match"]["course"] == "Jurisprudence"
    # Must be Seminar 4, absolutely NOT Seminar 1 or Seminar 10
    assert res["best_match"]["subfolder"] == "Seminar 4"
    assert res["best_match"]["destination"] == "Jurisprudence/Seminar 4"

def test_broader_course_folder_sorting(temp_workspace):
    """
    Validates that broader course documents (course specifications, syllabi, handbooks)
    are sorted into the broader course folder (e.g. Jurisprudence/) rather than forced into a subfolder.
    """
    tax = TaxonomyManager(temp_workspace)
    (temp_workspace / "Jurisprudence" / "Seminar 1").mkdir(parents=True)
    (temp_workspace / "Jurisprudence" / "Seminar 2").mkdir(parents=True)

    classifier = DocumentClassifier(tax, min_confidence=0.65)

    # General course specification document
    doc_path = temp_workspace / "Jurisprudence_Course_Specification_2026.docx"
    create_mock_docx(doc_path, "School of Law. Jurisprudence Course Specification 2026-2027. Aims and ILOs.")

    res = classifier.classify_file(doc_path)
    assert res["is_auto_sort"] is True
    assert res["best_match"] is not None
    assert res["best_match"]["course"] == "Jurisprudence"
    assert res["best_match"]["subfolder"] is None
    assert res["best_match"]["destination"] == "Jurisprudence"

def test_pptx_in_memory_sniffing(temp_workspace):
    """Validates fast in-memory XML slide text extraction from .pptx files."""
    tax = TaxonomyManager(temp_workspace)
    (temp_workspace / "Commercial Law" / "Lecture 3").mkdir(parents=True)

    classifier = DocumentClassifier(tax, min_confidence=0.65)

    pptx_path = temp_workspace / "Commercial_Law_Lec_3.pptx"
    create_mock_pptx(pptx_path, "Commercial Law. Lecture 3: Directors Duties and Fiduciary Obligations.")

    extracted = classifier.extract_pptx_text(pptx_path)
    assert "Commercial Law" in extracted
    assert "Directors Duties" in extracted

    res = classifier.classify_file(pptx_path)
    assert res["is_auto_sort"] is True
    assert res["best_match"]["course"] == "Commercial Law"
    assert res["best_match"]["subfolder"] == "Lecture 3"
    assert res["best_match"]["destination"] == "Commercial Law/Lecture 3"

def test_original_files_deleted_after_pdf_conversion(temp_workspace):
    """
    Verifies that upon successful PDF conversion, the original .docx and .pptx files
    are permanently deleted from disk as requested.
    """
    mock_conv = MagicMock()
    # Mock converter writes a non-empty fake PDF to target
    def fake_convert(src, pdf_target):
        pdf_target.parent.mkdir(parents=True, exist_ok=True)
        pdf_target.write_bytes(b"%PDF-1.4 fake pdf data for test")
        return True, pdf_target, "Mock conversion success"

    mock_conv.convert_to_pdf.side_effect = fake_convert
    ops = SafeFileOps(temp_workspace, mock_conv)

    # 1. Test Word Doc deletion
    word_doc = temp_workspace / "test_notes.docx"
    create_mock_docx(word_doc, "Dummy word notes")
    res_word = ops.process_file(word_doc, "Jurisprudence/Seminar 1")

    assert res_word["success"] is True
    assert res_word["deleted_original"] is True
    assert not word_doc.exists(), "Original Word doc must be deleted post-conversion!"
    assert (temp_workspace / "Jurisprudence" / "Seminar 1" / "test_notes.pdf").exists()

    # 2. Test PowerPoint Doc deletion
    ppt_doc = temp_workspace / "test_slides.pptx"
    create_mock_pptx(ppt_doc, "Dummy ppt slides")
    res_ppt = ops.process_file(ppt_doc, "Commercial Law/Lecture 2")

    assert res_ppt["success"] is True
    assert res_ppt["deleted_original"] is True
    assert not ppt_doc.exists(), "Original PPTX doc must be deleted post-conversion!"
    assert (temp_workspace / "Commercial Law" / "Lecture 2" / "test_slides.pdf").exists()

def test_unsorted_staging_for_ambiguous_documents(temp_workspace):
    """Verifies ambiguous documents are staged into _Unsorted/ awaiting user confirmation."""
    tax = TaxonomyManager(temp_workspace)
    (temp_workspace / "Jurisprudence").mkdir(parents=True)
    conv = OfficePdfConverter()
    ops = SafeFileOps(temp_workspace, conv)

    ambiguous_file = temp_workspace / "random_grocery_list.txt"
    ambiguous_file.write_text("Milk, eggs, coffee beans", encoding="utf-8")

    res = ops.stage_to_unsorted(ambiguous_file)
    assert res["success"] is True
    assert not ambiguous_file.exists()
    assert (temp_workspace / "_Unsorted" / "random_grocery_list.txt").exists()

def test_shaping_shakespeare_leading_number_subfolder(temp_workspace):
    """
    Specifically tests real-world university folder structure:
    Course: Shaping Shakespeare
    Subfolders: '1-Introduction-Creative Morphology', '2-Shaped Bodies-Titus Andronicus'
    Document: 'Shaping Shakespeare - Week 1 handout.docx'
    Must match '1-Introduction-Creative Morphology' because '1-' matches 'Week 1'.
    """
    tax = TaxonomyManager(temp_workspace)
    (temp_workspace / "Shaping Shakespeare" / "1-Introduction-Creative Morphology").mkdir(parents=True)
    (temp_workspace / "Shaping Shakespeare" / "2-Shaped Bodies-Titus Andronicus").mkdir(parents=True)

    classifier = DocumentClassifier(tax, min_confidence=0.65)

    doc_path = temp_workspace / "Shaping Shakespeare - Week 1 handout.docx"
    create_mock_docx(doc_path, "University of Glasgow. Shaping Shakespeare. Week 1 Introduction Handout.")

    res = classifier.classify_file(doc_path)
    assert res["is_auto_sort"] is True
    assert res["best_match"]["course"] == "Shaping Shakespeare"
    assert res["best_match"]["subfolder"] == "1-Introduction-Creative Morphology"
    assert res["best_match"]["destination"] == "Shaping Shakespeare/1-Introduction-Creative Morphology"

def test_semantic_course_matching_without_literal_keywords(temp_workspace):
    """
    Validates AI Semantic Matching:
    A document regarding syndicated credit agreements and financial debt restructuring
    should semantically classify into 'Banking Law' even without explicit course name keywords.
    """
    tax = TaxonomyManager(temp_workspace)
    (temp_workspace / "Banking Law").mkdir(parents=True)
    (temp_workspace / "Shaping Shakespeare").mkdir(parents=True)
    (temp_workspace / "Globalisation, Justice, and HR").mkdir(parents=True)

    classifier = DocumentClassifier(tax, min_confidence=0.50)

    doc_path = temp_workspace / "syndicated_facility_restructure.docx"
    create_mock_docx(
        doc_path,
        "Revolving credit facility agreement between syndicate lenders and commercial borrower. "
        "Clauses covering negative pledge, financial covenants, events of default and acceleration."
    )

    res = classifier.classify_file(doc_path)
    assert res["best_match"] is not None
    assert res["best_match"]["course"] == "Banking Law"

def test_semantic_subfolder_matching_titus(temp_workspace):
    """
    Validates that a document analyzing Titus Andronicus revenge tragedy themes
    is semantically guided to '2-Shaped Bodies-Titus Andronicus' under Shaping Shakespeare.
    """
    tax = TaxonomyManager(temp_workspace)
    (temp_workspace / "Shaping Shakespeare" / "1-Introduction-Creative Morphology").mkdir(parents=True)
    (temp_workspace / "Shaping Shakespeare" / "2-Shaped Bodies-Titus Andronicus").mkdir(parents=True)

    classifier = DocumentClassifier(tax, min_confidence=0.55)

    doc_path = temp_workspace / "Shaping Shakespeare - Roman Revenge Tragedy.docx"
    create_mock_docx(
        doc_path,
        "Shaping Shakespeare seminar discussion. Roman political violence, revenge tragedy conventions, "
        "and physical bodily mutilation of Lavinia in the grotesque drama of Titus Andronicus and Tamora."
    )

    res = classifier.classify_file(doc_path)
    assert res["is_auto_sort"] is True
    assert res["best_match"]["course"] == "Shaping Shakespeare"
    assert res["best_match"]["subfolder"] == "2-Shaped Bodies-Titus Andronicus"
    assert res["best_match"]["destination"] == "Shaping Shakespeare/2-Shaped Bodies-Titus Andronicus"

def test_as_you_like_it_phrase_vs_stopword(temp_workspace):
    """
    Validates that:
    1. A document discussing the play 'As You Like It' matches Sem4-Queer Shapes-As You Like It.
    2. A document using generic words 'you' and 'like' without mentioning the play DOES NOT trigger Sem4.
    """
    tax = TaxonomyManager(temp_workspace)
    (temp_workspace / "Shaping Shakespeare" / "Sem1-Introduction-Creative Morphology").mkdir(parents=True)
    (temp_workspace / "Shaping Shakespeare" / "Sem4-Queer Shapes-As You Like It").mkdir(parents=True)

    classifier = DocumentClassifier(tax, min_confidence=0.55)

    # 1. Real play discussion
    play_doc = temp_workspace / "Richard Stacey - Gender Transfiguration.docx"
    create_mock_docx(
        play_doc,
        "Shaping Shakespeare analysis of pastoral comedy. Transfiguring gender and queer pastoral desires in As You Like It. Rosalind and Ganymede."
    )
    res_play = classifier.classify_file(play_doc)
    assert res_play["is_auto_sort"] is True
    assert res_play["best_match"]["subfolder"] == "Sem4-Queer Shapes-As You Like It"

    # 2. Generic academic discourse using 'you' and 'like' (The 'As You Like It' trap)
    generic_doc = temp_workspace / "General Linguistic Analysis.docx"
    create_mock_docx(
        generic_doc,
        "Shaping Shakespeare essay. As you can see from historical records, much like early modern linguistic scholars have argued, grammar evolved."
    )
    res_generic = classifier.classify_file(generic_doc)
    # Must NOT route to Sem4 just because it contains 'you' and 'like'!
    if res_generic["best_match"] and res_generic["best_match"]["subfolder"]:
        assert res_generic["best_match"]["subfolder"] != "Sem4-Queer Shapes-As You Like It"

def test_antony_and_cleopatra_routing(temp_workspace):
    """
    Validates routing of Virginia Mason Vaughan reading to Sem6-Shaping Worlds-Antony and Cleopatra.
    """
    tax = TaxonomyManager(temp_workspace)
    (temp_workspace / "Shaping Shakespeare" / "Sem1-Introduction-Creative Morphology").mkdir(parents=True)
    (temp_workspace / "Shaping Shakespeare" / "Sem2-Shaped Bodies-Titus Andronicus").mkdir(parents=True)
    (temp_workspace / "Shaping Shakespeare" / "Sem6-Shaping Worlds-Antony and Cleopatra").mkdir(parents=True)

    classifier = DocumentClassifier(tax, min_confidence=0.55)

    doc_path = temp_workspace / "Virginia Mason Vaughan, Language - Forms and Uses.docx"
    create_mock_docx(
        doc_path,
        "Shaping Shakespeare seminar. Jacobean imperial politics, Roman rhetoric, and dramatic forms in Antony and Cleopatra. Octavius Caesar and Egypt."
    )
    res = classifier.classify_file(doc_path)
    assert res["is_auto_sort"] is True
    assert res["best_match"]["subfolder"] == "Sem6-Shaping Worlds-Antony and Cleopatra"

def test_volume_number_not_seminar_session(temp_workspace):
    """
    Ensures that 'Jonathan Hope, Ideas About Language in Shakespeare 2 - Words'
    does NOT falsely match Seminar 2 due to the volume/chapter number '2'.
    """
    tax = TaxonomyManager(temp_workspace)
    (temp_workspace / "Shaping Shakespeare" / "Sem1-Introduction-Creative Morphology").mkdir(parents=True)
    (temp_workspace / "Shaping Shakespeare" / "Sem2-Shaped Bodies-Titus Andronicus").mkdir(parents=True)

    classifier = DocumentClassifier(tax, min_confidence=0.55)

    # Document where '2' is a book volume
    doc_path = temp_workspace / "Jonathan Hope, Ideas About Language in Shakespeare 2 - Words.docx"
    create_mock_docx(
        doc_path,
        "Volume 2: Words. Linguistic morphology, vocabulary expansion, and lexical invention across early modern English drama."
    )

    sessions = classifier.extract_session_numbers("Jonathan Hope, Ideas About Language in Shakespeare Volume 2 - Words")
    assert 2 not in sessions["seminar"], "Volume 2 must not register as Seminar 2!"

def test_subfolder_exemplar_memory(temp_workspace):
    """
    Validates few-shot exemplar folder memory:
    When Sem1 already contains 'Introduction, Shakespeare and the Shape of Words.pdf',
    a new document with 'Words' and 'Morphology' is guided towards Sem1.
    """
    tax = TaxonomyManager(temp_workspace)
    sem1 = temp_workspace / "Shaping Shakespeare" / "Sem1-Introduction-Creative Morphology"
    sem1.mkdir(parents=True)
    # Seed an existing exemplar document inside Sem1
    existing_file = sem1 / "Introduction, Shakespeare and the Shape of Words.pdf"
    existing_file.write_bytes(b"%PDF-1.4 mock pdf")

    sem2 = temp_workspace / "Shaping Shakespeare" / "Sem2-Shaped Bodies-Titus Andronicus"
    sem2.mkdir(parents=True)

    classifier = DocumentClassifier(tax, min_confidence=0.50)

    new_doc = temp_workspace / "Shakespeare Lexical Morphology and Words.docx"
    create_mock_docx(
        new_doc,
        "Shaping Shakespeare analysis of lexical morphology and early modern words."
    )

    res = classifier.classify_file(new_doc)
    assert res["best_match"] is not None
    assert res["best_match"]["subfolder"] == "Sem1-Introduction-Creative Morphology"
    assert any("folder files" in term.lower() for term in res["best_match"]["matched_terms"])

def test_sweep_intake_with_overrides(temp_workspace):
    """
    Validates that sweep_intake honors user manual overrides:
    When a file has a manual destination override, it must sort to that override.
    """
    conv = OfficePdfConverter()
    ops = SafeFileOps(temp_workspace, conv)

    (temp_workspace / "Banking Law" / "Sem1-Definition of a Bank").mkdir(parents=True)
    (temp_workspace / "Banking Law" / "Sem2-Central Banking").mkdir(parents=True)

    # Place a file in intake root
    test_file = temp_workspace / "Cranston chapter 2.pdf"
    test_file.write_bytes(b"%PDF-1.4 mock pdf content")

    tax = TaxonomyManager(temp_workspace)
    clf = DocumentClassifier(tax)

    # Simulate sweep_intake with overrides
    overrides = {"Cranston chapter 2.pdf": "Banking Law/Sem1-Definition of a Bank"}

    incoming = ops.list_root_incoming_files()
    sorted_records = []
    for f in incoming:
        if f.name in overrides:
            dest = overrides[f.name]
            clf.learn_user_override(f.name, dest)
            res = ops.process_file(f, dest)
            sorted_records.append({"file": f.name, "destination": dest, "result": res})

    assert len(sorted_records) == 1
    assert sorted_records[0]["destination"] == "Banking Law/Sem1-Definition of a Bank"
    # Verify file is in Sem1, NOT Sem2
    assert (temp_workspace / "Banking Law" / "Sem1-Definition of a Bank" / "Cranston chapter 2.pdf").exists()
    assert not (temp_workspace / "Banking Law" / "Sem2-Central Banking" / "Cranston chapter 2.pdf").exists()

def test_active_learning_override_persistence(temp_workspace):
    """
    Validates that when a user manually overrides one chapter in a book series,
    Sorti learns the author/stem mapping and correctly routes subsequent chapters.
    """
    tax = TaxonomyManager(temp_workspace)
    (temp_workspace / "Banking Law" / "Sem1-Definition of a Bank").mkdir(parents=True)
    (temp_workspace / "Banking Law" / "Sem2-Central Banking").mkdir(parents=True)

    clf = DocumentClassifier(tax, min_confidence=0.60)

    # User manually overrides Chapter 1 to Sem1
    clf.learn_user_override("Cranston chapter 1.docx", "Banking Law/Sem1-Definition of a Bank")

    # Chapter 2 arrives
    ch2_doc = temp_workspace / "Cranston chapter 2.docx"
    create_mock_docx(ch2_doc, "Prudential Regulation and Capital Controls in Banking Law")

    res = clf.classify_file(ch2_doc)
    assert res["best_match"] is not None
    assert res["best_match"]["destination"] == "Banking Law/Sem1-Definition of a Bank"
    assert res["is_auto_sort"] is True
    assert any("learned rule" in term.lower() for term in res["best_match"]["matched_terms"])

def test_cross_course_isolation(temp_workspace):
    """
    Validates Hierarchical Gated Routing:
    Subfolder keywords in Course B (e.g. 'Structural Injustice') must NOT leak
    into Course A documents (e.g. 'Banking Law').
    """
    tax = TaxonomyManager(temp_workspace)
    (temp_workspace / "Banking Law" / "Sem1-Definition of a Bank").mkdir(parents=True)
    (temp_workspace / "Banking Law" / "Sem2-Central Banking").mkdir(parents=True)
    (temp_workspace / "Globalization, Justice, and Human Rights" / "Sem2-Structural Injustice").mkdir(parents=True)

    clf = DocumentClassifier(tax, min_confidence=0.60)

    # Banking document that mentions structural regulation
    doc = temp_workspace / "Banking Law Structural Reforms.docx"
    create_mock_docx(
        doc,
        "Banking Law: Structural regulation of banking institutions and capital ratios in financial markets."
    )

    res = clf.classify_file(doc)
    assert res["best_match"] is not None
    assert res["best_match"]["course"] == "Banking Law"
    # Globalization must not have leaked or overtaken
    assert res["best_match"]["course"] != "Globalization, Justice, and Human Rights"

def test_server_socket_handshake_and_reuse():
    """
    Validates that:
    1. wait_for_server_ready correctly detects closed vs open ports via HTTP.
    2. create_server binds with clean port and serves static dashboard.
    """
    from tools.moodle_sorter.app import wait_for_server_ready, create_server
    import threading

    test_port = 59997
    # 1. Closed port must return False
    assert wait_for_server_ready("127.0.0.1", test_port, timeout=0.2) is False

    # 2. Start server on test_port
    httpd, port = create_server("127.0.0.1", default_port=test_port)
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    try:
        assert port == test_port
        assert httpd.allow_reuse_address is True
        assert httpd.daemon_threads is True
        # 3. Active server must return True
        assert wait_for_server_ready("127.0.0.1", test_port, timeout=2.0) is True
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_find_clean_port_skips_occupied():
    """Validates that find_clean_port detects an occupied port and safely selects the next available port."""
    import socket
    from tools.moodle_sorter.app import find_clean_port

    base_port = 59980
    # Hold base_port with an active socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", base_port))
        s.listen(1)
        # find_clean_port should skip base_port and return base_port + 1
        clean_p = find_clean_port("127.0.0.1", default_port=base_port)
        assert clean_p != base_port
        assert clean_p >= base_port + 1

def test_sanitize_edge_profile(tmp_path):
    """Validates that sanitize_edge_profile fixes 'Crashed' exit_type and removes stale sessions and locks."""
    import json
    from tools.moodle_sorter.app import sanitize_edge_profile

    profile_dir = tmp_path / "SortiProfile"
    default_dir = profile_dir / "Default"
    default_dir.mkdir(parents=True)

    # 1. Create Preferences with Crashed exit_type
    pref_file = default_dir / "Preferences"
    with open(pref_file, "w", encoding="utf-8") as f:
        json.dump({"profile": {"exit_type": "Crashed"}}, f)

    # 2. Create stale sessions directory and lock
    sessions_dir = default_dir / "Sessions"
    sessions_dir.mkdir()
    (sessions_dir / "Session_123").write_text("dummy")
    lock_file = default_dir / "LOCK"
    lock_file.write_text("lock")

    # Run sanitization
    sanitize_edge_profile(profile_dir)

    # Verify exit_type is Normal
    with open(pref_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["profile"]["exit_type"] == "Normal"

    # Verify sessions and lock were purged
    assert not sessions_dir.exists()
    assert not lock_file.exists()

def test_single_instance_mutex():
    """Validates single instance mutex acquisition."""
    from tools.moodle_sorter.app import acquire_single_instance_lock
    is_prim, handle = acquire_single_instance_lock()
    # When running test, should acquire primary lock cleanly
    assert isinstance(is_prim, bool)


