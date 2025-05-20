from elasticsearch import Elasticsearch
from elasticsearch.exceptions import ConnectionError, AuthenticationException, TransportError, NotFoundError
import urllib3
import requests
import json
import os

# Отключаем предупреждения об отключении проверки сертификатов
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Настройки подключения к es / kibana
es_host = "http://localhost:9200"  # Используйте https, если сервер настроен на SSL/TLS
kibana_host = "http://localhost:5601"  # Используйте https, если Kibana настроена на SSL/TLS
username = "elastic"  # Замените на ваше имя пользователя
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
            # Проверка, существует ли уже политика ILM
            ilm_policy_name = f'{common_name}-policy'
            try:
                es.ilm.get_lifecycle(name=ilm_policy_name)
                print(f"ILM policy '{ilm_policy_name}' exists.")
            except NotFoundError:
                print(f"ILM policy '{ilm_policy_name}' does not exist. Creating...")

                # Определяем политику жизненного цикла индекса
                lifecycle_policy = {
                    "policy": {
                        "phases": {
                            "hot": {
                                "min_age": "0ms",
                                "actions": {
                                    "rollover": {
                                        "max_age": "1d",
                                        "max_primary_shard_size": "3gb"
                                    },
                                    "set_priority": {
                                        "priority": 100
                                    }
                                }
                            },
                            "delete": {
                                "min_age": "14d",
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

            # Создаем или обновляем компонуемый шаблон индекса
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

            # Создаем индекс с параметром "is_write_index": true
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

            # Создаем Data View в Kibana
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

            # Создаем роль {common_name}-viewer с правами read
            role_payload = {
                "cluster": [],
                "indices": [
                    {
                        "names": [f"{common_name}-*"],
                        "privileges": ["read"]
                    }
                ],
                "applications": [
                {
                    "application": "kibana-.kibana",
                    "privileges": [
                    "feature_discover.read"
                    ],
                    "resources": [
                    "space:default"
                    ]
                }
                ],
                "run_as": [],
                "metadata": {},
                "transient_metadata": {
                "enabled": True
                }
            }

            es.security.put_role(name=f"{common_name}-viewer", body=role_payload)
            print(f"Role '{common_name}-viewer' was successfully created.")

            # Обновляем роль teamlead-viewer
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
