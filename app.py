import streamlit as st
import requests
import cv2
import numpy as np
import concurrent.futures
import time

# ================= CONFIGURATION =================
# ⚠️ VERIFY: Log in to Camu on Chrome -> F12 -> Network -> Look at the 'login' request URL.
# If it says 'api.camu.in', keep this. If it says 'mycollege.camu.in', CHANGE IT.
BASE_URL = "https://api.camu.in" 
# =================================================

# --- 🕵️‍♂️ STEALTH HEADERS (Rotates ID to look like different phones) ---
def get_headers(user_agent_index):
    agents = [
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Mobile Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
    ]
    return {
        "User-Agent": agents[user_agent_index % len(agents)],
        "Content-Type": "application/json",
        "Origin": "https://www.camu.in",  # 🛡️ Anti-Block Header
        "Referer": "https://www.camu.in/"
    }

# --- 🔐 PASSWORD PROTECTION ---
def check_password():
    """Forces user to enter password before seeing the app."""
    if "APP_PASSWORD" not in st.secrets:
        st.warning("⚠️ Config Error: No 'APP_PASSWORD' found in Streamlit Secrets.")
        return True # Allow access for debugging if no password set

    def password_entered():
        if st.session_state["password"] == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("Enter Squad Password", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("Enter Squad Password", type="password", on_change=password_entered, key="password")
        st.error("❌ Access Denied")
        return False
    else:
        return True

# --- ⚙️ THE ATTENDANCE ENGINE ---
def process_student(student, qr_code, agent_index):
    start_time = time.time()
    headers = get_headers(agent_index)
    
    try:
        session = requests.Session()
        
        # 1. LOGIN
        login_url = f"{BASE_URL}/api/login"
        login_payload = {
            "username": student['user'], 
            "password": student['pass'],
            "user_type": "Student"
        }
        
        # Attempt Login with 5s timeout
        resp = session.post(login_url, json=login_payload, headers=headers, timeout=5)
        
        if resp.status_code != 200:
            return {"success": False, "name": student['name'], "msg": f"Login Failed ({resp.status_code})"}

        data = resp.json()
        
        # 2. FIND TOKEN (Handles different API response formats)
        token = None
        if 'data' in data and 'token' in data['data']:
            token = data['data']['token']
        elif 'token' in data:
            token = data['token']
        elif 'access_token' in data:
            token = data['access_token']
            
        if not token:
            return {"success": False, "name": student['name'], "msg": "Login OK, but No Token Found."}

        # 3. HUMAN DELAY (100ms)
        time.sleep(0.1) 

        # 4. FIRE ATTENDANCE
        mark_url = f"{BASE_URL}/api/instruction/mark_attendance_qr"
        auth_headers = headers.copy()
        auth_headers["Authorization"] = f"Bearer {token}"
        
        mark_payload = {
            "qr_code": qr_code,
            "latitude": "28.4744", # Greater Noida Coords
            "longitude": "77.5040"
        }
        
        mark_resp = session.post(mark_url, json=mark_payload, headers=auth_headers, timeout=5)
        duration = round(time.time() - start_time, 2)
        
        if mark_resp.status_code == 200:
            return {"success": True, "name": student['name'], "msg": f"MARKED in {duration}s", "status": 200}
        else:
            return {"success": False, "name": student['name'], "msg": f"Failed ({mark_resp.status_code})", "status": mark_resp.status_code}

    except Exception as e:
        return {"success": False, "name": student['name'], "msg": str(e)}

# --- 📱 THE USER INTERFACE ---
if check_password():
    st.set_page_config(page_title="Squad Bot", page_icon="⚡", layout="centered")
    st.title("⚡ Squad Auto-Attendance")
    st.markdown("`System: Online` | `Speed: Turbo`")

    # TABS for Input
    tab1, tab2 = st.tabs(["📸 Camera Scan", "📝 Paste Code"])
    qr_data = None

    with tab1:
        st.caption("Tap 'Take Photo'. Use your phone's native zoom if needed.")
        img_buffer = st.camera_input("Scan QR")
        
        if img_buffer:
            # Convert photo to format OpenCV can read
            bytes_data = img_buffer.getvalue()
            cv2_img = cv2.imdecode(np.frombuffer(bytes_data, np.uint8), cv2.IMREAD_COLOR)
            
            # Detect QR Code
            detector = cv2.QRCodeDetector()
            data, bbox, _ = detector.detectAndDecode(cv2_img)
            
            if data:
                qr_data = data
                st.success(f"🎯 QR Captured: `{qr_data[:20]}...`")
            else:
                st.warning("❌ No QR code detected. Try moving closer or use 'Paste Code' tab.")

    with tab2:
        qr_text = st.text_input("Paste QR text manually:")
        if qr_text:
            qr_data = qr_text

    # EXECUTION BUTTON
    if qr_data:
        if st.button("🚀 MARK EVERYONE NOW", type="primary", use_container_width=True):
            
            # Load Squad from Secrets
            if "squad" not in st.secrets:
                st.error("❌ Error: Squad list is missing from server secrets.")
                st.stop()
            
            squad_list = st.secrets["squad"]
            
            # Status Box
            with st.status("🔄 Processing Squad...", expanded=True) as status:
                results = []
                
                # Run all logins in PARALLEL (Max 5 at a time)
                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                    future_to_student = {
                        executor.submit(process_student, student, qr_data, i): student 
                        for i, student in enumerate(squad_list)
                    }
                    
                    for future in concurrent.futures.as_completed(future_to_student):
                        res = future.result()
                        results.append(res)
                        if res['success']:
                            st.write(f"✅ {res['name']}")
                        else:
                            st.write(f"❌ {res['name']}")
                
                status.update(label="✅ Mission Complete", state="complete", expanded=False)

            # Final Report
            st.divider()
            for res in results:
                if res['success']:
                    st.success(f"**{res['name']}**: {res['msg']}")
                else:
                    st.error(f"**{res['name']}**: {res['msg']}")