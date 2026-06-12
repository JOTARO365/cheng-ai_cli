# SME IT Agent — Project Prompt

## ภาพรวมโปรเจค

สร้างระบบ **AI IT Agent แบบ CLI** สำหรับบริษัท SME และองค์กรขนาดเล็กที่มีทีม IT จำกัด (1-3 คน) โดยใช้ **Local AI (Ollama)** ทั้งหมด ข้อมูลไม่ออกนอกบริษัท

ระบบทำหน้าที่เป็น "ผู้ช่วย IT อัจฉริยะ" ที่ **monitor, วิเคราะห์ และแจ้งเตือนปัญหา** ก่อนที่ user จะโทรมาหา IT

---

## โจทย์หลัก

IT 1-2 คนต้องดูแลระบบของบริษัท 30-200 คน โดยไม่มีเครื่องมือ monitoring ที่ดีพอ ส่งผลให้รู้ปัญหาช้า แก้ไขไม่ทันก่อน user ได้รับผลกระทบ

ระบบนี้จะเปลี่ยนการทำงานจาก **Reactive → Proactive**

---

## Infrastructure Target

- **Windows AD / Domain** เป็นหลัก
- On-premise network
- IT PC หรือ Windows Server สำหรับรัน agent

---

## Core Features (Phase 1)

### 1. Collector Layer
- อ่าน Windows Event Log (Event ID 4625 = login fail, 4740 = account lockout)
- Ping check ทุก node ใน network ทุก 30-60 วินาที
- WMI/WinRM query สถานะ PC และ service สำคัญ
- LDAP query ข้อมูล user จาก AD

### 2. Harness / Rule Engine
กรอง event ก่อนส่ง AI เพื่อประหยัด resource:
- Login fail 1-2 ครั้ง → บันทึก log เฉยๆ
- Login fail 3+ ครั้ง → ส่ง AI วิเคราะห์ pattern
- Login fail 5+ ครั้ง → alert IT ทันที (ไม่รอ AI)
- Node offline < 2 นาที → รอดูก่อน
- Node offline > 5 นาที ช่วงเวลางาน → alert IT
- Service down → alert ทันที + ส่ง AI ประเมิน impact

### 3. Local AI Brain (Ollama)
- Model แนะนำ: `qwen2.5:14b` หรือ `llama3.1:8b`
- ทำงาน offline 100%, ข้อมูลไม่ออกนอกบริษัท
- วิเคราะห์ root cause จาก pattern event
- ตอบคำถาม IT admin ใน context ปัจจุบัน

### 4. Chat-style CLI
IT admin พิมพ์คุยกับ AI ได้เป็นธรรมชาติ เช่น:
```
IT> สถานะระบบตอนนี้เป็นยังไง
IT> john lock อยู่ไหม
IT> PC ไหนปิดอยู่บ้าง
IT> login fail วันนี้มีกี่ครั้ง
```

### 5. Alert Engine
- แจ้งเตือนผ่าน Line Notify, Microsoft Teams Webhook หรือ Email
- IT รู้ปัญหาก่อน user ในหลายกรณี
- Alert มี context ครบ: ใคร, เวลาไหน, กี่ครั้ง, IP อะไร

---

## Tech Stack

| ชั้น | เครื่องมือ |
|---|---|
| Local LLM | Ollama + qwen2.5:14b / llama3.1:8b |
| AD/Event | pywin32, ldap3, wmi |
| CLI UI | rich, prompt_toolkit |
| Storage | SQLite (ไม่ต้อง install เพิ่ม) |
| Alert | requests → Line Notify / Teams |
| Language | Python 3.11+ |

---

## IT PC Spec ขั้นต่ำ

- RAM: 16GB (แนะนำ 32GB)
- Storage: SSD มีพื้นที่ว่าง 20GB+
- GPU: ไม่จำเป็น (รัน CPU mode ได้, ช้ากว่าแต่ใช้งานได้)
- OS: Windows 10/11 หรือ Windows Server

---

## สิ่งที่ระบบนี้ไม่ทำ (Phase 1)

- ไม่ auto-fix ใดๆ ทั้งสิ้น (แค่ monitor + alert)
- ไม่เชื่อมต่อ internet
- ไม่ส่งข้อมูลออกนอกบริษัท
- ไม่รองรับ Cloud AD (Azure AD) ใน phase นี้

---

## ผลลัพธ์ที่คาดหวัง

IT 1 คนสามารถดูแลระบบของบริษัท 50-150 คน ได้อย่างมีประสิทธิภาพ
เปรียบเหมือนมี IT ผู้ช่วยที่ตื่นตัว 24 ชั่วโมง คอย watch ระบบแทน

---

## Phase Plan

**Phase 1 (MVP ~2 สัปดาห์)**
Collector + Rule Engine + Chat CLI + Alert พื้นฐาน

**Phase 2**
ServiceWatcher + Dashboard summary + Alert ครบช่องทาง

**Phase 3**
Auto-remediation บางอย่าง (unlock account หลัง IT confirm ใน chat)

**Phase 4 (Product)**
Installer, multi-site support, web dashboard สำหรับขายเป็น SaaS
