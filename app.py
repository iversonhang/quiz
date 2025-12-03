import streamlit as st
import google.generativeai as genai
import json
import psycopg2
import os
import time
import tempfile

# --- CONFIGURATION ---
st.set_page_config(page_title="Pro Quiz Portal", page_icon="🎓", layout="wide")

# --- DATABASE CONNECTION (SUPABASE) ---
def get_db_connection():
    """Connect to Supabase using the URL from secrets."""
    try:
        # Load URL from secrets.toml
        return psycopg2.connect(st.secrets["DB_URL"])
    except Exception as e:
        st.error(f"Database Connection Failed: {e}")
        return None

def init_db():
    conn = get_db_connection()
    if conn:
        cur = conn.cursor()
        # Create table (Postgres syntax)
        cur.execute('''
            CREATE TABLE IF NOT EXISTS questions (
                id SERIAL PRIMARY KEY,
                subject TEXT,
                question TEXT,
                options TEXT,
                answer TEXT,
                explanation TEXT,
                source_file TEXT
            )
        ''')
        conn.commit()
        cur.close()
        conn.close()

def save_questions_to_db(questions, subject, filename):
    conn = get_db_connection()
    if not conn: return 0
    
    cur = conn.cursor()
    count = 0
    for q in questions:
        if 'question' in q and 'options' in q and 'answer' in q:
            options_str = json.dumps(q['options'])
            # Postgres uses %s for placeholders (unlike SQLite's ?)
            cur.execute('''
                INSERT INTO questions (subject, question, options, answer, explanation, source_file)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (subject, q['question'], options_str, q['answer'], q.get('explanation', ''), filename))
            count += 1
    conn.commit()
    cur.close()
    conn.close()
    return count

def get_random_quiz(subject, limit=20):
    conn = get_db_connection()
    if not conn: return []
    
    cur = conn.cursor()
    # Postgres RANDOM() function works same as SQLite
    cur.execute('''
        SELECT question, options, answer, explanation 
        FROM questions 
        WHERE subject = %s 
        ORDER BY RANDOM() 
        LIMIT %s
    ''', (subject, limit))
    
    rows = cur.fetchall()
    cur.close()
    conn.close()
    
    return [{
        'question': row[0],
        'options': json.loads(row[1]),
        'answer': row[2],
        'explanation': row[3]
    } for row in rows]

def get_db_stats():
    conn = get_db_connection()
    if not conn: return []
    cur = conn.cursor()
    cur.execute("SELECT subject, COUNT(*) FROM questions GROUP BY subject")
    stats = cur.fetchall()
    cur.close()
    conn.close()
    return stats

def clear_db():
    conn = get_db_connection()
    if conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM questions")
        conn.commit()
        cur.close()
        conn.close()

# --- GEMINI AI LOGIC (Same as before) ---
def generate_batch_with_vision(gemini_file, subject, model_name, batch_num):
    # Specialized instructions
    english_rules = ""
    if "English" in subject:
        english_rules = """
        IMPORTANT FOR ENGLISH: Focus STRICTLY on Grammar (Tenses, Prepositions, Phrasal Verbs).
        Format: "Fill-in-the-blank" or "Identify error". No reading comprehension.
        """

    prompt = f"""
    Role: Strict Teacher. Subject: {subject}.
    Task: Create 10 CHALLENGING multiple-choice questions.
    Batch: {batch_num} of 4.
    
    {english_rules}
    
    CRITICAL: Use LaTeX ($...$) for math formulas.
    
    JSON Structure:
    [
      {{
        "question": "...",
        "options": ["A", "B", "C", "D"],
        "answer": "Correct Answer",
        "explanation": "Brief explanation."
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

if "quiz_session_id" not in st.session_state:
    st.session_state.quiz_session_id = 0
if "current_quiz" not in st.session_state:
    st.session_state.current_quiz = []
if "quiz_submitted" not in st.session_state:
    st.session_state.quiz_submitted = False

with st.sidebar:
    st.title("⚙️ Settings")
    api_key = st.text_input("Gemini API Key", type="password")
    
    selected_model = None
    if api_key:
        genai.configure(api_key=api_key)
        try:
            models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            default_ix = next((i for i, m in enumerate(models) if "flash" in m), 0)
            selected_model = st.selectbox("AI Model", models, index=default_ix)
        except:
            st.error("Invalid Key")

    st.divider()
    st.write("📊 **Cloud Database Stats**")
    stats = get_db_stats()
    if stats:
        for s in stats:
            st.write(f"- {s[0]}: {s[1]} Qs")
    else:
        st.write("No questions yet.")
        
    if st.button("🗑️ Clear Cloud Database"):
        clear_db()
        st.success("Database cleared.")
        time.sleep(1)
        st.rerun()

# --- TABS ---
tab1, tab2 = st.tabs(["📤 Upload (Build Bank)", "📝 Take Quiz"])

# === TAB 1: GENERATE ===
with tab1:
    st.header("Build Question Bank")
    st.info("Upload PDF. Questions are saved to Supabase (Cloud) and persist forever.")
    
    gen_subject = st.selectbox("Subject", ["中文 (Chinese)", "英文 (English)", "數學 (Math)", "人文科學 (Humanities)"], key="gen_sub")
    uploaded_file = st.file_uploader("Upload Notes (PDF)", type=["pdf"])

    if st.button("🚀 Generate 40 Questions"):
        if not api_key or not uploaded_file or not selected_model:
            st.error("Missing API Key, File, or Model.")
        else:
            status = st.empty()
            progress = st.progress(0)
            
            status.write("Uploading to AI...")
            # Temp file logic for Gemini Upload
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                tmp_file.write(uploaded_file.getvalue())
                tmp_path = tmp_file.name

            try:
                sample_file = genai.upload_file(path=tmp_path, display_name="Class Notes")
                while sample_file.state.name == "PROCESSING":
                    time.sleep(1)
                    sample_file = genai.get_file(sample_file.name)
                
                if sample_file.state.name == "FAILED":
                    raise ValueError("AI failed to process file.")
                
                status.write("File Ready. Generating...")
                total_added = 0
                
                for i in range(4):
                    status.write(f"Generating Batch {i+1}/4...")
                    questions = generate_batch_with_vision(sample_file, gen_subject, selected_model, i+1)
                    if questions:
                        saved_count = save_questions_to_db(questions, gen_subject, uploaded_file.name)
                        total_added += saved_count
                    progress.progress((i + 1) / 4)
                    time.sleep(1) 
                
                status.success(f"✅ Saved {total_added} questions to Cloud Database!")
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
        quiz_subject = st.selectbox("Select Subject", ["中文 (Chinese)", "英文 (English)", "數學 (Math)", "人文科學 (Humanities)"], key="quiz_sub")

    if st.button("🎲 Start Random Quiz (20 Qs)"):
        questions = get_random_quiz(quiz_subject, limit=20)
        
        if not questions:
            st.warning("No questions found in Cloud DB.")
        else:
            # RESET
            st.session_state.current_quiz = questions
            st.session_state.quiz_submitted = False
            st.session_state.quiz_session_id = int(time.time())
            st.rerun()

    if st.session_state.current_quiz:
        st.divider()
        st.markdown(f"#### 📝 {quiz_subject} Assessment")
        
        with st.form("quiz_form"):
            for idx, q in enumerate(st.session_state.current_quiz):
                st.markdown(f"**{idx+1}. {q['question']}**")
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

        if st.session_state.quiz_submitted:
            score = 0
            total = len(st.session_state.current_quiz)
            
            st.divider()
            st.subheader("📊 Results")
            
            for idx, q in enumerate(st.session_state.current_quiz):
                u_ans = st.session_state.get(f"q{idx}_{st.session_state.quiz_session_id}")
                c_ans = q['answer']
                
                with st.container():
                    if u_ans == c_ans:
                        score += 1
                        st.success(f"**Q{idx+1}: Correct!**")
                    else:
                        st.error(f"**Q{idx+1}: Incorrect**")
                        
                    c1, c2 = st.columns(2)
                    with c1:
                        st.markdown("**Your Answer:**")
                        st.markdown(u_ans if u_ans else "No Answer")
                    with c2:
                        st.markdown("**Correct Answer:**")
                        st.markdown(c_ans)
                    
                    st.info(f"**Explanation:** {q['explanation']}")
                    st.markdown("---")
            
            st.metric("Final Score", f"{score}/{total}", f"{int(score/total*100)}%")
