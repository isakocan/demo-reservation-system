// --- AYARLAR & DURUMLAR ---
let currentUser = null;
let currentTimeGroup = "evening"; // 'day' (12-18) veya 'evening' (18-24)
let selectedDate = null;
let selectedSlot = null;
let currentResId = null;

// Hava Durumu Verileri (Statik Simülasyon)
const weatherData = {
  1: { emoji: "🌧️", text: "Yağmurlu", temp: "14°C" },
  2: { emoji: "⛅", text: "Parçalı", temp: "16°C" },
  3: { emoji: "☀️", text: "Güneşli", temp: "19°C" },
  4: { emoji: "💨", text: "Rüzgarlı", temp: "15°C" },
  5: { emoji: "☁️", text: "Bulutlu", temp: "15°C" },
  6: { emoji: "🌩️", text: "Fırtına", temp: "13°C" },
  0: { emoji: "☀️", text: "Açık", temp: "18°C" },
};
const daysName = ["Paz", "Pzt", "Sal", "Çar", "Per", "Cum", "Cmt"];

// --- BAŞLANGIÇ (ONLOAD) ---
window.onload = () => {
  // SessionStorage kullanarak her sekmeyi ayrı oturum gibi yönetiyoruz
  const storedUser = sessionStorage.getItem("user");
  
  if (storedUser) {
    currentUser = JSON.parse(storedUser);
    showDashboard();
  }
  
  // Tarih kutusunu bugüne ayarla
  if(document.getElementById("sim-date")){
      document.getElementById("sim-date").valueAsDate = new Date();
  }

  if (currentUser) renderCalendar();

  // Bildirimleri kontrol et (4 saniyede bir)
  setInterval(checkNotifications, 4000);
  
  // Takvimi güncelle (5 saniyede bir) - Sayfa yenilemeden durumları (Pending/Dolu) görmek için
  setInterval(() => {
    if (currentUser) {
       renderCalendar(true); // true = sessiz mod (Yükleniyor yazısı çıkmaz)
    }
  }, 5000);
};

// --- KULLANICI İŞLEMLERİ ---
function toggleAuth() {
  document.getElementById("login-form").classList.toggle("d-none");
  document.getElementById("register-form").classList.toggle("d-none");
}

async function login() {
  const email = document.getElementById("login-email").value;
  const pass = document.getElementById("login-pass").value;
  
  try {
      const res = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email, password: pass }),
      });
      const data = await res.json();
      if (data.success) {
        currentUser = data.user;
        sessionStorage.setItem("user", JSON.stringify(currentUser));
        showDashboard();
        renderCalendar();
      } else {
          alert(data.message);
      }
  } catch (err) {
      console.error("Giriş hatası:", err);
      alert("Sunucuya bağlanılamadı.");
  }
}

function logout() {
  sessionStorage.removeItem("user");
  location.reload();
}

function showDashboard() {
  document.getElementById("auth-screen").classList.add("d-none");
  document.getElementById("dashboard").classList.remove("d-none");
  document.getElementById("user-name").innerText =
    currentUser.first_name + " " + currentUser.last_name;
  document.getElementById("user-role").innerText =
    currentUser.role === "admin" ? "YÖNETİCİ" : "ÖĞRENCİ";
  
  if (currentUser.role === "admin") {
    const adminPanel = document.getElementById("admin-panel");
    if(adminPanel) {
        adminPanel.classList.remove("d-none");
        adminPanel.classList.add("d-flex");
    }
  }
}

async function register() {
  const payload = {
    name: document.getElementById("reg-name").value,
    surname: document.getElementById("reg-surname").value,
    student_id: document.getElementById("reg-student-id").value,
    email: document.getElementById("reg-email").value,
    password: document.getElementById("reg-pass").value,
  };
  const res = await fetch("/api/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  alert(data.message);
  if (data.success) toggleAuth();
}

// --- TAKVİM KONTROLLERİ ---
function setTimeGroup(group) {
  currentTimeGroup = group;
  if (group === "day") {
    document.getElementById("btn-day").className = "btn btn-sm btn-warning fw-bold";
    document.getElementById("btn-evening").className = "btn btn-sm btn-light text-muted";
  } else {
    document.getElementById("btn-day").className = "btn btn-sm btn-light text-muted";
    document.getElementById("btn-evening").className = "btn btn-sm btn-dark fw-bold";
  }
  renderCalendar();
}

function changeDate(days) {
  const dateInput = document.getElementById("sim-date");
  const current = new Date(dateInput.value);
  current.setDate(current.getDate() + days);
  dateInput.valueAsDate = current;
  renderCalendar();
}

async function handleModeSwitch() {
  const switchEl = document.getElementById("modeSwitch");
  const newMode = switchEl.checked ? "sliding" : "classic";
  document.getElementById("modeLabel").innerText = switchEl.checked
    ? "Kayan Mod"
    : "Klasik Mod";
  await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode: newMode }),
  });
  renderCalendar();
}

// --- TAKVİM RENDER (ÇİZİM) ---
async function renderCalendar(silentMode = false) {
  const dateVal = document.getElementById("sim-date").value;
  const grid = document.getElementById("calendar-grid");
  
  if (!silentMode) {
      grid.innerHTML = '<div class="text-center p-5 w-100">Yükleniyor...</div>';
  }

  try {
      const res = await fetch(
        `/api/reservations?start_date=${dateVal}&user_id=${currentUser.id}`
      );
      const data = await res.json();
      
      // Admin Switch Durumunu Güncelle
      if (currentUser && currentUser.role === "admin") {
          const switchEl = document.getElementById("modeSwitch");
          const labelEl = document.getElementById("modeLabel");
          if(switchEl && labelEl) {
              if (data.system_mode === 'classic') {
                  switchEl.checked = false;
                  labelEl.innerText = "Klasik Mod";
              } else {
                  switchEl.checked = true;
                  labelEl.innerText = "Kayan Mod";
              }
          }
      }

      const reservations = data.reservations;
      const myAlarms = data.my_alarms || [];

      grid.innerHTML = "";
      const startDate = new Date(dateVal);

      let startH = 18, endH = 24;
      if (currentTimeGroup === "day") {
        startH = 12;
        endH = 18;
      }

      for (let i = 0; i < 7; i++) {
        let d = new Date(startDate);
        d.setDate(startDate.getDate() + i);
        let dateStr = d.toISOString().split("T")[0];
        let dayIdx = d.getDay();
        let w = weatherData[dayIdx];

        let col = document.createElement("div");
        col.className = "col day-column";

        let dayAlarmActive = myAlarms.includes(`${dateStr}_None`);
        let bellClass = dayAlarmActive ? "header-alarm-active" : "";

        col.innerHTML = `
          <div class="day-header">
              <div class="weather-bg-icon">${w.emoji}</div>
              <div class="day-title">${daysName[dayIdx]}</div>
              <div class="day-date">${d.getDate()}.${d.getMonth() + 1}</div>
              <button class="btn-alarm-header ${bellClass}" onclick="openAlarmModal('${dateStr}', null)">
                  <i class="fa-solid fa-bell"></i>
              </button>
          </div>
        `;

        for (let h = startH; h < endH; h++) {
          let booking = reservations.find(
            (r) => r.reservation_date === dateStr && r.time_slot === h
          );
          let slotDiv = document.createElement("div");
          let contentHTML = "";
          let statusClass = "slot-bos";

          let slotAlarmKey = `${dateStr}_${h}`;
          let hasAlarm = myAlarms.includes(slotAlarmKey);
          let alarmBadge = hasAlarm
            ? `<div class="alarm-badge"><i class="fa-solid fa-bell"></i></div>`
            : "";

          if (booking) {
            // DURUM KONTROLLERİ (Pending, Active, Maintenance)
            if (booking.status === "pending") {
                if(booking.is_mine) {
                    statusClass = "slot-pending-mine"; // Benim seçimim
                    contentHTML = `<span>SEÇTİNİZ...</span>`;
                } else {
                    statusClass = "slot-pending"; // Başkası seçiyor
                    contentHTML = `<span>SEÇİLİYOR</span>`;
                }
            } else if (booking.is_mine) {
              statusClass = "slot-sizin";
              contentHTML = `<span>${booking.display_name}</span>`;
            } else if (booking.status === "maintenance") {
              statusClass = "slot-bakim";
              contentHTML = `<span>BAKIMDA</span>`;
            } else {
              statusClass = "slot-dolu";
              contentHTML = `<span>DOLU</span>`;
            }
            contentHTML += alarmBadge;
          } else {
            // BOŞ SLOT
            statusClass = "slot-bos";
            contentHTML = `
              <span>Boş</span>
              <div class="weather-small text-muted">
                  ${w.emoji} ${w.temp}
              </div>
            `;
          }

          slotDiv.className = `time-slot ${statusClass}`;
          slotDiv.innerHTML = `<strong>${h}:00 - ${h + 1}:00</strong>${contentHTML}`;
          slotDiv.onclick = () => handleSlotClick(dateStr, h, booking, w);
          col.appendChild(slotDiv);
        }
        grid.appendChild(col);
      }
  } catch (error) {
      console.error("Takvim güncellenirken hata:", error);
  }
}

// --- TIKLAMA VE KİLİTLEME MANTIĞI ---
async function handleSlotClick(date, slot, booking, weather) {
  selectedDate = date;
  selectedSlot = slot;

  // 1. Admin ise Bakım Modunu Aç/Kapa
  if (currentUser.role === "admin") {
    toggleMaintenance();
    return;
  }

  // 2. Dolu veya Kilitli Bir Yere Tıklanırsa
  if (booking) {
    if (booking.is_mine) {
        if(booking.status === 'pending') {
             // Kendi seçtiğim yere tekrar tıkladım, işlem yapma (zaten modal açık olmalı)
             return;
        }
      // Kendi aldığım randevuyu iptal et
      currentResId = booking.id;
      new bootstrap.Modal(document.getElementById("modalCancel")).show();
      
    } else if (booking.status === "active") {
      // Başkasının dolu randevusu -> Alarm kur
      new bootstrap.Modal(document.getElementById("modalAlarm")).show();
      
    } else if (booking.status === "pending") {
        // Başkası kilitlediği için tıklanamaz
        alert("Bu saat şu an başka bir kullanıcı tarafından seçiliyor. Lütfen bekleyin.");
    }
  } else {
    // 3. BOŞ BİR YERE TIKLANDI -> KİLİTLE (LOCK)
    try {
        const res = await fetch("/api/lock", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              user_id: currentUser.id,
              date: selectedDate,
              time_slot: selectedSlot,
            }),
        });
        const data = await res.json();
        
        if (data.success) {
            // Kilit başarılı -> Modalı Aç
            document.getElementById("res-detail-text").innerText = `${date} | ${slot}:00`;
            document.getElementById("weather-modal-info").innerText = `Hava Durumu: ${weather.text} (${weather.temp})`;
            
            const modalEl = document.getElementById("modalReserve");
            const modalInstance = new bootstrap.Modal(modalEl);
            modalInstance.show();
            
            // Modal kapandığında (Vazgeçilirse) kilidi kaldıracak Listener ekle
            modalEl.addEventListener('hidden.bs.modal', onModalClose, { once: true });
            
            // Kullanıcıya anında geri bildirim vermek için takvimi yenile ("SEÇTİNİZ" yazsın)
            renderCalendar(true); 
        } else {
            // Kilit başarısız (Aynı anda başkası tıkladı)
            alert(data.message);
            renderCalendar(true);
        }
    } catch (e) {
        console.error("Lock hatası:", e);
        alert("İşlem sırasında bir hata oluştu.");
    }
  }
}

// --- MODAL KAPANINCA KİLİDİ KALDIR ---
async function onModalClose() {
    // Modal kapandığında, eğer işlem tamamlanmadıysa (pending ise) kilidi kaldır.
    // Backend'deki /api/unlock sadece 'pending' durumundakini siler.
    // Eğer 'confirmReserve' çalıştıysa durum 'active' olmuştur, silinmez. Güvenli.
    try {
        await fetch("/api/unlock", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              user_id: currentUser.id,
              date: selectedDate,
              time_slot: selectedSlot,
            }),
        });
        renderCalendar(true); // Rengi normale döndür
    } catch (e) {
        console.error("Unlock hatası:", e);
    }
}

// --- DİĞER MODAL İŞLEMLERİ ---
function openAlarmModal(date, slot) {
  selectedDate = date;
  selectedSlot = slot;
  new bootstrap.Modal(document.getElementById("modalAlarm")).show();
}

// --- API ÇAĞRILARI (RESERVE, CANCEL, ALARM) ---
async function confirmReserve() {
  // Pending olan rezervasyonu Active yap
  try {
      const res = await fetch("/api/reserve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: currentUser.id,
          date: selectedDate,
          time_slot: selectedSlot,
        }),
      });
      const data = await res.json();
      
      // Modalı kapat
      const modalEl = document.getElementById("modalReserve");
      const modal = bootstrap.Modal.getInstance(modalEl);
      if(modal) modal.hide();
      
      alert(data.message);
      if (data.success) renderCalendar();
      
  } catch (e) {
      console.error(e);
      alert("Rezervasyon sırasında hata oluştu.");
  }
}

async function cancelReservation() {
  try {
      const res = await fetch("/api/cancel", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          reservation_id: currentResId,
          simulation_date: document.getElementById("sim-date").value,
        }),
      });
      const data = await res.json();
      
      const modal = bootstrap.Modal.getInstance(document.getElementById("modalCancel"));
      if(modal) modal.hide();
      
      alert(data.message);
      if (data.success) renderCalendar();
  } catch (e) {
      alert("İptal işleminde hata oluştu.");
  }
}

async function setAlarm() {
  try {
      const res = await fetch("/api/alarm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: currentUser.id,
          date: selectedDate,
          time_slot: selectedSlot,
        }),
      });
      const data = await res.json();
      
      const modal = bootstrap.Modal.getInstance(document.getElementById("modalAlarm"));
      if(modal) modal.hide();
      
      alert(data.message);
      if (data.success) renderCalendar();
  } catch (e) {
      alert("Alarm kurulurken hata oluştu.");
  }
}

async function toggleMaintenance() {
  await fetch("/api/maintenance", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_id: currentUser.id,
      date: selectedDate,
      time_slot: selectedSlot,
    }),
  });
  renderCalendar();
}

// --- İLAN PANOSU ---
async function loadBoard() {
  try {
      const res = await fetch("/api/board");
      const posts = await res.json();
      const list = document.getElementById("board-list");
      list.innerHTML = "";
      posts.forEach((p) => {
        let delBtn =
          p.user_id == currentUser.id
            ? `<button onclick="deletePost(${p.id})" class="btn btn-sm btn-outline-danger float-end"><i class="fa-solid fa-trash"></i></button>`
            : "";

        list.innerHTML += `
          <div class="col-12">
              <div class="card bulletin-card p-3 shadow-sm">
                  <div class="mb-1">${delBtn} <h6 class="fw-bold d-inline">${p.title}</h6></div>
                  <p class="mb-2 text-dark small">${p.message}</p>
                  <div class="bulletin-info d-flex justify-content-between">
                      <span><i class="fa-solid fa-user"></i> ${p.first_name}</span>
                      <span><i class="fa-solid fa-phone"></i> ${p.contact_info}</span>
                  </div>
              </div>
          </div>
        `;
      });
  } catch (e) { console.log(e); }
}

async function addPost() {
  const payload = {
    user_id: currentUser.id,
    title: document.getElementById("post-title").value,
    message: document.getElementById("post-msg").value,
    contact: document.getElementById("post-contact").value,
  };
  await fetch("/api/board", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  document.getElementById("post-msg").value = "";
  loadBoard();
}

async function deletePost(id) {
  if (!confirm("İlanı silmek istiyor musunuz?")) return;
  await fetch(`/api/board?id=${id}`, { method: "DELETE" });
  loadBoard();
}

// --- BİLDİRİMLER ---
async function checkNotifications() {
  if (!currentUser) return;
  try {
    const res = await fetch(`/api/notifications?user_id=${currentUser.id}`);
    const alerts = await res.json();
    alerts.forEach((a) =>
      showToast(`MÜJDE! ${a.date} - ${a.slot} boşaldı!`)
    );
  } catch (e) {}
}

function showToast(msg) {
  const area = document.getElementById("notification-area");
  const toast = document.createElement("div");
  toast.className = "toast-custom";
  toast.innerHTML = `<i class="fa-solid fa-bell me-2"></i> ${msg}`;
  area.appendChild(toast);
  setTimeout(() => toast.remove(), 5000);
}