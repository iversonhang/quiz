import streamlit as st
import google.generativeai as genai
import json
import sqlite3
import time
import tempfile
import os
import time

# --- CONFIGURATION ---
st.set_page_config(page_title="Pro Quiz Portal", page_icon="🎓", layout="wide")

# --- DATABASE FUNCTIONS ---
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
            # Ensure options are stringified JSON
            options_str = json.dumps(q['options'])
            c.execute('''
                INSERT INTO questions (subject, question, options, answer, explanation, source_file)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (subject, q['question'], options_str, q['answer'], q.get('explanation', ''), filename))
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

# --- GEMINI VISION ---
def generate_batch_with_vision(gemini_file, subject, model_name, batch_num):
    prompt = f"""
    Role: Strict Teacher. Subject: {subject}.
    Task: Create 10 CHALLENGING multiple-choice questions based on the uploaded document.
    Batch: {batch_num} of 4.
    
    CRITICAL INSTRUCTION FOR MATH/SCIENCE:
    If the question involves formulas, equations, or special symbols, YOU MUST use LaTeX formatting enclosed in dollar signs.
    
    Examples:
    - Write "x squared" as: $ x^2 $
    - Write "fractions" as: $ \\frac{{1}}{{2}} $
    - Write "square root" as: $ \\sqrt{{x}} $
    
    Rules:
    1. Output JSON Array ONLY.
    2. Language: 
       - Math/Science: Traditional Chinese questions, but use LaTeX for ALL numbers/formulas.
       - Chinese/Humanities: Traditional Chinese.
       - English: English.
    
    JSON Structure:
    [
      {{
        "question": "Calculate the integral: $ \\int x dx $",
        "options": ["$ x^2 $", "$ \\frac{{x^2}}{{2}} + C $", "$ 2x $", "$ x $"],
        "answer": "$ \\frac{{x^2}}{{2}} + C $",
        "explanation": "Using the power rule..."
      }}
    ]
    """
    
    model = genai.GenerativeModel(model_name)
    try:
        response = model.generate_content([gemini_file, prompt])
        clean = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean)
    except Exception as e:
        print(f"Batch generation failed: {e}")
        return []

# --- MAIN APP UI ---
init_db()

# Session State Initialization
if "quiz_session_id" not in st.session_state:
    st.session_state.quiz_session_id = 0

with st.sidebar:
    st.title("⚙️ Settings")
    api_key = st.text_input("Gemini API Key", type="password")
    
    selected_model = None
    if api_key:
        genai.configure(api_key=api_key)
        try:
            models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            # Prefer flash model
            default_ix = next((i for i, m in enumerate(models) if "flash" in m), 0)
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
        
    if st.button("🗑️ Clear All Questions"):
        conn = sqlite3.connect('quiz.db')
        conn.execute("DELETE FROM questions")
        conn.commit()
        conn.close()
        st.success("Database cleared.")
        time.sleep(1)
        st.rerun()

# --- TABS ---
tab1, tab2 = st.tabs(["📤 Upload (Build Bank)", "📝 Take Quiz"])

# === TAB 1: GENERATE ===
with tab1:
    st.header("Build Question Bank")
    st.info("Upload PDF. Google Gemini will read it (including Scans) and generate 40 questions.")
    
    gen_subject = st.selectbox("Subject", ["中文 (Chinese)", "英文 (English)", "數學 (Math)", "人文科學 (Humanities)"], key="gen_sub")
    uploaded_file = st.file_uploader("Upload Notes (PDF)", type=["pdf"])

    if st.button("🚀 Generate 40 Questions"):
        if not api_key or not uploaded_file or not selected_model:
            st.error("Missing API Key, File, or Model.")
        else:
            status = st.empty()
            progress = st.progress(0)
            
            status.write("Uploading to AI...")
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                tmp_file.write(uploaded_file.getvalue())
                tmp_path = tmp_file.name

            try:
                sample_file = genai.upload_file(path=tmp_path, display_name="Class Notes")
                
                # Poll for processing
                while sample_file.state.name == "PROCESSING":
                    time.sleep(1)
                    sample_file = genai.get_file(sample_file.name)
                
                if sample_file.state.name == "FAILED":
                    raise ValueError("AI failed to process file.")
                
                status.write("File Ready. Generating Questions...")
                total_added = 0
                
                for i in range(4):
                    status.write(f"Generating Batch {i+1}/4...")
                    questions = generate_batch_with_vision(sample_file, gen_subject, selected_model, i+1)
                    if questions:
                        saved_count = save_questions_to_db(questions, gen_subject, uploaded_file.name)
                        total_added += saved_count
                    progress.progress((i + 1) / 4)
                    time.sleep(1) 
                
                status.success(f"✅ Success! Added {total_added} questions.")
                genai.delete_file(sample_file.name)
                time.sleep(2)
                st.rerun()

            except Exception as e:
                st.error(f"Error: {e}")
            finally:
                os.remove(tmp_path)

# === TAB 2: TAKE QUIZ ===
with tab2:
    col1, col2 = st.columns([3, 1])
    with col1:
        st.header("Practice Mode")
    with col2:
        # Subject Selector for Quiz
        quiz_subject = st.selectbox("Select Subject", ["中文 (Chinese)", "英文 (English)", "數學 (Math)", "人文科學 (Humanities)"], key="quiz_sub")

    # Initialize State
    if "current_quiz" not in st.session_state:
        st.session_state.current_quiz = []
    if "quiz_submitted" not in st.session_state:
        st.session_state.quiz_submitted = False

    # START BUTTON
    if st.button("🎲 Start New Quiz (20 Qs)"):
        # 1. Fetch Questions
        questions = get_random_quiz(quiz_subject, limit=20)
        
        if not questions:
            st.warning("No questions found. Please upload notes first.")
        else:
            # 2. RESET EVERYTHING
            st.session_state.current_quiz = questions
            st.session_state.quiz_submitted = False
            # 3. UPDATE SESSION ID (This forces all radio buttons to reset)
            st.session_state.quiz_session_id = int(time.time())
            st.rerun()

    # DISPLAY QUIZ
    if st.session_state.current_quiz:
        st.divider()
        st.markdown(f"#### 📝 {quiz_subject} Assessment")
        
        with st.form("quiz_form"):
            for idx, q in enumerate(st.session_state.current_quiz):
                # RENDER QUESTION (Markdown supports LaTeX)
                st.markdown(f"**{idx+1}. {q['question']}**")
                
                # RENDER OPTIONS
                # We append quiz_session_id to the key to force a hard reset
                st.radio(
                    "Select Answer:", 
                    q['options'], 
                    key=f"q{idx}_{st.session_state.quiz_session_id}", 
                    label_visibility="collapsed",
                    index=None
                )
                st.markdown("---")
            
            submitted = st.form_submit_button("Submit Exam")
            if submitted:
                st.session_state.quiz_submitted = True
                st.rerun()

        # RESULTS
        if st.session_state.quiz_submitted:
            score = 0
            total = len(st.session_state.current_quiz)
            
            st.divider()
            st.subheader("📊 Results")
            
            for idx, q in enumerate(st.session_state.current_quiz):
                # Retrieve user answer using the dynamic key
                u_ans = st.session_state.get(f"q{idx}_{st.session_state.quiz_session_id}")
                c_ans = q['answer']
                
                if u_ans == c_ans:
                    score += 1
                    st.success(f"Q{idx+1}: Correct")
                else:
                    st.error(f"Q{idx+1}: Incorrect")
                    # Use LaTeX columns to show math clearly
                    c1, c2 = st.columns(2)
                    with c1: 
                        st.markdown("**Your Answer:**")
                        st.markdown(u_ans if u_ans else "None")
                    with c2:
                        st.markdown("**Correct Answer:**")
                        st.markdown(c_ans)
                    
                    st.info(f"**Explanation:** {q['explanation']}")
            
            st.metric("Final Score", f"{score}/{total}", f"{int(score/total*100)}%")
