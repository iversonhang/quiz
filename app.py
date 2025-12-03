import streamlit as st
import google.generativeai as genai
import json
import sqlite3
import time
import tempfile
import os

# --- CONFIGURATION ---
st.set_page_config(page_title="Pro Quiz Portal (OCR Version)", page_icon="👁️", layout="wide")

# --- DATABASE FUNCTIONS (Same as before) ---
def init_db():
    conn = sqlite3.connect('quiz.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT,
            question TEXT,
            options TEXT,
            answer TEXT,
            explanation TEXT,
            source_file TEXT
        )
    ''')
    conn.commit()
    conn.close()

def save_questions_to_db(questions, subject, filename):
    conn = sqlite3.connect('quiz.db')
    c = conn.cursor()
    count = 0
    for q in questions:
        if 'question' in q and 'options' in q and 'answer' in q:
            c.execute('''
                INSERT INTO questions (subject, question, options, answer, explanation, source_file)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (subject, q['question'], json.dumps(q['options']), q['answer'], q.get('explanation', ''), filename))
            count += 1
    conn.commit()
    conn.close()
    return count

def get_random_quiz(subject, limit=20):
    conn = sqlite3.connect('quiz.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM questions WHERE subject = ? ORDER BY RANDOM() LIMIT ?', (subject, limit))
    rows = c.fetchall()
    conn.close()
    return [{
        'question': row['question'],
        'options': json.loads(row['options']),
        'answer': row['answer'],
        'explanation': row['explanation']
    } for row in rows]

def get_db_stats():
    conn = sqlite3.connect('quiz.db')
    c = conn.cursor()
    c.execute("SELECT subject, COUNT(*) FROM questions GROUP BY subject")
    stats = c.fetchall()
    conn.close()
    return stats

# --- NEW: GEMINI VISION FUNCTIONS ---
def generate_batch_with_vision(gemini_file, subject, model_name, batch_num):
    """
    Sends the PDF file directly to Gemini. 
    Gemini performs OCR internally.
    """
    prompt = f"""
    Role: Strict Teacher. Subject: {subject}.
    Task: Create 10 CHALLENGING multiple-choice questions based on the uploaded document.
    
    Focus:
    This is Batch {batch_num} of 4. 
    - If batch 1: Focus on the beginning/introductory concepts.
    - If batch 2: Focus on the middle concepts.
    - If batch 3: Focus on the advanced/later concepts.
    - If batch 4: Focus on details, definitions, and specific examples throughout the text.
    
    Rules:
    1. Read the document carefully (even if it is a scan).
    2. Language: 
       - Math: Traditional Chinese + Text Formulas (x^2)
       - Chinese/Humanities: Traditional Chinese
       - English: English
    3. Output: JSON Array ONLY.
    
    JSON Structure:
    [
      {{
        "question": "...",
        "options": ["Option A", "Option B", "Option C", "Option D"],
        "answer": "Exact text of correct option",
        "explanation": "Brief explanation."
      }}
    ]
    """
    
    model = genai.GenerativeModel(model_name)
    try:
        # We send the FILE object + the PROMPT together
        response = model.generate_content([gemini_file, prompt])
        clean = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean)
    except Exception as e:
        print(f"Batch generation failed: {e}")
        return []

# --- MAIN APP UI ---
init_db()

with st.sidebar:
    st.title("⚙️ Settings")
    api_key = st.text_input("Gemini API Key", type="password")
    
    selected_model = None
    if api_key:
        genai.configure(api_key=api_key)
        try:
            # We filter for models that support 'generateContent'
            # Note: 1.5-flash is multimodal by default
            models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            # Default to flash if available as it is best for PDF reading
            default_ix = 0
            for i, m in enumerate(models):
                if "flash" in m:
                    default_ix = i
            selected_model = st.selectbox("AI Model", models, index=default_ix)
        except:
            st.error("Invalid Key")

    st.divider()
    st.write("📊 **Database Stats**")
    stats = get_db_stats()
    if stats:
        for s in stats:
            st.write(f"- {s[0]}: {s[1]} Qs")
    else:
        st.write("No questions yet.")
        
    if st.button("🗑️ Clear Database"):
        conn = sqlite3.connect('quiz.db')
        conn.execute("DELETE FROM questions")
        conn.commit()
        conn.close()
        st.rerun()

# --- TABS ---
tab1, tab2 = st.tabs(["📤 Upload (OCR Supported)", "📝 Take Quiz"])

# === TAB 1: GENERATE ===
with tab1:
    st.header("Build your Question Bank")
    st.info("Upload PDF (Text or Scans). Google Gemini will read it directly.")
    
    gen_subject = st.selectbox("Subject", ["中文 (Chinese)", "英文 (English)", "數學 (Math)", "人文科學 (Humanities)"], key="gen_sub")
    uploaded_file = st.file_uploader("Upload Notes (PDF)", type=["pdf"])

    if st.button("🚀 Generate 40 Questions"):
        if not api_key or not uploaded_file or not selected_model:
            st.error("Missing API Key, File, or Model.")
        else:
            status = st.empty()
            progress = st.progress(0)
            
            # 1. Save uploaded file to a temporary path (Required for Gemini Upload)
            status.write("Uploading file to AI...")
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                tmp_file.write(uploaded_file.getvalue())
                tmp_path = tmp_file.name

            try:
                # 2. Upload file to Google Gemini
                sample_file = genai.upload_file(path=tmp_path, display_name="Class Notes")
                
                # Wait for file to be processed
                while sample_file.state.name == "PROCESSING":
                    time.sleep(2)
                    sample_file = genai.get_file(sample_file.name)
                
                if sample_file.state.name == "FAILED":
                    raise ValueError("AI failed to process the file.")
                
                status.write("File Processed by AI. Generating Questions...")
                total_added = 0
                
                # 3. Loop 4 times to get 40 questions
                for i in range(4):
                    status.write(f"Generating Batch {i+1}/4 (Focusing on different parts)...")
                    
                    # Pass the FILE object to the generate function
                    questions = generate_batch_with_vision(sample_file, gen_subject, selected_model, i+1)
                    
                    if questions:
                        saved_count = save_questions_to_db(questions, gen_subject, uploaded_file.name)
                        total_added += saved_count
                    
                    progress.progress((i + 1) / 4)
                    time.sleep(1) 
                
                status.success(f"✅ Done! Added {total_added} questions from scanned document.")
                
                # Cleanup: Delete file from Google Cloud to save space
                genai.delete_file(sample_file.name)
                
                time.sleep(2)
                st.rerun()

            except Exception as e:
                st.error(f"Error: {e}")
            finally:
                # Cleanup local temp file
                os.remove(tmp_path)

# === TAB 2: TAKE QUIZ (Same as before) ===
with tab2:
    st.header("Practice Mode")
    quiz_subject = st.selectbox("Choose Subject", ["中文 (Chinese)", "英文 (English)", "數學 (Math)", "人文科學 (Humanities)"], key="quiz_sub")
    
    if "current_quiz" not in st.session_state:
        st.session_state.current_quiz = []
    if "quiz_submitted" not in st.session_state:
        st.session_state.quiz_submitted = False

    if st.button("🎲 Start Random Quiz (20 Qs)"):
        questions = get_random_quiz(quiz_subject, limit=20)
        if not questions:
            st.warning("No questions found. Go to 'Upload' tab first!")
        else:
            st.session_state.current_quiz = questions
            st.session_state.quiz_submitted = False
            st.rerun()

    if st.session_state.current_quiz:
        st.write(f"### {quiz_subject} Test")
        with st.form("quiz_form"):
            for idx, q in enumerate(st.session_state.current_quiz):
                st.markdown(f"**{idx+1}. {q['question']}**")
                st.radio("Options", q['options'], key=f"q{idx}", label_visibility="collapsed", index=None)
                st.markdown("---")
            submitted = st.form_submit_button("Submit Exam")
            if submitted:
                st.session_state.quiz_submitted = True
                st.rerun()

        if st.session_state.quiz_submitted:
            score = 0
            total = len(st.session_state.current_quiz)
            st.divider()
            st.subheader("📝 Results")
            for idx, q in enumerate(st.session_state.current_quiz):
                u_ans = st.session_state.get(f"q{idx}")
                c_ans = q['answer']
                if u_ans == c_ans:
                    score += 1
                    st.success(f"Q{idx+1}: Correct")
                else:
                    st.error(f"Q{idx+1}: Incorrect")
                    st.markdown(f"**Your Answer:** {u_ans}")
                    st.markdown(f"**Correct Answer:** {c_ans}")
                    st.info(f"**Explanation:** {q['explanation']}")
            st.metric("Final Score", f"{score}/{total}", f"{int(score/total*100)}%")
