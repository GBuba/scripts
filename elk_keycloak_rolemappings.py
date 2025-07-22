import requests
import json
import urllib3
import os

# Отключаем предупреждения о небезопасном SSL (если используется self-signed)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# === Загрузка переменных окружения ===
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL")
REALM = os.getenv("REALM")
CLIENT_ID = os.getenv("CLIENT_ID")
ADMIN_USER = os.getenv("ADMIN_USER")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")

ES_URL = os.getenv("ES_URL")
ES_USER = os.getenv("ES_USER")
ES_PASSWORD = os.getenv("ES_PASSWORD")

TARGET_GROUP_PATH = os.getenv("TARGET_GROUP_PATH")  # Например: /kibana

# Читаем суффиксы из ROLE_SUFFIXE, разбиваем и очищаем от пробелов
ROLE_SUFFIXES = [suffix.strip() for suffix in os.getenv("ROLE_SUFFIX").split(",")]


# === Получение админ-токена Keycloak ===
def get_kc_admin_token():
    url = f"{KEYCLOAK_URL}/realms/master/protocol/openid-connect/token"
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "username": ADMIN_USER,
        "password": ADMIN_PASSWORD,
        "grant_type": "password",
    }
    try:
        response = requests.post(url, data=data, verify=False)
        response.raise_for_status()
        return response.json()["access_token"]
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Не удалось получить токен Keycloak: {e}")
        if response.text:
            print(f"Ответ сервера: {response.text}")
        exit(1)


# === Рекурсивное получение всех групп ===
def get_all_groups(token):
    url = f"{KEYCLOAK_URL}/admin/realms/{REALM}/groups"
    headers = {"Authorization": f"Bearer {token}"}

    def fetch_children(group_id, headers):
        try:
            response = requests.get(
                f"{url}/{group_id}/children",
                headers=headers,
                verify=False
            )
            response.raise_for_status()
            groups = response.json()
            all_groups = []
            for group in groups:
                all_groups.append(group)
                # Рекурсивно получаем дочерние группы
                children = fetch_children(group['id'], headers)
                if children:
                    all_groups.extend(children)
            return all_groups
        except Exception as e:
            print(f"[ERROR] Ошибка при получении подгрупп: {e}")
            return []

    # Сначала получаем корневые группы
    root_groups = requests.get(url, headers=headers, verify=False).json()

    # Запускаем рекурсивный сбор всех групп
    all_groups = []
    for group in root_groups:
        all_groups.append(group)
        children = fetch_children(group['id'], headers)
        if children:
            all_groups.extend(children)

    return all_groups


# === Создание/обновление role_mapping в Elasticsearch ===
def create_role_mapping(group_path, role_name):
    mapping_name = role_name  # имя маппинга = имя роли
    url = f"{ES_URL}/_security/role_mapping/{mapping_name}"

    body = {
        "roles": [role_name],
        "enabled": True,
        "rules": {
            "all": [
                {"field": {"realm.name": REALM}},
                {"field": {"groups": group_path}}
            ]
        }
    }

    print(f"\n[INFO] Создаю маппинг: '{mapping_name}' для группы '{group_path}'")
    print(f"Тело запроса:\n{json.dumps(body, indent=2)}")

    try:
        response = requests.put(
            url,
            auth=(ES_USER, ES_PASSWORD),
            headers={"Content-Type": "application/json"},
            json=body,
            verify=False,
        )
        print(f"[INFO] Статус: {response.status_code}, Ответ: {response.text}")

        if response.status_code in (200, 201):
            print(f"[SUCCESS] Маппинг '{mapping_name}' успешно создан.")
        else:
            print(f"[ERROR] Не удалось создать маппинг.")
    except Exception as e:
        print(f"[ERROR] Исключение при вызове Elasticsearch: {e}")


# === Основная логика ===
def main():
    print("[INFO] Запуск синхронизации маппингов ролей...")

    # Шаг 1: Получаем токен
    token = get_kc_admin_token()

    # Шаг 2: Получаем все группы
    groups = get_all_groups(token)
    group_paths = [g["path"] for g in groups if g.get("path")]

    print(f"[INFO] Найдено {len(group_paths)} групп:")
    for path in group_paths:
        print(f" - {path}")

    # Фильтруем по базовому префиксу (например, /kibana)
    filtered_paths = [p for p in group_paths if p.startswith(TARGET_GROUP_PATH)]
    print(f"[INFO] После фильтрации по {TARGET_GROUP_PATH}: {len(filtered_paths)}")

    # Ищем группы, заканчивающиеся на нужный суффикс
    mappings_to_create = []
    for path in filtered_paths:
        group_name = path.split("/")[-1]  # например: subgroupAadmin
        if any(group_name.endswith(suffix) for suffix in ROLE_SUFFIXES):
            mappings_to_create.append({
                "path": path,
                "role": group_name
            })

    print(f"[INFO] Подходящих групп для маппинга: {len(mappings_to_create)}")
    for item in mappings_to_create:
        create_role_mapping(item["path"], item["role"])


if __name__ == "__main__":
    main()
