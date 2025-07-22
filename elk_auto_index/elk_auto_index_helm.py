from elasticsearch import Elasticsearch
from elasticsearch.exceptions import ConnectionError, AuthenticationException, TransportError, NotFoundError
import urllib3
import requests
import json
import os

# Отключаем предупреждения об отключении проверки сертификатов
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Настройки подключения к ES / Kibana
es_host = os.getenv('ES_HOST')  # Хост Elasticsearch из переменной окружения
kibana_host = os.getenv('KIBANA_HOST')  # Хост Kibana из переменной окружения
username = os.getenv('USERNAME')  # Имя пользователя из переменной окружения
password = os.getenv('ELK_PASSWORD')  # Пароль из переменной окружения

if password is None:
    print("Password not found in environment variables.")
    exit(1)

# Создаем клиент Elasticsearch с отключенной проверкой сертификатов
es = Elasticsearch(
    [es_host],
    basic_auth=(username, password),
    verify_certs=False  # Отключаем проверку сертификатов
)

# Чтение common_name из ConfigMap
with open('/etc/config/common_name', 'r') as file:
    common_names = file.read().strip()

if len(common_names) > 0:
    # Проверка и создание ILM
    for name in common_names.split(','):
        common_name = name.strip()

        try:
            # === ПОЛИТИКА ILM ===
            ilm_policy_name = f'{common_name}-policy'
            try:
                es.ilm.get_lifecycle(name=ilm_policy_name)
                print(f"ILM policy '{ilm_policy_name}' exists.")
            except NotFoundError:
                print(f"ILM policy '{ilm_policy_name}' does not exist. Creating...")

                lifecycle_policy = {
                    "policy": {
                        "phases": {
                            "hot": {
                                "min_age": "0ms",
                                "actions": {
                                    "rollover": {
                                        "max_age": "1d",
                                        "max_primary_shard_size": "1gb"
                                    },
                                    "set_priority": {
                                        "priority": 100
                                    }
                                }
                            },
                            "delete": {
                                "min_age": "30d",
                                "actions": {
                                    "delete": {
                                        "delete_searchable_snapshot": True
                                    }
                                }
                            }
                        }
                    }
                }

                es.ilm.put_lifecycle(name=ilm_policy_name, body=lifecycle_policy)
                print(f"Index Lifecycle Policy '{ilm_policy_name}' was successfully created.")

            # === ШАБЛОН ИНДЕКСА ===
            index_template = {
                "index_patterns": [f"{common_name}-*"],
                "template": {
                    "settings": {
                        "index": {
                            "lifecycle": {
                                "name": ilm_policy_name,
                                "rollover_alias": f"{common_name}_logs"
                            },
                            "number_of_shards": 3,
                            "number_of_replicas": 2,
                            "codec": "best_compression"
                        }
                    },
                },
                "priority": 100
            }

            es.indices.put_index_template(name=f"{common_name}-template", body=index_template)
            print(f"Index template '{common_name}-template' was successfully created.")

            # === СОЗДАНИЕ ИНДЕКСА С АЛИАСОМ is_write_index ===
            index_name = f"{common_name}-000001"
            index_body = {
                "aliases": {
                    f"{common_name}_logs": {
                        "is_write_index": True
                    }
                }
            }

            es.indices.create(index=index_name, body=index_body)
            print(f"Index '{index_name}' was successfully created with 'is_write_index': true.")

            # === СОЗДАНИЕ DATA VIEW В KIBANA ===
            data_view_payload = {
                "attributes": {
                    "name": common_name,
                    "title": f"{common_name}-*",
                    "timeFieldName": "timestamp"
                }
            }

            headers = {
                "Content-Type": "application/json",
                "kbn-xsrf": "true"
            }

            kibana_response = requests.post(
                f"{kibana_host}/api/saved_objects/index-pattern/{common_name}",
                auth=(username, password),
                headers=headers,
                data=json.dumps(data_view_payload),
                verify=False
            )

            if kibana_response.status_code in [200, 201]:
                print(f"Data View '{common_name}' was successfully created in Kibana.")
            else:
                print(f"Failed to create Data View in Kibana. Status code: {kibana_response.status_code}, Response: {kibana_response.text}")

            # === СОЗДАНИЕ РОЛЕЙ read и admin ===
            ROLES_CONFIG = {
                "read": {
                    "privileges": ["read"],
                    "kibana_features": [
                        "feature_discover.read",
                        "feature_visualize.read",
                        "feature_dashboard.read"
                    ],
                    "kibana_spaces": ["space:default"]
                },
                "admin": {
                    "privileges": [
                        "read", "write", "create_index", "delete_index", "manage", "index", "create", "delete"
                    ],
                    "kibana_features": [
                        "feature_discover.all",
                        "feature_visualize.all",
                        "feature_dashboard.all",
                        "feature_maps.all",
                        "feature_canvas.all"
                    ],
                    "kibana_spaces": ["space:default"]  # или ["*"], если нужно в любом space
                }
            }

            for role_type, config in ROLES_CONFIG.items():
                role_name = f"{common_name}{role_type}"
                role_payload = {
                    "cluster": [],
                    "indices": [
                        {
                            "names": [f"{common_name}-*"],
                            "privileges": config["privileges"]
                        }
                    ],
                    "applications": [
                        {
                            "application": "kibana-.kibana",
                            "privileges": config["kibana_features"],
                            "resources": ["space:default"]
                        }
                    ],
                    "run_as": [],
                    "metadata": {},
                    "transient_metadata": {"enabled": True}
                }

                try:
                    es.security.put_role(name=role_name, body=role_payload)
                    print(f"Role '{role_name}' was successfully created.")
                except Exception as e:
                    print(f"Failed to create role '{role_name}': {e}")

            # === ОБНОВЛЕНИЕ РОЛИ teamlead-viewer (только для read) ===
            try:
                teamlead_viewer_role = es.security.get_role(name="teamlead-viewer").get("teamlead-viewer", {})
                indices = teamlead_viewer_role.get("indices", [])
                indices.append({
                    "names": [f"{common_name}-*"],
                    "privileges": ["read"]
                })

                updated_role_payload = {
                    "cluster": teamlead_viewer_role.get("cluster", []),
                    "indices": indices,
                    "applications": teamlead_viewer_role.get("applications", []),
                    "run_as": teamlead_viewer_role.get("run_as", []),
                    "metadata": teamlead_viewer_role.get("metadata", {}),
                    "transient_metadata": teamlead_viewer_role.get("transient_metadata", {"enabled": True})
                }

                es.security.put_role(name="teamlead-viewer", body=updated_role_payload)
                print(f"Role 'teamlead-viewer' was successfully updated with permissions for '{common_name}-*'.")
            except NotFoundError:
                print("Role 'teamlead-viewer' does not exist.")

        except Exception as e:
            print(f"An unexpected error occurred: {e}")
else:
    print('ConfigMap is empty, nothing to do.')
