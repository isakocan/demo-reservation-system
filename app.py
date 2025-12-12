from flask import Flask, render_template, request, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta

app = Flask(__name__)

# --- VERİTABANI AYARLARI ---
DB_HOST = "localhost"
DB_NAME = "halisaha_db"
DB_USER = "postgres"
DB_PASS = "0000"  # <-- ŞİFRENİZİ BURAYA YAZIN

def get_db_connection():
    conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)
    return conn

# 1. ANA SAYFA
@app.route('/')
def index():
    return render_template('index.html')

# 2. GİRİŞ VE KAYIT (AUTH)
@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM users WHERE email = %s AND password = %s", (data['email'], data['password']))
    user = cur.fetchone()
    cur.close()
    conn.close()
    
    if user:
        return jsonify({"success": True, "user": user})
    return jsonify({"success": False, "message": "Hatalı bilgiler!"}), 401

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    if not data['email'].endswith('@std.yildiz.edu.tr') and not data['email'].endswith('@yildiz.edu.tr'):
         return jsonify({"success": False, "message": "Sadece YTÜ kurumsal maili geçerlidir!"}), 400
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""INSERT INTO users (email, password, first_name, last_name, student_id, role) 
                       VALUES (%s, %s, %s, %s, %s, 'student')""",
                    (data['email'], data['password'], data['name'], data['surname'], data['student_id']))
        conn.commit()
        return jsonify({"success": True, "message": "Kayıt başarılı!"})
    except Exception as e:
        return jsonify({"success": False, "message": "Bu mail zaten kayıtlı."}), 409
    finally:
        if conn: conn.close()

# 3. TAKVİM VERİLERİ (GİZLİLİK VE MOD YÖNETİMİ)
@app.route('/api/reservations', methods=['GET'])
def get_reservations():
    sim_date_str = request.args.get('start_date') # Simülasyon Tarihi
    user_id = request.args.get('user_id') # Kimin gözünden bakıyoruz? (Gizlilik için)
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # 1. Sistem Modunu Kontrol Et (Kayar mı, Klasik mi?)
    cur.execute("SELECT setting_value FROM system_settings WHERE setting_key = 'system_mode'")
    mode = cur.fetchone()['setting_value'] # 'sliding' veya 'classic'
    
    start_date = datetime.strptime(sim_date_str, '%Y-%m-%d').date()
    
    # Eğer Klasik Mod ise ve bugün Pazartesi değilse, takvim en son Pazartesi'den başlar (veya o haftayı gösterir)
    if mode == 'classic':
        # (Demo basitliği: Klasik modda başlangıç gününü o haftanın Pazartesi'si yapıyoruz)
        start_date = start_date - timedelta(days=start_date.weekday())

    # Verileri Çek
    cur.execute("""
        SELECT r.*, u.first_name, u.last_name, u.email 
        FROM reservations r
        LEFT JOIN users u ON r.user_id = u.id
        WHERE reservation_date >= %s AND reservation_date < (DATE %s + INTERVAL '7 days')
    """, (start_date, start_date))
    reservations = cur.fetchall()
    
    # 2. GİZLİLİK FİLTRESİ (Privacy Layer)
    # Backend veriyi maskeleyerek göndermeli
    processed_data = []
    for res in reservations:
        is_mine = str(res['user_id']) == str(user_id)
        is_admin = False # (Burada admin kontrolü yapılabilir ama demo için basit tutuyoruz)
        
        # İsim Gizleme Mantığı
        display_name = "DOLU"
        if is_mine:
            display_name = "SİZİN"
        elif res['status'] == 'maintenance':
            display_name = "BAKIMDA"
        # Not: Admin ise frontend'de 'admin' rolüyle her şeyi görecek, 
        # ama burada veri güvenliği için normal kullanıcıya "Ahmet" ismini göndermiyoruz.
        
        processed_data.append({
            "id": res['id'],
            "reservation_date": res['reservation_date'].strftime('%Y-%m-%d'),
            "time_slot": res['time_slot'],
            "status": res['status'],
            "display_name": display_name,
            "real_name": f"{res['first_name']} {res['last_name']}" if is_mine else "", # Sadece kendine görünür
            "is_mine": is_mine
        })

    cur.close()
    conn.close()
    return jsonify(processed_data)

# 4. RANDEVU AL
@app.route('/api/reserve', methods=['POST'])
def reserve():
    data = request.json
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Kota Kontrolü (Haftada 2)
        cur.execute("SELECT COUNT(*) FROM reservations WHERE user_id = %s AND status='active'", (data['user_id'],))
        if cur.fetchone()[0] >= 2:
            return jsonify({"success": False, "message": "Haftalık kotanız (2 saat) dolmuştur."}), 400

        cur.execute("INSERT INTO reservations (user_id, reservation_date, time_slot) VALUES (%s, %s, %s)",
                    (data['user_id'], data['date'], data['time_slot']))
        conn.commit()
        return jsonify({"success": True, "message": "Rezervasyon başarılı!"})
    except:
        return jsonify({"success": False, "message": "Bu saat az önce alındı!"}), 409
    finally:
        conn.close()

# 5. İPTAL ET (24 SAAT KURALI)
@app.route('/api/cancel', methods=['POST'])
def cancel_reservation():
    data = request.json
    res_id = data.get('reservation_id')
    sim_date_str = data.get('simulation_date') # Şu anki "sanal" bugün
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Randevu Tarihini Bul
    cur.execute("SELECT reservation_date, time_slot FROM reservations WHERE id = %s", (res_id,))
    res = cur.fetchone()
    
    if not res:
        return jsonify({"success": False, "message": "Randevu bulunamadı."}), 404
        
    # Kural Kontrolü
    res_date = res['reservation_date'] # datetime.date
    sim_date = datetime.strptime(sim_date_str, '%Y-%m-%d').date()
    
    # Eğer maç bugünden 1 gün sonrasından daha yakınsa iptal edilemez (Örn: Maç yarın, bugün iptal yok)
    # Demo mantığı: Maç tarihi <= (Bugün + 1 gün) ise iptal yasak.
    limit_date = sim_date + timedelta(days=1)
    
    if res_date <= limit_date:
        return jsonify({"success": False, "message": "Maça 24 saatten az kaldığı için iptal edilemez!"}), 400
        
    # Silme İşlemi
    cur.execute("DELETE FROM reservations WHERE id = %s", (res_id,))
    conn.commit()
    
    # Not: Burada alarm tetiklemiyoruz. Polling sistemi (aşağıda) boşluğu otomatik fark edecek.
    
    cur.close()
    conn.close()
    return jsonify({"success": True, "message": "Randevu iptal edildi. Ücret iadeniz yapılacaktır."})

# 6. BAKIM MODU (Admin)
@app.route('/api/maintenance', methods=['POST'])
def toggle_maintenance():
    data = request.json
    conn = get_db_connection()
    cur = conn.cursor()
    # Varsa sil, yoksa ekle
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

# 7. ALARM KURMA
@app.route('/api/alarm', methods=['POST'])
def set_alarm():
    data = request.json
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO alarms (user_id, alarm_date, time_slot) VALUES (%s, %s, %s)",
                    (data['user_id'], data['date'], data.get('time_slot')))
        conn.commit()
        return jsonify({"success": True, "message": "Alarm kuruldu. Yer açılırsa bildirim alacaksınız."})
    except:
        return jsonify({"success": False, "message": "Hata oluştu."}), 500
    finally:
        conn.close()

# 8. CANLI BİLDİRİM KONTROLÜ (POLLING) - EN KRİTİK YER
@app.route('/api/notifications', methods=['GET'])
def check_notifications():
    user_id = request.args.get('user_id')
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Mantık: 
    # 1. Kullanıcının henüz bildirim almadığı (is_notified=False) alarmlarını bul.
    # 2. Bu alarmların tarih/saatlerinde 'reservation' tablosunda kayıt VAR MI diye bak.
    # 3. Eğer kayıt YOKSA (yani boşalmışsa), bildirim gönder ve alarmı 'notified' yap.
    
    cur.execute("""
        SELECT a.id, a.alarm_date, a.time_slot 
        FROM alarms a
        WHERE a.user_id = %s AND a.is_notified = FALSE
    """, (user_id,))
    my_alarms = cur.fetchall()
    
    triggered_alarms = []
    
    for alarm in my_alarms:
        # Bu saat şu an dolu mu?
        sql = "SELECT id FROM reservations WHERE reservation_date = %s"
        params = [alarm['alarm_date']]
        
        if alarm['time_slot'] is not None:
            sql += " AND time_slot = %s"
            params.append(alarm['time_slot'])
            
        cur.execute(sql, tuple(params))
        is_full = cur.fetchone()
        
        # EĞER DOLU DEĞİLSE (is_full None ise) -> YER AÇILMIŞ DEMEKTİR!
        if not is_full:
            triggered_alarms.append({
                "date": alarm['alarm_date'].strftime('%Y-%m-%d'),
                "slot": alarm['time_slot'] if alarm['time_slot'] else "Tüm Gün"
            })
            # Bildirimi okundu işaretle
            cur.execute("UPDATE alarms SET is_notified = TRUE WHERE id = %s", (alarm['id'],))
            conn.commit()
    
    cur.close()
    conn.close()
    return jsonify(triggered_alarms)

# 9. İLAN PANOSU (BOARD)
@app.route('/api/board', methods=['GET', 'POST'])
def bulletin_board():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    if request.method == 'GET':
        cur.execute("""
            SELECT b.*, u.first_name, u.last_name 
            FROM bulletin_board b
            JOIN users u ON b.user_id = u.id
            ORDER BY b.created_at DESC
        """)
        posts = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify(posts)
        
    if request.method == 'POST':
        data = request.json
        cur.execute("INSERT INTO bulletin_board (user_id, title, message, contact_info) VALUES (%s, %s, %s, %s)",
                    (data['user_id'], data['title'], data['message'], data['contact']))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True, "message": "İlan eklendi."})

# 10. SİSTEM AYARLARI (ADMIN)
@app.route('/api/settings', methods=['POST'])
def update_settings():
    data = request.json
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE system_settings SET setting_value = %s WHERE setting_key = 'system_mode'", (data['mode'],))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "Sistem modu güncellendi."})

if __name__ == '__main__':
    app.run(debug=True)