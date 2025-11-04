# Docker'da Sıfırdan Çalıştırma Rehberi

## Adım 1: Gerekli Dosyaları Hazırlama

### 1.1 Config Dosyasını Hazırlama
```bash
# Runtime config dosyasını kopyalayın ve düzenleyin
cp config/runtime.example.yml config/runtime.yml

# İçeriğini kendi ayarlarınıza göre düzenleyin
# Özellikle email ayarları, endpoint'ler ve session_store_path'i güncelleyin
```

### 1.2 Session Store Dosyasını Hazırlama
```bash
# Session store dosyasını kopyalayın
cp config/session_store.example.json config/session_store.json

# Kendi kullanıcı bilgilerinizle düzenleyin
# Özellikle credentials, profile ve preferences alanlarını güncelleyin
```

### 1.3 .env Dosyası Oluşturma (Opsiyonel)
```bash
# .env dosyasını örnek dosyadan kopyalayın (docker-compose.yml bunu kullanıyor)
cp .env.example .env

# .env dosyasını düzenleyip gerekli değerleri doldurun:
# - AGENTBOT_SESSION_KEY: Fernet encryption key (aşağıdaki komutla oluşturabilirsiniz)
# - BROWSERQL_TOKEN: Eğer BrowserQL kullanacaksanız
# - OPENAI_API_KEY: Eğer LLM kullanacaksanız
# - Diğer opsiyonel ayarlar
```

**Fernet Key Oluşturma:**
```bash
python3 - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
```

## Adım 2: Docker Build ve Çalıştırma

### 2.1 Docker Compose ile Çalıştırma (Önerilen)

```bash
# Tüm servisleri (Redis + API) başlat
docker-compose up --build

# Arka planda çalıştırmak için:
docker-compose up -d --build

# Logları görmek için:
docker-compose logs -f

# Sadece API servisinin loglarını görmek için:
docker-compose logs -f api
```

### 2.2 Sadece Docker Build (Manuel Çalıştırma İçin)

```bash
# Docker image'ı build et
docker build -t agentbot:latest .

# Redis'i başlat (gerekliyse)
docker run -d --name redis -p 6379:6379 redis:7-alpine

# Container'ı çalıştır
docker run -d \
  --name agentbot \
  -p 8000:8000 \
  -v $(pwd):/app \
  -e AGENTBOT_CONFIG=/app/config/runtime.example.yml \
  -e PYTHONPATH=/app/src \
  --env-file .env \
  --link redis:redis \
  agentbot:latest
```

## Adım 3: Servisleri Kontrol Etme

### 3.1 Container Durumunu Kontrol
```bash
# Tüm container'ları listele
docker-compose ps

# veya
docker ps
```

### 3.2 API'nin Çalıştığını Doğrulama
```bash
# Health check veya API endpoint'lerini test et
curl http://localhost:8000/docs  # FastAPI docs
curl http://localhost:8000/health  # Eğer health endpoint varsa
```

### 3.3 Redis Bağlantısını Kontrol
```bash
# Redis container'ına bağlan
docker-compose exec redis redis-cli ping
# Cevap: PONG olmalı
```

## Adım 4: Durdurma ve Temizleme

### 4.1 Servisleri Durdurma
```bash
# Container'ları durdur (veriler korunur)
docker-compose stop

# Container'ları durdur ve sil
docker-compose down

# Container'ları durdur, sil ve volume'ları da temizle
docker-compose down -v
```

### 4.2 Image'ı Yeniden Build Etme
```bash
# Cache olmadan yeniden build
docker-compose build --no-cache

# Sonra tekrar başlat
docker-compose up -d
```

## Adım 5: Logları İzleme

```bash
# Tüm servislerin logları
docker-compose logs -f

# Sadece API logları
docker-compose logs -f api

# Son 100 satır log
docker-compose logs --tail=100 api

# Container içine girip manuel kontrol
docker-compose exec api bash
```

## Adım 6: Sorun Giderme

### 6.1 Container Başlamıyorsa
```bash
# Logları kontrol et
docker-compose logs api

# Container içine gir
docker-compose exec api bash

# Python path'i kontrol et
docker-compose exec api python -c "import sys; print(sys.path)"
```

### 6.2 Config Dosyası Bulunamıyorsa
```bash
# Config dosyasının mount edildiğini kontrol et
docker-compose exec api ls -la /app/config/

# Config dosyasını düzenle
docker-compose exec api cat /app/config/runtime.yml
```

### 6.3 Redis Bağlantı Sorunu
```bash
# Redis'in çalıştığını kontrol et
docker-compose ps redis

# Redis'e bağlanmayı test et
docker-compose exec api python -c "import redis; r=redis.Redis(host='redis'); print(r.ping())"
```

## Hızlı Başlangıç (Özet)

```bash
# 1. Config dosyalarını hazırla
cp config/runtime.example.yml config/runtime.yml
cp config/session_store.example.json config/session_store.json

# 2. .env dosyası oluştur (opsiyonel)
cp .env.example .env
# .env dosyasını düzenleyip gerekli değerleri doldurun

# 3. Docker compose ile başlat
docker-compose up --build

# 4. Logları izle
docker-compose logs -f api

# 5. Durdurmak için
docker-compose down
```

## Notlar

- `docker-compose.yml` dosyasında `config/runtime.example.yml` kullanılıyor. Kendi config'inizi kullanmak için `AGENTBOT_CONFIG` environment variable'ını değiştirin veya docker-compose.yml'i düzenleyin.
- Volume mount (`./:/app`) sayesinde kod değişiklikleriniz otomatik olarak container'a yansır (development için).
- Production için volume mount kullanmayın, kodunuzu image içine kopyalayın.
- Redis verileri kalıcı olması için volume ekleyebilirsiniz (docker-compose.yml'e ekleyin).

