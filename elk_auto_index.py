from elasticsearch import Elasticsearch
from elasticsearch.exceptions import ConnectionError, AuthenticationException, TransportError
import urllib3
import requests
import json
import getpass

# Отключаем предупреждения об отключении проверки сертификатов
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Настройки подключения к es / kibana
es_host = "https://localhost:9200"  # Используйте https, если сервер настроен на SSL/TLS
kibana_host = "http://localhost:5601"  # Используйте https, если Kibana настроена на SSL/TLS
username = "elastic"  # Замените на ваше имя пользователя
password = getpass.getpass("Введи пароль: ")  # Введите пароль

# Создаем клиент Elasticsearch с отключенной проверкой сертификатов
es = Elasticsearch(
    [es_host],
    basic_auth=(username, password),
    verify_certs=False  # Отключаем проверку сертификатов
)

# Общая переменная для имени политики и шаблона (одним словом или через "-")
common_name = input("Введи имя приложения(одним словом или через '-'): ")

try:
    # # Выполняем запрос для получения информации о кластере
    # info = es.info()
    # print("Connected to Elasticsearch cluster:")
    # print(info)

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

    # Создаем или обновляем политику ILM
    ilm_response = es.ilm.put_lifecycle(
        name=f"{common_name}-policy",
        body=lifecycle_policy
    )

    # Проверяем успешность выполнения запроса для ILM
    if ilm_response.get('acknowledged', False):
        print(f"Index Lifecycle Policy '{common_name}-policy' was successfully created.")
    else:
        print(f"Failed to create Index Lifecycle Policy.")

    # Определяем компонуемый шаблон индекса
    index_template = {
        "index_patterns": [f"{common_name}-*"],  # Шаблон для совпадения с именами индексов
        "template": {  # Структура для компонуемого шаблона
            "settings": {
                "index": {
                    "lifecycle": {
                        "name": f"{common_name}-policy",  # Название политики жизненного цикла
                        "rollover_alias": f"{common_name}_logs"  # Алиас для использования с rollover
                    },
                    "number_of_shards": 3,
                    "number_of_replicas": 2,
                    "codec": "best_compression"
                }
            },
        },
        "priority": 100
    }

    # Создаем или обновляем компонуемый шаблон индекса
    template_response = es.indices.put_index_template(
        name=f"{common_name}-template",
        body=index_template
    )

    # Проверяем успешность выполнения запроса для шаблона
    if template_response.get('acknowledged', False):
        print(f"Index template '{common_name}-template' was successfully created.")
    else:
        print(f"Failed to create index template.")

    # Создаем индекс с параметром "is_write_index": true
    index_name = f"{common_name}-000001"
    index_body = {
        "aliases": {
            f"{common_name}_logs": {
                "is_write_index": True
            }
        }
    }

    index_response = es.indices.create(index=index_name, body=index_body)

    # Проверяем успешность создания индекса
    if index_response.get('acknowledged', False):
        print(f"Index '{index_name}' was successfully created with 'is_write_index': true.")
    else:
        print(f"Failed to create index '{index_name}'.")

    # Создаем Data View в Kibana
    data_view_payload = {
        "attributes": {
            "name": common_name,  # Имя Data View
            "title": f"{common_name}-*",  # Шаблон индекса
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
        verify=False  # Отключаем проверку сертификатов
    )

    # Проверяем успешность создания Data View
    if kibana_response.status_code in [200, 201]:
        print(f"Data View '{common_name}' was successfully created in Kibana.")
    else:
        print(f"Failed to create Data View in Kibana. Status code: {kibana_response.status_code}, Response: {kibana_response.text}")

except AuthenticationException as auth_err:
    print(f"Authentication failed: {auth_err}")

except ConnectionError as conn_err:
    print(f"Failed to connect to Elasticsearch: {conn_err}")

except TransportError as transport_err:
    print(f"Transport error: {transport_err}")

except Exception as e:
    print(f"An unexpected error occurred: {e}")
