import requests
import json
import urllib3
import os

urllib3.disable_warnings()

KEYCLOAK_URL = os.getenv("KEYCLOAK_URL")
REALM = os.getenv("REALM")
CLIENT_ID = os.getenv("CLIENT_ID")
ADMIN_USER = os.getenv("ADMIN_USER")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")

ES_URL = os.getenv("ES_URL")
ES_USER = os.getenv("ES_USER")
ES_PASSWORD = os.getenv("ES_PASSWORD")

TARGET_GROUP_PATH = os.getenv("TARGET_GROUP_PATH")

# Получение токена администратора Keycloak
def get_kc_admin_token():
    url = f"{KEYCLOAK_URL}/realms/master/protocol/openid-connect/token"
    data = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'username': ADMIN_USER,
        'password': ADMIN_PASSWORD,
        'grant_type': 'password'
    }

    try:
        response = requests.post(url, data=data, verify=False)
        response.raise_for_status()
        return response.json()['access_token']
    except requests.exceptions.RequestException as e:
        print("[ERROR] Не удалось получить токен Keycloak:", str(e))
        if response.text:
            print("Ответ сервера:", response.text)
        exit(1)


# Получение всех групп из Keycloak
def get_groups(token, realm=None, parent_id=None):
    if realm is None:
        realm = REALM

    headers = {'Authorization': f'Bearer {token}'}

    if parent_id:
        url = f"{KEYCLOAK_URL}/admin/realms/{realm}/groups/{parent_id}/children"
    else:
        url = f"{KEYCLOAK_URL}/admin/realms/{realm}/groups"

    try:
        response = requests.get(url, headers=headers, verify=False)
        response.raise_for_status()
        groups = response.json()

        all_groups = []
        for group in groups:
            all_groups.append(group)
            # Рекурсивно получаем подгруппы
            subgroups = get_groups(token, realm, group['id'])
            if subgroups:
                all_groups.extend(subgroups)

        return all_groups

    except requests.exceptions.RequestException as e:
        print("[ERROR] Ошибка при получении групп:", str(e))
        if response.text:
            print("Ответ сервера:", response.text)
        return []


# Рекурсивный обход групп и подгрупп
def walk_groups(groups):
    result = []
    for group in groups:
        if isinstance(group, dict):
            path = group.get('path')
            if path:
                result.append(path)
    return result


# Создание Role Mapping в Elasticsearch
def create_role_mapping(group_path):
    group_name = group_path.split("/")[-1]  # получаем 'test' из '/kibana/test'
    role_name = f"{group_name}-viewer"
    mapping_name = role_name  # или можно сделать mapping_{group_name}

    es_mapping_url = f"{ES_URL}/_security/role_mapping/{mapping_name}"

    mapping_body = {
        "roles": [role_name],
        "enabled": True,
        "rules": {
            "all": [
                {"field": {"realm.name": REALM}},
                {"field": {"groups": group_path}}
            ]
        }
    }

    print(f"\n[INFO] Создаю маппинг '{mapping_name}' для группы '{group_path}' → роль '{role_name}'")
    print(f"URL: {es_mapping_url}")
    print(f"Тело запроса:\n{json.dumps(mapping_body, indent=2)}")

    try:
        response = requests.put(
            es_mapping_url,
            auth=(ES_USER, ES_PASSWORD),
            headers={"Content-Type": "application/json"},
            data=json.dumps(mapping_body),
            verify=False
        )

        print(f"[INFO] Статус код: {response.status_code}")
        print(f"[INFO] Ответ: {response.text}")

        if response.status_code in (200, 201):
            print(f"[SUCCESS] Маппинг '{mapping_name}' успешно создан.")
        else:
            print(f"[ERROR] Не удалось создать маппинг '{mapping_name}'.")
    except Exception as e:
        print("[ERROR] Исключение при отправке запроса:", str(e))


# Основная функция
def main():
    token = get_kc_admin_token()
    groups = get_groups(token)
    all_group_paths = walk_groups(groups)

    print("\n[INFO] Все найденные пути групп:")
    for path in all_group_paths:
        print(f" - {path}")

    # Фильтруем только те, что начинаются с /kibana/
    filtered_groups = [path for path in all_group_paths if path.startswith(TARGET_GROUP_PATH)]

    for group_path in filtered_groups:
        create_role_mapping(group_path)


if __name__ == "__main__":
    main()
