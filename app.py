import streamlit as st
import requests
import cv2
import numpy as np
import concurrent.futures
import time

# ================= CONFIGURATION =================
BASE_URL = "https://student.bennetterp.camu.in"
# =================================================

def get_headers(user_agent_index, target_host=None):
    agents = [
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Mobile Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36"
    ]
    
    # If we are hitting the Global Server, we must pretend to be on the Global Site
    origin = "https://www.camu.in" if target_host == "global" else BASE_URL
    referer = "https://www.camu.in/" if target_host == "global" else f"{BASE_URL}/"

    return {
        "User-Agent": agents[user_agent_index % len(agents)],
        "Content-Type": "application/json",
        "Origin": origin,
        "Referer": referer
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

# --- 🧠 SMART LOGIN (NOW WITH GLOBAL FALLBACK) ---
def get_auth_token(student, session, agent_index):
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
        
        # 1. Try Bennett Server (Might fail with 404)
        try:
            headers = get_headers(agent_index)
            resp = session.post(f"{BASE_URL}/api/login", json=payload, headers=headers, timeout=5)
            if resp.status_code == 200:
                token = resp.json().get('data', {}).get('token') or resp.json().get('token')
                if token: return token, "🔓 Login (Bennett)"
        except: pass

        # 2. Try Global Server (The Backdoor)
        try:
            # We must change headers to look like we are on camu.in
            global_headers = get_headers(agent_index, target_host="global")
            resp = session.post("https://api.camu.in/api/login", json=payload, headers=global_headers, timeout=5)
            if resp.status_code == 200:
                token = resp.json().get('data', {}).get('token') or resp.json().get('token')
                if token: return token, "🔓 Login (Global)"
            else:
                return None, f"❌ Global Login Failed ({resp.status_code})"
        except Exception as e:
            return None, f"⚠️ Error: {str(e)}"
            
    return None, "❌ No Credentials"

# --- ⚡ PROCESS STUDENT ---
def process_student(student, qr_code, agent_index):
    start_time = time.time()
    session = requests.Session()
    safe_name = student.get('name', 'Unknown')
    
    # 1. LOGIN
    token, login_status = get_auth_token(student, session, agent_index)
    
    if not token:
        return {
            "success": False, 
            "name": safe_name, 
            "step": "Login", 
            "msg": login_status
        }

    # 2. MARK ATTENDANCE
    # Bennett URL for marking
    mark_url = f"{BASE_URL}/api/instruction/mark_attendance_qr"
    headers = get_headers(agent_index)
    headers["Authorization"] = f"Bearer {token}"
    
    mark_payload = {
        "qr_code": qr_code,
        "latitude": "28.4505", 
        "longitude": "77.5128"
    }
    
    try:
        time.sleep(0.1)
        mark_resp = session.post(mark_url, json=mark_payload, headers=headers, timeout=5)
        duration = round(time.time() - start_time, 2)
        
        # Server Reply Analysis
        server_reply = "No Reply"
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
        
        # 404 Fallback for Marking (Just in case)
        elif mark_resp.status_code == 404:
             global_mark_url = "https://api.camu.in/api/instruction/mark_attendance_qr"
             headers = get_headers(agent_index, target_host="global") # Switch headers
             headers["Authorization"] = f"Bearer {token}"
             
             fallback_resp = session.post(global_mark_url, json=mark_payload, headers=headers, timeout=5)
             if fallback_resp.status_code == 200:
                 return {
                     "success": True, 
                     "name": safe_name, 
                     "step": "Fallback", 
                     "msg": f"{login_status} ➝ ⚠️ 404 ➝ ✅ Global Marked",
                     "server_reply": "Saved via Global API"
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
    st.set_page_config(page_title="Bennett Verifier", page_icon="🕵️", layout="centered")
    st.title("🕵️ Bennett Attendance Verifier")
    st.caption("Auto-Login • Server Verification • Live Logs")

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
        if st.button("🚀 VERIFY & MARK", type="primary", use_container_width=True):
            if "squad" not in st.secrets:
                st.error("Secrets missing.")
                st.stop()
            
            squad_list = st.secrets["squad"]
            
            st.divider()
            st.write("### 📡 Live Verification Logs")
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                future_to_student = {
                    executor.submit(process_student, student, qr_data, i): student 
                    for i, student in enumerate(squad_list)
                }
                
                for future in concurrent.futures.as_completed(future_to_student):
                    res = future.result()
                    
                    if res['success']:
                        st.success(f"**{res['name']}**")
                        st.code(f"Status: {res['msg']}\nServer Said: \"{res.get('server_reply', 'OK')}\"")
                    else:
                        st.error(f"**{res['name']}**")
                        st.code(f"Failed At: {res.get('step')}\nError: {res['msg']}\nServer Said: \"{res.get('server_reply', 'No Reply')}\"")
