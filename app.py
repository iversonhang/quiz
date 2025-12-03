import streamlit as st
import google.generativeai as genai
import pypdf
import json
import sqlite3
import random
import time

# --- CONFIGURATION ---
st.set_page_config(page_title="Pro Quiz Portal", page_icon="🎓", layout="wide")

# --- DATABASE FUNCTIONS ---
def init_db():
    """Create the database if it doesn't exist."""
    conn = sqlite3.connect('quiz.db')
    c = conn.cursor()
    # Create table to store questions
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
    """Save a list of questions to SQLite."""
    conn = sqlite3.connect('quiz.db')
    c = conn.cursor()
    count = 0
    for q in questions:
        # Verify structure before saving
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
    """Fetch random questions for a specific subject."""
    conn = sqlite3.connect('quiz.db')
    conn.row_factory = sqlite3.Row # Allow accessing columns by name
    c = conn.cursor()
    
    c.execute('''
        SELECT * FROM questions 
        WHERE subject = ? 
        ORDER BY RANDOM() 
        LIMIT ?
    ''', (subject, limit))
    
    rows = c.fetchall()
    conn.close()
    
    # Convert back to Python dictionary format
    quiz_list = []
    for row in rows:
        quiz_list.append({
            'question': row['question'],
            'options': json.loads(row['options']), # Convert string back to list
            'answer': row['answer'],
            'explanation': row['explanation']
        })
    return quiz_list

def get_db_stats():
    """Check how many questions we have per subject."""
    conn = sqlite3.connect('quiz.db')
    c = conn.cursor()
    c.execute("SELECT subject, COUNT(*) FROM questions GROUP BY subject")
    stats = c.fetchall()
    conn.close()
    return stats

# --- PDF & AI FUNCTIONS ---
def extract_text(file):
    try:
        reader = pypdf.PdfReader(file)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text
    except:
        return None

def generate_batch(text_chunk, subject, model_name):
    """Generates 10 questions from a chunk of text."""
    prompt = f"""
    Role: Strict Teacher. Subject: {subject}.
    Task: Create 10 CHALLENGING multiple-choice questions based ONLY on the provided text.
    
    Rules:
    1. Accuracy is paramount. Verify the answer exists in the text.
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
        "explanation": "Quote the sentence from the text that proves this answer."
      }}
    ]

    Text content to quiz on:
    {text_chunk}
    """
    model = genai.GenerativeModel(model_name)
    try:
        response = model.generate_content(prompt)
        clean = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean)
    except Exception as e:
        print(f"Batch generation failed: {e}")
        return []

# --- MAIN APP UI ---
init_db() # Ensure DB exists on startup

with st.sidebar:
    st.title("⚙️ Settings")
    api_key = st.text_input("Gemini API Key", type="password")
    
    # Model Selector
    selected_model = None
    if api_key:
        genai.configure(api_key=api_key)
        try:
            models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            selected_model = st.selectbox("AI Model", models)
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

# --- TABS FOR MODE SELECTION ---
tab1, tab2 = st.tabs(["📤 Upload & Generate", "📝 Take Quiz"])

# === TAB 1: GENERATE ===
with tab1:
    st.header("Build your Question Bank")
    st.info("Upload notes to generate 40 questions and save them to the database.")
    
    gen_subject = st.selectbox("Subject", ["中文 (Chinese)", "英文 (English)", "數學 (Math)", "人文科學 (Humanities)"], key="gen_sub")
    uploaded_file = st.file_uploader("Upload Notes (PDF)", type=["pdf"])

    if st.button("🚀 Generate 40 Questions"):
        if not api_key or not uploaded_file or not selected_model:
            st.error("Missing API Key, File, or Model.")
        else:
            status = st.empty()
            progress = st.progress(0)
            
            # 1. Read PDF
            status.write("Reading PDF...")
            full_text = extract_text(uploaded_file)
            
            if not full_text:
                st.error("Could not read PDF.")
            else:
                # 2. Split text into chunks to get better variety
                # We need 4 batches of 10 questions.
                # We split the text into 4 parts roughly.
                chunk_size = len(full_text) // 4
                total_added = 0
                
                for i in range(4):
                    start = i * chunk_size
                    end = (i + 1) * chunk_size
                    chunk = full_text[start:end]
                    
                    status.write(f"Generating Batch {i+1}/4 (Questions {i*10+1}-{i*10+10})...")
                    
                    # Generate
                    questions = generate_batch(chunk, gen_subject, selected_model)
                    
                    # Save
                    if questions:
                        saved_count = save_questions_to_db(questions, gen_subject, uploaded_file.name)
                        total_added += saved_count
                    
                    progress.progress((i + 1) / 4)
                    time.sleep(1) # Prevent hitting API rate limits
                
                status.success(f"✅ Done! Added {total_added} questions to the database.")
                time.sleep(2)
                st.rerun()

# === TAB 2: TAKE QUIZ ===
with tab2:
    st.header("Practice Mode")
    
    quiz_subject = st.selectbox("Choose Subject", ["中文 (Chinese)", "英文 (English)", "數學 (Math)", "人文科學 (Humanities)"], key="quiz_sub")
    
    # Initialize Quiz State
    if "current_quiz" not in st.session_state:
        st.session_state.current_quiz = []
    if "quiz_submitted" not in st.session_state:
        st.session_state.quiz_submitted = False

    if st.button("🎲 Start Random Quiz (20 Qs)"):
        questions = get_random_quiz(quiz_subject, limit=20)
        if not questions:
            st.warning("No questions found for this subject. Go to 'Upload' tab first!")
        else:
            st.session_state.current_quiz = questions
            st.session_state.quiz_submitted = False
            st.rerun()

    # Display Quiz
    if st.session_state.current_quiz:
        st.write(f"### {quiz_subject} Test")
        
        with st.form("quiz_form"):
            user_answers = {}
            for idx, q in enumerate(st.session_state.current_quiz):
                st.markdown(f"**{idx+1}. {q['question']}**")
                user_answers[idx] = st.radio(
                    "Options", 
                    q['options'], 
                    key=f"q{idx}", 
                    label_visibility="collapsed",
                    index=None
                )
                st.markdown("---")
            
            submitted = st.form_submit_button("Submit Exam")
            if submitted:
                st.session_state.quiz_submitted = True
                st.rerun()

        # Results
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
