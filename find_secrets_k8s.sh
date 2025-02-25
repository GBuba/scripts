#!/bin/bash

# Скрипт для поиска использования секретов в Kubernetes

# Функция для поиска секретов в переменных окружения
find_secrets_in_env() {
  echo "Поиск секретов в переменных окружения..."
  kubectl get pods,deployments,statefulsets,daemonsets,cronjobs,jobs --all-namespaces -o json | \
  jq -r '.items[] | .spec.containers[]? | .env? // empty | .[] | select(.valueFrom.secretKeyRef?) | .valueFrom.secretKeyRef.name' | \
  sort | uniq
}

# Функция для поиска секретов в томах
find_secrets_in_volumes() {
  echo "Поиск секретов в томах..."
  kubectl get pods,deployments,statefulsets,daemonsets,cronjobs,jobs --all-namespaces -o json | \
  jq -r '.items[] | .spec.volumes[]? | select(.secret?) | .secret.secretName' | \
  sort | uniq
}

# Запуск функций
find_secrets_in_env
find_secrets_in_volumes
