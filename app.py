import streamlit as st
import requests
import cv2
import numpy as np
import concurrent.futures
import time

# ================= CONFIGURATION =================
BASE_URL = "https://student.bennetterp.camu.in"
# =================================================

def get_headers(user_agent_index):
    agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ]
    return {
        "User-Agent": agents[user_agent_index % len(agents)],
        "Content-Type": "application/json",
        "Origin": BASE_URL,
        "Referer": f"{BASE_URL}/"
    }

def check_password():
    if "APP_PASSWORD" not in st.secrets: return True
    def password_entered():
        if st.session_state["password"] == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False
    if "password_correct" not in st.session_state:
        st.text_input("Enter Access Password", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("Enter Access Password", type="password", on_change=password_entered, key="password")
        st.error("❌ Access Denied")
        return False
    else:
        return True

# --- 🧠 SMART LOGIN (WITH SESSION PRIMING) ---
def get_auth_token(student, session, headers):
    # 1. Manual Token (Always Fastest)
    if student.get('token'): return student['token'], "🔑 Token (Manual)"

    # 2. Auto-Login with "Browser Mimic"
    if student.get('user') and student.get('pass'):
        try:
            # STEP A: Visit the Main Page first (To get Cookies/CSRF)
            # This makes the server think we are a real browser
            session.get(BASE_URL, headers={"User-Agent": headers["User-Agent"]}, timeout=5)
            
            # STEP B: Now try to Login
            payload = {
                "username": student['user'],
                "password": student['pass'],
                "user_type": "Student"
            }
            
            # Try V2 (Likely for Bennett)
            resp = session.post(f"{BASE_URL}/v2/login", json=payload, headers=headers, timeout=5)
            if resp.status_code == 200:
                token = resp.json().get('data', {}).get('token') or resp.json().get('token')
                if token: return token, "🔓 Login (V2)"
            
            # Try Standard (Backup)
            resp = session.post(f"{BASE_URL}/api/login", json=payload, headers=headers, timeout=5)
            if resp.status_code == 200:
                token = resp.json().get('data', {}).get('token') or resp.json().get('token')
                if token: return token, "🔓 Login (V1)"

        except Exception as e:
            return None, f"⚠️ Err: {str(e)}"
            
    return None, "❌ Login Failed (404/401)"

# --- ⚡ PROCESS STUDENT ---
def process_student(student, qr_code, agent_index):
    start_time = time.time()
    headers = get_headers(agent_index)
    session = requests.Session() # Session keeps cookies (Like a browser)
    safe_name = student.get('name', 'Unknown')
    
    # 1. LOGIN
    token, login_status = get_auth_token(student, session, headers)
    
    if not token:
        return {"success": False, "name": safe_name, "step": "Login", "msg": login_status}

    # 2. MARK ATTENDANCE
    mark_payload = {
        "qr_code": qr_code,
        "latitude": "28.4505", 
        "longitude": "77.5128"
    }
    auth_headers = headers.copy()
    auth_headers["Authorization"] = f"Bearer {token}"
    
    try:
        # Try V2 Mark first
        mark_resp = session.post(f"{BASE_URL}/v2/instruction/mark_attendance_qr", json=mark_payload, headers=auth_headers, timeout=5)
        
        # If V2 fails, Try V1
        if mark_resp.status_code == 404:
            mark_resp = session.post(f"{BASE_URL}/api/instruction/mark_attendance_qr", json=mark_payload, headers=auth_headers, timeout=5)

        duration = round(time.time() - start_time, 2)
        
        # Read Server Reply
        try: server_reply = mark_resp.json().get('message', mark_resp.text[:30])
        except: server_reply = mark_resp.text[:30]

        if mark_resp.status_code == 200:
            return {
                "success": True, 
                "name": safe_name, 
                "step": "Complete", 
                "msg": f"{login_status} ➝ ✅ Marked ({duration}s)", 
                "server_reply": server_reply
            }
        
        return {
            "success": False, 
            "name": safe_name, 
            "step": "Marking", 
            "msg": f"{login_status} ➝ ❌ Failed ({mark_resp.status_code})", 
            "server_reply": server_reply
        }

    except Exception as e:
        return {"success": False, "name": safe_name, "step": "Error", "msg": str(e)}

# --- 🖥️ UI ---
if check_password():
    st.set_page_config(page_title="Bennett Bot", page_icon="🎓", layout="centered")
    st.title("🎓 Bennett Bot (Browser Mode)")

    tab1, tab2 = st.tabs(["📸 Camera", "📝 Paste"])
    qr_data = None

    with tab1:
        img_buffer = st.camera_input("Scan QR")
        if img_buffer:
            bytes_data = img_buffer.getvalue()
            cv2_img = cv2.imdecode(np.frombuffer(bytes_data, np.uint8), cv2.IMREAD_COLOR)
            detector = cv2.QRCodeDetector()
            data, bbox, _ = detector.detectAndDecode(cv2_img)
            if data: qr_data = data

    with tab2:
        qr_text = st.text_input("Paste Manually:")
        if qr_text: qr_data = qr_text

    if qr_data:
        if st.button("🚀 LAUNCH", type="primary", use_container_width=True):
            if "squad" not in st.secrets: st.error("Secrets missing."); st.stop()
            
            squad_list = st.secrets["squad"]
            st.divider()
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                future_to_student = {
                    executor.submit(process_student, student, qr_data, i): student 
                    for i, student in enumerate(squad_list)
                }
                for future in concurrent.futures.as_completed(future_to_student):
                    res = future.result()
                    if res['success']:
                        st.success(f"**{res['name']}**\n{res['msg']}")
                    else:
                        st.error(f"**{res['name']}**\nFailed: {res['msg']}")
