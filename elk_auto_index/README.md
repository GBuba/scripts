Скрипт берет common_name из ConfigMap, проверяет с тем, что уже созданно и если находит новое значение, создает:

    ilm policy (на этом щаге происходит проверка уже имеющихся ilm),
    index template,
    index, вида ({common_name}-000001) с параметром "is_write_index": true,
    Discover -> Create a data view {common_name},
    Создаем роль {group}{common_name}read/admin,
    Обновляем роль teamlead-viewer (добавляет права на просмотр нового индекса).

Отрабатывает в 00:00, если нужно срочно:

    kubectl -n kibana create job --from=cronjob.batch/elk-auto-index-py elk-auto-index-py-manual

***Скрипт крутится в k8s, для удобства администрирования вынесен в Helm Chart***

Как пользоваться?
 
    При новом развертывании в values.yaml через ',' добавить необходимые имена.
    При добавлении нового индекса в уже развернутом Helm можно просто поправить ConfigMap (kubectl -n kibana edit configmaps elk-config)
