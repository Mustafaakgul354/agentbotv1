# 🔍 Login Debug Rehberi

Bu rehber, VFS Global login timeout hatalarını debug etmek için hazırlanmıştır.

## 🚀 Hızlı Test

Debug script'i çalıştırın (tarayıcı görünür modda açılır):

```bash
python scripts/debug_login.py
```

Bu script:
- ✅ Tarayıcıyı görünür modda açar (ne olduğunu görebilirsiniz)
- ✅ Her adımda screenshot alır
- ✅ Sayfa HTML'ini kaydeder
- ✅ Tüm input elementlerini listeler
- ✅ Detaylı log tutar

## 📸 Debug Artifacts

Script çalıştıktan sonra şu klasörde debug dosyalarını bulabilirsiniz:

```
artifacts/
└── vfs-fra-session-001/
    ├── 01-after-navigation.png      # İlk yükleme
    ├── 02-after-turnstile.png       # Cloudflare sonrası
    ├── 03-after-networkidle.png     # Tam yüklenme sonrası
    ├── 04-login-error.png           # Hata anı (varsa)
    └── page-content.html            # Sayfa HTML'i
```

## 🔍 Logları İnceleme

Script çalışırken terminalde şunları göreceksiniz:

```
[INFO] Current URL after navigation: https://...
[INFO] Checking for Cloudflare challenge...
[INFO] Waiting for page to fully load...
[INFO] Page reached networkidle state
[INFO] Page HTML saved to: artifacts/.../page-content.html
[INFO] Found 5 input elements on page
[INFO]   Input 0: type=email, id=Email, name=None, class=...
[INFO]   Input 1: type=password, id=Password, name=None, class=...
[INFO] Looking for login form elements...
[INFO] ✓ Login card found
```

## 🐛 Yaygın Sorunlar ve Çözümler

### 1. Timeout Hatası: "No email input found"

**Neden:** Sayfa yüklenmedi veya bot koruması aktif

**Çözüm:**
1. `artifacts/` klasöründeki screenshot'ları inceleyin
2. `page-content.html` dosyasını açıp sayfanın gerçek yapısını görün
3. Logları kontrol edin - kaç input bulundu?

### 2. Cloudflare Challenge

**Belirtiler:** 
- Screenshot'ta "Checking your browser" mesajı
- Sayfa sürekli yükleniyor

**Çözüm:**
- Headless mode'u kapatın (zaten kapalı debug script'te)
- Proxy kullanmayı deneyin
- BrowserQL hybrid mode'u aktif edin

### 3. Zaten Login Olmuş

**Belirtiler:**
- Log: "Already logged in, skipping login flow"
- URL'de `/dashboard` var

**Çözüm:**
- Bu normal! Bot zaten login olmuş
- Eğer test etmek istiyorsanız `.user_data/` klasörünü silin:
  ```bash
  rm -rf .user_data/vfs-fra-session-001
  ```

### 4. Sayfa Yapısı Değişmiş

**Belirtiler:**
- HTML'de Email input var ama ID farklı
- Selector'lar çalışmıyor

**Çözüm:**
1. `page-content.html` dosyasını inceleyin
2. Email input'un gerçek ID/class'ını bulun
3. `src/agentbot/site/vfs_fra_flow.py` dosyasındaki selector'ları güncelleyin:

```python
# VfsSelectors sınıfında:
email: str = "xpath=//input[@id='YeniID' and @type='email']"
```

## 🛠️ Manuel Test

Eğer script çalışmıyorsa, manuel olarak test edin:

```bash
# 1. Virtual environment'ı aktif edin
source .venv/bin/activate

# 2. Python REPL'i açın
python

# 3. Şu kodları çalıştırın:
from pathlib import Path
from agentbot.browser.play import BrowserFactory
import asyncio

async def test():
    browser = BrowserFactory(headless=False)
    async with browser.page("test-session") as page:
        await page.goto("https://visa.vfsglobal.com/tur/tr/fra/login")
        await asyncio.sleep(10)  # 10 saniye bekle
        print(f"URL: {page.url}")
        inputs = await page.query_selector_all("input")
        print(f"Found {len(inputs)} inputs")
        for i, inp in enumerate(inputs):
            print(f"  {i}: {await inp.get_attribute('id')}")

asyncio.run(test())
```

## 📊 Headless vs Görünür Mod

### Görünür Mod (Debug için)
```python
browser = BrowserFactory(headless=False)
```
- ✅ Ne olduğunu görebilirsiniz
- ✅ Manuel müdahale edebilirsiniz
- ❌ Daha yavaş

### Headless Mod (Production için)
```python
browser = BrowserFactory(headless=True)
```
- ✅ Daha hızlı
- ✅ Sunucuda çalışır
- ❌ Görsel debug yok

## 🔧 Gelişmiş Debug

### Playwright Inspector Kullanma

```bash
# Playwright inspector ile çalıştırın
PWDEBUG=1 python scripts/debug_login.py
```

Bu size:
- ✅ Adım adım debug
- ✅ Selector test etme
- ✅ Network isteklerini görme

### Verbose Logging

```bash
# Daha detaylı loglar için
export AGENTBOT_LOG_LEVEL=DEBUG
python scripts/debug_login.py
```

## 📞 Yardım

Hala sorun yaşıyorsanız:

1. ✅ `artifacts/` klasöründeki tüm dosyaları kontrol edin
2. ✅ Terminal loglarını kaydedin
3. ✅ Screenshot'ları inceleyin
4. ✅ `page-content.html` dosyasını açın

Bu bilgilerle sorununuzu daha kolay çözebilirsiniz!

