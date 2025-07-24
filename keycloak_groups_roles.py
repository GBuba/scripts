import requests
import json
import urllib3
import os

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

KEYCLOAK_URL = os.getenv("KEYCLOAK_URL")
MASTER_REALM = os.getenv("MASTER_REALM")
ADMIN_USER = os.getenv("ADMIN_USER")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD") 
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")  

NEW_REALM = os.getenv("NEW_REALM")
GROUPS_TO_CREATE = os.getenv("GROUPS_TO_CREATE").split()
SUBGROUPS = os.getenv("SUBGROUPS").split()
ROLE_SUFFIX = os.getenv("ROLE_SUFFIX") # роль будет {group_name}{subgroup}{suffix}


# Получение токена администратора
def get_admin_token():
    token_url = f"{KEYCLOAK_URL}/realms/{MASTER_REALM}/protocol/openid-connect/token"
    data = {
        "username": ADMIN_USER,
        "password": ADMIN_PASSWORD,
        "grant_type": "password",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }
    response = requests.post(token_url, data=data, verify=False)
    response.raise_for_status()
    return response.json()["access_token"]


# Создание нового реалма
def create_realm(token):
    url = f"{KEYCLOAK_URL}/admin/realms/{NEW_REALM}"
    headers = {
        "Authorization": f"Bearer {token}"
    }

    # Проверяем, существует ли реалм
    response = requests.get(url, headers=headers, verify=False)

    if response.status_code == 200:
        print(f"Реалм '{NEW_REALM}' уже существует.")
        return
    elif response.status_code != 404:
        # Если ошибка не "не найден", выбрасываем исключение
        response.raise_for_status()

    # Реалм не найден — создаём его
    url_create = f"{KEYCLOAK_URL}/admin/realms"
    payload = {
        "realm": NEW_REALM,
        "enabled": True
    }
    create_response = requests.post(url_create, headers={**headers, "Content-Type": "application/json"},
                                    json=payload, verify=False)
    create_response.raise_for_status()
    print(f"Реалм '{NEW_REALM}' успешно создан.")


# Получение ID реалма по имени
def get_realm_id(token, realm_name):
    url = f"{KEYCLOAK_URL}/admin/realms"
    headers = {
        "Authorization": f"Bearer {token}"
    }
    response = requests.get(url, headers=headers, verify=False)
    response.raise_for_status()
    realms = response.json()
    for r in realms:
        if r["realm"] == realm_name:
            return r["id"]
    raise Exception(f"Realm {realm_name} не найден")


# Создание группы
def create_group(token, realm, parent_group_id, group_name, parent_path=""):
    url = f"{KEYCLOAK_URL}/admin/realms/{realm}/groups"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    if parent_group_id:
        url += f"/{parent_group_id}/children"

    payload = {
        "name": group_name
    }

    response = requests.post(url, headers=headers, data=json.dumps(payload), verify=False)
    if response.status_code == 409:
        print(f"Группа '{group_name}' уже существует в '{parent_path}'.")
        # Получаем существующую группу, чтобы получить её ID
        groups = get_groups(token, realm, parent_group_id)
        for g in groups:
            if g["name"] == group_name:
                return g["id"]
    else:
        response.raise_for_status()
        print(f"Создана группа '{group_name}' в '{parent_path}'.")
    
    location = response.headers.get("Location")
    group_id = location.split("/")[-1]
    return group_id


# Получение списка групп
def get_groups(token, realm, parent_group_id=None):
    url = f"{KEYCLOAK_URL}/admin/realms/{realm}/groups"
    if parent_group_id:
        url += f"/{parent_group_id}/children"
    headers = {
        "Authorization": f"Bearer {token}"
    }
    response = requests.get(url, headers=headers, verify=False)
    response.raise_for_status()
    return response.json()


# Создание роли
def create_role(token, realm, role_name):
    url = f"{KEYCLOAK_URL}/admin/realms/{realm}/roles"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "name": role_name
    }
    response = requests.post(url, headers=headers, data=json.dumps(payload), verify=False)
    if response.status_code == 409:
        print(f"Роль '{role_name}' уже существует.")
    else:
        response.raise_for_status()
        print(f"Создана роль '{role_name}'.")


# Назначение роли на группу
def assign_role_to_group(token, realm, group_id, role_name):
    url = f"{KEYCLOAK_URL}/admin/realms/{realm}/groups/{group_id}/role-mappings/realm"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # Получаем ID роли
    roles_url = f"{KEYCLOAK_URL}/admin/realms/{realm}/roles"
    response = requests.get(roles_url, headers=headers, verify=False)
    response.raise_for_status()
    roles = response.json()
    role = next((r for r in roles if r["name"] == role_name), None)
    if not role:
        raise Exception(f"Роль '{role_name}' не найдена")

    payload = [{"id": role["id"], "name": role["name"]}]

    response = requests.post(url, headers=headers, data=json.dumps(payload), verify=False)
    response.raise_for_status()
    print(f"Роль '{role_name}' назначена на группу.")


def main():
    token = get_admin_token()

    create_realm(token)

    # Парсим ROLE_SUFFIX как список (чтобы можно было передать несколько ролей через запятую)
    role_suffixes = [suffix.strip() for suffix in ROLE_SUFFIX.split(",")]

    for group_name in GROUPS_TO_CREATE:
        # Создаём основную группу
        group_id = create_group(token, NEW_REALM, None, group_name)
        for subgroup in SUBGROUPS:
            # Создаём подгруппу
            subgroup_id = create_group(token, NEW_REALM, group_id, subgroup, parent_path=group_name)
            for suffix in role_suffixes:
                # Формируем общее имя с префиксом group_name
                role_key = f"{group_name}{subgroup}{suffix}"

                # Создаём подгруппу с именем {group_name}{subgroup}{suffix}
                role_group_id = create_group(
                    token,
                    NEW_REALM,
                    subgroup_id,
                    role_key,
                    parent_path=f"{group_name}/{subgroup}"
                )

                # Создаём роль с тем же именем
                create_role(token, NEW_REALM, role_key)

                # Назначаем роль на группу
                assign_role_to_group(token, NEW_REALM, role_group_id, role_key)

if __name__ == "__main__":
    main()
