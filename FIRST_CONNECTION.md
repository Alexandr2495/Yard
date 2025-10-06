# Первое подключение к серверу

## Подключение по SSH

При первом подключении к серверу SSH покажет предупреждение о неизвестном ключе:

```
The authenticity of host '46.148.238.248 (46.148.238.248)' can't be established.
ED25519 key fingerprint is SHA256:TiD.......aXBmfiVMhIKL+ihDeTi4.
This key is not known by any other names
Are you sure you want to continue connecting (yes/no/[fingerprint])? 
```

**Введите `yes` и нажмите Enter** - это нормально для первого подключения.

## После подключения

1. **Обновите систему:**
```bash
apt update && apt upgrade -y
```

2. **Установите необходимые пакеты:**
```bash
apt install python3 python3-pip python3-venv postgresql postgresql-contrib git -y
```

3. **Запустите PostgreSQL:**
```bash
systemctl start postgresql
systemctl enable postgresql
```

4. **Клонируйте репозиторий:**
```bash
cd /root
git clone https://github.com/Alexandr2495/Yard.git Yard_bot
cd Yard_bot
```

5. **Создайте виртуальное окружение:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

6. **Настройте базу данных:**
```bash
sudo -u postgres psql
CREATE USER yardbot WITH PASSWORD 'your_strong_password';
CREATE DATABASE yardbot OWNER yardbot;
\q
```

7. **Создайте .env файл:**
```bash
nano .env
```

## Следующие шаги

После выполнения этих команд следуйте инструкциям из `SERVER_DEPLOYMENT.md` для полной настройки ботов.
