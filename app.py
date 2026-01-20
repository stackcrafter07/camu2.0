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
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Mobile Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36"
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

# --- 🧠 SMART LOGIN (TRYING V2 ENDPOINT) ---
def get_auth_token(student, session, headers):
    # Option A: Manual Token
    if student.get('token'):
        return student['token'], "🔑 Token (Manual)"
    
    # Option B: Auto-Login
    if student.get('user') and student.get('pass'):
        payload = {
            "username": student['user'],
            "password": student['pass'],
            "user_type": "Student"
        }
        
        # 1. Try V2 Endpoint (Most likely for Bennett)
        try:
            # Note: Trying /v2/login based on your logs
            v2_url = f"{BASE_URL}/v2/login" 
            resp = session.post(v2_url, json=payload, headers=headers, timeout=5)
            if resp.status_code == 200:
                token = resp.json().get('data', {}).get('token') or resp.json().get('token')
                if token: return token, "🔓 Login (V2)"
        except: pass

        # 2. Try Standard Endpoint (Backup)
        try:
            v1_url = f"{BASE_URL}/api/login"
            resp = session.post(v1_url, json=payload, headers=headers, timeout=5)
            if resp.status_code == 200:
                token = resp.json().get('data', {}).get('token') or resp.json().get('token')
                if token: return token, "🔓 Login (V1)"
        except: pass
            
    return None, "❌ Login Failed (Check Pass)"

# --- ⚡ PROCESS STUDENT ---
def process_student(student, qr_code, agent_index):
    start_time = time.time()
    headers = get_headers(agent_index)
    session = requests.Session()
    safe_name = student.get('name', 'Unknown')
    
    # 1. LOGIN
    token, login_status = get_auth_token(student, session, headers)
    
    if not token:
        return {
            "success": False, 
            "name": safe_name, 
            "step": "Login", 
            "msg": login_status
        }

    # 2. MARK ATTENDANCE
    # Bennett V2 URL
    mark_url = f"{BASE_URL}/v2/instruction/mark_attendance_qr"
    # Fallback V1 URL
    mark_url_v1 = f"{BASE_URL}/api/instruction/mark_attendance_qr"

    auth_headers = headers.copy()
    auth_headers["Authorization"] = f"Bearer {token}"
    
    mark_payload = {
        "qr_code": qr_code,
        "latitude": "28.4505", 
        "longitude": "77.5128"
    }
    
    try:
        time.sleep(0.1)
        
        # Try V2 Mark
        mark_resp = session.post(mark_url, json=mark_payload, headers=auth_headers, timeout=5)
        
        # If V2 fails (404), try V1
        if mark_resp.status_code == 404:
             mark_resp = session.post(mark_url_v1, json=mark_payload, headers=auth_headers, timeout=5)

        duration = round(time.time() - start_time, 2)
        
        # Read Reply
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
    st.set_page_config(page_title="Bennett V2 Bot", page_icon="🎓", layout="centered")
    st.title("🎓 Bennett V2 Bot")
    st.caption("Auto-Login • V2 API • Live Logs")

    tab1, tab2 = st.tabs(["📸 Camera", "📝 Paste"])
    qr_data = None

    with tab1:
        img_buffer = st.camera_input("Scan QR")
        if img_buffer:
            bytes_data = img_buffer.getvalue()
            cv2_img = cv2.imdecode(np.frombuffer(bytes_data, np.uint8), cv2.IMREAD_COLOR)
            detector = cv2.QRCodeDetector()
            data, bbox, _ = detector.detectAndDecode(cv2_img)
            if data:
                qr_data = data
                st.success(f"Captured: {data[:15]}...")

    with tab2:
        qr_text = st.text_input("Paste Manually:")
        if qr_text:
            qr_data = qr_text

    if qr_data:
        if st.button("🚀 LAUNCH ATTENDANCE", type="primary", use_container_width=True):
            if "squad" not in st.secrets:
                st.error("Secrets missing.")
                st.stop()
            
            squad_list = st.secrets["squad"]
            
            st.divider()
            st.write("### 📡 Live Status")
            
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
                        st.error(f"**{res['name']}**\nFailed: {res['msg']}\nReply: {res.get('server_reply', '')}")
