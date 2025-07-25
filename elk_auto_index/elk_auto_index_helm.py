from elasticsearch import Elasticsearch
from elasticsearch.exceptions import ConnectionError, AuthenticationException, TransportError, NotFoundError
import urllib3
import requests
import json
import os

# Отключаем предупреждения об отключении проверки сертификатов
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Настройки подключения к ES / Kibana
es_host = os.getenv('ES_HOST')
kibana_host = os.getenv('KIBANA_HOST')
username = os.getenv('USERNAME')
password = os.getenv('ELK_PASSWORD')

target_group_path = os.getenv('TARGET_GROUP_PATH').strip().strip('/')

if not password:
    print("Password not found in environment variables.")
    exit(1)

# Создаем клиент Elasticsearch
es = Elasticsearch(
    [es_host],
    basic_auth=(username, password),
    verify_certs=False
)

# Чтение common_name из ConfigMap
try:
    with open('/etc/config/common_name', 'r') as file:
        common_names = file.read().strip()
except Exception as e:
    print(f"Failed to read common_name from ConfigMap: {e}")
    common_names = ""

if not common_names:
    print('ConfigMap is empty, nothing to do.')
else:
    for name in common_names.split(','):
        common_name = name.strip()
        if not common_name:
            continue

        print(f"\n--- Processing common_name: {common_name} ---")

        # === 1. ПРОВЕРКА И СОЗДАНИЕ ILM POLICY ===
        try:
            ilm_policy_name = f'{common_name}-policy'
            try:
                es.ilm.get_lifecycle(name=ilm_policy_name)
                print(f"ILM policy '{ilm_policy_name}' exists.")
            except NotFoundError:
                print(f"ILM policy '{ilm_policy_name}' not found. Creating...")
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
                print(f"ILM policy '{ilm_policy_name}' created.")
        except Exception as e:
            print(f"Error handling ILM policy: {e}")

        # === 2. ПРОВЕРКА И СОЗДАНИЕ ШАБЛОНА ИНДЕКСА ===
        try:
            template_name = f"{common_name}-template"
            if es.indices.exists_index_template(template_name):
                print(f"Index template '{template_name}' already exists.")
            else:
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
                es.indices.put_index_template(name=template_name, body=index_template)
                print(f"Index template '{template_name}' created.")
        except Exception as e:
            print(f"Error creating index template: {e}")

        # === 3. СОЗДАНИЕ ПЕРВОГО ИНДЕКСА С АЛИАСОМ ===
        try:
            index_name = f"{common_name}-000001"
            alias_name = f"{common_name}_logs"
            if es.indices.exists(index=index_name):
                print(f"Index '{index_name}' already exists.")
            else:
                index_body = {
                    "aliases": {
                        alias_name: {
                            "is_write_index": True
                        }
                    }
                }
                es.indices.create(index=index_name, body=index_body)
                print(f"Index '{index_name}' created with write alias.")
        except Exception as e:
            print(f"Error creating initial index: {e}")

        # === 4. СОЗДАНИЕ DATA VIEW В KIBANA ===
        try:
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
            kibana_url = f"{kibana_host}/api/saved_objects/index-pattern/{common_name}"
            kibana_response = requests.post(
                kibana_url,
                auth=(username, password),
                headers=headers,
                data=json.dumps(data_view_payload),
                verify=False
            )

            if kibana_response.status_code in [200, 201]:
                print(f"Data View '{common_name}' created in Kibana.")
            else:
                print(f"Failed to create Data View: {kibana_response.status_code}, {kibana_response.text}")
        except Exception as e:
            print(f"Error creating Data View: {e}")

        # === 5. СОЗДАНИЕ РОЛЕЙ read и admin ===
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
                "privileges": ["read", "write", "create_index", "delete_index", "manage", "index", "create", "delete"],
                "kibana_features": [
                    "feature_discover.all",
                    "feature_visualize.all",
                    "feature_dashboard.all",
                    "feature_maps.all",
                    "feature_canvas.all"
                ],
                "kibana_spaces": ["space:default"]
            }
        }

        for role_type, config in ROLES_CONFIG.items():
            try:
                role_name = f"{target_group_path}{common_name}{role_type}"
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

                es.security.put_role(name=role_name, body=role_payload)
                print(f"Role '{role_name}' created or updated.")
            except Exception as e:
                print(f"Failed to create/update role '{role_name}': {e}")

        # === 6. ОБНОВЛЕНИЕ РОЛИ teamlead-viewer (только для read) ===
        try:
            role_name = "teamlead-viewer"
            try:
                role = es.security.get_role(name=role_name)
                current_role = role.get(role_name, {})
                indices = current_role.get("indices", [])
                pattern = f"{common_name}-*"

                # Проверяем, есть ли уже такой паттерн
                if any(pattern in index.get("names", []) for index in indices):
                    print(f"Role '{role_name}' already has access to '{pattern}'.")
                else:
                    indices.append({
                        "names": [pattern],
                        "privileges": ["read"]
                    })

                updated_payload = {
                    "cluster": current_role.get("cluster", []),
                    "indices": indices,
                    "applications": current_role.get("applications", []),
                    "run_as": current_role.get("run_as", []),
                    "metadata": current_role.get("metadata", {}),
                    "transient_metadata": current_role.get("transient_metadata", {"enabled": True})
                }

                es.security.put_role(name=role_name, body=updated_payload)
                print(f"Role '{role_name}' updated with access to '{pattern}'.")
            except NotFoundError:
                print(f"Role '{role_name}' does not exist. Skipping update.")
        except Exception as e:
            print(f"Error updating role '{role_name}': {e}")
