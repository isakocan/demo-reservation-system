from flask import Flask, render_template, request, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta

app = Flask(__name__)

# --- VERİTABANI AYARLARI ---
DB_HOST = "localhost"
DB_NAME = "halisaha_db"
DB_USER = "postgres"
DB_PASS = "0000"  # Şifreni buraya yaz

def get_db_connection():
    try:
        conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)
        return conn
    except Exception as e:
        print(f"Veritabanı bağlantı hatası: {e}")
        return None

# --- 1. ANA SAYFA ---
@app.route('/')
def index():
    return render_template('index.html')

# --- 2. GİRİŞ & KAYIT ---
@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    conn = get_db_connection()
    if not conn: return jsonify({"success": False, "message": "Veritabanı hatası"}), 500
    
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM users WHERE email = %s AND password = %s", (data['email'], data['password']))
    user = cur.fetchone()
    cur.close()
    conn.close()
    
    if user: return jsonify({"success": True, "user": user})
    return jsonify({"success": False, "message": "Hatalı e-posta veya şifre!"}), 401

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    # Mail uzantı kontrolü
    if not data['email'].endswith('@std.yildiz.edu.tr') and not data['email'].endswith('@yildiz.edu.tr'):
         return jsonify({"success": False, "message": "Sadece YTÜ kurumsal maili geçerlidir!"}), 400
    
    conn = get_db_connection()
    if not conn: return jsonify({"success": False, "message": "Veritabanı hatası"}), 500
    
    try:
        cur = conn.cursor()
        cur.execute("""INSERT INTO users (email, password, first_name, last_name, student_id, role) 
                       VALUES (%s, %s, %s, %s, %s, 'student')""",
                    (data['email'], data['password'], data['name'], data['surname'], data['student_id']))
        conn.commit()
        return jsonify({"success": True, "message": "Kayıt başarılı! Giriş yapabilirsiniz."})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": "Bu mail adresi zaten kayıtlı."}), 409
    finally:
        conn.close()

# --- 3. TAKVİM & REZERVASYON VERİLERİ ---
@app.route('/api/reservations', methods=['GET'])
def get_reservations():
    sim_date_str = request.args.get('start_date')
    user_id = request.args.get('user_id')
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # TEMİZLİK: 5 dakikadan eski 'pending' (kilitli) kayıtları sil
    # Eğer kullanıcı sayfayı kapatıp kaçtıysa kilit sonsuza kadar kalmasın diye.
    try:
        cur.execute("DELETE FROM reservations WHERE status = 'pending' AND created_at < NOW() - INTERVAL '5 minutes'")
        conn.commit()
    except Exception as e:
        conn.rollback()
        print("Temizlik hatası (Tablo sütunu eksik olabilir):", e)

    # Sistem Modu Kontrolü (Admin ayarı: Sliding vs Classic)
    cur.execute("SELECT setting_value FROM system_settings WHERE setting_key = 'system_mode'")
    mode_row = cur.fetchone()
    mode = mode_row['setting_value'] if mode_row else 'sliding'
    
    start_date = datetime.strptime(sim_date_str, '%Y-%m-%d').date()
    
    # Eğer Klasik moddaysak, tarihi o haftanın Pazartesi gününe sabitleriz
    if mode == 'classic':
        start_date = start_date - timedelta(days=start_date.weekday()) 

    # 7 Günlük Randevuları Çek
    cur.execute("""
        SELECT r.*, u.first_name, u.last_name 
        FROM reservations r
        LEFT JOIN users u ON r.user_id = u.id
        WHERE reservation_date >= %s AND reservation_date < (DATE %s + INTERVAL '7 days')
    """, (start_date, start_date))
    reservations = cur.fetchall()

    # Kullanıcının Alarmlarını Çek
    my_alarms = []
    if user_id and user_id != 'null':
        cur.execute("SELECT alarm_date, time_slot FROM alarms WHERE user_id = %s", (user_id,))
        alarms_raw = cur.fetchall()
        for a in alarms_raw:
            d_str = a['alarm_date'].strftime('%Y-%m-%d')
            my_alarms.append(f"{d_str}_{a['time_slot']}") 

    # Veriyi Frontend İçin İşle
    processed_data = []
    for res in reservations:
        is_mine = str(res['user_id']) == str(user_id)
        
        display = "DOLU"
        if res['status'] == 'pending':
            display = "SEÇİLİYOR" # Başkası bakıyorsa
            if is_mine: display = "SEÇTİNİZ" # Ben bakıyorsam
        elif is_mine: 
            display = "SİZİN"
        elif res['status'] == 'maintenance': 
            display = "BAKIMDA"

        processed_data.append({
            "id": res['id'],
            "reservation_date": res['reservation_date'].strftime('%Y-%m-%d'),
            "time_slot": res['time_slot'],
            "status": res['status'],
            "display_name": display,
            "is_mine": is_mine
        })

    cur.close()
    conn.close()
    
    return jsonify({
        "reservations": processed_data,
        "my_alarms": my_alarms,
        "system_mode": mode
    })

# --- 4. KİLİTLEME SİSTEMİ (LOCK / UNLOCK) ---
@app.route('/api/lock', methods=['POST'])
def lock_slot():
    data = request.json
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Önce o saatte aktif veya pending bir rezervasyon var mı bak
        cur.execute("SELECT id FROM reservations WHERE reservation_date=%s AND time_slot=%s AND (status='active' OR status='pending')", 
                    (data['date'], data['time_slot']))
        if cur.fetchone():
            return jsonify({"success": False, "message": "Maalesef az önce doldu veya seçildi!"}), 409

        # Yoksa 'pending' olarak kilitle
        cur.execute("INSERT INTO reservations (user_id, reservation_date, time_slot, status) VALUES (%s, %s, %s, 'pending')",
                    (data['user_id'], data['date'], data['time_slot']))
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        conn.close()

@app.route('/api/unlock', methods=['POST'])
def unlock_slot():
    data = request.json
    conn = get_db_connection()
    # Sadece kendi koyduğu 'pending' kilidini kaldırabilir
    conn.cursor().execute("DELETE FROM reservations WHERE user_id=%s AND reservation_date=%s AND time_slot=%s AND status='pending'",
                          (data['user_id'], data['date'], data['time_slot']))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

# --- 5. RANDEVU İŞLEMLERİ ---
@app.route('/api/reserve', methods=['POST'])
def reserve():
    data = request.json
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Kota kontrolü (Sadece 'active' olanları say, pending sayılmaz)
        cur.execute("SELECT COUNT(*) FROM reservations WHERE user_id = %s AND status='active'", (data['user_id'],))
        if cur.fetchone()[0] >= 2: 
            return jsonify({"success": False, "message": "Haftalık kota (2 saat) doldu."}), 400
        
        # Pending olan kaydı Active yap (Kilidi kalıcıya çevir)
        cur.execute("""
            UPDATE reservations SET status = 'active' 
            WHERE user_id = %s AND reservation_date = %s AND time_slot = %s AND status = 'pending'
        """, (data['user_id'], data['date'], data['time_slot']))
        
        if cur.rowcount == 0:
            # Eğer pending kaydı yoksa (zaman aşımı vs.) sıfırdan insert dene
             cur.execute("INSERT INTO reservations (user_id, reservation_date, time_slot, status) VALUES (%s, %s, %s, 'active')",
                    (data['user_id'], data['date'], data['time_slot']))

        conn.commit()
        return jsonify({"success": True, "message": "Randevu başarıyla alındı!"})
    except: 
        conn.rollback()
        return jsonify({"success": False, "message": "Hata oluştu veya başkası aldı."}), 409
    finally: conn.close()

@app.route('/api/cancel', methods=['POST'])
def cancel_reservation():
    data = request.json
    res_id = data.get('reservation_id')
    sim_date_str = data.get('simulation_date')
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("SELECT reservation_date FROM reservations WHERE id=%s", (res_id,))
    res = cur.fetchone()
    if not res: 
        return jsonify({"success": False, "message": "Randevu bulunamadı"}), 404
    
    match_date = res['reservation_date']
    sim_date = datetime.strptime(sim_date_str, '%Y-%m-%d').date()
    
    if match_date <= (sim_date + timedelta(days=1)):
        return jsonify({"success": False, "message": "Maça 24 saatten az kaldığı için iptal edilemez!"}), 400
        
    cur.execute("DELETE FROM reservations WHERE id=%s", (res_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "Randevu iptal edildi."})

@app.route('/api/maintenance', methods=['POST'])
def toggle_maintenance():
    data = request.json
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("SELECT id FROM reservations WHERE reservation_date=%s AND time_slot=%s", (data['date'], data['time_slot']))
    existing = cur.fetchone()
    
    if existing: 
        cur.execute("DELETE FROM reservations WHERE id=%s", (existing[0],))
    else: 
        cur.execute("INSERT INTO reservations (user_id, reservation_date, time_slot, status) VALUES (%s, %s, %s, 'maintenance')",
                      (data['user_id'], data['date'], data['time_slot']))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

# --- 6. ALARM SİSTEMİ ---
@app.route('/api/alarm', methods=['POST'])
def set_alarm():
    data = request.json
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO alarms (user_id, alarm_date, time_slot) VALUES (%s, %s, %s)",
                    (data['user_id'], data['date'], data.get('time_slot')))
        conn.commit()
        return jsonify({"success": True, "message": "Alarm kuruldu. Yer açılınca bildirim alacaksınız."})
    except: 
        conn.rollback()
        return jsonify({"success": False, "message": "Bu alarm zaten kurulu."}), 500
    finally: 
        conn.close()

@app.route('/api/notifications', methods=['GET'])
def check_notifications():
    user_id = request.args.get('user_id')
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("SELECT * FROM alarms WHERE user_id = %s AND is_notified = FALSE", (user_id,))
    my_alarms = cur.fetchall()
    
    triggered = []
    for a in my_alarms:
        sql = "SELECT id FROM reservations WHERE reservation_date = %s"
        params = [a['alarm_date']]
        if a['time_slot'] is not None:
            sql += " AND time_slot = %s"
            params.append(a['time_slot'])
            
        cur.execute(sql, tuple(params))
        is_full = cur.fetchone()
        
        if not is_full: 
            triggered.append({
                "date": a['alarm_date'].strftime('%Y-%m-%d'), 
                "slot": a['time_slot'] or "Tüm Gün"
            })
            cur.execute("UPDATE alarms SET is_notified = TRUE WHERE id = %s", (a['id'],))
            conn.commit()
            
    conn.close()
    return jsonify(triggered)

# --- 7. İLAN PANOSU ---
@app.route('/api/board', methods=['GET', 'POST', 'DELETE'])
def bulletin_board():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    if request.method == 'GET':
        cur.execute("""SELECT b.*, u.first_name, u.last_name FROM bulletin_board b 
                       JOIN users u ON b.user_id = u.id ORDER BY b.created_at DESC""")
        posts = cur.fetchall()
        conn.close()
        return jsonify(posts)
        
    if request.method == 'POST':
        data = request.json
        cur.execute("INSERT INTO bulletin_board (user_id, title, message, contact_info) VALUES (%s, %s, %s, %s)",
                    (data['user_id'], data['title'], data['message'], data['contact']))
        conn.commit()
        conn.close()
        return jsonify({"success": True})

    if request.method == 'DELETE':
        post_id = request.args.get('id')
        cur.execute("DELETE FROM bulletin_board WHERE id = %s", (post_id,))
        conn.commit()
        conn.close()
        return jsonify({"success": True})

# --- 8. SİSTEM AYARLARI ---
@app.route('/api/settings', methods=['POST'])
def update_settings():
    conn = get_db_connection()
    mode = request.json['mode']
    conn.cursor().execute("UPDATE system_settings SET setting_value = %s WHERE setting_key = 'system_mode'", (mode,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

# --- UYGULAMAYI BAŞLAT ---
if __name__ == '__main__':
    app.run(debug=True)