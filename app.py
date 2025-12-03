import streamlit as st
import google.generativeai as genai
import pypdf
import os
import json

# 1. Configure Page
st.set_page_config(page_title="Note-to-Quiz", page_icon="📚")

# 2. Sidebar for API Key
with st.sidebar:
    st.header("Settings")
    api_key = st.text_input("Enter Google Gemini API Key", type="password")
    
    # Store API key in session state if entered
    if api_key:
        genai.configure(api_key=api_key)
    
    st.markdown("---")
    st.markdown("**How to use:**\n1. Enter API Key\n2. Upload PDF\n3. Select Subject\n4. Take Quiz!")

# 3. Main App Logic
st.title("📚 AI Note-to-Quiz Portal")

# Initialize Session State (To remember quiz data)
if "quiz_data" not in st.session_state:
    st.session_state.quiz_data = None
if "answers" not in st.session_state:
    st.session_state.answers = {}
if "score_submitted" not in st.session_state:
    st.session_state.score_submitted = False

# Subject Selection
subject = st.selectbox("Select Subject", ["中文 (Chinese)", "英文 (English)", "數學 (Math)", "人文科學 (Humanities)"])

# File Upload
uploaded_file = st.file_uploader("Upload your Notes (PDF)", type=["pdf"])

def extract_text_from_pdf(file):
    try:
        pdf_reader = pypdf.PdfReader(file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() or ""
        return text
    except Exception as e:
        st.error(f"Error reading PDF: {e}")
        return None

def generate_quiz(text, subject):
    prompt = f"""
    You are a strict teacher. 
    Subject: {subject}
    Language Logic:
    - If subject is Chinese/Humanities: Use Traditional Chinese (繁體中文).
    - If subject is English: Use English.
    - If subject is Math: Use Traditional Chinese. Return math formulas as text (e.g., x^2).
    
    Task: Generate 5 multiple choice questions based on the notes below.
    Format: Return ONLY raw JSON. No markdown formatting.
    Structure:
    [
        {{
            "question": "Question text",
            "options": ["A", "B", "C", "D"],
            "answer": "Correct Option Text",
            "explanation": "Why it is correct"
        }}
    ]
    
    Notes Content:
    {text[:20000]}
    """
    
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        
        # Clean up JSON (remove markdown backticks if AI adds them)
        clean_json = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_json)
    except Exception as e:
        st.error(f"AI Error: {e}")
        return None

# Generate Button
if uploaded_file and api_key:
    if st.button("Generate Quiz"):
        with st.spinner("Analyzing PDF..."):
            text = extract_text_from_pdf(uploaded_file)
            if text:
                quiz = generate_quiz(text, subject)
                if quiz:
                    st.session_state.quiz_data = quiz
                    st.session_state.answers = {}
                    st.session_state.score_submitted = False
                    st.rerun()

# --- QUIZ INTERFACE ---
if st.session_state.quiz_data:
    st.markdown("### 📝 Quiz Time")
    
    form = st.form(key='quiz_form')
    
    correct_count = 0
    
    for i, q in enumerate(st.session_state.quiz_data):
        form.markdown(f"**Q{i+1}: {q['question']}**")
        
        # Radio button for options
        user_choice = form.radio(
            f"Select answer for Q{i+1}:", 
            q['options'], 
            key=f"q_{i}", 
            index=None
        )
        
    submit = form.form_submit_button("Submit Answers")
    
    if submit:
        st.session_state.score_submitted = True

    # Show Results
    if st.session_state.score_submitted:
        st.divider()
        st.subheader("Results")
        score = 0
        for i, q in enumerate(st.session_state.quiz_data):
            user_ans = st.session_state.get(f"q_{i}")
            correct_ans = q['answer']
            
            if user_ans == correct_ans:
                score += 1
                st.success(f"**Q{i+1}: Correct!**")
            else:
                st.error(f"**Q{i+1}: Incorrect.**")
                st.markdown(f"Your answer: {user_ans}")
                st.markdown(f"Correct answer: **{correct_ans}**")
            
            with st.expander(f"See Explanation for Q{i+1}"):
                st.write(q['explanation'])
        
        st.metric(label="Final Score", value=f"{score} / 5")
        
        if st.button("Start New Quiz"):
            st.session_state.quiz_data = None
            st.rerun()

elif not api_key:
    st.info("👈 Please enter your API Key in the sidebar to start.")